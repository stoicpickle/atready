#!/usr/bin/env python3
"""Prove a real AtReady install and first-use journey in disposable local state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_COMMAND_TIMEOUT_SECONDS = 60
_INSTALL_TIMEOUT_SECONDS = 300
_MAX_WHEEL_BYTES = 64 * 1_048_576
_BOUNDARY = "No routed project resources were contacted or run."
_CHECKS = (
    "isolated-real-install",
    "installed-version",
    "offline-doctor",
    "offline-demo",
    "offline-init",
    "offline-resource-add-preview",
    "offline-resource-add-apply",
    "offline-project-validate",
    "offline-first-route",
    "no-real-atready-or-codex-state",
    "post-install-common-python-socket-paths-blocked",
)


def _json_object(text: str, *, subject: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{subject} did not return JSON") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"{subject} did not return a JSON object")
    return value


def _expected_version() -> str:
    value = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = value.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise AssertionError("pyproject.toml omitted the project version")
    return version


def _write_network_guard(path: Path) -> None:
    path.mkdir(mode=0o700)
    (path / "sitecustomize.py").write_text(
        """\
import os
import socket
import sys
from pathlib import Path

root = Path(os.environ["ATREADY_NETWORK_GUARD_DIR"])
def blocked(*_args, **_kwargs):
    with (root / "attempted").open("a", encoding="utf-8") as stream:
        stream.write("python-network-call\\n")
    raise RuntimeError("network disabled by AtReady clean first-use harness")

def audit(event, _args):
    if event.startswith("socket."):
        blocked()

sys.addaudithook(audit)
socket.create_connection = blocked
socket.getaddrinfo = blocked
with (root / "loaded").open("a", encoding="utf-8") as stream:
    stream.write(f"{os.getpid()}\\n")
""",
        encoding="utf-8",
    )


def _isolated_install_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "ATREADY_HOME",
        "QUARTERMASTER_HOME",
        "CODEX_HOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
    ):
        environment.pop(name, None)
    install_home = root / "install-home"
    install_home.mkdir(mode=0o700, exist_ok=True)
    environment.update(
        {
            "ATREADY_HOME": str(root / "install-state-must-not-exist"),
            "QUARTERMASTER_HOME": str(root / "legacy-state-must-not-exist"),
            "CODEX_HOME": str(root / "codex-state-must-not-exist"),
            "HOME": str(install_home),
            "USERPROFILE": str(install_home),
            "XDG_CONFIG_HOME": str(install_home / "config"),
            "XDG_DATA_HOME": str(install_home / "data"),
            "APPDATA": str(install_home / "appdata"),
            "LOCALAPPDATA": str(install_home / "localappdata"),
            "UV_TOOL_DIR": str(root / "uv-tools"),
            "UV_TOOL_BIN_DIR": str(root / "uv-bin"),
            "UV_CACHE_DIR": str(root.parent / "uv-cache"),
            "UV_NO_CONFIG": "1",
            "UV_PYTHON_DOWNLOADS": "never",
        }
    )
    return environment


def _post_install_environment(root: Path, guard: Path) -> dict[str, str]:
    environment = _isolated_install_environment(root)
    home = root / "home"
    home.mkdir(mode=0o700)
    state = root / "state"
    environment.update(
        {
            "ATREADY_HOME": str(state),
            "QUARTERMASTER_HOME": str(root / "legacy-state-must-not-exist"),
            "CODEX_HOME": str(root / "codex-state-must-not-exist"),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "APPDATA": str(home / "appdata"),
            "LOCALAPPDATA": str(home / "localappdata"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(guard),
            "ATREADY_NETWORK_GUARD_DIR": str(guard),
            "UV_OFFLINE": "1",
        }
    )
    return environment


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    expected: int = 0,
    timeout: int = _COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"command exceeded {timeout} seconds: {command[1:]!r}") from exc
    if result.returncode != expected:
        raise AssertionError(
            f"command returned {result.returncode}, expected {expected}: "
            f"{command[1:]!r}: {result.stderr}"
        )
    return result


def _wheel_sha256(path: Path) -> str:
    if path.is_symlink() or path.suffix != ".whl":
        raise AssertionError("wheel lane requires one non-symlink .whl artifact")
    try:
        details = path.stat()
    except OSError as exc:
        raise AssertionError("wheel lane cannot inspect its --wheel artifact") from exc
    if not path.is_file() or details.st_size > _MAX_WHEEL_BYTES:
        raise AssertionError("wheel lane requires one bounded regular --wheel artifact")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1_048_576), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AssertionError("wheel lane cannot read its --wheel artifact") from exc
    return digest.hexdigest()


def _install(
    kind: str,
    root: Path,
    *,
    wheel: Path | None,
    wheel_sha256: str | None,
) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        raise AssertionError("clean first-use harness requires the reviewed uv installer")
    if kind == "source":
        package = _ROOT
    else:
        if wheel is None or wheel_sha256 is None:
            raise AssertionError("wheel lane requires --wheel and --wheel-sha256")
        actual_digest = _wheel_sha256(wheel)
        if actual_digest != wheel_sha256:
            raise AssertionError("wheel lane artifact does not match --wheel-sha256")
        package = wheel
    command = [
        uv,
        "tool",
        "install",
        "--force",
        "--reinstall",
        "--no-config",
        "--no-sources",
        "--no-python-downloads",
        "--python",
        sys.executable,
    ]
    if kind == "source":
        command.extend(["--build-constraints", str(_ROOT / "build-constraints.txt")])
    command.append(str(package.resolve()))
    environment = _isolated_install_environment(root)
    _run(
        command,
        cwd=root,
        environment=environment,
        timeout=_INSTALL_TIMEOUT_SECONDS,
    )
    if kind == "wheel" and _wheel_sha256(package) != wheel_sha256:
        raise AssertionError("wheel lane artifact changed during installation")
    executable = root / "uv-bin" / ("atready.exe" if os.name == "nt" else "atready")
    if not executable.is_file():
        raise AssertionError("isolated install did not create the AtReady console command")
    return executable


def _exercise(
    kind: str,
    root: Path,
    *,
    wheel: Path | None,
    wheel_sha256: str | None,
) -> dict[str, Any]:
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    executable = _install(kind, root, wheel=wheel, wheel_sha256=wheel_sha256)
    guard = root / "network-guard"
    _write_network_guard(guard)
    environment = _post_install_environment(root, guard)
    journey = root / "journey"
    journey.mkdir(mode=0o700)
    state = root / "state"
    commands = 0

    def run(argv: list[str], *, expected: int = 0) -> subprocess.CompletedProcess[str]:
        nonlocal commands
        result = _run(
            [str(executable), *argv],
            cwd=journey,
            environment=environment,
            expected=expected,
        )
        commands += 1
        return result

    expected_version = _expected_version()
    version = run(["--version"])
    if version.stdout != f"atready {expected_version}\n" or version.stderr:
        raise AssertionError("clean install returned the wrong CLI version")

    doctor = _json_object(run(["doctor", "--json"]).stdout, subject="doctor")
    if (
        doctor.get("status") != "ready"
        or doctor.get("runtime_version") != expected_version
        or doctor.get("network_accessed") is not False
        or doctor.get("writes_performed") is not False
    ):
        raise AssertionError("clean install doctor did not return the inert ready contract")

    demo = run(["demo"])
    if _BOUNDARY not in demo.stdout or "Ready to try your own roster?" not in demo.stdout:
        raise AssertionError("clean install demo omitted its first-use or execution boundary")
    if state.exists():
        raise AssertionError("version, doctor, or demo created personal AtReady state")

    initialized = _json_object(run(["init", "--json"]).stdout, subject="init")
    inventory = state / "inventory.yaml"
    if initialized.get("inventory_kind") != "personal" or not inventory.is_file():
        raise AssertionError("clean install did not initialize the isolated personal roster")

    today = date.today().isoformat()
    add = [
        "inventory",
        "add",
        "--id",
        "synthetic-clean-install-agent",
        "--name",
        "Synthetic Clean Install Agent",
        "--category",
        "coding-agent",
        "--capability",
        "code-implementation=0.85",
        "--capability",
        "test-automation=0.80",
        "--access",
        "active",
        "--interaction",
        "local-cli",
        "--session",
        "available",
        "--billing",
        "owned",
        "--marginal-cost",
        "0.10",
        "--quota",
        "ample",
        "--allowed-data-class",
        "internal",
        "--no-requires-network",
        "--confidence-basis",
        "user-judgment",
        "--verified-on",
        today,
        "--json",
    ]
    preview = _json_object(run(add).stdout, subject="resource-add preview")
    if preview.get("applied") is not False or preview.get("operation") != "add-resource":
        raise AssertionError("clean install did not return a no-write resource preview")
    before_apply = inventory.read_bytes()
    receipt = _json_object(
        run(
            [
                *add,
                "--apply",
                "--expect-revision",
                str(preview["expect_revision"]),
                "--expect-plan",
                str(preview["expect_plan"]),
            ]
        ).stdout,
        subject="resource-add receipt",
    )
    if (
        receipt.get("applied") is not True
        or receipt.get("operation") != "add-resource"
        or inventory.read_bytes() == before_apply
    ):
        raise AssertionError("clean install did not apply the exact previewed resource")

    listed = _json_object(
        run(["inventory", "list", "--json"]).stdout,
        subject="inventory list",
    )
    resources = listed.get("resources")
    if not isinstance(resources, list) or [item.get("id") for item in resources] != [
        "synthetic-clean-install-agent"
    ]:
        raise AssertionError("clean install roster did not retain exactly the added resource")

    project = journey / "project.yaml"
    project.write_text(run(["project", "template"]).stdout, encoding="utf-8")
    validation = _json_object(
        run(["project", "validate", str(project), "--json"]).stdout,
        subject="project validation",
    )
    if validation.get("valid") is not True:
        raise AssertionError("clean install project template did not validate")
    route = run(["route", "--project", str(project), "--format", "agent-summary"])
    if "Synthetic Clean Install Agent" not in route.stdout or not route.stdout.endswith(
        _BOUNDARY + "\n"
    ):
        raise AssertionError("clean install route omitted its resource or execution boundary")

    untouched_state = (
        root / "install-state-must-not-exist",
        root / "legacy-state-must-not-exist",
        root / "codex-state-must-not-exist",
    )
    if any(path.exists() for path in untouched_state):
        raise AssertionError("install or first-use lane touched unrelated AtReady or Codex state")
    if (guard / "attempted").exists():
        raise AssertionError(
            "an AtReady command attempted Python network access after installation"
        )
    loaded = (guard / "loaded").read_text(encoding="utf-8").splitlines()
    if len(loaded) != commands:
        raise AssertionError("network guard did not load for every post-install AtReady command")

    return {
        "checks": list(_CHECKS),
        "commands_checked": commands,
        "install_kind": kind,
        "installed_version": expected_version,
        "mutation_scope": "disposable-isolated-directory-only",
        "network_after_install": "common-python-socket-paths-blocked",
        "result": "passed",
        "synthetic_only": True,
    }


def run_lanes(
    root: Path,
    kinds: tuple[str, ...],
    *,
    wheel: Path | None,
    wheel_sha256: str | None,
) -> dict[str, Any]:
    """Run selected install lanes in a new caller-approved disposable root."""

    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    lanes = [
        _exercise(
            kind,
            root / kind,
            wheel=wheel,
            wheel_sha256=wheel_sha256,
        )
        for kind in kinds
    ]
    return {
        "installations": lanes,
        "mutation_scope": "disposable-isolated-directory-only",
        "network_after_install": "common-python-socket-paths-blocked",
        "real_atready_or_codex_state_accessed": False,
        "result": "passed",
        "synthetic_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        choices=("source", "wheel", "all"),
        default="all",
        help="Install from the current source, one exact wheel, or both (default: all)",
    )
    parser.add_argument("--wheel", type=Path, help="Exact wheel for the wheel or all lane")
    parser.add_argument(
        "--wheel-sha256",
        help="Required expected SHA-256 for the exact wheel artifact",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Use this new disposable root; it must not already exist",
    )
    args = parser.parse_args()
    kinds = ("source", "wheel") if args.install == "all" else (args.install,)
    wheel = args.wheel.absolute() if args.wheel is not None else None
    if "wheel" in kinds and wheel is None:
        parser.error("--wheel is required for the wheel or all lane")
    if "wheel" in kinds and args.wheel_sha256 is None:
        parser.error("--wheel-sha256 is required for the wheel or all lane")
    if args.root is not None:
        receipt = run_lanes(
            args.root.resolve(),
            kinds,
            wheel=wheel,
            wheel_sha256=args.wheel_sha256,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="atready-clean-first-use-") as directory:
            receipt = run_lanes(
                Path(directory) / "lanes",
                kinds,
                wheel=wheel,
                wheel_sha256=args.wheel_sha256,
            )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
