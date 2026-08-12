"""Preview-first, revision-aware inventory onboarding operations."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from atready.catalog import InventoryCatalog
from atready.errors import AtReadyError, ConfigurationError, StorageError
from atready.fsprivacy import (
    darwin_fd_has_extended_acl,
    descriptor_snapshot_unchanged,
    file_identity_is_known,
    path_snapshot_unchanged,
    same_file_identity,
)
from atready.models import Inventory, InventoryKind, Resource, Slug
from atready.paths import ensure_private_directory, validate_no_darwin_extended_acl
from atready.resource_input import parse_resource_mapping, resource_intake_review
from atready.yamlio import MAX_FILE_BYTES, dumps_yaml

_BACKUP_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_BACKUP_FILENAME_PATTERN = re.compile(r"inventory-([0-9a-f]{64})\.yaml")
_MANIFEST_EVENT_FILENAME_PATTERN = re.compile(r"event-([0-9]{12})-([0-9a-f]{64})\.json")
_MANIFEST_TEMP_FILENAME_PATTERN = re.compile(r"\.manifest-([0-9a-f]{32})\.tmp")
_MANIFEST_DIRECTORY_NAME = ".operations-v1"
_MANIFEST_SCHEMA_VERSION = 1
_MAX_BACKUP_DIRECTORY_ENTRIES = 4_096
_MAX_BACKUP_TOTAL_BYTES = 64 * 1_048_576
_MAX_MANIFEST_EVENTS = 4_096
_MAX_MANIFEST_TOTAL_BYTES = 64 * 1_048_576
_MAX_MANIFEST_EVENT_BYTES = 16 * 1_024
_MAX_MANIFEST_DETAILS_DEPTH = 32
_MAX_MANIFEST_DETAILS_VALUES = 1_024
_MANIFEST_CAPACITY_REMEDIATION = (
    "start a new explicitly initialized inventory path and re-onboard the required state; "
    "in-place manifest pruning or rotation is unsupported"
)
_CASE_PHYSICAL = "physical-spelling"
_CASE_SENSITIVE = "case-sensitive"
_CASE_INSENSITIVE = "case-insensitive"
_RESOURCE_ID_ADAPTER = TypeAdapter(Slug)

_CaseEntryObservation = tuple[int, int, int, int] | None


def _revision(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _required_identity(details: os.stat_result, *, subject: str) -> tuple[int, int]:
    """Return a plan-safe identity or fail closed when the platform did not provide one."""

    if not file_identity_is_known(details):
        raise StorageError(f"cannot verify {subject} identity")
    return details.st_dev, details.st_ino


def _format_validation_errors(exc: ValidationError, *, subject: str) -> ConfigurationError:
    messages: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "$"
        messages.append(f"{location}: {error['msg']}")
    return ConfigurationError(f"{subject} validation failed:\n- " + "\n- ".join(messages))


def resource_from_mapping(value: dict[str, Any]) -> Resource:
    """Validate one CLI-declared resource with actionable errors."""

    return parse_resource_mapping(value).resource


def _validated_resource_id(value: str) -> str:
    try:
        validated = _RESOURCE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise ConfigurationError("resource ID must be a valid lowercase slug") from exc
    if validated != value:
        raise ConfigurationError("resource ID must match its exact lowercase slug")
    return validated


@dataclass(frozen=True)
class InventoryFile:
    path: Path
    raw: bytes = field(repr=False)
    revision: str
    inventory: Inventory = field(repr=False)


@dataclass(frozen=True)
class InventoryAddPlan:
    target: Path
    original_revision: str
    candidate_revision: str
    resource: Resource = field(repr=False)
    candidate_yaml: str = field(repr=False)
    resource_count_before: int
    defaulted_fields: tuple[str, ...]
    target_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    revision_protection: str

    @property
    def plan_token(self) -> str:
        payload = "\0".join(
            (
                "add-resource-v1",
                str(self.target),
                self.original_revision,
                self.candidate_revision,
                f"target:{self.target_identity[0]}:{self.target_identity[1]}",
                f"parent:{self.parent_identity[0]}:{self.parent_identity[1]}",
            )
        ).encode("utf-8")
        return _revision(payload)

    def resource_preview(self) -> dict[str, Any]:
        """Return every persisted resource field except private notes."""

        return self.resource.model_dump(mode="json", exclude={"private_notes"})

    def preview(self) -> dict[str, Any]:
        return {
            "applied": False,
            "backup_on_apply": True,
            "canonicalizes_yaml": True,
            "candidate_revision": self.candidate_revision,
            "changed_fields": ["resources"],
            "defaulted_fields": list(self.defaulted_fields),
            "expect_revision": self.original_revision,
            "expect_plan": self.plan_token,
            "intake_review": resource_intake_review(
                self.resource,
                self.defaulted_fields,
            ).as_dict(),
            "operation": "add-resource",
            "private_notes_bound_to_plan": True,
            "private_notes_exposed": False,
            "private_notes_present": self.resource.private_notes is not None,
            "resource": self.resource_preview(),
            "resource_count_after": self.resource_count_before + 1,
            "resource_count_before": self.resource_count_before,
            "resource_id": self.resource.id,
            "revision_protection": self.revision_protection,
            "target": str(self.target),
        }


@dataclass(frozen=True)
class InventoryReplacePlan:
    target: Path
    original_revision: str
    candidate_revision: str
    previous_resource: Resource = field(repr=False)
    resource: Resource = field(repr=False)
    candidate_yaml: str = field(repr=False)
    resource_count: int
    defaulted_fields: tuple[str, ...]
    target_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    revision_protection: str

    @property
    def plan_token(self) -> str:
        payload = "\0".join(
            (
                "replace-resource-v1",
                str(self.target),
                self.resource.id,
                self.original_revision,
                self.candidate_revision,
                f"target:{self.target_identity[0]}:{self.target_identity[1]}",
                f"parent:{self.parent_identity[0]}:{self.parent_identity[1]}",
            )
        ).encode("utf-8")
        return _revision(payload)

    @staticmethod
    def _resource_preview(resource: Resource) -> dict[str, Any]:
        return resource.model_dump(mode="json", exclude={"private_notes"})

    def preview(self) -> dict[str, Any]:
        return {
            "applied": False,
            "backup_on_apply": True,
            "canonicalizes_yaml": True,
            "candidate_revision": self.candidate_revision,
            "changed_fields": ["resources"],
            "defaulted_fields": list(self.defaulted_fields),
            "expect_revision": self.original_revision,
            "expect_plan": self.plan_token,
            "intake_review": resource_intake_review(
                self.resource,
                self.defaulted_fields,
            ).as_dict(),
            "operation": "replace-resource",
            "private_notes_bound_to_plan": True,
            "private_notes_effect": _private_note_effect(
                self.previous_resource.private_notes,
                self.resource.private_notes,
            ),
            "private_notes_exposed": False,
            "resource_after": self._resource_preview(self.resource),
            "resource_before": self._resource_preview(self.previous_resource),
            "resource_count_after": self.resource_count,
            "resource_count_before": self.resource_count,
            "resource_id": self.resource.id,
            "revision_protection": self.revision_protection,
            "target": str(self.target),
        }


@dataclass(frozen=True)
class InventoryRemovePlan:
    target: Path
    original_revision: str
    candidate_revision: str
    resource: Resource = field(repr=False)
    candidate_yaml: str = field(repr=False)
    resource_count_before: int
    target_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    revision_protection: str

    @property
    def plan_token(self) -> str:
        payload = "\0".join(
            (
                "remove-resource-v1",
                str(self.target),
                self.resource.id,
                self.original_revision,
                self.candidate_revision,
                f"target:{self.target_identity[0]}:{self.target_identity[1]}",
                f"parent:{self.parent_identity[0]}:{self.parent_identity[1]}",
            )
        ).encode("utf-8")
        return _revision(payload)

    def preview(self) -> dict[str, Any]:
        return {
            "applied": False,
            "backup_on_apply": True,
            "canonicalizes_yaml": True,
            "candidate_revision": self.candidate_revision,
            "changed_fields": ["resources"],
            "expect_revision": self.original_revision,
            "expect_plan": self.plan_token,
            "operation": "remove-resource",
            "private_notes_exposed": False,
            "private_notes_present": self.resource.private_notes is not None,
            "resource": self.resource.model_dump(mode="json", exclude={"private_notes"}),
            "resource_count_after": self.resource_count_before - 1,
            "resource_count_before": self.resource_count_before,
            "resource_id": self.resource.id,
            "revision_protection": self.revision_protection,
            "safety_backup_on_apply": True,
            "target": str(self.target),
        }


@dataclass(frozen=True)
class InventoryAnnotationPlan:
    """Preview binding for one root private-note set or clear operation."""

    target: Path
    original_revision: str
    candidate_revision: str
    private_notes: str | None = field(repr=False)
    candidate_yaml: str = field(repr=False)
    private_notes_effect: str
    target_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    revision_protection: str

    @property
    def plan_token(self) -> str:
        payload = "\0".join(
            (
                "annotate-inventory-v1",
                str(self.target),
                self.original_revision,
                self.candidate_revision,
                f"target:{self.target_identity[0]}:{self.target_identity[1]}",
                f"parent:{self.parent_identity[0]}:{self.parent_identity[1]}",
            )
        ).encode("utf-8")
        return _revision(payload)

    def preview(self) -> dict[str, Any]:
        return {
            "applied": False,
            "backup_on_apply": True,
            "canonicalizes_yaml": True,
            "candidate_revision": self.candidate_revision,
            "changed_fields": ["private_notes"],
            "expect_revision": self.original_revision,
            "expect_plan": self.plan_token,
            "operation": "annotate-inventory",
            "private_notes_bound_to_plan": True,
            "private_notes_effect": self.private_notes_effect,
            "private_notes_exposed": False,
            "revision_protection": self.revision_protection,
            "target": str(self.target),
        }


@dataclass(frozen=True)
class InventoryUpdateReceipt:
    target: Path
    previous_revision: str
    candidate_revision: str
    revision: str | None
    backup_id: str
    backup_path: Path
    directory_synced: bool
    replacement_verified: bool
    warnings: tuple[str, ...] = ()
    operation: str = "replace-inventory"

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied": True,
            "backup_id": self.backup_id,
            "backup_path": str(self.backup_path),
            "candidate_revision": self.candidate_revision,
            "directory_synced": self.directory_synced,
            "operation": self.operation,
            "previous_revision": self.previous_revision,
            "replacement_verified": self.replacement_verified,
            "revision": self.revision,
            "target": str(self.target),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class InventoryBackupSummary:
    """Sanitized metadata for one validated, target-scoped backup."""

    backup_id: str
    path: Path
    size_bytes: int = field(repr=False)
    schema_version: int
    inventory_kind: InventoryKind
    resource_count: int
    revision_protection: str
    matches_active: bool
    filesystem_modified_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "filesystem_modified_at": self.filesystem_modified_at,
            "filesystem_modified_at_is_history": False,
            "inventory_kind": self.inventory_kind.value,
            "matches_active": self.matches_active,
            "path": str(self.path),
            "resource_count": self.resource_count,
            "revision_protection": self.revision_protection,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class InventoryBackupListing:
    """Bounded backup-store listing that never exposes inventory contents."""

    target: Path
    active_state: str
    active_revision: str | None
    active_revision_protection: str | None
    namespace: str
    backups: tuple[InventoryBackupSummary, ...]
    legacy_unscoped_count: int
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "active_state": self.active_state,
            "active_revision": self.active_revision,
            "active_revision_protection": self.active_revision_protection,
            "backup_count": len(self.backups),
            "backups": [backup.as_dict() for backup in self.backups],
            "legacy_unscoped_count": self.legacy_unscoped_count,
            "namespace": self.namespace,
            "target": str(self.target),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class InventoryBackupInspection:
    """Explicit, sanitized comparison of one backup with the active inventory."""

    target: Path
    active_state: str
    active_revision: str | None
    active_revision_protection: str | None
    backup: InventoryBackupSummary
    active_snapshot: dict[str, Any] | None
    backup_snapshot: dict[str, Any]
    comparison: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "active_state": self.active_state,
            "active_revision": self.active_revision,
            "active_revision_protection": self.active_revision_protection,
            "active_snapshot": self.active_snapshot,
            "backup": self.backup.as_dict(),
            "backup_snapshot": self.backup_snapshot,
            "comparison": self.comparison,
            "private_notes_exposed": False,
            "target": str(self.target),
        }


@dataclass(frozen=True)
class InventoryBackupManifestEvent:
    """One validated, immutable event from a target-scoped operation manifest."""

    sequence: int
    event_hash: str
    previous_event_hash: str | None
    event_type: str
    phase: str
    operation_id: str | None
    operation: str | None
    recorded_at: str
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "details": self.details,
            "event_hash": self.event_hash,
            "event_type": self.event_type,
            "operation": self.operation,
            "operation_id": self.operation_id,
            "phase": self.phase,
            "previous_event_hash": self.previous_event_hash,
            "recorded_at": self.recorded_at,
            "recorded_at_is_history": False,
            "sequence": self.sequence,
        }


@dataclass(frozen=True)
class InventoryBackupManifest:
    """Validated ordering evidence for backup-affecting apply operations."""

    target: Path
    namespace: str
    initialized: bool
    events: tuple[InventoryBackupManifestEvent, ...]
    unresolved_operation_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "authoritative_order": "sequence",
            "event_count": len(self.events),
            "events": [event.as_dict() for event in self.events],
            "history_before_manifest": "unknown" if self.initialized else "unavailable",
            "initialized": self.initialized,
            "namespace": self.namespace,
            "target": str(self.target),
            "tamper_evidence": "local-hash-chain-not-a-signature",
            "unresolved_operation_ids": list(self.unresolved_operation_ids),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class InventoryRecoveryPlan:
    """Preview binding for recovery when no valid active inventory exists."""

    target: Path
    active_state: str
    active_fingerprint: str = field(repr=False)
    active_raw: bytes | None = field(repr=False)
    candidate_revision: str
    candidate_revision_protection: str
    source_backup_id: str
    source_backup_path: Path
    candidate_raw: bytes = field(repr=False)
    parent_identity: tuple[int, int]
    target_identity: tuple[int, int] | None
    backup_directory_identity: tuple[int, int]
    source_backup_identity: tuple[int, int]
    candidate_snapshot: dict[str, Any] = field(repr=False)

    @property
    def state_token(self) -> str:
        return self.active_state

    @property
    def plan_token(self) -> str:
        target_identity = (
            "target:missing"
            if self.target_identity is None
            else f"target:{self.target_identity[0]}:{self.target_identity[1]}"
        )
        payload = "\0".join(
            (
                "recover-inventory-v1",
                str(self.target),
                self.active_state,
                self.active_fingerprint,
                self.candidate_revision,
                self.source_backup_id,
                str(self.source_backup_path),
                f"parent:{self.parent_identity[0]}:{self.parent_identity[1]}",
                target_identity,
                "backup-directory:"
                f"{self.backup_directory_identity[0]}:{self.backup_directory_identity[1]}",
                f"backup:{self.source_backup_identity[0]}:{self.source_backup_identity[1]}",
            )
        ).encode("utf-8")
        return _revision(payload)

    def preview(self) -> dict[str, Any]:
        return {
            "active_revision": None,
            "active_state": self.active_state,
            "applied": False,
            "candidate_revision": self.candidate_revision,
            "candidate_revision_protection": self.candidate_revision_protection,
            "candidate_snapshot": self.candidate_snapshot,
            "corrupt_bytes_quarantined_on_apply": self.active_state == "invalid",
            "expect_plan": self.plan_token,
            "expect_state": self.state_token,
            "operation": "recover-inventory",
            "private_notes_exposed": False,
            "source_backup_id": self.source_backup_id,
            "source_backup_path": str(self.source_backup_path),
            "source_backup_retained": True,
            "target": str(self.target),
        }


@dataclass(frozen=True)
class InventoryRecoveryReceipt:
    target: Path
    previous_state: str
    restored_revision: str
    observed_revision: str | None
    source_backup_id: str
    source_backup_path: Path
    quarantine_id: str | None
    quarantine_path: Path | None
    directory_synced: bool
    replacement_verified: bool
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied": True,
            "directory_synced": self.directory_synced,
            "observed_revision": self.observed_revision,
            "operation": "recover-inventory",
            "previous_revision": None,
            "previous_state": self.previous_state,
            "quarantine_id": self.quarantine_id,
            "quarantine_path": str(self.quarantine_path) if self.quarantine_path else None,
            "replacement_verified": self.replacement_verified,
            "restored_revision": self.restored_revision,
            "source_backup_id": self.source_backup_id,
            "source_backup_path": str(self.source_backup_path),
            "source_backup_retained": True,
            "target": str(self.target),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class _StoredInventoryBackup:
    backup_id: str
    path: Path
    raw: bytes = field(repr=False)
    inventory: Inventory = field(repr=False)
    file_identity: tuple[int, int]
    directory_identity: tuple[int, int]
    size_bytes: int = field(repr=False)
    filesystem_modified_at: str

    def summary(self, *, active_revision: str | None) -> InventoryBackupSummary:
        return InventoryBackupSummary(
            backup_id=self.backup_id,
            path=self.path,
            size_bytes=self.size_bytes,
            schema_version=self.inventory.schema_version,
            inventory_kind=self.inventory.inventory_kind,
            resource_count=len(self.inventory.resources),
            revision_protection=self.inventory.revision_protection(),
            matches_active=self.backup_id == active_revision,
            filesystem_modified_at=self.filesystem_modified_at,
        )


@dataclass(frozen=True)
class InventoryRollbackPlan:
    target: Path
    original_revision: str
    candidate_revision: str
    active_revision_protection: str
    candidate_revision_protection: str
    source_backup_id: str
    source_backup_path: Path
    candidate_raw: bytes = field(repr=False)
    target_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    backup_directory_identity: tuple[int, int]
    source_backup_identity: tuple[int, int]
    active_snapshot: dict[str, Any] = field(repr=False)
    candidate_snapshot: dict[str, Any] = field(repr=False)
    comparison: dict[str, Any] = field(repr=False)

    @property
    def plan_token(self) -> str:
        payload = "\0".join(
            (
                "rollback-inventory-v1",
                str(self.target),
                self.original_revision,
                self.candidate_revision,
                self.source_backup_id,
                str(self.source_backup_path),
                f"target:{self.target_identity[0]}:{self.target_identity[1]}",
                f"parent:{self.parent_identity[0]}:{self.parent_identity[1]}",
                "backup-directory:"
                f"{self.backup_directory_identity[0]}:{self.backup_directory_identity[1]}",
                f"backup:{self.source_backup_identity[0]}:{self.source_backup_identity[1]}",
            )
        ).encode("utf-8")
        return _revision(payload)

    def preview(self) -> dict[str, Any]:
        return {
            "active_snapshot": self.active_snapshot,
            "active_revision_protection": self.active_revision_protection,
            "applied": False,
            "candidate_revision": self.candidate_revision,
            "candidate_revision_protection": self.candidate_revision_protection,
            "candidate_snapshot": self.candidate_snapshot,
            "canonicalizes_yaml": False,
            "comparison": self.comparison,
            "expect_plan": self.plan_token,
            "expect_revision": self.original_revision,
            "operation": "rollback-inventory",
            "private_notes_exposed": False,
            "revision_privacy_nonce_changed": (
                self.comparison["revision_privacy_nonce_effect"] != "unchanged"
            ),
            "restores_hidden_private_notes": True,
            "safety_backup_on_apply": True,
            "source_backup_id": self.source_backup_id,
            "source_backup_path": str(self.source_backup_path),
            "target": str(self.target),
        }


@dataclass(frozen=True)
class InventoryRollbackReceipt:
    update: InventoryUpdateReceipt
    source_backup_id: str
    source_backup_path: Path
    candidate_revision_protection: str

    @property
    def target(self) -> Path:
        return self.update.target

    @property
    def observed_revision_protection(self) -> str | None:
        if (
            self.update.replacement_verified
            and self.update.revision == self.update.candidate_revision
        ):
            return self.candidate_revision_protection
        return None

    def as_dict(self) -> dict[str, Any]:
        result = self.update.as_dict()
        result.update(
            {
                "operation": "rollback-inventory",
                "restored_revision": self.update.candidate_revision,
                "safety_backup_id": self.update.backup_id,
                "safety_backup_path": str(self.update.backup_path),
                "source_backup_id": self.source_backup_id,
                "source_backup_path": str(self.source_backup_path),
                "candidate_revision_protection": self.candidate_revision_protection,
                "observed_revision_protection": self.observed_revision_protection,
            }
        )
        return result


@dataclass(frozen=True)
class InventoryBackupDeletePlan:
    target: Path
    original_revision: str
    backup_id: str
    backup_path: Path
    size_bytes: int = field(repr=False)
    selected_revision_protection: str
    remaining_revision_protection_counts: dict[str, int]
    target_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    backup_directory_identity: tuple[int, int]
    backup_identity: tuple[int, int]
    backup_set_revision: str
    backup_count_before: int
    allow_no_backups: bool
    warnings: tuple[str, ...] = ()

    @property
    def plan_token(self) -> str:
        payload = "\0".join(
            (
                "delete-inventory-backup-v1",
                str(self.target),
                self.original_revision,
                self.backup_id,
                str(self.backup_path),
                self.backup_set_revision,
                f"allow-no-backups:{str(self.allow_no_backups).lower()}",
                f"target:{self.target_identity[0]}:{self.target_identity[1]}",
                f"parent:{self.parent_identity[0]}:{self.parent_identity[1]}",
                "backup-directory:"
                f"{self.backup_directory_identity[0]}:{self.backup_directory_identity[1]}",
                f"backup:{self.backup_identity[0]}:{self.backup_identity[1]}",
            )
        ).encode("utf-8")
        return _revision(payload)

    def preview(self) -> dict[str, Any]:
        return {
            "allow_no_backups": self.allow_no_backups,
            "applied": False,
            "backup_count_after": self.backup_count_before - 1,
            "backup_count_before": self.backup_count_before,
            "backup_id": self.backup_id,
            "backup_path": str(self.backup_path),
            "expect_plan": self.plan_token,
            "expect_revision": self.original_revision,
            "irreversible": True,
            "operation": "delete-inventory-backup",
            "remaining_revision_protection_counts": self.remaining_revision_protection_counts,
            "selected_revision_protection": self.selected_revision_protection,
            "target": str(self.target),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class InventoryBackupDeleteReceipt:
    target: Path
    previous_revision: str
    backup_id: str
    backup_path: Path
    deletion_verified: bool
    directory_synced: bool
    remaining_valid_backups: int
    selected_revision_protection: str
    remaining_revision_protection_counts: dict[str, int] | None
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied": True,
            "backup_id": self.backup_id,
            "backup_path": str(self.backup_path),
            "deleted": True,
            "deletion_verified": self.deletion_verified,
            "directory_synced": self.directory_synced,
            "operation": "delete-inventory-backup",
            "previous_revision": self.previous_revision,
            "remaining_valid_backups": self.remaining_valid_backups,
            "remaining_revision_protection_counts": self.remaining_revision_protection_counts,
            "selected_revision_protection": self.selected_revision_protection,
            "target": str(self.target),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class _InventoryReplacementPlan:
    target: Path
    original_revision: str
    candidate_revision: str
    candidate_raw: bytes = field(repr=False)
    target_identity: tuple[int, int]
    parent_identity: tuple[int, int]


@dataclass(frozen=True)
class _RecoveryActiveState:
    target: Path
    state: str
    fingerprint: str
    raw: bytes | None = field(repr=False)
    target_identity: tuple[int, int] | None
    parent_identity: tuple[int, int]


class _CommittedQuarantineError(StorageError):
    """Carry an already-committed quarantine artifact across a later failure."""

    def __init__(self, message: str, *, quarantine_id: str, quarantine_path: Path) -> None:
        super().__init__(message)
        self.quarantine_id = quarantine_id
        self.quarantine_path = quarantine_path


def _inspect_regular_file(path: Path) -> os.stat_result:
    path = path.expanduser()
    try:
        inspected = path.lstat()
    except FileNotFoundError as exc:
        raise ConfigurationError(f"configuration file does not exist: {path}") from exc
    except OSError as exc:
        raise ConfigurationError(f"cannot inspect inventory {path}: {exc}") from exc
    if stat.S_ISLNK(inspected.st_mode):
        raise ConfigurationError(f"refusing to read symlinked configuration: {path}")
    if not stat.S_ISREG(inspected.st_mode):
        raise ConfigurationError(f"configuration path is not a regular file: {path}")
    return inspected


def _read_regular_descriptor(
    path: Path,
    descriptor: int,
    inspected: os.stat_result,
) -> tuple[bytes | None, ConfigurationError | None]:
    """Read one descriptor while returning, rather than raising, content-adjacent errors."""

    try:
        opened = os.fstat(descriptor)
    except OSError:
        return None, ConfigurationError(f"cannot inspect open inventory {path}")
    if not stat.S_ISREG(opened.st_mode):
        return None, ConfigurationError(f"configuration path is not a regular file: {path}")
    if not same_file_identity(opened, inspected):
        return None, ConfigurationError(f"inventory changed while it was being opened: {path}")
    if opened.st_size > MAX_FILE_BYTES:
        return None, ConfigurationError(f"configuration exceeds {MAX_FILE_BYTES} bytes: {path}")
    try:
        has_extended_acl = darwin_fd_has_extended_acl(descriptor)
    except OSError:
        return None, ConfigurationError(f"cannot verify inventory extended access controls: {path}")
    if has_extended_acl:
        return None, ConfigurationError(f"refusing inventory with a macOS extended ACL: {path}")
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
    except (OSError, ValueError):
        return None, ConfigurationError(f"cannot read inventory {path}")
    if len(raw) > MAX_FILE_BYTES:
        return None, ConfigurationError(f"configuration exceeds {MAX_FILE_BYTES} bytes: {path}")
    try:
        has_extended_acl = darwin_fd_has_extended_acl(descriptor)
    except OSError:
        return None, ConfigurationError(
            f"cannot recheck inventory extended access controls: {path}"
        )
    if has_extended_acl:
        return None, ConfigurationError(
            f"inventory gained a macOS extended ACL while being read: {path}"
        )
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            confirmed_raw = stream.read(MAX_FILE_BYTES + 1)
    except (OSError, ValueError):
        return None, ConfigurationError(f"cannot verify inventory snapshot: {path}")
    if confirmed_raw != raw:
        return None, ConfigurationError(f"inventory changed while it was being read: {path}")
    try:
        after = os.fstat(descriptor)
    except OSError:
        return None, ConfigurationError(f"cannot verify inventory after reading: {path}")
    if not descriptor_snapshot_unchanged(after, opened):
        return None, ConfigurationError(f"inventory changed while it was being read: {path}")
    return raw, None


def _read_regular_bytes(path: Path) -> bytes:
    path = path.expanduser()
    inspected = _inspect_regular_file(path)

    flags = os.O_RDONLY
    for flag_name in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= int(getattr(os, flag_name, 0))
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
    except OSError:
        pass
    if descriptor is None:
        raise ConfigurationError(f"cannot open inventory {path}")

    raw, failure = _read_regular_descriptor(path, descriptor, inspected)
    close_failed = False
    try:
        os.close(descriptor)
    except OSError:
        close_failed = True
    if close_failed:
        if failure is None:
            failure = ConfigurationError(f"cannot close inventory descriptor for {path}")
        else:
            failure.add_note("inventory descriptor cleanup failed")
    if failure is None:
        try:
            final = path.lstat()
        except OSError:
            failure = ConfigurationError(f"cannot verify inventory after reading: {path}")
        else:
            if not path_snapshot_unchanged(final, inspected=inspected, opened=inspected):
                failure = ConfigurationError(f"inventory changed while it was being read: {path}")
    if failure is not None:
        raw = None
        raise failure
    assert raw is not None
    return raw


def read_inventory_file(path: Path) -> InventoryFile:
    """Read exact bytes and validate an inventory without following the target symlink."""

    path = path.expanduser()
    raw = _read_regular_bytes(path)
    result, failure = _inventory_file_from_raw(path, raw)
    if failure is not None:
        del raw
        raise failure
    assert result is not None
    return result


def _inventory_file_from_raw(
    path: Path, raw: bytes
) -> tuple[InventoryFile | None, ConfigurationError | None]:
    """Parse bytes without propagating an exception frame that retains those bytes."""

    text: str | None = None
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        pass
    if text is None:
        return None, ConfigurationError(f"cannot read UTF-8 configuration {path}")
    try:
        inventory = InventoryCatalog.from_text(text).inventory
    except ConfigurationError as exc:
        return None, ConfigurationError(str(exc))
    return (
        InventoryFile(path=path, raw=raw, revision=_revision(raw), inventory=inventory),
        None,
    )


def _candidate_inventory(current: Inventory, resource: Resource) -> Inventory:
    _require_personal_inventory(current)
    if any(item.id == resource.id for item in current.resources):
        raise ConfigurationError(f"resource {resource.id!r} already exists")
    value = current.model_dump(mode="json")
    value["resources"].append(resource.model_dump(mode="json"))
    failure: ConfigurationError | None = None
    try:
        return Inventory.model_validate(value)
    except ValidationError as exc:
        failure = _format_validation_errors(exc, subject="inventory")
    assert failure is not None
    raise failure


def _replacement_inventory(current: Inventory, resource: Resource) -> tuple[Inventory, Resource]:
    _require_personal_inventory(current)
    matches = [index for index, item in enumerate(current.resources) if item.id == resource.id]
    if not matches:
        raise ConfigurationError(f"resource {resource.id!r} does not exist")
    index = matches[0]
    previous = current.resources[index]
    value = current.model_dump(mode="json")
    value["resources"][index] = resource.model_dump(mode="json")
    try:
        return Inventory.model_validate(value), previous
    except ValidationError as exc:
        raise _format_validation_errors(exc, subject="inventory") from exc


def _inventory_without_resource(current: Inventory, resource_id: str) -> tuple[Inventory, Resource]:
    _require_personal_inventory(current)
    matches = [index for index, item in enumerate(current.resources) if item.id == resource_id]
    if not matches:
        raise ConfigurationError(f"resource {resource_id!r} does not exist")
    index = matches[0]
    removed = current.resources[index]
    value = current.model_dump(mode="json")
    del value["resources"][index]
    try:
        return Inventory.model_validate(value), removed
    except ValidationError as exc:
        raise _format_validation_errors(exc, subject="inventory") from exc


def _physical_inventory_path(path: Path) -> Path:
    """Resolve Darwin case aliases to the descriptor's physical directory-entry spelling."""

    if sys.platform != "darwin":
        return path
    inspected = _inspect_regular_file(path)
    flags = os.O_RDONLY
    for flag_name in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= int(getattr(os, flag_name, 0))
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StorageError(f"cannot open inventory for physical target identity: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if not same_file_identity(opened, inspected):
            raise StorageError(f"inventory changed while resolving its physical path: {path}")
        import fcntl

        raw_path = fcntl.fcntl(descriptor, fcntl.F_GETPATH, b"\0" * 1_024)
        physical_path = Path(os.fsdecode(raw_path.split(b"\0", 1)[0]))
        if not physical_path.name:
            raise StorageError(f"cannot resolve physical inventory path: {path}")
        return physical_path
    except OSError as exc:
        raise StorageError(f"cannot resolve physical inventory path: {path}") from exc
    finally:
        active_error = sys.exception()
        try:
            os.close(descriptor)
        except OSError as exc:
            if active_error is not None:
                active_error.add_note(f"physical inventory path descriptor cleanup failed: {exc}")
            else:
                raise StorageError(
                    f"cannot close physical inventory path descriptor: {path}"
                ) from exc


def _case_contract_for(platform: str, os_name: str) -> str:
    if platform == "darwin":
        return _CASE_PHYSICAL
    if os_name == "posix":
        return _CASE_SENSITIVE
    if os_name == "nt":
        return _CASE_INSENSITIVE
    raise StorageError(f"unsupported filesystem case-semantics platform: {os_name}")


def _platform_case_contract() -> str:
    """Return the one case-semantics contract supported by this platform."""

    return _case_contract_for(sys.platform, os.name)


def _ascii_case_variants(name: str) -> tuple[str, ...]:
    """Return bounded one-position variants without Unicode case expansion."""

    variants: list[str] = []
    for index, character in enumerate(name):
        if "a" <= character <= "z":
            variants.append(name[:index] + character.upper() + name[index + 1 :])
        elif "A" <= character <= "Z":
            variants.append(name[:index] + character.lower() + name[index + 1 :])
    return tuple(variants)


def _case_probe_failure(path: Path) -> StorageError:
    return StorageError(
        f"cannot verify filesystem case semantics for inventory directory: {path.parent}"
    )


def _case_entry_observation(
    details: os.stat_result,
    *,
    path: Path,
) -> _CaseEntryObservation:
    """Reduce one lstat-style result to non-secret identity evidence."""

    if not file_identity_is_known(details) or details.st_nlink < 1:
        raise _case_probe_failure(path)
    return (
        details.st_dev,
        details.st_ino,
        details.st_nlink,
        stat.S_IFMT(details.st_mode),
    )


def _classify_case_observations(
    path: Path,
    *,
    target: os.stat_result,
    first: _CaseEntryObservation,
    second: _CaseEntryObservation,
) -> str:
    """Classify two stable observations of one exact case-only sibling spelling."""

    if first != second:
        raise _case_probe_failure(path)
    if first is None:
        return _CASE_SENSITIVE
    if first[:2] != (target.st_dev, target.st_ino):
        return _CASE_SENSITIVE
    if first[2] != 1 or first[3] != stat.S_IFREG:
        raise _case_probe_failure(path)
    return _CASE_INSENSITIVE


def _require_uniform_case_semantics(path: Path, observations: tuple[str, ...]) -> str:
    if not observations or any(observed != observations[0] for observed in observations[1:]):
        raise _case_probe_failure(path)
    return observations[0]


def _case_snapshot_unchanged(
    current: os.stat_result,
    baseline: os.stat_result,
) -> bool:
    return (
        descriptor_snapshot_unchanged(current, baseline)
        and current.st_nlink == baseline.st_nlink
        and stat.S_IFMT(current.st_mode) == stat.S_IFMT(baseline.st_mode)
    )


def _posix_case_entry(
    descriptor: int,
    name: str,
    *,
    path: Path,
) -> _CaseEntryObservation:
    try:
        details = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except (OSError, NotImplementedError, TypeError) as exc:
        raise _case_probe_failure(path) from exc
    return _case_entry_observation(details, path=path)


def _observe_posix_case_semantics(
    path: Path,
    variants: tuple[str, ...],
    *,
    target: os.stat_result,
    parent: os.stat_result,
) -> str:
    """Probe a POSIX directory through a pinned, non-followed parent descriptor."""

    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")
    if any(not hasattr(os, flag) for flag in required_flags):
        raise _case_probe_failure(path)
    if os.stat not in os.supports_dir_fd or os.stat not in os.supports_follow_symlinks:
        raise _case_probe_failure(path)

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    flags |= int(getattr(os, "O_CLOEXEC", 0))
    try:
        descriptor = os.open(path.parent, flags)
    except OSError as exc:
        raise _case_probe_failure(path) from exc
    try:
        try:
            opened_parent = os.fstat(descriptor)
            opened_target = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        except (OSError, NotImplementedError, TypeError) as exc:
            raise _case_probe_failure(path) from exc
        if (
            not stat.S_ISDIR(opened_parent.st_mode)
            or not _case_snapshot_unchanged(opened_parent, parent)
            or not stat.S_ISREG(opened_target.st_mode)
            or opened_target.st_nlink != 1
            or not _case_snapshot_unchanged(opened_target, target)
        ):
            raise _case_probe_failure(path)

        observations: list[str] = []
        for variant in variants:
            first = _posix_case_entry(descriptor, variant, path=path)
            second = _posix_case_entry(descriptor, variant, path=path)
            observations.append(
                _classify_case_observations(
                    path,
                    target=opened_target,
                    first=first,
                    second=second,
                )
            )
        try:
            final_target = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
            final_parent = os.fstat(descriptor)
            live_target = path.lstat()
            live_parent = path.parent.lstat()
        except (OSError, NotImplementedError, TypeError) as exc:
            raise _case_probe_failure(path) from exc
        if (
            not _case_snapshot_unchanged(final_target, opened_target)
            or not _case_snapshot_unchanged(final_parent, opened_parent)
            or not _case_snapshot_unchanged(live_target, opened_target)
            or not _case_snapshot_unchanged(live_parent, opened_parent)
        ):
            raise _case_probe_failure(path)
        return _require_uniform_case_semantics(path, tuple(observations))
    finally:
        active_error = sys.exception()
        try:
            os.close(descriptor)
        except OSError as exc:
            if active_error is not None:
                active_error.add_note("case-semantics directory descriptor cleanup failed")
            else:
                raise _case_probe_failure(path) from exc


def _direct_case_entry(path: Path, variant: str) -> _CaseEntryObservation:
    try:
        details = path.with_name(variant).lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _case_probe_failure(path) from exc
    return _case_entry_observation(details, path=path)


def _observe_direct_case_semantics(
    path: Path,
    variants: tuple[str, ...],
    *,
    target: os.stat_result,
    parent: os.stat_result,
) -> str:
    """Probe platforms without descriptor-relative stat and reject snapshot drift."""

    observations: list[str] = []
    for variant in variants:
        first = _direct_case_entry(path, variant)
        second = _direct_case_entry(path, variant)
        observations.append(
            _classify_case_observations(
                path,
                target=target,
                first=first,
                second=second,
            )
        )
    try:
        final_target = path.lstat()
        final_parent = path.parent.lstat()
    except OSError as exc:
        raise _case_probe_failure(path) from exc
    if not _case_snapshot_unchanged(final_target, target) or not _case_snapshot_unchanged(
        final_parent, parent
    ):
        raise _case_probe_failure(path)
    return _require_uniform_case_semantics(path, tuple(observations))


def _observe_case_semantics(
    path: Path,
    variants: tuple[str, ...],
    *,
    target: os.stat_result,
    parent: os.stat_result,
) -> str:
    if os.name == "posix":
        return _observe_posix_case_semantics(
            path,
            variants,
            target=target,
            parent=parent,
        )
    if os.name == "nt":
        return _observe_direct_case_semantics(
            path,
            variants,
            target=target,
            parent=parent,
        )
    raise _case_probe_failure(path)


def _validate_supported_case_semantics(path: Path) -> None:
    """Refuse backup namespaces whose case behavior cannot be mapped safely."""

    contract = _platform_case_contract()
    if contract == _CASE_PHYSICAL:
        return
    if not path.name.isascii():
        raise StorageError(
            "cannot verify filesystem case semantics because the inventory filename is not "
            f"ASCII: {path}"
        )
    variants = _ascii_case_variants(path.name)
    if not variants:
        raise StorageError(
            "cannot verify filesystem case semantics because the inventory filename has no "
            f"ASCII letter: {path}"
        )
    target = _inspect_regular_file(path)
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise _case_probe_failure(path) from exc
    if (
        not stat.S_ISREG(target.st_mode)
        or target.st_nlink != 1
        or not file_identity_is_known(target)
        or not stat.S_ISDIR(parent.st_mode)
        or not file_identity_is_known(parent)
    ):
        raise _case_probe_failure(path)

    observed = _observe_case_semantics(
        path,
        variants,
        target=target,
        parent=parent,
    )
    if observed == contract:
        return
    if contract == _CASE_SENSITIVE and observed == _CASE_INSENSITIVE:
        raise StorageError(
            f"refusing case-insensitive non-Darwin POSIX inventory directory: {path.parent}"
        )
    if contract == _CASE_INSENSITIVE and observed == _CASE_SENSITIVE:
        raise StorageError(f"refusing case-sensitive Windows inventory directory: {path.parent}")
    raise _case_probe_failure(path)


def _canonical_update_target(path: Path) -> Path:
    """Return a physical absolute target while refusing final/direct-parent links."""

    lexical = path.expanduser().absolute()
    try:
        parent_mode = lexical.parent.lstat().st_mode
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {lexical.parent}: {exc}") from exc
    if stat.S_ISLNK(parent_mode):
        raise StorageError(f"refusing symlinked AtReady directory: {lexical.parent}")
    if not stat.S_ISDIR(parent_mode):
        raise StorageError(f"refusing non-directory AtReady path: {lexical.parent}")
    inspected = _inspect_regular_file(lexical)
    if stat.S_ISLNK(inspected.st_mode):
        raise ConfigurationError(f"refusing to read symlinked configuration: {lexical}")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"cannot resolve inventory {lexical}: {exc}") from exc
    return _physical_inventory_path(resolved)


def _canonical_recovery_target(path: Path) -> Path:
    """Resolve the parent physically while allowing the final target to be absent."""

    lexical = path.expanduser().absolute()
    try:
        parent_mode = lexical.parent.lstat().st_mode
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {lexical.parent}: {exc}") from exc
    if stat.S_ISLNK(parent_mode):
        raise StorageError(f"refusing symlinked AtReady directory: {lexical.parent}")
    if not stat.S_ISDIR(parent_mode):
        raise StorageError(f"refusing non-directory AtReady path: {lexical.parent}")
    try:
        parent = lexical.parent.resolve(strict=True)
    except OSError as exc:
        raise StorageError(f"cannot resolve inventory directory {lexical.parent}: {exc}") from exc
    candidate = parent / lexical.name
    try:
        candidate.lstat()
    except FileNotFoundError:
        return candidate
    except OSError as exc:
        raise ConfigurationError(f"cannot inspect inventory {candidate}: {exc}") from exc
    return _canonical_update_target(candidate)


def _validate_recovery_parent(target: Path) -> os.stat_result:
    """Apply the persistent-write parent contract without requiring the target."""

    _validate_posix_ancestor_chain(target)
    try:
        parent = target.parent.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {target.parent}: {exc}") from exc
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        raise StorageError(f"refusing unsafe inventory directory: {target.parent}")
    if os.name == "posix":
        if parent.st_uid != os.geteuid():
            raise StorageError(
                f"refusing inventory directory not owned by the current user: {target.parent}"
            )
        mode = stat.S_IMODE(parent.st_mode)
        if mode & 0o022:
            raise StorageError(
                f"refusing writable inventory directory mode {oct(mode)}: {target.parent}"
            )
        validate_no_darwin_extended_acl(
            target.parent,
            parent,
            subject="inventory directory",
            directory=True,
        )
    return parent


def _recovery_active_state(path: Path) -> _RecoveryActiveState:
    """Classify only the two states that disaster recovery is allowed to replace."""

    target = _canonical_recovery_target(path)
    parent = _validate_recovery_parent(target)
    try:
        target.lstat()
    except FileNotFoundError:
        return _RecoveryActiveState(
            target=target,
            state="missing",
            fingerprint="missing",
            raw=None,
            target_identity=None,
            parent_identity=_required_identity(parent, subject="inventory directory"),
        )
    except OSError as exc:
        raise ConfigurationError(f"cannot inspect inventory {target}: {exc}") from exc

    _validate_update_target(target)
    raw = _read_regular_bytes(target)
    parsed, failure = _inventory_file_from_raw(target, raw)
    if failure is None:
        assert parsed is not None
        if parsed.inventory.inventory_kind is InventoryKind.DEMO:
            raise ConfigurationError("demo inventories are read-only and cannot be recovered over")
        raise ConfigurationError(
            "active inventory is valid; use inventory backup rollback instead of recover"
        )
    details = _inspect_regular_file(target)
    return _RecoveryActiveState(
        target=target,
        state="invalid",
        fingerprint=_revision(raw),
        raw=raw,
        target_identity=_required_identity(details, subject="inventory target"),
        parent_identity=_required_identity(parent, subject="inventory directory"),
    )


def _validate_posix_ancestor_chain(path: Path) -> None:
    """Reject canonical ancestor entries another local account can retarget."""

    if os.name != "posix":
        return
    chain = [path.parent, *path.parent.parents]
    chain.reverse()
    inspected: list[tuple[Path, os.stat_result]] = []
    for directory in chain:
        try:
            details = directory.lstat()
        except OSError as exc:
            raise StorageError(f"cannot inspect inventory ancestor {directory}: {exc}") from exc
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise StorageError(f"refusing unsafe inventory ancestor: {directory}")
        inspected.append((directory, details))

    trusted_owners = {0, os.geteuid()}
    for (parent, parent_details), (child, child_details) in pairwise(inspected):
        mode = stat.S_IMODE(parent_details.st_mode)
        if not mode & 0o022:
            continue
        sticky = bool(mode & stat.S_ISVTX)
        if (
            not sticky
            or parent_details.st_uid not in trusted_owners
            or child_details.st_uid not in trusted_owners
        ):
            raise StorageError(
                f"refusing retargetable inventory ancestor {parent} for child {child}"
            )


def _validate_update_target(path: Path) -> None:
    """Reject redirected or shared targets before planning a persistent update."""

    try:
        parent_mode = path.parent.lstat().st_mode
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {path.parent}: {exc}") from exc
    if stat.S_ISLNK(parent_mode):
        raise StorageError(f"refusing symlinked AtReady directory: {path.parent}")
    if not stat.S_ISDIR(parent_mode):
        raise StorageError(f"refusing non-directory AtReady path: {path.parent}")
    _validate_posix_ancestor_chain(path)
    if os.name == "posix":
        inspected_parent = path.parent.lstat()
        if inspected_parent.st_uid != os.geteuid():
            raise StorageError(
                f"refusing inventory directory not owned by the current user: {path.parent}"
            )
        mode = stat.S_IMODE(inspected_parent.st_mode)
        if mode & 0o022:
            raise StorageError(
                f"refusing writable inventory directory mode {oct(mode)}: {path.parent}"
            )
        validate_no_darwin_extended_acl(
            path.parent,
            inspected_parent,
            subject="inventory directory",
            directory=True,
        )

    inspected = _inspect_regular_file(path)
    if inspected.st_nlink != 1:
        raise StorageError(f"refusing hard-linked inventory update target: {path}")
    if os.name == "posix":
        if inspected.st_uid != os.geteuid():
            raise StorageError(f"refusing inventory not owned by the current user: {path}")
        mode = stat.S_IMODE(inspected.st_mode)
        if mode != 0o600:
            raise StorageError(f"refusing insecure inventory mode {oct(mode)}: {path}")
        validate_no_darwin_extended_acl(
            path,
            inspected,
            subject="inventory",
            directory=False,
        )
    _validate_supported_case_semantics(path)


def _require_personal_inventory(inventory: Inventory) -> None:
    if inventory.inventory_kind is not InventoryKind.PERSONAL:
        raise ConfigurationError("demo inventories are read-only; initialize a personal inventory")


def _backup_namespace(target: Path) -> str:
    """Derive a stable logical-target namespace without relying on replaceable inodes."""

    logical_name = os.path.normcase(target.name)
    digest = hashlib.sha256(os.fsencode(logical_name)).hexdigest()
    return f"target-{digest}"


def _validate_backup_id(backup_id: str) -> str:
    if _BACKUP_ID_PATTERN.fullmatch(backup_id) is None:
        raise ConfigurationError("backup ID must be sha256: followed by 64 lowercase hex digits")
    return backup_id


def _validated_private_directory(path: Path, *, subject: str) -> os.stat_result:
    try:
        details = path.lstat()
    except FileNotFoundError as exc:
        raise ConfigurationError(f"{subject} does not exist: {path}") from exc
    except OSError as exc:
        raise StorageError(f"cannot inspect {subject} {path}: {exc}") from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise StorageError(f"refusing unsafe {subject}: {path}")
    if os.name == "posix":
        if details.st_uid != os.geteuid():
            raise StorageError(f"refusing {subject} not owned by the current user: {path}")
        mode = stat.S_IMODE(details.st_mode)
        if mode != 0o700:
            raise StorageError(f"refusing insecure {subject} mode {oct(mode)}: {path}")
        validate_no_darwin_extended_acl(
            path,
            details,
            subject=subject,
            directory=True,
        )
    return details


def _snapshot_inventory(inventory: Inventory) -> dict[str, Any]:
    """Revalidate serialized values, then return the established private-note-free snapshot."""

    value = inventory.model_dump(mode="json")
    return InventoryCatalog.from_mapping(value).snapshot()


def _private_note_effect(current: str | None, candidate: str | None) -> str:
    if current == candidate:
        return "unchanged"
    if current is None:
        return "will-add"
    if candidate is None:
        return "will-remove"
    return "will-change"


def _inventory_comparison(current: Inventory, candidate: Inventory) -> dict[str, Any]:
    current_resources = {resource.id: resource for resource in current.resources}
    candidate_resources = {resource.id: resource for resource in candidate.resources}
    current_ids = set(current_resources)
    candidate_ids = set(candidate_resources)
    changed_ids = sorted(
        resource_id
        for resource_id in current_ids & candidate_ids
        if current_resources[resource_id].model_dump(mode="json", exclude={"private_notes"})
        != candidate_resources[resource_id].model_dump(mode="json", exclude={"private_notes"})
    )
    note_effects = {"unchanged": 0, "will-add": 0, "will-remove": 0, "will-change": 0}
    for resource_id in current_ids | candidate_ids:
        current_note = (
            current_resources[resource_id].private_notes
            if resource_id in current_resources
            else None
        )
        candidate_note = (
            candidate_resources[resource_id].private_notes
            if resource_id in candidate_resources
            else None
        )
        note_effects[_private_note_effect(current_note, candidate_note)] += 1
    return {
        "inventory_private_notes": _private_note_effect(
            current.private_notes, candidate.private_notes
        ),
        "revision_privacy_nonce_effect": _private_note_effect(
            current.revision_privacy_nonce,
            candidate.revision_privacy_nonce,
        ),
        "preferences_change": (
            "unchanged" if current.preferences == candidate.preferences else "will-change"
        ),
        "resource_changes": {
            "added": sorted(candidate_ids - current_ids),
            "changed": changed_ids,
            "removed": sorted(current_ids - candidate_ids),
        },
        "resource_private_note_effect_counts": note_effects,
    }


class _InventoryBackupStore:
    """Deep internal module for target-scoped backup storage and validation."""

    def __init__(self, target: Path) -> None:
        self.target = target
        # This hidden name is a persisted v1 storage contract. Retain it so the
        # product rename does not strand exact-byte backups beside an inventory.
        self.root = target.parent / ".quartermaster-backups"
        self.namespace = _backup_namespace(target)
        self.directory = self.root / self.namespace

    def _existing_directories(self) -> tuple[os.stat_result, os.stat_result] | None:
        try:
            self.root.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError(f"cannot inspect backup root {self.root}: {exc}") from exc
        root_details = _validated_private_directory(self.root, subject="backup root")
        try:
            self.directory.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError(
                f"cannot inspect target backup directory {self.directory}: {exc}"
            ) from exc
        directory_details = _validated_private_directory(
            self.directory, subject="target backup directory"
        )
        return root_details, directory_details

    def _ensure_directories(self) -> tuple[os.stat_result, os.stat_result]:
        ensure_private_directory(self.root)
        root_details = _validated_private_directory(self.root, subject="backup root")
        root_entry_count = self._root_entry_count()
        try:
            self.directory.lstat()
        except FileNotFoundError:
            if root_entry_count >= _MAX_BACKUP_DIRECTORY_ENTRIES:
                raise StorageError(
                    "backup root is at its bounded target capacity; "
                    "choose a different inventory parent or remove obsolete legacy storage"
                ) from None
            ensure_private_directory(self.directory)
        except OSError as exc:
            raise StorageError(
                f"cannot inspect target backup directory {self.directory}: {exc}"
            ) from exc
        directory_details = _validated_private_directory(
            self.directory, subject="target backup directory"
        )
        return root_details, directory_details

    def _root_entry_count(self) -> int:
        try:
            iterator = os.scandir(self.root)
        except OSError as exc:
            raise StorageError(f"cannot inspect backup root capacity {self.root}: {exc}") from exc
        entries_seen = 0
        with iterator:
            for _entry in iterator:
                entries_seen += 1
                if entries_seen > _MAX_BACKUP_DIRECTORY_ENTRIES:
                    raise StorageError(
                        f"backup root exceeds {_MAX_BACKUP_DIRECTORY_ENTRIES} entries"
                    )
        return entries_seen

    def _legacy_unscoped_count(self) -> int:
        try:
            iterator = os.scandir(self.root)
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise StorageError(f"cannot list backup root {self.root}: {exc}") from exc
        count = 0
        entries_seen = 0
        with iterator:
            for entry in iterator:
                entries_seen += 1
                if entries_seen > _MAX_BACKUP_DIRECTORY_ENTRIES:
                    raise StorageError(
                        f"backup root exceeds {_MAX_BACKUP_DIRECTORY_ENTRIES} entries"
                    )
                if _BACKUP_FILENAME_PATTERN.fullmatch(entry.name):
                    count += 1
        return count

    def _path_for_id(self, backup_id: str) -> Path:
        digest = _validate_backup_id(backup_id).removeprefix("sha256:")
        return self.directory / f"inventory-{digest}.yaml"

    def _namespace_usage(self) -> tuple[int, int]:
        directories = self._existing_directories()
        if directories is None:
            return 0, 0
        try:
            iterator = os.scandir(self.directory)
        except OSError as exc:
            raise StorageError(
                f"cannot inspect target backup capacity {self.directory}: {exc}"
            ) from exc
        entries_seen = 0
        total_bytes = 0
        with iterator:
            for entry in iterator:
                if entry.name == _MANIFEST_DIRECTORY_NAME:
                    continue
                entries_seen += 1
                if entries_seen > _MAX_BACKUP_DIRECTORY_ENTRIES:
                    raise StorageError(
                        "target backup directory exceeds "
                        f"{_MAX_BACKUP_DIRECTORY_ENTRIES} entries: {self.directory}"
                    )
                try:
                    details = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise StorageError(
                        f"cannot inspect target backup entry {self.directory / entry.name}: {exc}"
                    ) from exc
                total_bytes += max(0, details.st_size)
                if total_bytes > _MAX_BACKUP_TOTAL_BYTES:
                    raise StorageError(
                        "target backup directory exceeds the bounded inspection budget of "
                        f"{_MAX_BACKUP_TOTAL_BYTES} bytes: {self.directory}"
                    )
        return entries_seen, total_bytes

    def _read_restorable(self, backup_id: str) -> _StoredInventoryBackup:
        directories = self._existing_directories()
        if directories is None:
            raise ConfigurationError(f"no target-scoped backups exist for inventory {self.target}")
        _, directory_details = directories
        path = self._path_for_id(backup_id)
        try:
            inspected = _inspect_regular_file(path)
        except ConfigurationError as exc:
            raise ConfigurationError(
                f"backup does not exist or is not a regular file: {backup_id}"
            ) from exc
        if inspected.st_nlink != 1:
            raise StorageError(f"refusing hard-linked backup file: {path}")
        if os.name == "posix":
            if inspected.st_uid != os.geteuid():
                raise StorageError(f"refusing unsafe backup file: {path}")
            mode = stat.S_IMODE(inspected.st_mode)
            if mode != 0o600:
                raise StorageError(f"refusing insecure backup file mode {oct(mode)}: {path}")
        try:
            raw = _read_regular_bytes(path)
        except ConfigurationError as exc:
            raise ConfigurationError(f"backup cannot be read safely: {backup_id}") from exc
        observed_revision = _revision(raw)
        if observed_revision != backup_id:
            raise StorageError(f"backup content does not match its ID: {backup_id}")
        text: str | None = None
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            pass
        if text is None:
            raise ConfigurationError(f"backup is not a valid UTF-8 inventory: {backup_id}")
        inventory: Inventory | None = None
        invalid_inventory = False
        try:
            inventory = InventoryCatalog.from_text(text).inventory
        except ConfigurationError:
            invalid_inventory = True
        if invalid_inventory:
            raise ConfigurationError(f"backup is not a valid inventory: {backup_id}")
        assert inventory is not None
        if inventory.inventory_kind is not InventoryKind.PERSONAL:
            raise ConfigurationError(f"backup is not a personal inventory: {backup_id}")
        final_details = _inspect_regular_file(path)
        if not same_file_identity(final_details, inspected):
            raise StorageError(f"backup changed while it was inspected: {backup_id}")
        modified_at = (
            datetime.fromtimestamp(final_details.st_mtime, UTC).isoformat().replace("+00:00", "Z")
        )
        return _StoredInventoryBackup(
            backup_id=backup_id,
            path=path,
            raw=raw,
            inventory=inventory,
            file_identity=_required_identity(final_details, subject="backup file"),
            directory_identity=_required_identity(
                directory_details,
                subject="target backup directory",
            ),
            size_bytes=len(raw),
            filesystem_modified_at=modified_at,
        )

    def _read(self, backup_id: str) -> _StoredInventoryBackup:
        """Collapse all exact-ID availability states to one non-oracular diagnostic."""

        backup: _StoredInventoryBackup | None = None
        unavailable = False
        try:
            backup = self._read_restorable(backup_id)
        except AtReadyError:
            unavailable = True
        if unavailable or backup is None:
            raise ConfigurationError("backup is unavailable or non-restorable")
        return backup

    def list(self) -> tuple[tuple[_StoredInventoryBackup, ...], int, tuple[str, ...]]:
        directories = self._existing_directories()
        legacy_count = self._legacy_unscoped_count()
        warnings: list[str] = []
        if legacy_count:
            warnings.append(
                f"found {legacy_count} legacy unscoped backup file(s); they are not selectable "
                "because no target ownership can be proven"
            )
        if directories is None:
            return (), legacy_count, tuple(warnings)
        try:
            iterator = os.scandir(self.directory)
        except OSError as exc:
            raise StorageError(
                f"cannot list target backup directory {self.directory}: {exc}"
            ) from exc
        backups: list[_StoredInventoryBackup] = []
        entries_seen = 0
        total_bytes_seen = 0
        unexpected_entries = 0
        non_restorable_backups = 0
        with iterator:
            for entry in iterator:
                if entry.name == _MANIFEST_DIRECTORY_NAME:
                    continue
                entries_seen += 1
                if entries_seen > _MAX_BACKUP_DIRECTORY_ENTRIES:
                    raise StorageError(
                        "target backup directory exceeds "
                        f"{_MAX_BACKUP_DIRECTORY_ENTRIES} entries: {self.directory}"
                    )
                try:
                    details = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise StorageError(
                        f"cannot inspect target backup entry {self.directory / entry.name}: {exc}"
                    ) from exc
                total_bytes_seen += max(0, details.st_size)
                if total_bytes_seen > _MAX_BACKUP_TOTAL_BYTES:
                    raise StorageError(
                        "target backup directory exceeds the bounded inspection budget of "
                        f"{_MAX_BACKUP_TOTAL_BYTES} bytes: {self.directory}"
                    )
                match = _BACKUP_FILENAME_PATTERN.fullmatch(entry.name)
                if match is None:
                    unexpected_entries += 1
                    continue
                backup_id = "sha256:" + match.group(1)
                try:
                    backups.append(self._read(backup_id))
                except AtReadyError:
                    non_restorable_backups += 1
        if unexpected_entries:
            warnings.append(
                f"ignored {unexpected_entries} unexpected target backup directory entry(s)"
            )
        if non_restorable_backups:
            warnings.append(
                f"ignored {non_restorable_backups} non-restorable target-scoped backup(s)"
            )
        backups.sort(key=lambda backup: backup.backup_id)
        return tuple(backups), legacy_count, tuple(warnings)

    def read(self, backup_id: str) -> _StoredInventoryBackup:
        return self._read(_validate_backup_id(backup_id))

    def save(self, raw: bytes) -> tuple[str, Path]:
        digest = hashlib.sha256(raw).hexdigest()
        backup_id = "sha256:" + digest
        self._ensure_directories()
        backup_path = self._path_for_id(backup_id)
        try:
            backup_path.lstat()
            backup_exists = True
        except FileNotFoundError:
            backup_exists = False
        except OSError as exc:
            raise StorageError(
                f"cannot inspect inventory backup path {backup_path}: {exc}"
            ) from exc
        if backup_exists:
            existing = self._read(backup_id)
            if existing.raw != raw:
                raise StorageError(f"backup digest collision or unexpected content: {backup_path}")
        else:
            entry_count, total_bytes = self._namespace_usage()
            if entry_count >= _MAX_BACKUP_DIRECTORY_ENTRIES:
                raise StorageError(
                    "target backup directory is at its bounded entry capacity; "
                    "delete one exact validated backup or manually inspect unexpected entries "
                    f"before another inventory replacement: {self.directory}"
                )
            if total_bytes + len(raw) > _MAX_BACKUP_TOTAL_BYTES:
                raise StorageError(
                    "target backup directory is at its bounded byte capacity; "
                    "delete one exact validated backup or manually inspect unexpected entries "
                    f"before another inventory replacement: {self.directory}"
                )
            from atready.paths import create_private_file

            text: str | None = None
            try:
                text = raw.decode("utf-8")
            except UnicodeError:
                pass
            if text is None:
                raise StorageError("validated inventory bytes are unexpectedly not UTF-8")
            create_private_file(backup_path, text)
            self._read(backup_id)

        if os.name == "posix" and not _fsync_directory(self.directory):
            raise StorageError(
                "cannot sync target backup directory before inventory replacement: "
                f"{self.directory}"
            )
        if os.name == "posix" and not _fsync_directory(self.root):
            raise StorageError(f"cannot sync backup root before inventory replacement: {self.root}")
        if os.name == "posix" and not _fsync_directory(self.target.parent):
            raise StorageError(
                "cannot sync inventory directory after private backup and before replacement: "
                f"{self.target.parent}"
            )
        return backup_id, backup_path


_MANIFEST_OPERATIONS = frozenset(
    {
        "add-resource",
        "annotate-inventory",
        "delete-inventory-backup",
        "recover-inventory",
        "remove-resource",
        "replace-resource",
        "rollback-inventory",
    }
)
_MANIFEST_PHASES = frozenset({"prepared", "completed", "aborted", "uncertain"})


def _canonical_manifest_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _manifest_details_are_safe(value: Any) -> bool:
    """Validate bounded, value-free manifest metadata without recursive descent."""

    pending: list[tuple[Any, int]] = [(value, 0)]
    values_seen = 0
    while pending:
        item, depth = pending.pop()
        values_seen += 1
        if values_seen > _MAX_MANIFEST_DETAILS_VALUES or depth > _MAX_MANIFEST_DETAILS_DEPTH:
            return False
        if item is None or isinstance(item, (bool, int, str)):
            continue
        if isinstance(item, list):
            if not all(isinstance(child, str) for child in item):
                return False
            values_seen += len(item)
            if values_seen > _MAX_MANIFEST_DETAILS_VALUES:
                return False
            continue
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                return False
            pending.extend((child, depth + 1) for child in item.values())
            continue
        return False
    return True


def _sync_manifest_directory(path: Path) -> None:
    """Durably sync manifest metadata without sharing inventory fsync fault injection."""

    if os.name != "posix" or not hasattr(os, "O_DIRECTORY"):
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(descriptor)
    except OSError as exc:
        raise StorageError(f"cannot sync backup operation manifest directory: {path}") from exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                raise StorageError(
                    f"cannot close backup operation manifest directory descriptor: {path}"
                ) from exc


def _append_manifest_file(path: Path, raw: bytes) -> str | None:
    """Commit one immutable event without using the inventory candidate-file seam."""

    temp_path: Path | None = None
    descriptor: int | None = None
    for _attempt in range(8):
        candidate = path.parent / f".manifest-{os.urandom(16).hex()}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_CLOEXEC", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        try:
            descriptor = os.open(candidate, flags, 0o600)
        except FileExistsError:
            continue
        except OSError as exc:
            raise StorageError("cannot create backup operation manifest event") from exc
        temp_path = candidate
        break
    if descriptor is None or temp_path is None:
        raise StorageError("cannot allocate backup operation manifest temporary file")
    try:
        failure = _populate_candidate_descriptor(descriptor, raw)
    except BaseException as exc:
        _scrub_close_unlink_temp(
            descriptor,
            temp_path,
            exc,
            descriptor_note="backup operation manifest descriptor cleanup failed",
            unlink_note="backup operation manifest temporary-file cleanup failed",
        )
        raise
    try:
        os.close(descriptor)
    except OSError as exc:
        if failure is None:
            failure = StorageError("cannot close backup operation manifest event")
            failure.__cause__ = exc
        else:
            failure.add_note("backup operation manifest descriptor cleanup failed")
    if failure is not None:
        temp_path.unlink(missing_ok=True)
        raise failure
    committed = False
    try:
        os.link(temp_path, path, follow_symlinks=False)
        committed = True
    except (OSError, NotImplementedError) as exc:
        failure = StorageError("cannot append backup operation manifest event")
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            failure.add_note("backup operation manifest temporary-file cleanup also failed")
        raise failure from exc
    cleanup_warning: str | None = None
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        if committed:
            cleanup_warning = (
                "backup operation manifest event committed, but its validated temporary hard "
                "link could not be removed"
            )
        else:
            raise StorageError("cannot clean backup operation manifest temporary file") from None
    try:
        _sync_manifest_directory(path.parent)
    except StorageError as exc:
        if cleanup_warning is not None:
            exc.add_note(cleanup_warning)
        raise
    return cleanup_warning


class _BackupOperationManifest:
    """Append-only, target-scoped ordering evidence for backup-affecting applies."""

    def __init__(self, store: _InventoryBackupStore) -> None:
        self.store = store
        self.directory = store.directory / _MANIFEST_DIRECTORY_NAME
        self._append_warnings: list[str] = []
        self._leftover_temp_count = 0
        self._interrupted_temps: tuple[tuple[Path, Path, bytes], ...] = ()

    def take_warnings(self) -> tuple[str, ...]:
        warnings = tuple(self._append_warnings)
        self._append_warnings.clear()
        return warnings

    def _existing_directory(self) -> os.stat_result | None:
        try:
            self.directory.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError(
                f"cannot inspect backup operation manifest {self.directory}: {exc}"
            ) from exc
        return _validated_private_directory(
            self.directory,
            subject="backup operation manifest directory",
        )

    def _ensure_directory(self) -> None:
        self.store._ensure_directories()
        entries_seen, total_bytes = self.store._namespace_usage()
        try:
            self.directory.lstat()
        except FileNotFoundError:
            if entries_seen >= _MAX_BACKUP_DIRECTORY_ENTRIES:
                raise StorageError(
                    "backup namespace is at capacity before manifest initialization"
                ) from None
            if total_bytes >= _MAX_BACKUP_TOTAL_BYTES:
                raise StorageError("backup namespace byte budget is exhausted") from None
            ensure_private_directory(self.directory)
        except OSError as exc:
            raise StorageError(
                f"cannot inspect backup operation manifest {self.directory}: {exc}"
            ) from exc
        self._existing_directory()
        _sync_manifest_directory(self.store.directory)

    def _event_from_raw(
        self,
        raw: bytes,
        *,
        expected_sequence: int,
        expected_previous: str | None,
        observed_hash: str,
    ) -> InventoryBackupManifestEvent:
        try:
            value = json.loads(raw)
        except (UnicodeError, RecursionError, ValueError) as exc:
            raise StorageError("backup operation manifest event is not canonical JSON") from exc
        if not isinstance(value, dict) or _canonical_manifest_bytes(value) != raw:
            raise StorageError("backup operation manifest event is not canonical JSON")
        required_keys = {
            "details",
            "event_type",
            "operation",
            "operation_id",
            "phase",
            "previous_event_hash",
            "recorded_at",
            "schema_version",
            "sequence",
        }
        if set(value) != required_keys or value["schema_version"] != _MANIFEST_SCHEMA_VERSION:
            raise StorageError("backup operation manifest event has an unsupported schema")
        if value["sequence"] != expected_sequence:
            raise StorageError("backup operation manifest event sequence does not match its path")
        if value["previous_event_hash"] != expected_previous:
            raise StorageError("backup operation manifest hash chain is broken")
        if not isinstance(value["recorded_at"], str) or not _manifest_details_are_safe(
            value["details"]
        ):
            raise StorageError("backup operation manifest event contains unsupported values")
        if value["event_type"] == "genesis":
            if (
                expected_sequence != 0
                or value["phase"] != "completed"
                or value["operation"] is not None
                or value["operation_id"] is not None
            ):
                raise StorageError("backup operation manifest genesis is invalid")
        elif value["event_type"] == "operation":
            if (
                value["phase"] not in _MANIFEST_PHASES
                or value["operation"] not in _MANIFEST_OPERATIONS
                or not isinstance(value["operation_id"], str)
                or re.fullmatch(r"operation-v1:[0-9a-f]{64}", value["operation_id"]) is None
            ):
                raise StorageError("backup operation manifest operation event is invalid")
        else:
            raise StorageError("backup operation manifest event type is invalid")
        return InventoryBackupManifestEvent(
            sequence=value["sequence"],
            event_hash=observed_hash,
            previous_event_hash=value["previous_event_hash"],
            event_type=value["event_type"],
            phase=value["phase"],
            operation_id=value["operation_id"],
            operation=value["operation"],
            recorded_at=value["recorded_at"],
            details=value["details"],
        )

    def _event_from_path(
        self,
        path: Path,
        *,
        expected_sequence: int,
        expected_previous: str | None,
        validated_leftover_event_names: frozenset[str],
    ) -> InventoryBackupManifestEvent:
        match = _MANIFEST_EVENT_FILENAME_PATTERN.fullmatch(path.name)
        if match is None or int(match.group(1)) != expected_sequence:
            raise StorageError("backup operation manifest has a sequence gap or unexpected entry")
        inspected = _inspect_regular_file(path)
        _required_identity(inspected, subject="backup operation manifest event")
        link_count_is_safe = inspected.st_nlink == 1 or (
            inspected.st_nlink == 2 and path.name in validated_leftover_event_names
        )
        if not link_count_is_safe or inspected.st_size > _MAX_MANIFEST_EVENT_BYTES:
            raise StorageError("refusing unsafe backup operation manifest event")
        if os.name == "posix":
            if inspected.st_uid != os.geteuid() or stat.S_IMODE(inspected.st_mode) != 0o600:
                raise StorageError("refusing insecure backup operation manifest event")
        raw = _read_regular_bytes(path)
        observed_hash = _revision(raw)
        if observed_hash.removeprefix("sha256:") != match.group(2):
            raise StorageError("backup operation manifest event does not match its filename hash")
        return self._event_from_raw(
            raw,
            expected_sequence=expected_sequence,
            expected_previous=expected_previous,
            observed_hash=observed_hash,
        )

    def load(self) -> tuple[InventoryBackupManifestEvent, ...]:
        if self._existing_directory() is None:
            self._leftover_temp_count = 0
            self._interrupted_temps = ()
            return ()
        try:
            entries = list(os.scandir(self.directory))
        except OSError as exc:
            raise StorageError(f"cannot list backup operation manifest: {exc}") from exc
        if len(entries) > _MAX_MANIFEST_EVENTS * 2:
            raise StorageError(
                "backup operation manifest exceeds its bounded entry capacity; "
                + _MANIFEST_CAPACITY_REMEDIATION
            )
        event_entries: list[Any] = []
        temp_entries: list[Any] = []
        total_bytes = 0
        for entry in entries:
            if _MANIFEST_EVENT_FILENAME_PATTERN.fullmatch(entry.name):
                event_entries.append(entry)
            elif _MANIFEST_TEMP_FILENAME_PATTERN.fullmatch(entry.name):
                temp_entries.append(entry)
            else:
                raise StorageError("backup operation manifest has an unexpected directory entry")
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise StorageError(
                    f"cannot inspect backup operation manifest entry: {exc}"
                ) from exc
            total_bytes += max(0, details.st_size)
            if total_bytes > _MAX_MANIFEST_TOTAL_BYTES:
                raise StorageError(
                    "backup operation manifest exceeds its bounded byte capacity; "
                    + _MANIFEST_CAPACITY_REMEDIATION
                )
        if len(event_entries) > _MAX_MANIFEST_EVENTS or len(temp_entries) > _MAX_MANIFEST_EVENTS:
            raise StorageError(
                "backup operation manifest exceeds its bounded event capacity; "
                + _MANIFEST_CAPACITY_REMEDIATION
            )

        event_entries_by_name = {entry.name: entry for entry in event_entries}
        validated_leftover_event_names: set[str] = set()
        interrupted_temp_candidates: list[tuple[Path, bytes]] = []
        for entry in temp_entries:
            path = Path(entry.path)
            inspected = _inspect_regular_file(path)
            if inspected.st_nlink not in {1, 2} or inspected.st_size > _MAX_MANIFEST_EVENT_BYTES:
                raise StorageError("refusing unsafe backup operation manifest temporary artifact")
            if os.name == "posix" and (
                inspected.st_uid != os.geteuid() or stat.S_IMODE(inspected.st_mode) != 0o600
            ):
                raise StorageError("refusing insecure backup operation manifest temporary artifact")
            raw = _read_regular_bytes(path)
            try:
                value = json.loads(raw)
            except (UnicodeError, RecursionError, ValueError) as exc:
                raise StorageError(
                    "backup operation manifest temporary artifact is not canonical JSON"
                ) from exc
            if not isinstance(value, dict) or _canonical_manifest_bytes(value) != raw:
                raise StorageError(
                    "backup operation manifest temporary artifact is not canonical JSON"
                )
            sequence = value.get("sequence")
            if type(sequence) is not int or not 0 <= sequence < _MAX_MANIFEST_EVENTS:
                raise StorageError("backup operation manifest temporary artifact is invalid")
            digest = hashlib.sha256(raw).hexdigest()
            event_name = f"event-{sequence:012d}-{digest}.json"
            linked_event = event_entries_by_name.get(event_name)
            if inspected.st_nlink == 1:
                if linked_event is not None:
                    raise StorageError(
                        "refusing unsafe backup operation manifest temporary artifact with an "
                        "unlinked committed event"
                    )
                interrupted_temp_candidates.append((path, raw))
                continue
            if linked_event is None:
                raise StorageError(
                    "backup operation manifest temporary artifact has no committed event"
                )
            try:
                linked_details = linked_event.stat(follow_symlinks=False)
            except OSError as exc:
                raise StorageError(
                    "cannot inspect committed event for manifest temporary artifact"
                ) from exc
            linked_identity_matches = same_file_identity(inspected, linked_details)
            if not linked_identity_matches:
                try:
                    linked_identity_matches = os.path.samefile(path, linked_event.path)
                except OSError:
                    linked_identity_matches = False
            if not linked_identity_matches:
                raise StorageError(
                    "backup operation manifest temporary artifact is not linked to its event"
                )
            validated_leftover_event_names.add(event_name)

        event_entries.sort(key=lambda entry: entry.name)
        events: list[InventoryBackupManifestEvent] = []
        previous: str | None = None
        for sequence, entry in enumerate(event_entries):
            event = self._event_from_path(
                Path(entry.path),
                expected_sequence=sequence,
                expected_previous=previous,
                validated_leftover_event_names=frozenset(validated_leftover_event_names),
            )
            events.append(event)
            previous = event.event_hash
        if len(interrupted_temp_candidates) > 1:
            raise StorageError("refusing unsafe backup operation manifest temporary artifact fork")
        interrupted_temps: list[tuple[Path, Path, bytes]] = []
        interrupted_event: InventoryBackupManifestEvent | None = None
        for path, raw in interrupted_temp_candidates:
            try:
                interrupted_event = self._event_from_raw(
                    raw,
                    expected_sequence=len(events),
                    expected_previous=previous,
                    observed_hash=_revision(raw),
                )
            except StorageError as exc:
                raise StorageError(
                    "refusing unsafe backup operation manifest temporary artifact that does not "
                    "continue the committed chain"
                ) from exc
            digest = hashlib.sha256(raw).hexdigest()
            event_path = self.directory / f"event-{len(events):012d}-{digest}.json"
            interrupted_temps.append((path, event_path, raw))
        if events and events[0].event_type != "genesis":
            raise StorageError("backup operation manifest does not begin with genesis")
        open_operations: dict[str, str] = {}
        for event in events[1:]:
            assert event.operation_id is not None
            assert event.operation is not None
            if event.phase == "prepared":
                if event.operation_id in open_operations:
                    raise StorageError("backup operation manifest repeats an operation preparation")
                open_operations[event.operation_id] = event.operation
            else:
                if open_operations.pop(event.operation_id, None) != event.operation:
                    raise StorageError("backup operation manifest closes an unknown operation")
        if interrupted_event is not None:
            interrupted_is_valid = True
            if not events:
                interrupted_is_valid = interrupted_event.event_type == "genesis"
            elif interrupted_event.phase == "prepared":
                interrupted_is_valid = all(
                    event.operation_id != interrupted_event.operation_id for event in events
                )
            else:
                interrupted_is_valid = (
                    open_operations.get(interrupted_event.operation_id)
                    == interrupted_event.operation
                )
            if not interrupted_is_valid:
                raise StorageError(
                    "refusing unsafe backup operation manifest temporary artifact with an "
                    "unrecognized operation transition"
                )
        self._leftover_temp_count = len(validated_leftover_event_names)
        self._interrupted_temps = tuple(interrupted_temps)
        return tuple(events)

    def _promote_interrupted_temps(self) -> bool:
        """Preserve an exact-next temp as an event before removing its ambiguous name."""

        interrupted_temps = self._interrupted_temps
        if not interrupted_temps:
            return False
        for temp_path, event_path, expected_raw in interrupted_temps:
            inspected = _inspect_regular_file(temp_path)
            if inspected.st_nlink != 1 or _read_regular_bytes(temp_path) != expected_raw:
                raise StorageError("interrupted manifest append changed before promotion")
            if os.name == "posix" and (
                inspected.st_uid != os.geteuid() or stat.S_IMODE(inspected.st_mode) != 0o600
            ):
                raise StorageError("interrupted manifest append became insecure before promotion")
            try:
                os.link(temp_path, event_path, follow_symlinks=False)
            except (OSError, NotImplementedError) as exc:
                raise StorageError("cannot promote validated interrupted manifest append") from exc
            _sync_manifest_directory(self.directory)
            promoted = _inspect_regular_file(event_path)
            retained = _inspect_regular_file(temp_path)
            identity_matches = same_file_identity(promoted, retained)
            if not identity_matches:
                try:
                    identity_matches = os.path.samefile(event_path, temp_path)
                except OSError:
                    identity_matches = False
            if (
                not identity_matches
                or promoted.st_nlink != 2
                or retained.st_nlink != 2
                or _read_regular_bytes(event_path) != expected_raw
            ):
                raise StorageError(
                    "promoted interrupted manifest append failed identity verification"
                )
            try:
                temp_path.unlink()
            except OSError:
                self._append_warnings.append(
                    "interrupted manifest append was preserved as a committed event, but its "
                    "validated temporary hard link could not be removed"
                )
        _sync_manifest_directory(self.directory)
        self._interrupted_temps = ()
        self._append_warnings.append(
            "preserved a validated interrupted manifest append as its canonical event before "
            "retry; no operation outcome was inferred"
        )
        return True

    def _append(
        self,
        *,
        event_type: str,
        phase: str,
        operation_id: str | None,
        operation: str | None,
        details: dict[str, Any],
    ) -> InventoryBackupManifestEvent:
        if not _manifest_details_are_safe(details):
            raise StorageError("refusing unsupported backup operation manifest details")
        self._ensure_directory()
        events = self.load()
        if self._interrupted_temps:
            raise StorageError("interrupted manifest append must be reconciled before append")
        sequence = len(events)
        if sequence >= _MAX_MANIFEST_EVENTS:
            raise StorageError(
                "backup operation manifest is at its bounded event capacity; "
                + _MANIFEST_CAPACITY_REMEDIATION
            )
        previous = events[-1].event_hash if events else None
        value = {
            "details": details,
            "event_type": event_type,
            "operation": operation,
            "operation_id": operation_id,
            "phase": phase,
            "previous_event_hash": previous,
            "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "sequence": sequence,
        }
        raw = _canonical_manifest_bytes(value)
        if len(raw) > _MAX_MANIFEST_EVENT_BYTES:
            raise StorageError("backup operation manifest event exceeds its size limit")
        try:
            existing_bytes = sum(
                entry.stat(follow_symlinks=False).st_size for entry in os.scandir(self.directory)
            )
        except OSError as exc:
            raise StorageError("cannot inspect backup operation manifest capacity") from exc
        if existing_bytes + len(raw) > _MAX_MANIFEST_TOTAL_BYTES:
            raise StorageError(
                "backup operation manifest is at its bounded byte capacity; "
                + _MANIFEST_CAPACITY_REMEDIATION
            )
        digest = hashlib.sha256(raw).hexdigest()
        path = self.directory / f"event-{sequence:012d}-{digest}.json"
        cleanup_warning = _append_manifest_file(path, raw)
        if cleanup_warning is not None:
            self._append_warnings.append(cleanup_warning)
        refreshed = self.load()
        if len(refreshed) != sequence + 1:
            raise StorageError("backup operation manifest append verification failed")
        return refreshed[-1]

    def _require_reserved_capacity(self, event_slots: int) -> None:
        """Fail before mutation unless every required outcome event can still be appended."""

        events = self.load()
        if len(events) + event_slots > _MAX_MANIFEST_EVENTS:
            raise StorageError(
                "backup operation manifest cannot reserve preparation and outcome events; "
                + _MANIFEST_CAPACITY_REMEDIATION
            )
        try:
            existing_bytes = sum(
                entry.stat(follow_symlinks=False).st_size for entry in os.scandir(self.directory)
            )
        except OSError as exc:
            raise StorageError("cannot inspect backup operation manifest capacity") from exc
        if existing_bytes + event_slots * _MAX_MANIFEST_EVENT_BYTES > _MAX_MANIFEST_TOTAL_BYTES:
            raise StorageError(
                "backup operation manifest cannot reserve preparation and outcome bytes; "
                + _MANIFEST_CAPACITY_REMEDIATION
            )

    def ensure_genesis(self) -> None:
        self._ensure_directory()
        events = self.load()
        if self._promote_interrupted_temps():
            events = self.load()
        if events:
            return
        backups, _legacy_count, warnings = self.store.list()
        backup_ids = [backup.backup_id for backup in backups]
        backup_set_revision = _revision(
            "\0".join(("backup-id-set-v1", *backup_ids)).encode("ascii")
        )
        self._append(
            event_type="genesis",
            phase="completed",
            operation_id=None,
            operation=None,
            details={
                "backup_count": len(backup_ids),
                "backup_set_revision": backup_set_revision,
                "history_before_manifest": "unknown",
                "ignored_store_warning_count": len(warnings),
            },
        )

    def prepare(self, operation: str, details: dict[str, Any]) -> str:
        if operation not in _MANIFEST_OPERATIONS:
            raise StorageError(f"unsupported backup operation manifest action: {operation}")
        self.ensure_genesis()
        events = self.load()
        if self._promote_interrupted_temps():
            events = self.load()
        open_ids = {
            event.operation_id
            for event in events
            if event.event_type == "operation" and event.phase == "prepared"
        }
        closed_ids = {
            event.operation_id
            for event in events
            if event.event_type == "operation" and event.phase != "prepared"
        }
        unresolved_ids = sorted(open_ids - closed_ids)
        self._require_reserved_capacity(len(unresolved_ids) + 2)
        for operation_id in unresolved_ids:
            previous = next(event for event in events if event.operation_id == operation_id)
            self.finish(
                operation_id,
                previous.operation or "recover-inventory",
                "uncertain",
                {"outcome_inferred": False, "reason": "prior-apply-ended-without-closure"},
            )
        operation_id = "operation-v1:" + os.urandom(32).hex()
        self._append(
            event_type="operation",
            phase="prepared",
            operation_id=operation_id,
            operation=operation,
            details=details,
        )
        return operation_id

    def finish(
        self,
        operation_id: str,
        operation: str,
        phase: str,
        details: dict[str, Any],
    ) -> None:
        if phase not in {"completed", "aborted", "uncertain"}:
            raise StorageError("invalid backup operation manifest closing phase")
        events = self.load()
        if self._promote_interrupted_temps():
            events = self.load()
        operation_events = [event for event in events if event.operation_id == operation_id]
        if len(operation_events) == 2:
            prepared_event, recorded_outcome = operation_events
            if (
                prepared_event.phase == "prepared"
                and recorded_outcome.operation == operation
                and recorded_outcome.phase == phase
                and recorded_outcome.details == details
            ):
                return
            raise StorageError("backup operation manifest operation already has another outcome")
        if len(operation_events) != 1 or operation_events[0].phase != "prepared":
            raise StorageError("backup operation manifest operation is not open")
        if operation_events[0].operation != operation:
            raise StorageError("backup operation manifest operation type changed")
        self._append(
            event_type="operation",
            phase=phase,
            operation_id=operation_id,
            operation=operation,
            details=details,
        )


def _manifest_for_target(target: Path) -> _BackupOperationManifest:
    return _BackupOperationManifest(_InventoryBackupStore(target))


def _manifest_abort(
    manifest: _BackupOperationManifest | None,
    operation_id: str | None,
    operation: str,
) -> None:
    if manifest is None or operation_id is None:
        return
    try:
        manifest.finish(
            operation_id,
            operation,
            "aborted",
            {"outcome_inferred": False, "reason": "apply-raised-before-receipt"},
        )
        append_warnings = manifest.take_warnings()
        active_error = sys.exception()
        if active_error is not None:
            for warning in append_warnings:
                active_error.add_note(warning)
    except AtReadyError as exc:
        active_error = sys.exception()
        if active_error is not None:
            active_error.add_note(f"backup operation manifest abort recording failed: {exc}")


def _manifest_complete(
    manifest: _BackupOperationManifest,
    operation_id: str,
    operation: str,
    details: dict[str, Any],
    *,
    uncertain: bool = False,
) -> tuple[str, ...]:
    try:
        manifest.finish(
            operation_id,
            operation,
            "uncertain" if uncertain else "completed",
            details,
        )
    except AtReadyError as exc:
        return (
            *manifest.take_warnings(),
            "operation completed, but its backup operation manifest could not be closed: "
            + str(exc),
        )
    return manifest.take_warnings()


def inspect_inventory_backup_manifest(path: Path) -> InventoryBackupManifest:
    """Read validated operation ordering without creating manifest state."""

    target, _active_state, _current, store = _prepare_backup_view(path)
    operation_manifest = _BackupOperationManifest(store)
    events = operation_manifest.load()
    prepared = {
        event.operation_id
        for event in events
        if event.event_type == "operation" and event.phase == "prepared"
    }
    closed = {
        event.operation_id
        for event in events
        if event.event_type == "operation" and event.phase != "prepared"
    }
    unresolved = tuple(sorted(item for item in prepared - closed if item is not None))
    warnings: tuple[str, ...] = ()
    if unresolved:
        warnings = (
            f"{len(unresolved)} prepared operation(s) have no recorded outcome; outcome is unknown",
        )
    if operation_manifest._leftover_temp_count:
        warnings = (
            *warnings,
            f"{operation_manifest._leftover_temp_count} validated manifest temporary hard "
            "link(s) remain after cleanup failure",
        )
    if operation_manifest._interrupted_temps:
        warnings = (
            *warnings,
            f"{len(operation_manifest._interrupted_temps)} validated interrupted manifest "
            "append(s) remain outside the committed event path; no operation outcome was inferred",
        )
    return InventoryBackupManifest(
        target=target,
        namespace=store.namespace,
        initialized=bool(events),
        events=events,
        unresolved_operation_ids=unresolved,
        warnings=warnings,
    )


def _prepare_backup_target(path: Path) -> tuple[Path, InventoryFile, _InventoryBackupStore]:
    target = _canonical_update_target(path)
    _validate_update_target(target)
    current = read_inventory_file(target)
    _require_personal_inventory(current.inventory)
    return target, current, _InventoryBackupStore(target)


def _prepare_backup_view(
    path: Path,
) -> tuple[Path, str, InventoryFile | None, _InventoryBackupStore]:
    """Open the backup namespace even when the active target is missing or invalid."""

    target = _canonical_recovery_target(path)
    _validate_recovery_parent(target)
    try:
        target.lstat()
    except FileNotFoundError:
        return target, "missing", None, _InventoryBackupStore(target)
    except OSError as exc:
        raise ConfigurationError(f"cannot inspect inventory {target}: {exc}") from exc
    _validate_update_target(target)
    raw = _read_regular_bytes(target)
    current, failure = _inventory_file_from_raw(target, raw)
    if failure is not None:
        return target, "invalid", None, _InventoryBackupStore(target)
    assert current is not None
    _require_personal_inventory(current.inventory)
    return target, "valid", current, _InventoryBackupStore(target)


def list_inventory_backups(path: Path) -> InventoryBackupListing:
    """List only validated backups scoped to this exact logical inventory target."""

    target, active_state, current, store = _prepare_backup_view(path)
    records, legacy_count, warnings = store.list()
    active_revision = current.revision if current else None
    return InventoryBackupListing(
        target=target,
        active_state=active_state,
        active_revision=active_revision,
        active_revision_protection=(current.inventory.revision_protection() if current else None),
        namespace=store.namespace,
        backups=tuple(record.summary(active_revision=active_revision) for record in records),
        legacy_unscoped_count=legacy_count,
        warnings=warnings,
    )


def inspect_inventory_backup(path: Path, backup_id: str) -> InventoryBackupInspection:
    """Return a private-note-free comparison for one exact backup ID."""

    target, active_state, current, store = _prepare_backup_view(path)
    backup = store.read(backup_id)
    return InventoryBackupInspection(
        target=target,
        active_state=active_state,
        active_revision=current.revision if current else None,
        active_revision_protection=(current.inventory.revision_protection() if current else None),
        backup=backup.summary(active_revision=current.revision if current else None),
        active_snapshot=_snapshot_inventory(current.inventory) if current else None,
        backup_snapshot=_snapshot_inventory(backup.inventory),
        comparison=(
            _inventory_comparison(current.inventory, backup.inventory) if current else None
        ),
    )


def plan_add_resource(
    path: Path,
    resource: Resource,
    *,
    defaulted_fields: tuple[str, ...] = (),
) -> InventoryAddPlan:
    """Return a redacted add preview without writing or creating anything."""

    path = _canonical_update_target(path)
    _validate_update_target(path)
    current = read_inventory_file(path)
    candidate = _candidate_inventory(current.inventory, resource)
    candidate_yaml = dumps_yaml(candidate.model_dump(mode="json", exclude_none=True))
    reparsed = InventoryCatalog.from_text(candidate_yaml).inventory
    if reparsed != candidate:
        raise ConfigurationError("canonical inventory serialization did not round-trip")
    target_details = _inspect_regular_file(path)
    try:
        parent_details = path.parent.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {path.parent}: {exc}") from exc
    return InventoryAddPlan(
        target=current.path,
        original_revision=current.revision,
        candidate_revision=_revision(candidate_yaml.encode("utf-8")),
        resource=resource,
        candidate_yaml=candidate_yaml,
        resource_count_before=len(current.inventory.resources),
        defaulted_fields=tuple(sorted(defaulted_fields)),
        target_identity=_required_identity(target_details, subject="inventory target"),
        parent_identity=_required_identity(parent_details, subject="inventory directory"),
        revision_protection=current.inventory.revision_protection(),
    )


def plan_replace_resource(
    path: Path,
    resource: Resource,
    *,
    defaulted_fields: tuple[str, ...] = (),
) -> InventoryReplacePlan:
    """Return a redacted full-resource replacement preview without writing state."""

    path = _canonical_update_target(path)
    _validate_update_target(path)
    current = read_inventory_file(path)
    candidate, previous = _replacement_inventory(current.inventory, resource)
    candidate_yaml = dumps_yaml(candidate.model_dump(mode="json", exclude_none=True))
    reparsed = InventoryCatalog.from_text(candidate_yaml).inventory
    if reparsed != candidate:
        raise ConfigurationError("canonical inventory serialization did not round-trip")
    candidate_revision = _revision(candidate_yaml.encode("utf-8"))
    if candidate_revision == current.revision:
        raise ConfigurationError(f"resource {resource.id!r} replacement does not change inventory")
    target_details = _inspect_regular_file(path)
    try:
        parent_details = path.parent.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {path.parent}: {exc}") from exc
    return InventoryReplacePlan(
        target=current.path,
        original_revision=current.revision,
        candidate_revision=candidate_revision,
        previous_resource=previous,
        resource=resource,
        candidate_yaml=candidate_yaml,
        resource_count=len(current.inventory.resources),
        defaulted_fields=tuple(sorted(defaulted_fields)),
        target_identity=_required_identity(target_details, subject="inventory target"),
        parent_identity=_required_identity(parent_details, subject="inventory directory"),
        revision_protection=current.inventory.revision_protection(),
    )


def plan_remove_resource(path: Path, resource_id: str) -> InventoryRemovePlan:
    """Return a redacted single-resource removal preview without writing state."""

    resource_id = _validated_resource_id(resource_id)
    path = _canonical_update_target(path)
    _validate_update_target(path)
    current = read_inventory_file(path)
    candidate, removed = _inventory_without_resource(current.inventory, resource_id)
    candidate_yaml = dumps_yaml(candidate.model_dump(mode="json", exclude_none=True))
    reparsed = InventoryCatalog.from_text(candidate_yaml).inventory
    if reparsed != candidate:
        raise ConfigurationError("canonical inventory serialization did not round-trip")
    target_details = _inspect_regular_file(path)
    try:
        parent_details = path.parent.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {path.parent}: {exc}") from exc
    return InventoryRemovePlan(
        target=current.path,
        original_revision=current.revision,
        candidate_revision=_revision(candidate_yaml.encode("utf-8")),
        resource=removed,
        candidate_yaml=candidate_yaml,
        resource_count_before=len(current.inventory.resources),
        target_identity=_required_identity(target_details, subject="inventory target"),
        parent_identity=_required_identity(parent_details, subject="inventory directory"),
        revision_protection=current.inventory.revision_protection(),
    )


def plan_inventory_annotation(path: Path, private_notes: str | None) -> InventoryAnnotationPlan:
    """Return a value-free root annotation preview without writing state."""

    path = _canonical_update_target(path)
    _validate_update_target(path)
    current = read_inventory_file(path)
    _require_personal_inventory(current.inventory)
    if current.inventory.private_notes == private_notes:
        raise ConfigurationError("inventory annotation does not change inventory")
    value = current.inventory.model_dump(mode="json")
    value["private_notes"] = private_notes
    try:
        candidate = Inventory.model_validate(value)
    except ValidationError as exc:
        raise _format_validation_errors(exc, subject="inventory") from exc
    candidate_yaml = dumps_yaml(candidate.model_dump(mode="json", exclude_none=True))
    reparsed = InventoryCatalog.from_text(candidate_yaml).inventory
    if reparsed != candidate:
        raise ConfigurationError("canonical inventory serialization did not round-trip")
    candidate_revision = _revision(candidate_yaml.encode("utf-8"))
    if candidate_revision == current.revision:
        raise ConfigurationError("inventory annotation does not change inventory")
    target_details = _inspect_regular_file(path)
    try:
        parent_details = path.parent.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {path.parent}: {exc}") from exc
    return InventoryAnnotationPlan(
        target=current.path,
        original_revision=current.revision,
        candidate_revision=candidate_revision,
        private_notes=private_notes,
        candidate_yaml=candidate_yaml,
        private_notes_effect=_private_note_effect(current.inventory.private_notes, private_notes),
        target_identity=_required_identity(target_details, subject="inventory target"),
        parent_identity=_required_identity(parent_details, subject="inventory directory"),
        revision_protection=current.inventory.revision_protection(),
    )


def _acquire_lock(target: Path) -> tuple[int, Path]:
    lock_path = target.with_name(f".{target.name}.lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise StorageError(f"cannot open inventory update lock {lock_path}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise StorageError(f"inventory update lock is not a regular file: {lock_path}")
        if not file_identity_is_known(opened):
            raise StorageError(f"cannot verify inventory update lock identity: {lock_path}")
        if opened.st_nlink != 1:
            raise StorageError(f"refusing hard-linked inventory update lock: {lock_path}")
        if os.name == "posix":
            if opened.st_uid != os.geteuid():
                raise StorageError(f"refusing unsafe inventory update lock: {lock_path}")
            mode = stat.S_IMODE(opened.st_mode)
            if mode != 0o600:
                raise StorageError(
                    f"refusing insecure inventory update lock mode {oct(mode)}: {lock_path}"
                )
            try:
                if darwin_fd_has_extended_acl(descriptor):
                    raise StorageError(
                        f"refusing inventory update lock with a macOS extended ACL: {lock_path}"
                    )
            except OSError:
                raise StorageError(
                    f"cannot verify inventory update lock extended access controls: {lock_path}"
                ) from None
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                if darwin_fd_has_extended_acl(descriptor):
                    raise StorageError(
                        f"inventory update lock gained a macOS extended ACL: {lock_path}"
                    )
            except OSError:
                raise StorageError(
                    f"cannot recheck inventory update lock extended access controls: {lock_path}"
                ) from None
        elif os.name == "nt":
            import msvcrt

            if opened.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            raise StorageError(f"unsupported inventory lock platform: {os.name}")
    except BlockingIOError as exc:
        os.close(descriptor)
        raise StorageError(f"another inventory update is in progress: {lock_path}") from exc
    except OSError as exc:
        os.close(descriptor)
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            raise StorageError(f"another inventory update is in progress: {lock_path}") from exc
        raise StorageError(f"cannot lock inventory update lock {lock_path}: {exc}") from exc
    except StorageError:
        os.close(descriptor)
        raise
    return descriptor, lock_path


def _release_lock(descriptor: int, lock_path: Path) -> None:
    failure: StorageError | None = None
    opened: os.stat_result | None = None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not file_identity_is_known(opened):
            raise StorageError(f"cannot verify inventory update lock identity: {lock_path}")
        if os.name == "posix":
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        elif os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            raise StorageError(f"unsupported inventory lock platform: {os.name}")
    except StorageError as exc:
        failure = exc
    except FileNotFoundError as exc:
        failure = StorageError(f"inventory update lock disappeared during operation: {lock_path}")
        failure.__cause__ = exc
    except OSError as exc:
        failure = StorageError(f"inventory update finished but lock cleanup failed: {exc}")
        failure.__cause__ = exc
    finally:
        try:
            os.close(descriptor)
        except OSError as exc:
            if failure is None:
                failure = StorageError(f"inventory update lock descriptor cleanup failed: {exc}")
                failure.__cause__ = exc
            else:
                failure.add_note(f"lock descriptor cleanup also failed: {exc}")
    if failure is None:
        try:
            inspected = lock_path.lstat()
        except FileNotFoundError as exc:
            failure = StorageError(
                f"inventory update lock disappeared during operation: {lock_path}"
            )
            failure.__cause__ = exc
        except OSError as exc:
            failure = StorageError(f"inventory update finished but lock cleanup failed: {exc}")
            failure.__cause__ = exc
        else:
            assert opened is not None
            if not stat.S_ISREG(inspected.st_mode):
                failure = StorageError(
                    f"inventory update lock is no longer a regular file: {lock_path}"
                )
            elif not same_file_identity(opened, inspected):
                failure = StorageError(
                    f"inventory update lock changed during operation: {lock_path}"
                )
    if failure is not None:
        raise failure


def _cleanup_after_update(
    temp_path: Path | None,
    descriptor: int,
    lock_path: Path,
) -> tuple[str, ...]:
    """Clean artifacts without hiding the failure that caused cleanup."""

    active_error = sys.exception()
    cleanup_errors: list[str] = []
    if temp_path is not None:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError as exc:
            cleanup_errors.append(f"temporary-file cleanup failed: {exc}")
    try:
        _release_lock(descriptor, lock_path)
    except StorageError as exc:
        cleanup_errors.append(str(exc))
    if not cleanup_errors:
        return ()
    detail = "; ".join(cleanup_errors)
    if active_error is not None:
        active_error.add_note(detail)
    return tuple(cleanup_errors)


def _backup_current(target: Path, raw: bytes) -> tuple[str, Path]:
    return _InventoryBackupStore(target).save(raw)


def _populate_candidate_descriptor(descriptor: int, content: str | bytes) -> StorageError | None:
    """Write candidate bytes without raising an exception frame that retains them."""

    raw: bytes | None = None
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        try:
            has_extended_acl = darwin_fd_has_extended_acl(descriptor)
        except OSError:
            return StorageError("cannot verify temporary-file extended access controls")
        if has_extended_acl:
            return StorageError("refusing inventory temporary file with a macOS extended ACL")
        raw = content.encode("utf-8") if isinstance(content, str) else content
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                return StorageError("cannot write complete inventory update temporary file")
            written += count
        os.fsync(descriptor)
        try:
            has_extended_acl = darwin_fd_has_extended_acl(descriptor)
        except OSError:
            return StorageError("cannot recheck temporary-file extended access controls")
        if has_extended_acl:
            return StorageError("inventory temporary file gained a macOS extended ACL")
    except KeyboardInterrupt:
        del raw
        del content
        raise
    except (OSError, ValueError):
        return StorageError("cannot write inventory update temporary file")
    return None


def _scrub_close_unlink_temp(
    descriptor: int,
    temp_path: Path,
    error: BaseException,
    *,
    descriptor_note: str,
    unlink_note: str,
) -> None:
    """Best-effort scrub one uncommitted temporary inode before propagating an interrupt."""

    try:
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
    except BaseException:
        error.add_note("temporary-file content cleanup could not be fully synced")
    try:
        os.close(descriptor)
    except BaseException:
        error.add_note(descriptor_note)
    try:
        temp_path.unlink(missing_ok=True)
    except BaseException:
        error.add_note(unlink_note)


def _write_candidate_temp(target: Path, content: str | bytes) -> Path:
    descriptor: int | None = None
    raw_path: str | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            text=False,
        )
    except OSError:
        pass
    if descriptor is None or raw_path is None:
        failure = StorageError("cannot create inventory update temporary file")
        del content
        raise failure

    temp_path = Path(raw_path)
    try:
        failure = _populate_candidate_descriptor(descriptor, content)
    except BaseException as exc:
        _scrub_close_unlink_temp(
            descriptor,
            temp_path,
            exc,
            descriptor_note="temporary descriptor cleanup failed",
            unlink_note="temporary-file cleanup failed",
        )
        del content
        raise
    if failure is not None:
        try:
            os.ftruncate(descriptor, 0)
            os.fsync(descriptor)
        except OSError:
            failure.add_note("temporary-file content cleanup could not be fully synced")
    try:
        os.close(descriptor)
    except OSError:
        if failure is None:
            failure = StorageError("cannot close inventory update temporary file")
        else:
            failure.add_note("temporary descriptor cleanup failed")
    if failure is not None:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            failure.add_note("temporary-file cleanup failed")
        del content
        raise failure
    return temp_path


def _fsync_directory(path: Path) -> bool:
    if os.name != "posix" or not hasattr(os, "O_DIRECTORY"):
        return False
    descriptor: int | None = None
    synced = True
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(descriptor)
    except OSError:
        synced = False
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                synced = False
    return synced


def _commit_inventory_replacement(
    plan: _InventoryReplacementPlan,
    *,
    refresh: Callable[[], _InventoryReplacementPlan],
    changed_message: str,
    operation: str,
) -> InventoryUpdateReceipt:
    """Durably back up and atomically replace one exact validated inventory candidate."""

    _validate_update_target(plan.target)
    lock_descriptor, lock_path = _acquire_lock(plan.target)
    temp_path: Path | None = None
    receipt: InventoryUpdateReceipt | None = None
    cleanup_warnings: tuple[str, ...] = ()
    manifest: _BackupOperationManifest | None = None
    manifest_operation_id: str | None = None
    replacement_started = False
    backup_id: str | None = None
    try:
        current = read_inventory_file(plan.target)
        if current.revision != plan.original_revision:
            raise StorageError(
                "inventory changed after preview; no update was applied (revision conflict)"
            )
        refreshed = refresh()
        if refreshed != plan:
            raise StorageError(changed_message)

        manifest = _manifest_for_target(plan.target)
        manifest_operation_id = manifest.prepare(
            operation,
            {
                "candidate_revision": refreshed.candidate_revision,
                "original_revision": plan.original_revision,
            },
        )
        backup_id, backup_path = _backup_current(plan.target, current.raw)
        temp_path = _write_candidate_temp(plan.target, refreshed.candidate_raw)
        rechecked = read_inventory_file(plan.target)
        if rechecked.revision != plan.original_revision:
            raise StorageError(
                "inventory changed during update; no update was applied (revision conflict)"
            )
        rechecked_target = _inspect_regular_file(plan.target)
        try:
            rechecked_parent = plan.target.parent.lstat()
        except OSError as exc:
            raise StorageError(
                f"cannot recheck inventory directory identity {plan.target.parent}: {exc}"
            ) from exc
        if (
            _required_identity(rechecked_target, subject="inventory target") != plan.target_identity
            or _required_identity(rechecked_parent, subject="inventory directory")
            != plan.parent_identity
        ):
            raise StorageError(
                "inventory target identity changed during update; no update was applied"
            )
        try:
            os.replace(temp_path, plan.target)
        except OSError as exc:
            raise StorageError(f"cannot atomically replace inventory {plan.target}: {exc}") from exc
        replacement_started = True
        temp_path = None
        directory_synced = _fsync_directory(plan.target.parent)
        observed_revision: str | None = None
        replacement_verified = False
        warnings: list[str] = []
        try:
            applied = read_inventory_file(plan.target)
            observed_revision = applied.revision
            replacement_verified = observed_revision == refreshed.candidate_revision
            if not replacement_verified:
                warnings.append(
                    "inventory was replaced, but its observed revision differs from the candidate; "
                    "inspect the target and backup before another update"
                )
        except (AtReadyError, OSError) as exc:
            warnings.append(
                "inventory was replaced, but post-replacement verification failed: " + str(exc)
            )
        receipt = InventoryUpdateReceipt(
            target=plan.target,
            previous_revision=plan.original_revision,
            candidate_revision=refreshed.candidate_revision,
            revision=observed_revision,
            backup_id=backup_id,
            backup_path=backup_path,
            directory_synced=directory_synced,
            replacement_verified=replacement_verified,
            warnings=tuple(warnings),
            operation=operation,
        )
        manifest_warnings = _manifest_complete(
            manifest,
            manifest_operation_id,
            operation,
            {
                "candidate_revision": refreshed.candidate_revision,
                "directory_synced": directory_synced,
                "observed_revision": observed_revision,
                "replacement_verified": replacement_verified,
                "safety_backup_id": backup_id,
            },
            uncertain=(
                not replacement_verified
                or bool(warnings)
                or (os.name == "posix" and not directory_synced)
            ),
        )
        if manifest_warnings:
            receipt = replace(receipt, warnings=(*receipt.warnings, *manifest_warnings))
    except Exception as exc:
        if replacement_started and manifest is not None and manifest_operation_id is not None:
            try:
                manifest_warnings = _manifest_complete(
                    manifest,
                    manifest_operation_id,
                    operation,
                    {
                        "candidate_revision": plan.candidate_revision,
                        "outcome_inferred": False,
                        "reason": "apply-raised-after-replacement-started",
                        "replacement_started": True,
                        "safety_backup_id": backup_id,
                    },
                    uncertain=True,
                )
                for warning in manifest_warnings:
                    exc.add_note(warning)
            except Exception as manifest_exc:
                exc.add_note(
                    "backup operation manifest uncertain recording failed: " + str(manifest_exc)
                )
            exc.add_note(
                "inventory replacement started before this failure; inspect the target and "
                "safety backup before retrying"
            )
        else:
            _manifest_abort(manifest, manifest_operation_id, operation)
        raise
    finally:
        cleanup_warnings = _cleanup_after_update(temp_path, lock_descriptor, lock_path)
    assert receipt is not None
    if cleanup_warnings:
        receipt = replace(receipt, warnings=(*receipt.warnings, *cleanup_warnings))
    return receipt


def _add_replacement_plan(plan: InventoryAddPlan) -> _InventoryReplacementPlan:
    return _InventoryReplacementPlan(
        target=plan.target,
        original_revision=plan.original_revision,
        candidate_revision=plan.candidate_revision,
        candidate_raw=plan.candidate_yaml.encode("utf-8"),
        target_identity=plan.target_identity,
        parent_identity=plan.parent_identity,
    )


def _resource_replace_replacement_plan(plan: InventoryReplacePlan) -> _InventoryReplacementPlan:
    return _InventoryReplacementPlan(
        target=plan.target,
        original_revision=plan.original_revision,
        candidate_revision=plan.candidate_revision,
        candidate_raw=plan.candidate_yaml.encode("utf-8"),
        target_identity=plan.target_identity,
        parent_identity=plan.parent_identity,
    )


def _resource_remove_replacement_plan(plan: InventoryRemovePlan) -> _InventoryReplacementPlan:
    return _InventoryReplacementPlan(
        target=plan.target,
        original_revision=plan.original_revision,
        candidate_revision=plan.candidate_revision,
        candidate_raw=plan.candidate_yaml.encode("utf-8"),
        target_identity=plan.target_identity,
        parent_identity=plan.parent_identity,
    )


def _annotation_replacement_plan(plan: InventoryAnnotationPlan) -> _InventoryReplacementPlan:
    return _InventoryReplacementPlan(
        target=plan.target,
        original_revision=plan.original_revision,
        candidate_revision=plan.candidate_revision,
        candidate_raw=plan.candidate_yaml.encode("utf-8"),
        target_identity=plan.target_identity,
        parent_identity=plan.parent_identity,
    )


def commit_inventory_annotation(
    plan: InventoryAnnotationPlan,
    *,
    expected_revision: str,
    expected_plan: str,
) -> InventoryUpdateReceipt:
    """Apply one root annotation plan through the shared replacement engine."""

    if expected_revision != plan.original_revision:
        raise ConfigurationError(
            "--expect-revision does not match this preview; preview the change again"
        )
    if expected_plan != plan.plan_token:
        raise ConfigurationError(
            "--expect-plan does not match this preview; preview the change again"
        )

    def refresh() -> _InventoryReplacementPlan:
        refreshed = plan_inventory_annotation(plan.target, plan.private_notes)
        if refreshed.candidate_revision != plan.candidate_revision:
            raise StorageError("inventory candidate changed after preview; no update was applied")
        if (
            refreshed.target_identity != plan.target_identity
            or refreshed.parent_identity != plan.parent_identity
        ):
            raise StorageError(
                "inventory target identity changed after preview; no update was applied"
            )
        return _annotation_replacement_plan(refreshed)

    return _commit_inventory_replacement(
        _annotation_replacement_plan(plan),
        refresh=refresh,
        changed_message="inventory candidate changed after preview; no update was applied",
        operation="annotate-inventory",
    )


def commit_add_resource(
    plan: InventoryAddPlan,
    *,
    expected_revision: str,
    expected_plan: str,
) -> InventoryUpdateReceipt:
    """Apply an add plan only when the exact previewed bytes are still current."""

    if expected_revision != plan.original_revision:
        raise ConfigurationError(
            "--expect-revision does not match this preview; preview the change again"
        )
    if expected_plan != plan.plan_token:
        raise ConfigurationError(
            "--expect-plan does not match this preview; preview the change again"
        )

    def refresh() -> _InventoryReplacementPlan:
        refreshed = plan_add_resource(
            plan.target,
            plan.resource,
            defaulted_fields=plan.defaulted_fields,
        )
        if refreshed.candidate_revision != plan.candidate_revision:
            raise StorageError("inventory candidate changed after preview; no update was applied")
        if (
            refreshed.target_identity != plan.target_identity
            or refreshed.parent_identity != plan.parent_identity
        ):
            raise StorageError(
                "inventory target identity changed after preview; no update was applied"
            )
        return _add_replacement_plan(refreshed)

    return _commit_inventory_replacement(
        _add_replacement_plan(plan),
        refresh=refresh,
        changed_message="inventory candidate changed after preview; no update was applied",
        operation="add-resource",
    )


def commit_replace_resource(
    plan: InventoryReplacePlan,
    *,
    expected_revision: str,
    expected_plan: str,
) -> InventoryUpdateReceipt:
    """Apply a replacement only when the exact redacted preview remains current."""

    if expected_revision != plan.original_revision:
        raise ConfigurationError(
            "--expect-revision does not match this preview; preview the change again"
        )
    if expected_plan != plan.plan_token:
        raise ConfigurationError(
            "--expect-plan does not match this preview; preview the change again"
        )

    def refresh() -> _InventoryReplacementPlan:
        refreshed = plan_replace_resource(
            plan.target,
            plan.resource,
            defaulted_fields=plan.defaulted_fields,
        )
        if refreshed.candidate_revision != plan.candidate_revision:
            raise StorageError("inventory candidate changed after preview; no update was applied")
        if (
            refreshed.target_identity != plan.target_identity
            or refreshed.parent_identity != plan.parent_identity
        ):
            raise StorageError(
                "inventory target identity changed after preview; no update was applied"
            )
        return _resource_replace_replacement_plan(refreshed)

    return _commit_inventory_replacement(
        _resource_replace_replacement_plan(plan),
        refresh=refresh,
        changed_message="inventory candidate changed after preview; no update was applied",
        operation="replace-resource",
    )


def commit_remove_resource(
    plan: InventoryRemovePlan,
    *,
    expected_revision: str,
    expected_plan: str,
) -> InventoryUpdateReceipt:
    """Apply a removal only when the exact redacted preview remains current."""

    if expected_revision != plan.original_revision:
        raise ConfigurationError(
            "--expect-revision does not match this preview; preview the change again"
        )
    if expected_plan != plan.plan_token:
        raise ConfigurationError(
            "--expect-plan does not match this preview; preview the change again"
        )

    def refresh() -> _InventoryReplacementPlan:
        refreshed = plan_remove_resource(plan.target, plan.resource.id)
        if refreshed.candidate_revision != plan.candidate_revision:
            raise StorageError("inventory candidate changed after preview; no update was applied")
        if (
            refreshed.target_identity != plan.target_identity
            or refreshed.parent_identity != plan.parent_identity
        ):
            raise StorageError(
                "inventory target identity changed after preview; no update was applied"
            )
        return _resource_remove_replacement_plan(refreshed)

    return _commit_inventory_replacement(
        _resource_remove_replacement_plan(plan),
        refresh=refresh,
        changed_message="inventory candidate changed after preview; no update was applied",
        operation="remove-resource",
    )


def plan_inventory_recovery(path: Path, backup_id: str) -> InventoryRecoveryPlan:
    """Preview recovery from one exact backup when the active target is absent or invalid."""

    active = _recovery_active_state(path)
    store = _InventoryBackupStore(active.target)
    backup = store.read(backup_id)
    return InventoryRecoveryPlan(
        target=active.target,
        active_state=active.state,
        active_fingerprint=active.fingerprint,
        active_raw=active.raw,
        candidate_revision=backup.backup_id,
        candidate_revision_protection=backup.inventory.revision_protection(),
        source_backup_id=backup.backup_id,
        source_backup_path=backup.path,
        candidate_raw=backup.raw,
        parent_identity=active.parent_identity,
        target_identity=active.target_identity,
        backup_directory_identity=backup.directory_identity,
        source_backup_identity=backup.file_identity,
        candidate_snapshot=_snapshot_inventory(backup.inventory),
    )


def _save_recovery_quarantine(
    target: Path,
    raw: bytes,
) -> tuple[str, Path]:
    """Persist displaced invalid bytes outside the restorable backup namespace."""

    # Retain the persisted v1 name so previously displaced bytes stay visible
    # to the recovery lifecycle after the product rename.
    root = target.parent / ".quartermaster-quarantine"
    directory = root / _backup_namespace(target)
    ensure_private_directory(root)
    _validated_private_directory(root, subject="recovery quarantine root")
    ensure_private_directory(directory)
    _validated_private_directory(directory, subject="target recovery quarantine directory")
    entries_seen = 0
    total_bytes = 0
    try:
        iterator = os.scandir(directory)
    except OSError as exc:
        raise StorageError(f"cannot inspect recovery quarantine {directory}: {exc}") from exc
    with iterator:
        for entry in iterator:
            entries_seen += 1
            if entries_seen > _MAX_BACKUP_DIRECTORY_ENTRIES:
                raise StorageError("recovery quarantine exceeds its bounded entry capacity")
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise StorageError(f"cannot inspect recovery quarantine entry: {exc}") from exc
            total_bytes += max(0, details.st_size)
            if total_bytes > _MAX_BACKUP_TOTAL_BYTES:
                raise StorageError("recovery quarantine exceeds its bounded byte capacity")
    if entries_seen >= _MAX_BACKUP_DIRECTORY_ENTRIES:
        raise StorageError("recovery quarantine is at its bounded entry capacity")
    if total_bytes + len(raw) > _MAX_BACKUP_TOTAL_BYTES:
        raise StorageError("recovery quarantine is at its bounded byte capacity")
    temp_path = _write_candidate_temp(directory / "invalid", raw)
    quarantine_id: str | None = None
    quarantine_path: Path | None = None
    try:
        for _attempt in range(8):
            token = os.urandom(32).hex()
            candidate = directory / f"invalid-{token}.bin"
            try:
                os.link(temp_path, candidate, follow_symlinks=False)
            except FileExistsError:
                continue
            except (OSError, NotImplementedError) as exc:
                raise StorageError(f"cannot commit recovery quarantine: {exc}") from exc
            quarantine_id = "quarantine-v1:" + token
            quarantine_path = candidate
            break
        if quarantine_path is None:
            raise StorageError("cannot allocate an opaque recovery quarantine ID")
        temp_path.unlink()
        temp_path = None
        assert quarantine_id is not None
        inspected = _inspect_regular_file(quarantine_path)
        if inspected.st_nlink != 1:
            raise StorageError("refusing hard-linked recovery quarantine artifact")
        if os.name == "posix":
            if inspected.st_uid != os.geteuid() or stat.S_IMODE(inspected.st_mode) != 0o600:
                raise StorageError("refusing insecure recovery quarantine artifact")
        if _read_regular_bytes(quarantine_path) != raw:
            raise StorageError("recovery quarantine verification failed")
        if os.name == "posix":
            for sync_target in (directory, root, target.parent):
                if not _fsync_directory(sync_target):
                    raise StorageError(f"cannot sync recovery quarantine state: {sync_target}")
    except Exception as exc:
        cleanup_failure: OSError | None = None
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                cleanup_failure = cleanup_exc
        if quarantine_id is None or quarantine_path is None:
            if cleanup_failure is not None:
                exc.add_note("recovery quarantine temporary-file cleanup also failed")
            raise
        failure = _CommittedQuarantineError(
            str(exc),
            quarantine_id=quarantine_id,
            quarantine_path=quarantine_path,
        )
        if cleanup_failure is not None:
            failure.add_note(
                "recovery quarantine temporary artifact may also remain at " + str(temp_path)
            )
        raise failure from exc
    assert quarantine_id is not None
    assert quarantine_path is not None
    return quarantine_id, quarantine_path


def _commit_missing_recovery_candidate(
    temp_path: Path,
    target: Path,
) -> tuple[Path | None, str | None]:
    """Atomically install a missing-target candidate without clobbering a new entry."""

    try:
        os.link(temp_path, target, follow_symlinks=False)
    except FileExistsError as exc:
        raise StorageError(
            "recovery target appeared during apply; no recovery was applied"
        ) from exc
    except (OSError, NotImplementedError) as exc:
        raise StorageError(
            f"cannot atomically recover missing inventory {target} without overwriting: {exc}"
        ) from exc
    try:
        temp_path.unlink()
    except OSError:
        return temp_path, (
            "inventory was recovered without overwriting, but its temporary hard link could not "
            "be removed immediately"
        )
    return None, None


def commit_inventory_recovery(
    plan: InventoryRecoveryPlan,
    *,
    expected_state: str,
    expected_plan: str,
) -> InventoryRecoveryReceipt:
    """Recover an absent or invalid target after exact state and plan approval."""

    if expected_state != plan.state_token:
        raise ConfigurationError(
            "--expect-state does not match this preview; preview the recovery again"
        )
    if expected_plan != plan.plan_token:
        raise ConfigurationError(
            "--expect-plan does not match this preview; preview the recovery again"
        )
    _validate_recovery_parent(plan.target)
    lock_descriptor, lock_path = _acquire_lock(plan.target)
    temp_path: Path | None = None
    receipt: InventoryRecoveryReceipt | None = None
    cleanup_warnings: tuple[str, ...] = ()
    manifest: _BackupOperationManifest | None = None
    manifest_operation_id: str | None = None
    quarantine_id: str | None = None
    quarantine_path: Path | None = None
    replacement_started = False
    try:
        refreshed = plan_inventory_recovery(plan.target, plan.source_backup_id)
        if refreshed.plan_token != plan.plan_token:
            raise StorageError(
                "recovery target or source backup changed after preview; no recovery was applied"
            )
        manifest = _manifest_for_target(refreshed.target)
        manifest_operation_id = manifest.prepare(
            "recover-inventory",
            {
                "candidate_revision": refreshed.candidate_revision,
                "previous_state": refreshed.active_state,
                "source_backup_id": refreshed.source_backup_id,
            },
        )
        if refreshed.active_state == "invalid":
            assert refreshed.active_raw is not None
            try:
                quarantine_id, quarantine_path = _save_recovery_quarantine(
                    refreshed.target,
                    refreshed.active_raw,
                )
            except _CommittedQuarantineError as exc:
                quarantine_id = exc.quarantine_id
                quarantine_path = exc.quarantine_path
                raise
        temp_path = _write_candidate_temp(refreshed.target, refreshed.candidate_raw)
        final_check = plan_inventory_recovery(refreshed.target, refreshed.source_backup_id)
        if final_check.plan_token != refreshed.plan_token:
            raise StorageError(
                "recovery target or source backup changed during apply; no recovery was applied"
            )
        warnings: list[str] = []
        if refreshed.active_state == "missing":
            temp_path, cleanup_warning = _commit_missing_recovery_candidate(
                temp_path,
                refreshed.target,
            )
            replacement_started = True
            if cleanup_warning is not None:
                warnings.append(cleanup_warning)
        else:
            try:
                os.replace(temp_path, refreshed.target)
            except OSError as exc:
                raise StorageError(
                    f"cannot atomically recover inventory {refreshed.target}: {exc}"
                ) from exc
            replacement_started = True
            temp_path = None
        directory_synced = _fsync_directory(refreshed.target.parent)
        observed_revision: str | None = None
        replacement_verified = False
        try:
            applied = read_inventory_file(refreshed.target)
            observed_revision = applied.revision
            replacement_verified = observed_revision == refreshed.candidate_revision
            if not replacement_verified:
                warnings.append(
                    "inventory was recovered, but its observed revision differs from the source"
                )
        except (AtReadyError, OSError) as exc:
            warnings.append(
                "inventory was recovered, but post-recovery verification failed: " + str(exc)
            )
        receipt = InventoryRecoveryReceipt(
            target=refreshed.target,
            previous_state=refreshed.active_state,
            restored_revision=refreshed.candidate_revision,
            observed_revision=observed_revision,
            source_backup_id=refreshed.source_backup_id,
            source_backup_path=refreshed.source_backup_path,
            quarantine_id=quarantine_id,
            quarantine_path=quarantine_path,
            directory_synced=directory_synced,
            replacement_verified=replacement_verified,
            warnings=tuple(warnings),
        )
        manifest_warnings = _manifest_complete(
            manifest,
            manifest_operation_id,
            "recover-inventory",
            {
                "directory_synced": directory_synced,
                "observed_revision": observed_revision,
                "quarantine_created": quarantine_id is not None,
                "replacement_verified": replacement_verified,
                "restored_revision": refreshed.candidate_revision,
                "source_backup_id": refreshed.source_backup_id,
            },
            uncertain=(
                not replacement_verified
                or bool(warnings)
                or (os.name == "posix" and not directory_synced)
            ),
        )
        if manifest_warnings:
            receipt = replace(receipt, warnings=(*receipt.warnings, *manifest_warnings))
    except Exception as exc:
        if replacement_started or (quarantine_id is not None and quarantine_path is not None):
            if manifest is not None and manifest_operation_id is not None:
                try:
                    manifest.finish(
                        manifest_operation_id,
                        "recover-inventory",
                        "uncertain",
                        {
                            "outcome_inferred": False,
                            "quarantine_created": quarantine_id is not None,
                            "quarantine_id": quarantine_id,
                            "replacement_started": replacement_started,
                            "reason": (
                                "apply-raised-after-replacement-started"
                                if replacement_started
                                else "apply-raised-after-quarantine"
                            ),
                        },
                    )
                    for warning in manifest.take_warnings():
                        exc.add_note(warning)
                except AtReadyError as manifest_exc:
                    exc.add_note(
                        "backup operation manifest recovery-side-effect recording failed: "
                        + str(manifest_exc)
                    )
            if quarantine_path is not None:
                exc.add_note(
                    "invalid inventory bytes were retained in recovery quarantine at "
                    f"{quarantine_path}; review recovery state before removing that file manually"
                )
            if replacement_started:
                exc.add_note(
                    "inventory replacement started before the failure; inspect the target and "
                    "manifest before retrying"
                )
        else:
            _manifest_abort(manifest, manifest_operation_id, "recover-inventory")
        raise
    finally:
        cleanup_warnings = _cleanup_after_update(temp_path, lock_descriptor, lock_path)
    assert receipt is not None
    if cleanup_warnings:
        receipt = replace(receipt, warnings=(*receipt.warnings, *cleanup_warnings))
    return receipt


def plan_inventory_rollback(path: Path, backup_id: str) -> InventoryRollbackPlan:
    """Preview an exact-byte rollback without creating state or a lock file."""

    target, current, store = _prepare_backup_target(path)
    backup = store.read(backup_id)
    if backup.backup_id == current.revision:
        raise ConfigurationError("selected backup already matches the active inventory")
    target_details = _inspect_regular_file(target)
    try:
        parent_details = target.parent.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {target.parent}: {exc}") from exc
    return InventoryRollbackPlan(
        target=target,
        original_revision=current.revision,
        candidate_revision=backup.backup_id,
        active_revision_protection=current.inventory.revision_protection(),
        candidate_revision_protection=backup.inventory.revision_protection(),
        source_backup_id=backup.backup_id,
        source_backup_path=backup.path,
        candidate_raw=backup.raw,
        target_identity=_required_identity(target_details, subject="inventory target"),
        parent_identity=_required_identity(parent_details, subject="inventory directory"),
        backup_directory_identity=backup.directory_identity,
        source_backup_identity=backup.file_identity,
        active_snapshot=_snapshot_inventory(current.inventory),
        candidate_snapshot=_snapshot_inventory(backup.inventory),
        comparison=_inventory_comparison(current.inventory, backup.inventory),
    )


def _rollback_replacement_plan(plan: InventoryRollbackPlan) -> _InventoryReplacementPlan:
    return _InventoryReplacementPlan(
        target=plan.target,
        original_revision=plan.original_revision,
        candidate_revision=plan.candidate_revision,
        candidate_raw=plan.candidate_raw,
        target_identity=plan.target_identity,
        parent_identity=plan.parent_identity,
    )


def commit_inventory_rollback(
    plan: InventoryRollbackPlan,
    *,
    expected_revision: str,
    expected_plan: str,
) -> InventoryRollbackReceipt:
    """Restore one exact backup after revalidating its complete preview binding."""

    if expected_revision != plan.original_revision:
        raise ConfigurationError(
            "--expect-revision does not match this preview; preview the rollback again"
        )
    if expected_plan != plan.plan_token:
        raise ConfigurationError(
            "--expect-plan does not match this preview; preview the rollback again"
        )

    def refresh() -> _InventoryReplacementPlan:
        refreshed = plan_inventory_rollback(plan.target, plan.source_backup_id)
        if refreshed.plan_token != plan.plan_token:
            raise StorageError(
                "rollback target or source backup changed after preview; no rollback was applied"
            )
        return _rollback_replacement_plan(refreshed)

    update = _commit_inventory_replacement(
        _rollback_replacement_plan(plan),
        refresh=refresh,
        changed_message=(
            "rollback target or source backup changed after preview; no rollback was applied"
        ),
        operation="rollback-inventory",
    )
    return InventoryRollbackReceipt(
        update=update,
        source_backup_id=plan.source_backup_id,
        source_backup_path=plan.source_backup_path,
        candidate_revision_protection=plan.candidate_revision_protection,
    )


def _backup_set_revision(backups: tuple[_StoredInventoryBackup, ...]) -> str:
    payload = "\0".join(
        f"{backup.backup_id}:{backup.file_identity[0]}:{backup.file_identity[1]}"
        for backup in backups
    ).encode("utf-8")
    return _revision(payload)


def plan_inventory_backup_delete(
    path: Path,
    backup_id: str,
    *,
    allow_no_backups: bool = False,
) -> InventoryBackupDeletePlan:
    """Preview deletion of one exact validated backup; never delete implicitly."""

    target, current, store = _prepare_backup_target(path)
    backups, _legacy_count, warnings = store.list()
    selected = store.read(backup_id)
    selected_ids = {backup.backup_id for backup in backups}
    if selected.backup_id not in selected_ids:
        raise StorageError("selected backup is not in the validated target backup set")
    if len(backups) == 1 and not allow_no_backups:
        raise ConfigurationError(
            "deleting the last valid backup requires --allow-no-backups in the preview and apply"
        )
    if len(backups) > 1 and allow_no_backups:
        raise ConfigurationError(
            "--allow-no-backups is only valid when deleting the last valid backup"
        )
    remaining_backups = tuple(
        backup for backup in backups if backup.backup_id != selected.backup_id
    )
    remaining_protection_counts = dict(
        sorted(
            Counter(backup.inventory.revision_protection() for backup in remaining_backups).items()
        )
    )
    plan_warnings = list(warnings)
    if (
        selected.inventory.revision_protection() == "nonce-v1-present"
        and remaining_backups
        and remaining_protection_counts.get("nonce-v1-present", 0) == 0
    ):
        plan_warnings.append(
            "deletion leaves no nonce-v1-present backup; remaining recovery state is "
            "legacy-unblinded"
        )
    target_details = _inspect_regular_file(target)
    try:
        parent_details = target.parent.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect inventory directory {target.parent}: {exc}") from exc
    return InventoryBackupDeletePlan(
        target=target,
        original_revision=current.revision,
        backup_id=selected.backup_id,
        backup_path=selected.path,
        size_bytes=selected.size_bytes,
        selected_revision_protection=selected.inventory.revision_protection(),
        remaining_revision_protection_counts=remaining_protection_counts,
        target_identity=_required_identity(target_details, subject="inventory target"),
        parent_identity=_required_identity(parent_details, subject="inventory directory"),
        backup_directory_identity=selected.directory_identity,
        backup_identity=selected.file_identity,
        backup_set_revision=_backup_set_revision(backups),
        backup_count_before=len(backups),
        allow_no_backups=allow_no_backups,
        warnings=tuple(plan_warnings),
    )


def commit_inventory_backup_delete(
    plan: InventoryBackupDeletePlan,
    *,
    expected_revision: str,
    expected_plan: str,
) -> InventoryBackupDeleteReceipt:
    """Delete one exact backup after revalidating the active and backup-set revisions."""

    if expected_revision != plan.original_revision:
        raise ConfigurationError(
            "--expect-revision does not match this preview; preview the deletion again"
        )
    if expected_plan != plan.plan_token:
        raise ConfigurationError(
            "--expect-plan does not match this preview; preview the deletion again"
        )
    _validate_update_target(plan.target)
    lock_descriptor, lock_path = _acquire_lock(plan.target)
    receipt: InventoryBackupDeleteReceipt | None = None
    cleanup_warnings: tuple[str, ...] = ()
    manifest: _BackupOperationManifest | None = None
    manifest_operation_id: str | None = None
    deletion_started = False
    try:
        current = read_inventory_file(plan.target)
        if current.revision != plan.original_revision:
            raise StorageError(
                "inventory changed after preview; no backup was deleted (revision conflict)"
            )
        try:
            refreshed = plan_inventory_backup_delete(
                plan.target,
                plan.backup_id,
                allow_no_backups=plan.allow_no_backups,
            )
        except AtReadyError as exc:
            raise StorageError(
                "backup target or validated backup set changed after preview; no backup was deleted"
            ) from exc
        if refreshed.plan_token != plan.plan_token:
            raise StorageError(
                "backup target or validated backup set changed after preview; no backup was deleted"
            )
        rechecked = read_inventory_file(plan.target)
        if rechecked.revision != plan.original_revision:
            raise StorageError(
                "inventory changed during backup deletion; no backup was deleted "
                "(revision conflict)"
            )
        manifest = _manifest_for_target(plan.target)
        manifest_operation_id = manifest.prepare(
            "delete-inventory-backup",
            {
                "active_revision": plan.original_revision,
                "backup_id": refreshed.backup_id,
                "backup_set_revision": refreshed.backup_set_revision,
            },
        )
        try:
            refreshed.backup_path.unlink()
        except OSError as exc:
            raise StorageError(
                f"cannot delete selected inventory backup {refreshed.backup_path}: {exc}"
            ) from exc
        deletion_started = True

        warnings: list[str] = []
        try:
            refreshed.backup_path.lstat()
        except FileNotFoundError:
            deletion_verified = True
        except OSError as exc:
            deletion_verified = False
            warnings.append("backup was unlinked, but post-delete verification failed: " + str(exc))
        else:
            deletion_verified = False
            warnings.append(
                "backup unlink returned, but the selected path still exists; inspect before "
                "another deletion"
            )
        directory_synced = _fsync_directory(refreshed.backup_path.parent)
        if os.name == "posix" and not directory_synced:
            warnings.append(
                "backup was unlinked, but the target backup directory could not be synced"
            )
        remaining_valid_backups = plan.backup_count_before - 1
        remaining_revision_protection_counts: dict[str, int] | None = None
        try:
            remaining, _legacy_count, _listing_warnings = _InventoryBackupStore(plan.target).list()
            remaining_valid_backups = len(remaining)
            remaining_revision_protection_counts = dict(
                sorted(
                    Counter(backup.inventory.revision_protection() for backup in remaining).items()
                )
            )
        except AtReadyError as exc:
            warnings.append(
                "backup was unlinked, but the remaining validated backup set could not be "
                f"recounted: {exc}"
            )
        receipt = InventoryBackupDeleteReceipt(
            target=plan.target,
            previous_revision=plan.original_revision,
            backup_id=plan.backup_id,
            backup_path=plan.backup_path,
            deletion_verified=deletion_verified,
            directory_synced=directory_synced,
            remaining_valid_backups=remaining_valid_backups,
            selected_revision_protection=plan.selected_revision_protection,
            remaining_revision_protection_counts=remaining_revision_protection_counts,
            warnings=tuple(warnings),
        )
        manifest_warnings = _manifest_complete(
            manifest,
            manifest_operation_id,
            "delete-inventory-backup",
            {
                "backup_id": refreshed.backup_id,
                "deletion_verified": deletion_verified,
                "directory_synced": directory_synced,
                "remaining_valid_backups": remaining_valid_backups,
            },
            uncertain=(
                not deletion_verified
                or bool(warnings)
                or (os.name == "posix" and not directory_synced)
            ),
        )
        if manifest_warnings:
            receipt = replace(receipt, warnings=(*receipt.warnings, *manifest_warnings))
    except Exception as exc:
        if deletion_started and manifest is not None and manifest_operation_id is not None:
            try:
                manifest_warnings = _manifest_complete(
                    manifest,
                    manifest_operation_id,
                    "delete-inventory-backup",
                    {
                        "backup_id": plan.backup_id,
                        "deletion_started": True,
                        "outcome_inferred": False,
                        "reason": "apply-raised-after-deletion-started",
                    },
                    uncertain=True,
                )
                for warning in manifest_warnings:
                    exc.add_note(warning)
            except Exception as manifest_exc:
                exc.add_note(
                    "backup operation manifest uncertain recording failed: " + str(manifest_exc)
                )
            exc.add_note(
                "backup deletion started before this failure; inspect the backup set before "
                "retrying"
            )
        else:
            _manifest_abort(manifest, manifest_operation_id, "delete-inventory-backup")
        raise
    finally:
        cleanup_warnings = _cleanup_after_update(None, lock_descriptor, lock_path)
    assert receipt is not None
    if cleanup_warnings:
        receipt = replace(receipt, warnings=(*receipt.warnings, *cleanup_warnings))
    return receipt
