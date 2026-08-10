"""Pure, deterministic routing from validated inventory and project contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from atready.catalog import InventoryCatalog
from atready.errors import ConfigurationError
from atready.models import (
    AccessStatus,
    CandidateEvaluation,
    ConfidenceBasis,
    DispositionStatus,
    HandoffPacket,
    Inventory,
    InventoryKind,
    ProjectBrief,
    QuotaStatus,
    Resource,
    ResourceDisposition,
    ResourceSelection,
    RouteAssignment,
    RoutePlan,
    ScoreAdjustment,
    SessionAvailability,
    UnresolvedRouteGap,
    Workstream,
)

_UNAVAILABLE_GATES = {"access-inactive", "session-unavailable", "quota-exhausted"}
_UNVERIFIED_GATES = {
    "access-unknown",
    "confidence-unknown",
    "provenance-stale",
    "provenance-unknown",
    "quota-unknown",
    "session-unknown",
}
_UNVERIFIED_ADJUSTMENTS = {
    "stale-provenance",
    "unknown-access",
    "unknown-provenance",
    "unknown-quota",
    "unknown-session",
}
_REQUIRED_ALTERNATE_GAP_CODE = "required-alternate-unavailable"
_REQUIRED_ALTERNATE_GAP_REASON = (
    "An alternate is required, but no additional standalone-eligible resource remains "
    "after primary and support selection."
)
_ALTERNATE_ACTIVATION_CONDITION = (
    "Re-check eligibility and obtain separate authorization if the primary cannot proceed."
)


@dataclass(frozen=True)
class _RoutingState:
    previous_primary: str | None
    used_primaries: frozenset[str]


def _basis_points(value: float) -> int:
    return int((Decimal(str(value)) * 10_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _weighted_score(components: dict[str, int], weights: dict[str, float]) -> int:
    weight_bp = {name: _basis_points(value) for name, value in weights.items()}
    denominator = sum(weight_bp.values())
    if denominator <= 0:
        raise ConfigurationError("routing weights must include at least one basis point")
    numerator = sum(components[name] * weight_bp[name] for name in weight_bp)
    return (numerator + denominator // 2) // denominator


def _capability_fit(resource: Resource, workstream: Workstream) -> int:
    weighted = 0
    total = 0
    for requirement in workstream.required_capabilities:
        importance = _basis_points(requirement.importance)
        weighted += _basis_points(resource.capabilities.get(requirement.id, 0.0)) * importance
        total += importance
    if total <= 0:
        raise ConfigurationError("capability importance must include at least one basis point")
    return (weighted + total // 2) // total


def _gate_resource(
    resource: Resource,
    project: ProjectBrief,
    workstream: Workstream,
    *,
    allowed_below_minimum: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    gates: list[str] = []
    notes: list[str] = []
    constraints = project.constraints

    if resource.id in constraints.forbidden_resources:
        gates.append("resource-forbidden")
    if resource.access.status is AccessStatus.INACTIVE:
        gates.append("access-inactive")
    elif resource.access.status is AccessStatus.UNKNOWN:
        gates.append("access-unknown")
    if resource.access.current_session is SessionAvailability.UNAVAILABLE:
        gates.append("session-unavailable")
    elif resource.access.current_session is SessionAvailability.UNKNOWN:
        gates.append("session-unknown")
    if resource.economics.quota is QuotaStatus.EXHAUSTED:
        gates.append("quota-exhausted")
    elif resource.economics.quota is QuotaStatus.UNKNOWN:
        gates.append("quota-unknown")
    if constraints.data_class not in resource.policy.allowed_data_classes:
        gates.append("data-class-disallowed")
    if resource.access.interaction not in constraints.allowed_interactions:
        gates.append("interaction-disallowed")
    if resource.policy.requires_network and not constraints.network_allowed:
        gates.append("network-disallowed")
    if resource.economics.marginal_cost > constraints.max_marginal_cost:
        gates.append("marginal-cost-exceeded")

    capability_scores = [
        resource.capabilities.get(item.id, 0.0) for item in workstream.required_capabilities
    ]
    if not any(score > 0 for score in capability_scores):
        gates.append("no-applicable-capability")
    else:
        missing = [
            requirement.id
            for requirement in workstream.required_capabilities
            if resource.capabilities.get(requirement.id, 0.0) < requirement.minimum
            and requirement.id not in allowed_below_minimum
        ]
        if missing:
            gates.append("capability-below-minimum")
            notes.append("below minimum: " + ", ".join(sorted(missing)))

    if resource.provenance.basis is ConfidenceBasis.UNKNOWN:
        gates.append("confidence-unknown")
    if resource.provenance.last_verified is None:
        gates.append("provenance-unknown")
    else:
        if (project.as_of - resource.provenance.last_verified).days < 0:
            gates.append("provenance-unknown")
            notes.append("last_verified is after project as_of")

    if constraints.allow_unverified:
        gates = [gate for gate in gates if gate not in _UNVERIFIED_GATES]
    return sorted(set(gates)), notes


def _evaluate_resource(
    resource: Resource,
    inventory: Inventory,
    project: ProjectBrief,
    workstream: Workstream,
    state: _RoutingState,
    *,
    role: str = "primary",
    allowed_below_minimum: frozenset[str] = frozenset(),
) -> CandidateEvaluation:
    gates, notes = _gate_resource(
        resource,
        project,
        workstream,
        allowed_below_minimum=allowed_below_minimum,
    )
    last_verified = resource.provenance.last_verified
    stale = bool(
        last_verified
        and (project.as_of - last_verified).days > inventory.preferences.stale_after_days
    )
    if stale and not project.constraints.allow_unverified:
        gates = sorted(set([*gates, "provenance-stale"]))
    if gates:
        return CandidateEvaluation(
            role=role,
            resource_id=resource.id,
            resource_name=resource.name,
            eligible_for_role=False,
            gate_codes=gates,
            notes=notes,
        )

    components = {
        "capability-fit": _capability_fit(resource, workstream),
        "quality": _basis_points(resource.ratings.quality),
        "cost-efficiency": 10_000 - _basis_points(resource.economics.marginal_cost),
        "speed": _basis_points(resource.ratings.speed),
        "autonomy": _basis_points(resource.ratings.autonomy),
        "privacy": _basis_points(resource.ratings.privacy),
        "reliability": _basis_points(resource.ratings.reliability),
        "confidence": _basis_points(resource.ratings.confidence),
        "low-context-switching": 10_000 - _basis_points(resource.ratings.context_switch_cost),
        "low-integration-friction": 10_000 - _basis_points(resource.ratings.integration_friction),
    }
    weight_values = inventory.preferences.weights.model_dump()
    weights = {name.replace("_", "-"): value for name, value in weight_values.items()}
    base = _weighted_score(components, weights)
    adjustments: list[ScoreAdjustment] = []
    if resource.access.status is AccessStatus.LIMITED:
        adjustments.append(ScoreAdjustment(code="limited-access", basis_points=-300))
    if resource.economics.quota is QuotaStatus.LIMITED:
        adjustments.append(ScoreAdjustment(code="limited-quota", basis_points=-200))
    if stale:
        adjustments.append(ScoreAdjustment(code="stale-provenance", basis_points=-500))
    if project.constraints.allow_unverified:
        if resource.access.status is AccessStatus.UNKNOWN:
            adjustments.append(ScoreAdjustment(code="unknown-access", basis_points=-800))
        if resource.access.current_session is SessionAvailability.UNKNOWN:
            adjustments.append(ScoreAdjustment(code="unknown-session", basis_points=-800))
        if resource.economics.quota is QuotaStatus.UNKNOWN:
            adjustments.append(ScoreAdjustment(code="unknown-quota", basis_points=-800))
        if (
            resource.provenance.basis is ConfidenceBasis.UNKNOWN
            or resource.provenance.last_verified is None
            or resource.provenance.last_verified > project.as_of
        ):
            adjustments.append(ScoreAdjustment(code="unknown-provenance", basis_points=-800))
    if role == "primary":
        if state.previous_primary == resource.id:
            adjustments.append(ScoreAdjustment(code="same-primary-continuity", basis_points=400))
        elif resource.id in state.used_primaries:
            adjustments.append(ScoreAdjustment(code="used-primary-continuity", basis_points=200))
    adjusted = max(0, min(10_000, base + sum(item.basis_points for item in adjustments)))
    return CandidateEvaluation(
        role=role,
        resource_id=resource.id,
        resource_name=resource.name,
        eligible_for_role=True,
        components_bp=components,
        base_score_bp=base,
        adjustments=adjustments,
        adjusted_score_bp=adjusted,
        notes=notes,
    )


def _rank_key(candidate: CandidateEvaluation) -> tuple[int, int, int, int, int, int, str]:
    if not candidate.eligible_for_role or candidate.adjusted_score_bp is None:
        return (1, 0, 0, 0, 0, 0, candidate.resource_id)
    return (
        0,
        -candidate.adjusted_score_bp,
        -candidate.components_bp["capability-fit"],
        -candidate.components_bp["confidence"],
        -candidate.components_bp["cost-efficiency"],
        -candidate.components_bp["low-integration-friction"],
        candidate.resource_id,
    )


def _selection(candidate: CandidateEvaluation, reason: str) -> ResourceSelection:
    assert candidate.adjusted_score_bp is not None
    return ResourceSelection(
        resource_id=candidate.resource_id,
        resource_name=candidate.resource_name,
        score_bp=candidate.adjusted_score_bp,
        reason=reason,
    )


def _support_selection(
    primary: CandidateEvaluation,
    support_eligible: list[CandidateEvaluation],
    resources: dict[str, Resource],
    workstream: Workstream,
    maximum_supporting_resources: int,
) -> tuple[CandidateEvaluation | None, list[str], int | None, int | None]:
    if maximum_supporting_resources == 0 or not workstream.support.allowed:
        return None, [], None, None
    primary_resource = resources[primary.resource_id]
    primary_fit = _capability_fit(primary_resource, workstream)
    options: list[tuple[int, CandidateEvaluation, list[str]]] = []
    named_gaps = set(workstream.support.capability_gaps)
    for candidate in support_eligible:
        if candidate.resource_id == primary.resource_id:
            continue
        support_resource = resources[candidate.resource_id]
        if any(
            max(
                primary_resource.capabilities.get(requirement.id, 0.0),
                support_resource.capabilities.get(requirement.id, 0.0),
            )
            < requirement.minimum
            for requirement in workstream.required_capabilities
        ):
            continue
        combined_weighted = 0
        total = 0
        improved: list[str] = []
        for requirement in workstream.required_capabilities:
            importance = _basis_points(requirement.importance)
            primary_score = primary_resource.capabilities.get(requirement.id, 0.0)
            support_score = support_resource.capabilities.get(requirement.id, 0.0)
            combined_weighted += _basis_points(max(primary_score, support_score)) * importance
            total += importance
            if requirement.id in named_gaps and support_score > primary_score:
                improved.append(requirement.id)
        if total <= 0:
            raise ConfigurationError("capability importance must include at least one basis point")
        combined_fit = (combined_weighted + total // 2) // total
        gain = combined_fit - primary_fit
        if improved and gain >= _basis_points(workstream.support.minimum_gain):
            options.append((gain, candidate, sorted(improved)))
    if not options:
        return None, [], None, None
    options.sort(key=lambda item: (-item[0], _rank_key(item[1])))
    gain, winner, gaps = options[0]
    return winner, gaps, primary_fit + gain, gain


def _meets_capability_minima(resource: Resource, workstream: Workstream) -> bool:
    return all(
        resource.capabilities.get(requirement.id, 0.0) >= requirement.minimum
        for requirement in workstream.required_capabilities
    )


def _without_unavailable_support(candidate: CandidateEvaluation) -> CandidateEvaluation:
    return candidate.model_copy(
        update={
            "eligible_for_role": False,
            "gate_codes": sorted({*candidate.gate_codes, "support-combination-unavailable"}),
            "notes": [
                *candidate.notes,
                "declared capability gaps require a valid support combination",
            ],
        }
    )


def _unverified_selection_warning(
    workstream: Workstream,
    candidate: CandidateEvaluation,
    role: str,
) -> str | None:
    issue_codes = sorted(
        adjustment.code
        for adjustment in candidate.adjustments
        if adjustment.code in _UNVERIFIED_ADJUSTMENTS
    )
    if not issue_codes:
        return None
    return (
        f"[selected-unverified-resource] workstream {workstream.id!r} selected {role} "
        f"resource {candidate.resource_id!r} with allowed unverified state: "
        + ", ".join(issue_codes)
    )


def _handoff(
    workstream: Workstream,
    owner: CandidateEvaluation,
    owner_resource: Resource,
    *,
    role: str,
    activation_condition: str,
) -> HandoffPacket:
    return HandoffPacket(
        role=role,
        activation_condition=activation_condition,
        owner_resource_id=owner.resource_id,
        owner_resource_name=owner.resource_name,
        handoff_method=owner_resource.handoff.method,
        handoff_instructions=owner_resource.handoff.instructions,
        declared_resource_approval_required=owner_resource.policy.approval_required,
        objective=workstream.objective,
        inputs=workstream.inputs,
        allowed_scope=workstream.allowed_scope,
        exclusions=workstream.exclusions,
        deliverable=workstream.deliverable,
        acceptance_criteria=workstream.acceptance_criteria,
        verification=workstream.verification,
        stop_conditions=workstream.stop_conditions,
        next_owner=workstream.next_owner,
    )


def _build_dispositions(
    inventory: Inventory,
    assignments: list[RouteAssignment],
) -> list[ResourceDisposition]:
    roles: dict[str, tuple[DispositionStatus, set[str]]] = {}
    precedence = {
        DispositionStatus.SELECTED_PRIMARY: 3,
        DispositionStatus.SELECTED_SUPPORT: 2,
        DispositionStatus.RESERVED_ALTERNATE: 1,
    }
    for assignment in assignments:
        for selection, status in (
            (assignment.primary, DispositionStatus.SELECTED_PRIMARY),
            (assignment.support, DispositionStatus.SELECTED_SUPPORT),
            (assignment.alternate, DispositionStatus.RESERVED_ALTERNATE),
        ):
            if selection is None:
                continue
            existing = roles.get(selection.resource_id)
            if existing is None:
                roles[selection.resource_id] = (status, {assignment.workstream_id})
            else:
                existing_status, workstreams = existing
                workstreams.add(assignment.workstream_id)
                chosen = (
                    status if precedence[status] > precedence[existing_status] else existing_status
                )
                roles[selection.resource_id] = (chosen, workstreams)

    dispositions: list[ResourceDisposition] = []
    for resource in sorted(inventory.resources, key=lambda item: item.id):
        if resource.id in roles:
            status, workstreams = roles[resource.id]
            dispositions.append(
                ResourceDisposition(
                    resource_id=resource.id,
                    resource_name=resource.name,
                    status=status,
                    reason_code=status.value,
                    reason=f"Selected as {status.value} in the deterministic workstream route.",
                    workstreams=sorted(workstreams),
                )
            )
            continue

        evaluations = [
            candidate
            for assignment in assignments
            for candidate in assignment.candidates
            if candidate.resource_id == resource.id
        ]
        if any(candidate.eligible_for_role for candidate in evaluations):
            status = DispositionStatus.DELIBERATELY_UNUSED
            code = "lower-adjusted-score"
            reason = (
                "Primary-feasible, but another resource ranked higher for the ordered workstream."
            )
        elif evaluations and all(
            "no-applicable-capability" in candidate.gate_codes for candidate in evaluations
        ):
            status = DispositionStatus.DELIBERATELY_UNUSED
            code = "no-applicable-capability"
            reason = "No project workstream requires this resource's declared capabilities."
        else:
            gates = {gate for candidate in evaluations for gate in candidate.gate_codes}
            if gates & _UNAVAILABLE_GATES:
                status = DispositionStatus.UNAVAILABLE
                code = sorted(gates & _UNAVAILABLE_GATES)[0]
                reason = f"Unavailable because every relevant route was gated by {code}."
            elif gates - _UNVERIFIED_GATES:
                status = DispositionStatus.INELIGIBLE
                code = sorted(gates - _UNVERIFIED_GATES)[0]
                reason = f"Ineligible because every relevant route was gated by {code}."
            else:
                status = DispositionStatus.UNVERIFIED
                code = sorted(gates & _UNVERIFIED_GATES)[0]
                reason = f"Unverified because every relevant route was gated by {code}."
        dispositions.append(
            ResourceDisposition(
                resource_id=resource.id,
                resource_name=resource.name,
                status=status,
                reason_code=code,
                reason=reason,
            )
        )
    return dispositions


def route(
    inventory: Inventory,
    project: ProjectBrief,
    *,
    allow_demo: bool = False,
) -> RoutePlan:
    """Return a deterministic, complete route plan with no I/O or network access."""

    if inventory.inventory_kind is InventoryKind.DEMO and not allow_demo:
        raise ConfigurationError(
            "refusing to route a demo inventory without explicit demo opt-in "
            "(--allow-demo in the CLI or allow_demo=True in the API)"
        )
    if not inventory.resources:
        if inventory.inventory_kind is InventoryKind.DEMO:
            raise ConfigurationError("demo inventory has no synthetic resources to route")
        raise ConfigurationError(
            "personal inventory has no resources; add one with 'atready inventory add'"
        )

    resources = {resource.id: resource for resource in inventory.resources}
    assignments: list[RouteAssignment] = []
    used_primaries: set[str] = set()
    previous_primary: str | None = None
    warnings: list[str] = []
    if inventory.inventory_kind is InventoryKind.DEMO:
        warnings.append(
            "[demo-inventory] this inventory is labeled demo; its user-controlled contents are "
            "not verified as synthetic or as personal access"
        )

    for workstream in project.workstreams:
        state = _RoutingState(previous_primary, frozenset(used_primaries))
        support_enabled = bool(
            workstream.support.allowed and inventory.preferences.maximum_supporting_resources == 1
        )
        supportable_gaps = (
            frozenset(workstream.support.capability_gaps) if support_enabled else frozenset()
        )
        all_requirement_ids = frozenset(
            requirement.id for requirement in workstream.required_capabilities
        )
        candidates = [
            _evaluate_resource(
                resource,
                inventory,
                project,
                workstream,
                state,
                allowed_below_minimum=supportable_gaps,
            )
            for resource in sorted(inventory.resources, key=lambda item: item.id)
        ]
        support_candidates = (
            [
                _evaluate_resource(
                    resource,
                    inventory,
                    project,
                    workstream,
                    state,
                    role="support",
                    allowed_below_minimum=all_requirement_ids,
                )
                for resource in sorted(inventory.resources, key=lambda item: item.id)
            ]
            if support_enabled
            else []
        )
        support_candidates.sort(key=_rank_key)
        eligible_support = [
            candidate for candidate in support_candidates if candidate.eligible_for_role
        ]
        pair_by_primary: dict[
            str, tuple[CandidateEvaluation | None, list[str], int | None, int | None]
        ] = {}
        feasible_candidates: list[CandidateEvaluation] = []
        for candidate in candidates:
            if not candidate.eligible_for_role:
                feasible_candidates.append(candidate)
                continue
            support_candidate, support_gap, combined_fit, fit_gain = _support_selection(
                candidate,
                eligible_support,
                resources,
                workstream,
                inventory.preferences.maximum_supporting_resources,
            )
            if (
                _meets_capability_minima(resources[candidate.resource_id], workstream)
                or support_candidate is not None
            ):
                feasible_candidates.append(candidate)
                pair_by_primary[candidate.resource_id] = (
                    support_candidate,
                    support_gap,
                    combined_fit,
                    fit_gain,
                )
            else:
                feasible_candidates.append(_without_unavailable_support(candidate))
        candidates = sorted(feasible_candidates, key=_rank_key)
        eligible = [candidate for candidate in candidates if candidate.eligible_for_role]
        if not eligible:
            assignments.append(
                RouteAssignment(
                    workstream_id=workstream.id,
                    workstream_name=workstream.name,
                    gap_reason=(
                        "No verified eligible resource satisfies the required capabilities "
                        "and constraints."
                    ),
                    candidates=candidates,
                )
            )
            warnings.append(f"workstream {workstream.id!r} is an unresolved capability gap")
            previous_primary = None
            continue

        primary = eligible[0]
        support_candidate, support_gap, combined_fit, fit_gain = pair_by_primary.get(
            primary.resource_id,
            (None, [], None, None),
        )
        strict_candidates = [
            _evaluate_resource(
                resource,
                inventory,
                project,
                workstream,
                state,
                role="alternate",
            )
            for resource in sorted(inventory.resources, key=lambda item: item.id)
        ]
        strict_candidates.sort(key=_rank_key)
        remaining = [
            candidate
            for candidate in strict_candidates
            if candidate.eligible_for_role
            if candidate.resource_id
            not in {
                primary.resource_id,
                support_candidate.resource_id if support_candidate else None,
            }
        ]
        primary_is_standalone = _meets_capability_minima(resources[primary.resource_id], workstream)
        if (
            workstream.alternate_required
            and support_candidate is not None
            and primary_is_standalone
            and not remaining
        ):
            reservable_alternates = [
                candidate
                for candidate in strict_candidates
                if candidate.eligible_for_role and candidate.resource_id != primary.resource_id
            ]
            if reservable_alternates:
                support_candidate = None
                support_gap = []
                combined_fit = None
                fit_gain = None
                remaining = reservable_alternates
        primary_resource = resources[primary.resource_id]
        volatile = (
            primary_resource.access.status is AccessStatus.LIMITED
            or primary_resource.economics.quota is QuotaStatus.LIMITED
        )
        alternate_candidate = (
            remaining[0] if remaining and (workstream.alternate_required or volatile) else None
        )
        unresolved_gaps: list[UnresolvedRouteGap] = []
        if workstream.alternate_required and alternate_candidate is None:
            unresolved_gaps.append(
                UnresolvedRouteGap(
                    code=_REQUIRED_ALTERNATE_GAP_CODE,
                    reason=_REQUIRED_ALTERNATE_GAP_REASON,
                )
            )
            warnings.append(
                f"[{_REQUIRED_ALTERNATE_GAP_CODE}] workstream {workstream.id!r} requires an "
                "alternate, but no additional standalone-eligible resource remains after "
                "primary and support selection"
            )

        for role, candidate in (
            ("primary", primary),
            ("support", support_candidate),
            ("alternate", alternate_candidate),
        ):
            if candidate is None:
                continue
            warning = _unverified_selection_warning(workstream, candidate, role)
            if warning:
                warnings.append(warning)

        assignment = RouteAssignment(
            workstream_id=workstream.id,
            workstream_name=workstream.name,
            primary=_selection(
                primary,
                "Highest eligible weighted score after hard gates and continuity adjustments.",
            ),
            support=(
                _selection(
                    support_candidate,
                    "Adds the named capability gap above the configured minimum gain.",
                )
                if support_candidate
                else None
            ),
            support_gap=support_gap,
            support_evaluation=(
                support_candidate.model_copy(
                    update={
                        "combined_fit_bp": combined_fit,
                        "fit_gain_bp": fit_gain,
                        "covered_capability_gaps": support_gap,
                    }
                )
                if support_candidate
                else None
            ),
            alternate=(
                _selection(
                    alternate_candidate,
                    "Reserved as another currently eligible candidate; independence is not proven.",
                )
                if alternate_candidate
                else None
            ),
            alternate_evaluation=(alternate_candidate if alternate_candidate else None),
            alternate_activation_condition=(
                _ALTERNATE_ACTIVATION_CONDITION if alternate_candidate else None
            ),
            unresolved_gaps=unresolved_gaps,
            handoffs=[
                _handoff(
                    workstream,
                    primary,
                    resources[primary.resource_id],
                    role="primary",
                    activation_condition="Run only after the user authorizes this route.",
                ),
                *(
                    [
                        _handoff(
                            workstream,
                            support_candidate,
                            resources[support_candidate.resource_id],
                            role="support",
                            activation_condition=(
                                "Run only with the primary for capability gaps: "
                                + ", ".join(support_gap)
                            ),
                        )
                    ]
                    if support_candidate
                    else []
                ),
                *(
                    [
                        _handoff(
                            workstream,
                            alternate_candidate,
                            resources[alternate_candidate.resource_id],
                            role="alternate",
                            activation_condition=_ALTERNATE_ACTIVATION_CONDITION,
                        )
                    ]
                    if alternate_candidate
                    else []
                ),
            ],
            candidates=candidates,
        )
        assignments.append(assignment)
        used_primaries.add(primary.resource_id)
        previous_primary = primary.resource_id

    dispositions = _build_dispositions(inventory, assignments)
    catalog = InventoryCatalog(inventory=inventory, warnings=())
    base = RoutePlan(
        plan_id="pending",
        project_id=project.id,
        project_name=project.name,
        as_of=project.as_of,
        inventory_fingerprint="sha256:" + catalog.fingerprint(),
        assignments=assignments,
        dispositions=dispositions,
        warnings=warnings,
    )
    canonical = json.dumps(
        base.model_dump(mode="json", exclude={"plan_id"}),
        sort_keys=True,
        separators=(",", ":"),
    )
    return base.model_copy(
        update={"plan_id": "ar-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]}
    )
