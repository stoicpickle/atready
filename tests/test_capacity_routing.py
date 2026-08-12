from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from atready.models import (
    Access,
    Capacity,
    CapacityDemand,
    DispositionStatus,
    Economics,
    Inventory,
    ProjectBrief,
    ProjectConstraints,
    Provenance,
    QuotaStatus,
    Resource,
    Workstream,
)
from atready.render import render_agent_summary, render_summary
from atready.routing import route

AS_OF = date(2026, 8, 10)


def _resource(*, capacity: Capacity | None) -> Resource:
    return Resource.model_validate(
        {
            "id": "synthetic-seat",
            "name": "Synthetic Seat",
            "categories": ["synthetic-tool"],
            "capabilities": {"review": 0.9},
            "access": Access(
                status="active",
                interaction="local-cli",
                current_session="available",
            ),
            "economics": Economics(
                marginal_cost=0.1,
                quota=QuotaStatus.LIMITED if capacity else QuotaStatus.AMPLE,
                capacity=capacity,
            ),
            "policy": {"allowed_data_classes": ["public"]},
            "provenance": Provenance(basis="observed", last_verified=AS_OF),
        }
    )


def _workstream(*, demand: CapacityDemand | None) -> Workstream:
    return Workstream.model_validate(
        {
            "id": "review",
            "name": "Review",
            "objective": "Review a synthetic change",
            "required_capabilities": [{"id": "review", "minimum": 0.5}],
            "inputs": ["Synthetic diff"],
            "allowed_scope": ["Synthetic repository"],
            "exclusions": ["No execution"],
            "deliverable": "Review findings",
            "acceptance_criteria": ["Findings are actionable"],
            "verification": ["Human review"],
            "stop_conditions": ["Scope changes"],
            "next_owner": "Human reviewer",
            "capacity_demand": demand,
        }
    )


def _project(*, demand: CapacityDemand | None) -> ProjectBrief:
    return ProjectBrief(
        id="synthetic-project",
        name="Synthetic Project",
        goal="Exercise declared capacity routing",
        as_of=AS_OF,
        workstreams=[_workstream(demand=demand)],
    )


def _capacity(**overrides: object) -> Capacity:
    values: dict[str, object] = {
        "unit": "review-request",
        "remaining": 5,
        "basis": "user-judgment",
        "last_verified": date(2026, 8, 9),
    }
    values.update(overrides)
    return Capacity.model_validate(values)


def test_exact_same_unit_capacity_can_make_a_candidate_eligible() -> None:
    inventory = Inventory(inventory_kind="personal", resources=[_resource(capacity=_capacity())])
    project = _project(demand=CapacityDemand(unit="review-request", amount=3))
    before = inventory.model_dump(mode="json")

    plan = route(inventory, project)

    candidate = plan.assignments[0].candidates[0]
    assert candidate.eligible_for_role is True
    assert candidate.gate_codes == []
    assert candidate.notes == [
        "[capacity-enough] demand 3 review-request; declared remaining 5 (verified 2026-08-09)"
    ]
    assert inventory.model_dump(mode="json") == before


def test_insufficient_declared_capacity_is_an_explicit_candidate_gate() -> None:
    inventory = Inventory(inventory_kind="personal", resources=[_resource(capacity=_capacity())])

    plan = route(
        inventory,
        _project(demand=CapacityDemand(unit="review-request", amount=6)),
    )

    assignment = plan.assignments[0]
    candidate = assignment.candidates[0]
    assert assignment.primary is None
    assert candidate.eligible_for_role is False
    assert candidate.gate_codes == ["capacity-insufficient"]
    assert candidate.notes == [
        "[capacity-insufficient] demand 6 review-request; declared remaining 5 "
        "(verified 2026-08-09)"
    ]


def test_missing_capacity_stays_unknown_even_when_other_unverified_state_is_allowed() -> None:
    inventory = Inventory(inventory_kind="personal", resources=[_resource(capacity=None)])
    project = _project(demand=CapacityDemand(unit="review-request", amount=1)).model_copy(
        update={"constraints": ProjectConstraints(allow_unverified=True)}
    )

    candidate = route(inventory, project).assignments[0].candidates[0]

    assert candidate.eligible_for_role is False
    assert candidate.gate_codes == ["capacity-unknown"]
    assert candidate.notes == [
        "[capacity-unknown] demand 1 review-request; resource has no exact capacity declaration"
    ]

    plan = route(inventory, project)
    assert plan.dispositions[0].status is DispositionStatus.UNVERIFIED
    assert plan.dispositions[0].reason_code == "capacity-unknown"


def test_capacity_units_are_never_converted_or_compared() -> None:
    inventory = Inventory(
        inventory_kind="personal",
        resources=[_resource(capacity=_capacity(unit="credit", remaining=100))],
    )

    candidate = (
        route(
            inventory,
            _project(demand=CapacityDemand(unit="review-request", amount=1)),
        )
        .assignments[0]
        .candidates[0]
    )

    assert candidate.gate_codes == ["capacity-unit-mismatch"]
    assert candidate.notes == [
        "[capacity-unit-mismatch] demand 1 review-request; declared capacity uses credit; "
        "units were not converted"
    ]


def test_reset_after_verification_makes_the_declared_balance_unknown() -> None:
    inventory = Inventory(
        inventory_kind="personal",
        resources=[_resource(capacity=_capacity(resets_on=AS_OF))],
    )

    candidate = (
        route(
            inventory,
            _project(demand=CapacityDemand(unit="review-request", amount=1)),
        )
        .assignments[0]
        .candidates[0]
    )

    assert candidate.gate_codes == ["capacity-reset-unknown"]
    assert candidate.notes == [
        "[capacity-reset-unknown] demand 1 review-request; declared capacity reset on "
        "2026-08-10 after verification; post-reset remaining was not inferred"
    ]


def test_capacity_verified_after_project_date_is_not_backdated() -> None:
    inventory = Inventory(
        inventory_kind="personal",
        resources=[
            _resource(
                capacity=_capacity(
                    last_verified=date(2026, 8, 11),
                    resets_on=None,
                )
            )
        ],
    )

    candidate = (
        route(
            inventory,
            _project(demand=CapacityDemand(unit="review-request", amount=1)),
        )
        .assignments[0]
        .candidates[0]
    )

    assert candidate.gate_codes == ["capacity-unknown"]
    assert candidate.notes == [
        "[capacity-unknown] demand 1 review-request; declared capacity was verified after "
        "project as_of (2026-08-11)"
    ]


def test_capacity_verified_on_its_reset_date_remains_comparable() -> None:
    inventory = Inventory(
        inventory_kind="personal",
        resources=[
            _resource(
                capacity=_capacity(
                    resets_on=AS_OF,
                    last_verified=AS_OF,
                )
            )
        ],
    )

    candidate = (
        route(
            inventory,
            _project(demand=CapacityDemand(unit="review-request", amount=5)),
        )
        .assignments[0]
        .candidates[0]
    )

    assert candidate.eligible_for_role is True
    assert candidate.notes == [
        "[capacity-enough] demand 5 review-request; declared remaining 5 (verified 2026-08-10)"
    ]


def test_project_limit_is_the_effective_advisory_bound() -> None:
    inventory = Inventory(
        inventory_kind="personal",
        resources=[_resource(capacity=_capacity(remaining=10, project_limit=2))],
    )

    candidate = (
        route(
            inventory,
            _project(demand=CapacityDemand(unit="review-request", amount=3)),
        )
        .assignments[0]
        .candidates[0]
    )

    assert candidate.gate_codes == ["capacity-insufficient"]
    assert candidate.notes == [
        "[capacity-insufficient] demand 3 review-request; declared remaining 10 "
        "(verified 2026-08-09); effective project limit 2"
    ]


def test_no_demand_preserves_prior_routing_behavior_and_ignores_capacity() -> None:
    resource = _resource(capacity=_capacity(remaining=1, project_limit=0))
    inventory = Inventory(inventory_kind="personal", resources=[resource])
    before = inventory.model_dump(mode="json")

    candidate = route(inventory, _project(demand=None)).assignments[0].candidates[0]

    assert candidate.eligible_for_role is True
    assert candidate.gate_codes == []
    assert candidate.notes == []
    assert inventory.model_dump(mode="json") == before


def test_multiple_workstreams_compare_one_snapshot_without_implying_consumption() -> None:
    inventory = Inventory(
        inventory_kind="personal",
        resources=[_resource(capacity=_capacity(remaining=1))],
    )
    before = inventory.model_dump(mode="json")
    first = _workstream(demand=CapacityDemand(unit="review-request", amount=1))
    second = first.model_copy(update={"id": "second-review", "name": "Second Review"})
    project = _project(demand=None).model_copy(update={"workstreams": [first, second]})

    plan = route(inventory, project)

    assert [assignment.primary.resource_id for assignment in plan.assignments] == [
        "synthetic-seat",
        "synthetic-seat",
    ]
    assert [assignment.candidates[0].notes for assignment in plan.assignments] == [
        ["[capacity-enough] demand 1 review-request; declared remaining 1 (verified 2026-08-09)"],
        ["[capacity-enough] demand 1 review-request; declared remaining 1 (verified 2026-08-09)"],
    ]
    assert inventory.model_dump(mode="json") == before
    evidence = " ".join(
        note for assignment in plan.assignments for note in assignment.candidates[0].notes
    ).lower()
    assert all(word not in evidence for word in ("decrement", "reserve", "spend", "spent"))


def test_capacity_gap_is_plain_in_summary_and_has_a_specific_next_action() -> None:
    inventory = Inventory(inventory_kind="personal", resources=[_resource(capacity=_capacity())])
    plan = route(
        inventory,
        _project(demand=CapacityDemand(unit="review-request", amount=6)),
    )

    summary = render_summary(plan)
    agent_summary = render_agent_summary(plan)

    for output in (summary, agent_summary):
        folded = " ".join(output.split())
        assert "Synthetic Seat: demand 6 review-request; declared remaining 5" in folded
        assert (
            "Use a resource with enough same-unit declared capacity or reduce the workstream "
            "demand, then route again."
        ) in folded
        assert "capacity-insufficient" not in output


@pytest.mark.parametrize(
    ("capacity", "expected_evidence", "expected_action"),
    [
        (
            None,
            "resource has no exact capacity declaration",
            "Check and update exact same-unit capacity, then route again.",
        ),
        (
            _capacity(unit="credit", remaining=100),
            "declared capacity uses credit; units were not converted",
            "Use one exact unit for both workstream demand and resource capacity, then route "
            "again.",
        ),
        (
            _capacity(resets_on=AS_OF),
            "post-reset remaining was not inferred",
            "Check and update exact same-unit capacity, then route again.",
        ),
    ],
)
def test_other_capacity_gaps_are_plain_and_actionable(
    capacity: Capacity | None,
    expected_evidence: str,
    expected_action: str,
) -> None:
    inventory = Inventory(inventory_kind="personal", resources=[_resource(capacity=capacity)])
    plan = route(
        inventory,
        _project(demand=CapacityDemand(unit="review-request", amount=1)),
    )

    folded = " ".join(render_agent_summary(plan).split())

    assert expected_evidence in folded
    assert expected_action in folded
    assert all(code not in folded for code in ("capacity-unknown", "capacity-unit-mismatch"))


@pytest.mark.parametrize("amount", [0, -1, True, "1", float("inf"), 10**18 + 1])
def test_capacity_demand_requires_a_positive_bounded_native_number(amount: object) -> None:
    with pytest.raises(ValidationError, match="amount"):
        CapacityDemand.model_validate({"unit": "review-request", "amount": amount})


def test_capacity_demand_schema_is_minimal_strict_and_unit_scoped() -> None:
    schema = CapacityDemand.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"unit", "amount"}
    assert schema["properties"]["unit"]["pattern"] == "^[a-z0-9][a-z0-9._-]*$"
    assert schema["properties"]["amount"] == {
        "exclusiveMinimum": 0,
        "maximum": 1e18,
        "title": "Amount",
        "type": "number",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CapacityDemand.model_validate(
            {"unit": "review-request", "amount": 1, "convert_from": "credit"}
        )

    project_schema = ProjectBrief.model_json_schema()
    demand_field = project_schema["$defs"]["Workstream"]["properties"]["capacity_demand"]
    assert demand_field == {
        "anyOf": [{"$ref": "#/$defs/CapacityDemand"}, {"type": "null"}],
        "default": None,
    }
