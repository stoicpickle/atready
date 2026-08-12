from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

import atready.inventory_edit as inventory_edit
import atready.paths as paths
from atready.errors import ConfigurationError, StorageError
from atready.inventory_edit import (
    commit_add_resource,
    inspect_inventory_backup_manifest,
    plan_add_resource,
    resource_from_mapping,
)
from atready.paths import create_private_file
from atready.resource_input import load_resource_declaration_stdin
from atready.templates import starter_inventory
from atready.yamlio import MAX_FILE_BYTES

_PRIVATE_SENTINEL = "SYNTHETIC-PRIVATE-ADVERSARIAL-SENTINEL"


def _resource(*, private_notes: str | None = None):
    return resource_from_mapping(
        {
            "id": "adversarial-tool",
            "name": "Adversarial Tool",
            "categories": ["coding-agent"],
            "capabilities": {"code-review": 0.8},
            "private_notes": private_notes,
        }
    )


def _personal_inventory(path: Path) -> bytes:
    create_private_file(path, starter_inventory())
    return path.read_bytes()


def _apply_resource(path: Path, *, private_notes: str | None = None):
    plan = plan_add_resource(path, _resource(private_notes=private_notes))
    return commit_add_resource(
        plan,
        expected_revision=plan.original_revision,
        expected_plan=plan.plan_token,
    )


def _replace_last_manifest_event(path: Path, raw: bytes) -> None:
    events = sorted((path.parent / ".quartermaster-backups").rglob("event-*.json"))
    assert events
    previous = events[-1]
    sequence = int(previous.name.split("-")[1])
    replacement = previous.with_name(
        f"event-{sequence:012d}-{hashlib.sha256(raw).hexdigest()}.json"
    )
    previous.unlink()
    replacement.write_bytes(raw)
    if os.name == "posix":
        replacement.chmod(0o600)


def _deep_manifest_event(raw: bytes) -> bytes:
    marker = b'"details":'
    start = raw.index(marker) + len(marker)
    end = raw.index(b',"event_type"', start)
    sentinel = json.dumps(_PRIVATE_SENTINEL, ensure_ascii=True).encode()
    details = b'{"a":' * 2_000 + sentinel + b"}" * 2_000
    return raw[:start] + details + raw[end:]


def _huge_integer_manifest_event(raw: bytes) -> bytes:
    marker = b'"details":'
    start = raw.index(marker) + len(marker)
    end = raw.index(b',"event_type"', start)
    return raw[:start] + b"9" * 8_000 + raw[end:]


@pytest.mark.parametrize(
    "mutate",
    [_deep_manifest_event, _huge_integer_manifest_event],
    ids=["deep-details", "huge-integer"],
)
def test_manifest_json_adversaries_fail_closed_without_echoing_values(
    tmp_path: Path,
    mutate: Callable[[bytes], bytes],
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_inventory(target)
    _apply_resource(target)
    event = sorted((target.parent / ".quartermaster-backups").rglob("event-*.json"))[-1]
    hostile = mutate(event.read_bytes())
    assert len(hostile) <= inventory_edit._MAX_MANIFEST_EVENT_BYTES
    _replace_last_manifest_event(target, hostile)

    with pytest.raises(StorageError, match=r"canonical JSON|unsupported values") as caught:
        inspect_inventory_backup_manifest(target)

    assert _PRIVATE_SENTINEL not in str(caught.value)
    assert _PRIVATE_SENTINEL not in repr(caught.value)


def test_interrupted_candidate_write_is_sanitized_and_scrubbed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_inventory(target)
    plan = plan_add_resource(target, _resource(private_notes=_PRIVATE_SENTINEL))
    real_write = inventory_edit.os.write

    def interrupt_private_candidate(descriptor: int, raw: bytes) -> int:
        if _PRIVATE_SENTINEL.encode() in raw:
            raise KeyboardInterrupt("synthetic private interruption")
        return real_write(descriptor, raw)

    monkeypatch.setattr(inventory_edit.os, "write", interrupt_private_candidate)

    with pytest.raises(KeyboardInterrupt, match="synthetic private interruption") as caught:
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert _PRIVATE_SENTINEL not in str(caught.value)
    assert _PRIVATE_SENTINEL not in repr(caught.value)
    assert target.read_bytes() == original
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_interrupted_candidate_encoding_preserves_original_interrupt_and_cleans_temp(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    target.parent.mkdir(mode=0o700)

    class InterruptingText(str):
        def encode(self, *_args, **_kwargs):
            raise KeyboardInterrupt("synthetic encoding interruption")

    with pytest.raises(KeyboardInterrupt, match="synthetic encoding interruption"):
        inventory_edit._write_candidate_temp(target, InterruptingText(_PRIVATE_SENTINEL))

    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_cleanup_fault_does_not_mask_original_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    target.parent.mkdir(mode=0o700)
    real_write = inventory_edit.os.write

    def interrupt_write(descriptor: int, raw: bytes) -> int:
        if _PRIVATE_SENTINEL.encode() in raw:
            raise KeyboardInterrupt("original synthetic interruption")
        return real_write(descriptor, raw)

    def interrupt_scrub(*_args, **_kwargs):
        raise KeyboardInterrupt("secondary cleanup interruption")

    monkeypatch.setattr(inventory_edit.os, "write", interrupt_write)
    monkeypatch.setattr(inventory_edit.os, "ftruncate", interrupt_scrub)

    with pytest.raises(KeyboardInterrupt, match="original synthetic interruption"):
        inventory_edit._write_candidate_temp(target, _PRIVATE_SENTINEL)

    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_interrupted_manifest_event_write_is_scrubbed_and_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_inventory(target)
    plan = plan_add_resource(target, _resource())
    real_write = inventory_edit.os.write
    interrupted = False

    def interrupt_manifest_candidate(descriptor: int, raw: bytes) -> int:
        nonlocal interrupted
        if not interrupted and b'"event_type":"operation"' in raw:
            interrupted = True
            raise KeyboardInterrupt("synthetic manifest interruption")
        return real_write(descriptor, raw)

    monkeypatch.setattr(inventory_edit.os, "write", interrupt_manifest_candidate)

    with pytest.raises(KeyboardInterrupt, match="synthetic manifest interruption"):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original
    assert not list((target.parent / ".quartermaster-backups").rglob(".manifest-*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-only directory contract")
def test_private_file_rejects_writable_existing_directory(tmp_path: Path) -> None:
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o777)
    target = parent / "private.txt"

    with pytest.raises(StorageError, match="writable AtReady directory mode"):
        create_private_file(target, _PRIVATE_SENTINEL)

    assert not target.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-only directory contract")
def test_private_file_accepts_owner_controlled_readable_directory(tmp_path: Path) -> None:
    parent = tmp_path / "owner-readable"
    parent.mkdir(mode=0o755)
    target = parent / "private.txt"

    create_private_file(target, "synthetic non-secret")

    assert target.read_text(encoding="utf-8") == "synthetic non-secret"
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-only directory contract")
def test_private_file_scrubs_content_when_parent_permissions_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    target = parent / "private.txt"
    real_write = paths._write_private_descriptor

    def write_then_open_parent(descriptor: int, path: Path, content: str):
        failure = real_write(descriptor, path, content)
        parent.chmod(0o777)
        return failure

    monkeypatch.setattr(paths, "_write_private_descriptor", write_then_open_parent)

    with pytest.raises(StorageError, match="permissions changed during creation") as caught:
        create_private_file(target, _PRIVATE_SENTINEL)

    assert _PRIVATE_SENTINEL not in str(caught.value)
    assert not target.exists()


def test_lexical_path_aliases_bind_to_one_physical_preview(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    _personal_inventory(target)
    (target.parent / "alias-hop").mkdir()
    alias = target.parent / "alias-hop" / ".." / target.name

    physical_plan = plan_add_resource(target, _resource())
    alias_plan = plan_add_resource(alias, _resource())

    assert alias_plan.target == target.resolve(strict=True)
    assert alias_plan.plan_token == physical_plan.plan_token
    assert alias_plan.preview()["target"] == str(target.resolve(strict=True))


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-only state contract")
@pytest.mark.parametrize("drift", ["target-mode", "parent-mode"])
def test_permission_drift_after_preview_refuses_apply_before_backup(
    tmp_path: Path,
    drift: str,
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    original = _personal_inventory(target)
    plan = plan_add_resource(target, _resource())
    changed = target if drift == "target-mode" else target.parent
    changed.chmod(0o644 if changed == target else 0o777)

    with pytest.raises(
        StorageError,
        match=r"insecure inventory mode|writable inventory directory",
    ):
        commit_add_resource(
            plan,
            expected_revision=plan.original_revision,
            expected_plan=plan.plan_token,
        )

    assert target.read_bytes() == original
    assert not (target.parent / ".quartermaster-backups").exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":1,"resource":{"private_notes":"' + _PRIVATE_SENTINEL.encode(),
        b'{"schema_version":1,"resource":{"api_key":"' + _PRIVATE_SENTINEL.encode() + b'"}}',
        b"schema_version: 1\nresource: &resource {private_notes: "
        + _PRIVATE_SENTINEL.encode()
        + b"}\ncopy: *resource\n",
        b"[" * 40 + b'"' + _PRIVATE_SENTINEL.encode() + b'"' + b"]" * 40,
        b"x" * (MAX_FILE_BYTES + 1),
    ],
    ids=["truncated-json", "secret-json", "yaml-alias", "deep-json", "oversized"],
)
def test_declaration_adversary_corpus_is_bounded_and_value_free(raw: bytes) -> None:
    from io import BytesIO

    with pytest.raises(ConfigurationError) as caught:
        load_resource_declaration_stdin(BytesIO(raw))

    assert _PRIVATE_SENTINEL not in str(caught.value)
    assert _PRIVATE_SENTINEL not in repr(caught.value)
