"""Source-value-free validation diagnostics for public configuration contracts."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from pydantic import ValidationError

from atready.errors import ConfigurationError

RESOURCE_LOCATION_FIELDS = frozenset(
    {
        "access",
        "allowed_data_classes",
        "approval_required",
        "autonomy",
        "avoid_for",
        "basis",
        "best_for",
        "billing",
        "capacity",
        "capabilities",
        "categories",
        "confidence",
        "context_switch_cost",
        "current_session",
        "economics",
        "expires_on",
        "handoff",
        "id",
        "instructions",
        "integration_friction",
        "interaction",
        "last_verified",
        "limit",
        "marginal_cost",
        "method",
        "name",
        "policy",
        "private_notes",
        "project_limit",
        "privacy",
        "provenance",
        "quality",
        "quota",
        "ratings",
        "reliability",
        "remaining",
        "resets_on",
        "requires_network",
        "resource",
        "schema_version",
        "speed",
        "status",
        "unit",
    }
)

INVENTORY_LOCATION_FIELDS = RESOURCE_LOCATION_FIELDS | frozenset(
    {
        "allow_purchase_suggestions",
        "autonomy",
        "capability_fit",
        "confidence",
        "cost_efficiency",
        "inventory_kind",
        "low_context_switching",
        "low_integration_friction",
        "maximum_supporting_resources",
        "preferences",
        "resources",
        "revision_privacy_nonce",
        "stale_after_days",
        "weights",
    }
)

PROJECT_LOCATION_FIELDS = frozenset(
    {
        "acceptance_criteria",
        "allow_unverified",
        "allowed_interactions",
        "allowed_scope",
        "allowed",
        "as_of",
        "capability_gaps",
        "constraints",
        "data_class",
        "deliverable",
        "exclusions",
        "alternate_required",
        "forbidden_resources",
        "goal",
        "id",
        "importance",
        "inputs",
        "max_marginal_cost",
        "minimum",
        "minimum_gain",
        "name",
        "network_allowed",
        "next_owner",
        "objective",
        "required_capabilities",
        "schema_version",
        "stop_conditions",
        "support",
        "verification",
        "workstreams",
    }
)


def safe_validation_location(
    location: tuple[Any, ...],
    *,
    allowed_fields: Collection[str],
    dynamic_mapping_fields: Collection[str] = (),
) -> str:
    """Render schema locations without echoing user-defined keys or list positions."""

    parts: list[str] = []
    redact_next = False
    for item in location:
        if isinstance(item, int):
            parts.append("[*]")
            continue
        if redact_next:
            parts.append("<entry>")
            redact_next = False
            continue
        name = str(item)
        parts.append(name if name in allowed_fields else "<field>")
        if name in dynamic_mapping_fields:
            redact_next = True
    rendered = ".".join(parts).replace(".[*]", "[*]")
    return rendered or "$"


def validation_configuration_error(
    exc: ValidationError,
    *,
    subject: str,
    allowed_fields: Collection[str],
    dynamic_mapping_fields: Collection[str] = (),
) -> ConfigurationError:
    """Build one unchained ConfigurationError without Pydantic input values."""

    messages: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        location = safe_validation_location(
            tuple(error["loc"]),
            allowed_fields=allowed_fields,
            dynamic_mapping_fields=dynamic_mapping_fields,
        )
        messages.append(f"{location}: {error['msg']}")
    return ConfigurationError(f"{subject} validation failed:\n- " + "\n- ".join(messages))
