#!/usr/bin/env python3
"""Exercise AtReady install and skill-resolution risks in an isolated directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_CANONICAL_SKILL = _ROOT / "plugins" / "atready" / "skills" / "project-atready"
_WRAPPER_RELATIVE = Path("scripts/atready.py")
_REQUIRED_SKILL_FILES = (
    Path("SKILL.md"),
    _WRAPPER_RELATIVE,
    Path("references/output-contract.md"),
    Path("references/routing-rules.md"),
    Path("references/runtime-setup.md"),
)
_COMMAND_TIMEOUT_SECONDS = 15


def _skill_fingerprint(path: Path) -> str | None:
    """Return a stable digest for a complete skill bundle, otherwise ``None``."""

    if not path.is_dir() or any(
        not (path / relative).is_file() for relative in _REQUIRED_SKILL_FILES
    ):
        return None
    digest = hashlib.sha256()
    for file_path in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = file_path.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = file_path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _skill_status(path: Path) -> dict[str, str | None]:
    if not path.is_dir():
        return {"path": str(path), "status": "not-found", "fingerprint": None}
    fingerprint = _skill_fingerprint(path)
    return {
        "path": str(path),
        "status": "ready" if fingerprint is not None else "incomplete",
        "fingerprint": fingerprint,
    }


def inspect_skill_precedence(paths: list[Path]) -> dict[str, Any]:
    """Inspect ordered candidate locations without asserting Codex's discovery policy.

    ``paths`` are ordered by the caller's assumed precedence. The report flags every
    multiple-ready state because hosts can use a different discovery order.
    """

    locations = [_skill_status(path) for path in paths]
    ready = [location for location in locations if location["status"] == "ready"]
    fingerprints = {location["fingerprint"] for location in ready}
    return {
        "assumed_effective_path": ready[0]["path"] if ready else None,
        "content_mismatch": len(fingerprints) > 1,
        "duplicate_risk": len(ready) > 1,
        "locations": locations,
        "ready_count": len(ready),
    }


def _write_executable(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _runtime_payload(*, plugin_version: str, missing_feature: bool = False) -> dict[str, Any]:
    features = [
        "inventory.mutate-preview-apply.v1",
        "inventory.read.v1",
        "resource.profiles.v1",
        "routing.plan-only.v1",
        "routing.presentation-bundle.v1",
        "schema.declarations.v1",
    ]
    if missing_feature:
        features.remove("routing.plan-only.v1")
    return {
        "compatible": True,
        "inventory_read": False,
        "missing_features": [],
        "network_accessed": False,
        "plugin_contract_version": 1,
        "plugin_version": plugin_version,
        "product": "project-atready",
        "runtime_contract_version": 1,
        "runtime_features": features,
        "runtime_version": "9.9.9",
        "status": "ready",
        "writes_performed": False,
    }


def _invoke_staged_wrapper(
    root: Path,
    *,
    plugin_version: str = "0.1.7",
    missing_feature: bool = False,
) -> subprocess.CompletedProcess[str]:
    skill = root / "staged-plugin" / "skills" / "project-atready"
    shutil.copytree(_CANONICAL_SKILL, skill)
    tool_bin = root / "uv-tools"
    tool_bin.mkdir()
    fake_path = root / "fake-path"
    fake_path.mkdir()

    runtime = tool_bin / ("atready.exe" if os.name == "nt" else "atready")
    payload = json.dumps(
        _runtime_payload(plugin_version=plugin_version, missing_feature=missing_feature),
        sort_keys=True,
    )
    _write_executable(
        runtime,
        "import sys\n"
        f"payload = {payload!r}\n"
        "if len(sys.argv) > 1 and sys.argv[1] == 'doctor':\n"
        "    print(payload)\n"
        "else:\n"
        "    print('SYNTHETIC-DELEGATED-RUNTIME')\n",
    )
    uv = fake_path / ("uv.exe" if os.name == "nt" else "uv")
    _write_executable(uv, f"print({str(tool_bin)!r})\n")

    environment = os.environ.copy()
    environment["PATH"] = str(fake_path)
    environment["ATREADY_HOME"] = str(root / "private-state-must-not-exist")
    environment.pop("PYTHONPATH", None)
    if os.name == "nt":
        # A text fixture cannot emulate uv's native Windows console launcher. Exercise the
        # same staged launcher's resolver and strict handshake in-process instead; the release
        # wheel smoke separately proves the native console entry point on Windows CI.
        namespace = runpy.run_path(str(skill / _WRAPPER_RELATIVE))
        launcher_globals = namespace["_resolve_command"].__globals__
        launcher_globals["_uv_tool_bin"] = lambda: tool_bin
        launcher_globals["_run_bounded"] = lambda _command: subprocess.CompletedProcess(
            _command,
            0,
            payload + "\n",
            "",
        )
        try:
            _executable, command = namespace["_resolve_command"](platform="win32")
            namespace["_verify_runtime_contract"](command)
        except SystemExit as exc:
            return subprocess.CompletedProcess([], 1, "", f"{exc}\n")
        return subprocess.CompletedProcess([], 0, "SYNTHETIC-DELEGATED-RUNTIME\n", "")
    return subprocess.run(  # noqa: S603
        [sys.executable, str(skill / _WRAPPER_RELATIVE), "--version"],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )


def run_matrix(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)

    compatible = _invoke_staged_wrapper(root / "compatible")
    if compatible.returncode != 0 or compatible.stdout != "SYNTHETIC-DELEGATED-RUNTIME\n":
        raise AssertionError(f"fresh compatible stage failed: {compatible.stderr}")

    stale = _invoke_staged_wrapper(root / "stale", plugin_version="0.1.6")
    if stale.returncode == 0 or "refusing to continue" not in stale.stderr:
        raise AssertionError("stale runtime was not rejected before delegation")
    if "SYNTHETIC-DELEGATED-RUNTIME" in stale.stdout + stale.stderr:
        raise AssertionError("stale runtime delegated the requested command")

    incomplete_runtime = _invoke_staged_wrapper(root / "incomplete-runtime", missing_feature=True)
    if incomplete_runtime.returncode == 0 or "incomplete" not in incomplete_runtime.stderr:
        raise AssertionError("feature-incomplete runtime was not rejected before delegation")

    discovery = root / "skill-discovery"
    complete = discovery / "personal" / "project-atready"
    incomplete = discovery / "incomplete" / "project-atready"
    workspace = discovery / "workspace" / "project-atready"
    shutil.copytree(_CANONICAL_SKILL, complete)
    incomplete.mkdir(parents=True)
    (incomplete / "SKILL.md").write_text("synthetic incomplete skill\n", encoding="utf-8")
    shutil.copytree(_CANONICAL_SKILL, workspace)
    with (workspace / "SKILL.md").open("a", encoding="utf-8") as stream:
        stream.write("\n<!-- synthetic divergent copy -->\n")

    complete_status = _skill_status(complete)
    incomplete_status = _skill_status(incomplete)
    precedence = inspect_skill_precedence([workspace, complete])
    if complete_status["status"] != "ready":
        raise AssertionError("complete skill bundle was not detected")
    if incomplete_status["status"] != "incomplete":
        raise AssertionError("incomplete skill bundle was not detected")
    if not precedence["duplicate_risk"] or not precedence["content_mismatch"]:
        raise AssertionError("divergent duplicate skill copies did not surface precedence risk")

    private_state_paths = sorted(root.rglob("private-state-must-not-exist"))
    if private_state_paths:
        raise AssertionError(
            f"launcher compatibility checks wrote private state: {private_state_paths}"
        )

    return {
        "checks": [
            "fresh-compatible-runtime-handshake",
            "stale-runtime-rejected-before-delegation",
            "incomplete-runtime-rejected-before-delegation",
            "complete-skill-bundle-detected",
            "incomplete-skill-bundle-detected",
            "divergent-duplicate-skill-precedence-risk-detected",
            "no-private-state-write",
        ],
        "duplicate_probe": precedence,
        "mutation_scope": "caller-provided-isolated-directory-only",
        "result": "passed",
        "synthetic_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        help=(
            "Create and use this new path beneath a disposable directory instead of an "
            "automatic temporary directory; the path must not already exist."
        ),
    )
    args = parser.parse_args()
    if args.root is not None:
        receipt = run_matrix(args.root.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="atready-elevated-install-") as directory:
            receipt = run_matrix(Path(directory) / "matrix")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
