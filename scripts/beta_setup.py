"""Install, update, or inspect one exact private AtReady beta candidate.

This is a reviewed bootstrap helper, not a remote installer. The owner sends the
copy committed at the target source SHA; the helper proves that its bytes match
the checked-out source before changing uv or Codex configuration.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_MARKETPLACE = "atready"
_PLUGIN = "atready@atready"
_PROJECT = "project-atready"
_STATE_NAME = ".atready-beta-state.json"
_STAGED_NAME = ".atready-beta-candidate.json"
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_PATTERN = re.compile(r"^[0-9]+$")
_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[A-Za-z0-9.+-]*)?$")
_PRODUCT_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_PYPI = "https://pypi.org/simple"
_FEATURE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_PLUGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$")
_MAX_DOCTOR_CHARACTERS = 32_768
_MAX_PRODUCT_VERSION_CHARACTERS = 64
_MAX_REQUIRED_FEATURE_IDS = 100
_MAX_FEATURE_ID_CHARACTERS = 100
_DOCTOR_KEYS = {
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
}


class BetaSetupError(RuntimeError):
    """The exact private-beta installation contract was not satisfied."""


def _run(argv: list[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BetaSetupError(f"could not run {argv[0]!r}: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic output"
        raise BetaSetupError(f"{argv[0]!r} exited with {completed.returncode}: {detail}")
    return completed.stdout


def _require_commands() -> dict[str, str]:
    commands: dict[str, str] = {}
    for name in ("gh", "git", "uv", "codex"):
        resolved = shutil.which(name)
        if resolved is None:
            raise BetaSetupError(f"required command is not available on PATH: {name}")
        commands[name] = resolved
    return commands


def _validate_identity(repository: str, source_sha: str, run_id: str) -> None:
    if _REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise BetaSetupError("repository must use the OWNER/REPOSITORY form")
    if _SHA_PATTERN.fullmatch(source_sha) is None:
        raise BetaSetupError("source SHA must be 40 lowercase hexadecimal characters")
    if _RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise BetaSetupError("run ID must contain decimal digits only")


def _resolve_root(raw: Path, *, must_exist: bool) -> Path:
    if not raw.is_absolute():
        raise BetaSetupError("beta root must be an explicit absolute path")
    if raw.is_symlink():
        raise BetaSetupError("beta root cannot be a symbolic link")
    root = raw.resolve(strict=must_exist)
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise BetaSetupError("beta root cannot be a filesystem root or the user home directory")
    if must_exist and not root.is_dir():
        raise BetaSetupError("beta root is not a directory")
    return root


def _create_root(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise BetaSetupError("install beta root already exists and is not empty")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:
        # Windows ACLs do not implement POSIX modes. The caller still chose the exact root.
        pass


def _read_json_object(text: str, *, subject: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise BetaSetupError(f"{subject} contains a duplicate JSON key")
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=unique_object)
    except json.JSONDecodeError as exc:
        raise BetaSetupError(f"{subject} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise BetaSetupError(f"{subject} did not return one JSON object")
    return value


def _verify_workflow(
    commands: dict[str, str], *, repository: str, source_sha: str, run_id: str
) -> None:
    raw = _run(
        [
            commands["gh"],
            "run",
            "view",
            run_id,
            "--repo",
            repository,
            "--json",
            "workflowName,event,conclusion,headSha",
        ]
    )
    actual = _read_json_object(raw, subject="GitHub workflow lookup")
    expected = {
        "workflowName": "Release candidate",
        "event": "workflow_dispatch",
        "conclusion": "success",
        "headSha": source_sha,
    }
    if actual != expected:
        raise BetaSetupError(
            "workflow run is not the successful owner-dispatched candidate for the exact source SHA"
        )


def _stage_candidate(
    commands: dict[str, str],
    *,
    root: Path,
    repository: str,
    source_sha: str,
    run_id: str,
) -> tuple[Path, Path, str, str]:
    releases = root / "releases"
    releases_created = not releases.exists()
    releases.mkdir(exist_ok=True)
    final = releases / source_sha
    if final.exists():
        if final.is_symlink() or not final.is_dir():
            raise BetaSetupError("retained candidate path is not a regular directory")
        marker_path = final / _STAGED_NAME
        if not marker_path.is_file() or marker_path.is_symlink():
            raise BetaSetupError("retained candidate is missing its exact identity marker")
        marker = _read_json_object(
            marker_path.read_text(encoding="utf-8"), subject="retained candidate marker"
        )
        if marker != {
            "repository": repository,
            "run_id": run_id,
            "source_sha": source_sha,
        }:
            raise BetaSetupError("retained candidate identity does not match this exact retry")
        source, candidate, runtime_version, plugin_version = _verify_candidate_files(
            commands,
            release=final,
            repository=repository,
            source_sha=source_sha,
        )
        return source, candidate, runtime_version, plugin_version
    temporary = Path(tempfile.mkdtemp(prefix=f".{source_sha}.", dir=releases))
    source = temporary / "source"
    candidate = temporary / "candidate"
    try:
        candidate.mkdir()
        _run([commands["gh"], "repo", "clone", repository, str(source)])
        _run([commands["git"], "-C", str(source), "checkout", "--detach", source_sha])
        if _run([commands["git"], "-C", str(source), "rev-parse", "HEAD"]).strip() != source_sha:
            raise BetaSetupError("detached checkout does not match the requested source SHA")

        _run(
            [
                commands["gh"],
                "run",
                "download",
                run_id,
                "--repo",
                repository,
                "--name",
                f"release-candidate-{source_sha}",
                "--dir",
                str(candidate),
            ]
        )
        source, candidate, runtime_version, plugin_version = _verify_candidate_files(
            commands,
            release=temporary,
            repository=repository,
            source_sha=source_sha,
        )
        _write_json_file(
            temporary / _STAGED_NAME,
            {"repository": repository, "run_id": run_id, "source_sha": source_sha},
        )
        os.replace(temporary, final)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        if releases_created:
            try:
                releases.rmdir()
            except OSError:
                pass
        raise
    return final / "source", final / "candidate", runtime_version, plugin_version


def _verify_candidate_files(
    commands: dict[str, str],
    *,
    release: Path,
    repository: str,
    source_sha: str,
    helper_must_match: bool = True,
) -> tuple[Path, Path, str, str]:
    source = release / "source"
    candidate = release / "candidate"
    if (
        source.is_symlink()
        or candidate.is_symlink()
        or not source.is_dir()
        or not candidate.is_dir()
    ):
        raise BetaSetupError("retained candidate source or artifact directory is unavailable")
    if _run([commands["git"], "-C", str(source), "rev-parse", "HEAD"]).strip() != source_sha:
        raise BetaSetupError("candidate checkout no longer matches the exact source SHA")
    if _run(
        [
            commands["git"],
            "-C",
            str(source),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ]
    ):
        raise BetaSetupError("candidate checkout contains local changes")
    target_helper = source / "scripts" / "beta_setup.py"
    if (
        not target_helper.is_file()
        or target_helper.is_symlink()
        or (
            helper_must_match
            and target_helper.read_bytes() != Path(__file__).resolve().read_bytes()
        )
    ):
        raise BetaSetupError(
            "the reviewed beta helper does not byte-match scripts/beta_setup.py at the target SHA"
        )
    verifier = source / "scripts" / "release_bundle.py"
    _run(
        [
            sys.executable,
            str(verifier),
            "verify",
            "--dist",
            str(candidate),
            "--repository",
            repository,
            "--source-commit",
            source_sha,
            "--workflow-commit",
            source_sha,
        ]
    )
    receipt = _read_json_object(
        (candidate / "release-receipt.json").read_text(encoding="utf-8"),
        subject="release receipt",
    )
    runtime_version = receipt.get("runtime_version")
    if not isinstance(runtime_version, str) or _VERSION_PATTERN.fullmatch(runtime_version) is None:
        raise BetaSetupError("release receipt has an invalid runtime version")
    wheel = candidate / f"project_atready-{runtime_version}-py3-none-any.whl"
    if not wheel.is_file() or wheel.is_symlink():
        raise BetaSetupError("verified candidate omitted its exact wheel")

    manifest = _read_json_object(
        (source / "plugins" / "atready" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        ),
        subject="plugin manifest",
    )
    plugin_version = receipt.get("plugin_version")
    manifest_version = manifest.get("version")
    if manifest.get("name") != "atready":
        raise BetaSetupError("plugin manifest does not match the candidate identity")
    if not isinstance(plugin_version, str) or _VERSION_PATTERN.fullmatch(plugin_version) is None:
        raise BetaSetupError("release receipt has an invalid plugin version")
    if manifest_version != plugin_version:
        raise BetaSetupError("plugin manifest version does not match the release receipt")
    return source, candidate, runtime_version, plugin_version


def _uv_bin(commands: dict[str, str]) -> Path:
    raw = _run([commands["uv"], "--offline", "--no-config", "tool", "dir", "--bin"]).strip()
    if not raw:
        raise BetaSetupError("uv returned an empty tool-bin directory")
    return Path(raw).resolve()


def _executable(uv_bin: Path) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return uv_bin / f"atready{suffix}"


def _marketplace_roots(commands: dict[str, str]) -> dict[str, Path]:
    output = _run([commands["codex"], "plugin", "marketplace", "list"])
    lines = output.splitlines()
    if not lines or lines[0].split() != ["MARKETPLACE", "ROOT"]:
        raise BetaSetupError("Codex marketplace listing has an unexpected table header")
    root_column = lines[0].index("ROOT")
    roots: dict[str, Path] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        name = line[:root_column].strip()
        raw_root = line[root_column:].strip()
        root = Path(raw_root)
        if (
            not name
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
                for character in name
            )
            or not raw_root
            or "\0" in raw_root
            or not root.is_absolute()
            or name in roots
        ):
            raise BetaSetupError("Codex marketplace listing contains a malformed row")
        roots[name] = root.resolve()
    return roots


def _plugin_row(commands: dict[str, str]) -> tuple[str, str, Path] | None:
    output = _run([commands["codex"], "plugin", "list", "--marketplace", _MARKETPLACE])
    lines = output.splitlines()
    headers = [
        index
        for index, line in enumerate(lines)
        if line.split() == ["PLUGIN", "STATUS", "VERSION", "PATH"]
    ]
    if len(headers) != 1:
        raise BetaSetupError("Codex plugin listing has an unexpected table header")
    header_index = headers[0]
    header = lines[header_index]
    status_column = header.index("STATUS")
    version_column = header.index("VERSION")
    path_column = header.index("PATH")
    selected: tuple[str, str, Path] | None = None
    seen: set[str] = set()
    for line in lines[header_index + 1 :]:
        if not line.strip():
            continue
        plugin_id = line[:status_column].strip()
        status = line[status_column:version_column].strip()
        version = line[version_column:path_column].strip()
        raw_path = line[path_column:].strip()
        path = Path(raw_path)
        if (
            _PLUGIN_ID_PATTERN.fullmatch(plugin_id) is None
            or plugin_id in seen
            or status not in {"installed, enabled", "installed, disabled", "not installed"}
            or (
                status in {"installed, enabled", "installed, disabled"}
                and _VERSION_PATTERN.fullmatch(version) is None
            )
            or (status == "not installed" and version != "")
            or not raw_path
            or "\0" in raw_path
            or not path.is_absolute()
        ):
            raise BetaSetupError("Codex plugin listing contains a malformed row")
        seen.add(plugin_id)
        if plugin_id == _PLUGIN:
            selected = (status, version, path.resolve())
    return selected


def _install_wheel(commands: dict[str, str], wheel: Path) -> None:
    _run(
        [
            commands["uv"],
            "tool",
            "install",
            "--no-config",
            "--no-python-downloads",
            "--default-index",
            _PYPI,
            "--force",
            "--reinstall",
            "--no-cache",
            str(wheel),
        ]
    )


def _launcher_requirements(source: Path) -> tuple[str, int, tuple[str, ...]]:
    launcher = (
        source / "plugins" / "atready" / "skills" / "project-atready" / "scripts" / "atready.py"
    )
    try:
        tree = ast.parse(launcher.read_text(encoding="utf-8"), filename=str(launcher))
        values: dict[str, object] = {}
        wanted = {
            "PLUGIN_VERSION",
            "REQUIRED_RUNTIME_CONTRACT_VERSION",
            "REQUIRED_RUNTIME_FEATURE_IDS",
        }
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in wanted
            ):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    except (OSError, SyntaxError, UnicodeError, ValueError) as exc:
        raise BetaSetupError("could not read the plugin runtime requirements") from exc
    plugin_version = values.get("PLUGIN_VERSION")
    contract = values.get("REQUIRED_RUNTIME_CONTRACT_VERSION")
    features = values.get("REQUIRED_RUNTIME_FEATURE_IDS")
    if (
        not isinstance(plugin_version, str)
        or len(plugin_version) > _MAX_PRODUCT_VERSION_CHARACTERS
        or _PRODUCT_VERSION_PATTERN.fullmatch(plugin_version) is None
    ):
        raise BetaSetupError("plugin launcher has an invalid product version")
    if not isinstance(contract, int) or isinstance(contract, bool) or contract <= 0:
        raise BetaSetupError("plugin launcher has an invalid runtime contract version")
    if (
        not isinstance(features, tuple)
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
        raise BetaSetupError("plugin launcher has invalid required runtime features")
    return plugin_version, contract, features


def _verify_runtime_contract(
    executable: Path, *, source: Path, plugin_version: str, runtime_version: str
) -> None:
    launcher_version, contract, features = _launcher_requirements(source)
    if launcher_version != plugin_version:
        raise BetaSetupError("plugin launcher and manifest product versions differ")
    arguments = [
        str(executable),
        "doctor",
        "--plugin-version",
        plugin_version,
        "--plugin-contract",
        str(contract),
    ]
    for feature in features:
        arguments.extend(("--require-feature", feature))
    arguments.append("--json")
    raw = _run(arguments)
    if not raw or len(raw) > _MAX_DOCTOR_CHARACTERS:
        raise BetaSetupError("AtReady doctor returned an invalid bounded report")
    result = _read_json_object(raw, subject="AtReady doctor")
    if set(result) != _DOCTOR_KEYS:
        raise BetaSetupError("AtReady doctor returned an unexpected report shape")
    runtime_features = result.get("runtime_features")
    if (
        result.get("compatible") is not True
        or result.get("status") != "ready"
        or result.get("missing_features") != []
        or result.get("plugin_version") != plugin_version
        or type(result.get("plugin_contract_version")) is not int
        or result.get("plugin_contract_version") != contract
        or type(result.get("runtime_contract_version")) is not int
        or result.get("runtime_contract_version") != contract
        or result.get("runtime_version") != runtime_version
        or result.get("product") != _PROJECT
        or result.get("inventory_read") is not False
        or result.get("network_accessed") is not False
        or result.get("writes_performed") is not False
        or not isinstance(runtime_features, list)
        or any(
            not isinstance(feature, str)
            or len(feature) > 100
            or _FEATURE_PATTERN.fullmatch(feature) is None
            for feature in runtime_features
        )
        or runtime_features != sorted(set(runtime_features))
        or not set(features).issubset(runtime_features)
    ):
        raise BetaSetupError("AtReady doctor did not confirm the runtime/plugin contract")


def _verify_installed(
    commands: dict[str, str],
    *,
    source: Path,
    runtime_version: str,
    plugin_version: str,
    run_acceptance: bool,
) -> Path:
    executable = _executable(_uv_bin(commands))
    if not executable.is_file():
        raise BetaSetupError("uv's exact AtReady executable is unavailable")
    if _run([str(executable), "--version"]).strip() != f"atready {runtime_version}":
        raise BetaSetupError("installed CLI version does not match the candidate")
    roots = _marketplace_roots(commands)
    if roots.get(_MARKETPLACE) != source.resolve():
        raise BetaSetupError("configured marketplace does not match the exact candidate source")
    row = _plugin_row(commands)
    expected_plugin_path = (source / "plugins" / "atready").resolve()
    if row != ("installed, enabled", plugin_version, expected_plugin_path):
        raise BetaSetupError("installed plugin does not match the exact candidate")
    _verify_runtime_contract(
        executable,
        source=source,
        plugin_version=plugin_version,
        runtime_version=runtime_version,
    )
    if run_acceptance:
        _run(
            [
                sys.executable,
                str(source / "scripts" / "first_user_acceptance.py"),
                "--executable",
                str(executable),
            ]
        )
    return executable


def _write_json_file(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_state(root: Path, value: dict[str, Any]) -> None:
    _write_json_file(root / _STATE_NAME, value)


def _load_state(root: Path) -> dict[str, Any]:
    path = root / _STATE_NAME
    if not path.is_file() or path.is_symlink():
        raise BetaSetupError("beta root does not contain a regular installer state file")
    value = _read_json_object(path.read_text(encoding="utf-8"), subject="installer state")
    required = {
        "candidate",
        "inventory",
        "plugin_version",
        "repository",
        "run_id",
        "runtime_version",
        "source",
        "source_sha",
    }
    if set(value) != required or any(not isinstance(value[key], str) for key in required):
        raise BetaSetupError("installer state has an unexpected shape")
    return value


def _configure_plugin(commands: dict[str, str], source: Path) -> None:
    _run([commands["codex"], "plugin", "marketplace", "add", str(source)])
    _run([commands["codex"], "plugin", "add", _PLUGIN])


def _remove_plugin_configuration(commands: dict[str, str]) -> None:
    _run([commands["codex"], "plugin", "remove", _PLUGIN])
    _run([commands["codex"], "plugin", "marketplace", "remove", _MARKETPLACE])


def _clear_atready_configuration(commands: dict[str, str]) -> None:
    if _MARKETPLACE not in _marketplace_roots(commands):
        return
    row = _plugin_row(commands)
    if row is not None and row[0] in {"installed, enabled", "installed, disabled"}:
        _run([commands["codex"], "plugin", "remove", _PLUGIN])
    _run([commands["codex"], "plugin", "marketplace", "remove", _MARKETPLACE])


def _restore_plugin_configuration(commands: dict[str, str], source: Path) -> None:
    roots = _marketplace_roots(commands)
    configured = roots.get(_MARKETPLACE)
    if configured is None:
        _run([commands["codex"], "plugin", "marketplace", "add", str(source)])
    elif configured != source.resolve():
        raise BetaSetupError("AtReady marketplace changed during recovery; refusing mutation")

    row = _plugin_row(commands)
    expected = source / "plugins" / "atready"
    if row is not None and row[0] in {"installed, enabled", "installed, disabled"}:
        if row[2] != expected.resolve():
            raise BetaSetupError("AtReady plugin changed during recovery; refusing mutation")
        if row[0] == "installed, enabled":
            return
        _run([commands["codex"], "plugin", "remove", _PLUGIN])
    _run([commands["codex"], "plugin", "add", _PLUGIN])


def _verified_state_candidate(
    commands: dict[str, str], state: dict[str, Any]
) -> tuple[Path, Path, str, str]:
    source = Path(state["source"])
    candidate = Path(state["candidate"])
    release = source.parent
    if candidate.parent != release or candidate != release / "candidate":
        raise BetaSetupError("installer state candidate paths are inconsistent")
    marker_path = release / _STAGED_NAME
    if not marker_path.is_file() or marker_path.is_symlink():
        raise BetaSetupError("retained installed candidate is missing its identity marker")
    marker = _read_json_object(
        marker_path.read_text(encoding="utf-8"), subject="installed candidate marker"
    )
    if marker != {
        "repository": state["repository"],
        "run_id": state["run_id"],
        "source_sha": state["source_sha"],
    }:
        raise BetaSetupError("retained installed candidate identity does not match installer state")
    verified = _verify_candidate_files(
        commands,
        release=release,
        repository=state["repository"],
        source_sha=state["source_sha"],
        helper_must_match=False,
    )
    if verified != (
        source,
        candidate,
        state["runtime_version"],
        state["plugin_version"],
    ):
        raise BetaSetupError("retained installed candidate does not match installer state")
    return verified


def _restore_exact_beta(commands: dict[str, str], state: dict[str, Any]) -> None:
    source, candidate, runtime_version, plugin_version = _verified_state_candidate(commands, state)
    wheel = candidate / f"project_atready-{runtime_version}-py3-none-any.whl"
    _install_wheel(commands, wheel)
    _restore_plugin_configuration(commands, source)
    _verify_installed(
        commands,
        source=source,
        runtime_version=runtime_version,
        plugin_version=plugin_version,
        run_acceptance=False,
    )


def _rollback_new_install(commands: dict[str, str]) -> None:
    if _MARKETPLACE in _marketplace_roots(commands):
        row = _plugin_row(commands)
        if row is not None and row[0] in {"installed, enabled", "installed, disabled"}:
            _run([commands["codex"], "plugin", "remove", _PLUGIN])
        _run([commands["codex"], "plugin", "marketplace", "remove", _MARKETPLACE])
    if _executable(_uv_bin(commands)).exists():
        _run([commands["uv"], "tool", "uninstall", _PROJECT])


def _state_payload(
    *,
    repository: str,
    source_sha: str,
    run_id: str,
    runtime_version: str,
    plugin_version: str,
    source: Path,
    candidate: Path,
    inventory: Path,
) -> dict[str, str]:
    return {
        "candidate": str(candidate),
        "inventory": str(inventory),
        "plugin_version": plugin_version,
        "repository": repository,
        "run_id": run_id,
        "runtime_version": runtime_version,
        "source": str(source),
        "source_sha": source_sha,
    }


def install(args: argparse.Namespace) -> None:
    _validate_identity(args.repository, args.source_sha, args.run_id)
    root = _resolve_root(args.beta_root, must_exist=False)
    _create_root(root)
    commands = _require_commands()
    if _executable(_uv_bin(commands)).exists():
        raise BetaSetupError("AtReady is already installed in uv's tool directory")
    if _MARKETPLACE in _marketplace_roots(commands):
        raise BetaSetupError("a AtReady marketplace is already configured")
    if "atready@" in _run([commands["codex"], "plugin", "list"]):
        raise BetaSetupError("a AtReady plugin is already installed or configured")

    _verify_workflow(
        commands,
        repository=args.repository,
        source_sha=args.source_sha,
        run_id=args.run_id,
    )
    source, candidate, runtime_version, plugin_version = _stage_candidate(
        commands,
        root=root,
        repository=args.repository,
        source_sha=args.source_sha,
        run_id=args.run_id,
    )
    wheel = candidate / f"project_atready-{runtime_version}-py3-none-any.whl"
    try:
        _install_wheel(commands, wheel)
        _configure_plugin(commands, source)
        executable = _verify_installed(
            commands,
            source=source,
            runtime_version=runtime_version,
            plugin_version=plugin_version,
            run_acceptance=True,
        )

        test_state = root / "test-state"
        test_state.mkdir(mode=0o700)
        inventory = test_state / "inventory.yaml"
        _run([str(executable), "init", "--path", str(inventory), "--json"])
        _write_state(
            root,
            _state_payload(
                repository=args.repository,
                source_sha=args.source_sha,
                run_id=args.run_id,
                runtime_version=runtime_version,
                plugin_version=plugin_version,
                source=source,
                candidate=candidate,
                inventory=inventory,
            ),
        )
    except (BetaSetupError, OSError, UnicodeError) as install_error:
        try:
            _rollback_new_install(commands)
        except BetaSetupError as rollback_error:
            raise BetaSetupError(
                f"install failed ({install_error}); setup rollback also failed ({rollback_error})"
            ) from rollback_error
        raise BetaSetupError(
            "install failed and newly added tool configuration was removed; the beta root was "
            f"retained at {root}. Retry with a new or emptied --beta-root: {install_error}"
        ) from install_error
    print("AtReady private beta installed and verified.")
    print(f"Plugin version: {plugin_version}")
    print(f"Runtime version: {runtime_version}")
    print(f"Source SHA: {args.source_sha}")
    print(f"Beta root: {root}")
    print(f"Synthetic inventory: {inventory}")
    print("Start a new Codex task before testing the plugin.")


def update(args: argparse.Namespace) -> None:
    _validate_identity(args.repository, args.source_sha, args.run_id)
    root = _resolve_root(args.beta_root, must_exist=True)
    state = _load_state(root)
    commands = _require_commands()
    if state["repository"] != args.repository:
        raise BetaSetupError("update repository does not match the installed beta")
    if state["source_sha"] == args.source_sha and state["run_id"] == args.run_id:
        _verify_installed(
            commands,
            source=Path(state["source"]),
            runtime_version=state["runtime_version"],
            plugin_version=state["plugin_version"],
            run_acceptance=False,
        )
        print("AtReady private beta is already at this exact candidate.")
        return

    _verify_installed(
        commands,
        source=Path(state["source"]),
        runtime_version=state["runtime_version"],
        plugin_version=state["plugin_version"],
        run_acceptance=False,
    )
    _verified_state_candidate(commands, state)
    _verify_workflow(
        commands,
        repository=args.repository,
        source_sha=args.source_sha,
        run_id=args.run_id,
    )
    source, candidate, runtime_version, plugin_version = _stage_candidate(
        commands,
        root=root,
        repository=args.repository,
        source_sha=args.source_sha,
        run_id=args.run_id,
    )
    wheel = candidate / f"project_atready-{runtime_version}-py3-none-any.whl"

    try:
        _install_wheel(commands, wheel)
        _remove_plugin_configuration(commands)
        _configure_plugin(commands, source)
        _verify_installed(
            commands,
            source=source,
            runtime_version=runtime_version,
            plugin_version=plugin_version,
            run_acceptance=True,
        )
        _write_state(
            root,
            _state_payload(
                repository=args.repository,
                source_sha=args.source_sha,
                run_id=args.run_id,
                runtime_version=runtime_version,
                plugin_version=plugin_version,
                source=source,
                candidate=candidate,
                inventory=Path(state["inventory"]),
            ),
        )
    except (BetaSetupError, OSError, UnicodeError) as update_error:
        try:
            _clear_atready_configuration(commands)
            _restore_exact_beta(commands, state)
        except (BetaSetupError, OSError, UnicodeError) as rollback_error:
            raise BetaSetupError(
                f"update failed ({update_error}); rollback also failed ({rollback_error})"
            ) from rollback_error
        raise BetaSetupError(
            f"update failed and the previous beta was restored: {update_error}"
        ) from update_error

    print("AtReady private beta updated and verified.")
    print(f"Plugin version: {plugin_version}")
    print(f"Runtime version: {runtime_version}")
    print(f"Source SHA: {args.source_sha}")
    print(f"Synthetic inventory preserved: {state['inventory']}")
    print("Start a new Codex task before testing the updated plugin.")


def status(args: argparse.Namespace) -> None:
    root = _resolve_root(args.beta_root, must_exist=True)
    state = _load_state(root)
    commands = _require_commands()
    _verify_installed(
        commands,
        source=Path(state["source"]),
        runtime_version=state["runtime_version"],
        plugin_version=state["plugin_version"],
        run_acceptance=False,
    )
    print("AtReady private beta status: passed")
    print(f"Plugin version: {state['plugin_version']}")
    print(f"Runtime version: {state['runtime_version']}")
    print(f"Source SHA: {state['source_sha']}")
    print(f"Beta root: {root}")
    print(f"Synthetic inventory: {state['inventory']}")


def remove(args: argparse.Namespace) -> None:
    root = _resolve_root(args.beta_root, must_exist=True)
    state = _load_state(root)
    commands = _require_commands()
    source = Path(state["source"])
    _verified_state_candidate(commands, state)
    _verify_installed(
        commands,
        source=source,
        runtime_version=state["runtime_version"],
        plugin_version=state["plugin_version"],
        run_acceptance=False,
    )
    try:
        _remove_plugin_configuration(commands)
        _run([commands["uv"], "tool", "uninstall", _PROJECT])
        if _MARKETPLACE in _marketplace_roots(commands):
            raise BetaSetupError("AtReady marketplace remains configured after removal")
        if _executable(_uv_bin(commands)).exists():
            raise BetaSetupError("AtReady runtime remains installed after removal")
    except (BetaSetupError, OSError, UnicodeError) as removal_error:
        try:
            _restore_exact_beta(commands, state)
        except (BetaSetupError, OSError, UnicodeError) as restore_error:
            raise BetaSetupError(
                f"removal failed ({removal_error}); exact beta restore also failed "
                f"({restore_error})"
            ) from restore_error
        raise BetaSetupError(
            f"removal failed and the exact previous beta was restored: {removal_error}"
        ) from removal_error
    print("AtReady private beta plugin and runtime removed.")
    print(f"Beta files and synthetic inventory were retained at: {root}")
    print("Review that exact folder before moving it to Trash.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("install", install), ("update", update)):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--repository", required=True)
        subparser.add_argument("--source-sha", required=True)
        subparser.add_argument("--run-id", required=True)
        subparser.add_argument("--beta-root", required=True, type=Path)
        subparser.set_defaults(handler=handler)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--beta-root", required=True, type=Path)
    status_parser.set_defaults(handler=status)
    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("--beta-root", required=True, type=Path)
    remove_parser.set_defaults(handler=remove)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        args.handler(args)
    except (BetaSetupError, OSError, UnicodeError) as exc:
        print(f"AtReady beta setup stopped: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
