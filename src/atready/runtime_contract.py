"""Stable compatibility contract between the plugin and local runtime."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from atready import __version__

RUNTIME_CONTRACT_VERSION = 1
SUPPORTED_RUNTIME_FEATURE_IDS = (
    "inventory.mutate-preview-apply.v1",
    "inventory.read.v1",
    "resource.discovery-consent.v1",
    "resource.profiles.v1",
    "routing.plan-only.v1",
    "routing.presentation-bundle.v1",
    "schema.declarations.v1",
)


def runtime_contract_payload() -> dict[str, Any]:
    """Return the value-free, side-effect-free runtime compatibility report."""
    return {
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "features": list(SUPPORTED_RUNTIME_FEATURE_IDS),
        "inventory_read": False,
        "network_accessed": False,
        "product": "project-atready",
        "runtime_version": __version__,
        "writes_performed": False,
    }


def doctor_payload(
    *,
    plugin_version: str | None,
    plugin_contract_version: int | None,
    required_features: Sequence[str],
) -> dict[str, Any]:
    """Assess declared plugin requirements without inspecting local user state."""
    missing_features = sorted(set(required_features).difference(SUPPORTED_RUNTIME_FEATURE_IDS))
    compatible = (
        plugin_contract_version is None or plugin_contract_version == RUNTIME_CONTRACT_VERSION
    ) and not missing_features
    return {
        "compatible": compatible,
        "inventory_read": False,
        "missing_features": missing_features,
        "network_accessed": False,
        "plugin_contract_version": plugin_contract_version,
        "plugin_version": plugin_version,
        "product": "project-atready",
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "runtime_features": list(SUPPORTED_RUNTIME_FEATURE_IDS),
        "runtime_version": __version__,
        "status": "ready" if compatible else "incompatible",
        "writes_performed": False,
    }
