#!/usr/bin/env python3
"""Run a compatible AtReady local runtime for this plugin."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

PLUGIN_VERSION = "0.1.6"
REQUIRED_RUNTIME_CONTRACT_VERSION = 1
REQUIRED_RUNTIME_FEATURE_IDS = (
    "inventory.mutate-preview-apply.v1",
    "inventory.read.v1",
    "resource.profiles.v1",
    "routing.plan-only.v1",
    "routing.presentation-bundle.v1",
    "schema.declarations.v1",
)
_HANDSHAKE_TIMEOUT_SECONDS = 10
_MAX_HANDSHAKE_BYTES = 32_768
_UV_TOOL_BIN_ARGUMENTS = ("--offline", "--no-config", "tool", "dir", "--bin")
_FEATURE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_PRODUCT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,63}$")


class _BoundedOutputError(RuntimeError):
    """The compatibility process exceeded its per-stream output budget."""


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            if process.poll() is None:
                process.kill()
    elif os.name == "nt":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(32_768)
            length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
            system_directory = Path(buffer.value) if 0 < length < len(buffer) else None
        except (AttributeError, OSError, ValueError):
            system_directory = None
        taskkill = system_directory / "taskkill.exe" if system_directory is not None else None
        if taskkill is not None and taskkill.is_file():
            try:
                subprocess.run(  # noqa: S603
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            process.kill()
    elif process.poll() is None:  # pragma: no cover - unsupported platform fallback
        process.kill()


def _run_bounded(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one doctor command while bounding stdout and stderr during capture."""

    process = subprocess.Popen(  # noqa: S603
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    if process.stdout is None or process.stderr is None:  # pragma: no cover - Popen contract
        _terminate_process_tree(process)
        raise OSError("doctor output pipes were unavailable")

    stop = threading.Event()
    outputs = [bytearray(), bytearray()]
    failures: list[OSError] = []

    def drain(stream: object, destination: bytearray) -> None:
        try:
            while True:
                chunk = stream.read(4096)  # type: ignore[attr-defined]
                if not chunk:
                    return
                if len(destination) + len(chunk) > _MAX_HANDSHAKE_BYTES:
                    stop.set()
                    return
                destination.extend(chunk)
        except OSError as exc:
            failures.append(exc)
            stop.set()

    threads = [
        threading.Thread(target=drain, args=(process.stdout, outputs[0]), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, outputs[1]), daemon=True),
    ]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + _HANDSHAKE_TIMEOUT_SECONDS
    timed_out = False
    while process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        if stop.wait(min(0.05, remaining)):
            break
    # The direct command may exit after spawning a descendant that inherited a
    # handshake pipe. Reap the entire isolated tree on every completion path.
    _terminate_process_tree(process)
    process.wait()
    for thread in threads:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            thread.join(remaining)

    if any(thread.is_alive() for thread in threads):
        _terminate_process_tree(process)
        for thread in threads:
            thread.join(0.25)
        raise subprocess.TimeoutExpired(command, _HANDSHAKE_TIMEOUT_SECONDS)

    if failures:
        raise failures[0]
    if timed_out:
        raise subprocess.TimeoutExpired(command, _HANDSHAKE_TIMEOUT_SECONDS)
    if stop.is_set():
        raise _BoundedOutputError("doctor output exceeded its bounded capture")
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        outputs[0].decode("utf-8"),
        outputs[1].decode("utf-8"),
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _uv_tool_bin() -> Path:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit(
            "AtReady requires uv to locate the separately installed CLI; "
            "install uv and ensure its executable is on PATH."
        )
    if not Path(uv).is_absolute():
        raise SystemExit(
            "AtReady requires PATH to resolve uv to an absolute executable path; "
            "refusing to continue."
        )

    try:
        result = _run_bounded([uv, *_UV_TOOL_BIN_ARGUMENTS])
    except (OSError, UnicodeError, subprocess.TimeoutExpired, _BoundedOutputError) as exc:
        raise SystemExit(
            "AtReady could not resolve uv's tool executable directory; refusing to continue."
        ) from exc

    lines = result.stdout.splitlines()
    if (
        result.returncode != 0
        or result.stderr
        or len(lines) != 1
        or not lines[0]
        or "\0" in lines[0]
        or lines[0].strip() != lines[0]
    ):
        raise SystemExit(
            "AtReady could not resolve uv's tool executable directory; refusing to continue."
        )

    tool_bin = Path(lines[0])
    if not tool_bin.is_absolute():
        raise SystemExit(
            "AtReady requires uv's tool executable directory to be an absolute path; "
            "refusing to continue."
        )
    return tool_bin


def _resolve_command(*, platform: str | None = None) -> tuple[str, list[str]]:
    wrapper = Path(__file__).resolve()
    executable_name = "atready.exe" if (platform or sys.platform) == "win32" else "atready"
    candidate = _uv_tool_bin() / executable_name

    try:
        installed = candidate.resolve(strict=True)
        installed_mode = installed.stat().st_mode
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(
            "AtReady requires a compatible, separately installed project-atready "
            "local runtime in uv's tool executable directory. Install or update the runtime "
            "using the bundled runtime-setup instructions, then retry through the plugin."
        ) from exc

    if not stat.S_ISREG(installed_mode) or installed == wrapper:
        raise SystemExit(
            "AtReady requires a compatible, separately installed project-atready "
            "local runtime in uv's tool executable directory. Install or update the runtime "
            "using the bundled runtime-setup instructions, then retry through the plugin."
        )

    executable = str(installed)
    return executable, [executable]


def _verify_runtime_contract(command: list[str]) -> None:
    doctor_arguments = [
        "doctor",
        "--plugin-version",
        PLUGIN_VERSION,
        "--plugin-contract",
        str(REQUIRED_RUNTIME_CONTRACT_VERSION),
    ]
    for feature_id in REQUIRED_RUNTIME_FEATURE_IDS:
        doctor_arguments.extend(("--require-feature", feature_id))
    doctor_arguments.append("--json")
    try:
        result = _run_bounded([*command, *doctor_arguments])
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(
            "AtReady could not verify the installed local runtime; refusing to continue. "
            "Reinstall or update project-atready, then retry through the plugin."
        ) from exc
    except _BoundedOutputError as exc:
        raise SystemExit(
            "AtReady received an invalid local runtime compatibility report; refusing to "
            "continue. Reinstall or update project-atready, then retry through the plugin."
        ) from exc

    if result.returncode != 0 or result.stderr or not result.stdout:
        raise SystemExit(
            "AtReady received an invalid local runtime compatibility report; refusing to "
            "continue. Reinstall or update project-atready, then retry through the plugin."
        )

    try:
        payload = json.loads(result.stdout, object_pairs_hook=_unique_json_object)
        if not isinstance(payload, dict) or set(payload) != {
            "compatible",
            "inventory_read",
            "missing_features",
            "network_accessed",
            "plugin_contract_version",
            "plugin_version",
            "product",
            "runtime_contract_version",
            "runtime_features",
            "runtime_version",
            "status",
            "writes_performed",
        }:
            raise ValueError("invalid report shape")
        if (
            payload["compatible"] is not True
            or payload["inventory_read"] is not False
            or payload["missing_features"] != []
            or payload["status"] != "ready"
            or payload["network_accessed"] is not False
            or payload["writes_performed"] is not False
            or payload["plugin_version"] != PLUGIN_VERSION
            or type(payload["plugin_contract_version"]) is not int
            or payload["plugin_contract_version"] != REQUIRED_RUNTIME_CONTRACT_VERSION
            or payload["product"] != "project-atready"
            or type(payload["runtime_contract_version"]) is not int
            or payload["runtime_contract_version"] != REQUIRED_RUNTIME_CONTRACT_VERSION
            or not isinstance(payload["runtime_version"], str)
            or _PRODUCT_VERSION.fullmatch(payload["runtime_version"]) is None
        ):
            raise ValueError("invalid report metadata")

        features = payload["runtime_features"]
        if (
            not isinstance(features, list)
            or any(
                not isinstance(value, str)
                or len(value) > 100
                or _FEATURE_ID.fullmatch(value) is None
                for value in features
            )
            or features != sorted(set(features))
        ):
            raise ValueError("invalid contract values")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(
            "AtReady received an invalid local runtime compatibility report; refusing to "
            "continue. Reinstall or update project-atready, then retry through the plugin."
        ) from exc

    if not set(REQUIRED_RUNTIME_FEATURE_IDS).issubset(features):
        raise SystemExit(
            "AtReady received an incomplete local runtime compatibility report; refusing "
            "to continue. Update project-atready. No command was delegated."
        )


def main() -> None:
    executable, command = _resolve_command()
    _verify_runtime_contract(command)
    os.execv(executable, [*command, *sys.argv[1:]])  # noqa: S606


if __name__ == "__main__":
    main()
