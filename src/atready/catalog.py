"""Deep inventory module: load, validate, warn, fingerprint, and redact."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from atready.diagnostics import INVENTORY_LOCATION_FIELDS, validation_configuration_error
from atready.errors import ConfigurationError
from atready.models import (
    AccessStatus,
    ConfidenceBasis,
    Inventory,
    QuotaStatus,
    Resource,
    SessionAvailability,
)
from atready.yamlio import loads_yaml


def _routing_resource(resource: Resource) -> dict[str, Any]:
    """Return the resource fields included in the routing fingerprint."""

    value = resource.model_dump(
        mode="json",
        exclude={"private_notes", "best_for", "avoid_for"},
    )
    value["economics"].pop("billing")
    return value


@dataclass(frozen=True)
class InventoryCatalog:
    inventory: Inventory = field(repr=False)
    warnings: tuple[str, ...]

    @classmethod
    def from_path(cls, path: Path, *, today: date | None = None) -> InventoryCatalog:
        # Import lazily because the secure inventory reader depends on this catalog for parsing.
        from atready.inventory_edit import read_inventory_file

        current = read_inventory_file(path)
        return cls.from_mapping(current.inventory.model_dump(mode="json"), today=today)

    @classmethod
    def from_text(cls, text: str, *, today: date | None = None) -> InventoryCatalog:
        return cls.from_mapping(loads_yaml(text), today=today)

    @classmethod
    def from_mapping(cls, value: Any, *, today: date | None = None) -> InventoryCatalog:
        if not isinstance(value, dict):
            raise ConfigurationError("inventory root must be a mapping")
        if "inventory_kind" not in value:
            raise ConfigurationError(
                "inventory validation failed:\n- inventory_kind: field is required; classify "
                "user-declared state as 'personal' or synthetic examples as 'demo'"
            )
        failure: ConfigurationError | None = None
        try:
            inventory = Inventory.model_validate(value)
        except ValidationError as exc:
            failure = validation_configuration_error(
                exc,
                subject="inventory",
                allowed_fields=INVENTORY_LOCATION_FIELDS,
                dynamic_mapping_fields={"capabilities"},
            )
            inventory = None
        if failure is not None:
            raise failure
        assert inventory is not None
        return cls(inventory=inventory, warnings=tuple(_inventory_warnings(inventory, today=today)))

    def snapshot(self, *, today: date | None = None) -> dict[str, Any]:
        """Return only fields needed for model-side routing."""

        current_date = today or date.today()
        resources: list[dict[str, Any]] = []
        for resource in sorted(self.inventory.resources, key=lambda item: item.id):
            last_verified = resource.provenance.last_verified
            if last_verified is None:
                verification_status = "unknown"
            elif (current_date - last_verified).days > self.inventory.preferences.stale_after_days:
                verification_status = "stale"
            else:
                verification_status = "fresh"
            resources.append(
                {
                    "id": resource.id,
                    "name": resource.name,
                    "categories": sorted(resource.categories),
                    "capabilities": dict(sorted(resource.capabilities.items())),
                    "access": resource.access.model_dump(mode="json"),
                    "economics": {
                        "marginal_cost": resource.economics.marginal_cost,
                        "quota": resource.economics.quota.value,
                        "capacity": (
                            resource.economics.capacity.model_dump(mode="json")
                            if resource.economics.capacity is not None
                            else None
                        ),
                    },
                    "ratings": resource.ratings.model_dump(mode="json"),
                    "policy": resource.policy.model_dump(mode="json"),
                    "provenance": {
                        "basis": resource.provenance.basis.value,
                        "last_verified": last_verified.isoformat() if last_verified else None,
                        "verification_status": verification_status,
                    },
                    "handoff": resource.handoff.model_dump(mode="json"),
                }
            )
        snapshot: dict[str, Any] = {
            "schema_version": self.inventory.schema_version,
            "inventory_kind": self.inventory.inventory_kind.value,
            "inventory_fingerprint": "sha256:" + self.fingerprint(),
            "preferences": self.inventory.preferences.model_dump(mode="json"),
            "resources": resources,
            "warnings": list(_inventory_warnings(self.inventory, today=current_date)),
        }
        return snapshot

    def fingerprint(self) -> str:
        """Fingerprint routing-visible fields without exposing private notes."""

        payload = {
            "schema_version": self.inventory.schema_version,
            "inventory_kind": self.inventory.inventory_kind.value,
            "preferences": self.inventory.preferences.model_dump(mode="json"),
            "resources": [
                _routing_resource(resource)
                for resource in sorted(self.inventory.resources, key=lambda item: item.id)
            ],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _inventory_warnings(inventory: Inventory, *, today: date | None = None) -> list[str]:
    current_date = today or date.today()
    warnings: list[str] = []
    for resource in sorted(inventory.resources, key=lambda item: item.id):
        prefix = f"resource {resource.id!r}"
        if resource.access.status is AccessStatus.UNKNOWN:
            warnings.append(f"{prefix} has unknown declared access")
        if resource.access.current_session is SessionAvailability.UNKNOWN:
            warnings.append(f"{prefix} has unknown current-session availability")
        if resource.economics.quota is QuotaStatus.UNKNOWN:
            warnings.append(f"{prefix} has unknown quota")
        capacity = resource.economics.capacity
        if capacity is not None:
            capacity_age = (current_date - capacity.last_verified).days
            if capacity_age > inventory.preferences.stale_after_days:
                warnings.append(
                    f"{prefix} exact capacity is stale ({capacity_age} days; limit is "
                    f"{inventory.preferences.stale_after_days})"
                )
            if capacity.resets_on is not None and current_date > capacity.resets_on:
                warnings.append(
                    f"{prefix} exact capacity reset date has passed; re-check the balance"
                )
        if resource.provenance.basis is ConfidenceBasis.UNKNOWN:
            warnings.append(f"{prefix} has unknown confidence basis")
        if resource.provenance.last_verified is None:
            warnings.append(f"{prefix} has never been verified")
        else:
            age = (current_date - resource.provenance.last_verified).days
            if age > inventory.preferences.stale_after_days:
                warnings.append(
                    f"{prefix} verification is stale ({age} days; limit is "
                    f"{inventory.preferences.stale_after_days})"
                )
    return warnings
