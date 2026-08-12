from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "release_bundle.py"
BUILD_CONSTRAINTS = ROOT / "build-constraints.txt"
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
VERSION = PROJECT["version"]
PLUGIN = json.loads(
    (ROOT / "plugins" / "atready" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
)
NORMALIZED_NAME = PROJECT["name"].replace("-", "_")
REPOSITORY = "stoicpickle/atready"
SOURCE_COMMIT = "a" * 40
WORKFLOW_COMMIT = "b" * 40
SPEC = importlib.util.spec_from_file_location("atready_release_bundle", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_bundle)


def _seed_dist(tmp_path: Path) -> tuple[Path, Path, Path]:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / f"{NORMALIZED_NAME}-{VERSION}-py3-none-any.whl"
    source = dist / f"{NORMALIZED_NAME}-{VERSION}.tar.gz"
    wheel.write_bytes(b"synthetic wheel bytes\n")
    source.write_bytes(b"synthetic source bytes\n")
    return dist, wheel, source


def _run(command: str, dist: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT),
            command,
            "--dist",
            str(dist),
            "--repository",
            REPOSITORY,
            "--source-commit",
            SOURCE_COMMIT,
            "--workflow-commit",
            WORKFLOW_COMMIT,
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )


def test_release_bundle_round_trip_is_canonical_and_identity_bound(tmp_path: Path) -> None:
    dist, wheel, source = _seed_dist(tmp_path)

    created = _run("create", dist)
    assert created.returncode == 0, created.stderr
    verified = _run("verify", dist)
    assert verified.returncode == 0, verified.stderr

    receipt_path = dist / "release-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt == {
        "artifacts": [
            {
                "bytes": wheel.stat().st_size,
                "filename": wheel.name,
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            },
            {
                "bytes": source.stat().st_size,
                "filename": source.name,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
        ],
        "build_constraints": {
            "filename": BUILD_CONSTRAINTS.name,
            "sha256": hashlib.sha256(BUILD_CONSTRAINTS.read_bytes()).hexdigest(),
        },
        "builder_workflow": f"{REPOSITORY}/.github/workflows/release-candidate.yml",
        "metadata_kind": "unsigned-release-candidate",
        "plugin_version": PLUGIN["version"],
        "project": PROJECT["name"],
        "repository": REPOSITORY,
        "runtime_version": VERSION,
        "schema_version": 2,
        "source_commit": SOURCE_COMMIT,
        "unsigned": True,
        "workflow_commit": WORKFLOW_COMMIT,
    }
    assert (
        receipt_path.read_bytes() == (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    )

    checksum_lines = (dist / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    assert checksum_lines == [
        f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}",
        f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {source.name}",
        f"{hashlib.sha256(receipt_path.read_bytes()).hexdigest()}  release-receipt.json",
    ]


def test_receipt_keeps_distinct_runtime_and_plugin_versions_in_their_own_fields(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = tmp_path / "first.whl"
    second = tmp_path / "second.tar.gz"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.setattr(
        release_bundle,
        "_release_contract",
        lambda: ("project-atready", "project_atready", "1.2.3", "4.5.6"),
    )

    receipt = release_bundle._receipt(
        repository=REPOSITORY,
        source_commit=SOURCE_COMMIT,
        workflow_commit=WORKFLOW_COMMIT,
        artifacts=(first, second),
    )

    assert receipt["runtime_version"] == "1.2.3"
    assert receipt["plugin_version"] == "4.5.6"


def test_release_contract_binds_runtime_and_public_recovery_channel() -> None:
    assert release_bundle._release_contract() == (
        PROJECT["name"],
        NORMALIZED_NAME,
        VERSION,
        PLUGIN["version"],
    )


def test_release_contract_refuses_runtime_compatibility_version_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher = tmp_path / "atready.py"
    launcher.write_text(
        f"PLUGIN_VERSION = {PLUGIN['version']!r}\n"
        "REVIEWED_RUNTIME_VERSION = '0.0.0'\n"
        "PUBLIC_RUNTIME_SOURCE = "
        "'git+https://github.com/stoicpickle/atready.git@main'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_bundle, "_LAUNCHER", launcher)

    with pytest.raises(
        release_bundle.ReleaseBundleError,
        match="runtime package and launcher compatibility versions do not match",
    ):
        release_bundle._release_contract()


def test_release_contract_refuses_placeholder_recovery_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher = tmp_path / "atready.py"
    launcher.write_text(
        f"PLUGIN_VERSION = {PLUGIN['version']!r}\n"
        f"REVIEWED_RUNTIME_VERSION = {VERSION!r}\n"
        "PUBLIC_RUNTIME_SOURCE = 'git+https://github.com/stoicpickle/atready.git@RELEASE_VERSION'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_bundle, "_LAUNCHER", launcher)

    with pytest.raises(
        release_bundle.ReleaseBundleError,
        match="public runtime source must name the public main channel",
    ):
        release_bundle._release_contract()


def test_release_contract_refuses_readme_recovery_command_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Synthetic README\n", encoding="utf-8")
    monkeypatch.setattr(release_bundle, "_README", readme)

    with pytest.raises(
        release_bundle.ReleaseBundleError,
        match="recovery command does not match README onboarding",
    ):
        release_bundle._release_contract()


def test_release_bundle_verification_refuses_artifact_tampering(tmp_path: Path) -> None:
    dist, wheel, _ = _seed_dist(tmp_path)
    assert _run("create", dist).returncode == 0

    wheel.write_bytes(wheel.read_bytes() + b"tampered")
    result = _run("verify", dist)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "release receipt does not match" in result.stderr


def test_release_bundle_verification_refuses_identity_drift(tmp_path: Path) -> None:
    dist, _, _ = _seed_dist(tmp_path)
    assert _run("create", dist).returncode == 0

    result = _run("verify", dist, "--source-commit", "c" * 40)

    assert result.returncode == 2
    assert "release receipt does not match" in result.stderr


def test_release_bundle_refuses_extra_artifacts_or_entries(tmp_path: Path) -> None:
    dist, _, _ = _seed_dist(tmp_path)
    (dist / f"{NORMALIZED_NAME}-{VERSION}-other.whl").write_bytes(b"unexpected wheel")
    extra_artifact = _run("create", dist)
    assert extra_artifact.returncode == 2
    assert "exactly the version-matched wheel and sdist" in extra_artifact.stderr

    (dist / f"{NORMALIZED_NAME}-{VERSION}-other.whl").unlink()
    (dist / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    extra_entry = _run("create", dist)
    assert extra_entry.returncode == 2
    assert "unexpected entries" in extra_entry.stderr


def test_release_bundle_refuses_duplicate_receipt_keys(tmp_path: Path) -> None:
    dist, _, _ = _seed_dist(tmp_path)
    assert _run("create", dist).returncode == 0
    receipt = dist / "release-receipt.json"
    receipt.write_text(
        receipt.read_text(encoding="utf-8").replace(
            '  "schema_version": 2,',
            '  "schema_version": 2,\n  "schema_version": 2,',
        ),
        encoding="utf-8",
    )

    result = _run("verify", dist)

    assert result.returncode == 2
    assert "duplicate JSON key: schema_version" in result.stderr


def test_release_bundle_refuses_unbound_identity(tmp_path: Path) -> None:
    dist, _, _ = _seed_dist(tmp_path)
    result = _run("create", dist, "--workflow-commit", "not-a-commit")

    assert result.returncode == 2
    assert "workflow commit must be" in result.stderr


def test_release_bundle_replaces_metadata_links_without_touching_linked_files(
    tmp_path: Path,
) -> None:
    dist, _, _ = _seed_dist(tmp_path)
    protected_receipt = tmp_path / "protected-receipt"
    protected_checksums = tmp_path / "protected-checksums"
    protected_receipt.write_bytes(b"protected receipt\n")
    protected_checksums.write_bytes(b"protected checksums\n")
    try:
        os.link(protected_receipt, dist / "release-receipt.json")
        os.link(protected_checksums, dist / "SHA256SUMS")
    except OSError as exc:
        pytest.skip(f"hard links unavailable in the test filesystem: {exc}")

    result = _run("create", dist)

    assert result.returncode == 0, result.stderr
    assert protected_receipt.read_bytes() == b"protected receipt\n"
    assert protected_checksums.read_bytes() == b"protected checksums\n"
    assert (dist / "release-receipt.json").read_bytes() != protected_receipt.read_bytes()
    assert (dist / "SHA256SUMS").read_bytes() != protected_checksums.read_bytes()
    assert not list(dist.glob(".release-receipt.json.*"))
    assert not list(dist.glob(".SHA256SUMS.*"))
