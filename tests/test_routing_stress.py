from __future__ import annotations

import random
import socket
from datetime import date, timedelta

import pytest

from atready.models import (
    Access,
    AccessStatus,
    CapabilityRequirement,
    ConfidenceBasis,
    DataClass,
    DispositionStatus,
    Economics,
    InteractionMode,
    Inventory,
    Policy,
    Preferences,
    ProjectBrief,
    ProjectConstraints,
    Provenance,
    QuotaStatus,
    Ratings,
    Resource,
    RouteAssignment,
    SessionAvailability,
    SupportPolicy,
    Workstream,
)
from atready.routing import route

TODAY = date(2026, 8, 10)
CAPABILITIES = ("architecture", "build", "design", "research", "review", "test")
DATA_CLASSES = tuple(DataClass)
INTERACTIONS = tuple(InteractionMode)
ACTIVE_STATES = (AccessStatus.ACTIVE, AccessStatus.ACTIVE, AccessStatus.LIMITED)
ALL_ACCESS_STATES = (*ACTIVE_STATES, AccessStatus.INACTIVE, AccessStatus.UNKNOWN)
ALL_SESSION_STATES = (
    SessionAvailability.AVAILABLE,
    SessionAvailability.AVAILABLE,
    SessionAvailability.UNAVAILABLE,
    SessionAvailability.UNKNOWN,
)
ALL_QUOTA_STATES = (
    QuotaStatus.AMPLE,
    QuotaStatus.AMPLE,
    QuotaStatus.LIMITED,
    QuotaStatus.EXHAUSTED,
    QuotaStatus.UNKNOWN,
)
REQUIRED_ALTERNATE_GAP = "required-alternate-unavailable"


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("routing stress tests forbid network access")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket, "getaddrinfo", fail_network)


def _score(rng: random.Random, *, low: int = 0, high: int = 10) -> float:
    return rng.randint(low, high) / 10


def _synthetic_resource(rng: random.Random, index: int) -> Resource:
    capability_count = rng.randint(1, 4)
    capabilities = {
        capability: _score(rng, low=1) for capability in rng.sample(CAPABILITIES, capability_count)
    }
    status = rng.choice(ALL_ACCESS_STATES)
    provenance_basis = ConfidenceBasis.OBSERVED
    last_verified: date | None = TODAY - timedelta(days=rng.randint(0, 180))
    if index == 0:
        # A missing declaration is valid only when the resource is not declared active.
        status = AccessStatus.UNKNOWN
        provenance_basis = ConfidenceBasis.UNKNOWN
        last_verified = None
    elif index == 1:
        provenance_basis = ConfidenceBasis.UNKNOWN
    elif index == 2:
        # Every generated project predates TODAY, exercising project-relative future evidence.
        last_verified = TODAY
    quota = rng.choice(ALL_QUOTA_STATES)
    allowed_data_classes = rng.sample(DATA_CLASSES, rng.randint(1, len(DATA_CLASSES)))
    ratings = [_score(rng) for _ in range(8)]
    return Resource(
        id=f"resource-{index:02d}",
        name=f"Synthetic Resource {index:02d}",
        categories=["synthetic-tool"],
        capabilities=capabilities,
        access=Access(
            status=status,
            interaction=rng.choice(INTERACTIONS),
            current_session=rng.choice(ALL_SESSION_STATES),
        ),
        economics=Economics(
            marginal_cost=_score(rng),
            quota=quota,
        ),
        ratings=Ratings(
            quality=ratings[0],
            speed=ratings[1],
            autonomy=ratings[2],
            privacy=ratings[3],
            reliability=ratings[4],
            confidence=ratings[5],
            context_switch_cost=ratings[6],
            integration_friction=ratings[7],
        ),
        policy=Policy(
            allowed_data_classes=allowed_data_classes,
            approval_required=True,
            requires_network=rng.choice((False, False, True)),
        ),
        provenance=Provenance(
            basis=provenance_basis,
            last_verified=last_verified,
        ),
    )


def _synthetic_workstream(rng: random.Random, index: int) -> Workstream:
    capability_ids = rng.sample(CAPABILITIES, rng.randint(1, 3))
    support_allowed = len(capability_ids) > 1 and rng.choice((False, True))
    support_gaps = (
        rng.sample(capability_ids, rng.randint(1, len(capability_ids))) if support_allowed else []
    )
    return Workstream(
        id=f"workstream-{index:02d}",
        name=f"Synthetic Workstream {index:02d}",
        objective=f"Complete deterministic synthetic workstream {index:02d}",
        required_capabilities=[
            CapabilityRequirement(
                id=capability,
                importance=rng.randint(1, 10) / 10,
                minimum=rng.randint(2, 8) / 10,
            )
            for capability in capability_ids
        ],
        inputs=["Synthetic input"],
        allowed_scope=["synthetic/scope"],
        exclusions=["External side effects"],
        deliverable="Synthetic deliverable",
        acceptance_criteria=["The deterministic invariants pass"],
        verification=["pytest"],
        stop_conditions=["The generated contract changes"],
        next_owner="Human reviewer",
        support=SupportPolicy(
            allowed=support_allowed,
            capability_gaps=support_gaps,
            minimum_gain=rng.randint(1, 4) / 10,
        ),
        alternate_required=rng.choice((False, False, True)),
    )


def _synthetic_case(seed: int) -> tuple[Inventory, ProjectBrief]:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic test data, not security
    resources = [_synthetic_resource(rng, index) for index in range(rng.randint(8, 16))]
    allowed_interactions = rng.sample(INTERACTIONS, rng.randint(1, len(INTERACTIONS)))
    forbidden_count = rng.randint(0, min(2, len(resources)))
    project = ProjectBrief(
        id=f"stress-project-{seed:04d}",
        name=f"Stress Project {seed:04d}",
        goal="Exercise deterministic routing invariants with synthetic data",
        as_of=TODAY - timedelta(days=7),
        constraints=ProjectConstraints(
            data_class=rng.choice(DATA_CLASSES),
            max_marginal_cost=_score(rng, low=3),
            allowed_interactions=allowed_interactions,
            network_allowed=rng.choice((False, True)),
            allow_unverified=rng.choice((False, False, True)),
            forbidden_resources=[
                resource.id for resource in rng.sample(resources, forbidden_count)
            ],
        ),
        workstreams=[_synthetic_workstream(rng, index) for index in range(rng.randint(3, 8))],
    )
    inventory = Inventory(
        inventory_kind="personal",
        preferences=Preferences(
            maximum_supporting_resources=rng.choice((0, 1)),
            stale_after_days=rng.choice((30, 60, 90, 180)),
        ),
        resources=resources,
    )
    return inventory, project


def _assert_hard_gates_pass(
    resource: Resource,
    inventory: Inventory,
    project: ProjectBrief,
) -> None:
    constraints = project.constraints
    assert resource.id not in constraints.forbidden_resources
    assert resource.access.status is not AccessStatus.INACTIVE
    assert resource.access.current_session is not SessionAvailability.UNAVAILABLE
    assert resource.economics.quota is not QuotaStatus.EXHAUSTED
    assert constraints.data_class in resource.policy.allowed_data_classes
    assert resource.access.interaction in constraints.allowed_interactions
    assert constraints.network_allowed or not resource.policy.requires_network
    assert resource.economics.marginal_cost <= constraints.max_marginal_cost
    if not constraints.allow_unverified:
        assert resource.access.status is not AccessStatus.UNKNOWN
        assert resource.access.current_session is not SessionAvailability.UNKNOWN
        assert resource.economics.quota is not QuotaStatus.UNKNOWN
        assert resource.provenance.basis is not ConfidenceBasis.UNKNOWN
        assert resource.provenance.last_verified is not None
        age = (project.as_of - resource.provenance.last_verified).days
        assert 0 <= age <= inventory.preferences.stale_after_days


def _assert_assignment_invariants(
    assignment: RouteAssignment,
    inventory: Inventory,
    project: ProjectBrief,
) -> None:
    resources = {resource.id: resource for resource in inventory.resources}
    workstream = next(item for item in project.workstreams if item.id == assignment.workstream_id)
    candidate_ids = [candidate.resource_id for candidate in assignment.candidates]
    assert set(candidate_ids) == set(resources)
    assert len(candidate_ids) == len(set(candidate_ids)) == len(resources)

    if assignment.primary is None:
        assert assignment.gap_reason
        assert not any(candidate.eligible_for_role for candidate in assignment.candidates)
        assert assignment.support is None
        assert assignment.alternate is None
        assert assignment.handoffs == []
        return

    assert assignment.gap_reason is None
    selected_ids = {assignment.primary.resource_id}
    primary = resources[assignment.primary.resource_id]
    _assert_hard_gates_pass(primary, inventory, project)
    primary_evaluation = next(
        candidate
        for candidate in assignment.candidates
        if candidate.resource_id == assignment.primary.resource_id
    )
    assert primary_evaluation.eligible_for_role

    if assignment.support is None:
        assert assignment.support_gap == []
        assert all(
            primary.capabilities.get(requirement.id, 0.0) >= requirement.minimum
            for requirement in workstream.required_capabilities
        )
    else:
        support = resources[assignment.support.resource_id]
        selected_ids.add(support.id)
        _assert_hard_gates_pass(support, inventory, project)
        assert assignment.support_evaluation is not None
        assert assignment.support_evaluation.eligible_for_role
        assert workstream.support.allowed
        assert inventory.preferences.maximum_supporting_resources == 1
        assert assignment.support_gap
        assert set(assignment.support_gap) <= set(workstream.support.capability_gaps)
        assert all(
            max(
                primary.capabilities.get(requirement.id, 0.0),
                support.capabilities.get(requirement.id, 0.0),
            )
            >= requirement.minimum
            for requirement in workstream.required_capabilities
        )
        assert all(
            support.capabilities.get(capability, 0.0) > primary.capabilities.get(capability, 0.0)
            for capability in assignment.support_gap
        )

    alternate_gap_codes = {gap.code for gap in assignment.unresolved_gaps}
    if assignment.alternate is None:
        assert (REQUIRED_ALTERNATE_GAP in alternate_gap_codes) is workstream.alternate_required
    else:
        alternate = resources[assignment.alternate.resource_id]
        selected_ids.add(alternate.id)
        _assert_hard_gates_pass(alternate, inventory, project)
        assert assignment.alternate_evaluation is not None
        assert assignment.alternate_evaluation.eligible_for_role
        assert workstream.alternate_required or (
            primary.access.status is AccessStatus.LIMITED
            or primary.economics.quota is QuotaStatus.LIMITED
        )
        assert all(
            alternate.capabilities.get(requirement.id, 0.0) >= requirement.minimum
            for requirement in workstream.required_capabilities
        )
        assert REQUIRED_ALTERNATE_GAP not in alternate_gap_codes

    assert len(selected_ids) == 1 + (assignment.support is not None) + (
        assignment.alternate is not None
    )


@pytest.mark.parametrize("seed", range(32))
def test_seeded_routing_is_repeatable_complete_and_eligible(seed: int) -> None:
    inventory, project = _synthetic_case(seed)
    inventory_before = inventory.model_dump(mode="json")
    project_before = project.model_dump(mode="json")

    first = route(inventory, project)
    repeated = route(inventory, project)
    reordered = route(
        inventory.model_copy(update={"resources": list(reversed(inventory.resources))}),
        project,
    )

    assert first.model_dump(mode="json") == repeated.model_dump(mode="json")
    assert first.model_dump(mode="json") == reordered.model_dump(mode="json")
    assert inventory.model_dump(mode="json") == inventory_before
    assert project.model_dump(mode="json") == project_before
    assert len(first.assignments) == len(project.workstreams)
    assert {assignment.workstream_id for assignment in first.assignments} == {
        workstream.id for workstream in project.workstreams
    }
    assert len(first.dispositions) == len(inventory.resources)
    assert {item.resource_id for item in first.dispositions} == {
        resource.id for resource in inventory.resources
    }
    assert len({item.resource_id for item in first.dispositions}) == len(first.dispositions)

    for assignment in first.assignments:
        _assert_assignment_invariants(assignment, inventory, project)

    selected = {
        selection.resource_id
        for assignment in first.assignments
        for selection in (assignment.primary, assignment.support, assignment.alternate)
        if selection is not None
    }
    selected_statuses = {
        DispositionStatus.SELECTED_PRIMARY,
        DispositionStatus.SELECTED_SUPPORT,
        DispositionStatus.RESERVED_ALTERNATE,
    }
    assert {
        item.resource_id for item in first.dispositions if item.status in selected_statuses
    } == selected


def test_seeded_corpus_exercises_bounded_route_and_provenance_shapes() -> None:
    observed = {
        "gap": False,
        "support": False,
        "alternate": False,
        "unknown_provenance": False,
        "missing_provenance": False,
        "project_relative_future_provenance": False,
        "provenance_unknown_gate": False,
    }
    case_count = 0

    for seed in range(96):
        inventory, project = _synthetic_case(seed)
        plan = route(inventory, project)
        case_count += 1
        assert 8 <= len(inventory.resources) <= 16
        assert 3 <= len(project.workstreams) <= 8
        observed["gap"] |= any(assignment.primary is None for assignment in plan.assignments)
        observed["support"] |= any(
            assignment.support is not None for assignment in plan.assignments
        )
        observed["alternate"] |= any(
            assignment.alternate is not None for assignment in plan.assignments
        )
        observed["unknown_provenance"] |= any(
            resource.provenance.basis is ConfidenceBasis.UNKNOWN for resource in inventory.resources
        )
        observed["missing_provenance"] |= any(
            resource.provenance.last_verified is None for resource in inventory.resources
        )
        observed["project_relative_future_provenance"] |= any(
            resource.provenance.last_verified is not None
            and resource.provenance.last_verified > project.as_of
            for resource in inventory.resources
        )
        observed["provenance_unknown_gate"] |= any(
            "provenance-unknown" in candidate.gate_codes
            for assignment in plan.assignments
            for candidate in assignment.candidates
        )

    assert case_count == 96
    assert all(observed.values()), observed
