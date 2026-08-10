"""Deterministic Markdown rendering with untrusted text escaped as data."""

from __future__ import annotations

import re
from collections import defaultdict
from textwrap import TextWrapper

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


def _terminal_text(value: object) -> str:
    """Flatten text and escape non-printing characters for terminal output."""

    escaped = "".join(
        character if character.isprintable() else character.encode("unicode_escape").decode("ascii")
        for character in str(value)
    )
    return " ".join(escaped.split())


def _append_wrapped(
    lines: list[str],
    value: object,
    *,
    width: int,
    initial_indent: str = "",
    subsequent_indent: str | None = None,
) -> None:
    wrapper = TextWrapper(
        width=max(width, 20),
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent or initial_indent,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=True,
        drop_whitespace=True,
    )
    lines.extend(wrapper.wrap(_terminal_text(value)) or [initial_indent.rstrip()])


def _plain_selection_reason(reason: str) -> str:
    if reason == "Highest eligible weighted score after hard gates and continuity adjustments.":
        return "Best eligible match after applying the project constraints."
    if reason == "Adds the named capability gap above the configured minimum gain.":
        return "Covers a required capability the primary resource does not cover alone."
    return reason


def _plain_warning(warning: str) -> str:
    if warning.startswith("[demo-inventory]"):
        return "This uses a demo inventory. Its contents are not verified as resources you can use."
    unverified = re.fullmatch(
        r"\[selected-unverified-resource\] workstream '([^']+)' selected "
        r"(primary|support|alternate) resource '([^']+)' with allowed unverified state: (.+)",
        warning,
    )
    if unverified:
        workstream, role, resource, issue_text = unverified.groups()
        issue_labels = {
            "stale-provenance": "its verification is stale",
            "unknown-access": "its access is unknown",
            "unknown-provenance": "its verification source is unknown",
            "unknown-quota": "its remaining quota is unknown",
            "unknown-session": "its current availability is unknown",
        }
        issues = [issue_labels.get(code, code.replace("-", " ")) for code in issue_text.split(", ")]
        return f"{resource} is selected as {role} for {workstream}, but " + "; ".join(issues) + "."
    return warning


def _primary_handoff(assignment: RouteAssignment):
    return next((handoff for handoff in assignment.handoffs if handoff.role == "primary"), None)


def render_summary(plan: RoutePlan, *, goal: str | None = None, width: int = 100) -> str:
    """Render a concise, width-aware human route without audit-only details."""

    width = max(width, 20)
    assigned_count = sum(assignment.primary is not None for assignment in plan.assignments)
    gap_count = sum(
        (1 if assignment.primary is None else 0) + len(assignment.unresolved_gaps)
        for assignment in plan.assignments
    )
    step_label = "step" if len(plan.assignments) == 1 else "steps"
    if gap_count == 0:
        gap_label = "no open gaps"
    else:
        gap_label = f"{gap_count} open {'gap' if gap_count == 1 else 'gaps'}"
    lines: list[str] = []
    _append_wrapped(lines, f"Resource plan: {plan.project_name}", width=width)
    if goal:
        _append_wrapped(
            lines,
            goal,
            width=width,
            initial_indent="Goal: ",
            subsequent_indent="      ",
        )
    _append_wrapped(
        lines,
        f"{len(plan.assignments)} {step_label} - {assigned_count} assigned - {gap_label}",
        width=width,
    )

    unresolved_codes = {
        gap.code for assignment in plan.assignments for gap in assignment.unresolved_gaps
    }
    visible_warnings = [
        warning
        for warning in plan.warnings
        if "unresolved capability gap" not in warning
        and not any(f"[{code}]" in warning for code in unresolved_codes)
    ]
    if visible_warnings:
        lines.extend(["", "Watch"])
        for warning in visible_warnings:
            _append_wrapped(
                lines,
                _plain_warning(warning),
                width=width,
                initial_indent="- ",
                subsequent_indent="  ",
            )

    for index, assignment in enumerate(plan.assignments, start=1):
        lines.append("")
        _append_wrapped(
            lines,
            f"{index}. {assignment.workstream_name}",
            width=width,
            subsequent_indent="   ",
        )
        if assignment.primary is None:
            _append_wrapped(
                lines,
                "Unassigned",
                width=width,
                initial_indent="   Use: ",
                subsequent_indent="        ",
            )
            continue

        _append_wrapped(
            lines,
            assignment.primary.resource_name,
            width=width,
            initial_indent="   Use: ",
            subsequent_indent="        ",
        )
        _append_wrapped(
            lines,
            _plain_selection_reason(assignment.primary.reason),
            width=width,
            initial_indent="   Why: ",
            subsequent_indent="        ",
        )
        if assignment.support:
            support_gaps = ", ".join(gap.replace("-", " ") for gap in assignment.support_gap)
            _append_wrapped(
                lines,
                f"{assignment.support.resource_name} (covers {support_gaps})",
                width=width,
                initial_indent="   Help from: ",
                subsequent_indent="              ",
            )
        if assignment.alternate:
            _append_wrapped(
                lines,
                assignment.alternate.resource_name,
                width=width,
                initial_indent="   Backup option: ",
                subsequent_indent="                  ",
            )
            _append_wrapped(
                lines,
                assignment.alternate_activation_condition,
                width=width,
                initial_indent="   Condition: ",
                subsequent_indent="              ",
            )
            _append_wrapped(
                lines,
                "AtReady will not switch automatically.",
                width=width,
                initial_indent="   Note: ",
                subsequent_indent="         ",
            )

        primary_handoff = _primary_handoff(assignment)
        if primary_handoff:
            _append_wrapped(
                lines,
                primary_handoff.deliverable,
                width=width,
                initial_indent="   Deliver: ",
                subsequent_indent="            ",
            )
            verification = primary_handoff.verification[0]
            if len(primary_handoff.verification) > 1:
                verification += (
                    f" (+{len(primary_handoff.verification) - 1} more in the detailed view)"
                )
            _append_wrapped(
                lines,
                verification,
                width=width,
                initial_indent="   Check: ",
                subsequent_indent="          ",
            )

    gaps = [
        (assignment.workstream_name, assignment.gap_reason)
        for assignment in plan.assignments
        if assignment.primary is None
    ]
    gaps.extend(
        (assignment.workstream_name, gap.reason)
        for assignment in plan.assignments
        for gap in assignment.unresolved_gaps
    )
    if gaps:
        lines.extend(["", "Gaps and decisions"])
        for workstream_name, reason in gaps:
            _append_wrapped(
                lines,
                f"{workstream_name}: {reason or 'Unresolved.'}",
                width=width,
                initial_indent="- ",
                subsequent_indent="  ",
            )

    disposition_labels = (
        (DispositionStatus.DELIBERATELY_UNUSED, "not needed for this plan"),
        (DispositionStatus.UNAVAILABLE, "not available now"),
        (DispositionStatus.INELIGIBLE, "blocked by a project rule"),
        (DispositionStatus.UNVERIFIED, "not verified"),
    )
    disposition_groups = [
        ([item for item in plan.dispositions if item.status == status], label)
        for status, label in disposition_labels
    ]
    if any(items for items, _ in disposition_groups):
        lines.extend(["", "Other resources"])
        for items, label in disposition_groups:
            if not items:
                continue
            visible = ", ".join(item.resource_name for item in items[:5])
            if len(items) > 5:
                visible += f" (+{len(items) - 5} more)"
            _append_wrapped(
                lines,
                visible,
                width=width,
                initial_indent=f"- {label.capitalize()}: ",
                subsequent_indent="  ",
            )

    lines.append("")
    _append_wrapped(
        lines,
        "Review the assignments. Use --format markdown for scores and full handoff details.",
        width=width,
        initial_indent="Next: ",
        subsequent_indent="      ",
    )
    _append_wrapped(
        lines,
        "AtReady made this plan only.",
        width=width,
    )
    lines.append("No routed project resources were contacted or run.")
    return "\n".join(lines) + "\n"


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
            "No routed project resources were contacted or run.",
            "",
        ]
    )
    return "\n".join(lines)
