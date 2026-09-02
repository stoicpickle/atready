"""Provider-neutral, refreshable resource-state evidence contracts.

These contracts describe observations about resources already declared in an
inventory.  They deliberately contain no inventory identity details, provider
configuration, credentials, or discovery behavior.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from atready.diagnostics import validation_configuration_error
from atready.errors import ConfigurationError
from atready.models import (
    Capacity,
    CapacityNumber,
    ConfidenceBasis,
    Inventory,
    QuotaStatus,
    Resource,
    SchemaVersion,
    SessionAvailability,
    Slug,
    StrictModel,
    _trusted_capacity_validation_context,
)
from atready.yamlio import load_yaml, loads_yaml


def _parse_datetime(value: object) -> object:
    """Parse only native datetimes or bounded ISO 8601 strings."""

    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not 1 <= len(value) <= 40 or not value.isascii():
        raise ValueError("timestamp must be an ISO 8601 string or native datetime")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("timestamp must be valid ISO 8601") from exc


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


AwareDateTime = Annotated[
    datetime,
    BeforeValidator(_parse_datetime),
    AfterValidator(_require_aware_datetime),
]


class ResourceStateSourceKind(StrEnum):
    """The bounded local origin of a state observation, not a provider identity."""

    MANUAL = "manual"
    LOCAL_CACHE = "local-cache"
    ADAPTER = "adapter"


class ResourceStateMode(StrEnum):
    """How fresh or derived the reported observation is."""

    LIVE = "live"
    CACHED = "cached"
    ESTIMATED = "estimated"
    MANUAL = "manual"


class ResourceCapacityState(StrictModel):
    """One exact, unit-scoped dynamic capacity observation."""

    unit: Slug
    remaining: CapacityNumber
    limit: CapacityNumber | None = None
    project_limit: CapacityNumber | None = None
    resets_at: AwareDateTime | None = None
    expires_at: AwareDateTime | None = None

    @field_validator("remaining", "limit", "project_limit")
    @classmethod
    def canonicalize_numeric_zero(cls, value: int | float | None) -> int | float | None:
        if value == 0:
            return 0
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    @model_validator(mode="after")
    def validate_exact_capacity(self) -> ResourceCapacityState:
        if self.limit is not None and self.limit == 0:
            raise ValueError("capacity limit must be greater than zero")
        if self.limit is not None and self.remaining > self.limit:
            raise ValueError("capacity remaining cannot exceed limit")
        if self.project_limit is not None and self.project_limit > self.remaining:
            raise ValueError("capacity project_limit cannot exceed remaining")
        return self


class ResourceStateSnapshot(StrictModel):
    """A bounded observation of dynamic state for one declared resource."""

    schema_version: SchemaVersion = 1
    resource_id: Slug
    observed_at: AwareDateTime
    source: Slug
    source_kind: ResourceStateSourceKind
    mode: ResourceStateMode
    confidence: ConfidenceBasis
    session: SessionAvailability | None = None
    quota: QuotaStatus | None = None
    capacity: ResourceCapacityState | None = None
    valid_until: AwareDateTime | None = None

    @model_validator(mode="after")
    def validate_state_evidence(self) -> ResourceStateSnapshot:
        if (
            self.source_kind is ResourceStateSourceKind.MANUAL
            and self.mode is not ResourceStateMode.MANUAL
        ):
            raise ValueError("manual source requires manual mode")
        if (
            self.mode is ResourceStateMode.MANUAL
            and self.source_kind is not ResourceStateSourceKind.MANUAL
        ):
            raise ValueError("manual mode requires manual source")
        if (
            self.source_kind is ResourceStateSourceKind.LOCAL_CACHE
            and self.mode is not ResourceStateMode.CACHED
        ):
            raise ValueError("local-cache source requires cached mode")
        if self.valid_until is not None and self.valid_until < self.observed_at:
            raise ValueError("valid_until cannot be earlier than observed_at")
        if (
            self.mode in {ResourceStateMode.LIVE, ResourceStateMode.CACHED}
            and self.valid_until is None
        ):
            raise ValueError("live or cached state requires valid_until")
        if self.capacity is not None:
            if self.confidence is ConfidenceBasis.UNKNOWN:
                raise ValueError("numeric capacity requires a non-unknown confidence basis")
            if self.capacity.resets_at is not None and self.capacity.resets_at < self.observed_at:
                raise ValueError("capacity resets_at cannot be earlier than observed_at")
            if self.capacity.expires_at is not None and self.capacity.expires_at < self.observed_at:
                raise ValueError("capacity expires_at cannot be earlier than observed_at")
            if self.capacity.remaining == 0 and self.quota is not QuotaStatus.EXHAUSTED:
                raise ValueError("zero remaining capacity requires quota exhausted")
            if self.capacity.remaining > 0 and self.quota is QuotaStatus.EXHAUSTED:
                raise ValueError("quota exhausted cannot have positive remaining capacity")
        if self.session is None and self.quota is None and self.capacity is None:
            raise ValueError("state snapshot requires session, quota, or capacity evidence")
        return self

    def to_evidence(self) -> dict[str, object]:
        """Return a JSON-safe, complete record suitable for local evidence output."""

        return self.model_dump(mode="json", exclude_none=True)


class ResourceStateCollection(StrictModel):
    """A versioned, bounded set of current state observations."""

    schema_version: SchemaVersion = 1
    snapshots: list[ResourceStateSnapshot] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_unique_resource_ids(self) -> ResourceStateCollection:
        resource_ids = [snapshot.resource_id for snapshot in self.snapshots]
        duplicates = sorted(
            {resource_id for resource_id in resource_ids if resource_ids.count(resource_id) > 1}
        )
        if duplicates:
            raise ValueError("resource state snapshot resource_ids must be unique")
        return self

    def to_evidence(self) -> dict[str, object]:
        """Return JSON-safe versioned evidence without inventing inventory state."""

        return self.model_dump(mode="json", exclude_none=True)

    def fingerprint(self) -> str:
        evidence = self.to_evidence()
        evidence["snapshots"] = [
            snapshot.to_evidence()
            for snapshot in sorted(self.snapshots, key=lambda item: item.resource_id)
        ]
        canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_STATE_LOCATION_FIELDS = frozenset(
    {
        "capacity",
        "confidence",
        "economics",
        "expires_at",
        "limit",
        "mode",
        "observed_at",
        "project_limit",
        "quota",
        "remaining",
        "resets_at",
        "resource_id",
        "schema_version",
        "session",
        "snapshots",
        "source",
        "source_kind",
        "unit",
        "valid_until",
    }
)


def resource_state_from_mapping(value: Any) -> ResourceStateCollection:
    """Validate one adapter-neutral resource-state collection."""

    if not isinstance(value, dict):
        raise ConfigurationError("resource state root must be a mapping")
    try:
        return ResourceStateCollection.model_validate(value)
    except ValidationError as exc:
        raise validation_configuration_error(
            exc,
            subject="resource state",
            allowed_fields=_STATE_LOCATION_FIELDS,
        ) from None


def resource_state_from_path(path: Path) -> ResourceStateCollection:
    """Read one explicitly named, bounded, identity-checked state file."""

    return resource_state_from_mapping(load_yaml(path.expanduser()))


def resource_state_from_text(text: str) -> ResourceStateCollection:
    return resource_state_from_mapping(loads_yaml(text))


@dataclass(frozen=True)
class ResourceStateApplication:
    """Effective in-memory inventory plus source-bound evidence for one route."""

    inventory: Inventory = field(repr=False)
    evaluated_at: datetime
    fingerprint: str
    resource_ids: tuple[str, ...]
    sources: tuple[str, ...]
    capacity_expired_resource_ids: tuple[str, ...]
    capacity_reset_resource_ids: tuple[str, ...]
    warnings: tuple[str, ...]


def _require_evaluated_at(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ConfigurationError("resource state evaluated_at must be an aware datetime")
    if value.tzinfo is None:
        raise ConfigurationError("resource state evaluated_at must be timezone-aware")
    offset = value.utcoffset()
    if offset is None:
        raise ConfigurationError("resource state evaluated_at must be timezone-aware")
    return value.astimezone(timezone(offset))


def apply_resource_state(
    inventory: Inventory,
    state: ResourceStateCollection,
    *,
    as_of: date,
    evaluated_at: datetime,
) -> ResourceStateApplication:
    """Overlay validated dynamic facts in memory for one route; never mutate inputs."""

    evaluated_at = _require_evaluated_at(evaluated_at)
    evaluation_timezone = evaluated_at.tzinfo
    assert evaluation_timezone is not None
    evaluation_date = evaluated_at.date()
    resources = {resource.id: resource for resource in inventory.resources}
    unknown = sorted({snapshot.resource_id for snapshot in state.snapshots} - resources.keys())
    if unknown:
        raise ConfigurationError(
            "resource state references resource IDs absent from the selected inventory: "
            + ", ".join(unknown)
        )

    replacements: dict[str, Resource] = {}
    capacity_expired_resource_ids: set[str] = set()
    capacity_reset_resource_ids: set[str] = set()
    validation_context = _trusted_capacity_validation_context(evaluation_date)
    for snapshot in state.snapshots:
        if snapshot.observed_at > evaluated_at:
            raise ConfigurationError("resource state observation is later than evaluated_at")
        if snapshot.valid_until is not None and evaluated_at > snapshot.valid_until:
            raise ConfigurationError(
                "resource state is no longer valid at evaluated_at; refresh it or route without "
                "the state file"
            )
        observed_on = snapshot.observed_at.astimezone(evaluation_timezone).date()
        if observed_on > as_of:
            raise ConfigurationError(
                f"resource state for {snapshot.resource_id!r} was observed after project as_of"
            )
        if (
            snapshot.valid_until is not None
            and snapshot.valid_until.astimezone(evaluation_timezone).date() < as_of
        ):
            raise ConfigurationError(
                f"resource state for {snapshot.resource_id!r} has expired; refresh it or route "
                "without the state file"
            )
        if snapshot.mode is ResourceStateMode.ESTIMATED:
            raise ConfigurationError(
                f"estimated state for {snapshot.resource_id!r} cannot change routing; provide "
                "manual, live, or cached evidence"
            )
        if snapshot.confidence is ConfidenceBasis.UNKNOWN:
            raise ConfigurationError(
                f"resource state for {snapshot.resource_id!r} has unknown confidence"
            )
        if snapshot.mode is ResourceStateMode.MANUAL:
            age = (evaluation_date - observed_on).days
            if age > inventory.preferences.stale_after_days:
                raise ConfigurationError(
                    f"manual resource state for {snapshot.resource_id!r} is stale ({age} days)"
                )

        resource = resources[snapshot.resource_id]
        resource_data = resource.model_dump(mode="python")
        access_data = resource.access.model_dump(mode="python")
        economics_data = resource.economics.model_dump(mode="python")
        if snapshot.session is not None:
            access_data["current_session"] = snapshot.session
        if snapshot.quota is not None:
            economics_data["quota"] = snapshot.quota
        try:
            if snapshot.capacity is not None:
                capacity = snapshot.capacity
                economics_data["capacity"] = Capacity.model_validate(
                    {
                        "unit": capacity.unit,
                        "remaining": capacity.remaining,
                        "limit": capacity.limit,
                        "project_limit": capacity.project_limit,
                        "resets_on": (
                            capacity.resets_at.astimezone(evaluation_timezone).date()
                            if capacity.resets_at
                            else None
                        ),
                        "expires_on": (
                            capacity.expires_at.astimezone(evaluation_timezone).date()
                            if capacity.expires_at
                            else None
                        ),
                        "basis": snapshot.confidence,
                        "last_verified": observed_on,
                    },
                    context=validation_context,
                )
                if capacity.expires_at is not None and capacity.expires_at <= evaluated_at:
                    capacity_expired_resource_ids.add(resource.id)
                if capacity.resets_at is not None and capacity.resets_at <= evaluated_at:
                    capacity_reset_resource_ids.add(resource.id)
            resource_data["access"] = access_data
            resource_data["economics"] = economics_data
            replacements[resource.id] = Resource.model_validate(
                resource_data, context=validation_context
            )
        except ValidationError as exc:
            raise validation_configuration_error(
                exc,
                subject="resource state overlay",
                allowed_fields=_STATE_LOCATION_FIELDS,
            ) from None
    candidate = inventory.model_copy(
        update={
            "resources": [
                replacements.get(resource.id, resource) for resource in inventory.resources
            ]
        }
    )
    try:
        effective = Inventory.model_validate(
            candidate.model_dump(mode="python"), context=validation_context
        )
    except ValidationError as exc:
        raise validation_configuration_error(
            exc,
            subject="resource state overlay",
            allowed_fields=_STATE_LOCATION_FIELDS,
        ) from None
    sources = tuple(sorted({snapshot.source for snapshot in state.snapshots}))
    source_summary = ", ".join(sources[:3])
    if len(sources) > 3:
        source_summary += f", +{len(sources) - 3} more"
    warning = (
        f"[resource-state] temporary state applied to {len(replacements)} resource(s) from "
        f"{source_summary}; source labels and timestamps are evidence, not provider verification"
    )
    return ResourceStateApplication(
        inventory=effective,
        evaluated_at=evaluated_at,
        fingerprint="sha256:" + state.fingerprint(),
        resource_ids=tuple(sorted(replacements)),
        sources=sources,
        capacity_expired_resource_ids=tuple(sorted(capacity_expired_resource_ids)),
        capacity_reset_resource_ids=tuple(sorted(capacity_reset_resource_ids)),
        warnings=(warning,),
    )
