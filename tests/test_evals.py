from __future__ import annotations

import socket
from pathlib import Path

import pytest

from atready.catalog import InventoryCatalog
from atready.project import project_from_path
from atready.routing import route

FIXTURES = Path(__file__).parents[1] / "evals" / "fixtures"


@pytest.mark.parametrize(
    ("project_file", "expected_primaries"),
    [
        ("project-godot.yaml", ["codex", "codex", "coderabbit"]),
        ("project-web.yaml", ["codex", "openrouter", "upstash", "vercel"]),
        ("project-art.yaml", ["native-imagegen", "scenario", "aseprite"]),
    ],
)
def test_public_synthetic_routes_are_exact_repeatable_and_offline(
    project_file: str,
    expected_primaries: list[str],
    monkeypatch,
) -> None:
    def fail_network(*_args, **_kwargs):
        raise AssertionError("public eval routing must remain offline")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    project = project_from_path(FIXTURES / project_file)
    catalog = InventoryCatalog.from_path(FIXTURES / "inventory.yaml", today=project.as_of)

    first = route(catalog.inventory, project, allow_demo=True)
    second = route(catalog.inventory, project, allow_demo=True)

    assert [
        assignment.primary.resource_id for assignment in first.assignments
    ] == expected_primaries
    assert first.plan_id == second.plan_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert len(first.dispositions) == len(catalog.inventory.resources)
    assert len({item.resource_id for item in first.dispositions}) == len(first.dispositions)
    assert all(assignment.handoffs for assignment in first.assignments)
    assert all(len(assignment.handoffs) == 1 for assignment in first.assignments)
    assert catalog.inventory.preferences.allow_purchase_suggestions is False


def test_runpod_is_deliberately_unused_for_small_art_batch() -> None:
    project = project_from_path(FIXTURES / "project-art.yaml")
    catalog = InventoryCatalog.from_path(FIXTURES / "inventory.yaml", today=project.as_of)

    plan = route(catalog.inventory, project, allow_demo=True)
    runpod = next(item for item in plan.dispositions if item.resource_id == "runpod")

    assert runpod.status == "deliberately-unused"
    assert runpod.reason_code == "no-applicable-capability"


def test_degraded_route_reroutes_pairs_support_and_enforces_data_policy(
    monkeypatch,
) -> None:
    def fail_network(*_args, **_kwargs):
        raise AssertionError("degraded eval routing must remain offline")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    project = project_from_path(FIXTURES / "project-degraded.yaml")
    catalog = InventoryCatalog.from_path(
        FIXTURES / "inventory-degraded.yaml",
        today=project.as_of,
    )

    first = route(catalog.inventory, project, allow_demo=True)
    second = route(catalog.inventory, project, allow_demo=True)
    implementation, delivery, architecture = first.assignments
    dispositions = {item.resource_id: item for item in first.dispositions}

    assert len(first.dispositions) == len(catalog.inventory.resources)
    assert len(dispositions) == len(first.dispositions)
    assert set(dispositions) == {resource.id for resource in catalog.inventory.resources}
    assert all(assignment.handoffs for assignment in first.assignments)
    assert implementation.primary.resource_id == "backup-coder"
    assert delivery.primary.resource_id == "builder"
    assert delivery.support.resource_id == "reviewer"
    assert delivery.support_gap == ["review"]
    assert architecture.primary.resource_id == "private-architect"
    assert dispositions["fast-coder"].status == "unavailable"
    assert dispositions["fast-coder"].reason_code == "quota-exhausted"
    assert dispositions["public-architect"].status == "ineligible"
    assert dispositions["public-architect"].reason_code == "data-class-disallowed"
    assert first.plan_id == second.plan_id
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
