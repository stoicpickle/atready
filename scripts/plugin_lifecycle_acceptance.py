#!/usr/bin/env python3
"""Prove AtReady's local Codex plugin lifecycle in isolated temporary state."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN = ROOT / "plugins" / "atready"
COMMAND_TIMEOUT_SECONDS = 60
MAX_COMMAND_OUTPUT_CHARACTERS = 65_536
COMMAND_OUTPUT_CHUNK_BYTES = 8_192
COMMAND_OUTPUT_DRAIN_GRACE_SECONDS = 0.25
COMMAND_TERMINATION_GRACE_SECONDS = 1
MAX_VERSION_CHARACTERS = 64
EXPECTED_RUNTIME_CONTRACT_VERSION = 1
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$")
RUNTIME_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,63}$")


class _BoundedCapture:
    def __init__(self) -> None:
        self.chunks: list[str] = []
        self.characters = 0
        self.exceeded = False
        self.error: BaseException | None = None


def _strict_json(path: Path) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _resolve_executable(value: str | None, default: str) -> Path:
    requested = value or default
    located = shutil.which(requested)
    candidate = Path(located if located is not None else requested).expanduser().absolute()
    try:
        metadata = candidate.stat()
    except OSError as exc:
        raise RuntimeError(f"required executable is unavailable: {default}") from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(candidate, os.X_OK):
        raise RuntimeError(f"required executable is not runnable: {default}")
    return candidate


def _capture_stream(
    stream: BinaryIO,
    capture: _BoundedCapture,
    stop_requested: threading.Event,
) -> None:
    decoder = io.IncrementalNewlineDecoder(
        codecs.getincrementaldecoder("utf-8")(errors="backslashreplace"),
        translate=True,
    )

    def append(text: str) -> bool:
        remaining = MAX_COMMAND_OUTPUT_CHARACTERS - capture.characters
        if len(text) > remaining:
            if remaining > 0:
                capture.chunks.append(text[:remaining])
                capture.characters += remaining
            capture.exceeded = True
            stop_requested.set()
            return False
        capture.chunks.append(text)
        capture.characters += len(text)
        return True

    try:
        while True:
            raw = stream.read1(COMMAND_OUTPUT_CHUNK_BYTES)
            if not raw:
                append(decoder.decode(b"", final=True))
                break
            if not append(decoder.decode(raw)):
                break
    except BaseException as exc:
        capture.error = exc
        stop_requested.set()
    finally:
        stream.close()


def _windows_taskkill_path() -> Path | None:
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32_768)
        length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
        system_directory = Path(buffer.value) if 0 < length < len(buffer) else None
    except (AttributeError, OSError, ValueError):
        return None
    taskkill = system_directory / "taskkill.exe" if system_directory is not None else None
    return taskkill if taskkill is not None and taskkill.is_file() else None


def _terminate_windows_process_tree(process: subprocess.Popen[bytes], *, force: bool) -> None:
    taskkill = _windows_taskkill_path()
    if taskkill is not None:
        command = [str(taskkill), "/PID", str(process.pid), "/T"]
        if force:
            command.append("/F")
        try:
            subprocess.run(  # noqa: S603 - resolved from the Windows system directory
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if force and process.poll() is None:
        process.kill()


def _signal_process_tree(process: subprocess.Popen[bytes], *, force: bool) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except OSError:
            if process.poll() is None:
                if force:
                    process.kill()
                else:
                    process.terminate()
    elif os.name == "nt":
        _terminate_windows_process_tree(process, force=force)
    elif force and process.poll() is None:  # pragma: no cover - unsupported platform fallback
        process.kill()


def _join_capture_threads(threads: list[threading.Thread], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    return not any(thread.is_alive() for thread in threads)


def _terminate_and_reap(
    process: subprocess.Popen[bytes],
    capture_threads: list[threading.Thread],
) -> None:
    _signal_process_tree(process, force=False)
    try:
        process.wait(timeout=COMMAND_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_process_tree(process, force=True)
        process.wait()
    if _join_capture_threads(capture_threads, COMMAND_TERMINATION_GRACE_SECONDS):
        return
    _signal_process_tree(process, force=True)
    if not _join_capture_threads(capture_threads, COMMAND_TERMINATION_GRACE_SECONDS):
        raise AssertionError("local plugin lifecycle command left descendant output pipes open")


def _run(command: list[str], *, environment: dict[str, str]) -> str:
    process = subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        env=environment,
        start_new_session=os.name == "posix",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    if process.stdout is None or process.stderr is None:
        _terminate_and_reap(process, [])
        raise AssertionError("local plugin lifecycle command output was unavailable")

    stdout = _BoundedCapture()
    stderr = _BoundedCapture()
    stop_requested = threading.Event()
    capture_threads = [
        threading.Thread(
            target=_capture_stream,
            args=(process.stdout, stdout, stop_requested),
            name="atready-lifecycle-stdout",
            daemon=True,
        ),
        threading.Thread(
            target=_capture_stream,
            args=(process.stderr, stderr, stop_requested),
            name="atready-lifecycle-stderr",
            daemon=True,
        ),
    ]
    for thread in capture_threads:
        thread.start()

    deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
    timed_out = False
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            if stop_requested.wait(timeout=min(remaining, 0.05)):
                break
        if timed_out or stop_requested.is_set():
            _terminate_and_reap(process, capture_threads)
        else:
            process.wait()
            if not _join_capture_threads(capture_threads, COMMAND_OUTPUT_DRAIN_GRACE_SECONDS):
                _terminate_and_reap(process, capture_threads)
    except BaseException:
        if process.poll() is None or any(thread.is_alive() for thread in capture_threads):
            try:
                _terminate_and_reap(process, capture_threads)
            except AssertionError:
                pass
        raise

    if timed_out:
        raise AssertionError(
            f"local plugin lifecycle command exceeded {COMMAND_TIMEOUT_SECONDS} seconds"
        )
    for capture in (stdout, stderr):
        if capture.error is not None:
            raise capture.error
    if stdout.exceeded or stderr.exceeded:
        raise AssertionError("local plugin lifecycle command exceeded its output bound")

    stdout_text = "".join(stdout.chunks)
    stderr_text = "".join(stderr.chunks)
    if process.returncode != 0:
        detail = stderr_text.strip() or stdout_text.strip() or "no diagnostic output"
        raise AssertionError(
            f"local plugin lifecycle command returned {process.returncode}: {detail}"
        )
    return stdout_text


def _regular_file_hashes(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise AssertionError(f"plugin tree contains a symbolic link: {relative}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise AssertionError(f"plugin tree contains a non-regular file: {relative}")
        values[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not values:
        raise AssertionError("plugin tree contains no regular files")
    return values


def _load_config(codex_home: Path) -> dict[str, object]:
    path = codex_home / "config.toml"
    if not path.is_file():
        raise AssertionError("Codex did not create isolated plugin configuration")
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("Codex created invalid isolated plugin configuration")
    return payload


def _table(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key, {})
    if not isinstance(value, dict):
        raise AssertionError(f"Codex configuration table is invalid: {key}")
    return value


def _marketplace_contract() -> tuple[str, str, str]:
    payload = _strict_json(MARKETPLACE)
    marketplace_name = payload.get("name")
    plugins = payload.get("plugins")
    if not isinstance(marketplace_name, str) or not marketplace_name:
        raise AssertionError("marketplace lacks a stable name")
    if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
        raise AssertionError("marketplace must expose exactly one local pilot plugin")
    plugin_name = plugins[0].get("name")
    source = plugins[0].get("source")
    if not isinstance(plugin_name, str) or not plugin_name:
        raise AssertionError("marketplace plugin lacks a stable name")
    if IDENTIFIER.fullmatch(marketplace_name) is None or IDENTIFIER.fullmatch(plugin_name) is None:
        raise AssertionError("marketplace and plugin names must be bounded identifiers")
    if source != {"source": "local", "path": "./plugins/atready"}:
        raise AssertionError("pilot marketplace must use the canonical local plugin source")
    return marketplace_name, plugin_name, f"{plugin_name}@{marketplace_name}"


def run_lifecycle(
    *, codex_executable: str | None = None, atready_executable: str | None = None
) -> dict[str, object]:
    codex = _resolve_executable(codex_executable, "codex")
    atready = _resolve_executable(atready_executable, "atready")
    uv = _resolve_executable(None, "uv")
    marketplace_name, plugin_name, selector = _marketplace_contract()
    manifest = _strict_json(PLUGIN / ".codex-plugin" / "plugin.json")
    plugin_version = manifest.get("version")
    if (
        not isinstance(plugin_version, str)
        or len(plugin_version) > MAX_VERSION_CHARACTERS
        or SEMVER.fullmatch(plugin_version) is None
    ):
        raise AssertionError("plugin manifest lacks a version")
    expected_files = _regular_file_hashes(PLUGIN)

    with tempfile.TemporaryDirectory(prefix="atready-plugin-lifecycle-") as directory:
        temporary_root = Path(directory).resolve()
        codex_home = temporary_root / "codex-home"
        private_state = temporary_root / "atready-state"
        isolated_home = temporary_root / "user-home"
        xdg_config = temporary_root / "xdg-config"
        xdg_cache = temporary_root / "xdg-cache"
        xdg_data = temporary_root / "xdg-data"
        xdg_state = temporary_root / "xdg-state"
        for path in (
            codex_home,
            private_state,
            isolated_home,
            xdg_config,
            xdg_cache,
            xdg_data,
            xdg_state,
        ):
            path.mkdir()
        sentinel = private_state / "inventory.yaml"
        sentinel.write_bytes(b"synthetic lifecycle sentinel\n")
        state_before = _regular_file_hashes(private_state)

        path_parts = dict.fromkeys(
            [str(codex.parent), str(atready.parent), str(uv.parent), *os.defpath.split(os.pathsep)]
        )
        environment = {
            "ATREADY_HOME": str(private_state),
            "CODEX_HOME": str(codex_home),
            "HOME": str(isolated_home),
            "PATH": os.pathsep.join(path_parts),
            "UV_TOOL_BIN_DIR": str(atready.parent),
            "XDG_CACHE_HOME": str(xdg_cache),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_DATA_HOME": str(xdg_data),
            "XDG_STATE_HOME": str(xdg_state),
        }
        for inherited in ("LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "WINDIR"):
            if inherited in os.environ:
                environment[inherited] = os.environ[inherited]

        codex_version_output = _run([str(codex), "--version"], environment=environment).strip()
        codex_version_match = SEMVER.fullmatch(codex_version_output.removeprefix("codex-cli "))
        if (
            len(codex_version_output) > len("codex-cli ") + MAX_VERSION_CHARACTERS
            or not codex_version_output.startswith("codex-cli ")
            or codex_version_match is None
        ):
            raise AssertionError("Codex returned an unexpected version string")
        codex_version = codex_version_match.group(0)

        _run(
            [str(codex), "plugin", "marketplace", "add", str(ROOT)],
            environment=environment,
        )
        config = _load_config(codex_home)
        marketplace_config = _table(config, "marketplaces").get(marketplace_name)
        if not isinstance(marketplace_config, dict) or (
            marketplace_config.get("source_type") != "local"
            or marketplace_config.get("source") != str(ROOT)
        ):
            raise AssertionError("Codex did not bind the pilot to the exact local marketplace")

        before_install = _run(
            [str(codex), "plugin", "list", "--marketplace", marketplace_name],
            environment=environment,
        )
        if selector not in before_install or "not installed" not in before_install:
            raise AssertionError("Codex did not expose the uninstalled local pilot")

        _run([str(codex), "plugin", "add", selector], environment=environment)
        installed = _run(
            [str(codex), "plugin", "list", "--marketplace", marketplace_name],
            environment=environment,
        )
        if selector not in installed or "installed, enabled" not in installed:
            raise AssertionError("Codex did not report the local pilot as installed and enabled")
        config = _load_config(codex_home)
        installed_config = _table(config, "plugins").get(selector)
        if not isinstance(installed_config, dict) or installed_config.get("enabled") is not True:
            raise AssertionError("Codex did not enable the installed local pilot")

        installed_plugin = (
            codex_home / "plugins" / "cache" / marketplace_name / plugin_name / plugin_version
        )
        if _regular_file_hashes(installed_plugin) != expected_files:
            raise AssertionError("Codex cache does not exactly match the canonical plugin tree")

        wrapper = installed_plugin / "skills" / "project-atready" / "scripts" / "atready.py"
        runtime_contract = json.loads(
            _run(
                [sys.executable, str(wrapper), "runtime", "contract", "--json"],
                environment=environment,
            )
        )
        if not isinstance(runtime_contract, dict) or (
            runtime_contract.get("product") != "project-atready"
            or runtime_contract.get("inventory_read") is not False
            or runtime_contract.get("network_accessed") is not False
            or runtime_contract.get("writes_performed") is not False
        ):
            raise AssertionError("installed plugin did not negotiate a no-write runtime contract")
        runtime_version = runtime_contract.get("runtime_version")
        runtime_contract_version = runtime_contract.get("contract_version")
        if (
            not isinstance(runtime_version, str)
            or RUNTIME_VERSION.fullmatch(runtime_version) is None
            or type(runtime_contract_version) is not int
            or runtime_contract_version != EXPECTED_RUNTIME_CONTRACT_VERSION
        ):
            raise AssertionError("installed plugin returned invalid runtime contract metadata")
        if _regular_file_hashes(private_state) != state_before:
            raise AssertionError("plugin lifecycle or runtime handshake changed private state")

        _run([str(codex), "plugin", "remove", selector], environment=environment)
        if installed_plugin.exists():
            raise AssertionError("Codex left the removed plugin version in its cache")
        removed = _run(
            [str(codex), "plugin", "list", "--marketplace", marketplace_name],
            environment=environment,
        )
        if selector not in removed or "not installed" not in removed:
            raise AssertionError("Codex did not report the local pilot as removed")
        if selector in _table(_load_config(codex_home), "plugins"):
            raise AssertionError("Codex left the removed plugin enabled in configuration")

        _run(
            [str(codex), "plugin", "marketplace", "remove", marketplace_name],
            environment=environment,
        )
        if marketplace_name in _table(_load_config(codex_home), "marketplaces"):
            raise AssertionError("Codex left the removed marketplace in configuration")
        if _regular_file_hashes(private_state) != state_before:
            raise AssertionError("plugin cleanup changed private state")
        if (isolated_home / ".agents").exists():
            raise AssertionError("plugin lifecycle unexpectedly created personal agent state")

    return {
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
        "codex_cli_version": codex_version,
        "isolated_codex_home": True,
        "isolated_user_home": True,
        "marketplace_source": "local",
        "plugin_version": plugin_version,
        "result": "passed",
        "runtime_contract_version": runtime_contract_version,
        "runtime_version": runtime_version,
        "selector": selector,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-executable")
    parser.add_argument("--atready-executable")
    arguments = parser.parse_args()
    print(
        json.dumps(
            run_lifecycle(
                codex_executable=arguments.codex_executable,
                atready_executable=arguments.atready_executable,
            ),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
