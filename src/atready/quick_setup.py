"""Bounded Quick Setup facts-to-resource orchestration."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import BinaryIO, Literal

from pydantic import ValidationError

from atready.errors import ConfigurationError
from atready.intake import IntakeError, resource_profile
from atready.models import (
    AccessStatus,
    ConfidenceBasis,
    DataClass,
    ResourceName,
    SchemaVersion,
    SessionAvailability,
    StrictBoolean,
    StrictModel,
)
from atready.resource_input import ParsedResourceDeclaration, parse_resource_mapping
from atready.yamlio import load_json_line_stdin

_MAX_QUICK_SETUP_FACTS_BYTES = 4_096
_STRENGTH_SCORES = {
    "basic": 0.40,
    "solid": 0.65,
    "strong": 0.80,
    "exceptional": 0.95,
}


class QuickSetupFacts(StrictModel):
    """The complete, user-approved Quick Setup fact set."""

    schema_version: SchemaVersion
    name: ResourceName
    strength: Literal["basic", "solid", "strong", "exceptional"]
    available_now: StrictBoolean
    private_work: StrictBoolean


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _read_bounded_facts(stream: BinaryIO) -> bytes:
    isatty = getattr(stream, "isatty", None)
    if callable(isatty) and isatty():
        raise ConfigurationError(
            "--facts-stdin requires piped or redirected input; interactive input is refused"
        )
    try:
        raw = stream.readline(_MAX_QUICK_SETUP_FACTS_BYTES + 2)
    except ConfigurationError:
        raise
    except (OSError, ValueError):
        raise ConfigurationError("cannot read quick setup facts") from None
    if not isinstance(raw, bytes):
        raise ConfigurationError("quick setup facts must provide bytes")
    if not raw.endswith(b"\n"):
        if len(raw) > _MAX_QUICK_SETUP_FACTS_BYTES:
            raise ConfigurationError(
                f"quick setup facts exceed {_MAX_QUICK_SETUP_FACTS_BYTES} bytes"
            )
        raise ConfigurationError("quick setup facts must end with one newline")
    payload = raw[:-1]
    if len(payload) > _MAX_QUICK_SETUP_FACTS_BYTES:
        raise ConfigurationError(f"quick setup facts exceed {_MAX_QUICK_SETUP_FACTS_BYTES} bytes")
    return payload


def load_quick_setup_facts_stdin(stream: BinaryIO) -> QuickSetupFacts:
    """Read one exact, duplicate-free JSON facts envelope from non-interactive stdin."""

    raw = _read_bounded_facts(stream)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        return QuickSetupFacts.model_validate(value)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateKeyError,
        ValidationError,
        ValueError,
    ):
        raise ConfigurationError(
            "quick setup facts are invalid; expected only schema_version, name, strength, "
            "available_now, and private_work"
        ) from None


def load_quick_setup_facts_json_line(
    stream: BinaryIO, *, on_ready: Callable[[], None] | None = None
) -> QuickSetupFacts:
    """Read one bounded JSON facts record from an explicitly requested agent PTY."""

    value = load_json_line_stdin(
        stream,
        option="--facts-json-line",
        subject="quick setup facts",
        on_ready=on_ready,
        max_bytes=_MAX_QUICK_SETUP_FACTS_BYTES,
    )
    try:
        return QuickSetupFacts.model_validate(value)
    except ValidationError:
        raise ConfigurationError(
            "quick setup facts are invalid; expected only schema_version, name, strength, "
            "available_now, and private_work"
        ) from None


def resource_from_quick_setup(facts: QuickSetupFacts) -> tuple[ParsedResourceDeclaration, str]:
    """Map approved facts and one offline profile proposal to a conservative resource."""

    try:
        profile = resource_profile(facts.name)
    except IntakeError:
        raise ConfigurationError(
            "quick setup requires one unambiguous bundled profile; use detailed setup "
            "for a custom resource"
        ) from None

    allowed_data = [DataClass.PUBLIC.value]
    if facts.private_work:
        allowed_data.extend((DataClass.INTERNAL.value, DataClass.PRIVATE.value))
    score = _STRENGTH_SCORES[facts.strength]
    mapping = {
        "id": profile.id,
        "name": facts.name,
        "categories": [item.id for item in profile.category_suggestions],
        "capabilities": {item.id: score for item in profile.capability_suggestions},
        "access": {
            "status": AccessStatus.UNKNOWN.value,
            "current_session": (
                SessionAvailability.AVAILABLE.value
                if facts.available_now
                else SessionAvailability.UNAVAILABLE.value
            ),
        },
        "policy": {
            "allowed_data_classes": allowed_data,
            "approval_required": True,
            "requires_network": True,
        },
    }
    return parse_resource_mapping(mapping), profile.id


def quick_setup_mapping_summary(
    facts: QuickSetupFacts,
    *,
    profile_id: str,
) -> dict[str, object]:
    """Describe the bounded mappings without claiming provider verification."""

    return {
        "availability_mapping": (
            "access-unknown-session-available"
            if facts.available_now
            else "access-unknown-session-unavailable"
        ),
        "catalog_profile": profile_id,
        "private_work_mapping": (
            "public-internal-private" if facts.private_work else "public-only"
        ),
        "provider_or_account_inspected": False,
        "provenance_default": ConfidenceBasis.UNKNOWN.value,
        "requires_network_default": True,
        "strength_score": _STRENGTH_SCORES[facts.strength],
    }
