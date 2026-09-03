from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "plugin_lifecycle_acceptance.py"
SPEC = importlib.util.spec_from_file_location("atready_plugin_lifecycle", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
lifecycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lifecycle)


class _SyntheticProcess:
    pid = 1234

    def __init__(self) -> None:
        self.killed = False

    def poll(self) -> None:
        return None

    def kill(self) -> None:
        self.killed = True


@pytest.mark.parametrize("stream_name", ["stdout", "stderr"])
def test_lifecycle_rejects_and_reaps_oversized_command_output(
    monkeypatch: pytest.MonkeyPatch, stream_name: str
) -> None:
    monkeypatch.setattr(lifecycle, "MAX_COMMAND_OUTPUT_CHARACTERS", 64)
    monkeypatch.setattr(lifecycle, "COMMAND_TIMEOUT_SECONDS", 5)
    script = (
        f"import sys,time; stream=sys.{stream_name}; "
        "stream.write('x' * 4096); stream.flush(); time.sleep(30)"
    )
    started = time.monotonic()

    with pytest.raises(AssertionError, match="output bound"):
        lifecycle._run([sys.executable, "-c", script], environment=os.environ.copy())

    assert time.monotonic() - started < 5


def test_lifecycle_terminates_and_reaps_timed_out_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle, "COMMAND_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(lifecycle, "COMMAND_TERMINATION_GRACE_SECONDS", 0.1)
    started = time.monotonic()

    with pytest.raises(AssertionError, match=r"exceeded 0\.1 seconds"):
        lifecycle._run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            environment=os.environ.copy(),
        )

    assert time.monotonic() - started < 5


def test_lifecycle_preserves_nonzero_command_diagnostic() -> None:
    with pytest.raises(AssertionError, match=r"returned 7: synthetic failure"):
        lifecycle._run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('synthetic failure\\n'); raise SystemExit(7)",
            ],
            environment=os.environ.copy(),
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group regression")
def test_lifecycle_stops_an_inheriting_grandchild_after_direct_child_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_marker = tmp_path / "grandchild-started"
    survived_marker = tmp_path / "grandchild-survived"
    grandchild_script = (
        "import pathlib,time\n"
        f"pathlib.Path({str(started_marker)!r}).write_text('started', encoding='utf-8')\n"
        "time.sleep(1)\n"
        f"pathlib.Path({str(survived_marker)!r}).write_text('survived', encoding='utf-8')\n"
        "time.sleep(0.2)\n"
    )
    direct_child_script = (
        "import pathlib,subprocess,sys,time\n"
        f"marker = pathlib.Path({str(started_marker)!r})\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild_script!r}])\n"
        "while not marker.exists():\n"
        "    time.sleep(0.01)\n"
    )
    monkeypatch.setattr(lifecycle, "COMMAND_OUTPUT_DRAIN_GRACE_SECONDS", 0.1)
    started = time.monotonic()

    assert (
        lifecycle._run(
            [sys.executable, "-c", direct_child_script],
            environment=os.environ.copy(),
        )
        == ""
    )
    assert time.monotonic() - started < 5
    assert started_marker.read_text(encoding="utf-8") == "started"
    time.sleep(2)
    assert not survived_marker.exists()


@pytest.mark.parametrize("force", [False, True])
def test_windows_tree_cleanup_uses_bounded_system_taskkill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force: bool
) -> None:
    taskkill = tmp_path / "taskkill.exe"
    taskkill.touch()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(lifecycle, "_windows_taskkill_path", lambda: taskkill)
    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)
    process = _SyntheticProcess()

    lifecycle._terminate_windows_process_tree(process, force=force)

    expected_command = [str(taskkill), "/PID", "1234", "/T"]
    if force:
        expected_command.append("/F")
    assert process.killed is force
    assert calls == [
        (
            expected_command,
            {
                "check": False,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "timeout": 2,
            },
        )
    ]


@pytest.mark.skipif(
    any(shutil.which(executable) is None for executable in ("codex", "atready", "uv")),
    reason="live local Codex plugin lifecycle requires codex, atready, and uv",
)
def test_local_codex_plugin_lifecycle_is_isolated_and_reversible(tmp_path: Path) -> None:
    installed_cli = shutil.which("atready")
    assert installed_cli is not None
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT),
            "--atready-executable",
            installed_cli,
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt == {
        "checks": [
            "isolated-codex-home",
            "local-marketplace-bound",
            "plugin-discovered",
            "plugin-installed-enabled",
            "canonical-files-matched",
            "runtime-no-write-contract",
            "private-state-preserved",
            "plugin-removed",
            "marketplace-removed",
        ],
        "codex_cli_version": receipt["codex_cli_version"],
        "isolated_codex_home": True,
        "isolated_user_home": True,
        "marketplace_source": "local",
        "plugin_version": "0.1.13",
        "result": "passed",
        "runtime_contract_version": lifecycle.EXPECTED_RUNTIME_CONTRACT_VERSION,
        "runtime_version": receipt["runtime_version"],
        "selector": "atready@atready",
    }
    assert re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?",
        receipt["codex_cli_version"],
    )
    assert isinstance(receipt["runtime_version"], str)
    assert "/Users/" not in result.stdout
    assert "\\Users\\" not in result.stdout
