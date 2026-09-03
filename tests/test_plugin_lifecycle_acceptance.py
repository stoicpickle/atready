from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "plugin_lifecycle_acceptance.py"
SPEC = importlib.util.spec_from_file_location("atready_plugin_lifecycle", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
lifecycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lifecycle)


def test_lifecycle_rejects_unbounded_command_output(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess(
        args=["synthetic"],
        returncode=0,
        stdout="x" * (lifecycle.MAX_COMMAND_OUTPUT_CHARACTERS + 1),
        stderr="",
    )
    monkeypatch.setattr(lifecycle.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(AssertionError, match="output bound"):
        lifecycle._run(["synthetic"], environment={})


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
