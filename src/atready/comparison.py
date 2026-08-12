"""Compare two deterministic route plans without changing either one."""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import TextWrapper

from atready.models import RouteAssignment, RoutePlan

_FINAL_SAFETY_BOUNDARY = "No routed project resources were contacted or run."
_RESERVED_MARKERS = ("Resource fit comparison", "Before:", "After:", "New gaps:", "Next:")
_CAPACITY_GAPS = {
    "capacity-insufficient": "declared capacity is below the requested amount",
    "capacity-reset-unknown": "capacity after the declared reset is unknown",
    "capacity-unit-mismatch": "demand and capacity use different units",
    "capacity-unknown": "exact capacity is unknown",
    "no-eligible-primary": "no declared resource satisfies every requirement",
}


@dataclass(frozen=True)
class AssignmentState:
    """The resource selections and unresolved gaps for one workstream."""

    primary_id: str | None
    primary_name: str | None
    support_id: str | None
    support_name: str | None
    alternate_id: str | None
    alternate_name: str | None
    gaps: tuple[str, ...]

    def as_dict(self) -> dict[str, str | list[str] | None]:
        return {
            "primary": (
                {"id": self.primary_id, "name": self.primary_name}
                if self.primary_id is not None
                else None
            ),
            "support": (
                {"id": self.support_id, "name": self.support_name}
                if self.support_id is not None
                else None
            ),
            "alternate": (
                {"id": self.alternate_id, "name": self.alternate_name}
                if self.alternate_id is not None
                else None
            ),
            "gaps": list(self.gaps),
        }


@dataclass(frozen=True)
class RouteChange:
    """One added, removed, or materially changed workstream route."""

    workstream_id: str
    workstream_name: str
    kind: str
    before: AssignmentState | None
    after: AssignmentState | None

    def as_dict(self) -> dict[str, object]:
        return {
            "workstream_id": self.workstream_id,
            "workstream_name": self.workstream_name,
            "kind": self.kind,
            "before": self.before.as_dict() if self.before is not None else None,
            "after": self.after.as_dict() if self.after is not None else None,
        }


@dataclass(frozen=True)
class RouteComparison:
    """A bounded comparison of two complete route plans."""

    baseline_plan_id: str
    alternative_plan_id: str
    changes: tuple[RouteChange, ...]
    unchanged_workstreams: int

    def as_dict(self) -> dict[str, object]:
        return {
            "format": "atready-route-comparison-v1",
            "baseline_plan_id": self.baseline_plan_id,
            "alternative_plan_id": self.alternative_plan_id,
            "changed_workstreams": len(self.changes),
            "unchanged_workstreams": self.unchanged_workstreams,
            "changes": [change.as_dict() for change in self.changes],
        }


def _state(assignment: RouteAssignment) -> AssignmentState:
    gaps = [gap.code for gap in assignment.unresolved_gaps]
    if assignment.primary is None:
        gaps.append("no-eligible-primary")
    return AssignmentState(
        primary_id=assignment.primary.resource_id if assignment.primary else None,
        primary_name=assignment.primary.resource_name if assignment.primary else None,
        support_id=assignment.support.resource_id if assignment.support else None,
        support_name=assignment.support.resource_name if assignment.support else None,
        alternate_id=assignment.alternate.resource_id if assignment.alternate else None,
        alternate_name=assignment.alternate.resource_name if assignment.alternate else None,
        gaps=tuple(sorted(gaps)),
    )


def compare_routes(baseline: RoutePlan, alternative: RoutePlan) -> RouteComparison:
    """Return only material assignment and gap changes between two plans."""

    before = {item.workstream_id: item for item in baseline.assignments}
    after = {item.workstream_id: item for item in alternative.assignments}
    changes: list[RouteChange] = []
    unchanged = 0
    for workstream_id in sorted(before.keys() | after.keys()):
        baseline_assignment = before.get(workstream_id)
        alternative_assignment = after.get(workstream_id)
        baseline_state = _state(baseline_assignment) if baseline_assignment else None
        alternative_state = _state(alternative_assignment) if alternative_assignment else None
        if baseline_assignment is None:
            kind = "added-workstream"
        elif alternative_assignment is None:
            kind = "removed-workstream"
        elif baseline_state == alternative_state:
            unchanged += 1
            continue
        else:
            kind = "changed-route"
        assignment = alternative_assignment or baseline_assignment
        assert assignment is not None
        changes.append(
            RouteChange(
                workstream_id=workstream_id,
                workstream_name=assignment.workstream_name,
                kind=kind,
                before=baseline_state,
                after=alternative_state,
            )
        )
    return RouteComparison(
        baseline_plan_id=baseline.plan_id,
        alternative_plan_id=alternative.plan_id,
        changes=tuple(changes),
        unchanged_workstreams=unchanged,
    )


def _selection_text(state: AssignmentState | None) -> str:
    if state is None:
        return "Workstream absent"
    if state.primary_name is None:
        return "No resource assigned"
    parts = [f"Use {state.primary_name}"]
    if state.support_name is not None:
        parts.append(f"help from {state.support_name}")
    if state.alternate_name is not None:
        parts.append(f"backup option {state.alternate_name}")
    return "; ".join(parts)


def _safe_text(value: str) -> str:
    text = " ".join(
        "".join(
            character
            if character.isprintable()
            else character.encode("unicode_escape").decode("ascii")
            for character in value
        ).split()
    ).replace(_FINAL_SAFETY_BOUNDARY, "No routed resources were contacted or run [quoted].")
    for marker in _RESERVED_MARKERS:
        text = text.replace(marker, f"{marker.rstrip(':')} [quoted]")
    return text


def _gap_text(gaps: list[str]) -> str:
    return ", ".join(_CAPACITY_GAPS.get(gap, gap.replace("-", " ")) for gap in gaps)


def render_route_comparison(comparison: RouteComparison, *, width: int = 80) -> str:
    """Render a complete, plain-language comparison without scores or candidate dumps."""

    wrapper = TextWrapper(
        width=max(40, min(width, 120)),
        break_long_words=True,
        break_on_hyphens=False,
        subsequent_indent="   ",
    )
    count = len(comparison.changes)
    lines = [
        "Resource fit comparison",
        (
            f"{count} {'workstream changed' if count == 1 else 'workstreams changed'}; "
            f"{comparison.unchanged_workstreams} unchanged."
        ),
    ]
    if not comparison.changes:
        lines.append("The assignments and gaps are the same in both routes.")
    for index, change in enumerate(comparison.changes, start=1):
        lines.append("")
        lines.extend(wrapper.wrap(f"{index}. {_safe_text(change.workstream_name)}"))
        lines.extend(wrapper.wrap(f"Before: {_safe_text(_selection_text(change.before))}"))
        lines.extend(wrapper.wrap(f"After: {_safe_text(_selection_text(change.after))}"))
        before_gaps = set(change.before.gaps if change.before else ())
        after_gaps = set(change.after.gaps if change.after else ())
        added_gaps = sorted(after_gaps - before_gaps)
        closed_gaps = sorted(before_gaps - after_gaps)
        if added_gaps:
            lines.extend(wrapper.wrap("New gaps: " + _gap_text(added_gaps)))
        if closed_gaps:
            lines.extend(wrapper.wrap("Closed gaps: " + _gap_text(closed_gaps)))
    lines.append("")
    lines.extend(
        wrapper.wrap("Next: review these differences before choosing which constraints to keep.")
    )
    # The exact boundary is a contract marker and must remain one final line even below its width.
    lines.append(_FINAL_SAFETY_BOUNDARY)
    return "\n".join(lines) + "\n"
