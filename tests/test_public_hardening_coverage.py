from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import date
from pathlib import Path

import pytest

from atready.catalog import InventoryCatalog
from atready.cli import main
from atready.errors import ConfigurationError, StorageError
from atready.inventory_edit import (
    commit_inventory_recovery,
    inspect_inventory_backup_manifest,
    plan_inventory_recovery,
)
from atready.resource_input import (
    load_inventory_annotation_declaration_file,
    load_inventory_annotation_declaration_stdin,
)


def _resource_add_args(inventory: Path) -> list[str]:
    return [
        "inventory",
        "add",
        "--path",
        str(inventory),
        "--id",
        "recovery-tool",
        "--name",
        "Recovery Tool",
        "--category",
        "coding-agent",
        "--capability",
        "code-implementation=0.90",
        "--access",
        "active",
        "--interaction",
        "local-cli",
        "--session",
        "available",
        "--billing",
        "owned",
        "--marginal-cost",
        "0.05",
        "--quota",
        "ample",
        "--allowed-data-class",
        "internal",
        "--confidence-basis",
        "observed",
        "--verified-on",
        date.today().isoformat(),
        "--handoff-method",
        "manual-prompt",
    ]


def _initialize_with_backup(inventory: Path, capsys) -> tuple[bytes, dict[str, object]]:
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()
    args = _resource_add_args(inventory)
    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 0
    )
    return original, json.loads(capsys.readouterr().out)


def test_human_annotation_preview_and_apply_are_value_free(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    declaration = tmp_path / "annotation.yaml"
    sentinel = "SYNTHETIC-HUMAN-ANNOTATION"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    declaration.write_text(
        f"schema_version: 1\nprivate_notes: {sentinel}\n",
        encoding="utf-8",
    )
    if os.name == "posix":
        declaration.chmod(0o600)
    args = [
        "inventory",
        "annotate",
        "set",
        "--path",
        str(inventory),
        "--annotation-file",
        str(declaration),
    ]

    assert main(args) == 0
    preview = capsys.readouterr()
    assert "Inventory annotation preview (no files changed)" in preview.out
    assert "Private notes effect: will-add" in preview.out
    assert "Private notes: value omitted and bound to this plan." in preview.out
    assert sentinel not in preview.out + preview.err

    assert main([*args, "--json"]) == 0
    tokens = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                tokens["expect_revision"],
                "--expect-plan",
                tokens["expect_plan"],
            ]
        )
        == 0
    )
    receipt = capsys.readouterr()
    assert "Updated inventory annotation" in receipt.out
    assert "Private notes effect: will-add" in receipt.out
    assert "Replacement verified: true" in receipt.out
    assert "Backup ID: sha256:" in receipt.out
    assert sentinel not in receipt.out + receipt.err
    assert InventoryCatalog.from_path(inventory).inventory.private_notes == sentinel


def test_human_manifest_reports_validated_sequence_and_trust_boundary(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    _initialize_with_backup(inventory, capsys)

    assert (
        main(
            [
                "inventory",
                "backup",
                "manifest",
                "--path",
                str(inventory),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Initialized: true" in output
    assert "Authoritative order: sequence (wall-clock timestamps are metadata only)" in output
    assert "Tamper evidence: local hash chain; not a signature or trusted clock" in output
    assert "Validated events: 3" in output
    assert "0: baseline · completed · sha256:" in output
    assert "1: add-resource · prepared · sha256:" in output
    assert "2: add-resource · completed · sha256:" in output


def test_human_recovery_from_missing_target_previews_and_applies_exact_backup(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    original, addition = _initialize_with_backup(inventory, capsys)
    inventory.unlink()
    args = [
        "inventory",
        "backup",
        "recover",
        "--path",
        str(inventory),
        "--backup",
        str(addition["backup_id"]),
    ]

    assert main(args) == 0
    preview = capsys.readouterr()
    preview_text = preview.out
    assert "Inventory disaster-recovery preview (no files changed)" in preview_text
    assert "Active state: missing" in preview_text
    assert "The active target is missing, so no displaced bytes require quarantine." in preview_text
    assert "The exact source backup will be retained." in preview_text

    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-state",
                preview["expect_state"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 0
    )
    receipt = capsys.readouterr()
    assert "Recovered inventory at" in receipt.out
    assert "Previous state: missing" in receipt.out
    assert "Replacement verified: true" in receipt.out
    assert "Source backup retained:" in receipt.out
    assert "Invalid bytes quarantined:" not in receipt.out
    assert inventory.read_bytes() == original


def test_human_recovery_quarantines_invalid_bytes_without_echoing_them(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    original, addition = _initialize_with_backup(inventory, capsys)
    sentinel = "SYNTHETIC-INVALID-HUMAN-RECOVERY"
    invalid_bytes = f"invalid: [\n{sentinel}\n".encode()
    inventory.write_bytes(invalid_bytes)
    args = [
        "inventory",
        "backup",
        "recover",
        "--path",
        str(inventory),
        "--backup",
        str(addition["backup_id"]),
    ]

    assert main(args) == 0
    preview = capsys.readouterr()
    preview_text = preview.out
    assert "Active state: invalid" in preview_text
    assert "Applying will quarantine the exact invalid bytes before replacement." in preview_text
    assert sentinel not in preview_text + preview.err

    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-state",
                preview["expect_state"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 0
    )
    receipt = capsys.readouterr()
    assert "Previous state: invalid" in receipt.out
    assert "Invalid bytes quarantined:" in receipt.out
    assert sentinel not in receipt.out + receipt.err
    quarantine_match = re.search(r"^Invalid bytes quarantined: (.+)$", receipt.out, re.MULTILINE)
    assert quarantine_match is not None
    quarantine_path = Path(quarantine_match.group(1))
    assert quarantine_path.is_file()
    assert quarantine_path.read_bytes() == invalid_bytes
    assert inventory.read_bytes() == original


def test_recovery_tokens_are_rejected_without_apply(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    _, addition = _initialize_with_backup(inventory, capsys)
    inventory.unlink()

    assert (
        main(
            [
                "inventory",
                "backup",
                "recover",
                "--path",
                str(inventory),
                "--backup",
                str(addition["backup_id"]),
                "--expect-state",
                "missing",
                "--expect-plan",
                "sha256:not-an-approved-plan",
            ]
        )
        == 2
    )
    assert "only valid with --apply" in capsys.readouterr().err
    assert not inventory.exists()


def _manifest_directory(inventory: Path) -> Path:
    directories = list((inventory.parent / ".quartermaster-backups").glob("*/.operations-v1"))
    assert len(directories) == 1
    return directories[0]


def _rewrite_manifest_event(path: Path, **changes: object) -> None:
    value = json.loads(path.read_bytes())
    value.update(changes)
    raw = (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    sequence = int(path.name.split("-")[1])
    replacement = path.with_name(f"event-{sequence:012d}-{hashlib.sha256(raw).hexdigest()}.json")
    path.unlink()
    replacement.write_bytes(raw)
    if os.name == "posix":
        replacement.chmod(0o600)


def _replace_manifest_event_bytes(path: Path, raw: bytes) -> None:
    sequence = int(path.name.split("-")[1])
    replacement = path.with_name(f"event-{sequence:012d}-{hashlib.sha256(raw).hexdigest()}.json")
    path.unlink()
    replacement.write_bytes(raw)
    if os.name == "posix":
        replacement.chmod(0o600)


@pytest.mark.parametrize(
    ("event_index", "changes", "message"),
    [
        (-1, {"schema_version": 2}, "unsupported schema"),
        (-1, {"sequence": 99}, "sequence does not match"),
        (-1, {"previous_event_hash": "sha256:" + "0" * 64}, "hash chain is broken"),
        (-1, {"details": {"unsafe_number": 1.5}}, "unsupported values"),
        (0, {"phase": "uncertain"}, "genesis is invalid"),
        (-1, {"operation": "unsupported-operation"}, "operation event is invalid"),
        (-1, {"event_type": "unsupported-event"}, "event type is invalid"),
        (-1, {"phase": "prepared"}, "repeats an operation preparation"),
        (-1, {"operation_id": "operation-v1:" + "f" * 64}, "closes an unknown operation"),
    ],
)
def test_manifest_inspection_rejects_structurally_tampered_events(
    tmp_path: Path,
    capsys,
    event_index: int,
    changes: dict[str, object],
    message: str,
) -> None:
    inventory = tmp_path / "inventory.yaml"
    _initialize_with_backup(inventory, capsys)
    events = sorted(_manifest_directory(inventory).iterdir())
    _rewrite_manifest_event(events[event_index], **changes)

    with pytest.raises(StorageError, match=message):
        inspect_inventory_backup_manifest(inventory)


@pytest.mark.parametrize("tamper", ["invalid-json", "noncanonical-json"])
def test_manifest_inspection_rejects_noncanonical_event_encodings(
    tmp_path: Path, capsys, tamper: str
) -> None:
    inventory = tmp_path / "inventory.yaml"
    _initialize_with_backup(inventory, capsys)
    event = sorted(_manifest_directory(inventory).iterdir())[-1]
    raw = b"{not-json}\n"
    if tamper == "noncanonical-json":
        raw = json.dumps(json.loads(event.read_bytes()), indent=2).encode() + b"\n"
    _replace_manifest_event_bytes(event, raw)

    with pytest.raises(StorageError, match="not canonical JSON"):
        inspect_inventory_backup_manifest(inventory)


def test_manifest_inspection_rejects_unexpected_and_hard_linked_entries(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    _initialize_with_backup(inventory, capsys)
    directory = _manifest_directory(inventory)
    unexpected = directory / "unexpected-entry"
    unexpected.write_bytes(b"unexpected")
    if os.name == "posix":
        unexpected.chmod(0o600)
    with pytest.raises(StorageError, match="unexpected directory entry"):
        inspect_inventory_backup_manifest(inventory)

    unexpected.unlink()
    first = sorted(directory.iterdir())[0]
    try:
        os.link(first, directory / "zz-hard-link")
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"hard links are unavailable on this filesystem: {exc}")
    with pytest.raises(StorageError, match="unexpected directory entry"):
        inspect_inventory_backup_manifest(inventory)


@pytest.mark.skipif(os.name != "posix", reason="POSIX manifest mode contract")
def test_manifest_inspection_rejects_world_readable_event(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    _initialize_with_backup(inventory, capsys)
    event = sorted(_manifest_directory(inventory).iterdir())[0]
    event.chmod(0o644)

    with pytest.raises(StorageError, match="insecure backup operation manifest event"):
        inspect_inventory_backup_manifest(inventory)


def test_recovery_commit_requires_the_exact_preview_state_and_plan(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    _, addition = _initialize_with_backup(inventory, capsys)
    inventory.unlink()
    plan = plan_inventory_recovery(inventory, str(addition["backup_id"]))

    with pytest.raises(ConfigurationError, match="--expect-state does not match"):
        commit_inventory_recovery(
            plan,
            expected_state="invalid",
            expected_plan=plan.plan_token,
        )
    with pytest.raises(ConfigurationError, match="--expect-plan does not match"):
        commit_inventory_recovery(
            plan,
            expected_state=plan.state_token,
            expected_plan="sha256:not-the-approved-plan",
        )
    assert not inventory.exists()


class _NonByteStream:
    def read(self, _size: int) -> str:
        return "not bytes"


class _FailingStream:
    def read(self, _size: int) -> bytes:
        raise OSError("synthetic transport failure")


@pytest.mark.parametrize(
    ("stream", "message"),
    [
        (_NonByteStream(), "must provide bytes"),
        (_FailingStream(), "cannot read inventory annotation declaration"),
        (io.BytesIO(b"\xff\xfe"), "must be valid UTF-8"),
    ],
)
def test_annotation_stdin_rejects_unsafe_transport_values_without_leaking_causes(
    stream, message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message) as caught:
        load_inventory_annotation_declaration_stdin(stream)

    assert caught.value.__cause__ is None


def test_annotation_file_rejects_missing_nonregular_and_oversized_sources(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigurationError, match="file does not exist"):
        load_inventory_annotation_declaration_file(missing)

    directory = tmp_path / "annotation-directory"
    directory.mkdir()
    with pytest.raises(ConfigurationError, match="not a regular file"):
        load_inventory_annotation_declaration_file(directory)

    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b"x" * (1_048_576 + 1))
    if os.name == "posix":
        oversized.chmod(0o600)
    with pytest.raises(ConfigurationError, match="exceeds 1048576 bytes"):
        load_inventory_annotation_declaration_file(oversized)
