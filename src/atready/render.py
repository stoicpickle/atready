"""Deterministic Markdown rendering with untrusted text escaped as data."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from textwrap import TextWrapper
from typing import Literal

from atready.models import CandidateEvaluation, DispositionStatus, RouteAssignment, RoutePlan

_FINAL_SAFETY_BOUNDARY = "No routed project resources were contacted or run."
_RESERVED_PRESENTATION_MARKERS = ("Goal:", "Route:", "Gap:", "Uncertainty:", "Next:")


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


def _untrusted_presentation_text(value: object) -> str:
    """Flatten untrusted display text without allowing it to forge response structure."""

    text = _terminal_text(value).replace(
        _FINAL_SAFETY_BOUNDARY,
        "No routed project resources were contacted or run [quoted].",
    )
    for marker in _RESERVED_PRESENTATION_MARKERS:
        text = text.replace(marker, f"{marker[:-1]} [quoted]:")
    return text


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


_QUOTED_LITERAL = r'(?:\'(?:\\.|[^\'\\])*\'|"(?:\\.|[^"\\])*")'
_SELECTED_UNVERIFIED_PATTERN = re.compile(
    rf"\[selected-unverified-resource\] workstream (?P<workstream>{_QUOTED_LITERAL}) "
    rf"selected (?P<role>primary|support|alternate) resource "
    rf"(?P<resource>{_QUOTED_LITERAL}) with allowed unverified state: "
    rf"(?P<issues>[a-z0-9-]+(?:, [a-z0-9-]+)*)"
)
_UNVERIFIED_ISSUE_LABELS = {
    "stale-provenance": "verification is stale",
    "unknown-access": "access is unknown",
    "unknown-provenance": "the declaration source is unknown",
    "unknown-quota": "remaining usage is unknown",
    "unknown-session": "current availability is unknown",
}
_CAPACITY_GATE_CODES = {
    "capacity-expired",
    "capacity-insufficient",
    "capacity-reset-unknown",
    "capacity-unit-mismatch",
    "capacity-unknown",
}


def _capacity_gap_evidence(assignment: RouteAssignment) -> list[str]:
    """Return bounded plain evidence for capacity-gated candidates."""

    evidence: list[str] = []
    capacity_gated = [
        candidate
        for candidate in assignment.candidates
        if set(candidate.gate_codes) & _CAPACITY_GATE_CODES
    ]
    for candidate in capacity_gated[:3]:
        detail = next(
            (
                note.split("] ", 1)[1]
                for note in candidate.notes
                if note.startswith("[capacity-") and "] " in note
            ),
            "exact capacity could not be confirmed",
        )
        evidence.append(f"{candidate.resource_name}: {detail}")
    if len(capacity_gated) > 3:
        evidence.append(f"{len(capacity_gated) - 3} more candidates have capacity gaps")
    return evidence


def _selected_unverified_warning(warning: str) -> tuple[str, str, str, list[str]] | None:
    match = _SELECTED_UNVERIFIED_PATTERN.fullmatch(warning)
    if not match:
        return None
    try:
        workstream = ast.literal_eval(match.group("workstream"))
        resource = ast.literal_eval(match.group("resource"))
    except (SyntaxError, ValueError):
        return None
    if not isinstance(workstream, str) or not isinstance(resource, str):
        return None
    return (
        workstream,
        match.group("role"),
        resource,
        [
            _UNVERIFIED_ISSUE_LABELS.get(code, code.replace("-", " "))
            for code in match.group("issues").split(", ")
        ],
    )


def _plain_warning(warning: str) -> str:
    if warning.startswith("[demo-inventory]"):
        return "This uses an unverified demo inventory."
    if warning.startswith("[resource-state]"):
        return warning.removeprefix("[resource-state] ").capitalize() + "."
    unverified = _selected_unverified_warning(warning)
    if unverified:
        workstream, role, resource, issues = unverified
        issues = [
            {
                "verification is stale": "its verification is stale",
                "access is unknown": "its access is unknown",
                "the declaration source is unknown": "its verification source is unknown",
                "remaining usage is unknown": "its remaining quota is unknown",
                "current availability is unknown": "its current availability is unknown",
            }.get(issue, issue)
            for issue in issues
        ]
        return f"{resource} is selected as {role} for {workstream}, but " + "; ".join(issues) + "."
    return warning


def _primary_handoff(assignment: RouteAssignment):
    return next((handoff for handoff in assignment.handoffs if handoff.role == "primary"), None)


_MATERIAL_PRIMARY_GATE_REASONS = (
    ("quota-exhausted", "has no declared quota remaining"),
    ("data-class-disallowed", "is blocked by the project's data-class rule"),
)


def _primary_gate_context(
    assignment: RouteAssignment, selected_resource_ids: set[str]
) -> str | None:
    """Return one plain, route-proven gate affecting an unselected option.

    This is context about eligibility, not a claim that the gate changed the selected resource's
    ranking. Only a candidate with exactly one hard gate can supply the compact explanation.
    """

    for gate, explanation in _MATERIAL_PRIMARY_GATE_REASONS:
        excluded = sorted(
            (
                candidate
                for candidate in assignment.candidates
                if candidate.resource_id not in selected_resource_ids
                and not candidate.eligible_for_role
                and candidate.gate_codes == [gate]
            ),
            key=lambda candidate: (candidate.resource_id, candidate.resource_name),
        )
        if excluded:
            return f"{excluded[0].resource_name} {explanation}."
    return None


def _next_action(plan: RoutePlan, *, has_gaps: bool) -> str:
    assignment_gates = {
        gate
        for assignment in plan.assignments
        if assignment.primary is None
        for candidate in assignment.candidates
        for gate in candidate.gate_codes
    }
    capacity_gates = assignment_gates & _CAPACITY_GATE_CODES
    if has_gaps and capacity_gates:
        if assignment_gates - _CAPACITY_GATE_CODES:
            return (
                "Resolve the exact same-unit capacity and other selection gaps, then route again."
            )
        if capacity_gates == {"capacity-insufficient"}:
            return (
                "Use a resource with enough same-unit declared capacity or reduce the workstream "
                "demand, then route again."
            )
        if capacity_gates == {"capacity-unit-mismatch"}:
            return (
                "Use one exact unit for both workstream demand and resource capacity, then route "
                "again."
            )
        if capacity_gates <= {"capacity-unknown", "capacity-reset-unknown"}:
            return "Check and update exact same-unit capacity, then route again."
        return "Resolve the exact same-unit capacity gaps or adjust demand, then route again."
    unverified = [item for item in plan.dispositions if item.status is DispositionStatus.UNVERIFIED]
    if has_gaps and unverified:
        confirmation_labels = {
            "access-unknown": "access",
            "confidence-unknown": "the confidence basis",
            "provenance-stale": "a current verification date",
            "provenance-unknown": "the declaration source",
            "quota-unknown": "remaining usage",
            "session-unknown": "current availability",
        }
        if len(unverified) > 3:
            return (
                "Confirm the missing selection facts for the unverified resources, "
                "then route again."
            )
        confirmations = []
        for item in unverified:
            gate_codes = sorted(
                {
                    gate
                    for assignment in plan.assignments
                    for candidate in assignment.candidates
                    if candidate.resource_id == item.resource_id
                    for gate in candidate.gate_codes
                    if gate in confirmation_labels
                }
            )
            if not gate_codes:
                gate_codes = [item.reason_code]
            facts = [
                confirmation_labels.get(code, "the missing selection facts") for code in gate_codes
            ]
            if len(facts) == 1:
                fact_text = facts[0]
            else:
                fact_text = ", ".join(facts[:-1]) + f", and {facts[-1]}"
            confirmations.append(f"{fact_text} for {item.resource_name}")
        if len(confirmations) == 1:
            detail = confirmations[0]
        else:
            detail = ", ".join(confirmations[:-1]) + f", and {confirmations[-1]}"
        return f"Confirm {detail}, then route again."
    if has_gaps:
        return (
            "Add or update a resource that meets the open capability and project constraints, "
            "then route again."
        )
    return "Review the assignments. Use --format markdown for scores and full handoff details."


def render_summary(
    plan: RoutePlan,
    *,
    goal: str | None = None,
    width: int = 100,
    include_next_action: bool = True,
) -> str:
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
    _append_wrapped(
        lines,
        f"Resource fit: {_untrusted_presentation_text(plan.project_name)}",
        width=width,
    )
    if goal:
        _append_wrapped(
            lines,
            _untrusted_presentation_text(goal),
            width=width,
            initial_indent="Goal: ",
            subsequent_indent="      ",
        )
    _append_wrapped(
        lines,
        f"{len(plan.assignments)} {step_label} · {assigned_count} assigned · {gap_label}",
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
                _untrusted_presentation_text(_plain_warning(warning)),
                width=width,
                initial_indent="- ",
                subsequent_indent="  ",
            )

    for index, assignment in enumerate(plan.assignments, start=1):
        lines.append("")
        _append_wrapped(
            lines,
            f"{index}. {_untrusted_presentation_text(assignment.workstream_name)}",
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
            for evidence in _capacity_gap_evidence(assignment):
                _append_wrapped(
                    lines,
                    _untrusted_presentation_text(evidence),
                    width=width,
                    initial_indent="   Capacity: ",
                    subsequent_indent="             ",
                )
            continue

        _append_wrapped(
            lines,
            _untrusted_presentation_text(assignment.primary.resource_name),
            width=width,
            initial_indent="   Use: ",
            subsequent_indent="        ",
        )
        _append_wrapped(
            lines,
            _untrusted_presentation_text(_plain_selection_reason(assignment.primary.reason)),
            width=width,
            initial_indent="   Why: ",
            subsequent_indent="        ",
        )
        if assignment.support:
            support_gaps = ", ".join(gap.replace("-", " ") for gap in assignment.support_gap)
            _append_wrapped(
                lines,
                f"{_untrusted_presentation_text(assignment.support.resource_name)} "
                f"(covers {_untrusted_presentation_text(support_gaps)})",
                width=width,
                initial_indent="   Help from: ",
                subsequent_indent="              ",
            )
        if assignment.alternate:
            _append_wrapped(
                lines,
                _untrusted_presentation_text(assignment.alternate.resource_name),
                width=width,
                initial_indent="   Backup option: ",
                subsequent_indent="                  ",
            )
            _append_wrapped(
                lines,
                _untrusted_presentation_text(assignment.alternate_activation_condition),
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
                _untrusted_presentation_text(primary_handoff.deliverable),
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
                _untrusted_presentation_text(verification),
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
                f"{_untrusted_presentation_text(workstream_name)}: "
                f"{_untrusted_presentation_text(reason or 'Unresolved.')}",
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
            visible = ", ".join(
                _untrusted_presentation_text(item.resource_name) for item in items[:5]
            )
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
    if include_next_action:
        _append_wrapped(
            lines,
            _next_action(plan, has_gaps=bool(gaps)),
            width=width,
            initial_indent="Next: ",
            subsequent_indent="      ",
        )
    _append_wrapped(
        lines,
        "AtReady only recommends resources where they fit.",
        width=width,
    )
    lines.append(_FINAL_SAFETY_BOUNDARY)
    return "\n".join(lines) + "\n"


def _render_complete_agent_summary(
    plan: RoutePlan,
    *,
    goal: str | None,
    width: int,
) -> str:
    """Render the exact compact response used by the bundled agent workflow.

    Unlike the terminal-oriented summary, this view groups assignments by resource so the host
    can return it verbatim without duplicating names or reconstructing route evidence.
    """

    width = max(width, 20)
    assigned_count = sum(assignment.primary is not None for assignment in plan.assignments)
    gaps = [assignment for assignment in plan.assignments if assignment.primary is None]
    unresolved_count = sum(len(assignment.unresolved_gaps) for assignment in plan.assignments)
    gap_count = len(gaps) + unresolved_count
    lines: list[str] = []
    if goal:
        _append_wrapped(
            lines,
            _untrusted_presentation_text(goal),
            width=width,
            initial_indent="Goal: ",
            subsequent_indent="      ",
        )
    if gap_count:
        noun = "gap" if gap_count == 1 else "gaps"
        status = (
            f"Route: {assigned_count} of {len(plan.assignments)} steps assigned; "
            f"{gap_count} open {noun}."
        )
    else:
        noun = "step" if assigned_count == 1 else "steps"
        status = f"Route: {assigned_count} {noun} assigned."
    _append_wrapped(lines, status, width=width)

    unverified_by_resource: dict[str, list[str]] = defaultdict(list)
    general_warnings: list[str] = []
    unresolved_codes = {
        gap.code for assignment in plan.assignments for gap in assignment.unresolved_gaps
    }
    for warning in plan.warnings:
        if "unresolved capability gap" in warning or any(
            f"[{code}]" in warning for code in unresolved_codes
        ):
            continue
        unverified = _selected_unverified_warning(warning)
        if unverified:
            workstream, role, resource, issues = unverified
            assignment = next(
                (item for item in plan.assignments if item.workstream_id == workstream),
                None,
            )
            selection = getattr(assignment, role, None) if assignment else None
            resource_key = (
                selection.resource_id
                if selection is not None
                and resource in {selection.resource_id, selection.resource_name}
                else resource
            )
            for issue in issues:
                if issue not in unverified_by_resource[resource_key]:
                    unverified_by_resource[resource_key].append(issue)
        else:
            general_warnings.append(_plain_warning(warning))

    primary_groups: dict[str, list[RouteAssignment]] = defaultdict(list)
    support_groups: dict[str, list[RouteAssignment]] = defaultdict(list)
    alternate_groups: dict[str, list[RouteAssignment]] = defaultdict(list)
    resource_order: list[str] = []
    resource_names: dict[str, str] = {}
    for assignment in plan.assignments:
        for selection, groups in (
            (assignment.primary, primary_groups),
            (assignment.support, support_groups),
            (assignment.alternate, alternate_groups),
        ):
            if selection is None:
                continue
            groups[selection.resource_id].append(assignment)
            resource_names[selection.resource_id] = selection.resource_name
            if selection.resource_id not in resource_order:
                resource_order.append(selection.resource_id)

    selected_resource_ids = set(resource_order)

    generic_primary_reason = "Best eligible match after applying the project constraints."
    generic_primary_resources: set[str] = set()
    for resource_id, assignments in primary_groups.items():
        selection = assignments[0].primary
        assert selection is not None
        has_continuity = any(
            adjustment.code == "same-primary-continuity"
            for assignment in assignments
            for candidate in assignment.candidates
            if candidate.resource_id == resource_id
            for adjustment in candidate.adjustments
        )
        if (
            not has_continuity
            and _plain_selection_reason(selection.reason) == generic_primary_reason
        ):
            generic_primary_resources.add(resource_id)

    gate_contexts: list[str] = []
    for assignment in plan.assignments:
        context = _primary_gate_context(assignment, selected_resource_ids)
        if context is not None and context not in gate_contexts:
            gate_contexts.append(context)

    for resource_id in resource_order:
        name = resource_names[resource_id]
        primary_assignments = primary_groups[resource_id]
        support_assignments = support_groups[resource_id]
        alternate_assignments = alternate_groups[resource_id]
        clauses: list[str] = []
        if primary_assignments:
            steps = ", ".join(
                _untrusted_presentation_text(item.workstream_name) for item in primary_assignments
            )
            clauses.append(steps)
            selection = primary_assignments[0].primary
            assert selection is not None
            reason = _untrusted_presentation_text(_plain_selection_reason(selection.reason))
            has_continuity = any(
                adjustment.code == "same-primary-continuity"
                for assignment in primary_assignments
                for candidate in assignment.candidates
                if candidate.resource_id == resource_id
                for adjustment in candidate.adjustments
            )
            if has_continuity and len(primary_assignments) > 1:
                reason = (
                    "Best eligible match after project constraints; continuity kept related "
                    "steps together."
                )
            if resource_id not in generic_primary_resources or (
                len(generic_primary_resources) == 1
                and not any(assignment.support for assignment in primary_assignments)
            ):
                clauses.append(f"Why: {reason.rstrip('.')}")
        if support_assignments:
            steps = ", ".join(
                _untrusted_presentation_text(item.workstream_name) for item in support_assignments
            )
            covered = sorted(
                {gap.replace("-", " ") for item in support_assignments for gap in item.support_gap}
            )
            support_text = f"Supports {steps}, covering {', '.join(covered)}"
            if not primary_assignments:
                support_text += (
                    ". Why: It covers a required capability the primary resource does not "
                    "cover alone"
                )
            clauses.append(support_text)
        if alternate_assignments:
            steps = ", ".join(
                _untrusted_presentation_text(item.workstream_name) for item in alternate_assignments
            )
            clauses.append(
                f"Backup option for {steps}. Recheck eligibility and obtain separate "
                "authorization before use. AtReady will not switch automatically"
            )
        text = f"{_untrusted_presentation_text(name)}: " + ". ".join(clauses) + "."
        issues = unverified_by_resource.pop(resource_id, [])
        if issues:
            text += " Uncertainty: " + "; ".join(issues) + "."
        _append_wrapped(lines, text, width=width)

    if len(generic_primary_resources) > 1:
        subject = (
            "Each primary above"
            if len(generic_primary_resources) == len(primary_groups)
            else "Each other primary above"
        )
        _append_wrapped(
            lines,
            f"Why: {subject} is the best eligible match after applying the project constraints.",
            width=width,
        )

    if gate_contexts:
        context = "; ".join(item.rstrip(".") for item in gate_contexts) + "."
        _append_wrapped(
            lines,
            f"Not eligible: {_untrusted_presentation_text(context)}",
            width=width,
        )

    for assignment in gaps:
        _append_wrapped(
            lines,
            f"Gap: {_untrusted_presentation_text(assignment.workstream_name)} is unassigned. "
            f"{_untrusted_presentation_text(assignment.gap_reason)}",
            width=width,
        )
        for evidence in _capacity_gap_evidence(assignment):
            _append_wrapped(
                lines,
                _untrusted_presentation_text(evidence),
                width=width,
                initial_indent="Capacity: ",
                subsequent_indent="          ",
            )
    for assignment in plan.assignments:
        for gap in assignment.unresolved_gaps:
            _append_wrapped(
                lines,
                f"Gap: {_untrusted_presentation_text(assignment.workstream_name)}. "
                f"{_untrusted_presentation_text(gap.reason)}",
                width=width,
            )

    for warning in general_warnings:
        _append_wrapped(
            lines,
            f"Uncertainty: {_untrusted_presentation_text(warning)}",
            width=width,
        )
    for resource, issues in unverified_by_resource.items():
        _append_wrapped(
            lines,
            f"Uncertainty: {_untrusted_presentation_text(resource)}: " + "; ".join(issues) + ".",
            width=width,
        )

    if gaps:
        next_action = _next_action(plan, has_gaps=True)
    elif unresolved_count:
        next_action = "Resolve the open gaps before separately authorizing implementation."
    else:
        next_action = "Use this fit in Codex's plan; separately authorize implementation."
    _append_wrapped(
        lines,
        _untrusted_presentation_text(next_action),
        width=width,
        initial_indent="Next: ",
        subsequent_indent="      ",
    )
    lines.append(_FINAL_SAFETY_BOUNDARY)
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class AgentPresentation:
    """A complete deterministic summary or an explicit limit-conflict response."""

    summary: str
    status: Literal["ready", "limit-conflict"]
    required_words: int
    required_lines: int
    max_words: int | None
    max_lines: int | None


def render_agent_presentation(
    plan: RoutePlan,
    *,
    goal: str | None = None,
    width: int = 100,
    max_words: int | None = None,
    max_lines: int | None = None,
) -> AgentPresentation:
    """Render complete route evidence, or report deterministically that limits conflict.

    The renderer never drops assignments, gaps, uncertainty, or the authorization boundary to
    satisfy a requested limit. The complete route remains available in the presentation envelope.
    """

    complete = _render_complete_agent_summary(plan, goal=goal, width=max(width, 20))
    required_words = len(complete.split())
    required_lines = len(complete.splitlines())
    word_conflict = max_words is not None and required_words > max_words
    line_conflict = max_lines is not None and required_lines > max_lines
    conflicts = word_conflict or line_conflict
    requested_parts: list[str] = []
    required_parts: list[str] = []
    conflicting_flags: list[str] = []
    if max_words is not None:
        requested_parts.append(f"{max_words} {'word' if max_words == 1 else 'words'}")
        required_parts.append(f"{required_words} {'word' if required_words == 1 else 'words'}")
        if word_conflict:
            conflicting_flags.append("--max-words")
    if max_lines is not None:
        requested_parts.append(f"{max_lines} {'line' if max_lines == 1 else 'lines'}")
        required_parts.append(f"{required_lines} {'line' if required_lines == 1 else 'lines'}")
        if line_conflict:
            conflicting_flags.append("--max-lines")
    requested_text = " and ".join(requested_parts)
    required_text = " and ".join(required_parts)
    flags_text = " and ".join(conflicting_flags)
    conflict_summary = (
        "Presentation limit conflict.\n"
        f"Requested maximum: {requested_text}. Complete route summary requires {required_text}.\n"
        f"Rerun without {flags_text} to receive the complete route summary.\n"
        f"{_FINAL_SAFETY_BOUNDARY}\n"
    )
    return AgentPresentation(
        summary=conflict_summary if conflicts else complete,
        status="limit-conflict" if conflicts else "ready",
        required_words=required_words,
        required_lines=required_lines,
        max_words=max_words,
        max_lines=max_lines,
    )


def render_agent_summary(
    plan: RoutePlan,
    *,
    goal: str | None = None,
    width: int = 100,
    max_words: int | None = None,
    max_lines: int | None = None,
) -> str:
    """Render the exact host response, without truncating complete route evidence."""

    return render_agent_presentation(
        plan,
        goal=goal,
        width=width,
        max_words=max_words,
        max_lines=max_lines,
    ).summary


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
            0 if candidate.capacity_pressure_days is not None else 1,
            candidate.capacity_pressure_days or 0,
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
    selected_rank_prefix = (
        selected.adjusted_score_bp,
        selected.components_bp["capability-fit"],
        selected.components_bp["confidence"],
        selected.components_bp["cost-efficiency"],
        selected.components_bp["low-integration-friction"],
    )
    runner_rank_prefix = (
        runner_up.adjusted_score_bp,
        runner_up.components_bp["capability-fit"],
        runner_up.components_bp["confidence"],
        runner_up.components_bp["cost-efficiency"],
        runner_up.components_bp["low-integration-friction"],
    )
    if (
        selected_rank_prefix == runner_rank_prefix
        and selected.capacity_pressure_days is not None
        and (
            runner_up.capacity_pressure_days is None
            or selected.capacity_pressure_days < runner_up.capacity_pressure_days
        )
    ):
        runner_pressure = (
            "no dated pressure"
            if runner_up.capacity_pressure_days is None
            else f"{runner_up.capacity_pressure_days} days"
        )
        return (
            f"{assignment.primary.reason} {comparison} Declared same-unit capacity becomes "
            f"perishable sooner: {selected.capacity_pressure_days} days versus {runner_pressure}."
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
                f"Alternate: **{_text(assignment.alternate.resource_name)}**. "
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
