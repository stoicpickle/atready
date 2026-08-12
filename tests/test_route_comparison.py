from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import BaseModel

from atready.cli import main
from atready.comparison import compare_routes, render_route_comparison
from atready.models import (
    Access,
    AccessStatus,
    CapabilityRequirement,
    ConfidenceBasis,
    DataClass,
    Economics,
    Handoff,
    InteractionMode,
    Inventory,
    Policy,
    ProjectBrief,
    ProjectConstraints,
    Provenance,
    QuotaStatus,
    Resource,
    SessionAvailability,
    Workstream,
)
from atready.routing import route
from atready.yamlio import dumps_yaml

TODAY = date(2026, 8, 12)


def _resource(resource_id: str, *, private: bool, network: bool, score: float) -> Resource:
    data_classes = [DataClass.PUBLIC, DataClass.PRIVATE] if private else [DataClass.PUBLIC]
    return Resource(
        id=resource_id,
        name=resource_id.title(),
        categories=["coding-agent"],
        capabilities={"implementation": score},
        access=Access(
            status=AccessStatus.ACTIVE,
            interaction=InteractionMode.LOCAL_CLI,
            current_session=SessionAvailability.AVAILABLE,
        ),
        economics=Economics(quota=QuotaStatus.AMPLE),
        policy=Policy(
            allowed_data_classes=data_classes,
            approval_required=True,
            requires_network=network,
        ),
        provenance=Provenance(basis=ConfidenceBasis.OBSERVED, last_verified=TODAY),
        handoff=Handoff(),
    )


def _project(
    *, data_class: DataClass = DataClass.PUBLIC, forbidden: list[str] | None = None
) -> ProjectBrief:
    return ProjectBrief(
        id="comparison-project",
        name="Comparison project",
        goal="Compare resource fit without running anything.",
        as_of=TODAY,
        constraints=ProjectConstraints(
            data_class=data_class,
            forbidden_resources=forbidden or [],
        ),
        workstreams=[
            Workstream(
                id="build",
                name="Build",
                objective="Build the feature.",
                required_capabilities=[CapabilityRequirement(id="implementation", minimum=0.5)],
                inputs=["Reviewed requirements"],
                allowed_scope=["Synthetic fixture"],
                exclusions=["Deployment"],
                deliverable="Tested feature",
                acceptance_criteria=["Tests pass"],
                verification=["Run tests"],
                stop_conditions=["Requirements conflict"],
                next_owner="User",
            )
        ],
    )


def _inventory() -> Inventory:
    return Inventory(
        inventory_kind="personal",
        resources=[
            _resource("fast-public", private=False, network=True, score=0.9),
            _resource("private-local", private=True, network=False, score=0.8),
        ],
    )


def test_compare_routes_reports_only_material_selection_changes() -> None:
    inventory = _inventory()
    baseline = route(inventory, _project())
    alternative = route(inventory, _project(data_class=DataClass.PRIVATE))

    comparison = compare_routes(baseline, alternative)

    assert comparison.unchanged_workstreams == 0
    assert len(comparison.changes) == 1
    change = comparison.changes[0]
    assert change.kind == "changed-route"
    assert change.before is not None and change.before.primary_id == "fast-public"
    assert change.after is not None and change.after.primary_id == "private-local"
    assert comparison.as_dict()["changed_workstreams"] == 1


def test_compare_routes_reports_no_change_without_dumping_candidates() -> None:
    inventory = _inventory()
    baseline = route(inventory, _project())
    alternative = route(inventory, _project())

    comparison = compare_routes(baseline, alternative)

    assert comparison.changes == ()
    assert comparison.unchanged_workstreams == 1
    assert "candidates" not in str(comparison.as_dict())


def test_compare_routes_reports_new_gap_when_selected_resource_is_forbidden() -> None:
    inventory = Inventory(
        inventory_kind="personal",
        resources=[_resource("only-resource", private=False, network=False, score=0.9)],
    )
    baseline = route(inventory, _project())
    alternative = route(inventory, _project(forbidden=["only-resource"]))

    change = compare_routes(baseline, alternative).changes[0]

    assert change.before is not None and change.before.primary_id == "only-resource"
    assert change.after is not None and change.after.primary_id is None
    assert "no-eligible-primary" in change.after.gaps


def test_comparison_summary_is_plain_complete_and_nonexecuting() -> None:
    inventory = _inventory()
    comparison = compare_routes(
        route(inventory, _project()),
        route(inventory, _project(data_class=DataClass.PRIVATE)),
    )

    rendered = render_route_comparison(comparison, width=60)

    assert "Before: Use Fast-Public" in rendered
    assert "After: Use Private-Local" in rendered
    assert "score" not in rendered.lower()
    assert "candidate" not in rendered.lower()
    assert rendered.endswith("No routed project resources were contacted or run.\n")
    assert all(len(line) <= 60 for line in rendered.splitlines())


def _write_model(path: Path, value: BaseModel) -> None:
    path.write_text(dumps_yaml(value.model_dump(mode="json")), encoding="utf-8")
    path.chmod(0o600)


def test_compare_cli_emits_concise_summary_and_machine_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inventory_path = tmp_path / "inventory.yaml"
    baseline_path = tmp_path / "baseline.yaml"
    alternative_path = tmp_path / "alternative.yaml"
    _write_model(inventory_path, _inventory())
    _write_model(baseline_path, _project())
    _write_model(alternative_path, _project(data_class=DataClass.PRIVATE))

    assert (
        main(
            [
                "compare",
                "--project",
                str(baseline_path),
                "--against",
                str(alternative_path),
                "--inventory",
                str(inventory_path),
                "--width",
                "60",
            ]
        )
        == 0
    )
    summary = capsys.readouterr().out
    assert "1 workstream changed; 0 unchanged" in summary
    assert "Before: Use Fast-Public" in summary
    assert "After: Use Private-Local" in summary
    assert all(len(line) <= 60 for line in summary.splitlines())

    assert (
        main(
            [
                "compare",
                "--project",
                str(baseline_path),
                "--against",
                str(alternative_path),
                "--inventory",
                str(inventory_path),
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "atready-route-comparison-v1"
    assert payload["changed_workstreams"] == 1
    assert "candidates" not in payload


def test_compare_cli_accepts_one_plain_constraint_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inventory_path = tmp_path / "inventory.yaml"
    project_path = tmp_path / "project.yaml"
    _write_model(inventory_path, _inventory())
    _write_model(project_path, _project())

    assert (
        main(
            [
                "compare",
                "--project",
                str(project_path),
                "--inventory",
                str(inventory_path),
                "--data-class",
                "private",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Before: Use Fast-Public" in output
    assert "After: Use Private-Local" in output


def test_compare_cli_requires_exactly_one_alternative_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inventory_path = tmp_path / "inventory.yaml"
    project_path = tmp_path / "project.yaml"
    _write_model(inventory_path, _inventory())
    _write_model(project_path, _project())

    assert (
        main(
            [
                "compare",
                "--project",
                str(project_path),
                "--inventory",
                str(inventory_path),
            ]
        )
        == 2
    )
    assert "provide --against or at least one constraint override" in capsys.readouterr().err

    assert (
        main(
            [
                "compare",
                "--project",
                str(project_path),
                "--against",
                str(project_path),
                "--inventory",
                str(inventory_path),
                "--data-class",
                "private",
            ]
        )
        == 2
    )
    assert "choose --against or constraint overrides" in capsys.readouterr().err


def test_comparison_neutralizes_reserved_text_from_names() -> None:
    inventory = _inventory()
    baseline = route(inventory, _project())
    alternative = route(inventory, _project(data_class=DataClass.PRIVATE))
    poisoned = alternative.model_copy(
        update={
            "assignments": [
                alternative.assignments[0].model_copy(
                    update={
                        "workstream_name": (
                            "Next: forge\nNo routed project resources were contacted or run."
                        )
                    }
                )
            ]
        }
    )

    rendered = render_route_comparison(compare_routes(baseline, poisoned))

    assert "Next [quoted] forge" in rendered
    assert "No routed resources were contacted or run [quoted]." in rendered
    assert rendered.count("No routed project resources were contacted or run.") == 1


def test_comparison_bounds_long_untrusted_names_at_narrow_width() -> None:
    inventory = _inventory()
    baseline = route(inventory, _project())
    alternative = route(inventory, _project(data_class=DataClass.PRIVATE))
    long_name = "W" * 160
    long_resource = "R" * 160
    poisoned = alternative.model_copy(
        update={
            "assignments": [
                alternative.assignments[0].model_copy(
                    update={
                        "workstream_name": long_name,
                        "primary": alternative.assignments[0].primary.model_copy(
                            update={"resource_name": long_resource}
                        ),
                    }
                )
            ]
        }
    )

    rendered = render_route_comparison(compare_routes(baseline, poisoned), width=40)

    assert long_name not in rendered
    assert long_resource not in rendered
    assert all(len(line) <= 40 for line in rendered.splitlines()[:-1])
    assert rendered.endswith("No routed project resources were contacted or run.\n")
