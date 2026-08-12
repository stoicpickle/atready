from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import atready.intake as intake
from atready.catalog import InventoryCatalog
from atready.cli import main


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
    assert applied["receipt"]["resource_id"] == "coderabbit"
    assert applied["receipt"]["replacement_verified"] is True
    stored = InventoryCatalog.from_path(inventory).inventory.resources[0]
    assert stored.id == "coderabbit"
    assert stored.access.status.value == "unknown"
    assert stored.provenance.basis.value == "unknown"


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
    "raw",
    [
        _facts(name="CodeRabbit'; touch injected #"),
        b'{"schema_version":1,"name":"CodeRabbit\nsecond-command",'
        b'"strength":"strong","available_now":true,"private_work":true}\n',
        _facts().removesuffix(b"\n"),
    ],
)
def test_quick_setup_transport_keeps_hostile_names_inert_and_requires_one_line(
    tmp_path: Path,
    raw: bytes,
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
