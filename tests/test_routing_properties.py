from __future__ import annotations

import os
import socket
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import hypothesis.strategies as st
from hypothesis import given, settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from atready.catalog import InventoryCatalog
from atready.inventory_edit import (
    commit_add_resource,
    commit_remove_resource,
    commit_replace_resource,
    plan_add_resource,
    plan_remove_resource,
    plan_replace_resource,
    read_inventory_file,
    resource_from_mapping,
)
from atready.models import AccessStatus
from atready.paths import create_private_file
from atready.project import project_from_path
from atready.routing import route
from atready.templates import starter_inventory

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "evals" / "fixtures"
TODAY = date(2026, 8, 10)
RESOURCE_IDS = ("synthetic-a", "synthetic-b", "synthetic-c")
STRENGTHS = (0.40, 0.65, 0.80, 0.95)
ELEVATED = os.environ.get("ATREADY_ELEVATED_HYPOTHESIS") == "1"
ROUTE_EXAMPLES = 40 if ELEVATED else 12
DOMINATED_EXAMPLES = 24 if ELEVATED else 8
STATE_MACHINE_EXAMPLES = 20 if ELEVATED else 6
STATE_MACHINE_STEPS = 8 if ELEVATED else 5


def _deny_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("property tests must remain offline")


def _fixture_case():
    project = project_from_path(FIXTURES / "project-godot.yaml")
    inventory = InventoryCatalog.from_path(
        FIXTURES / "inventory.yaml", today=project.as_of
    ).inventory
    return inventory, project


def _assignment_projection(plan) -> list[tuple[object, ...]]:
    return [
        (
            assignment.workstream_id,
            assignment.primary.resource_id if assignment.primary else None,
            assignment.support.resource_id if assignment.support else None,
            assignment.alternate.resource_id if assignment.alternate else None,
            assignment.gap_reason,
            tuple((gap.code, gap.message) for gap in assignment.unresolved_gaps),
        )
        for assignment in plan.assignments
    ]


@st.composite
def _routing_variants(draw):
    inventory, _project = _fixture_case()
    order = draw(st.permutations(tuple(range(len(inventory.resources)))))
    forbidden = draw(
        st.sets(st.sampled_from(tuple(resource.id for resource in inventory.resources)), max_size=3)
    )
    return order, forbidden


@given(_routing_variants())
@settings(max_examples=ROUTE_EXAMPLES, deadline=None)
def test_route_is_order_independent_and_respects_generated_forbidden_sets(variant) -> None:
    order, forbidden = variant
    inventory, project = _fixture_case()
    reordered = inventory.model_copy(
        update={"resources": [inventory.resources[index] for index in order]}
    )
    constrained = project.model_copy(
        update={
            "constraints": project.constraints.model_copy(
                update={"forbidden_resources": sorted(forbidden)}
            )
        }
    )

    with (
        patch.object(socket.socket, "connect", _deny_network),
        patch.object(socket, "create_connection", _deny_network),
        patch.object(socket, "getaddrinfo", _deny_network),
    ):
        canonical = route(inventory, constrained, allow_demo=True)
        transformed = route(reordered, constrained, allow_demo=True)

    assert canonical.model_dump(mode="json") == transformed.model_dump(mode="json")
    selected = {
        choice.resource_id
        for assignment in transformed.assignments
        for choice in (assignment.primary, assignment.support, assignment.alternate)
        if choice is not None
    }
    assert selected.isdisjoint(forbidden)


@given(st.permutations(tuple(range(9))))
@settings(max_examples=DOMINATED_EXAMPLES, deadline=None)
def test_adding_a_dominated_ineligible_resource_cannot_change_assignments(order) -> None:
    inventory, project = _fixture_case()
    baseline = route(inventory, project, allow_demo=True)
    source = inventory.resources[order[0]]
    dominated = source.model_copy(
        update={
            "id": "synthetic-inactive-resource",
            "name": "Synthetic Inactive Resource",
            "access": source.access.model_copy(update={"status": AccessStatus.INACTIVE}),
        }
    )
    expanded = inventory.model_copy(update={"resources": [*inventory.resources, dominated]})

    transformed = route(expanded, project, allow_demo=True)

    assert _assignment_projection(transformed) == _assignment_projection(baseline)
    assert all(
        next(
            candidate
            for candidate in assignment.candidates
            if candidate.resource_id == dominated.id
        ).eligible_for_role
        is False
        for assignment in transformed.assignments
    )


def _resource(resource_id: str, strength: float):
    return resource_from_mapping(
        {
            "id": resource_id,
            "name": f"Synthetic {resource_id}",
            "categories": ["synthetic-tool"],
            "capabilities": {"code-implementation": strength},
            "access": {
                "status": "active",
                "interaction": "local-cli",
                "current_session": "available",
            },
            "economics": {"marginal_cost": 0.0, "quota": "ample"},
            "policy": {"allowed_data_classes": ["public"], "approval_required": True},
            "provenance": {"basis": "observed", "last_verified": TODAY},
        }
    )


class InventoryEditStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self._temporary = tempfile.TemporaryDirectory(prefix="atready-stateful-")
        self.target = Path(self._temporary.name).resolve() / "inventory.yaml"
        create_private_file(self.target, starter_inventory())
        self.expected: dict[str, float] = {}

    @rule(resource_id=st.sampled_from(RESOURCE_IDS), strength=st.sampled_from(STRENGTHS))
    def add_resource(self, resource_id: str, strength: float) -> None:
        if resource_id in self.expected:
            return
        before = self.target.read_bytes()
        plan = plan_add_resource(self.target, _resource(resource_id, strength))
        assert self.target.read_bytes() == before
        receipt = commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
        assert receipt.replacement_verified
        self.expected[resource_id] = strength

    @precondition(lambda self: bool(self.expected))
    @rule(strength=st.sampled_from(STRENGTHS))
    def replace_first_resource(self, strength: float) -> None:
        resource_id = sorted(self.expected)[0]
        if self.expected[resource_id] == strength:
            return
        before = self.target.read_bytes()
        plan = plan_replace_resource(self.target, _resource(resource_id, strength))
        assert self.target.read_bytes() == before
        receipt = commit_replace_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
        assert receipt.replacement_verified
        self.expected[resource_id] = strength

    @precondition(lambda self: bool(self.expected))
    @rule()
    def remove_first_resource(self) -> None:
        resource_id = sorted(self.expected)[0]
        before = self.target.read_bytes()
        plan = plan_remove_resource(self.target, resource_id)
        assert self.target.read_bytes() == before
        receipt = commit_remove_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
        assert receipt.replacement_verified
        del self.expected[resource_id]

    @invariant()
    def inventory_matches_the_state_model(self) -> None:
        parsed = read_inventory_file(self.target).inventory
        observed = {
            resource.id: resource.capabilities["code-implementation"]
            for resource in parsed.resources
        }
        assert observed == self.expected
        assert parsed.inventory_kind.value == "personal"
        assert parsed.revision_privacy_nonce is not None

    def teardown(self) -> None:
        self._temporary.cleanup()


class TestInventoryEditStateMachine(InventoryEditStateMachine.TestCase):
    settings = settings(
        max_examples=STATE_MACHINE_EXAMPLES,
        stateful_step_count=STATE_MACHINE_STEPS,
        deadline=None,
    )
