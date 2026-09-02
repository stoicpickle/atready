from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import atready.cli as cli
from atready.catalog import InventoryCatalog
from atready.cli import main
from atready.models import CapacityDemand, ProjectBrief, Workstream
from atready.routing import route
from atready.yamlio import dumps_yaml

FIXTURES = Path(__file__).parents[1] / "evals" / "fixtures"
EVALUATED_AT = datetime(2026, 8, 6, 12, 30, tzinfo=UTC)


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        assert tz is None
        return cls(2026, 8, 6, 5, 30, tzinfo=timezone(-timedelta(hours=7)))

    def astimezone(self, tz=None):
        if tz is None:
            return self
        return super().astimezone(tz)


@pytest.fixture(autouse=True)
def _freeze_cli_evaluation_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "datetime", _FixedDateTime)


def _state_snapshot(
    resource_id: str = "codex",
    *,
    session: str | None = "unavailable",
    quota: str | None = "exhausted",
    observed_at: str = "2026-08-06T12:00:00Z",
    valid_until: str = "2026-08-06T13:00:00Z",
    capacity: dict[str, object] | None = None,
) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "resource_id": resource_id,
        "observed_at": observed_at,
        "source": "synthetic-collector",
        "source_kind": "adapter",
        "mode": "live",
        "confidence": "observed",
        "valid_until": valid_until,
    }
    if session is not None:
        snapshot["session"] = session
    if quota is not None:
        snapshot["quota"] = quota
    if capacity is not None:
        snapshot["capacity"] = capacity
    return snapshot


def _write_state(
    path: Path,
    snapshots: list[dict[str, object]],
    *,
    json_input: bool = True,
) -> None:
    value = {"schema_version": 1, "snapshots": snapshots}
    path.write_text(
        json.dumps(value) if json_input else dumps_yaml(value),
        encoding="utf-8",
    )


@pytest.mark.parametrize("json_input", [True, False], ids=["json", "yaml"])
def test_route_state_overlay_changes_eligibility_emits_provenance_and_never_writes_roster(
    tmp_path: Path,
    capsys,
    json_input: bool,
) -> None:
    inventory = tmp_path / "inventory.yaml"
    inventory.write_bytes((FIXTURES / "inventory.yaml").read_bytes())
    before = inventory.read_bytes()
    state = tmp_path / ("state.json" if json_input else "state.yaml")
    _write_state(state, [_state_snapshot()], json_input=json_input)

    assert (
        main(
            [
                "route",
                "--project",
                str(FIXTURES / "project-godot.yaml"),
                "--inventory",
                str(inventory),
                "--resource-state",
                str(state),
                "--allow-demo",
                "--format",
                "json",
            ]
        )
        == 3
    )
    plan = json.loads(capsys.readouterr().out)

    assert plan["resource_state_fingerprint"].startswith("sha256:")
    assert plan["resource_state_evaluated_at"] == "2026-08-06T05:30:00-07:00"
    assert plan["resource_state_sources"] == ["synthetic-collector"]
    assert plan["resource_state_resources"] == ["codex"]
    assert any("temporary state applied" in warning for warning in plan["warnings"])
    codex_candidates = [
        candidate
        for assignment in plan["assignments"]
        for candidate in assignment["candidates"]
        if candidate["resource_id"] == "codex"
    ]
    assert codex_candidates
    assert any("session-unavailable" in candidate["gate_codes"] for candidate in codex_candidates)
    assert any("quota-exhausted" in candidate["gate_codes"] for candidate in codex_candidates)
    assert inventory.read_bytes() == before


def test_route_without_overlay_is_stable_and_state_metadata_is_absent(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    inventory.write_bytes((FIXTURES / "inventory.yaml").read_bytes())
    args = [
        "route",
        "--project",
        str(FIXTURES / "project-godot.yaml"),
        "--inventory",
        str(inventory),
        "--allow-demo",
        "--format",
        "json",
    ]

    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert main(args) == 0
    second = json.loads(capsys.readouterr().out)

    assert second == first
    assert "resource_state_fingerprint" not in first
    assert "resource_state_evaluated_at" not in first
    assert "resource_state_sources" not in first
    assert "resource_state_resources" not in first


@pytest.mark.parametrize(
    ("snapshots", "needle"),
    [
        ([_state_snapshot(resource_id="not-in-roster")], "absent from the selected inventory"),
        (
            [
                _state_snapshot(
                    observed_at="2026-08-05T12:00:00Z",
                    valid_until="2026-08-05T13:00:00Z",
                )
            ],
            "no longer valid at evaluated_at",
        ),
    ],
    ids=["unknown-id", "expired"],
)
def test_route_rejects_unknown_or_expired_state_with_exit_two(
    tmp_path: Path,
    capsys,
    snapshots: list[dict[str, object]],
    needle: str,
) -> None:
    state = tmp_path / "state.json"
    _write_state(state, snapshots)

    result = main(
        [
            "route",
            "--project",
            str(FIXTURES / "project-godot.yaml"),
            "--inventory",
            str(FIXTURES / "inventory.yaml"),
            "--resource-state",
            str(state),
            "--allow-demo",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert needle in captured.err
    assert captured.out == ""


def test_route_rejects_symlinked_state_file_with_exit_two(tmp_path: Path, capsys) -> None:
    target = tmp_path / "real-state.json"
    _write_state(target, [_state_snapshot()])
    state = tmp_path / "state-link.json"
    os.symlink(target, state)

    result = main(
        [
            "route",
            "--project",
            str(FIXTURES / "project-godot.yaml"),
            "--inventory",
            str(FIXTURES / "inventory.yaml"),
            "--resource-state",
            str(state),
            "--allow-demo",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "symlinked configuration" in captured.err
    assert captured.out == ""


def test_valid_state_does_not_hide_an_ordinary_route_gap(tmp_path: Path, capsys) -> None:
    state = tmp_path / "state.json"
    _write_state(
        state,
        [
            _state_snapshot(
                resource_id="verifier-b",
                session="unavailable",
                quota="ample",
                observed_at="2026-08-06T12:00:00Z",
                valid_until="2026-08-11T13:00:00Z",
            )
        ],
    )

    result = main(
        [
            "route",
            "--project",
            str(FIXTURES / "project-alternate.yaml"),
            "--inventory",
            str(FIXTURES / "inventory-alternate.yaml"),
            "--resource-state",
            str(state),
            "--allow-demo",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 3
    plan = json.loads(captured.out)
    assert plan["assignments"][0]["primary"]["resource_id"] == "verifier-a"
    assert plan["assignments"][0]["alternate"] is None
    assert plan["assignments"][0]["unresolved_gaps"][0]["code"] == (
        "required-alternate-unavailable"
    )


def test_state_validate_is_explicit_and_does_not_read_inventory(tmp_path: Path, capsys) -> None:
    state = tmp_path / "state.yaml"
    _write_state(state, [_state_snapshot()], json_input=False)

    assert main(["state", "validate", str(state), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["valid"] is True
    assert result["scope"] == "schema-only"
    assert result["resources"] == 1
    assert result["source_count"] == 1
    assert "fingerprint" not in result
    assert "sources" not in result
    assert "inventory" not in result

    assert main(["state", "validate", str(state)]) == 0
    human = capsys.readouterr().out
    assert "Resource-state file schema is valid" in human
    assert "Routing separately checks roster, evaluation time, mode, and confidence." in human


def test_resource_state_schema_is_strict_and_versioned(capsys) -> None:
    assert main(["schema", "resource-state"]) == 0
    schema = json.loads(capsys.readouterr().out)

    assert schema["title"] == "ResourceStateCollection"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["snapshots"]
    assert schema["properties"]["schema_version"]["default"] == 1


def test_route_help_describes_one_route_only_no_write_boundary(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["route", "--help"])

    assert raised.value.code == 0
    help_text = " ".join(capsys.readouterr().out.lower().split())
    assert "this route only" in help_text
    assert "local evaluation time and preserves its fixed utc offset" in help_text
    assert "never refreshes or writes" in help_text


def test_expired_overlay_capacity_is_a_routing_gap_not_usable_capacity() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = ProjectBrief(
        id="capacity-expiry",
        name="Capacity Expiry",
        goal="Check expired temporary capacity",
        as_of=date(2026, 8, 10),
        workstreams=[
            Workstream(
                id="architecture",
                name="Architecture",
                objective="Check capacity evidence",
                required_capabilities=[{"id": "architecture", "minimum": 0.5}],
                inputs=["Synthetic brief"],
                allowed_scope=["Synthetic route"],
                exclusions=["Execution"],
                deliverable="Capacity result",
                acceptance_criteria=["Expired capacity is gated"],
                verification=["Inspect route"],
                stop_conditions=["State expires"],
                next_owner="Human reviewer",
                capacity_demand=CapacityDemand(unit="review-request", amount=1),
            )
        ],
    )
    state = {
        "schema_version": 1,
        "snapshots": [
            _state_snapshot(
                session="available",
                capacity={
                    "unit": "review-request",
                    "remaining": 5,
                    "expires_at": "2026-08-07T12:00:00Z",
                },
                observed_at="2026-08-06T12:00:00Z",
                valid_until="2026-08-11T12:00:00Z",
                quota="limited",
            )
        ],
    }
    from atready.resource_state import resource_state_from_mapping

    plan = route(
        inventory,
        project,
        allow_demo=True,
        resource_state=resource_state_from_mapping(state),
        resource_state_evaluated_at=EVALUATED_AT,
    )
    candidate = next(item for item in plan.assignments[0].candidates if item.resource_id == "codex")

    assert candidate.eligible_for_role is False
    assert candidate.gate_codes == ["capacity-expired"]
