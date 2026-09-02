"""Exercise the installed wheel without importing the source checkout package."""

from __future__ import annotations

import errno
import json
import os
import re
import select
import stat
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import atready
from atready.catalog import InventoryCatalog
from atready.errors import ConfigurationError
from atready.models import RoutePlan
from atready.project import project_from_text
from atready.routing import route
from atready.runtime_contract import RUNTIME_CONTRACT_VERSION
from atready.templates import demo_inventory, starter_inventory, starter_project

_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(_SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIRECTORY))

from first_user_acceptance import run_acceptance  # noqa: E402

_COMMAND_TIMEOUT_SECONDS = 30
_CANONICAL_SMOKE_DATE = date(2026, 8, 10)
_NONCE_PATTERN = re.compile(
    r'^revision_privacy_nonce:\s+["\']?(nonce-v1:[0-9a-f]{64})["\']?$',
    re.MULTILINE,
)


def _installed_atready_executable() -> str:
    executable_name = "atready.exe" if os.name == "nt" else "atready"
    executable = Path(sys.executable).with_name(executable_name)
    if not executable.is_file():
        raise AssertionError("installed wheel did not provide the atready console command")
    return str(executable)


def _run(argv: list[str], *, expected: int = 0, input_text: str | None = None) -> tuple[str, str]:
    executable = _installed_atready_executable()
    try:
        result = subprocess.run(  # noqa: S603
            [executable, *argv],
            check=False,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"atready {argv!r} exceeded {_COMMAND_TIMEOUT_SECONDS} seconds"
        ) from exc
    if result.returncode != expected:
        raise AssertionError(
            f"atready {argv!r} returned {result.returncode}, expected {expected}: {result.stderr}"
        )
    return result.stdout, result.stderr


def _read_pty_until(descriptor: int, *, marker: bytes, timeout: float) -> bytes:
    captured = bytearray()
    deadline = time.monotonic() + timeout
    while marker not in captured:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError("installed console did not publish its PTY readiness marker")
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            continue
        try:
            chunk = os.read(descriptor, 65_536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        captured.extend(chunk)
    return bytes(captured)


def _drain_pty(descriptor: int) -> bytes:
    captured = bytearray()
    while True:
        readable, _, _ = select.select([descriptor], [], [], 0.2)
        if not readable:
            return bytes(captured)
        try:
            chunk = os.read(descriptor, 65_536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                return bytes(captured)
            raise
        if not chunk:
            return bytes(captured)
        captured.extend(chunk)


def _read_pty_until_exit(
    descriptor: int,
    *,
    process: subprocess.Popen[bytes],
    timeout: float,
) -> bytes:
    captured = bytearray()
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError("installed console did not exit after protected PTY input")
        readable, _, _ = select.select([descriptor], [], [], min(remaining, 0.2))
        if not readable:
            continue
        try:
            chunk = os.read(descriptor, 65_536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        captured.extend(chunk)
    remaining = max(0.1, deadline - time.monotonic())
    process.wait(timeout=remaining)
    captured.extend(_drain_pty(descriptor))
    return bytes(captured)


def _run_installed_pty_json_line(
    argv: list[str],
    *,
    marker: bytes,
    payload: bytes,
    working_directory: Path,
) -> bytes:
    if os.name != "posix" or not hasattr(os, "openpty"):
        raise AssertionError("installed PTY smoke requires POSIX openpty")

    import termios

    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    process: subprocess.Popen[bytes] | None = None
    trailing = b"touch SYNTHETIC-WHEEL-PTY-MUST-NOT-EXIST\n"
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed shell and installed console path
            [
                "/bin/sh",
                "-c",
                'exec "$@"',
                "atready-wheel-pty",
                _installed_atready_executable(),
                *argv,
            ],
            cwd=working_directory,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        transcript = _read_pty_until(master, marker=marker, timeout=5)
        if marker not in transcript:
            raise AssertionError("installed console exited before its PTY readiness marker")
        remaining = memoryview(payload + b"\n" + trailing)
        while remaining:
            written = os.write(master, remaining)
            remaining = remaining[written:]
        transcript += _read_pty_until_exit(
            master,
            process=process,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
        if process.returncode != 0:
            raise AssertionError("installed console PTY route did not succeed")
        if payload in transcript or trailing.rstrip(b"\n") in transcript:
            raise AssertionError("installed console reflected protected PTY input")
        if (working_directory / "SYNTHETIC-WHEEL-PTY-MUST-NOT-EXIST").exists():
            raise AssertionError("installed console allowed trailing PTY input to execute")
        if termios.tcgetattr(slave) != original:
            raise AssertionError("installed console did not restore the exact terminal state")
        os.set_blocking(slave, False)
        try:
            queued = os.read(slave, 65_536)
        except BlockingIOError:
            queued = b""
        if queued:
            raise AssertionError("installed console retained trailing PTY input")
        return transcript
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)


def _json_from_pty_transcript(transcript: bytes, *, marker: bytes) -> dict[str, object]:
    lines = transcript.splitlines()
    if lines.count(marker) != 1:
        raise AssertionError("installed console PTY transcript did not contain one exact marker")
    body = b"\n".join(line for line in lines if line != marker).strip()
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError("installed console PTY did not return strict JSON") from exc
    if not isinstance(payload, dict):
        raise AssertionError("installed console PTY JSON was not an object")
    return payload


def _assert_installed_package() -> None:
    package_file = Path(atready.__file__).resolve()
    source_root = (Path(__file__).resolve().parents[1] / "src").resolve()
    if package_file.is_relative_to(source_root):
        raise AssertionError(f"wheel smoke imported the source checkout: {package_file}")


def _file_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _private_state_snapshot(
    root: Path,
) -> tuple[tuple[str, str, bytes | str | tuple[int, int, int, int] | None], ...]:
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise AssertionError("private state root is not a readable directory") from exc
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise AssertionError("private state root is not a real directory")
    entries: list[tuple[str, str, bytes | str | tuple[int, int, int, int] | None]] = [
        (
            ".",
            "directory",
            (
                root_metadata.st_dev,
                root_metadata.st_ino,
                stat.S_IMODE(root_metadata.st_mode),
                root_metadata.st_ctime_ns,
            ),
        )
    ]
    for directory, child_directories, filenames in os.walk(root, followlinks=False):
        child_directories.sort()
        filenames.sort()
        parent = Path(directory)
        for name in [*child_directories, *filenames]:
            path = parent / name
            relative = path.relative_to(root).as_posix()
            metadata = path.lstat()
            if stat.S_ISREG(metadata.st_mode):
                entries.append((relative, "file", path.read_bytes()))
            elif stat.S_ISDIR(metadata.st_mode):
                entries.append((relative, "directory", None))
            elif stat.S_ISLNK(metadata.st_mode):
                entries.append((relative, "symlink", os.readlink(path)))
            else:
                entries.append((relative, f"mode:{stat.S_IFMT(metadata.st_mode)}", None))
    return tuple(entries)


def _inventory_nonce(path: Path) -> str:
    match = _NONCE_PATTERN.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError("installed wheel did not persist a revision privacy nonce")
    return match.group(1)


def _remove_inventory_nonce(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    updated, replacements = _NONCE_PATTERN.subn("", text, count=1)
    if replacements != 1:
        raise AssertionError("installed wheel inventory did not contain exactly one nonce")
    path.write_text(updated, encoding="utf-8")


def main_smoke() -> None:
    _assert_installed_package()
    with tempfile.TemporaryDirectory(prefix="atready-wheel-smoke-") as directory:
        directory = str(Path(directory).resolve())
        os.environ["ATREADY_HOME"] = directory
        contract_state_before = _private_state_snapshot(Path(directory))
        contract_text, contract_error = _run(["runtime", "contract", "--json"])
        if _private_state_snapshot(Path(directory)) != contract_state_before:
            raise AssertionError("installed runtime contract lookup wrote private state")
        contract = json.loads(contract_text)
        if (
            contract_error
            or contract.get("product") != "project-atready"
            or contract.get("runtime_version") != atready.__version__
            or contract.get("contract_version") != RUNTIME_CONTRACT_VERSION
            or "resource.quick-setup-json-line.v1" not in contract.get("features", [])
            or "routing.project-json-line.v1" not in contract.get("features", [])
            or "routing.project-stdin.v1" not in contract.get("features", [])
            or contract.get("inventory_read") is not False
            or contract.get("network_accessed") is not False
            or contract.get("writes_performed") is not False
        ):
            raise AssertionError("installed wheel did not expose the inert runtime contract")
        schema_text, _ = _run(["schema", "resource-declaration"])
        if "schema_version" not in schema_text or "resource" not in schema_text:
            raise AssertionError("installed wheel did not expose the declaration schema")
        annotation_schema_text, _ = _run(["schema", "inventory-annotation-declaration"])
        if (
            "schema_version" not in annotation_schema_text
            or "private_notes" not in annotation_schema_text
        ):
            raise AssertionError("installed wheel did not expose the annotation schema")

        if os.name == "posix" and hasattr(os, "openpty"):
            quick_inventory = Path(directory) / "quick-pty-inventory.yaml"
            _run(["init", "--path", str(quick_inventory), "--json"])
            quick_original = quick_inventory.read_bytes()
            quick_facts = json.dumps(
                {
                    "schema_version": 1,
                    "name": "CodeRabbit",
                    "strength": "strong",
                    "available_now": True,
                    "private_work": True,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            quick_marker = b"ATREADY_FACTS_JSON_LINE_READY"
            quick_state_before = _file_tree(Path(directory))
            quick_preview_transcript = _run_installed_pty_json_line(
                [
                    "resource",
                    "quick-add",
                    "--path",
                    str(quick_inventory),
                    "--facts-json-line",
                    "--json",
                ],
                marker=quick_marker,
                payload=quick_facts,
                working_directory=Path(directory),
            )
            quick_preview = _json_from_pty_transcript(
                quick_preview_transcript,
                marker=quick_marker,
            )
            quick_mapping = quick_preview.get("mapping")
            if (
                quick_preview.get("format") != "atready-resource-quick-preview-v1"
                or quick_preview.get("status") != "preview-ready"
                or not isinstance(quick_mapping, dict)
                or not quick_mapping
                or quick_preview.get("effects")
                != {
                    "inventory_read": True,
                    "network_accessed": False,
                    "provider_or_account_inspected": False,
                    "resource_run": False,
                    "writes_performed": False,
                }
                or _file_tree(Path(directory)) != quick_state_before
                or quick_inventory.read_bytes() != quick_original
            ):
                raise AssertionError("installed console PTY Quick Setup preview was not no-write")
            preview_plan = quick_preview.get("preview")
            if not isinstance(preview_plan, dict):
                raise AssertionError(
                    "installed console PTY Quick Setup omitted its preview binding"
                )
            quick_apply_transcript = _run_installed_pty_json_line(
                [
                    "resource",
                    "quick-add",
                    "--path",
                    str(quick_inventory),
                    "--facts-json-line",
                    "--apply",
                    "--expect-revision",
                    str(preview_plan.get("expect_revision", "")),
                    "--expect-plan",
                    str(preview_plan.get("expect_plan", "")),
                    "--json",
                ],
                marker=quick_marker,
                payload=quick_facts,
                working_directory=Path(directory),
            )
            quick_apply = _json_from_pty_transcript(
                quick_apply_transcript,
                marker=quick_marker,
            )
            quick_receipt = quick_apply.get("receipt")
            if (
                quick_apply.get("format") != "atready-resource-quick-apply-v1"
                or quick_apply.get("status") != "applied"
                or quick_apply.get("mapping") != quick_mapping
                or quick_apply.get("effects")
                != {
                    "inventory_read": True,
                    "network_accessed": False,
                    "provider_or_account_inspected": False,
                    "resource_run": False,
                    "writes_performed": True,
                }
                or not isinstance(quick_receipt, dict)
                or quick_receipt.get("applied") is not True
                or quick_receipt.get("resource_id") != "coderabbit"
                or quick_receipt.get("replacement_verified") is not True
                or not isinstance(quick_receipt.get("candidate_revision"), str)
                or not quick_receipt.get("candidate_revision")
                or quick_receipt.get("revision") != quick_receipt["candidate_revision"]
                or quick_receipt.get("warnings") != []
                or quick_receipt.get("candidate_revision_protection") != "nonce-v1-present"
                or quick_receipt.get("observed_revision_protection") != "nonce-v1-present"
                or (os.name == "posix" and quick_receipt.get("directory_synced") is not True)
            ):
                raise AssertionError("installed console PTY Quick Setup apply was not verified")
            quick_resources = InventoryCatalog.from_path(quick_inventory).inventory.resources
            if [resource.id for resource in quick_resources] != ["coderabbit"]:
                raise AssertionError("installed console PTY Quick Setup persisted the wrong entry")

        private_sentinel = "SYNTHETIC-WHEEL-PRIVATE-NOTE"
        declaration = (
            "schema_version: 1\n"
            "resource:\n"
            "  id: structured-wheel-tool\n"
            "  name: Structured Wheel Tool\n"
            "  categories: [synthetic-tool]\n"
            "  capabilities:\n"
            "    code-implementation: 0.8\n"
            f"  private_notes: {private_sentinel}\n"
        )

        file_inventory = Path(directory) / "file-inventory.yaml"
        file_init_text, file_init_error = _run(["init", "--path", str(file_inventory), "--json"])
        file_nonce = _inventory_nonce(file_inventory)
        if json.loads(file_init_text)["revision_protection"] != "nonce-v1-present":
            raise AssertionError("installed wheel omitted init revision protection status")
        if file_nonce in file_init_text or file_nonce in file_init_error:
            raise AssertionError("installed wheel exposed the file inventory nonce during init")
        annotation_sentinel = "SYNTHETIC-WHEEL-ROOT-ANNOTATION"
        annotation_file = Path(directory) / "inventory-annotation.yaml"
        annotation_file.write_text(
            f"schema_version: 1\nprivate_notes: {annotation_sentinel}\n", encoding="utf-8"
        )
        if os.name == "posix":
            annotation_file.chmod(0o600)
        annotation_args = [
            "inventory",
            "annotate",
            "set",
            "--path",
            str(file_inventory),
            "--annotation-file",
            str(annotation_file),
            "--json",
        ]
        annotation_preview_text, annotation_preview_error = _run(annotation_args)
        if (
            annotation_sentinel in annotation_preview_text
            or annotation_sentinel in annotation_preview_error
        ):
            raise AssertionError("installed wheel annotation preview exposed the hidden value")
        annotation_preview = json.loads(annotation_preview_text)
        annotation_receipt_text, annotation_receipt_error = _run(
            [
                *annotation_args,
                "--apply",
                "--expect-revision",
                annotation_preview["expect_revision"],
                "--expect-plan",
                annotation_preview["expect_plan"],
            ]
        )
        if (
            annotation_sentinel in annotation_receipt_text
            or annotation_sentinel in annotation_receipt_error
        ):
            raise AssertionError("installed wheel annotation receipt exposed the hidden value")
        if annotation_sentinel not in file_inventory.read_text(encoding="utf-8"):
            raise AssertionError("installed wheel did not persist the root annotation")
        clear_args = [
            "inventory",
            "annotate",
            "clear",
            "--path",
            str(file_inventory),
            "--json",
        ]
        clear_preview_text, _ = _run(clear_args)
        clear_preview = json.loads(clear_preview_text)
        _run(
            [
                *clear_args,
                "--apply",
                "--expect-revision",
                clear_preview["expect_revision"],
                "--expect-plan",
                clear_preview["expect_plan"],
            ]
        )
        if annotation_sentinel in file_inventory.read_text(encoding="utf-8"):
            raise AssertionError("installed wheel did not clear the root annotation")
        declaration_file = Path(directory) / "resource-declaration.yaml"
        declaration_file.write_text(declaration, encoding="utf-8")
        if os.name == "posix":
            declaration_file.chmod(0o600)
        source_before = declaration_file.read_bytes()
        file_args = [
            "inventory",
            "add",
            "--path",
            str(file_inventory),
            "--resource-file",
            str(declaration_file),
            "--json",
        ]
        file_preview_text, file_preview_error = _run(file_args)
        if (
            private_sentinel in file_preview_text
            or private_sentinel in file_preview_error
            or file_nonce in file_preview_text
            or file_nonce in file_preview_error
        ):
            raise AssertionError("installed wheel file preview exposed a hidden note")
        file_preview = json.loads(file_preview_text)
        if file_preview["private_notes_present"] is not True:
            raise AssertionError("installed wheel file preview omitted hidden-note presence")
        intake_review = file_preview.get("intake_review")
        if (
            not isinstance(intake_review, dict)
            or intake_review.get("selection_fact_status") != "requires-verification"
            or intake_review.get("route_eligibility_evaluated") is not False
            or not intake_review.get("default_groups", {}).get("selection_facts")
        ):
            raise AssertionError(
                f"installed wheel file preview omitted its intake review: {intake_review!r}"
            )
        file_receipt_text, file_receipt_error = _run(
            [
                *file_args,
                "--apply",
                "--expect-revision",
                file_preview["expect_revision"],
                "--expect-plan",
                file_preview["expect_plan"],
            ]
        )
        if (
            private_sentinel in file_receipt_text
            or private_sentinel in file_receipt_error
            or file_nonce in file_receipt_text
            or file_nonce in file_receipt_error
        ):
            raise AssertionError("installed wheel file receipt exposed a hidden note")
        if json.loads(file_receipt_text)["replacement_verified"] is not True:
            raise AssertionError("installed wheel did not apply a file declaration")
        if declaration_file.read_bytes() != source_before:
            raise AssertionError("installed wheel modified the declaration source")
        if private_sentinel not in file_inventory.read_text(encoding="utf-8"):
            raise AssertionError("installed wheel did not persist the file declaration note")

        replacement_declaration = declaration.replace(
            "name: Structured Wheel Tool", "name: Revised Structured Wheel Tool"
        ).replace(f"  private_notes: {private_sentinel}\n", "")
        replace_args = [
            "inventory",
            "replace",
            "--path",
            str(file_inventory),
            "--resource-stdin",
            "--json",
        ]
        replace_preview_text, _ = _run(replace_args, input_text=replacement_declaration)
        replace_preview = json.loads(replace_preview_text)
        if replace_preview["private_notes_effect"] != "will-remove":
            raise AssertionError("installed wheel replacement hid private-note removal")
        replaced_text, _ = _run(
            [
                *replace_args,
                "--apply",
                "--expect-revision",
                replace_preview["expect_revision"],
                "--expect-plan",
                replace_preview["expect_plan"],
            ],
            input_text=replacement_declaration,
        )
        if json.loads(replaced_text)["replacement_verified"] is not True:
            raise AssertionError("installed wheel did not verify resource replacement")
        replaced_inventory = file_inventory.read_text(encoding="utf-8")
        if private_sentinel in replaced_inventory:
            raise AssertionError("installed wheel replacement retained the removed private note")

        remove_args = [
            "inventory",
            "remove",
            "--path",
            str(file_inventory),
            "--resource",
            "structured-wheel-tool",
            "--json",
        ]
        remove_preview_text, _ = _run(remove_args)
        remove_preview = json.loads(remove_preview_text)
        removed_text, _ = _run(
            [
                *remove_args,
                "--apply",
                "--expect-revision",
                remove_preview["expect_revision"],
                "--expect-plan",
                remove_preview["expect_plan"],
            ]
        )
        if json.loads(removed_text)["replacement_verified"] is not True:
            raise AssertionError("installed wheel did not verify resource removal")
        file_list_text, _ = _run(["inventory", "list", str(file_inventory), "--json"])
        file_listed_ids = [item["id"] for item in json.loads(file_list_text)["resources"]]
        if "structured-wheel-tool" in file_listed_ids:
            raise AssertionError("installed wheel removal retained the resource")

        stdin_inventory = Path(directory) / "stdin-inventory.yaml"
        stdin_init_text, stdin_init_error = _run(["init", "--path", str(stdin_inventory), "--json"])
        stdin_nonce = _inventory_nonce(stdin_inventory)
        if stdin_nonce in stdin_init_text or stdin_nonce in stdin_init_error:
            raise AssertionError("installed wheel exposed the stdin inventory nonce during init")
        stdin_args = [
            "inventory",
            "add",
            "--path",
            str(stdin_inventory),
            "--resource-stdin",
            "--json",
        ]
        stdin_preview_text, stdin_preview_error = _run(stdin_args, input_text=declaration)
        if (
            private_sentinel in stdin_preview_text
            or private_sentinel in stdin_preview_error
            or stdin_nonce in stdin_preview_text
            or stdin_nonce in stdin_preview_error
        ):
            raise AssertionError("installed wheel stdin preview exposed a hidden note")
        stdin_preview = json.loads(stdin_preview_text)
        if stdin_preview["private_notes_present"] is not True:
            raise AssertionError("installed wheel stdin preview omitted hidden-note presence")
        stdin_receipt_text, stdin_receipt_error = _run(
            [
                *stdin_args,
                "--apply",
                "--expect-revision",
                stdin_preview["expect_revision"],
                "--expect-plan",
                stdin_preview["expect_plan"],
            ],
            input_text=declaration,
        )
        if (
            private_sentinel in stdin_receipt_text
            or private_sentinel in stdin_receipt_error
            or stdin_nonce in stdin_receipt_text
            or stdin_nonce in stdin_receipt_error
        ):
            raise AssertionError("installed wheel stdin receipt exposed a hidden note")
        if json.loads(stdin_receipt_text)["replacement_verified"] is not True:
            raise AssertionError("installed wheel did not apply a stdin declaration")
        if private_sentinel not in stdin_inventory.read_text(encoding="utf-8"):
            raise AssertionError("installed wheel did not persist the stdin declaration note")

        created, created_error = _run(["init", "--json"])
        default_inventory = Path(directory) / "inventory.yaml"
        default_nonce = _inventory_nonce(default_inventory)
        initialized = json.loads(created)
        if (
            initialized["resources"] != 0
            or initialized["revision_protection"] != "nonce-v1-present"
        ):
            raise AssertionError("installed wheel did not initialize an empty inventory")
        if default_nonce in created or default_nonce in created_error:
            raise AssertionError("installed wheel exposed the default inventory nonce during init")

        args = [
            "inventory",
            "add",
            "--id",
            "wheel-tool",
            "--name",
            "Wheel Tool",
            "--category",
            "synthetic-tool",
            "--capability",
            "code-implementation=0.8",
            "--json",
        ]
        preview_text, _ = _run(args)
        preview = json.loads(preview_text)
        applied_text, _ = _run(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        applied = json.loads(applied_text)
        if applied["replacement_verified"] is not True:
            raise AssertionError("installed wheel did not verify the inventory replacement")

        legacy_inventory = Path(directory) / "legacy-inventory.yaml"
        _run(["init", "--path", str(legacy_inventory), "--json"])
        _remove_inventory_nonce(legacy_inventory)
        note_free_declaration = declaration.replace(f"  private_notes: {private_sentinel}\n", "")
        legacy_args = [
            "inventory",
            "add",
            "--path",
            str(legacy_inventory),
            "--resource-stdin",
            "--json",
        ]
        legacy_preview_text, _ = _run(legacy_args, input_text=note_free_declaration)
        legacy_preview = json.loads(legacy_preview_text)
        if legacy_preview["revision_protection"] != "legacy-unblinded":
            raise AssertionError("installed wheel hid legacy revision protection status")
        legacy_receipt_text, _ = _run(
            [
                *legacy_args,
                "--apply",
                "--expect-revision",
                legacy_preview["expect_revision"],
                "--expect-plan",
                legacy_preview["expect_plan"],
            ],
            input_text=note_free_declaration,
        )
        legacy_receipt = json.loads(legacy_receipt_text)
        if legacy_receipt["candidate_revision_protection"] != "legacy-unblinded":
            raise AssertionError("installed wheel silently changed a legacy inventory")
        if legacy_receipt["observed_revision_protection"] != "legacy-unblinded":
            raise AssertionError("installed wheel did not verify legacy inventory state")
        if "revision_privacy_nonce" in legacy_inventory.read_text(encoding="utf-8"):
            raise AssertionError("installed wheel silently injected a privacy nonce")

        refused_inventory = Path(directory) / "legacy-private-note-inventory.yaml"
        _run(["init", "--path", str(refused_inventory), "--json"])
        _remove_inventory_nonce(refused_inventory)
        refused_before = refused_inventory.read_bytes()
        refused_out, refused_error = _run(
            [
                "inventory",
                "add",
                "--path",
                str(refused_inventory),
                "--resource-stdin",
            ],
            expected=2,
            input_text=declaration,
        )
        if private_sentinel in refused_out or private_sentinel in refused_error:
            raise AssertionError("installed wheel exposed a refused hidden note")
        if "legacy-unblinded inventories cannot contain private notes" not in refused_error:
            raise AssertionError("installed wheel returned the wrong legacy-note refusal")
        if refused_inventory.read_bytes() != refused_before:
            raise AssertionError("installed wheel changed a refused legacy inventory")

        backups_text, _ = _run(["inventory", "backup", "list", "--json"])
        backups = json.loads(backups_text)
        if [backup["backup_id"] for backup in backups["backups"]] != [applied["backup_id"]]:
            raise AssertionError(f"installed wheel listed unexpected backups: {backups!r}")
        inspection_text, _ = _run(
            [
                "inventory",
                "backup",
                "inspect",
                "--backup",
                applied["backup_id"],
                "--json",
            ]
        )
        inspection = json.loads(inspection_text)
        if inspection["private_notes_exposed"] is not False:
            raise AssertionError("installed wheel backup inspection was not explicitly redacted")

        rollback_args = [
            "inventory",
            "backup",
            "rollback",
            "--backup",
            applied["backup_id"],
            "--json",
        ]
        rollback_preview_text, _ = _run(rollback_args)
        rollback_preview = json.loads(rollback_preview_text)
        rollback_text, _ = _run(
            [
                *rollback_args,
                "--apply",
                "--expect-revision",
                rollback_preview["expect_revision"],
                "--expect-plan",
                rollback_preview["expect_plan"],
            ]
        )
        rollback = json.loads(rollback_text)
        if rollback["replacement_verified"] is not True:
            raise AssertionError("installed wheel did not verify the exact-byte rollback")

        corrupt_inventory_bytes = b"invalid: [\n"
        default_inventory.write_bytes(corrupt_inventory_bytes)
        recovery_args = [
            "inventory",
            "backup",
            "recover",
            "--backup",
            rollback["source_backup_id"],
            "--json",
        ]
        recovery_preview_text, _ = _run(recovery_args)
        recovery_preview = json.loads(recovery_preview_text)
        recovered_text, _ = _run(
            [
                *recovery_args,
                "--apply",
                "--expect-state",
                recovery_preview["expect_state"],
                "--expect-plan",
                recovery_preview["expect_plan"],
            ]
        )
        recovered = json.loads(recovered_text)
        if recovered["replacement_verified"] is not True or not recovered["quarantine_path"]:
            raise AssertionError("installed wheel did not verify invalid-active recovery")
        quarantine_path = Path(recovered["quarantine_path"])
        if not quarantine_path.is_file():
            raise AssertionError("installed wheel recovery did not retain its quarantine file")
        if quarantine_path.read_bytes() != corrupt_inventory_bytes:
            raise AssertionError("installed wheel recovery quarantine changed the corrupt bytes")

        listed_text, _ = _run(["inventory", "list", "--json"])
        listed_ids = [item["id"] for item in json.loads(listed_text)["resources"]]
        if listed_ids:
            raise AssertionError(f"installed wheel listed unexpected resources: {listed_ids!r}")

        delete_preview_text, _ = _run(
            [
                "inventory",
                "backup",
                "delete",
                "--backup",
                rollback["safety_backup_id"],
                "--json",
            ]
        )
        delete_preview = json.loads(delete_preview_text)
        if delete_preview["irreversible"] is not True:
            raise AssertionError("installed wheel did not mark backup deletion irreversible")
        if not Path(delete_preview["backup_path"]).is_file():
            raise AssertionError("installed wheel deletion preview changed backup state")
        delete_text, _ = _run(
            [
                "inventory",
                "backup",
                "delete",
                "--backup",
                rollback["safety_backup_id"],
                "--apply",
                "--expect-revision",
                delete_preview["expect_revision"],
                "--expect-plan",
                delete_preview["expect_plan"],
                "--json",
            ]
        )
        deleted = json.loads(delete_text)
        if deleted["deletion_verified"] is not True:
            raise AssertionError("installed wheel did not verify exact-ID backup deletion")
        remaining_text, _ = _run(["inventory", "backup", "list", "--json"])
        remaining = json.loads(remaining_text)
        if [backup["backup_id"] for backup in remaining["backups"]] != [
            rollback["source_backup_id"]
        ]:
            raise AssertionError(
                f"installed wheel retained unexpected backups after deletion: {remaining!r}"
            )

        skill_path_text, _ = _run(["skill", "path"])
        installed_skill = Path(skill_path_text.strip()) / "SKILL.md"
        if not installed_skill.is_file():
            raise AssertionError("installed wheel did not contain the bundled skill")
        installed_skill_root = installed_skill.parent
        canonical_skill_root = (
            Path(__file__).resolve().parents[1]
            / "plugins"
            / "atready"
            / "skills"
            / "project-atready"
        )
        if _file_tree(installed_skill_root) != _file_tree(canonical_skill_root):
            raise AssertionError("installed wheel skill differs from the canonical plugin skill")
        skill_contract_text = installed_skill.read_text(encoding="utf-8")
        required_planning_contract = (
            "AtReady handles intake and fit",
            "Codex owns planning",
            "Ask at most one consolidated clarification",
            "authorizes only the bounded, read-only inventory checks",
            "do not precede it with `config path` or a separate validation call",
            "inventory snapshot /absolute/path/to/inventory.yaml --format json",
            "Do not invoke `project template`",
            "--project-json-line",
            "writable terminal session",
            "ATREADY_PROJECT_JSON_LINE_READY",
            "session's stdin writer",
            "Do not run a separate project validation during the normal path",
            "If the resource is unnamed, ask only",
            "Do not read another reference or run any command",
            "Only after approval of an unchanged bundled-purpose Quick Setup recap",
            "Static `exec` is host-only",
            "invite exact `retry preview` once",
            "do not offer another retry",
            "--format agent-summary --width 120",
            "exit `3` for a route with gaps",
            "new planning input, not implementation authorization",
            "A resource-fit plan is advice, not authorization",
        )
        normalized_skill_body = " ".join(skill_contract_text.split())
        missing_contract = [
            phrase for phrase in required_planning_contract if phrase not in normalized_skill_body
        ]
        if missing_contract:
            raise AssertionError(
                f"installed wheel bundled a stale planning skill: {missing_contract!r}"
            )
        quick_intake = (installed_skill_root / "references" / "quick-resource-intake.md").read_text(
            encoding="utf-8"
        )
        normalized_quick_intake = " ".join(quick_intake.split())
        if (
            "must not trigger a command" not in normalized_quick_intake
            or "Ask only the unanswered subset" not in normalized_quick_intake
            or "Only an explicit yes to `Preview this entry?`" not in normalized_quick_intake
            or any(
                command in quick_intake
                for command in (
                    "python3 ",
                    "config path",
                    "inventory validate",
                    "schema resource-declaration",
                )
            )
        ):
            raise AssertionError("installed wheel bundled a stale quick intake contract")
        output_contract = (installed_skill_root / "references" / "output-contract.md").read_text(
            encoding="utf-8"
        )
        normalized_output_contract = " ".join(output_contract.split())
        if (
            "`--max-words N` and `--max-lines N`" not in normalized_output_contract
            or "`route --project-json-line --format agent-summary --width 120`"
            not in normalized_output_contract
            or "documented gap exit `3`" not in normalized_output_contract
            or "No routed project resources were contacted or run."
            not in normalized_output_contract
        ):
            raise AssertionError("installed wheel bundled a stale planning output contract")

        presentation_inventory = Path(directory) / "presentation-inventory.yaml"
        presentation_project = Path(directory) / "presentation-project.yaml"
        presentation_inventory.write_text(demo_inventory(_CANONICAL_SMOKE_DATE), encoding="utf-8")
        presentation_project_text = starter_project(_CANONICAL_SMOKE_DATE)
        presentation_project.write_text(presentation_project_text, encoding="utf-8")
        presentation_args = [
            "route",
            "--project",
            str(presentation_project),
            "--inventory",
            str(presentation_inventory),
            "--allow-demo",
        ]
        presentation_state_before = _file_tree(Path(directory))
        route_text, _ = _run([*presentation_args, "--format", "json"])
        stdin_route_text, _ = _run(
            [
                "route",
                "--project-stdin",
                "--inventory",
                str(presentation_inventory),
                "--allow-demo",
                "--format",
                "json",
            ],
            input_text=presentation_project_text,
        )
        if stdin_route_text != route_text:
            raise AssertionError("installed project stdin route differed from the file route")
        project_json_line = (
            json.dumps(project_from_text(presentation_project_text).model_dump(mode="json")) + "\n"
        )
        json_line_route_text, _ = _run(
            [
                "route",
                "--project-json-line",
                "--inventory",
                str(presentation_inventory),
                "--allow-demo",
                "--format",
                "json",
            ],
            input_text=project_json_line,
        )
        if json_line_route_text != route_text:
            raise AssertionError("installed project JSON-line route differed from the file route")
        if os.name == "posix" and hasattr(os, "openpty"):
            pty_state_before = _file_tree(Path(directory))
            pty_transcript = _run_installed_pty_json_line(
                [
                    "route",
                    "--project-json-line",
                    "--inventory",
                    str(presentation_inventory),
                    "--allow-demo",
                    "--format",
                    "agent-summary",
                    "--width",
                    "120",
                ],
                marker=b"ATREADY_PROJECT_JSON_LINE_READY",
                payload=project_json_line.rstrip("\n").encode("utf-8"),
                working_directory=Path(directory),
            )
            if b"No routed project resources were contacted or run." not in pty_transcript:
                raise AssertionError("installed console PTY route omitted its execution boundary")
            if _file_tree(Path(directory)) != pty_state_before:
                raise AssertionError("installed console PTY route wrote private state")
        agent_summary_text, _ = _run([*presentation_args, "--format", "agent-summary"])
        ready_text, _ = _run(
            [
                *presentation_args,
                "--format",
                "presentation",
                "--max-words",
                "500",
                "--max-lines",
                "50",
            ]
        )
        conflict_text, _ = _run(
            [*presentation_args, "--format", "presentation", "--max-words", "1"]
        )
        if _file_tree(Path(directory)) != presentation_state_before:
            raise AssertionError("installed presentation route wrote private state")
        route_payload = json.loads(route_text)
        ready_payload = json.loads(ready_text)
        conflict_payload = json.loads(conflict_text)
        validated_route = RoutePlan.model_validate(route_payload)
        if validated_route.model_dump(mode="json") != route_payload:
            raise AssertionError("installed presentation route did not round-trip its full schema")
        if (
            validated_route.plan_id != "ar-65dc13c0b02c130b"
            or [
                (
                    assignment.workstream_id,
                    assignment.primary.resource_id if assignment.primary else None,
                    len(assignment.handoffs),
                )
                for assignment in validated_route.assignments
            ]
            != [("implementation", "local-coding-agent", 1)]
            or [
                (disposition.resource_id, disposition.status.value, disposition.workstreams)
                for disposition in validated_route.dispositions
            ]
            != [
                ("asset-studio", "deliberately-unused", []),
                ("interactive-debugger", "ineligible", []),
                ("local-coding-agent", "selected-primary", ["implementation"]),
            ]
            or validated_route.assignments[0].handoffs[0].owner_resource_id != "local-coding-agent"
        ):
            raise AssertionError("installed presentation route changed the canonical demo result")
        expected_ready_summary = (
            "Goal: Ship a tested local CLI without network access or telemetry.\n"
            "Route: 1 step assigned.\n"
            "Synthetic Local Coding Agent: Core implementation. Why: Best eligible match\n"
            "after applying the project constraints.\n"
            "Uncertainty: This uses an unverified demo inventory.\n"
            "Next: Use this fit in Codex's plan; separately authorize implementation.\n"
            "No routed project resources were contacted or run.\n"
        )
        expected_conflict_summary = (
            "Presentation limit conflict.\n"
            "Requested maximum: 1 word. Complete route summary requires 55 words.\n"
            "Rerun without --max-words to receive the complete route summary.\n"
            "No routed project resources were contacted or run.\n"
        )
        if (
            ready_payload.get("format") != "atready-route-presentation-v1"
            or ready_payload.get("presentation_status") != "ready"
            or ready_payload.get("route") != route_payload
            or ready_payload.get("summary") != expected_ready_summary
            or agent_summary_text != expected_ready_summary
            or ready_payload.get("limits", {}).get("requested") != {"lines": 50, "words": 500}
            or ready_payload.get("limits", {}).get("required") != {"lines": 7, "words": 55}
        ):
            raise AssertionError("installed wheel did not expose a complete ready presentation")
        if (
            conflict_payload.get("format") != "atready-route-presentation-v1"
            or conflict_payload.get("presentation_status") != "limit-conflict"
            or conflict_payload.get("route") != route_payload
            or conflict_payload.get("summary") != expected_conflict_summary
            or conflict_payload.get("limits", {}).get("requested") != {"lines": None, "words": 1}
            or conflict_payload.get("limits", {}).get("required") != {"lines": 7, "words": 55}
        ):
            raise AssertionError(
                "installed wheel did not expose a complete limit-conflict presentation"
            )

        demo = InventoryCatalog.from_text(demo_inventory(_CANONICAL_SMOKE_DATE)).inventory
        project = project_from_text(starter_project(_CANONICAL_SMOKE_DATE))
        try:
            route(demo, project)
        except ConfigurationError as exc:
            if "--allow-demo in the CLI or allow_demo=True in the API" not in str(exc):
                raise AssertionError(
                    f"installed wheel returned the wrong demo refusal: {exc}"
                ) from exc
        else:
            raise AssertionError("installed wheel routed demo data without explicit opt-in")
        expected_demo_warning = (
            "[demo-inventory] this inventory is labeled demo; its user-controlled contents are "
            "not verified as synthetic or as personal access"
        )
        demo_plan = route(demo, project, allow_demo=True)
        demo_warnings = demo_plan.warnings
        if not demo_warnings or demo_warnings[0] != expected_demo_warning:
            raise AssertionError(
                f"installed wheel returned the wrong demo warnings: {demo_warnings!r}"
            )
        demo_resources = {resource.id: resource for resource in demo.resources}
        demo_handoffs = [
            packet for assignment in demo_plan.assignments for packet in assignment.handoffs
        ]
        if not demo_handoffs:
            raise AssertionError("installed wheel demo route omitted handoff packets")
        for packet in demo_handoffs:
            declared = demo_resources[packet.owner_resource_id].handoff
            if (
                packet.handoff_method is not declared.method
                or packet.handoff_instructions != declared.instructions
            ):
                raise AssertionError(
                    "installed wheel handoff packet did not preserve declared method/guidance"
                )

        unmarked = starter_inventory().replace("inventory_kind: personal\n", "")
        try:
            InventoryCatalog.from_text(unmarked)
        except ConfigurationError as exc:
            if "classify user-declared state" not in str(exc):
                raise AssertionError(
                    f"installed wheel returned the wrong classification error: {exc}"
                ) from exc
        else:
            raise AssertionError("installed wheel accepted an unclassified inventory")

        acceptance = run_acceptance(_installed_atready_executable())
        if acceptance["result"] != "passed":
            raise AssertionError(f"installed wheel failed first-user acceptance: {acceptance!r}")
        acceptance_checks = set(acceptance.get("checks", ()))
        required_intake_checks = {
            "catalog-and-bounded-local-discovery",
            "quick-add-intake-review",
            "quick-add-strict-validation",
            "quick-add-first-route",
            "progressive-intake-enrichment",
        }
        if not required_intake_checks.issubset(acceptance_checks):
            raise AssertionError(
                "installed wheel did not prove the intake-review journey: "
                f"{sorted(acceptance_checks)!r}"
            )

    print("Installed wheel smoke passed")


if __name__ == "__main__":
    main_smoke()
