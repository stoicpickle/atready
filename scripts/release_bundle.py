"""Create and verify a bounded AtReady release-candidate bundle."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_PROJECT = _ROOT / "pyproject.toml"
_PACKAGE = _ROOT / "src" / "atready" / "__init__.py"
_MANIFEST = _ROOT / "plugins" / "atready" / ".codex-plugin" / "plugin.json"
_BUILD_CONSTRAINTS = _ROOT / "build-constraints.txt"
_LAUNCHER = _ROOT / "plugins" / "atready" / "skills" / "project-atready" / "scripts" / "atready.py"
_README = _ROOT / "README.md"
_WORKFLOW_PATH = ".github/workflows/release-candidate.yml"
_RECEIPT_NAME = "release-receipt.json"
_CHECKSUMS_NAME = "SHA256SUMS"
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MAX_ARTIFACT_BYTES = 100 * 1024 * 1024


class ReleaseBundleError(ValueError):
    """A release bundle violated the explicit artifact contract."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseBundleError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ReleaseBundleError(f"{path.name} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseBundleError(f"{path.name} must contain one JSON object")
    return value


def _assigned_string(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise ReleaseBundleError(f"{path.name} does not assign a string to {name}")


def _release_contract() -> tuple[str, str, str, str]:
    try:
        project = tomllib.loads(_PROJECT.read_text(encoding="utf-8"))["project"]
    except (KeyError, tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise ReleaseBundleError("pyproject.toml does not contain a valid project table") from exc

    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name:
        raise ReleaseBundleError("project name must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise ReleaseBundleError("project version must be a non-empty string")

    manifest = _load_json(_MANIFEST)
    manifest_version = manifest.get("version")
    if not isinstance(manifest_version, str) or not manifest_version:
        raise ReleaseBundleError("plugin manifest version must be a non-empty string")
    package_version = _assigned_string(_PACKAGE, "__version__")
    launcher_plugin_version = _assigned_string(_LAUNCHER, "PLUGIN_VERSION")
    reviewed_runtime_version = _assigned_string(_LAUNCHER, "REVIEWED_RUNTIME_VERSION")
    public_runtime_source = _assigned_string(_LAUNCHER, "PUBLIC_RUNTIME_SOURCE")
    if version != package_version:
        raise ReleaseBundleError("runtime package and module versions do not match")
    if manifest_version != launcher_plugin_version:
        raise ReleaseBundleError("plugin manifest and launcher versions do not match")
    if version != reviewed_runtime_version:
        raise ReleaseBundleError("runtime package and launcher compatibility versions do not match")
    if public_runtime_source != "git+https://github.com/stoicpickle/atready.git@main":
        raise ReleaseBundleError("launcher public runtime source must name the public main channel")
    public_install_command = (
        "uv tool install --force --no-config --no-python-downloads \\\n"
        "  --default-index https://pypi.org/simple \\\n"
        f"  '{public_runtime_source}'"
    )
    if public_install_command not in _README.read_text(encoding="utf-8"):
        raise ReleaseBundleError("launcher recovery command does not match README onboarding")
    if manifest.get("name") != "atready":
        raise ReleaseBundleError("plugin manifest identity does not match atready")
    normalized_name = re.sub(r"[-_.]+", "_", name)
    return name, normalized_name, version, manifest_version


def _validate_identity(repository: str, source_commit: str, workflow_commit: str) -> None:
    if _REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise ReleaseBundleError("repository must use the OWNER/REPOSITORY form")
    if _COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise ReleaseBundleError("source commit must be a lowercase 40-character Git SHA")
    if _COMMIT_PATTERN.fullmatch(workflow_commit) is None:
        raise ReleaseBundleError("workflow commit must be a lowercase 40-character Git SHA")


def _resolve_dist(path: Path) -> Path:
    if path.is_symlink():
        raise ReleaseBundleError("distribution directory must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReleaseBundleError("distribution directory is unavailable") from exc
    if not resolved.is_dir():
        raise ReleaseBundleError("distribution path must be a directory")
    return resolved


def _expected_artifacts(dist: Path) -> tuple[Path, Path]:
    _, normalized_name, version, _ = _release_contract()
    wheel = dist / f"{normalized_name}-{version}-py3-none-any.whl"
    source = dist / f"{normalized_name}-{version}.tar.gz"
    expected = {wheel.name, source.name}
    actual = {
        path.name
        for path in dist.iterdir()
        if path.name.endswith(".whl") or path.name.endswith(".tar.gz")
    }
    if actual != expected:
        raise ReleaseBundleError(
            "distribution must contain exactly the version-matched wheel and sdist"
        )
    for artifact in (wheel, source):
        if artifact.is_symlink() or not artifact.is_file():
            raise ReleaseBundleError(f"release artifact is not a regular file: {artifact.name}")
        size = artifact.stat().st_size
        if size <= 0 or size > _MAX_ARTIFACT_BYTES:
            raise ReleaseBundleError(f"release artifact has an invalid size: {artifact.name}")
    return wheel, source


def _refuse_unexpected_entries(dist: Path, artifacts: tuple[Path, Path]) -> None:
    allowed = {path.name for path in artifacts} | {_RECEIPT_NAME, _CHECKSUMS_NAME}
    unexpected = sorted(path.name for path in dist.iterdir() if path.name not in allowed)
    if unexpected:
        raise ReleaseBundleError("distribution directory contains unexpected entries")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_entries(artifacts: tuple[Path, Path]) -> list[dict[str, Any]]:
    return [
        {"bytes": path.stat().st_size, "filename": path.name, "sha256": _sha256(path)}
        for path in sorted(artifacts, key=lambda candidate: candidate.name)
    ]


def _receipt(
    *,
    repository: str,
    source_commit: str,
    workflow_commit: str,
    artifacts: tuple[Path, Path],
) -> dict[str, Any]:
    project_name, _, runtime_version, plugin_version = _release_contract()
    return {
        "artifacts": _artifact_entries(artifacts),
        "build_constraints": {
            "filename": _BUILD_CONSTRAINTS.name,
            "sha256": _sha256(_BUILD_CONSTRAINTS),
        },
        "builder_workflow": f"{repository}/{_WORKFLOW_PATH}",
        "metadata_kind": "unsigned-release-candidate",
        "repository": repository,
        "plugin_version": plugin_version,
        "runtime_version": runtime_version,
        "schema_version": 2,
        "source_commit": source_commit,
        "project": project_name,
        "unsigned": True,
        "workflow_commit": workflow_commit,
    }


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _checksums(artifacts: tuple[Path, Path], receipt_path: Path) -> bytes:
    subjects = sorted((*artifacts, receipt_path), key=lambda candidate: candidate.name)
    return "".join(f"{_sha256(path)}  {path.name}\n" for path in subjects).encode("ascii")


def _replace_metadata(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def create_bundle(*, dist: Path, repository: str, source_commit: str, workflow_commit: str) -> None:
    _validate_identity(repository, source_commit, workflow_commit)
    resolved = _resolve_dist(dist)
    artifacts = _expected_artifacts(resolved)
    _refuse_unexpected_entries(resolved, artifacts)

    receipt_path = resolved / _RECEIPT_NAME
    checksums_path = resolved / _CHECKSUMS_NAME
    for target in (receipt_path, checksums_path):
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ReleaseBundleError(f"release metadata target is unsafe: {target.name}")

    receipt_payload = _canonical_json(
        _receipt(
            repository=repository,
            source_commit=source_commit,
            workflow_commit=workflow_commit,
            artifacts=artifacts,
        )
    )
    _replace_metadata(receipt_path, receipt_payload)
    _replace_metadata(checksums_path, _checksums(artifacts, receipt_path))


def verify_bundle(*, dist: Path, repository: str, source_commit: str, workflow_commit: str) -> None:
    _validate_identity(repository, source_commit, workflow_commit)
    resolved = _resolve_dist(dist)
    artifacts = _expected_artifacts(resolved)
    _refuse_unexpected_entries(resolved, artifacts)
    receipt_path = resolved / _RECEIPT_NAME
    checksums_path = resolved / _CHECKSUMS_NAME
    for metadata in (receipt_path, checksums_path):
        if metadata.is_symlink() or not metadata.is_file():
            raise ReleaseBundleError(f"release metadata is unavailable: {metadata.name}")

    expected_receipt = _receipt(
        repository=repository,
        source_commit=source_commit,
        workflow_commit=workflow_commit,
        artifacts=artifacts,
    )
    actual_receipt = _load_json(receipt_path)
    if actual_receipt != expected_receipt:
        raise ReleaseBundleError("release receipt does not match the artifact and build identity")
    if receipt_path.read_bytes() != _canonical_json(expected_receipt):
        raise ReleaseBundleError("release receipt is not in canonical form")
    if checksums_path.read_bytes() != _checksums(artifacts, receipt_path):
        raise ReleaseBundleError("SHA256SUMS does not match the release bundle")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--dist", type=Path, required=True)
        subparser.add_argument("--repository", required=True)
        subparser.add_argument("--source-commit", required=True)
        subparser.add_argument("--workflow-commit", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    operation = create_bundle if args.command == "create" else verify_bundle
    try:
        operation(
            dist=args.dist,
            repository=args.repository,
            source_commit=args.source_commit,
            workflow_commit=args.workflow_commit,
        )
    except (OSError, ReleaseBundleError, SyntaxError, UnicodeError) as exc:
        print(f"release bundle error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
