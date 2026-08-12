"""Exercise a staged skills-only plugin through an installed compatible runtime."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

_COMMAND_TIMEOUT_SECONDS = 60
_EXPECTED_PNG_ASSETS = {
    "icon.png": (512, 512),
    "logo-dark.png": (1200, 300),
    "logo.png": (1200, 300),
    "route-overview.png": (1440, 900),
    "safe-preview.png": (1440, 900),
}
_MAX_PNG_BYTES = 2 * 1024 * 1024
_MAX_PNG_CHUNKS = 4096
_PRODUCT_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_FEATURE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_MAX_PRODUCT_VERSION_CHARACTERS = 64
_MAX_REQUIRED_FEATURE_IDS = 100
_MAX_FEATURE_ID_CHARACTERS = 100


def _launcher_requirements(path: Path) -> tuple[str, int, tuple[str, ...]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    wanted = {
        "PLUGIN_VERSION",
        "REQUIRED_RUNTIME_CONTRACT_VERSION",
        "REQUIRED_RUNTIME_FEATURE_IDS",
    }
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted:
            values[target.id] = ast.literal_eval(node.value)
    version = values.get("PLUGIN_VERSION")
    contract = values.get("REQUIRED_RUNTIME_CONTRACT_VERSION")
    features = values.get("REQUIRED_RUNTIME_FEATURE_IDS")
    if (
        not isinstance(version, str)
        or len(version) > _MAX_PRODUCT_VERSION_CHARACTERS
        or _PRODUCT_VERSION_PATTERN.fullmatch(version) is None
        or not isinstance(contract, int)
        or isinstance(contract, bool)
        or contract < 1
        or not isinstance(features, tuple)
        or not features
        or len(features) > _MAX_REQUIRED_FEATURE_IDS
        or any(
            not isinstance(feature, str)
            or len(feature) > _MAX_FEATURE_ID_CHARACTERS
            or _FEATURE_PATTERN.fullmatch(feature) is None
            for feature in features
        )
        or list(features) != sorted(set(features))
    ):
        raise AssertionError("staged launcher has invalid runtime requirements")
    return version, contract, features


def _repository_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__version__"
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and _PRODUCT_VERSION_PATTERN.fullmatch(value):
                return value
    raise AssertionError("repository package has no valid product version")


def _png_contract(path: Path) -> tuple[int, int, int, int]:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise AssertionError(f"plugin asset is not a regular file: {path.name}")
        if before.st_size > _MAX_PNG_BYTES:
            raise AssertionError(f"plugin asset exceeds the PNG size bound: {path.name}")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                before.st_dev,
                before.st_ino,
            ):
                raise AssertionError(f"plugin asset changed before its bounded read: {path.name}")
            content = stream.read(_MAX_PNG_BYTES + 1)
    except OSError as exc:
        raise AssertionError(f"plugin asset is not safely readable: {path.name}") from exc
    if len(content) > _MAX_PNG_BYTES:
        raise AssertionError(f"plugin asset exceeds the PNG size bound: {path.name}")
    if len(content) != opened.st_size or content[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"plugin asset is not a canonical PNG: {path.name}")
    offset = 8
    chunks = 0
    ihdr: bytes | None = None
    saw_idat = False
    saw_iend = False
    while offset < len(content):
        chunks += 1
        if chunks > _MAX_PNG_CHUNKS or len(content) - offset < 12:
            raise AssertionError(f"plugin asset has malformed PNG chunks: {path.name}")
        length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_type = content[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if length > _MAX_PNG_BYTES or crc_end > len(content):
            raise AssertionError(f"plugin asset has an out-of-bounds PNG chunk: {path.name}")
        chunk_data = content[data_start:data_end]
        expected_crc = int.from_bytes(content[data_end:crc_end], "big")
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise AssertionError(f"plugin asset has an invalid PNG CRC: {path.name}")
        if chunks == 1:
            if chunk_type != b"IHDR" or length != 13:
                raise AssertionError(f"plugin asset lacks a valid first IHDR chunk: {path.name}")
            ihdr = chunk_data
        elif chunk_type == b"IHDR":
            raise AssertionError(f"plugin asset has multiple IHDR chunks: {path.name}")
        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if length != 0 or saw_iend or crc_end != len(content):
                raise AssertionError(f"plugin asset has an invalid IEND chunk: {path.name}")
            saw_iend = True
        offset = crc_end
    if ihdr is None or not saw_idat or not saw_iend:
        raise AssertionError(f"plugin asset lacks required PNG chunks: {path.name}")
    return (
        int.from_bytes(ihdr[0:4], "big"),
        int.from_bytes(ihdr[4:8], "big"),
        ihdr[8],
        ihdr[9],
    )


def _run(wrapper: Path, argv: list[str], *, environment: dict[str, str]) -> str:
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(wrapper), *argv],
            check=False,
            capture_output=True,
            text=True,
            cwd=wrapper.parents[4],
            env=environment,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"staged plugin command {argv!r} exceeded {_COMMAND_TIMEOUT_SECONDS} seconds"
        ) from exc
    if result.returncode != 0:
        raise AssertionError(
            f"staged plugin command {argv!r} returned {result.returncode}: {result.stderr}"
        )
    return result.stdout


def main_smoke() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    canonical_plugin = repository_root / "plugins" / "atready"
    manifest = json.loads(
        (canonical_plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    if manifest["name"] != "atready":
        raise AssertionError("plugin manifest identity does not match the release contract")
    plugin_version = manifest["version"]
    if {path.name for path in canonical_plugin.iterdir()} != {
        ".codex-plugin",
        "assets",
        "skills",
    }:
        raise AssertionError("plugin artifact contains components outside the skills-only contract")
    assets = canonical_plugin / "assets"
    if {path.name for path in assets.iterdir()} != set(_EXPECTED_PNG_ASSETS):
        raise AssertionError("plugin assets do not match the exact release allowlist")
    if "screenshots" in manifest["interface"]:
        raise AssertionError("skills-only plugin manifest must not declare screenshots")
    declared_assets = {
        manifest["interface"][field].removeprefix("./") for field in ("composerIcon", "logo")
    }
    if declared_assets != {"assets/icon.png"}:
        raise AssertionError("plugin manifest does not declare the expected install-surface assets")
    for name, dimensions in _EXPECTED_PNG_ASSETS.items():
        if _png_contract(assets / name) != (*dimensions, 8, 6):
            raise AssertionError(f"plugin asset has unexpected PNG properties: {name}")

    expected_primaries = {
        "project-godot.yaml": ["codex", "codex", "coderabbit"],
        "project-web.yaml": ["codex", "openrouter", "upstash", "vercel"],
        "project-art.yaml": ["native-imagegen", "scenario", "aseprite"],
    }
    fixtures = repository_root / "evals" / "fixtures"

    with tempfile.TemporaryDirectory(prefix="atready-plugin-smoke-") as directory:
        staging_root = Path(directory).resolve()
        staged_plugin = staging_root / "atready"
        shutil.copytree(canonical_plugin, staged_plugin)
        wrapper = staged_plugin / "skills" / "project-atready" / "scripts" / "atready.py"
        installed_cli = shutil.which("atready")
        if installed_cli is None:
            raise AssertionError("isolated plugin smoke did not provide the atready command")
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["ATREADY_HOME"] = str(staging_root / "private-state")
        environment["UV_TOOL_BIN_DIR"] = str(Path(installed_cli).parent)

        launcher_version, launcher_contract, launcher_features = _launcher_requirements(wrapper)
        repository_version = _repository_version(
            repository_root / "src" / "atready" / "__init__.py"
        )
        private_state = Path(environment["ATREADY_HOME"])
        if private_state.exists():
            raise AssertionError("isolated plugin smoke began with unexpected private state")
        contract = json.loads(
            _run(wrapper, ["runtime", "contract", "--json"], environment=environment)
        )
        if private_state.exists():
            raise AssertionError("runtime contract lookup wrote AtReady private state")
        required_features = set(launcher_features)
        if (
            contract.get("product") != "project-atready"
            or contract.get("runtime_version") != repository_version
            or contract.get("contract_version") != launcher_contract
            or not required_features.issubset(contract.get("features", []))
            or contract.get("inventory_read") is not False
            or contract.get("network_accessed") is not False
            or contract.get("writes_performed") is not False
        ):
            raise AssertionError("staged plugin did not negotiate the required runtime contract")
        version = _run(wrapper, ["--version"], environment=environment).strip()
        if version != f"atready {contract['runtime_version']}":
            raise AssertionError(f"staged plugin resolved the wrong runtime version: {version!r}")
        if launcher_version != plugin_version:
            raise AssertionError("staged launcher does not match the plugin manifest version")

        initialized = json.loads(_run(wrapper, ["init", "--json"], environment=environment))
        if (
            initialized["resources"] != 0
            or initialized["revision_protection"] != "nonce-v1-present"
        ):
            raise AssertionError("staged plugin did not produce a clean empty first-user inventory")

        for project_name, expected in expected_primaries.items():
            rendered = _run(
                wrapper,
                [
                    "route",
                    "--project",
                    str(fixtures / project_name),
                    "--inventory",
                    str(fixtures / "inventory.yaml"),
                    "--allow-demo",
                    "--format",
                    "json",
                ],
                environment=environment,
            )
            plan = json.loads(rendered)
            actual = [assignment["primary"]["resource_id"] for assignment in plan["assignments"]]
            if actual != expected:
                raise AssertionError(
                    f"staged plugin route {project_name!r} selected {actual!r}, "
                    f"expected {expected!r}"
                )


if __name__ == "__main__":
    main_smoke()
