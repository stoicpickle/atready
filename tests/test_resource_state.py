from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from atready.errors import ConfigurationError
from atready.models import Capacity, CapacityDemand, Inventory, ProjectBrief, Workstream
from atready.resource_state import (
    ResourceStateCollection,
    ResourceStateSnapshot,
    apply_resource_state,
    resource_state_from_text,
)
from atready.routing import route

OBSERVED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
EVALUATED_AT = OBSERVED_AT + timedelta(minutes=1)


def _snapshot(**overrides: object) -> ResourceStateSnapshot:
    values: dict[str, object] = {
        "resource_id": "synthetic-seat",
        "observed_at": OBSERVED_AT,
        "source": "synthetic-collector",
        "source_kind": "adapter",
        "mode": "live",
        "confidence": "observed",
        "session": "available",
        "quota": "limited",
        "capacity": {
            "unit": "review-request",
            "remaining": 5,
            "limit": 10,
            "project_limit": 3,
            "resets_at": OBSERVED_AT + timedelta(days=30),
            "expires_at": OBSERVED_AT + timedelta(days=20),
        },
        "valid_until": OBSERVED_AT + timedelta(minutes=10),
    }
    values.update(overrides)
    return ResourceStateSnapshot.model_validate(values)


def test_snapshot_emits_complete_json_safe_evidence() -> None:
    snapshot = _snapshot()

    assert snapshot.to_evidence() == {
        "schema_version": 1,
        "resource_id": "synthetic-seat",
        "observed_at": "2026-09-01T12:00:00Z",
        "source": "synthetic-collector",
        "source_kind": "adapter",
        "mode": "live",
        "confidence": "observed",
        "session": "available",
        "quota": "limited",
        "capacity": {
            "unit": "review-request",
            "remaining": 5,
            "limit": 10,
            "project_limit": 3,
            "resets_at": "2026-10-01T12:00:00Z",
            "expires_at": "2026-09-21T12:00:00Z",
        },
        "valid_until": "2026-09-01T12:10:00Z",
    }


def test_collection_is_versioned_bounded_and_unique_by_resource_id() -> None:
    collection = ResourceStateCollection(snapshots=[_snapshot()])

    assert collection.to_evidence() == {
        "schema_version": 1,
        "snapshots": [_snapshot().to_evidence()],
    }

    with pytest.raises(ValidationError, match="resource_ids must be unique"):
        ResourceStateCollection(snapshots=[_snapshot(), _snapshot()])

    with pytest.raises(ValidationError):
        ResourceStateCollection(
            snapshots=[_snapshot(resource_id=f"seat-{index}") for index in range(501)]
        )


def test_collection_fingerprint_is_independent_of_snapshot_order() -> None:
    first = _snapshot(resource_id="first-seat")
    second = _snapshot(resource_id="second-seat")

    forward = ResourceStateCollection(snapshots=[first, second])
    reverse = ResourceStateCollection(snapshots=[second, first])

    assert forward.fingerprint() == reverse.fingerprint()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_at", datetime(2026, 9, 1, 12, 0)),
        ("capacity", {"unit": "credit", "remaining": "5"}),
    ],
)
def test_snapshot_rejects_naive_timestamps_and_implicit_coercion(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_kind": "manual", "mode": "live"},
        {"source_kind": "adapter", "mode": "manual"},
        {"source_kind": "local-cache", "mode": "estimated"},
        {"valid_until": OBSERVED_AT - timedelta(seconds=1)},
        {"valid_until": None},
        {
            "capacity": {
                "unit": "credit",
                "remaining": 1,
                "resets_at": OBSERVED_AT - timedelta(seconds=1),
            }
        },
        {
            "capacity": {
                "unit": "credit",
                "remaining": 1,
                "expires_at": OBSERVED_AT - timedelta(seconds=1),
            }
        },
        {"capacity": {"unit": "credit", "remaining": 0}, "quota": "limited"},
        {"capacity": {"unit": "credit", "remaining": 1}, "quota": "exhausted"},
        {"capacity": {"unit": "credit", "remaining": 1}, "confidence": "unknown"},
        {"session": None, "quota": None, "capacity": None},
    ],
)
def test_snapshot_rejects_inconsistent_state_evidence(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**overrides)


def test_snapshot_rejects_unknown_and_sensitive_shape_fields() -> None:
    with pytest.raises(ValidationError):
        _snapshot(provider_id="untrusted-provider")

    with pytest.raises(ValidationError):
        _snapshot(account_id="account-123")

    with pytest.raises(ValidationError):
        _snapshot(credential="secret")


def test_snapshot_accepts_canonical_json_timestamp_strings() -> None:
    snapshot = _snapshot(
        observed_at="2026-09-01T12:00:00Z",
        valid_until="2026-09-01T12:10:00+00:00",
        capacity={
            "unit": "credit",
            "remaining": 4,
            "resets_at": "2026-09-02T12:00:00Z",
        },
    )

    assert snapshot.observed_at == OBSERVED_AT
    assert snapshot.valid_until == OBSERVED_AT + timedelta(minutes=10)


def _inventory() -> Inventory:
    return Inventory.model_validate(
        {
            "inventory_kind": "personal",
            "preferences": {"stale_after_days": 30},
            "resources": [
                {
                    "id": "synthetic-seat",
                    "name": "Synthetic Seat",
                    "categories": ["coding-agent"],
                    "capabilities": {"implementation": 0.9},
                    "access": {
                        "status": "active",
                        "interaction": "local-cli",
                        "current_session": "unknown",
                    },
                    "economics": {"quota": "unknown"},
                    "provenance": {
                        "basis": "user-judgment",
                        "last_verified": "2026-08-20",
                    },
                }
            ],
        }
    )


def _project_with_capacity_demand() -> ProjectBrief:
    return ProjectBrief(
        id="synthetic-project",
        name="Synthetic Project",
        goal="Exercise resource-state routing",
        as_of=date(2026, 9, 1),
        workstreams=[
            Workstream(
                id="implementation",
                name="Implementation",
                objective="Implement a synthetic change",
                required_capabilities=[{"id": "implementation", "minimum": 0.5}],
                inputs=["Synthetic input"],
                allowed_scope=["Synthetic scope"],
                exclusions=["No execution"],
                deliverable="Synthetic change",
                acceptance_criteria=["Change is reviewed"],
                verification=["Human review"],
                stop_conditions=["Scope changes"],
                next_owner="Human reviewer",
                capacity_demand=CapacityDemand(unit="review-request", amount=1),
            )
        ],
    )


def test_apply_resource_state_is_ephemeral_and_maps_exact_dynamic_facts() -> None:
    inventory = _inventory()
    original = inventory.model_dump(mode="json")
    state = ResourceStateCollection(snapshots=[_snapshot()])

    application = apply_resource_state(
        inventory,
        state,
        as_of=date(2026, 9, 1),
        evaluated_at=EVALUATED_AT,
    )

    effective = application.inventory.resources[0]
    assert effective.access.status.value == "active"
    assert effective.access.current_session.value == "available"
    assert effective.economics.quota.value == "limited"
    assert effective.economics.capacity is not None
    assert effective.economics.capacity.remaining == 5
    assert effective.economics.capacity.resets_on == date(2026, 10, 1)
    assert effective.economics.capacity.expires_on == date(2026, 9, 21)
    assert effective.economics.capacity.last_verified == date(2026, 9, 1)
    assert inventory.model_dump(mode="json") == original
    assert application.resource_ids == ("synthetic-seat",)
    assert application.sources == ("synthetic-collector",)
    assert application.fingerprint.startswith("sha256:")
    assert application.warnings[0].startswith("[resource-state] temporary state applied")


def test_partial_overlay_conflict_is_a_value_redacted_configuration_error() -> None:
    inventory_data = _inventory().model_dump(mode="python")
    inventory_data["resources"][0]["economics"] = {
        "quota": "ample",
        "capacity": Capacity(
            unit="review-request",
            remaining=5,
            basis="observed",
            last_verified=date(2026, 9, 1),
        ),
    }
    inventory = Inventory.model_validate(inventory_data)
    state = ResourceStateCollection(snapshots=[_snapshot(capacity=None, quota="exhausted")])

    with pytest.raises(
        ConfigurationError, match="resource state overlay validation failed"
    ) as error:
        apply_resource_state(
            inventory,
            state,
            as_of=date(2026, 9, 1),
            evaluated_at=EVALUATED_AT,
        )

    message = str(error.value)
    assert "synthetic-seat" not in message
    assert "5" not in message
    assert "economics" in message


def test_late_resource_state_capacity_dates_are_clamped_for_routing() -> None:
    state = ResourceStateCollection(
        snapshots=[
            _snapshot(
                capacity={
                    "unit": "review-request",
                    "remaining": 5,
                    "resets_at": datetime(2127, 3, 1, 12, 0, tzinfo=UTC),
                    "expires_at": datetime(2127, 3, 1, 12, 0, tzinfo=UTC),
                }
            )
        ]
    )

    plan = route(
        _inventory(),
        _project_with_capacity_demand(),
        resource_state=state,
        resource_state_evaluated_at=EVALUATED_AT,
    )

    candidate = plan.assignments[0].candidates[0]
    assert candidate.eligible_for_role is True
    assert candidate.capacity_pressure_days == 36_600


def test_resource_state_json_text_is_adapter_friendly_and_strict() -> None:
    state = resource_state_from_text(
        """{
          "schema_version": 1,
          "snapshots": [{
            "schema_version": 1,
            "resource_id": "synthetic-seat",
            "observed_at": "2026-09-01T12:00:00Z",
            "source": "synthetic-collector",
            "source_kind": "adapter",
            "mode": "live",
            "confidence": "observed",
            "session": "available",
            "valid_until": "2026-09-01T12:15:00Z"
          }]
        }"""
    )

    assert state.snapshots[0].observed_at == OBSERVED_AT


@pytest.mark.parametrize(
    ("state", "as_of", "evaluated_at", "message"),
    [
        (
            ResourceStateCollection(snapshots=[_snapshot(resource_id="absent")]),
            date(2026, 9, 1),
            EVALUATED_AT,
            "absent from the selected inventory",
        ),
        (
            ResourceStateCollection(
                snapshots=[
                    _snapshot(
                        observed_at=OBSERVED_AT + timedelta(days=1),
                        valid_until=OBSERVED_AT + timedelta(days=1, minutes=10),
                    )
                ]
            ),
            date(2026, 9, 1),
            OBSERVED_AT + timedelta(days=1),
            "observed after project as_of",
        ),
        (
            ResourceStateCollection(
                snapshots=[_snapshot(valid_until=OBSERVED_AT + timedelta(minutes=10))]
            ),
            date(2026, 9, 2),
            EVALUATED_AT,
            "has expired",
        ),
        (
            ResourceStateCollection(
                snapshots=[
                    _snapshot(
                        source="estimate",
                        source_kind="adapter",
                        mode="estimated",
                        valid_until=None,
                    )
                ]
            ),
            date(2026, 9, 1),
            EVALUATED_AT,
            "estimated state",
        ),
        (
            ResourceStateCollection(
                snapshots=[
                    _snapshot(
                        observed_at=OBSERVED_AT - timedelta(days=31),
                        source="manual",
                        source_kind="manual",
                        mode="manual",
                        valid_until=None,
                        capacity={"unit": "review-request", "remaining": 5},
                    )
                ]
            ),
            date(2026, 9, 1),
            EVALUATED_AT,
            "is stale",
        ),
    ],
)
def test_apply_resource_state_fails_closed(
    state: ResourceStateCollection,
    as_of: date,
    evaluated_at: datetime,
    message: str,
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        apply_resource_state(_inventory(), state, as_of=as_of, evaluated_at=evaluated_at)


@pytest.mark.parametrize(
    ("evaluated_at", "accepted"),
    [
        (OBSERVED_AT + timedelta(minutes=9, seconds=59), True),
        (OBSERVED_AT + timedelta(minutes=10), True),
        (OBSERVED_AT + timedelta(minutes=10, seconds=1), False),
    ],
)
def test_live_state_is_accepted_only_through_its_exact_validity_boundary(
    evaluated_at: datetime, accepted: bool
) -> None:
    state = ResourceStateCollection(snapshots=[_snapshot()])

    if accepted:
        application = apply_resource_state(
            _inventory(), state, as_of=date(2026, 9, 1), evaluated_at=evaluated_at
        )
        assert application.evaluated_at == evaluated_at
    else:
        with pytest.raises(ConfigurationError, match="no longer valid at evaluated_at"):
            apply_resource_state(
                _inventory(), state, as_of=date(2026, 9, 1), evaluated_at=evaluated_at
            )


def test_state_rejects_future_observation_and_missing_or_naive_evaluation_time() -> None:
    state = ResourceStateCollection(snapshots=[_snapshot()])

    with pytest.raises(ConfigurationError, match="later than evaluated_at"):
        apply_resource_state(
            _inventory(),
            state,
            as_of=date(2026, 9, 1),
            evaluated_at=OBSERVED_AT - timedelta(seconds=1),
        )
    with pytest.raises(ConfigurationError, match="aware datetime"):
        apply_resource_state(_inventory(), state, as_of=date(2026, 9, 1), evaluated_at=None)  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="timezone-aware"):
        apply_resource_state(
            _inventory(),
            state,
            as_of=date(2026, 9, 1),
            evaluated_at=OBSERVED_AT.replace(tzinfo=None),
        )
    with pytest.raises(ConfigurationError, match="requires an aware resource_state_evaluated_at"):
        route(_inventory(), _project_with_capacity_demand(), resource_state=state)


def test_project_date_comparison_preserves_the_evaluation_offset_as_route_evidence() -> None:
    evaluated_at = datetime(2026, 8, 5, 17, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    observed_at = datetime(2026, 8, 6, 0, 15, tzinfo=UTC)
    state = ResourceStateCollection(
        snapshots=[
            _snapshot(
                observed_at=observed_at,
                valid_until=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
                capacity=None,
            )
        ]
    )

    application = apply_resource_state(
        _inventory(), state, as_of=date(2026, 8, 5), evaluated_at=evaluated_at
    )

    assert application.evaluated_at.isoformat() == "2026-08-05T17:30:00-07:00"


def test_western_evaluation_timezone_controls_capacity_calendar_dates() -> None:
    evaluation_timezone = ZoneInfo("America/Los_Angeles")
    observed_at = datetime(2026, 9, 2, 2, 30, tzinfo=UTC)
    evaluated_at = datetime(2026, 9, 1, 19, 45, tzinfo=evaluation_timezone)
    state = ResourceStateCollection(
        snapshots=[
            _snapshot(
                observed_at=observed_at,
                valid_until=datetime(2026, 9, 2, 3, 0, tzinfo=UTC),
                capacity={
                    "unit": "review-request",
                    "remaining": 5,
                    "resets_at": datetime(2026, 9, 4, 2, 30, tzinfo=UTC),
                    "expires_at": datetime(2026, 9, 3, 2, 30, tzinfo=UTC),
                },
            )
        ]
    )

    application = apply_resource_state(
        _inventory(), state, as_of=date(2026, 9, 1), evaluated_at=evaluated_at
    )

    capacity = application.inventory.resources[0].economics.capacity
    assert capacity is not None
    assert capacity.last_verified == date(2026, 9, 1)
    assert capacity.expires_on == date(2026, 9, 2)
    assert capacity.resets_on == date(2026, 9, 3)


def test_eastern_evaluation_timezone_controls_validity_calendar_boundary() -> None:
    evaluation_timezone = ZoneInfo("Pacific/Kiritimati")
    state = ResourceStateCollection(
        snapshots=[
            _snapshot(
                observed_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                valid_until=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                capacity=None,
            )
        ]
    )

    application = apply_resource_state(
        _inventory(),
        state,
        as_of=date(2026, 1, 2),
        evaluated_at=datetime(2026, 1, 2, 0, 30, tzinfo=evaluation_timezone),
    )

    assert application.resource_ids == ("synthetic-seat",)


def test_manual_state_age_uses_evaluation_timezone_calendar_dates() -> None:
    evaluation_timezone = ZoneInfo("America/Los_Angeles")
    state = ResourceStateCollection(
        snapshots=[
            _snapshot(
                observed_at=datetime(2026, 8, 2, 6, 45, tzinfo=UTC),
                source="manual-entry",
                source_kind="manual",
                mode="manual",
                valid_until=None,
                capacity=None,
            )
        ]
    )

    with pytest.raises(ConfigurationError, match=r"is stale \(31 days\)"):
        apply_resource_state(
            _inventory(),
            state,
            as_of=date(2026, 9, 1),
            evaluated_at=datetime(2026, 9, 1, 0, 15, tzinfo=evaluation_timezone),
        )


def test_manual_state_ages_against_evaluated_at_not_project_as_of() -> None:
    state = ResourceStateCollection(
        snapshots=[
            _snapshot(
                observed_at=OBSERVED_AT - timedelta(days=31),
                source="manual-entry",
                source_kind="manual",
                mode="manual",
                valid_until=None,
                capacity={"unit": "review-request", "remaining": 5},
            )
        ]
    )

    application = apply_resource_state(
        _inventory(),
        state,
        as_of=date(2026, 9, 1),
        evaluated_at=OBSERVED_AT - timedelta(days=1),
    )
    assert application.resource_ids == ("synthetic-seat",)
    with pytest.raises(ConfigurationError, match="is stale"):
        apply_resource_state(_inventory(), state, as_of=date(2026, 9, 1), evaluated_at=EVALUATED_AT)


def test_zoneinfo_is_canonicalized_to_its_evaluation_time_fixed_offset_across_dst() -> None:
    evaluation_timezone = ZoneInfo("America/Los_Angeles")
    evaluated_at = datetime(2026, 3, 8, 0, 30, tzinfo=evaluation_timezone)
    state = ResourceStateCollection(
        snapshots=[
            _snapshot(
                observed_at=datetime(2026, 3, 8, 8, 15, tzinfo=UTC),
                valid_until=datetime(2026, 3, 8, 9, 0, tzinfo=UTC),
                capacity={
                    "unit": "review-request",
                    "remaining": 5,
                    "expires_at": datetime(2026, 3, 9, 7, 30, tzinfo=UTC),
                },
            )
        ]
    )

    application = apply_resource_state(
        _inventory(), state, as_of=date(2026, 3, 8), evaluated_at=evaluated_at
    )

    capacity = application.inventory.resources[0].economics.capacity
    assert capacity is not None
    assert application.evaluated_at.isoformat() == "2026-03-08T00:30:00-08:00"
    assert type(application.evaluated_at.tzinfo) is timezone
    assert capacity.expires_on == date(2026, 3, 8)


def test_manual_state_with_a_valid_until_fails_at_the_exact_expiry_boundary() -> None:
    state = ResourceStateCollection(
        snapshots=[
            _snapshot(
                source="manual-entry",
                source_kind="manual",
                mode="manual",
                valid_until=OBSERVED_AT + timedelta(minutes=10),
            )
        ]
    )

    with pytest.raises(ConfigurationError, match="no longer valid at evaluated_at"):
        apply_resource_state(
            _inventory(),
            state,
            as_of=date(2026, 9, 1),
            evaluated_at=OBSERVED_AT + timedelta(minutes=10, seconds=1),
        )


@pytest.mark.parametrize(
    ("capacity_field", "expected_gate"),
    [("expires_at", "capacity-expired"), ("resets_at", "capacity-reset-unknown")],
)
def test_same_day_exact_capacity_events_become_route_gates(
    capacity_field: str, expected_gate: str
) -> None:
    capacity = {"unit": "review-request", "remaining": 5, capacity_field: OBSERVED_AT}
    state = ResourceStateCollection(snapshots=[_snapshot(capacity=capacity)])

    plan = route(
        _inventory(),
        _project_with_capacity_demand(),
        resource_state=state,
        resource_state_evaluated_at=EVALUATED_AT,
    )

    candidate = plan.assignments[0].candidates[0]
    assert candidate.eligible_for_role is False
    assert candidate.gate_codes == [expected_gate]


def test_fixed_evaluation_time_is_reproducible_and_becomes_route_evidence() -> None:
    state = ResourceStateCollection(snapshots=[_snapshot()])
    project = _project_with_capacity_demand()

    first = route(
        _inventory(), project, resource_state=state, resource_state_evaluated_at=EVALUATED_AT
    )
    second = route(
        _inventory(), project, resource_state=state, resource_state_evaluated_at=EVALUATED_AT
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.plan_id == second.plan_id
    assert first.resource_state_evaluated_at == EVALUATED_AT

    for missing_field in ("resource_state_sources", "resource_state_resources"):
        incomplete = first.model_dump(mode="json")
        incomplete[missing_field] = []
        with pytest.raises(ValidationError, match="requires sources and affected resources"):
            type(first).model_validate(incomplete)


def test_same_instant_with_different_offsets_has_distinct_replayable_route_evidence() -> None:
    state = ResourceStateCollection(snapshots=[_snapshot()])
    project = _project_with_capacity_demand()
    western_evaluation = EVALUATED_AT.astimezone(timezone(timedelta(hours=-7)))

    utc_plan = route(
        _inventory(), project, resource_state=state, resource_state_evaluated_at=EVALUATED_AT
    )
    western_plan = route(
        _inventory(),
        project,
        resource_state=state,
        resource_state_evaluated_at=western_evaluation,
    )

    assert utc_plan.resource_state_evaluated_at == western_plan.resource_state_evaluated_at
    assert utc_plan.model_dump(mode="json")["resource_state_evaluated_at"].endswith("Z")
    assert western_plan.model_dump(mode="json")["resource_state_evaluated_at"].endswith("-07:00")
    assert utc_plan.plan_id != western_plan.plan_id

    serialized_evaluation = western_plan.model_dump(mode="json")["resource_state_evaluated_at"]
    replay = route(
        _inventory(),
        project,
        resource_state=state,
        resource_state_evaluated_at=datetime.fromisoformat(serialized_evaluation),
    )
    assert replay.model_dump(mode="json") == western_plan.model_dump(mode="json")
    assert replay.plan_id == western_plan.plan_id
