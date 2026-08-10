from pathlib import Path

from atready.catalog import InventoryCatalog
from atready.project import project_from_path
from atready.render import render_markdown
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

    no_approval_inventory = InventoryCatalog.from_text(
        (FIXTURES / "inventory.yaml")
        .read_text(encoding="utf-8")
        .replace("approval_required: true", "approval_required: false")
    ).inventory
    no_approval_rendered = render_markdown(route(no_approval_inventory, project, allow_demo=True))
    assert "Declared resource approval required: no" in no_approval_rendered
