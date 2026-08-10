from pathlib import Path

from atready.catalog import InventoryCatalog
from atready.project import project_from_path
from atready.render import render_markdown, render_summary
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

    assert "Resource plan: Synthetic Web Product" in rendered
    assert "4 steps - 4 assigned - no open gaps" in rendered
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
    assert plan.plan_id not in rendered
    assert plan.inventory_fingerprint not in rendered
    assert "handoff packet" not in rendered

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

    assert "1 step - 0 assigned - 1 open gap" in rendered
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
