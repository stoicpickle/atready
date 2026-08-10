from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import atready.inventory_edit as inventory_edit
from atready.catalog import InventoryCatalog
from atready.errors import ConfigurationError, StorageError
from atready.inventory_edit import (
    _acquire_lock,
    _release_lock,
    commit_add_resource,
    commit_inventory_annotation,
    commit_inventory_backup_delete,
    commit_inventory_recovery,
    commit_inventory_rollback,
    commit_remove_resource,
    commit_replace_resource,
    inspect_inventory_backup,
    inspect_inventory_backup_manifest,
    list_inventory_backups,
    plan_add_resource,
    plan_inventory_annotation,
    plan_inventory_backup_delete,
    plan_inventory_recovery,
    plan_inventory_rollback,
    plan_remove_resource,
    plan_replace_resource,
    read_inventory_file,
    resource_from_mapping,
)
from atready.paths import create_private_file
from atready.templates import demo_inventory, starter_inventory
from atready.yamlio import MAX_FILE_BYTES


def _resource(resource_id: str = "personal-tool"):
    return resource_from_mapping(
        {
            "id": resource_id,
            "name": "Personal Tool",
            "categories": ["coding-agent"],
            "capabilities": {"code-implementation": 0.9},
            "access": {
                "status": "active",
                "interaction": "local-cli",
                "current_session": "available",
            },
            "economics": {"billing": "owned", "marginal_cost": 0.05, "quota": "ample"},
            "policy": {"allowed_data_classes": ["internal"]},
            "provenance": {"basis": "observed", "last_verified": date.today()},
        }
    )


def _personal_file(path: Path, *, private_notes: str | None = None) -> bytes:
    text = starter_inventory()
    if private_notes is not None:
        text = text.replace("resources: []", f"private_notes: {private_notes}\nresources: []")
    create_private_file(path, text)
    return text.encode("utf-8")


def _apply_resource(target: Path, resource_id: str):
    plan = plan_add_resource(target, _resource(resource_id))
    return commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )


def test_preview_is_read_only_and_apply_keeps_exact_private_backup(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target, private_notes="local-only-observation")
    original_nonce = InventoryCatalog.from_text(original.decode()).inventory.revision_privacy_nonce
    assert original_nonce is not None

    plan = plan_add_resource(target, _resource())

    assert target.read_bytes() == original
    assert not (target.parent / ".quartermaster-backups").exists()
    preview = plan.preview()
    assert preview["resource_id"] == "personal-tool"
    assert "local-only-observation" not in repr(preview)

    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.backup_path.read_bytes() == original
    assert receipt.backup_id == "sha256:" + receipt.backup_path.stem.removeprefix("inventory-")
    parsed = InventoryCatalog.from_path(target).inventory
    assert parsed.private_notes == "local-only-observation"
    assert parsed.revision_privacy_nonce == original_nonce
    assert (
        InventoryCatalog.from_path(receipt.backup_path).inventory.revision_privacy_nonce
        == original_nonce
    )
    assert [resource.id for resource in parsed.resources] == ["personal-tool"]
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert stat.S_IMODE(receipt.backup_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(receipt.backup_path.parent.stat().st_mode) == 0o700


def test_inventory_annotation_set_and_clear_are_redacted_and_manifested(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    sentinel = "SYNTHETIC-ROOT-ANNOTATION"

    set_plan = plan_inventory_annotation(target, sentinel)
    assert target.read_bytes() == original
    assert set_plan.private_notes_effect == "will-add"
    assert sentinel not in repr(set_plan)
    assert sentinel not in repr(set_plan.preview())
    receipt = commit_inventory_annotation(
        set_plan,
        expected_revision=set_plan.original_revision,
        expected_plan=set_plan.plan_token,
    )
    assert receipt.operation == "annotate-inventory"
    assert receipt.backup_path.read_bytes() == original
    assert InventoryCatalog.from_path(target).inventory.private_notes == sentinel
    manifest = inspect_inventory_backup_manifest(target)
    assert manifest.events[-1].operation == "annotate-inventory"
    manifest_bytes = b"".join(
        path.read_bytes()
        for path in sorted(inventory_edit._manifest_for_target(target).directory.iterdir())
    )
    assert sentinel.encode() not in manifest_bytes

    clear_plan = plan_inventory_annotation(target, None)
    assert clear_plan.private_notes_effect == "will-remove"
    commit_inventory_annotation(
        clear_plan,
        expected_revision=clear_plan.original_revision,
        expected_plan=clear_plan.plan_token,
    )
    assert InventoryCatalog.from_path(target).inventory.private_notes is None


def test_inventory_annotation_rejects_noop_and_legacy_note_set(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    with pytest.raises(ConfigurationError, match="does not change"):
        plan_inventory_annotation(target, None)

    legacy = tmp_path / "legacy.yaml"
    create_private_file(legacy, "schema_version: 1\ninventory_kind: personal\nresources: []\n")
    with pytest.raises(ConfigurationError, match="legacy-unblinded"):
        plan_inventory_annotation(legacy, "hidden")


def test_apply_creates_hash_linked_manifest_without_private_values(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    sentinel = "SYNTHETIC-MANIFEST-PRIVATE-NOTE"
    _personal_file(target, private_notes=sentinel)
    plan = plan_add_resource(target, _resource())

    before = inspect_inventory_backup_manifest(target)
    assert before.initialized is False
    assert before.events == ()
    assert not (target.parent / ".quartermaster-backups").exists()

    commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )
    manifest = inspect_inventory_backup_manifest(target)

    assert manifest.initialized is True
    assert [event.sequence for event in manifest.events] == [0, 1, 2]
    assert [event.phase for event in manifest.events] == ["completed", "prepared", "completed"]
    assert manifest.events[0].details["history_before_manifest"] == "unknown"
    assert manifest.events[1].operation == manifest.events[2].operation == "add-resource"
    assert manifest.events[0].previous_event_hash is None
    assert manifest.events[1].previous_event_hash == manifest.events[0].event_hash
    assert manifest.events[2].previous_event_hash == manifest.events[1].event_hash
    assert manifest.unresolved_operation_ids == ()
    event_directory = Path(inventory_edit._manifest_for_target(target).directory)
    event_bytes = b"".join(path.read_bytes() for path in sorted(event_directory.iterdir()))
    assert sentinel.encode() not in event_bytes
    if os.name == "posix":
        assert stat.S_IMODE(event_directory.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in event_directory.iterdir())


def test_manifest_append_requests_binary_descriptor_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    real_open = inventory_edit.os.open
    platform_binary_flag = int(getattr(inventory_edit.os, "O_BINARY", 0))
    synthetic_binary_flag = platform_binary_flag or 1 << 28
    manifest_open_flags: list[int] = []
    if platform_binary_flag == 0:
        monkeypatch.setattr(inventory_edit.os, "O_BINARY", synthetic_binary_flag, raising=False)

    def observe_open(path, flags, mode=0o777, *, dir_fd=None):
        candidate = Path(path)
        if inventory_edit._MANIFEST_TEMP_FILENAME_PATTERN.fullmatch(candidate.name):
            manifest_open_flags.append(flags)
        if platform_binary_flag == 0:
            flags &= ~synthetic_binary_flag
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(inventory_edit.os, "open", observe_open)
    _apply_resource(target, "tool-one")

    assert manifest_open_flags
    assert all(flags & synthetic_binary_flag for flags in manifest_open_flags)


def test_manifest_reserves_prepare_and_outcome_before_inventory_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    before = target.read_bytes()
    assert len(inspect_inventory_backup_manifest(target).events) == 3
    monkeypatch.setattr(inventory_edit, "_MAX_MANIFEST_EVENTS", 4)
    plan = plan_add_resource(target, _resource("tool-two"))

    with pytest.raises(
        StorageError, match="cannot reserve preparation and outcome events"
    ) as caught:
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert "new explicitly initialized inventory path" in str(caught.value)
    assert "in-place manifest pruning or rotation is unsupported" in str(caught.value)
    assert target.read_bytes() == before
    manifest = inspect_inventory_backup_manifest(target)
    assert len(manifest.events) == 3
    assert manifest.unresolved_operation_ids == ()


def test_committed_manifest_event_survives_temp_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    plan = plan_add_resource(target, _resource())
    real_unlink = Path.unlink
    real_sync = inventory_edit._sync_manifest_directory
    synced_with_leftover: list[Path] = []

    def refuse_manifest_temp_cleanup(path: Path, *args, **kwargs):
        if inventory_edit._MANIFEST_TEMP_FILENAME_PATTERN.fullmatch(path.name):
            raise OSError("synthetic manifest temp cleanup failure")
        return real_unlink(path, *args, **kwargs)

    def observe_sync(path: Path) -> None:
        if path.name == inventory_edit._MANIFEST_DIRECTORY_NAME and any(
            inventory_edit._MANIFEST_TEMP_FILENAME_PATTERN.fullmatch(item.name)
            for item in path.iterdir()
        ):
            synced_with_leftover.append(path)
        real_sync(path)

    monkeypatch.setattr(Path, "unlink", refuse_manifest_temp_cleanup)
    monkeypatch.setattr(inventory_edit, "_sync_manifest_directory", observe_sync)
    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.replacement_verified is True
    assert any("event committed" in warning for warning in receipt.warnings)
    manifest = inspect_inventory_backup_manifest(target)
    assert [event.phase for event in manifest.events] == ["completed", "prepared", "completed"]
    assert any("validated manifest temporary hard link" in warning for warning in manifest.warnings)
    manifest_directory = inventory_edit._manifest_for_target(target).directory
    leftovers = [
        item
        for item in manifest_directory.iterdir()
        if inventory_edit._MANIFEST_TEMP_FILENAME_PATTERN.fullmatch(item.name)
    ]
    assert len(leftovers) == 3
    assert all(item.stat().st_nlink == 2 for item in leftovers)
    assert synced_with_leftover


def test_interrupted_pre_link_manifest_append_is_inspectable_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    plan = plan_add_resource(target, _resource("tool-two"))
    original = target.read_bytes()
    real_link = inventory_edit.os.link
    interrupted = False

    def interrupt_before_manifest_link(source, destination, *, follow_symlinks=True):
        nonlocal interrupted
        source_path = Path(source)
        if not interrupted and inventory_edit._MANIFEST_TEMP_FILENAME_PATTERN.fullmatch(
            source_path.name
        ):
            interrupted = True
            raise KeyboardInterrupt("synthetic interruption before manifest link")
        return real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(inventory_edit.os, "link", interrupt_before_manifest_link)
    with pytest.raises(KeyboardInterrupt, match="synthetic interruption"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original
    manifest = inspect_inventory_backup_manifest(target)
    assert manifest.initialized is True
    assert [event.phase for event in manifest.events] == ["completed", "prepared", "completed"]
    assert any("interrupted manifest append" in warning for warning in manifest.warnings)
    manifest_directory = inventory_edit._manifest_for_target(target).directory
    interrupted_temps = list(manifest_directory.glob(".manifest-*.tmp"))
    assert len(interrupted_temps) == 1
    assert interrupted_temps[0].stat().st_nlink == 1

    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.replacement_verified is True
    assert any("no operation outcome was inferred" in warning for warning in receipt.warnings)
    assert [resource.id for resource in InventoryCatalog.from_path(target).inventory.resources] == [
        "tool-one",
        "tool-two",
    ]
    assert list(manifest_directory.glob(".manifest-*.tmp")) == []
    manifest = inspect_inventory_backup_manifest(target)
    assert [event.phase for event in manifest.events] == [
        "completed",
        "prepared",
        "completed",
        "prepared",
        "uncertain",
        "prepared",
        "completed",
    ]
    assert manifest.unresolved_operation_ids == ()


def test_interrupted_temp_that_is_last_link_to_committed_tail_preserves_history(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    before = inspect_inventory_backup_manifest(target)
    manifest_directory = inventory_edit._manifest_for_target(target).directory
    committed_tail = sorted(manifest_directory.glob("event-*.json"))[-1]
    interrupted_temp = manifest_directory / (".manifest-" + "f" * 32 + ".tmp")
    os.link(committed_tail, interrupted_temp, follow_symlinks=False)
    committed_tail.unlink()
    assert interrupted_temp.stat().st_nlink == 1

    inspected = inspect_inventory_backup_manifest(target)
    assert [event.event_hash for event in inspected.events] == [
        event.event_hash for event in before.events[:-1]
    ]
    assert inspected.unresolved_operation_ids == (before.events[-1].operation_id,)
    assert any("interrupted manifest append" in warning for warning in inspected.warnings)
    assert interrupted_temp.exists()

    plan = plan_add_resource(target, _resource("tool-two"))
    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.replacement_verified is True
    assert any("preserved a validated interrupted" in warning for warning in receipt.warnings)
    assert [resource.id for resource in InventoryCatalog.from_path(target).inventory.resources] == [
        "tool-one",
        "tool-two",
    ]
    assert not interrupted_temp.exists()
    assert committed_tail.exists()
    after = inspect_inventory_backup_manifest(target)
    assert [event.event_hash for event in after.events[: len(before.events)]] == [
        event.event_hash for event in before.events
    ]
    assert [event.phase for event in after.events] == [
        "completed",
        "prepared",
        "completed",
        "prepared",
        "completed",
    ]
    assert after.unresolved_operation_ids == ()


def test_promoted_exact_closing_event_is_an_idempotent_finish(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    before = inspect_inventory_backup_manifest(target)
    closing_event = before.events[-1]
    assert closing_event.operation_id is not None
    assert closing_event.operation is not None
    manifest_directory = inventory_edit._manifest_for_target(target).directory
    committed_tail = sorted(manifest_directory.glob("event-*.json"))[-1]
    interrupted_temp = manifest_directory / (".manifest-" + "e" * 32 + ".tmp")
    os.link(committed_tail, interrupted_temp, follow_symlinks=False)
    committed_tail.unlink()

    operation_manifest = inventory_edit._manifest_for_target(target)
    operation_manifest.finish(
        closing_event.operation_id,
        closing_event.operation,
        closing_event.phase,
        closing_event.details,
    )

    after = inspect_inventory_backup_manifest(target)
    assert [event.event_hash for event in after.events] == [
        event.event_hash for event in before.events
    ]
    assert committed_tail.exists()
    assert not interrupted_temp.exists()

    with pytest.raises(StorageError, match="already has another outcome"):
        operation_manifest.finish(
            closing_event.operation_id,
            closing_event.operation,
            "aborted",
            closing_event.details,
        )
    with pytest.raises(StorageError, match="already has another outcome"):
        operation_manifest.finish(
            closing_event.operation_id,
            closing_event.operation,
            closing_event.phase,
            {**closing_event.details, "reason": "different-outcome"},
        )
    unchanged = inspect_inventory_backup_manifest(target)
    assert [event.event_hash for event in unchanged.events] == [
        event.event_hash for event in before.events
    ]


def test_manifest_rejects_unproven_temporary_or_arbitrary_entries(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    manifest_directory = inventory_edit._manifest_for_target(target).directory
    event_raw = sorted(manifest_directory.glob("event-*.json"))[0].read_bytes()
    fake_temp = manifest_directory / (".manifest-" + "0" * 32 + ".tmp")
    fake_temp.write_bytes(event_raw)
    if os.name == "posix":
        fake_temp.chmod(0o600)

    with pytest.raises(StorageError, match="unsafe backup operation manifest temporary"):
        inspect_inventory_backup_manifest(target)

    fake_temp.unlink()
    unexpected = manifest_directory / "unexpected.txt"
    unexpected.write_text("not an event\n", encoding="utf-8")
    if os.name == "posix":
        unexpected.chmod(0o600)
    with pytest.raises(StorageError, match="unexpected directory entry"):
        inspect_inventory_backup_manifest(target)


def test_manifest_rejects_canonical_interrupted_temp_for_unknown_operation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    manifest = inspect_inventory_backup_manifest(target)
    manifest_directory = inventory_edit._manifest_for_target(target).directory
    value = {
        "details": {"outcome_inferred": False},
        "event_type": "operation",
        "operation": "add-resource",
        "operation_id": "operation-v1:" + "0" * 64,
        "phase": "completed",
        "previous_event_hash": manifest.events[-1].event_hash,
        "recorded_at": "2026-01-01T00:00:00Z",
        "schema_version": inventory_edit._MANIFEST_SCHEMA_VERSION,
        "sequence": len(manifest.events),
    }
    fake_temp = manifest_directory / (".manifest-" + "0" * 32 + ".tmp")
    fake_temp.write_bytes(inventory_edit._canonical_manifest_bytes(value))
    if os.name == "posix":
        fake_temp.chmod(0o600)

    with pytest.raises(StorageError, match="unrecognized operation transition"):
        inspect_inventory_backup_manifest(target)


def test_manifest_rejects_interrupted_temp_that_breaks_the_chain(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    manifest = inspect_inventory_backup_manifest(target)
    manifest_directory = inventory_edit._manifest_for_target(target).directory
    value = {
        "details": {"outcome_inferred": False},
        "event_type": "operation",
        "operation": "add-resource",
        "operation_id": "operation-v1:" + "1" * 64,
        "phase": "prepared",
        "previous_event_hash": "sha256:" + "9" * 64,
        "recorded_at": "2026-01-01T00:00:00Z",
        "schema_version": inventory_edit._MANIFEST_SCHEMA_VERSION,
        "sequence": len(manifest.events),
    }
    fake_temp = manifest_directory / (".manifest-" + "1" * 32 + ".tmp")
    fake_temp.write_bytes(inventory_edit._canonical_manifest_bytes(value))
    if os.name == "posix":
        fake_temp.chmod(0o600)

    with pytest.raises(StorageError, match="does not continue the committed chain"):
        inspect_inventory_backup_manifest(target)
    assert fake_temp.exists()


def test_manifest_rejects_multiple_interrupted_temps(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    manifest = inspect_inventory_backup_manifest(target)
    manifest_directory = inventory_edit._manifest_for_target(target).directory
    for index, marker in enumerate(("2", "3")):
        value = {
            "details": {"outcome_inferred": False, "attempt": index},
            "event_type": "operation",
            "operation": "add-resource",
            "operation_id": "operation-v1:" + marker * 64,
            "phase": "prepared",
            "previous_event_hash": manifest.events[-1].event_hash,
            "recorded_at": "2026-01-01T00:00:00Z",
            "schema_version": inventory_edit._MANIFEST_SCHEMA_VERSION,
            "sequence": len(manifest.events),
        }
        fake_temp = manifest_directory / (".manifest-" + marker * 32 + ".tmp")
        fake_temp.write_bytes(inventory_edit._canonical_manifest_bytes(value))
        if os.name == "posix":
            fake_temp.chmod(0o600)

    with pytest.raises(StorageError, match="temporary artifact fork"):
        inspect_inventory_backup_manifest(target)


def test_manifest_genesis_binds_maximum_backup_set_with_bounded_digest(tmp_path: Path) -> None:
    directory = tmp_path / "namespace"
    backup_ids = tuple(
        SimpleNamespace(backup_id=f"sha256:{index:064x}")
        for index in range(inventory_edit._MAX_BACKUP_DIRECTORY_ENTRIES)
    )

    class SyntheticStore:
        def __init__(self) -> None:
            self.directory = directory

        def _ensure_directories(self) -> None:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)

        def _namespace_usage(self) -> tuple[int, int]:
            return 0, 0

        def list(self):
            return backup_ids, 0, ()

    manifest = inventory_edit._BackupOperationManifest(SyntheticStore())
    manifest.ensure_genesis()
    event = manifest.load()[0]

    assert event.details["backup_count"] == inventory_edit._MAX_BACKUP_DIRECTORY_ENTRIES
    assert event.details["backup_set_revision"].startswith("sha256:")
    assert "backup_ids" not in event.details
    event_path = next(manifest.directory.iterdir())
    assert event_path.stat().st_size <= inventory_edit._MAX_MANIFEST_EVENT_BYTES


def test_manifest_rejects_modified_event_bytes(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    directory = inventory_edit._manifest_for_target(target).directory
    event = sorted(directory.iterdir())[-1]
    event.write_bytes(event.read_bytes() + b" ")

    with pytest.raises(StorageError, match="filename hash"):
        inspect_inventory_backup_manifest(target)


def test_manifest_covers_every_valid_active_backup_affecting_apply(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    added = _apply_resource(target, "tool-one")

    replacement_value = _resource("tool-one").model_dump(mode="json")
    replacement_value["name"] = "Replacement Tool"
    replacement_plan = plan_replace_resource(target, resource_from_mapping(replacement_value))
    replaced = commit_replace_resource(
        replacement_plan,
        expected_revision=replacement_plan.original_revision,
        expected_plan=replacement_plan.plan_token,
    )
    remove_plan = plan_remove_resource(target, "tool-one")
    commit_remove_resource(
        remove_plan,
        expected_revision=remove_plan.original_revision,
        expected_plan=remove_plan.plan_token,
    )
    rollback_plan = plan_inventory_rollback(target, added.backup_id)
    commit_inventory_rollback(
        rollback_plan,
        expected_revision=rollback_plan.original_revision,
        expected_plan=rollback_plan.plan_token,
    )
    delete_plan = plan_inventory_backup_delete(target, replaced.backup_id)
    commit_inventory_backup_delete(
        delete_plan,
        expected_revision=delete_plan.original_revision,
        expected_plan=delete_plan.plan_token,
    )

    outcomes = [
        event.operation
        for event in inspect_inventory_backup_manifest(target).events
        if event.event_type == "operation" and event.phase == "completed"
    ]
    assert outcomes == [
        "add-resource",
        "replace-resource",
        "remove-resource",
        "rollback-inventory",
        "delete-inventory-backup",
    ]


def test_missing_active_inventory_can_recover_one_exact_backup(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    applied = _apply_resource(target, "temporary-resource")
    target.unlink()

    listing = list_inventory_backups(target)
    assert listing.active_state == "missing"
    assert listing.active_revision is None
    assert [item.backup_id for item in listing.backups] == [applied.backup_id]

    plan = plan_inventory_recovery(target, applied.backup_id)
    assert plan.preview()["expect_state"] == "missing"
    assert plan.preview()["candidate_snapshot"]["resources"] == []
    assert target.exists() is False

    receipt = commit_inventory_recovery(
        plan,
        expected_state="missing",
        expected_plan=plan.plan_token,
    )

    assert target.read_bytes() == original
    assert receipt.replacement_verified is True
    assert receipt.quarantine_path is None
    assert applied.backup_path.read_bytes() == original


def test_missing_recovery_never_clobbers_target_created_after_final_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    applied = _apply_resource(target, "temporary-resource")
    target.unlink()
    plan = plan_inventory_recovery(target, applied.backup_id)
    raced_bytes = starter_inventory().encode("utf-8")
    real_link = inventory_edit.os.link

    def create_target_before_link(source, destination, *args, **kwargs):
        if Path(destination) == target:
            create_private_file(target, raced_bytes.decode("utf-8"))
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(inventory_edit.os, "link", create_target_before_link)
    with pytest.raises(StorageError, match="target appeared during apply"):
        commit_inventory_recovery(
            plan,
            expected_state=plan.state_token,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == raced_bytes
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))
    manifest = inspect_inventory_backup_manifest(target)
    assert manifest.events[-1].operation == "recover-inventory"
    assert manifest.events[-1].phase == "aborted"


def test_missing_recovery_exception_after_commit_records_uncertain_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    applied = _apply_resource(target, "temporary-resource")
    target.unlink()
    plan = plan_inventory_recovery(target, applied.backup_id)

    def fail_post_commit_sync(path: Path) -> bool:
        if path == target.parent and target.exists():
            raise StorageError("synthetic post-commit recovery failure")
        return True

    monkeypatch.setattr(inventory_edit, "_fsync_directory", fail_post_commit_sync)
    with pytest.raises(StorageError, match="synthetic post-commit recovery failure") as caught:
        commit_inventory_recovery(
            plan,
            expected_state=plan.state_token,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original
    assert any("replacement started" in note for note in getattr(caught.value, "__notes__", ()))
    manifest = inspect_inventory_backup_manifest(target)
    outcome = manifest.events[-1]
    assert outcome.operation == "recover-inventory"
    assert outcome.phase == "uncertain"
    assert outcome.details["replacement_started"] is True
    assert outcome.details["quarantine_created"] is False


@pytest.mark.parametrize(
    ("case", "expected_operation"),
    [
        ("add", "add-resource"),
        ("replace", "replace-resource"),
        ("remove", "remove-resource"),
        ("rollback", "rollback-inventory"),
    ],
)
def test_replacement_exception_after_commit_records_uncertain_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_operation: str,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)

    if case == "add":
        plan = plan_add_resource(target, _resource("tool-one"))

        def commit() -> object:
            return commit_add_resource(
                plan,
                expected_revision=plan.original_revision,
                expected_plan=plan.plan_token,
            )

    else:
        added = _apply_resource(target, "tool-one")
        if case == "replace":
            value = _resource("tool-one").model_dump(mode="json")
            value["name"] = "Replacement Tool"
            plan = plan_replace_resource(target, resource_from_mapping(value))

            def commit() -> object:
                return commit_replace_resource(
                    plan,
                    expected_revision=plan.original_revision,
                    expected_plan=plan.plan_token,
                )

        elif case == "remove":
            plan = plan_remove_resource(target, "tool-one")

            def commit() -> object:
                return commit_remove_resource(
                    plan,
                    expected_revision=plan.original_revision,
                    expected_plan=plan.plan_token,
                )

        else:
            plan = plan_inventory_rollback(target, added.backup_id)

            def commit() -> object:
                return commit_inventory_rollback(
                    plan,
                    expected_revision=plan.original_revision,
                    expected_plan=plan.plan_token,
                )

    before = target.read_bytes()

    def fail_post_commit_sync(path: Path) -> bool:
        if path == target.parent and target.read_bytes() != before:
            raise StorageError("synthetic post-replacement failure")
        return True

    monkeypatch.setattr(inventory_edit, "_fsync_directory", fail_post_commit_sync)
    with pytest.raises(StorageError, match="synthetic post-replacement failure") as caught:
        commit()

    assert target.read_bytes() != before
    assert any("replacement started" in note for note in getattr(caught.value, "__notes__", ()))
    outcome = inspect_inventory_backup_manifest(target).events[-1]
    assert outcome.operation == expected_operation
    assert outcome.phase == "uncertain"
    assert outcome.details["replacement_started"] is True


def test_invalid_active_inventory_is_quarantined_before_exact_recovery(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    applied = _apply_resource(target, "temporary-resource")
    corrupt = b"schema_version: [definitely-invalid\nSYNTHETIC-CORRUPT-BYTES\n"
    target.write_bytes(corrupt)

    inspection = inspect_inventory_backup(target, applied.backup_id)
    assert inspection.active_state == "invalid"
    assert inspection.active_snapshot is None
    assert inspection.comparison is None

    plan = plan_inventory_recovery(target, applied.backup_id)
    preview = plan.preview()
    assert preview["expect_state"] == "invalid"
    assert "SYNTHETIC-CORRUPT-BYTES" not in repr(preview)
    assert "SYNTHETIC-CORRUPT-BYTES" not in repr(plan)

    receipt = commit_inventory_recovery(
        plan,
        expected_state="invalid",
        expected_plan=plan.plan_token,
    )

    assert target.read_bytes() == original
    assert receipt.quarantine_path is not None
    assert receipt.quarantine_path.read_bytes() == corrupt
    assert receipt.quarantine_id is not None
    assert receipt.quarantine_id.startswith("quarantine-v1:")
    assert hashlib.sha256(corrupt).hexdigest() not in receipt.quarantine_path.name
    assert receipt.replacement_verified is True
    assert "SYNTHETIC-CORRUPT-BYTES" not in repr(receipt)
    manifest = inspect_inventory_backup_manifest(target)
    assert manifest.events[-1].operation == "recover-inventory"
    assert manifest.events[-1].phase == "completed"


def test_recovery_failure_after_quarantine_records_and_reports_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    applied = _apply_resource(target, "temporary-resource")
    corrupt = b"schema_version: [invalid\nSYNTHETIC-CORRUPT-BYTES\n"
    target.write_bytes(corrupt)
    plan = plan_inventory_recovery(target, applied.backup_id)
    real_write = inventory_edit._write_candidate_temp

    def fail_recovery_candidate(path: Path, content: str | bytes) -> Path:
        if path == target:
            raise StorageError("synthetic recovery candidate failure")
        return real_write(path, content)

    monkeypatch.setattr(inventory_edit, "_write_candidate_temp", fail_recovery_candidate)
    with pytest.raises(StorageError, match="synthetic recovery candidate failure") as caught:
        commit_inventory_recovery(
            plan,
            expected_state=plan.state_token,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == corrupt
    notes = getattr(caught.value, "__notes__", ())
    assert any("retained in recovery quarantine" in note for note in notes)
    manifest = inspect_inventory_backup_manifest(target)
    outcome = manifest.events[-1]
    assert outcome.phase == "uncertain"
    assert outcome.details["quarantine_created"] is True
    assert outcome.details["replacement_started"] is False
    quarantine_path = Path(next(note.split(" at ", 1)[1].split(";", 1)[0] for note in notes))
    assert quarantine_path.read_bytes() == corrupt
    assert outcome.details["quarantine_id"].removeprefix("quarantine-v1:") in quarantine_path.name


def test_post_link_quarantine_failure_is_reported_and_manifested_as_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    applied = _apply_resource(target, "temporary-resource")
    corrupt = b"schema_version: [invalid\nSYNTHETIC-CORRUPT-BYTES\n"
    target.write_bytes(corrupt)
    plan = plan_inventory_recovery(target, applied.backup_id)
    real_unlink = Path.unlink
    failed_once = False

    def fail_first_quarantine_temp_unlink(path: Path, *args, **kwargs):
        nonlocal failed_once
        if path.name.startswith(".invalid.") and path.name.endswith(".tmp") and not failed_once:
            failed_once = True
            raise OSError("synthetic quarantine temp cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_quarantine_temp_unlink)
    with pytest.raises(StorageError, match="synthetic quarantine temp cleanup failure") as caught:
        commit_inventory_recovery(
            plan,
            expected_state=plan.state_token,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == corrupt
    notes = getattr(caught.value, "__notes__", ())
    retained_note = next(note for note in notes if "retained in recovery quarantine" in note)
    quarantine_path = Path(retained_note.split(" at ", 1)[1].split(";", 1)[0])
    assert quarantine_path.read_bytes() == corrupt
    assert not list(quarantine_path.parent.glob(".invalid.*.tmp"))
    manifest = inspect_inventory_backup_manifest(target)
    outcome = manifest.events[-1]
    assert outcome.operation == "recover-inventory"
    assert outcome.phase == "uncertain"
    assert outcome.details["quarantine_created"] is True
    assert outcome.details["replacement_started"] is False
    assert outcome.details["quarantine_id"].removeprefix("quarantine-v1:") in quarantine_path.name


def test_recovery_refuses_valid_active_and_changed_state(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    applied = _apply_resource(target, "temporary-resource")

    with pytest.raises(ConfigurationError, match="use inventory backup rollback"):
        plan_inventory_recovery(target, applied.backup_id)

    target.write_text("invalid: [\n", encoding="utf-8")
    plan = plan_inventory_recovery(target, applied.backup_id)
    target.unlink()
    with pytest.raises(StorageError, match="changed after preview"):
        commit_inventory_recovery(
            plan,
            expected_state="invalid",
            expected_plan=plan.plan_token,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX recovery file contract")
def test_recovery_refuses_insecure_invalid_active_file(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    applied = _apply_resource(target, "temporary-resource")
    target.write_text("invalid: [\n", encoding="utf-8")
    target.chmod(0o644)

    with pytest.raises(StorageError, match="insecure inventory mode"):
        plan_inventory_recovery(target, applied.backup_id)


def test_replace_preview_and_apply_replace_one_exact_resource_with_backup(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    sentinel = "SYNTHETIC-REPLACE-PRIVATE-NOTE"
    noted = _resource("personal-tool").model_copy(update={"private_notes": sentinel})
    add = plan_add_resource(target, noted)
    commit_add_resource(
        add,
        expected_revision=add.original_revision,
        expected_plan=add.plan_token,
    )
    before = target.read_bytes()
    replacement_value = _resource("personal-tool").model_dump(mode="json")
    replacement_value["name"] = "Revised Personal Tool"
    replacement_value["capabilities"] = {"code-implementation": 0.75, "review": 0.8}
    replacement = resource_from_mapping(replacement_value)

    plan = plan_replace_resource(target, replacement)
    preview = plan.preview()

    assert target.read_bytes() == before
    assert preview["operation"] == "replace-resource"
    assert preview["resource_id"] == "personal-tool"
    assert preview["resource_count_before"] == preview["resource_count_after"] == 1
    assert preview["resource_before"]["name"] == "Personal Tool"
    assert preview["resource_after"]["name"] == "Revised Personal Tool"
    assert preview["private_notes_effect"] == "will-remove"
    assert sentinel not in repr(plan)
    assert sentinel not in repr(preview)

    receipt = commit_replace_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.operation == "replace-resource"
    assert receipt.backup_path.read_bytes() == before
    parsed = InventoryCatalog.from_path(target).inventory
    assert [resource.id for resource in parsed.resources] == ["personal-tool"]
    assert parsed.resources[0].name == "Revised Personal Tool"
    assert parsed.resources[0].capabilities == {"code-implementation": 0.75, "review": 0.8}
    assert parsed.resources[0].private_notes is None


def test_remove_preview_and_apply_remove_one_exact_resource_with_backup(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    noted = _resource("personal-tool").model_copy(update={"private_notes": "hidden note"})
    add = plan_add_resource(target, noted)
    commit_add_resource(
        add,
        expected_revision=add.original_revision,
        expected_plan=add.plan_token,
    )
    before = target.read_bytes()

    plan = plan_remove_resource(target, "personal-tool")
    preview = plan.preview()

    assert target.read_bytes() == before
    assert preview["operation"] == "remove-resource"
    assert preview["resource_id"] == "personal-tool"
    assert preview["resource_count_before"] == 1
    assert preview["resource_count_after"] == 0
    assert preview["resource"]["name"] == "Personal Tool"
    assert preview["private_notes_present"] is True
    assert "hidden note" not in repr(plan)
    assert "hidden note" not in repr(preview)

    receipt = commit_remove_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.operation == "remove-resource"
    assert receipt.backup_path.read_bytes() == before
    assert InventoryCatalog.from_path(target).inventory.resources == []


def test_replace_refuses_noop_and_missing_ids_are_actionable(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "personal-tool")
    existing = InventoryCatalog.from_path(target).inventory.resources[0]

    with pytest.raises(ConfigurationError, match="replacement does not change"):
        plan_replace_resource(target, existing)
    with pytest.raises(ConfigurationError, match="resource 'missing' does not exist"):
        plan_replace_resource(target, _resource("missing"))
    with pytest.raises(ConfigurationError, match="resource 'missing' does not exist"):
        plan_remove_resource(target, "missing")
    with pytest.raises(ConfigurationError, match="valid lowercase slug"):
        plan_remove_resource(target, "../all")
    with pytest.raises(ConfigurationError, match="exact lowercase slug"):
        plan_remove_resource(target, " personal-tool ")


def test_add_plan_binds_but_never_represents_private_resource_notes(tmp_path: Path) -> None:
    sentinel = "SYNTHETIC-PRIVATE-SENTINEL"
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    value = _resource().model_dump(mode="json")
    value["private_notes"] = sentinel
    plan = plan_add_resource(target, resource_from_mapping(value))

    preview = plan.preview()
    assert preview["private_notes_present"] is True
    assert preview["private_notes_exposed"] is False
    assert preview["private_notes_bound_to_plan"] is True
    assert sentinel not in repr(plan)
    assert sentinel not in repr(preview)

    changed = value | {"private_notes": "different private note"}
    changed_plan = plan_add_resource(target, resource_from_mapping(changed))
    assert changed_plan.plan_token != plan.plan_token


def test_fresh_revision_privacy_nonces_blind_identical_hidden_notes() -> None:
    note = "guessable-low-entropy-note"
    first = starter_inventory().replace("resources: []", f"private_notes: {note}\nresources: []")
    second = starter_inventory().replace("resources: []", f"private_notes: {note}\nresources: []")

    first_catalog = InventoryCatalog.from_text(first)
    second_catalog = InventoryCatalog.from_text(second)
    assert first_catalog.fingerprint() == second_catalog.fingerprint()
    assert first_catalog.snapshot() == second_catalog.snapshot()
    assert inventory_edit._revision(first.encode()) != inventory_edit._revision(second.encode())
    assert first_catalog.inventory.revision_privacy_nonce not in repr(first_catalog)
    assert second_catalog.inventory.revision_privacy_nonce not in repr(second_catalog)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS extended ACL contract")
def test_inventory_reader_rejects_macos_extended_acl(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    subprocess.run(  # noqa: S603
        ["/bin/chmod", "+a", "everyone allow read", str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    target.chmod(0o600)

    with pytest.raises(ConfigurationError, match="macOS extended ACL"):
        read_inventory_file(target)


def test_candidate_temp_acl_refusal_cleans_exact_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    monkeypatch.setattr(inventory_edit, "darwin_fd_has_extended_acl", lambda _fd: True)

    with pytest.raises(StorageError, match="temporary file with a macOS extended ACL"):
        inventory_edit._write_candidate_temp(target, "synthetic candidate")

    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_revision_conflict_preserves_concurrent_bytes_without_backup(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    plan = plan_add_resource(target, _resource())
    concurrent = target.read_bytes() + b"# concurrent user edit\n"
    target.write_bytes(concurrent)

    with pytest.raises(StorageError, match="changed after preview"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == concurrent
    assert not (target.parent / ".quartermaster-backups").exists()
    assert target.with_name(f".{target.name}.lock").is_file()


def test_failed_atomic_replace_preserves_target_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("synthetic replace failure")

    monkeypatch.setattr("atready.inventory_edit.os.replace", fail_replace)
    with pytest.raises(StorageError, match="cannot atomically replace inventory"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original
    backups = list((target.parent / ".quartermaster-backups").rglob("inventory-*.yaml"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert target.with_name(f".{target.name}.lock").is_file()
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []

    monkeypatch.undo()
    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )
    assert receipt.replacement_verified is True
    assert receipt.backup_path.read_bytes() == original


def test_add_rejects_demo_inventory_and_symlinked_targets(tmp_path: Path) -> None:
    demo_path = tmp_path / "demo.yaml"
    create_private_file(demo_path, demo_inventory())
    with pytest.raises(ConfigurationError, match="demo inventories are read-only"):
        plan_add_resource(demo_path, _resource())

    actual = tmp_path / "actual.yaml"
    _personal_file(actual)
    linked = tmp_path / "linked.yaml"
    try:
        linked.symlink_to(actual)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(ConfigurationError, match="symlinked configuration"):
        plan_add_resource(linked, _resource())


def test_add_rejects_symlinked_parent_and_insecure_mode(tmp_path: Path) -> None:
    actual_parent = tmp_path / "actual"
    actual_target = actual_parent / "inventory.yaml"
    _personal_file(actual_target)
    linked_parent = tmp_path / "linked"
    try:
        linked_parent.symlink_to(actual_parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(StorageError, match="symlinked AtReady directory"):
        plan_add_resource(linked_parent / "inventory.yaml", _resource())

    if os.name == "posix":
        hard_link = tmp_path / "hard-linked-inventory.yaml"
        os.link(actual_target, hard_link)
        with pytest.raises(StorageError, match="hard-linked inventory update target"):
            plan_add_resource(actual_target, _resource())
        hard_link.unlink()

        actual_target.chmod(0o644)
        with pytest.raises(StorageError, match="insecure inventory mode"):
            plan_add_resource(actual_target, _resource())
        actual_target.chmod(0o600)
        actual_parent.chmod(0o777)
        with pytest.raises(StorageError, match="writable inventory directory mode"):
            plan_add_resource(actual_target, _resource())


def test_invalid_resource_mapping_has_actionable_field_locations() -> None:
    with pytest.raises(ConfigurationError) as raised:
        resource_from_mapping({"id": "Not A Slug"})

    message = str(raised.value)
    assert message.startswith("resource validation failed:")
    assert "id:" in message
    assert "name:" in message
    assert "categories:" in message
    assert "capabilities:" in message

    with pytest.raises(ConfigurationError, match="control or format characters"):
        resource_from_mapping(
            {
                "id": "unsafe-display",
                "name": "Unsafe\x1b]52;c;payload\x07",
                "categories": ["tool"],
                "capabilities": {"build": 0.5},
            }
        )


def test_plan_identity_capture_rejects_an_unknown_zero_inode() -> None:
    with pytest.raises(StorageError, match="cannot verify inventory target identity"):
        inventory_edit._required_identity(
            SimpleNamespace(st_dev=7, st_ino=0),
            subject="inventory target",
        )


def test_existing_cooperative_lock_refuses_apply_without_touching_inventory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    descriptor, lock = _acquire_lock(target)
    try:
        with pytest.raises(StorageError, match="another inventory update is in progress"):
            commit_add_resource(
                plan,
                expected_revision=plan.original_revision,
                expected_plan=plan.plan_token,
            )
    finally:
        _release_lock(descriptor, lock)

    assert target.read_bytes() == original
    assert lock.is_file()
    assert not (target.parent / ".quartermaster-backups").exists()

    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )
    assert receipt.replacement_verified is True


def test_non_utf8_inventory_is_rejected_before_planning(tmp_path: Path) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_bytes(b"\xff\xfe")
    if os.name == "posix":
        target.chmod(0o600)

    with pytest.raises(ConfigurationError, match="cannot read UTF-8 configuration"):
        plan_add_resource(target, _resource())


@pytest.mark.skipif(os.name != "posix", reason="POSIX backup mode contract")
def test_insecure_existing_backup_directory_refuses_apply(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    backup_directory = target.parent / ".quartermaster-backups"
    backup_directory.mkdir(mode=0o755)
    backup_directory.chmod(0o755)
    plan = plan_add_resource(target, _resource())

    with pytest.raises(StorageError, match="insecure backup root mode"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original


def test_temporary_file_creation_failure_preserves_active_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())

    def fail_temp(*_args, **_kwargs):
        raise OSError("synthetic temporary-file failure")

    monkeypatch.setattr(inventory_edit.tempfile, "mkstemp", fail_temp)
    with pytest.raises(StorageError, match="cannot create inventory update temporary file"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original
    assert len(list((target.parent / ".quartermaster-backups").rglob("inventory-*.yaml"))) == 1


def test_candidate_temp_preserves_exact_lf_bytes(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    content = "first line\nsecond line\n"

    temp_path = inventory_edit._write_candidate_temp(target, content)
    try:
        assert temp_path.read_bytes() == content.encode("utf-8")
    finally:
        temp_path.unlink()


def test_edit_during_update_is_detected_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    concurrent = original + b"# concurrent edit during update\n"
    real_backup = inventory_edit._backup_current

    def backup_then_edit(path: Path, raw: bytes):
        result = real_backup(path, raw)
        path.write_bytes(concurrent)
        return result

    monkeypatch.setattr(inventory_edit, "_backup_current", backup_then_edit)
    with pytest.raises(StorageError, match="changed during update"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == concurrent


def test_post_replace_revision_mismatch_returns_uncertain_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    plan = plan_add_resource(target, _resource())
    real_read = inventory_edit.read_inventory_file
    calls = 0

    def mismatch_fourth_read(path: Path):
        nonlocal calls
        calls += 1
        result = real_read(path)
        if calls == 4:
            return inventory_edit.InventoryFile(
                path=result.path,
                raw=result.raw,
                revision="sha256:synthetic-mismatch",
                inventory=result.inventory,
            )
        return result

    monkeypatch.setattr(inventory_edit, "read_inventory_file", mismatch_fourth_read)
    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.replacement_verified is False
    assert receipt.revision == "sha256:synthetic-mismatch"
    assert "observed revision differs" in receipt.warnings[0]


def test_post_replace_verification_failure_returns_applied_uncertain_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    plan = plan_add_resource(target, _resource())
    real_read = inventory_edit.read_inventory_file
    calls = 0

    def fail_fourth_read(path: Path):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise ConfigurationError("synthetic verification failure")
        return real_read(path)

    monkeypatch.setattr(inventory_edit, "read_inventory_file", fail_fourth_read)
    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.replacement_verified is False
    assert receipt.revision is None
    assert receipt.candidate_revision == plan.candidate_revision
    assert receipt.warnings == (
        "inventory was replaced, but post-replacement verification failed: "
        "synthetic verification failure",
    )
    assert [resource.id for resource in InventoryCatalog.from_path(target).inventory.resources] == [
        "personal-tool"
    ]


def test_post_replace_raw_io_failure_returns_applied_uncertain_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    plan = plan_add_resource(target, _resource())
    real_read = inventory_edit.read_inventory_file
    calls = 0

    def fail_fourth_read(path: Path):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("synthetic raw verification failure")
        return real_read(path)

    monkeypatch.setattr(inventory_edit, "read_inventory_file", fail_fourth_read)
    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.replacement_verified is False
    assert receipt.revision is None
    assert receipt.warnings == (
        "inventory was replaced, but post-replacement verification failed: "
        "synthetic raw verification failure",
    )
    assert [resource.id for resource in InventoryCatalog.from_path(target).inventory.resources] == [
        "personal-tool"
    ]


def test_post_commit_lock_cleanup_failure_is_a_receipt_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    plan = plan_add_resource(target, _resource())
    real_release = inventory_edit._release_lock

    def release_then_report(descriptor: int, lock_path: Path) -> None:
        real_release(descriptor, lock_path)
        raise StorageError("synthetic lock cleanup uncertainty")

    monkeypatch.setattr(inventory_edit, "_release_lock", release_then_report)
    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.replacement_verified is True
    assert receipt.revision == plan.candidate_revision
    assert receipt.warnings == ("synthetic lock cleanup uncertainty",)


def test_read_and_plan_reject_missing_nonregular_and_oversized_targets(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="configuration file does not exist"):
        plan_add_resource(tmp_path / "missing.yaml", _resource())

    directory_target = tmp_path / "directory.yaml"
    directory_target.mkdir()
    with pytest.raises(ConfigurationError, match="not a regular file"):
        plan_add_resource(directory_target, _resource())

    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    if os.name == "posix":
        oversized.chmod(0o600)
    with pytest.raises(ConfigurationError, match="configuration exceeds"):
        plan_add_resource(oversized, _resource())

    parent_file = tmp_path / "parent-file"
    parent_file.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(StorageError, match="non-directory AtReady path"):
        plan_add_resource(parent_file / "inventory.yaml", _resource())

    with pytest.raises(StorageError, match="cannot inspect inventory directory"):
        plan_add_resource(tmp_path / "missing-parent" / "inventory.yaml", _resource())


def test_inventory_open_failure_is_wrapped_as_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)

    def fail_open(*_args, **_kwargs):
        raise OSError("synthetic open failure")

    monkeypatch.setattr(inventory_edit.os, "open", fail_open)
    with pytest.raises(ConfigurationError, match="cannot open inventory"):
        read_inventory_file(target)


@pytest.mark.skipif(
    not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"),
    reason="FIFO substitution regression requires POSIX nonblocking descriptors",
)
def test_inventory_fifo_substitution_cannot_block_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    real_open = inventory_edit.os.open

    def substitute_fifo(path: Path, flags: int, *args: object) -> int:
        assert flags & os.O_NONBLOCK
        target.unlink()
        os.mkfifo(target, mode=0o600)
        return real_open(path, flags, *args)

    monkeypatch.setattr(inventory_edit.os, "open", substitute_fifo)

    with pytest.raises(ConfigurationError, match="not a regular file"):
        read_inventory_file(target)


def test_inventory_mutation_during_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    acl_checks = 0

    def mutate_after_read(_descriptor: int) -> bool:
        nonlocal acl_checks
        acl_checks += 1
        if acl_checks == 2:
            target.write_text(target.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
        return False

    monkeypatch.setattr(inventory_edit, "darwin_fd_has_extended_acl", mutate_after_read)

    with pytest.raises(ConfigurationError, match="changed while it was being read"):
        read_inventory_file(target)


def test_inventory_reader_compares_final_path_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    real_lstat = Path.lstat
    inspections = 0

    def mutate_before_final_lstat(path: Path):
        nonlocal inspections
        if path == target:
            inspections += 1
            if inspections == 2:
                target.write_text(
                    target.read_text(encoding="utf-8") + "# changed\n",
                    encoding="utf-8",
                )
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", mutate_before_final_lstat)

    with pytest.raises(ConfigurationError, match="changed while it was being read"):
        read_inventory_file(target)


def test_inventory_close_failure_is_wrapped_as_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    real_close = inventory_edit.os.close

    def close_then_fail(descriptor: int) -> None:
        real_close(descriptor)
        raise OSError("synthetic close failure")

    monkeypatch.setattr(inventory_edit.os, "close", close_then_fail)
    with pytest.raises(ConfigurationError, match="cannot close inventory descriptor") as caught:
        read_inventory_file(target)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    traceback = caught.value.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name in {"_read_regular_bytes", "read_inventory_file"}:
            assert not isinstance(traceback.tb_frame.f_locals.get("raw"), bytes)
        traceback = traceback.tb_next


def test_inventory_post_read_inspection_failure_does_not_retain_raw_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target, private_notes="SYNTHETIC-PRIVATE-SENTINEL")
    real_fstat = inventory_edit.os.fstat
    inspections = 0

    def fail_second_inspection(descriptor: int):
        nonlocal inspections
        inspections += 1
        if inspections == 2:
            raise OSError("synthetic post-read inspection failure")
        return real_fstat(descriptor)

    monkeypatch.setattr(inventory_edit.os, "fstat", fail_second_inspection)

    with pytest.raises(ConfigurationError, match="cannot verify inventory after reading") as caught:
        read_inventory_file(target)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    traceback = caught.value.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name in {"_read_regular_bytes", "read_inventory_file"}:
            assert traceback.tb_frame.f_locals.get("raw") != original
        traceback = traceback.tb_next


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock mode contract")
def test_unsafe_existing_lock_files_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    lock = target.with_name(f".{target.name}.lock")
    lock.write_text("unsafe mode\n", encoding="utf-8")
    lock.chmod(0o644)

    with pytest.raises(StorageError, match="insecure inventory update lock mode"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
    assert target.read_bytes() == original

    lock.unlink()
    lock_target = tmp_path / "lock-target"
    lock_target.write_text("redirect\n", encoding="utf-8")
    lock.symlink_to(lock_target)
    with pytest.raises(StorageError, match="cannot open inventory update lock"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock ACL contract")
def test_lock_with_extended_acl_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    monkeypatch.setattr(inventory_edit, "darwin_fd_has_extended_acl", lambda _fd: True)

    with pytest.raises(StorageError, match="update lock with a macOS extended ACL"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original


def test_corrupt_existing_backup_refuses_replacement(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    _, backup = inventory_edit._backup_current(target, original)
    backup.write_text("not the original inventory\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original


def test_temporary_write_failure_is_wrapped_and_temp_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    inventory_edit._backup_current(target, original)
    sentinel = "SYNTHETIC-PRIVATE-WRITE-FAILURE"
    real_mkstemp = inventory_edit.tempfile.mkstemp
    real_write = inventory_edit.os.write
    candidate_descriptors: set[int] = set()

    def track_candidate_temp(*args, **kwargs):
        descriptor, path = real_mkstemp(*args, **kwargs)
        candidate_descriptors.add(descriptor)
        return descriptor, path

    def fail_candidate_write(descriptor: int, raw: bytes) -> int:
        if descriptor in candidate_descriptors:
            raise OSError(sentinel)
        return real_write(descriptor, raw)

    monkeypatch.setattr(inventory_edit.tempfile, "mkstemp", track_candidate_temp)
    monkeypatch.setattr(inventory_edit.os, "write", fail_candidate_write)
    with pytest.raises(
        StorageError, match="cannot write inventory update temporary file"
    ) as caught:
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert target.read_bytes() == original
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_corrupted_plan_candidate_is_refused_before_backup(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    corrupted = replace(plan, candidate_revision="sha256:corrupted-candidate")

    with pytest.raises(StorageError, match="inventory candidate changed after preview"):
        commit_add_resource(
            corrupted,
            expected_revision=corrupted.original_revision,
            expected_plan=corrupted.plan_token,
        )

    assert target.read_bytes() == original
    assert not (target.parent / ".quartermaster-backups").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory fsync contract")
def test_directory_fsync_failure_is_reported_as_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_fsync(_descriptor: int) -> None:
        raise OSError("synthetic directory fsync failure")

    monkeypatch.setattr(inventory_edit.os, "fsync", fail_fsync)
    assert inventory_edit._fsync_directory(tmp_path) is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory fsync contract")
def test_directory_close_failure_is_reported_as_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_close = inventory_edit.os.close

    def close_then_fail(descriptor: int) -> None:
        real_close(descriptor)
        raise OSError("synthetic close failure")

    monkeypatch.setattr(inventory_edit.os, "close", close_then_fail)
    assert inventory_edit._fsync_directory(tmp_path) is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX backup durability contract")
def test_backup_directory_sync_failure_refuses_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())

    monkeypatch.setattr(inventory_edit, "_fsync_directory", lambda _path: False)
    with pytest.raises(StorageError, match="cannot sync target backup directory"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original
    backups = list((target.parent / ".quartermaster-backups").rglob("inventory-*.yaml"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


@pytest.mark.skipif(os.name != "posix", reason="POSIX backup durability contract")
def test_backup_parent_sync_failure_refuses_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    synced: list[Path] = []

    def fail_parent_sync(path: Path) -> bool:
        synced.append(path)
        return path.name.startswith("target-") or path.name == ".quartermaster-backups"

    monkeypatch.setattr(inventory_edit, "_fsync_directory", fail_parent_sync)
    with pytest.raises(StorageError, match="cannot sync inventory directory after private backup"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    backup_root = target.parent / ".quartermaster-backups"
    assert synced == [
        backup_root / inventory_edit._backup_namespace(target),
        backup_root,
        target.parent,
    ]
    assert target.read_bytes() == original
    backups = list((target.parent / ".quartermaster-backups").rglob("inventory-*.yaml"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_directory_identity_substitution_after_preview_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())

    displaced_parent = tmp_path / "displaced-private"
    target.parent.rename(displaced_parent)
    replacement_target = tmp_path / "private" / "inventory.yaml"
    create_private_file(replacement_target, original.decode("utf-8"))

    with pytest.raises(StorageError, match="target identity changed after preview"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert replacement_target.read_bytes() == original
    assert (displaced_parent / "inventory.yaml").read_bytes() == original
    assert not (replacement_target.parent / ".quartermaster-backups").exists()


def test_backup_listing_is_read_only_and_scoped_per_logical_target(tmp_path: Path) -> None:
    parent = tmp_path / "private"
    target_a = parent / "alpha.yaml"
    target_b = parent / "bravo.yaml"
    _personal_file(target_a, private_notes="alpha-only")
    _personal_file(target_b, private_notes="bravo-only")

    empty = list_inventory_backups(target_a)
    assert empty.backups == ()
    assert empty.warnings == ()
    assert not (parent / ".quartermaster-backups").exists()

    receipt_a = _apply_resource(target_a, "alpha-tool")
    listing_a = list_inventory_backups(target_a)
    listing_b = list_inventory_backups(target_b)
    assert [backup.backup_id for backup in listing_a.backups] == [receipt_a.backup_id]
    assert listing_b.backups == ()
    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        inspect_inventory_backup(target_b, receipt_a.backup_id)

    receipt_b = _apply_resource(target_b, "bravo-tool")
    assert receipt_a.backup_id != receipt_b.backup_id
    assert receipt_a.backup_path.parent != receipt_b.backup_path.parent
    assert [backup.backup_id for backup in list_inventory_backups(target_b).backups] == [
        receipt_b.backup_id
    ]


def test_case_variant_aliases_share_a_physical_namespace_or_are_refused(tmp_path: Path) -> None:
    physical = tmp_path / "Inventory.yaml"
    alias = tmp_path / "inventory.yaml"
    _personal_file(physical)
    if not alias.exists() or not physical.samefile(alias):
        pytest.skip("test requires a case-insensitive filesystem")
    if os.name == "posix" and sys.platform != "darwin":
        with pytest.raises(
            StorageError,
            match="refusing case-insensitive non-Darwin POSIX inventory directory",
        ):
            plan_add_resource(alias, _resource("case-tool"))
        assert not physical.with_name(f".{physical.name}.lock").exists()
        assert not (physical.parent / ".quartermaster-backups").exists()
        return

    plan = plan_add_resource(alias, _resource("case-tool"))
    assert plan.target.name == physical.name
    receipt = commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    for spelling in (physical, alias):
        listing = list_inventory_backups(spelling)
        assert listing.namespace == inventory_edit._backup_namespace(plan.target)
        assert [backup.backup_id for backup in listing.backups] == [receipt.backup_id]


def test_case_probe_varies_every_ascii_cased_position() -> None:
    assert inventory_edit._ascii_case_variants("aB1") == ("AB1", "ab1")
    assert inventory_edit._ascii_case_variants("123-_.456") == ()


@pytest.mark.parametrize(
    ("platform", "os_name", "contract"),
    [
        ("darwin", "posix", inventory_edit._CASE_PHYSICAL),
        ("linux", "posix", inventory_edit._CASE_SENSITIVE),
        ("win32", "nt", inventory_edit._CASE_INSENSITIVE),
    ],
)
def test_case_contract_is_explicit_per_platform(
    platform: str,
    os_name: str,
    contract: str,
) -> None:
    assert inventory_edit._case_contract_for(platform, os_name) == contract


def test_case_contract_rejects_an_unknown_platform() -> None:
    with pytest.raises(StorageError, match="unsupported filesystem case-semantics platform"):
        inventory_edit._case_contract_for("mystery", "mystery")


def test_case_observation_classifier_requires_two_stable_known_identities(
    tmp_path: Path,
) -> None:
    target = tmp_path / "inventory.yaml"
    _personal_file(target)
    details = target.lstat()
    same = (details.st_dev, details.st_ino, 1, stat.S_IFREG)
    different = (details.st_dev, details.st_ino + 1, 1, stat.S_IFREG)

    assert (
        inventory_edit._classify_case_observations(
            target,
            target=details,
            first=same,
            second=same,
        )
        == inventory_edit._CASE_INSENSITIVE
    )
    for observation in (None, different):
        assert (
            inventory_edit._classify_case_observations(
                target,
                target=details,
                first=observation,
                second=observation,
            )
            == inventory_edit._CASE_SENSITIVE
        )

    with pytest.raises(StorageError, match="cannot verify filesystem case semantics"):
        inventory_edit._classify_case_observations(
            target,
            target=details,
            first=None,
            second=different,
        )
    with pytest.raises(StorageError, match="cannot verify filesystem case semantics"):
        inventory_edit._classify_case_observations(
            target,
            target=details,
            first=(details.st_dev, details.st_ino, 2, stat.S_IFREG),
            second=(details.st_dev, details.st_ino, 2, stat.S_IFREG),
        )


def test_case_observation_rejects_an_unknown_zero_identity(tmp_path: Path) -> None:
    target = tmp_path / "inventory.yaml"
    with pytest.raises(StorageError, match="cannot verify filesystem case semantics"):
        inventory_edit._case_entry_observation(
            SimpleNamespace(st_dev=7, st_ino=0, st_nlink=1, st_mode=stat.S_IFREG),
            path=target,
        )


def test_case_probe_requires_uniform_behavior_at_every_position(tmp_path: Path) -> None:
    target = tmp_path / "inventory.yaml"
    assert (
        inventory_edit._require_uniform_case_semantics(
            target,
            (inventory_edit._CASE_SENSITIVE, inventory_edit._CASE_SENSITIVE),
        )
        == inventory_edit._CASE_SENSITIVE
    )
    with pytest.raises(StorageError, match="cannot verify filesystem case semantics"):
        inventory_edit._require_uniform_case_semantics(
            target,
            (inventory_edit._CASE_SENSITIVE, inventory_edit._CASE_INSENSITIVE),
        )


def test_case_probe_rejects_a_non_caseable_filename_off_darwin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "123-_.456"
    _personal_file(target)
    monkeypatch.setattr(
        inventory_edit,
        "_platform_case_contract",
        lambda: inventory_edit._CASE_SENSITIVE,
    )

    with pytest.raises(StorageError, match="inventory filename has no ASCII letter"):
        plan_add_resource(target, _resource())
    assert not target.with_name(f".{target.name}.lock").exists()
    assert not (target.parent / ".quartermaster-backups").exists()


@pytest.mark.parametrize(
    "contract",
    [inventory_edit._CASE_SENSITIVE, inventory_edit._CASE_INSENSITIVE],
)
def test_case_probe_rejects_a_non_ascii_filename_off_darwin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract: str,
) -> None:
    target = tmp_path / "private" / "inventorý.yaml"
    _personal_file(target)
    monkeypatch.setattr(inventory_edit, "_platform_case_contract", lambda: contract)

    def unexpected_probe(*_args, **_kwargs):
        pytest.fail("non-ASCII basename must fail before probing an alias")

    monkeypatch.setattr(inventory_edit, "_observe_case_semantics", unexpected_probe)
    with pytest.raises(StorageError, match="inventory filename is not ASCII"):
        plan_add_resource(target, _resource())
    assert not target.with_name(f".{target.name}.lock").exists()
    assert not (target.parent / ".quartermaster-backups").exists()


@pytest.mark.parametrize(
    ("contract", "observed", "message"),
    [
        (
            inventory_edit._CASE_SENSITIVE,
            inventory_edit._CASE_INSENSITIVE,
            "refusing case-insensitive non-Darwin POSIX inventory directory",
        ),
        (
            inventory_edit._CASE_INSENSITIVE,
            inventory_edit._CASE_SENSITIVE,
            "refusing case-sensitive Windows inventory directory",
        ),
    ],
)
def test_case_contract_mismatch_refuses_before_creating_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract: str,
    observed: str,
    message: str,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    monkeypatch.setattr(inventory_edit, "_platform_case_contract", lambda: contract)
    monkeypatch.setattr(
        inventory_edit,
        "_observe_case_semantics",
        lambda *_args, **_kwargs: observed,
    )

    with pytest.raises(StorageError, match=message):
        plan_add_resource(target, _resource())
    assert not target.with_name(f".{target.name}.lock").exists()
    assert not (target.parent / ".quartermaster-backups").exists()


def test_case_probe_is_read_only_on_the_platform_default(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    before = {entry.name for entry in target.parent.iterdir()}

    inventory_edit._validate_supported_case_semantics(target)

    assert {entry.name for entry in target.parent.iterdir()} == before
    assert not target.with_name(f".{target.name}.lock").exists()
    assert not (target.parent / ".quartermaster-backups").exists()


def test_case_probe_never_opens_for_write_or_calls_mutators(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    variants = inventory_edit._ascii_case_variants(target.name)
    assert variants
    observed = inventory_edit._observe_case_semantics(
        target,
        variants,
        target=target.lstat(),
        parent=target.parent.lstat(),
    )
    monkeypatch.setattr(inventory_edit, "_platform_case_contract", lambda: observed)

    def forbidden(*_args, **_kwargs):
        pytest.fail("case probe must not create, enumerate, replace, rename, or delete state")

    original_open = os.open
    write_flags = 0
    for name in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_EXCL", "O_TRUNC", "O_APPEND"):
        write_flags |= int(getattr(os, name, 0))

    def read_only_open(path, flags, *args, **kwargs):
        assert flags & write_flags == 0
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", read_only_open)
    for name in ("mkdir", "remove", "unlink", "replace", "rename", "scandir"):
        monkeypatch.setattr(os, name, forbidden)
    for name in ("mkdir", "unlink", "replace", "rename", "write_bytes", "write_text"):
        monkeypatch.setattr(Path, name, forbidden)
    monkeypatch.setattr(inventory_edit.tempfile, "mkstemp", forbidden)
    monkeypatch.setattr(inventory_edit.tempfile, "NamedTemporaryFile", forbidden)

    inventory_edit._validate_supported_case_semantics(target)


@pytest.mark.skipif(os.name != "posix", reason="requires descriptor-relative POSIX lookup")
def test_posix_case_observer_classifies_the_live_filesystem(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    target_details = target.lstat()
    parent_details = target.parent.lstat()
    variants = inventory_edit._ascii_case_variants(target.name)
    assert variants
    alias = target.with_name(variants[0])
    expected = (
        inventory_edit._CASE_INSENSITIVE
        if alias.exists() and alias.samefile(target)
        else inventory_edit._CASE_SENSITIVE
    )

    assert (
        inventory_edit._observe_posix_case_semantics(
            target,
            variants,
            target=target_details,
            parent=parent_details,
        )
        == expected
    )


def test_direct_case_entry_reports_a_missing_name(tmp_path: Path) -> None:
    target = tmp_path / "inventory.yaml"
    _personal_file(target)
    assert inventory_edit._direct_case_entry(target, "definitely-missing.entry") is None


@pytest.mark.skipif(os.name != "posix", reason="requires descriptor-relative POSIX lookup")
def test_posix_case_probe_refuses_missing_runtime_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "inventory.yaml"
    _personal_file(target)
    monkeypatch.setattr(os, "supports_dir_fd", set())

    with pytest.raises(StorageError, match="cannot verify filesystem case semantics"):
        inventory_edit._observe_posix_case_semantics(
            target,
            ("Inventory.yaml",),
            target=target.lstat(),
            parent=target.parent.lstat(),
        )


@pytest.mark.skipif(
    os.name != "posix" or sys.platform == "darwin",
    reason="requires a non-Darwin POSIX filesystem",
)
def test_non_darwin_posix_live_semantics_are_accepted_or_refused(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    details = target.lstat()
    parent = target.parent.lstat()
    variants = inventory_edit._ascii_case_variants(target.name)
    assert variants

    observed = inventory_edit._observe_posix_case_semantics(
        target,
        variants,
        target=details,
        parent=parent,
    )
    if observed == inventory_edit._CASE_SENSITIVE:
        inventory_edit._validate_supported_case_semantics(target)
    else:
        with pytest.raises(
            StorageError,
            match="refusing case-insensitive non-Darwin POSIX inventory directory",
        ):
            inventory_edit._validate_supported_case_semantics(target)


@pytest.mark.skipif(os.name != "nt", reason="requires ordinary Windows path semantics")
def test_windows_default_is_observed_as_case_insensitive(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    details = target.lstat()
    parent = target.parent.lstat()
    variants = inventory_edit._ascii_case_variants(target.name)
    assert variants

    assert (
        inventory_edit._observe_direct_case_semantics(
            target,
            variants,
            target=details,
            parent=parent,
        )
        == inventory_edit._CASE_INSENSITIVE
    )


@pytest.mark.skipif(
    os.name != "posix" or sys.platform == "darwin",
    reason="requires distinct case-only POSIX entries",
)
def test_case_only_posix_targets_keep_distinct_backup_namespaces(tmp_path: Path) -> None:
    lower = tmp_path / "private" / "inventory.yaml"
    upper = lower.with_name("Inventory.yaml")
    original = _personal_file(lower)
    if upper.exists() and upper.samefile(lower):
        pytest.skip("requires distinct case-only entries on this POSIX filesystem")
    create_private_file(upper, original.decode("utf-8"))

    lower_receipt = _apply_resource(lower, "shared-tool")
    upper_receipt = _apply_resource(upper, "shared-tool")

    lower_listing = list_inventory_backups(lower)
    upper_listing = list_inventory_backups(upper)
    assert lower_listing.namespace != upper_listing.namespace
    assert lower_receipt.backup_id == upper_receipt.backup_id
    assert lower_receipt.backup_path != upper_receipt.backup_path
    assert [backup.backup_id for backup in lower_listing.backups] == [lower_receipt.backup_id]
    assert [backup.backup_id for backup in upper_listing.backups] == [upper_receipt.backup_id]


@pytest.mark.skipif(
    os.name != "posix" or sys.platform == "darwin",
    reason="requires distinct case-only POSIX entries",
)
def test_case_variant_hard_link_is_refused_before_classification(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    alias = target.with_name("Inventory.yaml")
    if alias.exists() and alias.samefile(target):
        pytest.skip("requires distinct case-only entries on this POSIX filesystem")
    os.link(target, alias)

    with pytest.raises(StorageError, match="hard-linked inventory update target"):
        plan_add_resource(target, _resource())
    assert not target.with_name(f".{target.name}.lock").exists()
    assert not (target.parent / ".quartermaster-backups").exists()


@pytest.mark.skipif(
    os.name != "posix" or sys.platform == "darwin",
    reason="requires distinct case-only POSIX entries",
)
def test_case_variant_symlink_is_not_followed_by_the_probe(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    alias = target.with_name("Inventory.yaml")
    if alias.exists() and alias.samefile(target):
        pytest.skip("requires distinct case-only entries on this POSIX filesystem")
    alias.symlink_to(target.name)

    plan = plan_add_resource(target, _resource())

    assert plan.target == target
    with pytest.raises(ConfigurationError, match="symlinked configuration"):
        plan_add_resource(alias, _resource())


@pytest.mark.skipif(os.name != "posix", reason="requires descriptor-relative POSIX lookup")
def test_posix_case_probe_rejects_a_replaced_live_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    target_details = target.lstat()
    parent_details = target.parent.lstat()
    variants = inventory_edit._ascii_case_variants(target.name)
    assert variants
    displaced = tmp_path / "displaced"
    calls = 0

    def replace_parent(_descriptor: int, _name: str, *, path: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.parent.rename(displaced)
            _personal_file(path)
        return None

    monkeypatch.setattr(inventory_edit, "_posix_case_entry", replace_parent)
    with pytest.raises(StorageError, match="cannot verify filesystem case semantics"):
        inventory_edit._observe_posix_case_semantics(
            target,
            variants,
            target=target_details,
            parent=parent_details,
        )


@pytest.mark.skipif(os.name != "posix", reason="requires descriptor-relative POSIX lookup")
def test_posix_case_probe_redacts_lookup_errors(tmp_path: Path) -> None:
    target = tmp_path / "inventory.yaml"
    private_variant = "Private-Case-Probe.yaml"

    with pytest.raises(StorageError) as raised:
        inventory_edit._posix_case_entry(-1, private_variant, path=target)
    assert "cannot verify filesystem case semantics" in str(raised.value)
    assert private_variant not in str(raised.value)


def test_direct_case_probe_rejects_redacted_lookup_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "inventory.yaml"
    _personal_file(target)
    variants = inventory_edit._ascii_case_variants(target.name)
    assert variants
    variant = variants[0]
    original_lstat = Path.lstat

    def fail_variant(path: Path):
        if path.name == variant:
            raise PermissionError(f"private probe name {variant}")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_variant)
    with pytest.raises(StorageError) as raised:
        inventory_edit._direct_case_entry(target, variant)
    assert "cannot verify filesystem case semantics" in str(raised.value)
    assert variant not in str(raised.value)


@pytest.mark.parametrize("drift", ["target", "parent"])
def test_direct_case_probe_rejects_target_or_parent_snapshot_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    target_details = target.lstat()
    parent_details = target.parent.lstat()
    variants = inventory_edit._ascii_case_variants(target.name)
    assert variants
    calls = 0

    def mutate_once(_path: Path, _variant: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            if drift == "target":
                target.write_bytes(target.read_bytes() + b"\n")
            else:
                os.utime(
                    target.parent,
                    ns=(parent_details.st_atime_ns, parent_details.st_mtime_ns + 1_000_000_000),
                )
        return None

    monkeypatch.setattr(inventory_edit, "_direct_case_entry", mutate_once)
    with pytest.raises(StorageError, match="cannot verify filesystem case semantics"):
        inventory_edit._observe_direct_case_semantics(
            target,
            variants,
            target=target_details,
            parent=parent_details,
        )


def test_case_gate_covers_every_backup_namespace_consumer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    receipt = _apply_resource(target, "tool-one")

    def refuse(_path: Path) -> None:
        raise StorageError("case gate sentinel")

    monkeypatch.setattr(inventory_edit, "_validate_supported_case_semantics", refuse)
    operations = (
        lambda: plan_add_resource(target, _resource("tool-two")),
        lambda: list_inventory_backups(target),
        lambda: inspect_inventory_backup(target, receipt.backup_id),
        lambda: plan_inventory_rollback(target, receipt.backup_id),
        lambda: plan_inventory_backup_delete(
            target,
            receipt.backup_id,
            allow_no_backups=True,
        ),
    )
    for operation in operations:
        with pytest.raises(StorageError, match="case gate sentinel"):
            operation()


def test_add_apply_rechecks_case_contract_before_locking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())

    def refuse(_path: Path) -> None:
        raise StorageError("case gate sentinel")

    def unexpected_lock(_path: Path) -> tuple[int, Path]:
        pytest.fail("case refusal must happen before lock creation")

    monkeypatch.setattr(inventory_edit, "_validate_supported_case_semantics", refuse)
    monkeypatch.setattr(inventory_edit, "_acquire_lock", unexpected_lock)
    with pytest.raises(StorageError, match="case gate sentinel"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
    assert target.read_bytes() == original
    assert not target.with_name(f".{target.name}.lock").exists()
    assert not (target.parent / ".quartermaster-backups").exists()


def test_add_apply_rechecks_case_contract_under_lock_before_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource())
    checks = 0

    def refuse_second_check(_path: Path) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise StorageError("under-lock case gate sentinel")

    def unexpected_mutation(*_args, **_kwargs):
        pytest.fail("under-lock case refusal must happen before backup or replacement")

    monkeypatch.setattr(
        inventory_edit,
        "_validate_supported_case_semantics",
        refuse_second_check,
    )
    monkeypatch.setattr(inventory_edit, "_backup_current", unexpected_mutation)
    monkeypatch.setattr(inventory_edit, "_write_candidate_temp", unexpected_mutation)
    monkeypatch.setattr(os, "replace", unexpected_mutation)
    with pytest.raises(StorageError, match="under-lock case gate sentinel"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
    assert checks == 2
    assert target.read_bytes() == original
    assert not (target.parent / ".quartermaster-backups").exists()


def test_backup_delete_rechecks_case_contract_before_locking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    receipt = _apply_resource(target, "tool-one")
    plan = plan_inventory_backup_delete(
        target,
        receipt.backup_id,
        allow_no_backups=True,
    )

    def refuse(_path: Path) -> None:
        raise StorageError("case gate sentinel")

    def unexpected_lock(_path: Path) -> tuple[int, Path]:
        pytest.fail("case refusal must happen before lock acquisition")

    monkeypatch.setattr(inventory_edit, "_validate_supported_case_semantics", refuse)
    monkeypatch.setattr(inventory_edit, "_acquire_lock", unexpected_lock)
    with pytest.raises(StorageError, match="case gate sentinel"):
        commit_inventory_backup_delete(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
    assert receipt.backup_path.exists()


def test_backup_delete_rechecks_case_contract_under_lock_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    receipt = _apply_resource(target, "tool-one")
    plan = plan_inventory_backup_delete(
        target,
        receipt.backup_id,
        allow_no_backups=True,
    )
    checks = 0

    def refuse_second_check(_path: Path) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise StorageError("under-lock case gate sentinel")

    def unexpected_unlink(*_args, **_kwargs):
        pytest.fail("under-lock case refusal must happen before backup deletion")

    monkeypatch.setattr(
        inventory_edit,
        "_validate_supported_case_semantics",
        refuse_second_check,
    )
    monkeypatch.setattr(Path, "unlink", unexpected_unlink)
    with pytest.raises(
        StorageError,
        match="backup target or validated backup set changed after preview",
    ) as raised:
        commit_inventory_backup_delete(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
    assert raised.value.__cause__ is not None
    assert "under-lock case gate sentinel" in str(raised.value.__cause__)
    assert checks == 2
    assert receipt.backup_path.exists()


def test_identical_backup_ids_remain_isolated_between_two_targets(tmp_path: Path) -> None:
    target_a = tmp_path / "private" / "alpha.yaml"
    target_b = tmp_path / "private" / "bravo.yaml"
    original_a = _personal_file(target_a)
    create_private_file(target_b, original_a.decode("utf-8"))
    original_b = target_b.read_bytes()
    receipt_a = _apply_resource(target_a, "shared-tool")
    receipt_b = _apply_resource(target_b, "shared-tool")

    assert receipt_a.backup_id == receipt_b.backup_id
    assert receipt_a.backup_path != receipt_b.backup_path
    delete_a = plan_inventory_backup_delete(
        target_a,
        receipt_a.backup_id,
        allow_no_backups=True,
    )
    commit_inventory_backup_delete(
        delete_a,
        expected_revision=delete_a.original_revision,
        expected_plan=delete_a.plan_token,
    )

    assert list_inventory_backups(target_a).backups == ()
    assert receipt_b.backup_path.exists()
    rollback_b = plan_inventory_rollback(target_b, receipt_b.backup_id)
    commit_inventory_rollback(
        rollback_b,
        expected_revision=rollback_b.original_revision,
        expected_plan=rollback_b.plan_token,
    )
    assert target_b.read_bytes() == original_b
    assert target_a.read_bytes() != original_a


@pytest.mark.parametrize(
    "backup_id",
    [
        "../inventory.yaml",
        "sha256:abc",
        "sha256:" + "A" * 64,
        "sha512:" + "a" * 64,
        "sha256:" + "a" * 65,
    ],
)
def test_backup_ids_are_exact_lowercase_sha256_values(tmp_path: Path, backup_id: str) -> None:
    target = tmp_path / "inventory.yaml"
    _personal_file(target)

    with pytest.raises(ConfigurationError, match="64 lowercase hex digits"):
        inspect_inventory_backup(target, backup_id)


def test_backup_inspection_redacts_private_notes_and_compares_routing_state(
    tmp_path: Path,
) -> None:
    target = tmp_path / "inventory.yaml"
    sentinel = "DO-NOT-EXPOSE-PRIVATE-BACKUP-NOTE"
    _personal_file(target, private_notes=sentinel)
    receipt = _apply_resource(target, "new-tool")

    inspection = inspect_inventory_backup(target, receipt.backup_id)
    result = inspection.as_dict()

    assert sentinel not in repr(result)
    assert result["private_notes_exposed"] is False
    assert result["backup"]["resource_count"] == 0
    assert result["comparison"]["resource_changes"] == {
        "added": [],
        "changed": [],
        "removed": ["new-tool"],
    }
    assert result["comparison"]["inventory_private_notes"] == "unchanged"
    assert result["comparison"]["revision_privacy_nonce_effect"] == "unchanged"
    assert "private_notes" not in repr(result["backup_snapshot"])


def test_rollback_preview_flags_hidden_revision_nonce_change(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    receipt = _apply_resource(target, "new-tool")
    current = target.read_text(encoding="utf-8")
    active_nonce = InventoryCatalog.from_text(current).inventory.revision_privacy_nonce
    assert active_nonce is not None
    replacement_nonce = "nonce-v1:" + (
        "f" * 64 if not active_nonce.endswith("f" * 64) else "e" * 64
    )
    target.write_text(current.replace(active_nonce, replacement_nonce), encoding="utf-8")

    plan = plan_inventory_rollback(target, receipt.backup_id)
    preview = plan.preview()

    assert preview["revision_privacy_nonce_changed"] is True
    assert preview["comparison"]["revision_privacy_nonce_effect"] == "will-change"
    assert active_nonce not in repr(preview)
    assert replacement_nonce not in repr(preview)


def test_legacy_unscoped_backups_are_visible_but_never_selectable(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    raw = _personal_file(target)
    backup_id = inventory_edit._revision(raw)
    digest = backup_id.removeprefix("sha256:")
    legacy = target.parent / ".quartermaster-backups" / f"inventory-{digest}.yaml"
    create_private_file(legacy, raw.decode("utf-8"))

    listing = list_inventory_backups(target)

    assert listing.backups == ()
    assert listing.legacy_unscoped_count == 1
    assert "not selectable" in listing.warnings[0]
    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        inspect_inventory_backup(target, backup_id)


def test_backup_listing_does_not_expose_non_restorable_backup_revision(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    receipt = _apply_resource(target, "new-tool")
    legacy_text = starter_inventory()
    legacy_nonce = InventoryCatalog.from_text(legacy_text).inventory.revision_privacy_nonce
    assert legacy_nonce is not None
    legacy_text = legacy_text.replace(f'revision_privacy_nonce: "{legacy_nonce}"\n', "").replace(
        "resources: []",
        "private_notes: guessable-legacy-note\nresources: []",
    )
    legacy_raw = legacy_text.encode()
    legacy_id = inventory_edit._revision(legacy_raw)
    legacy_path = receipt.backup_path.parent / (
        "inventory-" + legacy_id.removeprefix("sha256:") + ".yaml"
    )
    create_private_file(legacy_path, legacy_text)

    listing = list_inventory_backups(target)

    rendered = repr(listing.warnings)
    assert legacy_id not in rendered
    assert "guessable-legacy-note" not in rendered
    assert "ignored 1 non-restorable target-scoped backup" in rendered


def test_backup_outputs_omit_exact_sizes_and_warn_before_privacy_state_downgrade(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    protected = _apply_resource(target, "new-tool")
    legacy_text = starter_inventory()
    legacy_nonce = InventoryCatalog.from_text(legacy_text).inventory.revision_privacy_nonce
    assert legacy_nonce is not None
    legacy_text = legacy_text.replace(f'revision_privacy_nonce: "{legacy_nonce}"\n', "")
    legacy_id = inventory_edit._revision(legacy_text.encode())
    legacy_path = protected.backup_path.parent / (
        "inventory-" + legacy_id.removeprefix("sha256:") + ".yaml"
    )
    create_private_file(legacy_path, legacy_text)

    listing = list_inventory_backups(target).as_dict()
    plan = plan_inventory_backup_delete(target, protected.backup_id)
    preview = plan.preview()

    assert "total_bytes" not in listing
    assert all("size_bytes" not in backup for backup in listing["backups"])
    assert "bytes_reclaimed" not in preview
    assert preview["selected_revision_protection"] == "nonce-v1-present"
    assert preview["remaining_revision_protection_counts"] == {"legacy-unblinded": 1}
    assert any("leaves no nonce-v1-present backup" in warning for warning in preview["warnings"])


def test_rollback_preview_is_read_only_and_apply_restores_exact_bytes(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original_text = starter_inventory().replace(
        "resources: []", "private_notes: exact-hidden-value\nresources: []"
    )
    original_text += "# exact formatting survives rollback\n"
    create_private_file(target, original_text)
    original = original_text.encode("utf-8")
    source = _apply_resource(target, "first-tool")
    active_before = target.read_bytes()
    lock_path = target.with_name(f".{target.name}.lock")
    lock_path.unlink()

    plan = plan_inventory_rollback(target, source.backup_id)

    assert target.read_bytes() == active_before
    assert source.backup_path.read_bytes() == original
    assert not lock_path.exists()
    assert plan.preview()["restores_hidden_private_notes"] is True
    assert "exact-hidden-value" not in repr(plan.preview())

    receipt = commit_inventory_rollback(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert target.read_bytes() == original
    assert receipt.update.replacement_verified is True
    assert receipt.source_backup_path.read_bytes() == original
    assert receipt.update.backup_path.read_bytes() == active_before
    assert receipt.source_backup_id == source.backup_id
    assert receipt.update.backup_id == inventory_edit._revision(active_before)


def test_rollback_rejects_noop_wrong_tokens_and_changed_source(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    current_id, _ = inventory_edit._backup_current(target, original)
    with pytest.raises(ConfigurationError, match="already matches"):
        plan_inventory_rollback(target, current_id)

    source = _apply_resource(target, "tool-one")
    active = target.read_bytes()
    plan = plan_inventory_rollback(target, source.backup_id)
    with pytest.raises(ConfigurationError, match="expect-revision"):
        commit_inventory_rollback(
            plan,
            expected_revision="sha256:" + "0" * 64,
            expected_plan=plan.plan_token,
        )
    with pytest.raises(ConfigurationError, match="expect-plan"):
        commit_inventory_rollback(
            plan,
            expected_revision=plan.original_revision,
            expected_plan="sha256:" + "0" * 64,
        )

    source.backup_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        commit_inventory_rollback(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
    assert target.read_bytes() == active


def test_rollback_respects_the_shared_inventory_lock(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    source = _apply_resource(target, "tool-one")
    plan = plan_inventory_rollback(target, source.backup_id)
    descriptor, lock_path = _acquire_lock(target)
    try:
        with pytest.raises(StorageError, match="another inventory update is in progress"):
            commit_inventory_rollback(
                plan,
                expected_revision=plan.original_revision,
                expected_plan=plan.plan_token,
            )
    finally:
        _release_lock(descriptor, lock_path)


def test_backup_delete_is_preview_first_and_removes_only_the_selected_backup(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    first = _apply_resource(target, "tool-one")
    second = _apply_resource(target, "tool-two")
    active = target.read_bytes()
    plan = plan_inventory_backup_delete(target, first.backup_id)

    assert plan.preview()["irreversible"] is True
    assert first.backup_path.exists()
    with pytest.raises(ConfigurationError, match="expect-plan"):
        commit_inventory_backup_delete(
            plan,
            expected_revision=plan.original_revision,
            expected_plan="sha256:" + "0" * 64,
        )
    assert first.backup_path.exists()

    receipt = commit_inventory_backup_delete(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.deletion_verified is True
    assert not first.backup_path.exists()
    assert second.backup_path.exists()
    assert target.read_bytes() == active
    assert [backup.backup_id for backup in list_inventory_backups(target).backups] == [
        second.backup_id
    ]


def test_backup_delete_recounts_backups_created_after_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    first = _apply_resource(target, "tool-one")
    second = _apply_resource(target, "tool-two")
    plan = plan_inventory_backup_delete(target, first.backup_id)
    concurrent_raw = target.read_bytes() + b"# concurrent recovery point\n"
    concurrent_id = inventory_edit._revision(concurrent_raw)
    concurrent_path = plan.backup_path.parent / (
        "inventory-" + concurrent_id.removeprefix("sha256:") + ".yaml"
    )
    original_fsync_directory = inventory_edit._fsync_directory
    injected = False

    def inject_concurrent_backup(path: Path) -> bool:
        nonlocal injected
        if not injected and path == plan.backup_path.parent:
            injected = True
            concurrent_path.write_bytes(concurrent_raw)
            if os.name == "posix":
                concurrent_path.chmod(0o600)
        return original_fsync_directory(path)

    monkeypatch.setattr(inventory_edit, "_fsync_directory", inject_concurrent_backup)
    receipt = commit_inventory_backup_delete(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.deletion_verified is True
    assert receipt.remaining_valid_backups == 2
    assert {backup.backup_id for backup in list_inventory_backups(target).backups} == {
        second.backup_id,
        concurrent_id,
    }


def test_backup_delete_warns_and_falls_back_when_recount_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    first = _apply_resource(target, "tool-one")
    _apply_resource(target, "tool-two")
    plan = plan_inventory_backup_delete(target, first.backup_id)
    original_list = inventory_edit._InventoryBackupStore.list
    list_calls = 0

    def fail_recount(store: inventory_edit._InventoryBackupStore):
        nonlocal list_calls
        list_calls += 1
        if list_calls == 2:
            raise StorageError("synthetic recount failure")
        return original_list(store)

    monkeypatch.setattr(inventory_edit._InventoryBackupStore, "list", fail_recount)
    receipt = commit_inventory_backup_delete(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.deletion_verified is True
    assert receipt.remaining_valid_backups == plan.backup_count_before - 1
    assert "could not be recounted" in receipt.warnings[0]


def test_deleting_last_backup_requires_a_bound_explicit_override(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    only = _apply_resource(target, "tool-one")

    with pytest.raises(ConfigurationError, match="requires --allow-no-backups"):
        plan_inventory_backup_delete(target, only.backup_id)
    plan = plan_inventory_backup_delete(
        target,
        only.backup_id,
        allow_no_backups=True,
    )
    assert plan.preview()["allow_no_backups"] is True

    receipt = commit_inventory_backup_delete(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.remaining_valid_backups == 0
    assert list_inventory_backups(target).backups == ()
    assert target.is_file()


def test_backup_set_drift_refuses_delete_without_touching_active_state(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    first = _apply_resource(target, "tool-one")
    _apply_resource(target, "tool-two")
    active = target.read_bytes()
    plan = plan_inventory_backup_delete(target, first.backup_id)
    inventory_edit._backup_current(target, active + b"# extra valid recovery state\n")

    with pytest.raises(StorageError, match="validated backup set changed"):
        commit_inventory_backup_delete(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == active
    assert first.backup_path.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX delete durability contract")
def test_post_unlink_sync_failure_is_applied_but_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    only = _apply_resource(target, "tool-one")
    active = target.read_bytes()
    plan = plan_inventory_backup_delete(
        target,
        only.backup_id,
        allow_no_backups=True,
    )
    monkeypatch.setattr(inventory_edit, "_fsync_directory", lambda _path: False)

    receipt = commit_inventory_backup_delete(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.deletion_verified is True
    assert receipt.directory_synced is False
    assert "could not be synced" in receipt.warnings[0]
    assert not only.backup_path.exists()
    assert target.read_bytes() == active


@pytest.mark.skipif(os.name != "posix", reason="POSIX backup file contract")
def test_backup_inspection_rejects_insecure_or_hard_linked_files(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    source = _apply_resource(target, "tool-one")

    source.backup_path.chmod(0o644)
    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        inspect_inventory_backup(target, source.backup_id)
    source.backup_path.chmod(0o600)

    other_link = tmp_path / "linked-backup.yaml"
    os.link(source.backup_path, other_link)
    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        inspect_inventory_backup(target, source.backup_id)


def test_hard_links_are_rejected_for_targets_and_backups_on_supported_platforms(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    target_link = tmp_path / "target-link.yaml"
    try:
        os.link(target, target_link)
    except (NotImplementedError, OSError):
        pytest.skip("hard links are unavailable on this platform")
    with pytest.raises(StorageError, match="hard-linked inventory update target"):
        plan_add_resource(target, _resource())
    target_link.unlink()

    source = _apply_resource(target, "tool-one")
    backup_link = tmp_path / "backup-link.yaml"
    os.link(source.backup_path, backup_link)
    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        inspect_inventory_backup(target, source.backup_id)


def test_backup_entry_capacity_refuses_before_replacement_and_reuses_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    first = _apply_resource(target, "tool-one")
    active = target.read_bytes()
    monkeypatch.setattr(inventory_edit, "_MAX_BACKUP_DIRECTORY_ENTRIES", 1)

    reused_id, reused_path = inventory_edit._backup_current(target, first.backup_path.read_bytes())
    assert (reused_id, reused_path) == (first.backup_id, first.backup_path)

    second_plan = plan_add_resource(target, _resource("tool-two"))
    with pytest.raises(StorageError, match="bounded entry capacity"):
        commit_add_resource(
            second_plan,
            expected_revision=second_plan.original_revision,
            expected_plan=second_plan.plan_token,
        )

    assert target.read_bytes() == active
    assert len(list_inventory_backups(target).backups) == 1
    delete_plan = plan_inventory_backup_delete(
        target,
        first.backup_id,
        allow_no_backups=True,
    )
    assert delete_plan.backup_count_before == 1


def test_backup_listing_refuses_over_byte_budget_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    _apply_resource(target, "tool-one")
    monkeypatch.setattr(inventory_edit, "_MAX_BACKUP_TOTAL_BYTES", 0)

    def fail_if_parsed(*_args, **_kwargs):
        raise AssertionError("over-budget backup content must not be parsed")

    monkeypatch.setattr(inventory_edit._InventoryBackupStore, "_read", fail_if_parsed)
    with pytest.raises(StorageError, match="bounded inspection budget"):
        list_inventory_backups(target)


def test_backup_byte_capacity_refuses_new_safety_backup_before_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    first = _apply_resource(target, "tool-one")
    active = target.read_bytes()
    existing_bytes = first.backup_path.stat().st_size
    monkeypatch.setattr(
        inventory_edit,
        "_MAX_BACKUP_TOTAL_BYTES",
        existing_bytes + len(active) - 1,
    )
    plan = plan_add_resource(target, _resource("tool-two"))

    with pytest.raises(StorageError, match="bounded byte capacity"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == active
    assert first.backup_path.exists()


def test_backup_root_capacity_refuses_a_new_target_before_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_a = tmp_path / "private" / "alpha.yaml"
    target_b = tmp_path / "private" / "bravo.yaml"
    _personal_file(target_a)
    _personal_file(target_b)
    monkeypatch.setattr(inventory_edit, "_MAX_BACKUP_DIRECTORY_ENTRIES", 1)
    _apply_resource(target_a, "alpha-tool")
    original_b = target_b.read_bytes()
    plan_b = plan_add_resource(target_b, _resource("bravo-tool"))

    with pytest.raises(StorageError, match="backup root is at its bounded target capacity"):
        commit_add_resource(
            plan_b,
            expected_revision=plan_b.original_revision,
            expected_plan=plan_b.plan_token,
        )

    assert target_b.read_bytes() == original_b
    assert len(list_inventory_backups(target_a).backups) == 1


def test_mid_commit_same_bytes_inode_substitution_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_file(target)
    plan = plan_add_resource(target, _resource("tool-one"))
    real_write = inventory_edit._write_candidate_temp

    def write_then_substitute(path: Path, content: str | bytes) -> Path:
        temp_path = real_write(path, content)
        displaced = path.with_name("displaced-inventory.yaml")
        path.rename(displaced)
        create_private_file(path, original.decode("utf-8"))
        return temp_path

    monkeypatch.setattr(inventory_edit, "_write_candidate_temp", write_then_substitute)
    with pytest.raises(StorageError, match="identity changed during update"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_delete_replan_wraps_disappeared_source_as_a_preview_conflict(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    first = _apply_resource(target, "tool-one")
    _apply_resource(target, "tool-two")
    active = target.read_bytes()
    plan = plan_inventory_backup_delete(target, first.backup_id)
    first.backup_path.unlink()

    with pytest.raises(StorageError, match="validated backup set changed after preview"):
        commit_inventory_backup_delete(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
    assert target.read_bytes() == active


def test_post_delete_lstat_error_is_applied_but_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    only = _apply_resource(target, "tool-one")
    plan = plan_inventory_backup_delete(
        target,
        only.backup_id,
        allow_no_backups=True,
    )
    real_lstat = Path.lstat

    def fail_when_deleted(path: Path):
        try:
            return real_lstat(path)
        except FileNotFoundError as exc:
            if path == only.backup_path:
                raise OSError("synthetic post-delete lstat failure") from exc
            raise

    monkeypatch.setattr(Path, "lstat", fail_when_deleted)
    receipt = commit_inventory_backup_delete(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )

    assert receipt.deletion_verified is False
    assert "post-delete verification failed" in receipt.warnings[0]


def test_backup_delete_exception_after_unlink_records_uncertain_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    first = _apply_resource(target, "tool-one")
    _apply_resource(target, "tool-two")
    plan = plan_inventory_backup_delete(target, first.backup_id)

    def fail_post_unlink_sync(path: Path) -> bool:
        if path == plan.backup_path.parent and not plan.backup_path.exists():
            raise StorageError("synthetic post-delete failure")
        return True

    monkeypatch.setattr(inventory_edit, "_fsync_directory", fail_post_unlink_sync)
    with pytest.raises(StorageError, match="synthetic post-delete failure") as caught:
        commit_inventory_backup_delete(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert not plan.backup_path.exists()
    assert any("deletion started" in note for note in getattr(caught.value, "__notes__", ()))
    outcome = inspect_inventory_backup_manifest(target).events[-1]
    assert outcome.operation == "delete-inventory-backup"
    assert outcome.phase == "uncertain"
    assert outcome.details["deletion_started"] is True


def test_digest_matching_invalid_and_demo_backups_are_not_restorable(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    valid = _apply_resource(target, "tool-one")
    backup_directory = valid.backup_path.parent
    invalid_text = "not: [valid\n"
    invalid_id = inventory_edit._revision(invalid_text.encode("utf-8"))
    invalid_path = backup_directory / (f"inventory-{invalid_id.removeprefix('sha256:')}.yaml")
    create_private_file(invalid_path, invalid_text)
    demo_text = demo_inventory()
    demo_id = inventory_edit._revision(demo_text.encode("utf-8"))
    demo_path = backup_directory / f"inventory-{demo_id.removeprefix('sha256:')}.yaml"
    create_private_file(demo_path, demo_text)

    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        inspect_inventory_backup(target, invalid_id)
    with pytest.raises(ConfigurationError, match="backup is unavailable or non-restorable"):
        inspect_inventory_backup(target, demo_id)
    listing = list_inventory_backups(target)
    assert [backup.backup_id for backup in listing.backups] == [valid.backup_id]
    assert listing.warnings == ("ignored 2 non-restorable target-scoped backup(s)",)


def test_exact_backup_lookup_does_not_oracle_legacy_hidden_note_guesses(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    valid = _apply_resource(target, "tool-one")
    legacy = starter_inventory()
    nonce = InventoryCatalog.from_text(legacy).inventory.revision_privacy_nonce
    assert nonce is not None
    legacy = legacy.replace(f'revision_privacy_nonce: "{nonce}"\n', "").replace(
        "resources: []",
        "private_notes: guessable-low-entropy-note\nresources: []",
    )
    guessed_id = inventory_edit._revision(legacy.encode("utf-8"))
    guessed_path = valid.backup_path.parent / f"inventory-{guessed_id.removeprefix('sha256:')}.yaml"
    create_private_file(guessed_path, legacy)
    missing_id = "sha256:" + "0" * 64
    assert missing_id != guessed_id

    messages: list[str] = []
    for backup_id in (guessed_id, missing_id):
        with pytest.raises(ConfigurationError) as caught:
            inspect_inventory_backup(target, backup_id)
        messages.append(str(caught.value))

    assert messages == ["backup is unavailable or non-restorable"] * 2
    assert guessed_id not in messages[0]


def test_rollback_refuses_backup_directory_identity_substitution(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_file(target)
    source = _apply_resource(target, "tool-one")
    active = target.read_bytes()
    plan = plan_inventory_rollback(target, source.backup_id)
    displaced = source.backup_path.parent.with_name("displaced-backup-namespace")
    source.backup_path.parent.rename(displaced)
    source_text = (displaced / source.backup_path.name).read_text(encoding="utf-8")
    create_private_file(source.backup_path, source_text)

    with pytest.raises(StorageError, match="source backup changed after preview"):
        commit_inventory_rollback(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )
    assert target.read_bytes() == active
