from __future__ import annotations

import io
import json
import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

import atready.cli as cli
import atready.intake as intake
from atready.catalog import InventoryCatalog
from atready.cli import build_parser, main


class _BinaryInput:
    def __init__(self, raw: bytes, *, tty: bool = False) -> None:
        self.buffer = io.BytesIO(raw)
        self.buffer.isatty = lambda: tty  # type: ignore[attr-defined]


def _facts(
    *,
    name: str = "CodeRabbit",
    strength: str = "strong",
    available_now: bool = True,
    private_work: bool = True,
) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "name": name,
                "strength": strength,
                "available_now": available_now,
                "private_work": private_work,
            }
        ).encode()
        + b"\n"
    )


def _preview(
    inventory: Path,
    raw: bytes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, object]:
    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))
    assert (
        main(
            [
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-stdin",
                "--json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_quick_setup_preview_delegates_to_exact_no_write_add_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()

    result = _preview(inventory, _facts(), monkeypatch, capsys)

    assert result["format"] == "atready-resource-quick-preview-v1"
    assert result["status"] == "preview-ready"
    assert result["effects"] == {
        "inventory_read": True,
        "network_accessed": False,
        "provider_or_account_inspected": False,
        "resource_run": False,
        "writes_performed": False,
    }
    human_preview = result["human_preview"]
    assert human_preview == (
        "CodeRabbit for code review and repository analysis\n\n"
        "Strength: Strong\n"
        "Available now: Yes\n"
        "Private work: Allowed\n"
        "Still unknown: Account access, usage limits, and permission for sensitive work.\n\n"
        "Nothing has been saved."
    )
    for hidden_detail in (
        "sha256:",
        "inventory.yaml",
        "defaulted",
        "rating",
        "target",
        "revision",
        "token",
        "expect_revision",
        "expect_plan",
        "intake_review",
        "mapping",
        "preview",
        "effects",
        "resource_id",
    ):
        assert hidden_detail not in human_preview.casefold()
    preview = result["preview"]
    assert isinstance(preview, dict)
    assert preview["operation"] == "add-resource"
    assert preview["applied"] is False
    assert preview["resource"]["id"] == "coderabbit"
    assert preview["resource"]["capabilities"] == {
        "code-review": 0.8,
        "repository-analysis": 0.8,
    }
    assert preview["resource"]["access"] == {
        "current_session": "available",
        "interaction": "manual",
        "status": "unknown",
    }
    assert preview["resource"]["economics"]["quota"] == "unknown"
    assert preview["resource"]["provenance"] == {
        "basis": "unknown",
        "last_verified": None,
    }
    assert preview["resource"]["policy"] == {
        "allowed_data_classes": ["public", "internal", "private"],
        "approval_required": True,
        "requires_network": True,
    }
    assert preview["intake_review"]["selection_fact_status"] == "requires-verification"
    assert result["mapping"] == {
        "availability_mapping": "access-unknown-session-available",
        "catalog_profile": "coderabbit",
        "private_work_mapping": "public-internal-private",
        "provider_or_account_inspected": False,
        "provenance_default": "unknown",
        "requires_network_default": True,
        "strength_score": 0.8,
    }
    assert result["correction"]["supported"] is True
    assert inventory.read_bytes() == original


def test_quick_setup_requires_separate_exact_apply_and_rederives_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.yaml"
    raw = _facts()
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()
    preview_result = _preview(inventory, raw, monkeypatch, capsys)
    preview = preview_result["preview"]
    assert isinstance(preview, dict)
    base = [
        "resource",
        "quick-add",
        "--path",
        str(inventory),
        "--facts-stdin",
        "--json",
    ]

    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))
    assert main([*base, "--apply"]) == 2
    assert "requires --expect-revision and --expect-plan" in capsys.readouterr().err
    assert inventory.read_bytes() == original

    changed = _facts(strength="solid")
    monkeypatch.setattr(sys, "stdin", _BinaryInput(changed))
    assert (
        main(
            [
                *base,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 2
    )
    assert "does not match this preview" in capsys.readouterr().err
    assert inventory.read_bytes() == original

    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))
    assert (
        main(
            [
                *base,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 0
    )
    applied = json.loads(capsys.readouterr().out)
    assert applied["format"] == "atready-resource-quick-apply-v1"
    assert applied["status"] == "applied"
    assert "recovery" not in applied
    assert applied["receipt"]["resource_id"] == "coderabbit"
    assert applied["receipt"]["replacement_verified"] is True
    stored = InventoryCatalog.from_path(inventory).inventory.resources[0]
    assert stored.id == "coderabbit"
    assert stored.access.status.value == "unknown"
    assert stored.provenance.basis.value == "unknown"


def test_quick_setup_uncertain_apply_forbids_retry_in_machine_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.yaml"
    raw = _facts()
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    preview_result = _preview(inventory, raw, monkeypatch, capsys)
    preview = preview_result["preview"]
    assert isinstance(preview, dict)
    receipt = {"target": str(inventory), "backup_path": str(tmp_path / "backup.yaml")}
    monkeypatch.setattr(
        cli,
        "_inventory_add_receipt_result",
        lambda *_args, **_kwargs: (receipt, True),
    )
    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))

    assert (
        main(
            [
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-stdin",
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 4
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "applied-with-uncertainty"
    assert result["recovery"] == {
        "instruction": (
            "Do not retry this apply. Inspect receipt.target and receipt.backup_path before "
            "another update."
        ),
        "retry_safe": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":1,"name":"CodeRabbit","name":"secret",'
        b'"strength":"strong","available_now":true,"private_work":true}\n',
        b'{"schema_version":1,"name":"CodeRabbit","strength":"strong",'
        b'"available_now":true,"private_work":true,"private_notes":"secret"}\n',
        b'{"schema_version":1,"name":"CodeRabbit\\u001b[31msecret",'
        b'"strength":"strong","available_now":true,"private_work":true}\n',
        b'{"schema_version":1,"name":"CodeRabbit","strength":"strong",'
        b'"available_now":"yes","private_work":true}\n',
        b'{"schema_version":1,"name":"CodeRabbit","strength":NaN,'
        b'"available_now":true,"private_work":true}\n',
    ],
)
def test_quick_setup_rejects_hostile_or_non_exact_facts_without_echoing_values(
    tmp_path: Path,
    raw: bytes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()
    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))

    assert (
        main(
            [
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-stdin",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "quick setup facts are invalid" in captured.err
    assert "secret" not in captured.out + captured.err
    assert "CodeRabbit" not in captured.out + captured.err
    assert inventory.read_bytes() == original


def test_quick_setup_refuses_tty_oversize_and_unknown_profile_without_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()
    base = [
        "resource",
        "quick-add",
        "--path",
        str(inventory),
        "--facts-stdin",
        "--json",
    ]

    monkeypatch.setattr(sys, "stdin", _BinaryInput(_facts(), tty=True))
    assert main(base) == 2
    assert "interactive input is refused" in capsys.readouterr().err

    monkeypatch.setattr(sys, "stdin", _BinaryInput(b"{" + b"x" * 4_096 + b"\n"))
    assert main(base) == 2
    assert "exceed" in capsys.readouterr().err

    monkeypatch.setattr(sys, "stdin", _BinaryInput(_facts(name="private-secret-tool")))
    assert main(base) == 2
    captured = capsys.readouterr()
    assert "use detailed setup" in captured.err
    assert "private-secret-tool" not in captured.out + captured.err
    assert inventory.read_bytes() == original


@pytest.mark.parametrize(
    ("raw", "expected_error"),
    [
        (
            _facts(name="CodeRabbit'; touch injected #"),
            "quick setup requires one unambiguous bundled profile",
        ),
        (
            b'{"schema_version":1,"name":"CodeRabbit\nsecond-command",'
            b'"strength":"strong","available_now":true,"private_work":true}\n',
            "quick setup facts are invalid",
        ),
        (_facts().removesuffix(b"\n"), "quick setup facts must end with one newline"),
    ],
)
def test_quick_setup_transport_keeps_hostile_names_inert_and_requires_one_line(
    tmp_path: Path,
    raw: bytes,
    expected_error: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.yaml"
    marker = tmp_path / "injected"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()
    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))

    assert (
        main(
            [
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-stdin",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert expected_error in captured.err
    assert "touch injected" not in captured.out + captured.err
    assert not marker.exists()
    assert inventory.read_bytes() == original


def test_quick_setup_exits_after_one_line_without_waiting_for_stdin_close(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.yaml"
    stdout_path = tmp_path / "stdout.json"
    stderr_path = tmp_path / "stderr.txt"
    assert main(["init", "--path", str(inventory)]) == 0
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        process = subprocess.Popen(  # noqa: S603 - exact current test interpreter
            [
                sys.executable,
                "-c",
                "from atready.cli import main; raise SystemExit(main())",
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-stdin",
                "--json",
            ],
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            env={**os.environ, "ATREADY_HOME": str(tmp_path)},
        )
        assert process.stdin is not None
        process.stdin.write(_facts())
        process.stdin.flush()
        try:
            assert process.wait(timeout=3) == 0
        finally:
            process.stdin.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)

    result = json.loads(stdout_path.read_bytes())
    assert result["status"] == "preview-ready"
    assert stderr_path.read_bytes() == b""


def test_quick_setup_json_line_is_exclusive_bounded_and_signals_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as missing:
        parser.parse_args(["resource", "quick-add"])
    assert missing.value.code == 2
    capsys.readouterr()
    with pytest.raises(SystemExit) as duplicate:
        parser.parse_args(["resource", "quick-add", "--facts-stdin", "--facts-json-line"])
    assert duplicate.value.code == 2
    assert "not allowed with argument --facts-stdin" in capsys.readouterr().err

    with pytest.raises(SystemExit) as non_json:
        parser.parse_args(["resource", "quick-add", "--facts-stdin"])
    assert non_json.value.code == 2
    assert "the following arguments are required: --json" in capsys.readouterr().err

    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()
    monkeypatch.setattr(sys, "stdin", _BinaryInput(_facts()))
    assert (
        main(
            [
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-json-line",
                "--json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == "ATREADY_FACTS_JSON_LINE_READY\n"
    assert json.loads(captured.out)["status"] == "preview-ready"
    assert inventory.read_bytes() == original

    monkeypatch.setattr(sys, "stdin", _BinaryInput(b"{" + b"x" * 4_096 + b"\n"))
    assert (
        main(
            [
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-json-line",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.err.startswith("ATREADY_FACTS_JSON_LINE_READY\n")
    assert "exceeds 4096 bytes" in captured.err
    assert captured.out == ""
    assert inventory.read_bytes() == original


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="agent handshake requires a POSIX PTY")
def test_quick_setup_json_line_launches_then_accepts_one_unreflected_facts_record(
    tmp_path: Path,
) -> None:
    import termios

    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    original = inventory.read_bytes()
    master, slave = os.openpty()
    expected_terminal = termios.tcgetattr(slave)
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(  # noqa: S603 - exact current test interpreter
            [
                sys.executable,
                "-c",
                "from atready.cli import main; raise SystemExit(main())",
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-json-line",
                "--json",
            ],
            stdin=slave,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "ATREADY_HOME": str(tmp_path)},
        )
        os.close(slave)
        slave = -1
        assert process.stderr is not None
        readable, _, _ = select.select([process.stderr], [], [], 3)
        assert readable, "quick setup did not publish its readiness marker"
        assert process.stderr.readline() == b"ATREADY_FACTS_JSON_LINE_READY\n"

        facts = _facts()
        facts_body = facts.rstrip(b"\n")
        os.write(master, facts_body)
        assert process.poll() is None
        readable, _, _ = select.select([master], [], [], 0.1)
        reflected = os.read(master, 8_192) if readable else b""
        assert facts_body not in reflected

        os.write(master, b"\n")
        stdout, stderr = process.communicate(timeout=3)

        assert process.returncode == 0
        assert stderr == b""
        assert json.loads(stdout)["status"] == "preview-ready"
        assert inventory.read_bytes() == original
        restored = termios.tcgetattr(master)
        assert restored[3] == expected_terminal[3]
        assert restored[6][termios.VMIN] == expected_terminal[6][termios.VMIN]
        assert restored[6][termios.VTIME] == expected_terminal[6][termios.VTIME]
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        if slave >= 0:
            os.close(slave)
        os.close(master)


def test_quick_setup_never_calls_discovery_provider_or_network_seams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("quick setup must not inspect or execute external state")

    monkeypatch.setattr(intake.shutil, "which", forbidden)
    monkeypatch.setattr(intake.subprocess, "run", forbidden)
    result = _preview(inventory, _facts(), monkeypatch, capsys)

    assert result["effects"]["network_accessed"] is False
    assert result["effects"]["provider_or_account_inspected"] is False


def test_quick_setup_duplicate_error_does_not_echo_approved_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inventory = tmp_path / "inventory.yaml"
    raw = _facts()
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    first = _preview(inventory, raw, monkeypatch, capsys)
    preview = first["preview"]
    assert isinstance(preview, dict)
    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))
    assert (
        main(
            [
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-stdin",
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
    capsys.readouterr()
    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))

    assert (
        main(
            [
                "resource",
                "quick-add",
                "--path",
                str(inventory),
                "--facts-stdin",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "could not be prepared" in captured.err
    assert "CodeRabbit" not in captured.out + captured.err
    assert "coderabbit" not in captured.out + captured.err
