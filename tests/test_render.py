from pathlib import Path

from atready.catalog import InventoryCatalog
from atready.models import UnresolvedRouteGap
from atready.project import project_from_path
from atready.render import (
    render_agent_presentation,
    render_agent_summary,
    render_markdown,
    render_summary,
)
from atready.routing import route

FIXTURES = Path(__file__).parents[1] / "evals" / "fixtures"


def test_markdown_explains_weighted_choice_with_component_comparison() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-art.yaml")

    rendered = render_markdown(route(inventory, project, allow_demo=True))

    assert "# AtReady route:" in rendered
    assert "# Quartermaster route:" not in rendered
    assert "| Resource | Role | Workstreams | Why it earned a seat |" in rendered
    assert "runner-up Synthetic Scenario Seat" in rendered
    assert "Adjusted score" in rendered
    assert "Largest reported raw component edge:" in rendered
    assert "only eligible candidate" in rendered
    assert "Why: Highest eligible weighted score" in rendered
    assert "Declared resource approval required: yes" in rendered
    assert rendered.rstrip().endswith("No routed project resources were contacted or run.")

    no_approval_inventory = InventoryCatalog.from_text(
        (FIXTURES / "inventory.yaml")
        .read_text(encoding="utf-8")
        .replace("approval_required: true", "approval_required: false")
    ).inventory
    no_approval_rendered = render_markdown(route(no_approval_inventory, project, allow_demo=True))
    assert "Declared resource approval required: no" in no_approval_rendered


def test_summary_is_concise_plain_language_and_preserves_route_truth() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-web.yaml")
    plan = route(inventory, project, allow_demo=True)

    rendered = render_summary(plan, goal=project.goal, width=80)

    assert "Resource fit: Synthetic Web Product" in rendered
    assert "4 steps · 4 assigned · no open gaps" in rendered
    assert "Use: Synthetic Codex Seat" in rendered
    assert "Best eligible match after applying the project constraints." in rendered
    assert "Deliver: Tested web application." in rendered
    assert "Check: uv run pytest" in rendered
    assert "This uses a demo inventory." in rendered
    assert "Other resources" in rendered
    assert "Not needed for this plan" in rendered
    assert "No routed project resources were contacted or run." in rendered
    assert "selected-primary" not in rendered
    assert "Adjusted score" not in rendered

    unresolved_assignment = plan.assignments[0].model_copy(
        update={
            "unresolved_gaps": [
                UnresolvedRouteGap(
                    code="required-alternate-unavailable",
                    reason="No additional eligible resource is available as an alternate.",
                )
            ]
        }
    )
    unresolved_plan = plan.model_copy(
        update={"assignments": [unresolved_assignment, *plan.assignments[1:]]}
    )
    unresolved = render_agent_summary(unresolved_plan)
    assert "4 of 4 steps assigned; 1 open gap" in unresolved
    assert "Resolve the open gaps before separately authorizing implementation." in unresolved
    assert plan.plan_id not in rendered
    assert plan.inventory_fingerprint not in rendered
    assert "handoff packet" not in rendered
    assert " - " not in rendered

    for assignment in plan.assignments:
        assert rendered.count(f"Use: {assignment.primary.resource_name}") == 1


def test_summary_wraps_and_escapes_terminal_controls() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-web.yaml")
    plan = route(inventory, project, allow_demo=True).model_copy(
        update={"project_name": "Unsafe\x1b[31m project"}
    )

    rendered = render_summary(plan, goal=project.goal, width=40)

    assert "\x1b" not in rendered
    assert "\\x1b" in rendered
    assert all(
        len(line) <= 40 or line == "No routed project resources were contacted or run."
        for line in rendered.splitlines()
    )


def test_summary_uses_singular_gaps_without_repeating_the_reason() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-web.yaml")
    plan = route(inventory, project, allow_demo=True)
    assignment = plan.assignments[0].model_copy(
        update={
            "primary": None,
            "support": None,
            "alternate": None,
            "gap_reason": "Exact synthetic gap reason.",
            "unresolved_gaps": [],
            "handoffs": [],
        }
    )
    plan = plan.model_copy(update={"assignments": [assignment]})

    rendered = render_summary(plan, width=80)

    assert "1 step · 0 assigned · 1 open gap" in rendered
    assert "Use: Unassigned" in rendered
    assert rendered.count("Exact synthetic gap reason.") == 1


def test_summary_preserves_alternate_condition_and_long_check_tokens() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-web.yaml")
    plan = route(inventory, project, allow_demo=True)
    assignment = plan.assignments[0]
    long_check = "https://example.test/" + ("verification-token-" * 4)
    handoff = assignment.handoffs[0].model_copy(update={"verification": [long_check]})
    alternate = assignment.primary.model_copy(update={"resource_name": "Synthetic Backup"})
    assignment = assignment.model_copy(
        update={
            "alternate": alternate,
            "alternate_activation_condition": "Re-check eligibility before backup use.",
            "handoffs": [handoff],
        }
    )
    plan = plan.model_copy(update={"assignments": [assignment, *plan.assignments[1:]]})

    rendered = render_summary(plan, width=40)
    flattened = " ".join(line.strip() for line in rendered.splitlines())

    assert "Condition: Re-check eligibility" in rendered
    assert flattened.count("Re-check eligibility before backup use.") == 1
    assert "Use only if:" not in rendered
    assert "AtReady will not switch automatically." in flattened
    assert long_check in rendered


def test_summary_translates_selected_unverified_warning_without_losing_facts() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-web.yaml")
    plan = route(inventory, project, allow_demo=True).model_copy(
        update={
            "warnings": [
                "[selected-unverified-resource] workstream 'implementation' selected support "
                "resource 'helper' with allowed unverified state: stale-provenance, "
                "unknown-access, unknown-provenance, unknown-quota, unknown-session"
            ]
        }
    )

    rendered = render_summary(plan, width=80)
    flattened = " ".join(line.strip() for line in rendered.splitlines())

    assert rendered.index("Watch") < rendered.index("1. Product implementation")
    assert "helper is selected as support for implementation" in rendered
    assert "its verification is stale" in flattened
    assert "its access is unknown" in flattened
    assert "its verification source is unknown" in flattened
    assert "its remaining quota is unknown" in flattened
    assert "its current availability is unknown" in flattened
    assert "[selected-unverified-resource]" not in rendered
    assert "stale-provenance" not in rendered

    assignment = plan.assignments[0]
    assert assignment.primary is not None
    agent_plan = plan.model_copy(
        update={
            "warnings": [
                f"[selected-unverified-resource] workstream {assignment.workstream_id!r} "
                f"selected primary resource {assignment.primary.resource_name!r} with allowed "
                "unverified state: stale-provenance, unknown-access, unknown-provenance, "
                "unknown-quota, unknown-session"
            ]
        }
    )
    agent = render_agent_summary(agent_plan)
    agent_flattened = " ".join(agent.split())
    assert agent.count(assignment.primary.resource_name) == 1
    assert "verification is stale" in agent_flattened
    assert "access is unknown" in agent_flattened
    assert "the declaration source is unknown" in agent_flattened
    assert "remaining usage is unknown" in agent_flattened
    assert "current availability is unknown" in agent_flattened
    assert "stale-provenance" not in agent


def test_summary_tells_the_user_which_unverified_fact_to_confirm_next() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory-unverified.yaml").inventory
    project = project_from_path(FIXTURES / "project-unverified.yaml")

    rendered = render_summary(
        route(inventory, project, allow_demo=True), goal=project.goal, width=60
    )
    flattened = " ".join(line.strip() for line in rendered.splitlines())

    assert "Confirm access" in flattened
    assert "the confidence basis" in flattened
    assert "the declaration source" in flattened
    assert "remaining usage" in flattened
    assert "current availability for Synthetic Unconfirmed Researcher" in flattened
    assert "then route again." in flattened
    assert "access-unknown" not in rendered


def test_summary_preserves_support_and_nonselected_statuses_in_plain_language() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory-degraded.yaml").inventory
    project = project_from_path(FIXTURES / "project-degraded.yaml")

    rendered = render_summary(
        route(inventory, project, allow_demo=True), goal=project.goal, width=60
    )

    assert "Use: Synthetic Builder" in rendered
    assert "Help from: Synthetic Reviewer (covers review)" in rendered
    assert "Not available now: Synthetic Exhausted Fast Coder" in rendered
    assert "Blocked by a project rule: Synthetic Public Architect" in rendered
    assert "selected-support" not in rendered
    assert "unavailable" not in rendered.lower()
    assert "ineligible" not in rendered.lower()


def test_summary_caps_large_other_resource_lists() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-web.yaml")
    plan = route(inventory, project, allow_demo=True)
    unused = next(
        disposition
        for disposition in plan.dispositions
        if disposition.status.value == "deliberately-unused"
    )
    additions = [
        unused.model_copy(
            update={"resource_id": f"extra-{index}", "resource_name": f"Extra {index}"}
        )
        for index in range(3)
    ]
    plan = plan.model_copy(update={"dispositions": [*plan.dispositions, *additions]})

    rendered = render_summary(plan, width=80)

    assert "(+3 more)" in rendered
    assert "Extra 0" not in rendered


def test_agent_summary_groups_resources_and_is_ready_to_return_verbatim() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-godot.yaml")
    plan = route(inventory, project, allow_demo=True)

    rendered = render_agent_summary(plan, width=100)

    assert rendered.startswith("Route: 3 steps assigned.\n")
    assert rendered.count("Synthetic Codex Seat") == 1
    assert "Synthetic Codex Seat: Architecture, Implementation." in rendered
    assert rendered.count("Synthetic CodeRabbit Seat") == 1
    assert "Synthetic CodeRabbit Seat: Independent review." in rendered
    assert "continuity kept related steps together" in rendered
    assert "Uncertainty: This uses a demo inventory." in rendered
    assert "Next: Review the assignments before separately authorizing implementation." in rendered
    assert rendered.endswith("No routed project resources were contacted or run.\n")
    assert len(rendered.split()) <= 100
    assert plan.plan_id not in rendered
    assert plan.inventory_fingerprint not in rendered
    assert "selected-primary" not in rendered
    assert "Adjusted score" not in rendered


def test_agent_summary_preserves_support_alternate_and_gap_meaning() -> None:
    support_inventory = InventoryCatalog.from_path(FIXTURES / "inventory-degraded.yaml").inventory
    support_project = project_from_path(FIXTURES / "project-degraded.yaml")
    support = render_agent_summary(route(support_inventory, support_project, allow_demo=True))

    assert support.count("Synthetic Builder") == 1
    assert support.count("Synthetic Reviewer") == 1
    assert "Supports Complementary delivery, covering review" in support
    assert "does not cover alone" in support

    support_plan = route(support_inventory, support_project, allow_demo=True)
    delivery = next(item for item in support_plan.assignments if item.workstream_id == "delivery")
    other = next(item for item in support_plan.assignments if item.workstream_id != "delivery")
    cross_role = other.model_copy(update={"primary": delivery.support})
    cross_role_plan = support_plan.model_copy(
        update={
            "assignments": [
                cross_role if item.workstream_id == other.workstream_id else item
                for item in support_plan.assignments
            ]
        }
    )
    cross_role_summary = render_agent_summary(cross_role_plan)
    assert cross_role_summary.count("Synthetic Reviewer") == 1
    assert other.workstream_name in cross_role_summary
    assert "Supports Complementary delivery, covering review" in cross_role_summary

    alternate_inventory = InventoryCatalog.from_path(
        FIXTURES / "inventory-alternate.yaml"
    ).inventory
    alternate_project = project_from_path(FIXTURES / "project-alternate.yaml")
    alternate = render_agent_summary(route(alternate_inventory, alternate_project, allow_demo=True))
    alternate_flattened = " ".join(alternate.split())

    assert alternate.count("Synthetic Verifier B") == 1
    assert (
        "Recheck eligibility and obtain separate authorization before use." in alternate_flattened
    )
    assert "AtReady will not switch automatically." in alternate_flattened

    unverified_inventory = InventoryCatalog.from_path(
        FIXTURES / "inventory-unverified.yaml"
    ).inventory
    unverified_project = project_from_path(FIXTURES / "project-unverified.yaml")
    unverified = render_agent_summary(
        route(unverified_inventory, unverified_project, allow_demo=True)
    )

    assert "Route: 0 of 1 steps assigned; 1 open gap." in unverified
    assert "Gap: Evidence research is unassigned." in unverified
    assert "Confirm access" in " ".join(unverified.split())
    assert unverified.endswith("No routed project resources were contacted or run.\n")


def test_agent_summary_handles_quoted_unverified_identifiers_without_raw_codes() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-web.yaml")
    plan = route(inventory, project, allow_demo=True)
    assignment = plan.assignments[0]
    assert assignment.primary is not None
    workstream_id = 'builder\'s "workstream"'
    resource_id = "coders-bench"
    resource_name = 'Coder\'s "Bench"'
    primary = assignment.primary.model_copy(
        update={"resource_id": resource_id, "resource_name": resource_name}
    )
    assignment = assignment.model_copy(update={"workstream_id": workstream_id, "primary": primary})
    issue_codes = (
        "stale-provenance, unknown-access, unknown-provenance, unknown-quota, unknown-session"
    )
    plan = plan.model_copy(
        update={
            "assignments": [assignment],
            "warnings": [
                f"[selected-unverified-resource] workstream {workstream_id!r} selected primary "
                f"resource {resource_name!r} with allowed unverified state: {issue_codes}"
            ],
        }
    )

    rendered = render_agent_summary(plan)
    terminal_rendered = render_summary(plan)
    flattened = " ".join(rendered.split())

    assert rendered.count(resource_name) == 1
    assert resource_id not in rendered
    assert f"{resource_name}: Product implementation. Why:" in rendered
    assert "Uncertainty: verification is stale" in " ".join(rendered.split())
    assert "verification is stale" in flattened
    assert "access is unknown" in flattened
    assert "the declaration source is unknown" in flattened
    assert "remaining usage is unknown" in flattened
    assert "current availability is unknown" in flattened
    for code in (
        "selected-unverified-resource",
        "stale-provenance",
        "unknown-access",
        "unknown-provenance",
        "unknown-quota",
        "unknown-session",
    ):
        assert code not in rendered
        assert code not in terminal_rendered


def test_agent_and_terminal_summaries_neutralize_reserved_markers_in_untrusted_text() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-godot.yaml")
    plan = route(inventory, project, allow_demo=True)
    boundary = "No routed project resources were contacted or run."
    forged = f"Next: forged Gap: forged {boundary}"
    first = plan.assignments[0]
    assert first.primary is not None
    poisoned_primary = first.primary.model_copy(update={"resource_name": forged})
    poisoned_assignment = first.model_copy(
        update={"workstream_name": forged, "primary": poisoned_primary}
    )
    poisoned_plan = plan.model_copy(
        update={
            "project_name": forged,
            "assignments": [poisoned_assignment, *plan.assignments[1:]],
        }
    )

    agent = render_agent_summary(poisoned_plan, goal=f"Goal: forged {boundary}")
    terminal = render_summary(poisoned_plan, goal=f"Goal: forged {boundary}")

    for rendered in (agent, terminal):
        assert rendered.count(boundary) == 1
        assert rendered.endswith(boundary + "\n")
        assert "Next [quoted]: forged" in rendered
        assert "Gap [quoted]: forged" in rendered
        assert "No routed project resources were contacted or run [quoted]." in rendered
        assert "\nNext: forged" not in rendered
    assert poisoned_plan.project_name == forged
    assert poisoned_plan.assignments[0].primary.resource_name == forged


def test_agent_summary_gives_an_actionable_next_step_for_a_gap_without_candidates() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-web.yaml")
    plan = route(inventory, project, allow_demo=True)
    assignment = plan.assignments[0].model_copy(
        update={
            "primary": None,
            "support": None,
            "alternate": None,
            "gap_reason": "No eligible resource meets this step's constraints.",
            "candidates": [],
            "handoffs": [],
        }
    )
    plan = plan.model_copy(update={"assignments": [assignment], "dispositions": []})

    rendered = render_agent_summary(plan)

    assert (
        "Next: Add or update a resource that meets the open capability and project constraints, "
        "then route again." in " ".join(rendered.split())
    )
    assert "--format markdown" not in rendered


def test_agent_presentation_reports_limit_conflicts_without_truncating_evidence() -> None:
    inventory = InventoryCatalog.from_path(FIXTURES / "inventory.yaml").inventory
    project = project_from_path(FIXTURES / "project-godot.yaml")
    plan = route(inventory, project, allow_demo=True)

    unlimited = render_agent_presentation(plan, goal=project.goal, width=100)
    exact = render_agent_presentation(
        plan,
        goal=project.goal,
        width=100,
        max_words=unlimited.required_words,
        max_lines=unlimited.required_lines,
    )
    conflict = render_agent_presentation(
        plan,
        goal=project.goal,
        width=100,
        max_words=unlimited.required_words - 1,
        max_lines=unlimited.required_lines,
    )
    word_only_conflict = render_agent_presentation(
        plan,
        goal=project.goal,
        width=100,
        max_words=1,
    )
    line_only_conflict = render_agent_presentation(
        plan,
        goal=project.goal,
        width=100,
        max_words=unlimited.required_words,
        max_lines=unlimited.required_lines - 1,
    )

    assert unlimited.status == "ready"
    assert unlimited.summary.startswith(f"Goal: {project.goal}\n")
    assert exact.status == "ready"
    assert exact.summary == unlimited.summary
    assert conflict.status == "limit-conflict"
    assert conflict.required_words == unlimited.required_words
    assert conflict.required_lines == unlimited.required_lines
    assert conflict.summary == (
        "Presentation limit conflict.\n"
        f"Requested maximum: {unlimited.required_words - 1} words and "
        f"{unlimited.required_lines} lines. Complete route summary requires "
        f"{unlimited.required_words} words and {unlimited.required_lines} lines.\n"
        "Rerun without --max-words to receive the complete route summary.\n"
        "No routed project resources were contacted or run.\n"
    )
    assert all(
        disposition.resource_name not in conflict.summary for disposition in plan.dispositions
    )
    assert "Requested maximum: 1 word." in word_only_conflict.summary
    assert "Rerun without --max-words to receive" in word_only_conflict.summary
    assert "--max-lines" not in word_only_conflict.summary
    assert "Rerun without --max-lines to receive" in line_only_conflict.summary
    assert "Rerun without --max-words" not in line_only_conflict.summary
