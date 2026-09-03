#!/usr/bin/env python3
"""Prove AtReady's local Codex plugin lifecycle in isolated temporary state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PLUGIN = ROOT / "plugins" / "atready"
COMMAND_TIMEOUT_SECONDS = 60
MAX_COMMAND_OUTPUT_CHARACTERS = 65_536
MAX_VERSION_CHARACTERS = 64
EXPECTED_RUNTIME_CONTRACT_VERSION = 1
IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-+][A-Za-z0-9.-]+)?$")
RUNTIME_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,63}$")


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


def _run(command: list[str], *, environment: dict[str, str]) -> str:
    try:
        result = subprocess.run(  # noqa: S603
            command,
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=environment,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"local plugin lifecycle command exceeded {COMMAND_TIMEOUT_SECONDS} seconds"
        ) from exc
    if (
        len(result.stdout) > MAX_COMMAND_OUTPUT_CHARACTERS
        or len(result.stderr) > MAX_COMMAND_OUTPUT_CHARACTERS
    ):
        raise AssertionError("local plugin lifecycle command exceeded its output bound")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise AssertionError(
            f"local plugin lifecycle command returned {result.returncode}: {detail}"
        )
    return result.stdout


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
