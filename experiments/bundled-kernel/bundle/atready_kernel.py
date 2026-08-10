"""Fail-closed feasibility assessment for a dependency-free bundled kernel.

This is deliberately not a second AtReady implementation.  Its one public
interface verifies a sanitized receipt from the canonical runtime and reports
which production guarantees are still absent from this extracted-style bundle.
"""

from __future__ import annotations

import re
from typing import Any

_JOURNEY_STEPS = ("init", "preview-add", "apply-add", "route")
_VERSION_PATTERN = re.compile(r"^atready (0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_MAX_VERSION_LENGTH = 64
_RECEIPT_FIELDS = {
    "schema_version",
    "canonical_runtime",
    "synthetic_only",
    "ephemeral_temporary_directory_only",
    "journey",
    "normal_output_exposed_revision_nonce",
}
_STEP_FIELDS = {
    "init": {"step", "proved", "resources"},
    "preview-add": {
        "step",
        "proved",
        "applied",
        "exact_revision_present",
        "exact_plan_token_present",
    },
    "apply-add": {
        "step",
        "proved",
        "applied",
        "preview_revision_honored",
        "resulting_revision_changed",
    },
    "route": {"step", "proved", "selected_resource_id", "handoffs_executed"},
}
_REMAINING_GATES = (
    {
        "id": "inventory-format-parity",
        "reason": (
            "The bundle has no production-equivalent YAML/JSON loader, strict model "
            "validation, or canonical serializer."
        ),
    },
    {
        "id": "write-safety-parity",
        "reason": (
            "The bundle has no production-equivalent nonce generation, identity checks, "
            "locking, exact-byte backup, plan binding, or atomic replacement engine."
        ),
    },
    {
        "id": "routing-parity",
        "reason": (
            "The bundle has no production scoring, policy filtering, gap handling, or inert "
            "handoff renderer."
        ),
    },
    {
        "id": "single-source-maintenance",
        "reason": (
            "No build step currently derives a dependency-free kernel from the canonical "
            "implementation, so porting behavior here would create a drifting mini-router."
        ),
    },
)


class ContractError(ValueError):
    """Raised when canonical evidence does not prove the expected journey."""


def assess(canonical_receipt: object, runtime: dict[str, Any]) -> dict[str, Any]:
    """Assess a sanitized canonical receipt through one deep, read-only interface.

    The caller supplies the current runtime facts because the adapter owns process
    inspection.  This module owns receipt validation, comparison, and the stop/go
    decision.  It never accepts an inventory path and has no mutation interface.
    """

    receipt = _object(canonical_receipt, "receipt", _RECEIPT_FIELDS)
    if type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1:
        raise ContractError("canonical receipt schema_version must be 1")

    canonical = _object(receipt.get("canonical_runtime"), "canonical_runtime", {"version"})
    version = canonical.get("version")
    if (
        not isinstance(version, str)
        or len(version) > _MAX_VERSION_LENGTH
        or _VERSION_PATTERN.fullmatch(version) is None
    ):
        raise ContractError("canonical runtime version is missing or malformed")

    journey = receipt.get("journey")
    if not isinstance(journey, list) or len(journey) != len(_JOURNEY_STEPS):
        raise ContractError("canonical receipt must contain the complete four-step journey")

    observed_steps: list[str] = []
    for expected, raw_step in zip(_JOURNEY_STEPS, journey, strict=True):
        step = _object(raw_step, f"journey.{expected}", _STEP_FIELDS[expected])
        if step.get("step") != expected or step.get("proved") is not True:
            raise ContractError(f"canonical receipt does not prove {expected!r}")
        observed_steps.append(expected)

    if receipt.get("synthetic_only") is not True:
        raise ContractError("canonical receipt must be synthetic-only")
    if receipt.get("ephemeral_temporary_directory_only") is not True:
        raise ContractError("canonical receipt must be ephemeral-only")
    if receipt.get("normal_output_exposed_revision_nonce") is not False:
        raise ContractError("canonical receipt must prove the revision nonce stayed private")

    isolated = runtime.get("isolated") is True
    no_site = runtime.get("no_site") is True
    site_packages_present = runtime.get("site_packages_present") is True
    local_module = runtime.get("local_module")
    if not isolated or not no_site or site_packages_present:
        raise ContractError("probe must run under python -I -S without site-packages")
    normalized_local_module = (
        local_module.replace("\\", "/") if isinstance(local_module, str) else None
    )
    if normalized_local_module is None or not normalized_local_module.endswith(
        "/bundle/atready_kernel.py"
    ):
        raise ContractError("kernel was not loaded from the extracted-style local bundle")

    return {
        "schema_version": 1,
        "probe_kind": "bundled-kernel-feasibility",
        "canonical_evidence": {
            "version": version,
            "proved_journey_steps": observed_steps,
            "synthetic_only": True,
            "ephemeral_temporary_directory_only": True,
            "normal_output_exposed_revision_nonce": receipt["normal_output_exposed_revision_nonce"],
        },
        "isolated_runtime": {
            "python_isolated": True,
            "site_initialization_disabled": True,
            "site_packages_present": False,
            "kernel_origin": local_module,
            "third_party_yaml_available": runtime.get("yaml_available") is True,
            "third_party_pydantic_available": runtime.get("pydantic_available") is True,
        },
        "candidate_interface": {
            "operations": ["assess-sanitized-canonical-receipt"],
            "inventory_paths_accepted": False,
            "mutation_operations": [],
            "routing_operations": [],
        },
        "comparison": {
            "canonical_journey_steps": list(_JOURNEY_STEPS),
            "candidate_journey_steps": [],
            "uncovered_journey_steps": list(_JOURNEY_STEPS),
            "full_behavioral_parity": False,
            "remaining_gates": list(_REMAINING_GATES),
        },
        "decision": {
            "status": "stop",
            "candidate_is_release_runtime": False,
            "reason": (
                "The isolated bundle can verify canonical evidence, but it cannot initialize, "
                "mutate, or route with production-equivalent guarantees. Do not ship a forked "
                "mini-router."
            ),
        },
    }


def _object(value: object, label: str, allowed_fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContractError(f"{label} must be an object with string keys")
    if set(value) != allowed_fields:
        raise ContractError(f"{label} has an unexpected field set")
    return value
