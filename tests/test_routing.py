from __future__ import annotations

import socket
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from atready.errors import ConfigurationError
from atready.models import (
    Access,
    AccessStatus,
    BillingModel,
    CapabilityRequirement,
    DataClass,
    Economics,
    Handoff,
    HandoffMethod,
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
    RoutingWeights,
    SessionAvailability,
    SupportPolicy,
    Workstream,
)
from atready.render import render_markdown
from atready.routing import route

TODAY = date(2026, 8, 6)


def _resource(
    resource_id: str,
    capabilities: dict[str, float],
    *,
    quality: float = 0.7,
    cost: float = 0.1,
    status: AccessStatus = AccessStatus.ACTIVE,
    quota: QuotaStatus = QuotaStatus.AMPLE,
    data_classes: list[DataClass] | None = None,
    handoff: Handoff | None = None,
    approval_required: bool = True,
) -> Resource:
    return Resource(
        id=resource_id,
        name=resource_id.title(),
        categories=["synthetic-tool"],
        capabilities=capabilities,
        access=Access(
            status=status,
            interaction=InteractionMode.LOCAL_CLI,
            current_session=SessionAvailability.AVAILABLE,
        ),
        economics=Economics(marginal_cost=cost, quota=quota),
        ratings=Ratings(
            quality=quality,
            speed=quality,
            autonomy=quality,
            privacy=quality,
            reliability=quality,
            confidence=quality,
            context_switch_cost=0.1,
            integration_friction=0.1,
        ),
        policy=Policy(
            allowed_data_classes=data_classes or [DataClass.PUBLIC],
            approval_required=approval_required,
        ),
        provenance=Provenance(basis="observed", last_verified=TODAY),
        handoff=handoff or Handoff(),
    )


def _workstream(
    workstream_id: str,
    requirements: list[tuple[str, float, float]],
    *,
    support: SupportPolicy | None = None,
    alternate_required: bool = False,
    verification: str = "pytest",
) -> Workstream:
    return Workstream(
        id=workstream_id,
        name=workstream_id.title(),
        objective=f"Complete {workstream_id}",
        required_capabilities=[
            CapabilityRequirement(id=name, importance=importance, minimum=minimum)
            for name, importance, minimum in requirements
        ],
        inputs=["Synthetic input"],
        allowed_scope=["synthetic/scope"],
        exclusions=["External side effects"],
        deliverable="Synthetic deliverable",
        acceptance_criteria=["Deterministic result"],
        verification=[verification],
        stop_conditions=["Constraint changes"],
        next_owner="Human reviewer",
        support=support or SupportPolicy(),
        alternate_required=alternate_required,
    )


def _project(
    workstreams: list[Workstream],
    *,
    data_class: DataClass = DataClass.PUBLIC,
) -> ProjectBrief:
    return ProjectBrief(
        id="synthetic-project",
        name="Synthetic Project",
        goal="Test deterministic routing",
        as_of=TODAY,
        constraints=ProjectConstraints(data_class=data_class),
        workstreams=workstreams,
    )


def _inventory(
    resources: list[Resource] | None = None,
    *,
    preferences: Preferences | None = None,
) -> Inventory:
    values = {"inventory_kind": "personal", "resources": resources or []}
    if preferences is not None:
        values["preferences"] = preferences
    return Inventory.model_validate(values)


def test_empty_personal_inventory_cannot_route() -> None:
    project = _project([_workstream("build", [("build", 1.0, 0.5)])])

    with pytest.raises(ConfigurationError, match="personal inventory has no resources"):
        route(_inventory(), project)


def test_demo_inventory_requires_opt_in_and_stays_visible_in_plan() -> None:
    project = _project([_workstream("build", [("build", 1.0, 0.5)])])
    inventory = Inventory(
        inventory_kind="demo",
        resources=[_resource("demo-builder", {"build": 0.9})],
    )

    with pytest.raises(ConfigurationError, match="allow_demo=True in the API"):
        route(inventory, project)

    plan = route(inventory, project, allow_demo=True)
    assert plan.assignments[0].primary.resource_id == "demo-builder"
    assert plan.warnings[0] == (
        "[demo-inventory] this inventory is labeled demo; its user-controlled contents are not "
        "verified as synthetic or as personal access"
    )


def test_resource_order_does_not_change_plan_or_hash() -> None:
    alpha = _resource("alpha", {"build": 0.9})
    zeta = _resource("zeta", {"build": 0.9})
    project = _project([_workstream("build", [("build", 1.0, 0.5)])])

    forward = route(_inventory([alpha, zeta]), project)
    reversed_plan = route(_inventory([zeta, alpha]), project)

    assert forward.plan_id == reversed_plan.plan_id
    assert forward.model_dump(mode="json") == reversed_plan.model_dump(mode="json")
    assert forward.assignments[0].primary.resource_id == "alpha"
    assert "component/resource-ID tie-break chain resolved the tie" in render_markdown(forward)


def test_billing_and_best_avoid_metadata_do_not_change_route_semantics() -> None:
    baseline_resource = _resource("only", {"build": 0.9})
    descriptive_variant = baseline_resource.model_copy(
        update={
            "economics": baseline_resource.economics.model_copy(
                update={"billing": BillingModel.USAGE}
            ),
            "best_for": ["descriptive recommendation only"],
            "avoid_for": ["descriptive caution only"],
        }
    )
    project = _project([_workstream("build", [("build", 1.0, 0.5)])])

    baseline = route(_inventory([baseline_resource]), project)
    variant = route(_inventory([descriptive_variant]), project)

    assert baseline.inventory_fingerprint == variant.inventory_fingerprint
    assert baseline.plan_id == variant.plan_id
    assert baseline.assignments == variant.assignments


@pytest.mark.parametrize("approval_required", [True, False])
def test_declared_approval_requirement_is_preserved_in_handoff_without_affecting_score(
    approval_required: bool,
) -> None:
    resource = _resource(
        "only",
        {"build": 0.9},
        approval_required=approval_required,
    )
    project = _project([_workstream("build", [("build", 1.0, 0.5)])])

    plan = route(_inventory([resource]), project)
    handoff = plan.assignments[0].handoffs[0]

    assert handoff.declared_resource_approval_required is approval_required
    assert plan.assignments[0].primary.score_bp == 7830
    assert handoff.activation_condition == "Run only after the user authorizes this route."


@pytest.mark.parametrize("value", [0.000001, 0.000049])
def test_routing_weight_below_one_basis_point_is_rejected(value: float) -> None:
    values = {name: 0.0 for name in RoutingWeights.model_fields}
    values["capability_fit"] = value

    with pytest.raises(ValidationError) as caught:
        RoutingWeights.model_validate(values)

    assert caught.value.errors(include_url=False)[0]["loc"] == ("capability_fit",)
    assert "zero or at least one basis point" in str(caught.value)


def test_capability_importance_below_one_basis_point_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        CapabilityRequirement(id="build", importance=0.000049, minimum=0.5)

    assert caught.value.errors(include_url=False)[0]["loc"] == ("importance",)
    assert "greater than or equal to 0.0001" in str(caught.value)


def test_positive_support_gain_below_one_basis_point_is_rejected() -> None:
    with pytest.raises(ValidationError) as caught:
        SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.000049,
        )

    assert caught.value.errors(include_url=False)[0]["loc"] == ("minimum_gain",)
    assert "zero or at least one basis point" in str(caught.value)


def test_one_basis_point_weights_and_importance_route_without_arithmetic_failure() -> None:
    values = {name: 0.0 for name in RoutingWeights.model_fields}
    values["capability_fit"] = 0.0001
    inventory = _inventory(
        [_resource("only", {"build": 0.9})],
        preferences=Preferences(weights=RoutingWeights.model_validate(values)),
    )
    project = _project([_workstream("build", [("build", 0.0001, 0.5)])])

    plan = route(inventory, project)

    assert plan.assignments[0].primary.resource_id == "only"


def test_route_defensively_rejects_zero_quantized_weight_denominator() -> None:
    invalid_weights = RoutingWeights.model_construct(
        **{name: 0.0 for name in RoutingWeights.model_fields}
    )
    preferences = Preferences().model_copy(update={"weights": invalid_weights})
    inventory = _inventory([_resource("only", {"build": 0.9})], preferences=preferences)
    project = _project([_workstream("build", [("build", 1.0, 0.5)])])

    with pytest.raises(ConfigurationError, match="routing weights"):
        route(inventory, project)


def test_route_defensively_rejects_zero_quantized_importance_denominator() -> None:
    invalid_requirement = CapabilityRequirement.model_construct(
        id="build", importance=0.000001, minimum=0.5
    )
    workstream = _workstream("build", [("build", 1.0, 0.5)]).model_copy(
        update={"required_capabilities": [invalid_requirement]}
    )

    with pytest.raises(ConfigurationError, match="capability importance"):
        route(_inventory([_resource("only", {"build": 0.9})]), _project([workstream]))


def test_hard_data_gate_beats_higher_score() -> None:
    unsafe = _resource("unsafe", {"build": 1.0}, quality=1.0)
    safe = _resource(
        "safe",
        {"build": 0.8},
        quality=0.6,
        data_classes=[DataClass.PUBLIC, DataClass.PRIVATE],
    )
    project = _project(
        [_workstream("build", [("build", 1.0, 0.5)])],
        data_class=DataClass.PRIVATE,
    )

    plan = route(_inventory([unsafe, safe]), project)

    assert plan.assignments[0].primary.resource_id == "safe"
    rejected = next(
        candidate
        for candidate in plan.assignments[0].candidates
        if candidate.resource_id == "unsafe"
    )
    assert rejected.eligible_for_role is False
    assert rejected.gate_codes == ["data-class-disallowed"]


def test_continuity_bonus_reuses_equivalent_primary() -> None:
    alpha = _resource("alpha", {"first": 0.9, "second": 0.9})
    beta = _resource("beta", {"first": 0.9, "second": 0.9})
    project = _project(
        [
            _workstream("first", [("first", 1.0, 0.5)]),
            _workstream("second", [("second", 1.0, 0.5)]),
        ]
    )

    plan = route(_inventory([beta, alpha]), project)

    assert [assignment.primary.resource_id for assignment in plan.assignments] == ["alpha", "alpha"]
    second_alpha = next(
        candidate
        for candidate in plan.assignments[1].candidates
        if candidate.resource_id == "alpha"
    )
    assert [(item.code, item.basis_points) for item in second_alpha.adjustments] == [
        ("same-primary-continuity", 400)
    ]


def test_primary_continuity_does_not_distort_reserved_alternate_ranking() -> None:
    previous = _resource(
        "previous",
        {"first": 1.0, "second": 0.6},
        quality=0.8,
    )
    stronger_alternate = _resource(
        "stronger-alternate",
        {"first": 0.1, "second": 0.8},
        quality=0.8,
    )
    current = _resource(
        "current",
        {"first": 0.1, "second": 1.0},
        quality=1.0,
    )
    project = _project(
        [
            _workstream("first", [("first", 1.0, 0.5)]),
            _workstream(
                "second",
                [("second", 1.0, 0.5)],
                alternate_required=True,
            ),
        ]
    )

    plan = route(_inventory([previous, stronger_alternate, current]), project)
    assignment = plan.assignments[1]

    assert plan.assignments[0].primary.resource_id == "previous"
    assert assignment.primary.resource_id == "current"
    assert assignment.alternate.resource_id == "stronger-alternate"
    assert assignment.alternate_evaluation.adjustments == []


def test_primary_continuity_does_not_distort_equal_gain_support_ranking() -> None:
    current = _resource(
        "current",
        {"first": 0.1, "build": 0.9, "review": 0.1},
        quality=1.0,
    )
    alphabetical_support = _resource(
        "alphabetical-support",
        {"first": 0.1, "build": 0.1, "review": 0.9},
        quality=0.2,
    )
    previous = _resource(
        "previous",
        {"first": 1.0, "build": 0.1, "review": 0.9},
        quality=0.2,
    )
    project = _project(
        [
            _workstream("first", [("first", 1.0, 0.5)]),
            _workstream(
                "delivery",
                [("build", 1.0, 0.6), ("review", 1.0, 0.6)],
                support=SupportPolicy(
                    allowed=True,
                    capability_gaps=["review"],
                    minimum_gain=0.08,
                ),
            ),
        ]
    )

    plan = route(
        _inventory([previous, alphabetical_support, current]),
        project,
    )
    assignment = plan.assignments[1]

    assert plan.assignments[0].primary.resource_id == "previous"
    assert assignment.primary.resource_id == "current"
    assert assignment.support.resource_id == "alphabetical-support"
    assert assignment.support_evaluation.adjustments == []


def test_support_requires_named_gap_and_minimum_gain() -> None:
    primary = _resource("primary", {"build": 0.9, "review": 0.5}, quality=1.0)
    support = _resource("support", {"build": 0.6, "review": 0.9}, quality=0.2)
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.4), ("review", 1.0, 0.4)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
    )

    plan = route(_inventory([primary, support]), _project([workstream]))
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "primary"
    assert assignment.support.resource_id == "support"
    assert assignment.support_gap == ["review"]
    assert [packet.role for packet in assignment.handoffs] == ["primary", "support"]

    stricter = workstream.model_copy(
        update={
            "support": SupportPolicy(
                allowed=True,
                capability_gaps=["review"],
                minimum_gain=0.25,
            )
        }
    )
    no_support = route(_inventory([primary, support]), _project([stricter]))
    assert no_support.assignments[0].support is None
    assert [packet.role for packet in no_support.assignments[0].handoffs] == ["primary"]


def test_complementary_specialist_can_close_a_declared_primary_gap() -> None:
    builder = _resource("builder", {"build": 0.9, "review": 0.1}, quality=1.0)
    reviewer = _resource("reviewer", {"build": 0.1, "review": 0.9}, quality=0.2)
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.6), ("review", 1.0, 0.6)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
    )

    plan = route(_inventory([reviewer, builder]), _project([workstream]))
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "builder"
    assert assignment.support.resource_id == "reviewer"
    assert assignment.support_gap == ["review"]
    assert assignment.gap_reason is None
    assert [packet.role for packet in assignment.handoffs] == ["primary", "support"]
    support_evaluation = assignment.support_evaluation
    assert support_evaluation is not None
    assert support_evaluation.role == "support"
    assert support_evaluation.eligible_for_role is True
    assert support_evaluation.adjusted_score_bp == assignment.support.score_bp
    assert support_evaluation.covered_capability_gaps == ["review"]
    assert support_evaluation.combined_fit_bp == 9000
    assert support_evaluation.fit_gain_bp == 4000


def test_support_pair_must_meet_every_combined_capability_minimum() -> None:
    builder = _resource("builder", {"build": 0.9, "review": 0.1}, quality=1.0)
    weak_reviewer = _resource("weak-reviewer", {"build": 0.1, "review": 0.55})
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.6), ("review", 1.0, 0.6)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.0,
        ),
    )

    plan = route(_inventory([builder, weak_reviewer]), _project([workstream]))

    assert plan.assignments[0].primary is None
    assert plan.assignments[0].gap_reason


def test_infeasible_relaxed_primary_is_skipped_for_a_standalone_generalist() -> None:
    incomplete = _resource("incomplete", {"build": 0.95, "review": 0.1}, quality=1.0)
    generalist = _resource("generalist", {"build": 0.7, "review": 0.7}, quality=0.4)
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.6), ("review", 1.0, 0.6)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.31,
        ),
    )

    plan = route(_inventory([incomplete, generalist]), _project([workstream]))
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "generalist"
    rejected = next(item for item in assignment.candidates if item.resource_id == "incomplete")
    assert rejected.eligible_for_role is False
    assert "support-combination-unavailable" in rejected.gate_codes


def test_support_must_independently_pass_non_capability_gates() -> None:
    builder = _resource(
        "builder",
        {"build": 0.9, "review": 0.1},
        quality=1.0,
        data_classes=[DataClass.PUBLIC, DataClass.PRIVATE],
    )
    public_only_reviewer = _resource(
        "public-reviewer",
        {"build": 0.1, "review": 0.9},
        data_classes=[DataClass.PUBLIC],
    )
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.6), ("review", 1.0, 0.6)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
    )

    plan = route(
        _inventory([builder, public_only_reviewer]),
        _project([workstream], data_class=DataClass.PRIVATE),
    )

    assert plan.assignments[0].primary is None
    assert plan.assignments[0].gap_reason


def test_mandatory_support_is_not_discarded_to_reserve_an_alternate() -> None:
    builder = _resource("builder", {"build": 0.9, "review": 0.1}, quality=1.0)
    reviewer = _resource("reviewer", {"build": 0.1, "review": 0.9}, quality=0.2)
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.6), ("review", 1.0, 0.6)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
        alternate_required=True,
    )

    plan = route(_inventory([builder, reviewer]), _project([workstream]))
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "builder"
    assert assignment.support.resource_id == "reviewer"
    assert assignment.alternate is None
    assert assignment.unresolved_gaps[0].code == "required-alternate-unavailable"


def test_optional_support_is_retained_when_no_standalone_alternate_exists() -> None:
    primary = _resource("primary", {"build": 0.9, "review": 0.5}, quality=1.0)
    support = _resource("support", {"build": 0.1, "review": 0.9}, quality=0.2)
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.4), ("review", 1.0, 0.4)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
        alternate_required=True,
    )

    plan = route(_inventory([primary, support]), _project([workstream]))
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "primary"
    assert assignment.support.resource_id == "support"
    assert assignment.support_gap == ["review"]
    assert assignment.alternate is None
    assert assignment.unresolved_gaps[0].code == "required-alternate-unavailable"
    assert [packet.role for packet in assignment.handoffs] == ["primary", "support"]


@pytest.mark.parametrize(
    ("blocker", "gate_code", "expected_disposition"),
    [
        ("forbidden", "resource-forbidden", "ineligible"),
        ("inactive", "access-inactive", "unavailable"),
        ("session", "session-unavailable", "unavailable"),
        ("quota", "quota-exhausted", "unavailable"),
        ("interaction", "interaction-disallowed", "ineligible"),
        ("network", "network-disallowed", "ineligible"),
        ("data-class", "data-class-disallowed", "ineligible"),
        ("capability", "capability-below-minimum", "ineligible"),
    ],
)
def test_degraded_hard_gate_maps_to_candidate_and_disposition(
    blocker: str,
    gate_code: str,
    expected_disposition: str,
) -> None:
    blocked = _resource("blocked", {"build": 0.9}, quality=1.0)
    eligible = _resource("eligible", {"build": 0.8}, quality=0.5)
    constraints = ProjectConstraints()

    if blocker == "forbidden":
        constraints = constraints.model_copy(update={"forbidden_resources": ["blocked"]})
    elif blocker == "inactive":
        blocked = _resource(
            "blocked",
            {"build": 0.9},
            quality=1.0,
            status=AccessStatus.INACTIVE,
        )
    elif blocker == "session":
        blocked = blocked.model_copy(
            update={
                "access": blocked.access.model_copy(
                    update={"current_session": SessionAvailability.UNAVAILABLE}
                )
            }
        )
    elif blocker == "quota":
        blocked = _resource(
            "blocked",
            {"build": 0.9},
            quality=1.0,
            quota=QuotaStatus.EXHAUSTED,
        )
    elif blocker == "interaction":
        constraints = constraints.model_copy(
            update={"allowed_interactions": [InteractionMode.MANUAL]}
        )
        eligible = eligible.model_copy(
            update={
                "access": eligible.access.model_copy(update={"interaction": InteractionMode.MANUAL})
            }
        )
    elif blocker == "network":
        blocked = blocked.model_copy(
            update={"policy": blocked.policy.model_copy(update={"requires_network": True})}
        )
        constraints = constraints.model_copy(update={"network_allowed": False})
    elif blocker == "data-class":
        constraints = constraints.model_copy(update={"data_class": DataClass.PRIVATE})
        eligible = eligible.model_copy(
            update={
                "policy": eligible.policy.model_copy(
                    update={"allowed_data_classes": [DataClass.PUBLIC, DataClass.PRIVATE]}
                )
            }
        )
    elif blocker == "capability":
        blocked = blocked.model_copy(update={"capabilities": {"build": 0.4}})

    project = _project([_workstream("build", [("build", 1.0, 0.5)])]).model_copy(
        update={"constraints": constraints}
    )
    plan = route(_inventory([blocked, eligible]), project)
    assignment = plan.assignments[0]
    blocked_candidate = next(
        candidate for candidate in assignment.candidates if candidate.resource_id == "blocked"
    )
    blocked_disposition = next(
        disposition for disposition in plan.dispositions if disposition.resource_id == "blocked"
    )

    assert assignment.primary.resource_id == "eligible"
    assert blocked_candidate.gate_codes == [gate_code]
    assert blocked_disposition.status.value == expected_disposition
    assert blocked_disposition.reason_code == gate_code


def test_resource_handoff_configuration_is_preserved_in_inert_packet() -> None:
    resource = _resource(
        "primary",
        {"build": 0.9},
        handoff=Handoff(
            method=HandoffMethod.FILE_EXPORT,
            instructions="Export one reviewed synthetic patch.",
        ),
    )
    plan = route(
        _inventory([resource]),
        _project([_workstream("delivery", [("build", 1.0, 0.4)])]),
    )

    packet = plan.assignments[0].handoffs[0]
    assert packet.handoff_method is HandoffMethod.FILE_EXPORT
    assert packet.handoff_instructions == "Export one reviewed synthetic patch."
    rendered = render_markdown(plan)
    assert "Handoff method: `file-export`" in rendered
    assert "Export one reviewed synthetic patch." in rendered


def test_inventory_support_limit_zero_prevents_support_selection() -> None:
    primary = _resource("primary", {"build": 0.9, "review": 0.5}, quality=1.0)
    support = _resource("support", {"build": 0.6, "review": 0.9}, quality=0.2)
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.4), ("review", 1.0, 0.4)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
    )

    plan = route(
        _inventory(
            [primary, support],
            preferences=Preferences(maximum_supporting_resources=0),
        ),
        _project([workstream]),
    )
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "primary"
    assert assignment.support is None
    assert assignment.support_gap == []
    assert [packet.role for packet in assignment.handoffs] == ["primary"]


def test_limited_primary_gets_reserved_alternate_and_complete_dispositions() -> None:
    limited = _resource(
        "limited",
        {"build": 1.0},
        quality=1.0,
        status=AccessStatus.LIMITED,
        quota=QuotaStatus.LIMITED,
    )
    alternate = _resource("alternate", {"build": 0.7}, quality=0.5)
    unused = _resource("unused", {"build": 0.6}, quality=0.3)

    plan = route(
        _inventory([unused, alternate, limited]),
        _project([_workstream("build", [("build", 1.0, 0.5)])]),
    )
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "limited"
    assert assignment.alternate.resource_id == "alternate"
    assert assignment.alternate_evaluation is not None
    assert assignment.alternate_evaluation.role == "alternate"
    assert assignment.alternate_evaluation.eligible_for_role is True
    assert assignment.alternate_evaluation.adjusted_score_bp == assignment.alternate.score_bp
    assert [packet.role for packet in assignment.handoffs] == ["primary", "alternate"]
    assert len(plan.dispositions) == 3
    assert {item.resource_id for item in plan.dispositions} == {"limited", "alternate", "unused"}
    assert len({item.resource_id for item in plan.dispositions}) == len(plan.dispositions)

    invalid = assignment.model_dump(mode="python")
    invalid["alternate_activation_condition"] = None
    with pytest.raises(ValidationError, match="selected alternate requires"):
        RouteAssignment.model_validate(invalid)

    invalid["alternate_activation_condition"] = "   "
    with pytest.raises(ValidationError, match="at least 1 character"):
        RouteAssignment.model_validate(invalid)


def test_assignment_requires_selected_primary_to_have_a_matching_trace() -> None:
    plan = route(
        _inventory([_resource("primary", {"build": 1.0})]),
        _project([_workstream("build", [("build", 1.0, 0.5)])]),
    )
    invalid = plan.assignments[0].model_dump(mode="python")
    invalid["candidates"] = []

    with pytest.raises(ValidationError, match="selected primary requires"):
        RouteAssignment.model_validate(invalid)


def test_assignment_rejects_detached_selected_support_evaluation() -> None:
    builder = _resource("builder", {"build": 0.9, "review": 0.1}, quality=1.0)
    reviewer = _resource("reviewer", {"build": 0.1, "review": 0.9}, quality=0.2)
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.6), ("review", 1.0, 0.6)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
    )
    assignment = route(
        _inventory([builder, reviewer]),
        _project([workstream]),
    ).assignments[0]
    invalid = assignment.model_dump(mode="python")
    invalid["candidates"] = [
        candidate
        for candidate in invalid["candidates"]
        if candidate["resource_id"] != assignment.support.resource_id
    ]

    with pytest.raises(ValidationError, match="selected support requires"):
        RouteAssignment.model_validate(invalid)


def test_assignment_rejects_detached_selected_alternate_evaluation() -> None:
    limited = _resource(
        "limited",
        {"build": 1.0},
        status=AccessStatus.LIMITED,
        quota=QuotaStatus.LIMITED,
    )
    alternate = _resource("alternate", {"build": 0.7}, quality=0.5)
    assignment = route(
        _inventory([limited, alternate]),
        _project([_workstream("build", [("build", 1.0, 0.5)])]),
    ).assignments[0]
    invalid = assignment.model_dump(mode="python")
    invalid["candidates"] = [
        candidate
        for candidate in invalid["candidates"]
        if candidate["resource_id"] != assignment.alternate.resource_id
    ]

    with pytest.raises(ValidationError, match="selected alternate requires"):
        RouteAssignment.model_validate(invalid)


def test_assignment_rejects_mismatched_alternate_handoff_activation_condition() -> None:
    limited = _resource(
        "limited",
        {"build": 1.0},
        status=AccessStatus.LIMITED,
        quota=QuotaStatus.LIMITED,
    )
    alternate = _resource("alternate", {"build": 0.7}, quality=0.5)
    assignment = route(
        _inventory([limited, alternate]),
        _project([_workstream("build", [("build", 1.0, 0.5)])]),
    ).assignments[0]
    invalid = assignment.model_dump(mode="python")
    alternate_handoff = next(
        handoff for handoff in invalid["handoffs"] if handoff["role"] == "alternate"
    )
    alternate_handoff["activation_condition"] = "Contradictory activation condition."

    with pytest.raises(ValidationError, match="assignment activation condition"):
        RouteAssignment.model_validate(invalid)


def test_required_alternate_without_candidate_preserves_primary_and_records_gap() -> None:
    primary = _resource("primary", {"build": 1.0})
    workstream = _workstream(
        "build",
        [("build", 1.0, 0.5)],
        alternate_required=True,
    )

    plan = route(_inventory([primary]), _project([workstream]))
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "primary"
    assert assignment.alternate is None
    assert assignment.unresolved_gaps[0].code == "required-alternate-unavailable"
    assert assignment.unresolved_gaps[0].reason == (
        "An alternate is required, but no additional standalone-eligible resource remains "
        "after primary and support selection."
    )
    assert plan.warnings == [
        "[required-alternate-unavailable] workstream 'build' requires an alternate, but no "
        "additional standalone-eligible resource remains after primary and support selection"
    ]


def test_required_alternate_takes_priority_when_only_alternate_could_support() -> None:
    primary = _resource("primary", {"build": 0.9, "review": 0.5}, quality=1.0)
    alternate = _resource("alternate", {"build": 0.6, "review": 0.9}, quality=0.2)
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.4), ("review", 1.0, 0.4)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
        alternate_required=True,
    )

    plan = route(_inventory([primary, alternate]), _project([workstream]))
    assignment = plan.assignments[0]

    assert assignment.primary.resource_id == "primary"
    assert assignment.support is None
    assert assignment.support_gap == []
    assert assignment.alternate.resource_id == "alternate"
    assert assignment.unresolved_gaps == []
    assert [packet.role for packet in assignment.handoffs] == ["primary", "alternate"]


def test_allowed_unverified_selected_resources_emit_role_specific_warnings() -> None:
    primary = _resource("primary", {"build": 0.9, "review": 0.5}, quality=1.0)
    support = _resource("support", {"build": 0.6, "review": 0.9}, quality=0.2).model_copy(
        update={
            "access": Access(
                status=AccessStatus.UNKNOWN,
                interaction=InteractionMode.LOCAL_CLI,
                current_session=SessionAvailability.UNKNOWN,
            ),
            "economics": Economics(marginal_cost=0.1, quota=QuotaStatus.UNKNOWN),
            "provenance": Provenance(basis="unknown", last_verified=date(2026, 1, 1)),
        }
    )
    alternate = _resource("alternate", {"build": 0.7, "review": 0.7}, quality=0.1).model_copy(
        update={"provenance": Provenance(basis="observed", last_verified=date(2026, 1, 1))}
    )
    workstream = _workstream(
        "delivery",
        [("build", 1.0, 0.4), ("review", 1.0, 0.4)],
        support=SupportPolicy(
            allowed=True,
            capability_gaps=["review"],
            minimum_gain=0.08,
        ),
        alternate_required=True,
    )
    project = _project([workstream]).model_copy(
        update={"constraints": ProjectConstraints(allow_unverified=True)}
    )

    plan = route(_inventory([primary, support, alternate]), project)
    rendered = render_markdown(plan)
    serialized = plan.model_dump_json()

    assert [plan.assignments[0].support.resource_id, plan.assignments[0].alternate.resource_id] == [
        "support",
        "alternate",
    ]
    assert plan.warnings == [
        "[selected-unverified-resource] workstream 'delivery' selected support resource "
        "'support' with allowed unverified state: stale-provenance, unknown-access, "
        "unknown-provenance, unknown-quota, unknown-session",
        "[selected-unverified-resource] workstream 'delivery' selected alternate resource "
        "'alternate' with allowed unverified state: stale-provenance",
    ]
    for code in (
        "stale-provenance",
        "unknown-access",
        "unknown-provenance",
        "unknown-quota",
        "unknown-session",
    ):
        assert code in serialized
        assert code in rendered


def test_allowed_stale_primary_emits_warning_without_becoming_a_gap() -> None:
    primary = _resource("primary", {"build": 1.0}).model_copy(
        update={"provenance": Provenance(basis="observed", last_verified=date(2026, 1, 1))}
    )
    project = _project([_workstream("build", [("build", 1.0, 0.5)])]).model_copy(
        update={"constraints": ProjectConstraints(allow_unverified=True)}
    )

    plan = route(_inventory([primary]), project)

    assert plan.assignments[0].primary.resource_id == "primary"
    assert plan.assignments[0].unresolved_gaps == []
    assert plan.warnings == [
        "[selected-unverified-resource] workstream 'build' selected primary resource "
        "'primary' with allowed unverified state: stale-provenance"
    ]


def test_allowed_post_as_of_verification_emits_unknown_provenance_warning() -> None:
    primary = _resource("primary", {"build": 1.0})
    project = _project([_workstream("build", [("build", 1.0, 0.5)])]).model_copy(
        update={
            "as_of": date(2026, 8, 5),
            "constraints": ProjectConstraints(allow_unverified=True),
        }
    )

    plan = route(_inventory([primary]), project)

    assert plan.warnings == [
        "[selected-unverified-resource] workstream 'build' selected primary resource "
        "'primary' with allowed unverified state: unknown-provenance"
    ]


def test_gap_has_no_packet_and_route_never_uses_socket(monkeypatch) -> None:
    def fail_network(*_args, **_kwargs):
        raise AssertionError("network access is outside the routing core")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    resource = _resource("coder", {"code": 1.0})
    project = _project([_workstream("music", [("audio", 1.0, 0.5)])])

    plan = route(_inventory([resource]), project)

    assert plan.assignments[0].primary is None
    assert plan.assignments[0].gap_reason
    assert plan.assignments[0].handoffs == []
    assert plan.warnings == ["workstream 'music' is an unresolved capability gap"]


def test_shell_looking_verification_is_rendered_but_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist"
    command = f"touch {marker}"
    resource = _resource("alpha", {"build": 1.0})
    project = _project([_workstream("build", [("build", 1.0, 0.5)], verification=command)])

    rendered = render_markdown(route(_inventory([resource]), project))

    assert command in rendered
    assert "Verification (display only)" in rendered
    assert "This route is advisory" in rendered
    assert not marker.exists()
