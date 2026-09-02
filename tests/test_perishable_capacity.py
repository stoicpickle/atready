from __future__ import annotations

from datetime import date

from atready.catalog import InventoryCatalog
from atready.models import (
    AccessStatus,
    Capacity,
    CapacityDemand,
    DataClass,
    Inventory,
    QuotaStatus,
    SessionAvailability,
)
from atready.project import project_from_text
from atready.render import render_markdown
from atready.routing import route
from atready.templates import demo_inventory, starter_project

AS_OF = date(2026, 9, 1)


def _project(*, demand: CapacityDemand | None = None):
    project = project_from_text(starter_project(AS_OF))
    workstream = project.workstreams[0].model_copy(update={"capacity_demand": demand})
    return project.model_copy(update={"workstreams": [workstream]})


def _inventory() -> Inventory:
    base = InventoryCatalog.from_text(demo_inventory(AS_OF), today=AS_OF).inventory.resources[0]
    common = {
        "access": base.access.model_copy(
            update={
                "status": AccessStatus.ACTIVE,
                "current_session": SessionAvailability.AVAILABLE,
            }
        ),
        "economics": base.economics.model_copy(update={"quota": QuotaStatus.LIMITED}),
        "policy": base.policy.model_copy(update={"allowed_data_classes": [DataClass.INTERNAL]}),
    }
    later = base.model_copy(
        update={
            **common,
            "id": "alpha-later",
            "name": "Alpha Later",
            "economics": common["economics"].model_copy(
                update={
                    "capacity": Capacity(
                        unit="request",
                        remaining=10,
                        expires_on=date(2026, 9, 20),
                        basis="observed",
                        last_verified=AS_OF,
                    )
                }
            ),
        }
    )
    sooner = later.model_copy(
        update={
            "id": "zeta-sooner",
            "name": "Zeta Sooner",
            "economics": later.economics.model_copy(
                update={
                    "capacity": later.economics.capacity.model_copy(
                        update={"expires_on": date(2026, 9, 5)}
                    )
                }
            ),
        }
    )
    return Inventory(inventory_kind="personal", resources=[later, sooner])


def test_perishable_capacity_is_only_a_late_exact_demand_tie_break() -> None:
    demand = CapacityDemand(unit="request", amount=1)
    plan = route(_inventory(), _project(demand=demand))

    assert plan.assignments[0].primary is not None
    assert plan.assignments[0].primary.resource_id == "zeta-sooner"
    candidates = {item.resource_id: item for item in plan.assignments[0].candidates}
    assert candidates["zeta-sooner"].capacity_pressure_days == 4
    assert candidates["alpha-later"].capacity_pressure_days == 19
    assert "perishable sooner: 4 days versus 19 days" in render_markdown(plan)


def test_reset_only_capacity_uses_the_same_late_tie_break() -> None:
    later, sooner = _inventory().resources
    later_capacity = later.economics.capacity
    sooner_capacity = sooner.economics.capacity
    assert later_capacity is not None
    assert sooner_capacity is not None
    later = later.model_copy(
        update={
            "economics": later.economics.model_copy(
                update={
                    "capacity": later_capacity.model_copy(
                        update={"expires_on": None, "resets_on": date(2026, 9, 20)}
                    )
                }
            )
        }
    )
    sooner = sooner.model_copy(
        update={
            "economics": sooner.economics.model_copy(
                update={
                    "capacity": sooner_capacity.model_copy(
                        update={"expires_on": None, "resets_on": date(2026, 9, 5)}
                    )
                }
            )
        }
    )
    inventory = Inventory(inventory_kind="personal", resources=[later, sooner])

    plan = route(inventory, _project(demand=CapacityDemand(unit="request", amount=1)))

    assert plan.assignments[0].primary is not None
    assert plan.assignments[0].primary.resource_id == "zeta-sooner"
    candidates = {item.resource_id: item for item in plan.assignments[0].candidates}
    assert candidates["zeta-sooner"].capacity_pressure_days == 4
    assert candidates["alpha-later"].capacity_pressure_days == 19


def test_capacity_expiry_never_changes_a_route_without_exact_demand() -> None:
    plan = route(_inventory(), _project())

    assert plan.assignments[0].primary is not None
    assert plan.assignments[0].primary.resource_id == "alpha-later"
    assert all(
        candidate.capacity_pressure_days is None for candidate in plan.assignments[0].candidates
    )


def test_perishable_capacity_never_overrides_a_better_weighted_fit() -> None:
    inventory = _inventory()
    later, sooner = inventory.resources
    stronger_later = later.model_copy(
        update={"ratings": later.ratings.model_copy(update={"quality": 1.0})}
    )
    inventory = inventory.model_copy(update={"resources": [stronger_later, sooner]})

    plan = route(
        inventory,
        _project(demand=CapacityDemand(unit="request", amount=1)),
    )

    assert plan.assignments[0].primary is not None
    assert plan.assignments[0].primary.resource_id == "alpha-later"
