"""Deterministic Markdown rendering with untrusted text escaped as data."""

from __future__ import annotations

from collections import defaultdict

from atready.models import CandidateEvaluation, DispositionStatus, RouteAssignment, RoutePlan


def _text(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("`", "*", "_", "[", "]", "<", ">", "|", "#", "!"):
        escaped = escaped.replace(character, "\\" + character)
    return " ".join(escaped.splitlines())


def _bullets(values: list[str]) -> list[str]:
    return [f"- {_text(value)}" for value in values]


def _score(basis_points: int) -> str:
    return f"{basis_points / 100:.2f}"


def _runner_up(
    assignment: RouteAssignment, selected: CandidateEvaluation
) -> CandidateEvaluation | None:
    eligible = [
        candidate
        for candidate in assignment.candidates
        if candidate.role == "primary"
        and candidate.eligible_for_role
        and candidate.adjusted_score_bp is not None
        and candidate.resource_id != selected.resource_id
    ]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda candidate: (
            -candidate.adjusted_score_bp,
            -candidate.components_bp["capability-fit"],
            -candidate.components_bp["confidence"],
            -candidate.components_bp["cost-efficiency"],
            -candidate.components_bp["low-integration-friction"],
            candidate.resource_id,
        ),
    )[0]


def _primary_trace(assignment: RouteAssignment) -> str:
    assert assignment.primary is not None
    selected = next(
        candidate
        for candidate in assignment.candidates
        if candidate.resource_id == assignment.primary.resource_id
    )
    runner_up = _runner_up(assignment, selected)
    if runner_up is None:
        return (
            f"{assignment.primary.reason} It was the only eligible candidate and scored "
            f"{_score(assignment.primary.score_bp)}."
        )

    assert selected.adjusted_score_bp is not None
    assert runner_up.adjusted_score_bp is not None
    component_deltas = sorted(
        (
            (selected.components_bp[name] - runner_up.components_bp.get(name, 0), name)
            for name in selected.components_bp
        ),
        key=lambda item: (-item[0], item[1]),
    )
    positive_edge = next((item for item in component_deltas if item[0] > 0), None)
    comparison = (
        f"Adjusted score {_score(selected.adjusted_score_bp)} versus runner-up "
        f"{runner_up.resource_name} at {_score(runner_up.adjusted_score_bp)}."
    )
    if selected.adjusted_score_bp == runner_up.adjusted_score_bp:
        comparison += " The deterministic component/resource-ID tie-break chain resolved the tie."
    if positive_edge is None:
        selected_adjustment = sum(item.basis_points for item in selected.adjustments)
        runner_adjustment = sum(item.basis_points for item in runner_up.adjustments)
        if selected_adjustment != runner_adjustment:
            return (
                f"{assignment.primary.reason} {comparison} Net adjustments were "
                f"{_score(selected_adjustment)} versus {_score(runner_adjustment)}."
            )
        if selected.adjusted_score_bp == runner_up.adjusted_score_bp:
            return f"{assignment.primary.reason} {comparison}"
        return f"{assignment.primary.reason} {comparison} The deterministic tie-break resolved it."
    delta, component = positive_edge
    return (
        f"{assignment.primary.reason} {comparison} Largest reported raw component edge: "
        f"{component.replace('-', ' ')} +{_score(delta)}."
    )


def _loadout_reason(plan: RoutePlan, resource_id: str) -> str:
    reasons: list[str] = []
    for assignment in plan.assignments:
        if assignment.primary and assignment.primary.resource_id == resource_id:
            reasons.append(f"{assignment.workstream_name}: {_primary_trace(assignment)}")
        if assignment.support and assignment.support.resource_id == resource_id:
            gaps = ", ".join(assignment.support_gap)
            reasons.append(
                f"{assignment.workstream_name}: {assignment.support.reason} Gaps: {gaps}."
            )
        if assignment.alternate and assignment.alternate.resource_id == resource_id:
            reasons.append(
                f"{assignment.workstream_name}: {assignment.alternate.reason} Activation: "
                f"{assignment.alternate_activation_condition}."
            )
    return " ".join(reasons)


def render_markdown(plan: RoutePlan) -> str:
    lines = [
        f"# AtReady route: {_text(plan.project_name)}",
        "",
        f"Plan `{plan.plan_id}` · inventory `{plan.inventory_fingerprint}` · as of `{plan.as_of}`",
        "",
        "## Deterministic workstream route",
        "",
        "| Resource | Role | Workstreams | Why it earned a seat |",
        "| --- | --- | --- | --- |",
    ]
    for disposition in plan.dispositions:
        if disposition.status in {
            DispositionStatus.SELECTED_PRIMARY,
            DispositionStatus.SELECTED_SUPPORT,
            DispositionStatus.RESERVED_ALTERNATE,
        }:
            lines.append(
                f"| {_text(disposition.resource_name)} | {disposition.status.value} | "
                f"{', '.join(disposition.workstreams)} | "
                f"{_text(_loadout_reason(plan, disposition.resource_id))} |"
            )

    lines.extend(["", "## Execution route", ""])
    for assignment in plan.assignments:
        lines.extend([f"### {_text(assignment.workstream_name)}", ""])
        if assignment.primary is None:
            lines.extend([f"Gap: {_text(assignment.gap_reason or 'Unresolved.')}", ""])
            continue
        lines.append(
            f"Primary: **{_text(assignment.primary.resource_name)}** "
            f"(`{_score(assignment.primary.score_bp)}`)"
        )
        lines.append(f"Why: {_text(_primary_trace(assignment))}")
        if assignment.support:
            lines.append(
                f"Support: **{_text(assignment.support.resource_name)}** for "
                f"{', '.join(assignment.support_gap)}"
            )
        if assignment.alternate:
            lines.append(
                f"Alternate: **{_text(assignment.alternate.resource_name)}** — "
                f"{_text(assignment.alternate_activation_condition or '')}"
            )
        for gap in assignment.unresolved_gaps:
            lines.append(f"Unresolved requirement (`{gap.code}`): {_text(gap.reason)}")
        for handoff in assignment.handoffs:
            lines.extend(["", f"#### {handoff.role.title()} handoff packet", ""])
            lines.extend(
                [
                    f"Activation: {_text(handoff.activation_condition)}",
                    f"Owner/resource: {_text(handoff.owner_resource_name)}",
                    f"Handoff method: `{handoff.handoff_method.value}`",
                    "Declared resource approval required: "
                    + ("yes" if handoff.declared_resource_approval_required else "no"),
                    "Handoff instructions: "
                    + (
                        _text(handoff.handoff_instructions)
                        if handoff.handoff_instructions is not None
                        else "None declared"
                    ),
                    f"Objective: {_text(handoff.objective)}",
                    "",
                    "Inputs:",
                    *_bullets(handoff.inputs),
                    "",
                    "Allowed scope:",
                    *_bullets(handoff.allowed_scope),
                    "",
                    "Exclusions:",
                    *_bullets(handoff.exclusions),
                    "",
                    f"Deliverable: {_text(handoff.deliverable)}",
                    "",
                    "Acceptance criteria:",
                    *_bullets(handoff.acceptance_criteria),
                    "",
                    "Verification (display only):",
                ]
            )
            for command in handoff.verification:
                lines.append(f"    {command.replace(chr(10), ' ')}")
            lines.extend(["", "Stop conditions:", *_bullets(handoff.stop_conditions), ""])
            lines.append(f"Next owner: {_text(handoff.next_owner)}")
            lines.append("")

    groups: dict[DispositionStatus, list] = defaultdict(list)
    for disposition in plan.dispositions:
        groups[disposition.status].append(disposition)
    headings = (
        (DispositionStatus.DELIBERATELY_UNUSED, "Resources deliberately not used"),
        (DispositionStatus.UNAVAILABLE, "Unavailable resources"),
        (DispositionStatus.INELIGIBLE, "Ineligible resources"),
        (DispositionStatus.UNVERIFIED, "Unverified resources"),
    )
    for status, heading in headings:
        if not groups[status]:
            continue
        lines.extend([f"## {heading}", ""])
        for item in groups[status]:
            lines.append(f"- **{_text(item.resource_name)}**: {_text(item.reason)}")
        lines.append("")

    if plan.warnings:
        lines.extend(["## Gaps and risks", "", *_bullets(plan.warnings), ""])
    lines.extend(
        [
            "## Authorization boundary",
            "",
            "This route is advisory. No handoff, command, purchase, or subscription change "
            "has been executed.",
            "",
        ]
    )
    return "\n".join(lines)
