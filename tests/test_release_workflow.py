from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[1]
README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "release-candidate.yml"
RUNTIME_WORKFLOW = ROOT / ".github" / "workflows" / "runtime-release.yml"
PUBLIC_WORKFLOW = ROOT / ".github" / "workflows" / "public-release.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASING = ROOT / "docs" / "RELEASING.md"
DISTRIBUTION = ROOT / "docs" / "DISTRIBUTION.md"
PRIVATE_BETA = ROOT / "docs" / "PRIVATE_BETA.md"

ACTION_PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "astral-sh/setup-uv": "c771a70e6277c0a99b617c7a806ffedaca235ff9",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
}

PUBLIC_ACTION_PINS = {
    **ACTION_PINS,
    "actions/attest": "1e69f48acb82d1966a394da916b4c1698aa569d6",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
}

RUNTIME_ACTION_PINS = {
    **ACTION_PINS,
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
}


def _load(path: Path) -> dict[str, Any]:
    # BaseLoader keeps the workflow key `on` as text and never constructs Python objects.
    value = yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,  # noqa: S506
    )
    assert isinstance(value, dict)
    return value


def _uses(value: object) -> list[str]:
    if isinstance(value, dict):
        result = [item for key, item in value.items() if key == "uses" and isinstance(item, str)]
        for item in value.values():
            result.extend(_uses(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_uses(item))
        return result
    return []


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [step for step in job["steps"] if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def _step_index(job: dict[str, Any], name: str) -> int:
    return next(index for index, step in enumerate(job["steps"]) if step.get("name") == name)


def test_every_workflow_pins_external_actions_and_avoids_privileged_pr_code() -> None:
    workflows = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    assert workflows
    for path in workflows:
        document = _load(path)
        assert "pull_request_target" not in document.get("on", {})
        for use in _uses(document):
            if use.startswith("./"):
                continue
            action, separator, pin = use.rpartition("@")
            assert separator and action
            assert re.fullmatch(r"[0-9a-f]{40}", pin), f"un-pinned action in {path}: {use}"


def test_release_candidate_workflow_is_manual_private_and_least_privilege() -> None:
    workflow = _load(WORKFLOW)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"source_sha", "version"}
    assert workflow["permissions"] == {}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"

    assert set(workflow["jobs"]) == {"build"}
    job = workflow["jobs"]["build"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    assert job["env"] == {
        "UV_DEFAULT_INDEX": "https://pypi.org/simple",
        "UV_INDEX": "",
        "UV_NO_CACHE": "1",
        "UV_NO_CONFIG": "1",
        "UV_PYTHON_DOWNLOADS": "never",
    }

    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert len(uses) == len(ACTION_PINS)
    for use in uses:
        action, pin = use.rsplit("@", 1)
        assert re.fullmatch(r"[0-9a-f]{40}", pin)
        assert ACTION_PINS[action] == pin
    for step in job["steps"]:
        command = step.get("run", "")
        if "\n" in command:
            assert command.startswith("set -euo pipefail\n")

    commands = "\n".join(step.get("run", "") for step in job["steps"])
    owner_gate = _step(job, "Require owner-dispatched green main commit")
    assert owner_gate["env"]["RELEASE_OWNER"] == "${{ secrets.ATREADY_RELEASE_OWNER }}"
    assert (
        '[[ -z "$RELEASE_OWNER" || "$GITHUB_TRIGGERING_ACTOR" != "$RELEASE_OWNER" ]]'
        in (owner_gate["run"])
    )
    assert '"$GITHUB_TRIGGERING_ACTOR" != "$GITHUB_REPOSITORY_OWNER"' not in owner_gate["run"]
    owner_gate_index = _step_index(job, "Require owner-dispatched green main commit")
    assert owner_gate_index < _step_index(
        job, "Check out exact source without persisted credentials"
    )
    assert owner_gate_index < _step_index(job, "Upload private candidate bundle")
    coverage_command = _step(job, "Test with branch coverage")["run"]
    assert "pytest" in coverage_command
    assert "--cov=atready" in coverage_command
    assert "--cov-report=term-missing" in coverage_command
    assert coverage_command.startswith("uv run --locked --no-sync --with-editable . pytest")
    for required in (
        "GITHUB_TRIGGERING_ACTOR",
        "actions/workflows/ci.yml/runs",
        "-f branch=main",
        "uv sync --locked --all-groups --no-group release --no-group elevated --no-install-project",
        "uv sync --locked --all-groups --no-group elevated --no-install-project",
        "uv run --no-sync ruff check .",
        "uv run --no-sync ruff format --check .",
        "twine check --strict",
        "scripts/verify_readme_rendering.py",
        "--build-constraints build-constraints.txt",
        "--require-hashes",
        "scripts/verify_release_artifacts.py",
        "scripts/release_bundle.py create",
        "scripts/release_bundle.py verify",
        "SOURCE_DATE_EPOCH",
        'cmp "$candidate_root/dist-first/$wheel" "$candidate_root/dist-second/$wheel"',
        'cmp "$candidate_root/dist-first/$sdist" "$candidate_root/dist-second/$sdist"',
        "git status --porcelain=v1 --untracked-files=all",
    ):
        assert required in commands
    assert commands.count("scripts/verify_release_artifacts.py") == 2
    assert _step(job, "Install locked test dependencies")["run"] == (
        "uv sync --locked --all-groups --no-group release --no-group elevated --no-install-project"
    )
    build = _step(job, "Build twice through hash-constrained backend")
    assert "--build-constraints build-constraints.txt" in build["run"]
    assert "--require-hashes" in build["run"]
    assert _step(job, "Install locked release checks")["run"] == (
        "uv sync --locked --all-groups --no-group elevated --no-install-project"
    )
    assert "twine check --strict" in _step(job, "Check PyPI metadata and rendering")["run"]
    assert _step(job, "Verify rendered README links")["run"] == (
        "uv run --no-sync python scripts/verify_readme_rendering.py"
    )
    assert (
        "scripts/verify_release_artifacts.py" in _step(job, "Verify exact artifact contents")["run"]
    )
    assert _step_index(job, "Build twice through hash-constrained backend") < _step_index(
        job, "Install locked release checks"
    )
    assert _step_index(job, "Install locked release checks") < _step_index(
        job, "Check PyPI metadata and rendering"
    )
    assert _step_index(job, "Check PyPI metadata and rendering") < _step_index(
        job, "Verify rendered README links"
    )
    assert _step_index(job, "Verify rendered README links") < _step_index(
        job, "Verify exact artifact contents"
    )
    assert _step_index(job, "Smoke installed wheel") < _step_index(
        job, "Reverify exact artifacts after smokes"
    )
    assert _step_index(job, "Smoke staged plugin") < _step_index(
        job, "Reverify exact artifacts after smokes"
    )
    assert _step_index(job, "Reverify exact artifacts after smokes") < _step_index(
        job, "Create and verify unsigned candidate metadata"
    )
    timestamp = _step(job, "Bind build timestamps to source commit")["run"]
    assert '[[ ! "$source_date_epoch" =~ ^[0-9]+$ ]]' in timestamp
    assert "printf 'SOURCE_DATE_EPOCH=%s\\n' \"$source_date_epoch\"" in timestamp
    for forbidden in (
        "pull_request_target",
        "contents: write",
        "id-token: write",
        "attestations: write",
        "artifact-metadata: write",
        "packages: write",
        "gh release create",
        "twine upload",
        "pypa/gh-action-pypi-publish",
        "uv publish",
        "gh release",
        "git tag",
        "git push",
    ):
        assert forbidden not in WORKFLOW.read_text(encoding="utf-8")

    upload = next(
        step for step in job["steps"] if step.get("name") == "Upload private candidate bundle"
    )
    checkout = next(step for step in job["steps"] if step.get("name", "").startswith("Check out"))
    assert checkout["with"] == {
        "fetch-depth": "1",
        "persist-credentials": "false",
        "ref": "${{ inputs.source_sha }}",
        "submodules": "false",
    }
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["overwrite"] == "false"
    assert upload["with"]["retention-days"] == "7"
    assert upload["with"]["path"].splitlines() == [
        "${{ runner.temp }}/atready-candidate/dist/"
        "project_atready-${{ inputs.version }}-py3-none-any.whl",
        "${{ runner.temp }}/atready-candidate/dist/project_atready-${{ inputs.version }}.tar.gz",
        "${{ runner.temp }}/atready-candidate/dist/release-receipt.json",
        "${{ runner.temp }}/atready-candidate/dist/SHA256SUMS",
    ]


def test_runtime_release_workflow_is_private_source_reviewed_and_pypi_only() -> None:
    workflow = _load(RUNTIME_WORKFLOW)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "public_metadata_urls_verified",
        "publish_pypi",
        "source_sha",
        "version",
    }
    assert inputs["public_metadata_urls_verified"]["default"] == "false"
    assert inputs["publish_pypi"]["default"] == "false"
    assert workflow["permissions"] == {}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert set(workflow["jobs"]) == {"build", "publish-pypi"}

    build = workflow["jobs"]["build"]
    publish = workflow["jobs"]["publish-pypi"]
    assert build["permissions"] == {"actions": "read", "contents": "read"}
    assert publish["permissions"] == {"actions": "read", "id-token": "write"}
    assert publish["environment"] == "pypi"
    assert publish["if"] == "${{ inputs.publish_pypi }}"
    assert publish["needs"] == "build"

    uses = _uses(workflow)
    assert len(uses) == 6
    for use in uses:
        action, pin = use.rsplit("@", 1)
        assert re.fullmatch(r"[0-9a-f]{40}", pin)
        assert RUNTIME_ACTION_PINS[action] == pin

    build_commands = "\n".join(step.get("run", "") for step in build["steps"])
    coverage_command = _step(build, "Test with branch coverage")["run"]
    assert "pytest" in coverage_command
    assert "--cov=atready" in coverage_command
    assert "--cov-report=term-missing" in coverage_command
    assert coverage_command.startswith("uv run --locked --no-sync --with-editable . pytest")
    for required in (
        'GITHUB_REPOSITORY" != "stoicpickle/atready-dev"',
        'gh api "repos/$GITHUB_REPOSITORY" --jq .visibility',
        'GITHUB_REF" != "refs/heads/main"',
        'WORKFLOW_SHA" != "$SOURCE_SHA"',
        "GITHUB_TRIGGERING_ACTOR",
        'PUBLISH_PYPI" == "true" && "$PUBLIC_METADATA_URLS_VERIFIED" != "true"',
        "actions/workflows/ci.yml/runs",
        "-f branch=main",
        "uv sync --locked --all-groups --no-group release --no-group elevated --no-install-project",
        "uv run --no-sync ruff check .",
        "uv run --no-sync ruff format --check .",
        "twine check --strict",
        "scripts/verify_readme_rendering.py",
        "--build-constraints build-constraints.txt",
        "--require-hashes",
        "scripts/verify_release_artifacts.py",
        "scripts/smoke_wheel.py",
        "scripts/smoke_plugin.py",
        "SOURCE_DATE_EPOCH",
        'cmp "$root/first/$wheel" "$root/second/$wheel"',
        'cmp "$root/first/$source" "$root/second/$source"',
        "unsigned-runtime-release-review-metadata",
        '"workflow_path": ".github/workflows/runtime-release.yml"',
        '"runtime_version": os.environ["RELEASE_VERSION"]',
        '"schema_version": 2',
        '"plugin_version": plugin_version',
        "public_metadata_urls_verified",
        "git status --porcelain=v1 --untracked-files=all",
    ):
        assert required in build_commands
    assert build_commands.count("scripts/verify_release_artifacts.py") == 2
    assert _step_index(build, "Smoke installed wheel") < _step_index(
        build, "Reverify exact artifacts after smokes"
    )
    assert _step_index(build, "Smoke staged plugin") < _step_index(
        build, "Reverify exact artifacts after smokes"
    )
    assert _step_index(build, "Reverify exact artifacts after smokes") < _step_index(
        build, "Create bounded runtime review metadata"
    )
    assert _step_index(build, "Create bounded runtime review metadata") < _step_index(
        build, "Upload runtime distributions for owner review"
    )
    upload = _step(build, "Upload runtime distributions for owner review")
    assert upload["with"] == {
        "name": "runtime-release-${{ inputs.source_sha }}",
        "path": "${{ runner.temp }}/atready-runtime-release/dist/",
        "if-no-files-found": "error",
        "overwrite": "false",
        "retention-days": "30",
        "compression-level": "0",
    }

    publish_commands = "\n".join(step.get("run", "") for step in publish["steps"])
    assert "runtime-release-manifest.json" in publish_commands
    assert 'expected = {wheel, source, "runtime-release-manifest.json", "SHA256SUMS"}' in (
        publish_commands
    )
    assert "review artifact does not contain the exact four regular files" in publish_commands
    assert 'publish_requested": True' in publish_commands
    assert 'public_metadata_urls_verified": True' in publish_commands
    assert '"runtime_version": version' in publish_commands
    assert '"plugin_version": plugin_version' in publish_commands
    assert "uv publish --no-config --trusted-publishing always" in publish_commands
    assert "--publish-url https://upload.pypi.org/legacy/" in publish_commands
    assert "uv build" not in publish_commands
    assert "twine upload" not in publish_commands
    assert _step_index(publish, "Verify review metadata and exact publish bytes") < _step_index(
        publish, "Publish wheel and sdist without rebuilding"
    )
    assert all(not step.get("name", "").startswith("Check out") for step in publish["steps"])

    workflow_text = RUNTIME_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "gh release",
        "actions/attest",
        "attestations: write",
        "contents: write",
        "PYPI_API_TOKEN",
        "password:",
        "git tag",
        "git push",
    ):
        assert forbidden not in workflow_text


def test_public_release_workflow_is_manual_split_and_human_gated() -> None:
    workflow = _load(PUBLIC_WORKFLOW)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {
        "immutable_releases_verified",
        "publish_pypi",
        "source_sha",
        "tag",
        "version",
    }
    assert inputs["immutable_releases_verified"]["default"] == "false"
    assert inputs["publish_pypi"]["default"] == "false"
    assert workflow["permissions"] == {}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert set(workflow["jobs"]) == {
        "attest",
        "build",
        "draft-release",
        "publish-pypi",
        "publish-release",
    }

    build = workflow["jobs"]["build"]
    attest = workflow["jobs"]["attest"]
    draft = workflow["jobs"]["draft-release"]
    release = workflow["jobs"]["publish-release"]
    publish = workflow["jobs"]["publish-pypi"]
    assert build["permissions"] == {"actions": "read", "contents": "read"}
    assert attest["permissions"] == {
        "actions": "read",
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }
    assert draft["permissions"] == {"actions": "read", "contents": "write"}
    assert release["permissions"] == {
        "actions": "read",
        "attestations": "read",
        "contents": "write",
    }
    assert release["environment"] == "github-release"
    assert publish["permissions"] == {
        "actions": "read",
        "attestations": "read",
        "contents": "read",
        "id-token": "write",
    }
    assert publish["environment"] == "pypi"
    assert publish["if"] == "${{ inputs.publish_pypi }}"
    assert attest["needs"] == "build"
    assert set(draft["needs"]) == {"attest", "build"}
    assert release["needs"] == "draft-release"
    assert set(publish["needs"]) == {"build", "publish-release"}

    checkout = _step(build, "Check out exact source without persisted credentials")
    assert checkout["with"] == {
        "fetch-depth": "0",
        "fetch-tags": "true",
        "persist-credentials": "false",
        "ref": "${{ inputs.source_sha }}",
        "submodules": "false",
    }
    upload = _step(build, "Upload reviewed release subjects")
    assert upload["with"] == {
        "compression-level": "0",
        "if-no-files-found": "error",
        "name": "public-release-${{ inputs.source_sha }}",
        "overwrite": "false",
        "path": "${{ runner.temp }}/atready-public-release/dist/",
        "retention-days": "30",
    }

    for use in _uses(workflow):
        action, pin = use.rsplit("@", 1)
        assert PUBLIC_ACTION_PINS[action] == pin
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            command = step.get("run", "")
            if "\n" in command:
                assert command.startswith("set -euo pipefail\n")

    build_commands = "\n".join(step.get("run", "") for step in build["steps"])
    for required in (
        '"$RELEASE_TAG" != "v$RELEASE_VERSION"',
        '"$GITHUB_REF" != "refs/tags/$RELEASE_TAG"',
        '"$WORKFLOW_SHA" != "$SOURCE_SHA"',
        "GITHUB_TRIGGERING_ACTOR",
        '"$IMMUTABLE_RELEASES_VERIFIED" != "true"',
        "gh release verify --help",
        "gh release verify-asset --help",
        "gh attestation verify --help",
        "--jq .visibility",
        "actions/workflows/ci.yml/runs",
        "-f branch=main",
        'git rev-parse "$RELEASE_TAG^{}"',
        "--build-constraints build-constraints.txt",
        "--require-hashes",
        'cmp "$root/first/$wheel" "$root/second/$wheel"',
        'cmp "$root/first/$source" "$root/second/$source"',
        "scripts/verify_release_artifacts.py",
        "scripts/smoke_wheel.py",
        "scripts/smoke_plugin.py",
        '"workflow_path": ".github/workflows/public-release.yml"',
        '"metadata_kind": "unsigned-public-release-metadata"',
        '"review_materials": {',
        '"path": "scripts/first_user_acceptance.py"',
        'pathlib.Path("scripts/first_user_acceptance.py").read_bytes()',
    ):
        assert required in build_commands
    validate = _step(build, "Validate source, plugin, and tests")
    assert validate["env"] == {"RELEASE_VERSION": "${{ inputs.version }}"}
    assert 'test "$actual_version" = "$RELEASE_VERSION"' in validate["run"]
    assert "${{ inputs.version }}" not in validate["run"]
    assert "uv run --locked --no-sync --with-editable . pytest" in validate["run"]
    timestamp_build = _step(
        build,
        "Bind timestamps and build twice through hash-constrained backend",
    )["run"]
    assert 'export SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$GITHUB_SHA")"' in (
        timestamp_build
    )
    assert "SOURCE_DATE_EPOCH=" not in "\n".join(
        step.get("run", "")
        for step in build["steps"]
        if step.get("name") != "Bind timestamps and build twice through hash-constrained backend"
    )
    assert '>> "$GITHUB_ENV"' not in timestamp_build

    attest_step = _step(attest, "Generate GitHub build provenance")
    assert attest_step["uses"].startswith("actions/attest@")
    assert set(attest_step["with"]["subject-path"].splitlines()) == {
        "dist/project_atready-${{ inputs.version }}-py3-none-any.whl",
        "dist/project_atready-${{ inputs.version }}.tar.gz",
    }
    draft_command = _step(draft, "Create or verify exact draft without publishing it")["run"]
    for required in (
        "if gh release view",
        "--json isDraft",
        "--json isImmutable",
        'isDraft --jq .isDraft)" = "true"',
        'isImmutable --jq .isImmutable)" = "false"',
        "gh release create",
        "--verify-tag",
        "--draft",
        "gh release download",
        "--json assets",
        "SHA256SUMS public-release-manifest.json",
        'cmp "$expected_assets" "$actual_assets"',
        'cmp "dist/$name" "$draft_dist/$name"',
    ):
        assert required in draft_command
    assert draft_command.index("if gh release view") < draft_command.index("gh release create")
    assert draft_command.index("gh release create") < draft_command.index(
        'cmp "dist/$name" "$draft_dist/$name"'
    )
    release_commands = "\n".join(step.get("run", "") for step in release["steps"])
    for required in (
        "gh attestation verify",
        "--signer-workflow",
        "--source-digest",
        "--signer-digest",
        "--source-ref",
        "--deny-self-hosted-runners",
        "gh release edit",
        "--draft=false",
        "gh release verify",
        "--json isImmutable",
        'commits/$RELEASE_TAG" --jq .sha',
        '"$is_draft" == "true" && "$is_immutable" == "false"',
        '"$is_draft" == "false" && "$is_immutable" == "true"',
        "gh release download",
        "--json assets",
        "SHA256SUMS public-release-manifest.json",
        'cmp "$expected_assets" "$actual_assets"',
        'cmp "reviewed-dist/$name" "$released_dist/$name"',
        "for attempt in {1..12}",
        "sleep 5",
        '"$release_verified" != "true"',
    ):
        assert required in release_commands
    release_publish = _step(release, "Publish the reviewer-approved draft and prove immutability")[
        "run"
    ]
    assert release_publish.index('cmp "reviewed-dist/$name" "$released_dist/$name"') < (
        release_publish.index("is_draft=")
    )
    assert release_publish.index('cmp "reviewed-dist/$name" "$released_dist/$name"') < (
        release_publish.index('gh release edit "$RELEASE_TAG"')
    )
    publish_commands = "\n".join(step.get("run", "") for step in publish["steps"])
    for required in (
        "gh release verify",
        "gh release verify-asset",
        "gh release download",
        "--json isImmutable",
        'commits/$RELEASE_TAG" --jq .sha',
        'cmp "reviewed-dist/$name" "released-dist/$name"',
        "gh attestation verify",
        "--signer-workflow",
        "--source-digest",
        "--signer-digest",
        "--source-ref",
        "--deny-self-hosted-runners",
        "uv publish --no-config --trusted-publishing always",
        "https://upload.pypi.org/legacy/",
    ):
        assert required in publish_commands
    assert "uv build" not in publish_commands
    publish_step = _step(publish, "Publish wheel and sdist without rebuilding")
    assert publish_step["env"] == {"RELEASE_VERSION": "${{ inputs.version }}"}
    assert "${RELEASE_VERSION}" in publish_step["run"]
    assert "${{ inputs.version }}" not in publish_step["run"]

    text = PUBLIC_WORKFLOW.read_text(encoding="utf-8")
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            assert "${{ inputs." not in step.get("run", "")
    for forbidden in ("pull_request_target", "git tag", "git push", "twine upload"):
        assert forbidden not in text


def test_public_release_runbook_keeps_external_controls_and_proof_explicit() -> None:
    text = RELEASING.read_text(encoding="utf-8")
    prose = " ".join(text.split())
    for required in (
        '"repos/$repository/immutable-releases"',
        '"repos/$repository/environments/github-release"',
        '"repos/$repository/environments/pypi"',
        "-f branch=main -f event=push -f status=success",
        "gh workflow run public-release.yml",
        '--ref "$tag"',
        "-f publish_pypi=true",
        "-f immutable_releases_verified=true",
        'gh release verify "$tag"',
        'gh release verify-asset "$tag"',
        'gh attestation verify "$artifact"',
        '--signer-workflow "$signer_workflow"',
        '--source-digest "$source_sha"',
        '--signer-digest "$source_sha"',
        '--source-ref "refs/tags/$tag"',
        "--deny-self-hosted-runners",
        "--json isImmutable",
        'commits/$tag" --jq .sha',
        'git show-ref --verify --quiet "refs/tags/$tag"',
        'git ls-remote --exit-code --tags origin "refs/tags/$tag"',
        'git rev-parse "$tag^{}"',
        'git ls-remote origin "refs/tags/$tag^{}"',
        "printf '%s\\n' \\\n  SHA256SUMS",
        'cmp "$expected_assets" "$actual_assets"',
        'f"https://pypi.org/pypi/project-atready/{version}/json"',
        'parsed.hostname != "files.pythonhosted.org"',
        "hashlib.sha256(content).hexdigest() != digest",
        '"$pypi_dir/project_atready-${version}-py3-none-any.whl"',
        '"$pypi_dir/project_atready-${version}.tar.gz"',
        '"repos/$repository/actions/permissions" --jq .allowed_actions',
        '"repos/$repository/actions/permissions" --jq .sha_pinning_required',
        '"repos/$repository/actions/permissions/workflow"',
        '"repos/$repository/actions/permissions/selected-actions"',
        "pending Trusted Publisher",
        "project `project-atready`",
        "GitHub owner `stoicpickle`",
        "repository `atready`",
        "environment `pypi`",
    ):
        assert required in text
    assert "does not create a separate PyPI publish attestation bundle" in prose
    for check_name in (
        "ubuntu-latest / Python 3.11",
        "ubuntu-latest / Python 3.14",
        "macos-latest / Python 3.11",
        "macos-latest / Python 3.14",
        "windows-latest / Python 3.11",
        "windows-latest / Python 3.14",
    ):
        assert check_name in prose
    assert text.count("```bash\n") == text.count("```bash\nset -euo pipefail\n")
    verifier_marker = 'PYPI_DIR="$pypi_dir" RELEASE_VERSION="$version" python - <<\'PY\'\n'
    pypi_verifier = text.split(verifier_marker, 1)[1].split("\nPY\n", 1)[0]
    compile(pypi_verifier, "RELEASING.md PyPI verifier", "exec")
    assert "workflow filename `public-release.yml`" in prose
    assert "`.github/workflows/public-release.yml`, and the `pypi` environment" not in prose
    assert "cannot be proved by committed YAML" in prose
    assert "retries for a bounded 55 seconds and fails closed" in prose
    assert "already-published immutable release at the exact source SHA" in prose
    assert "workflow success alone is not first-user proof" in prose
    bash_blocks = re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL)
    fetch = "git fetch --no-tags origin main:refs/remotes/origin/main"
    remote_check = 'git rev-parse origin/main)" = "$source_sha"'
    remote_blocks = [block for block in bash_blocks if "git rev-parse origin/main" in block]
    assert remote_blocks
    for block in remote_blocks:
        assert fetch in block
        assert block.index(fetch) < block.index(remote_check)

    candidate_blocks = [block for block in bash_blocks if 'candidate_dir="$(mktemp -d)"' in block]
    assert len(candidate_blocks) == 1
    assert (
        'uv run --no-sync python scripts/verify_release_artifacts.py --dist "$candidate_dir"'
        in candidate_blocks[0]
    )
    assert (
        "uv run --no-sync python scripts/release_bundle.py verify \\\n"
        '  --dist "$candidate_dir"' in candidate_blocks[0]
    )

    runtime_blocks = [block for block in bash_blocks if 'artifact_dist="$(mktemp -d)"' in block]
    assert len(runtime_blocks) == 1
    assert (
        'uv run --no-sync python scripts/verify_release_artifacts.py --dist "$artifact_dist"'
        in runtime_blocks[0]
    )
    assert "uv run python scripts/verify_release_artifacts.py" not in text
    assert "uv run python scripts/release_bundle.py verify" not in text


def test_distribution_uses_current_source_bound_release_and_submission_channels() -> None:
    text = DISTRIBUTION.read_text(encoding="utf-8")
    prose = " ".join(text.split())
    release_text = RELEASING.read_text(encoding="utf-8")
    assert '--signer-workflow "$signer_workflow"' in release_text
    assert '--signer-digest "$source_sha"' in release_text
    assert "RELEASED_SIGNER_WORKFLOW_IDENTITY" not in release_text
    assert "RELEASE_SIGNER_COMMIT_SHA" not in release_text
    assert "Promote the private candidate design" not in text
    assert "https://developers.openai.com/plugins/deploy/submission" in text
    assert "OpenAI Platform plugin submission portal" in text
    assert "Apps Management write permission" in text
    assert "explicitly authorize the external submission" in prose
    for distribution_boundary in (
        "AtReady is an open-source resource-fit companion for Codex",
        "private development -> reviewed public source beta -> optional PyPI package",
        "received its first clean source snapshot and was anonymously verified as public",
        "runtime contract version `1`",
        "product-version equality is no longer the compatibility boundary",
        "`atready runtime contract --json`",
        "`atready doctor --plugin-version VERSION --plugin-contract 1",
        "`runtime-release.yml`",
        "tagged, immutable, attested GitHub/PyPI release",
        "website, support, privacy, and terms URLs",
    ):
        assert distribution_boundary in prose
    assert "The plugin is the user experience" not in text


def test_release_runbook_separates_public_source_and_optional_package_lanes() -> None:
    text = RELEASING.read_text(encoding="utf-8")
    prose = " ".join(text.split())
    for required in (
        "`public-release.yml` is the source-public GitHub release and provenance lane",
        "The first public product surface is the open-source CLI repository",
        "## Publish the public runtime from private source",
        "`stoicpickle/atready-dev`",
        "workflow filename `runtime-release.yml`",
        "environment `pypi`",
        "runtime-release-$source_sha",
        "publish_requested",
        "does not check out source or rebuild",
        "A run with `publish_pypi=false` is a non-publishing rehearsal",
        "## Public-source release lane",
        "A public source beta may still exist without a tagged release, PyPI package, or OpenAI",
    ):
        assert required in prose
    assert "Before the first public release:" not in text


def test_private_beta_is_named_exact_candidate_access_with_cleanup() -> None:
    text = PRIVATE_BETA.read_text(encoding="utf-8")
    prose = " ".join(text.split())

    for required in (
        "organization-owned private beta repository",
        "uv 0.11.7",
        "beta-testers team with read-only repository access",
        "do not add testers to the personal development repository",
        "## Recommended one-command setup and update",
        "python3 beta_setup.py install",
        "python3 beta_setup.py update",
        "python3 beta_setup.py status",
        "--repository BETA_OWNER/BETA_REPOSITORY",
        "--beta-root /ABSOLUTE/PATH/atready-beta",
        "never changes GitHub access",
        "never silently advances to a branch head or friendly tag",
        '[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]]',
        '[[ "$run_id" =~ ^[0-9]+$ ]]',
        'gh run view "$run_id" --repo "$repository"',
        'repository="BETA_OWNER/BETA_REPOSITORY"',
        "--json workflowName --jq .workflowName",
        "--json event --jq .event",
        "--json conclusion --jq .conclusion",
        "--json headSha --jq .headSha",
        'git -C "$beta_root/source" checkout --detach "$source_sha"',
        'gh run download "$run_id"',
        '--name "release-candidate-$source_sha"',
        "release-receipt.json",
        'test "$(find "$beta_root/candidate" -mindepth 1 -maxdepth 1',
        "shasum -a 256 -c SHA256SUMS",
        'python3 "$beta_root/source/scripts/release_bundle.py" verify',
        '--source-commit "$source_sha"',
        '--workflow-commit "$source_sha"',
        'runtime_version="$(python3 -c',
        'plugin_version="$(python3 -c',
        "uv tool install --no-config --no-python-downloads",
        "--default-index https://pypi.org/simple --force --reinstall --no-cache",
        'codex plugin marketplace add "$beta_root/source"',
        "codex plugin add atready@atready",
        "project-atready/scripts/atready.py",
        "runtime contract --json",
        'python3 "$beta_root/source/scripts/first_user_acceptance.py"',
        "codex plugin remove atready@atready",
        "codex plugin marketplace remove atready",
        "uv tool uninstall project-atready",
    ):
        assert required in text
    for boundary in (
        "unsigned private candidate",
        "does not publish to PyPI or the OpenAI Plugins Directory",
        "Do not forward the bundle",
        "Use only synthetic projects",
        "does not delete an inventory",
        "cannot prove public availability",
    ):
        assert boundary in prose
    for forbidden in (
        "permission=pull",
        "/collaborators/TESTER_GITHUB_USERNAME",
        'repository="stoicpickle/atready-dev"',
    ):
        assert forbidden not in text

    readme_text = README.read_text(encoding="utf-8")
    assert "Public beta" in readme_text
    assert "Public beta candidate" not in readme_text
    assert "generally available" not in readme_text
    assert "PRIVATE_BETA.md" in DISTRIBUTION.read_text(encoding="utf-8")
    assert "PRIVATE_BETA.md" in RELEASING.read_text(encoding="utf-8")

    bash_blocks = re.findall(
        r"^[ \t]*```bash\n(.*?)\n[ \t]*```$",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert len(bash_blocks) == 5
    helper_install = next(block for block in bash_blocks if "beta_setup.py install" in block)
    helper_update = next(block for block in bash_blocks if "beta_setup.py update" in block)
    download = next(block for block in bash_blocks if 'source_sha="SOURCE_SHA"' in block)
    install = next(block for block in bash_blocks if 'runtime_version="$(python3' in block)
    cleanup = next(block for block in bash_blocks if 'beta_root="PASTE_' in block)

    assert "--source-sha SOURCE_SHA" in helper_install
    assert "--source-sha NEW_SOURCE_SHA" in helper_update
    assert "-name '*.whl'" in download
    assert "-name '*.tar.gz'" in download
    assert "project_atready-$runtime_version-py3-none-any.whl" in install
    for earlier, later in (
        ("--json workflowName --jq .workflowName", 'gh repo clone "$repository"'),
        ("--json headSha --jq .headSha", 'gh repo clone "$repository"'),
        ('checkout --detach "$source_sha"', 'gh run download "$run_id"'),
        ('gh run download "$run_id"', "expected_files=("),
        ("expected_files=(", "shasum -a 256 -c SHA256SUMS"),
        ("shasum -a 256 -c SHA256SUMS", "scripts/release_bundle.py"),
    ):
        assert download.index(earlier) < download.index(later)
    assert "report_beta_failure" in download
    assert "trap report_beta_failure EXIT" in download

    for fail_closed_check in (
        'marketplace_listing="$(codex plugin marketplace list)" || {',
        'existing_plugins="$(codex plugin list)" || {',
        "printf '%s\\n' \"$marketplace_listing\" | grep -Eq",
        "printf '%s\\n' \"$existing_plugins\" | grep -Eq '^atready@'",
    ):
        assert fail_closed_check in install
    for earlier, later in (
        ('test -e "$ar_uv_bin/atready"', "uv tool install"),
        ('existing_plugins="$(codex plugin list)"', "uv tool install"),
        ("uv tool install", "first_user_acceptance.py"),
        ("first_user_acceptance.py", 'init --path "$test_inventory"'),
        ('init --path "$test_inventory"', "codex plugin marketplace add"),
        ("codex plugin marketplace add", "codex plugin add"),
        ("codex plugin add", "project-atready/scripts/atready.py"),
    ):
        assert install.index(earlier) < install.index(later)
    assert "trap - EXIT" in install

    for ownership_check in (
        'test -d "$beta_root/source/.git"',
        'test -d "$beta_root/candidate"',
        'test -d "$beta_root/test-state"',
        'test "$("$ar_uv_bin/atready" --version)" = "atready $runtime_version"',
        'test "$marketplace_root" = "$beta_root/source"',
        'test "$plugin_path" = "$beta_root/source/plugins/atready"',
        '$1 == "atready@atready"',
        "$4 == version",
        "stop without removing anything",
    ):
        assert ownership_check in cleanup
    assert cleanup.index("codex plugin remove") < cleanup.index("marketplace remove")
    assert cleanup.index("marketplace remove") < cleanup.index("uv tool uninstall")


def test_build_backend_and_sdist_are_explicitly_bounded() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["build-system"] == {
        "requires": ["hatchling==1.31.0"],
        "build-backend": "hatchling.build",
    }
    assert project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"] == [
        "/PRIVACY.md",
        "/TERMS.md",
        "/src/atready",
        "/plugins/atready/skills/project-atready",
    ]
    assert project["dependency-groups"]["release"] == [
        "readme-renderer[md]>=45,<46",
        "twine>=7,<8",
    ]

    constraints = (ROOT / "build-constraints.txt").read_text(encoding="ascii")
    requirements = re.findall(r"^([a-z0-9-]+)==([^ \\]+) \\$", constraints, re.MULTILINE)
    assert requirements == [
        ("hatchling", "1.31.0"),
        ("packaging", "26.3"),
        ("pathspec", "1.1.1"),
        ("pluggy", "1.6.0"),
        ("trove-classifiers", "2026.6.1.19"),
    ]
    assert constraints.count("--hash=sha256:") == 10

    ci_workflow = _load(CI)
    assert set(ci_workflow["jobs"]) == {"validate"}
    ci_job = ci_workflow["jobs"]["validate"]
    assert _step(ci_job, "Install locked dependencies")["run"] == (
        "uv sync --locked --all-groups --no-group release --no-group elevated --no-install-project"
    )
    assert _step(ci_job, "Test")["run"] == ("uv run --locked --no-sync --with-editable . pytest")
    assert _step(ci_job, "Test with branch coverage")["run"] == (
        "uv run --locked --no-sync --with-editable . pytest --cov=atready --cov-report=term-missing"
    )
    ci_build = _step(ci_job, "Build distributions")
    assert "--build-constraints build-constraints.txt --require-hashes" in ci_build["run"]
    assert ci_build["env"] == {
        "UV_DEFAULT_INDEX": "https://pypi.org/simple",
        "UV_INDEX": "",
        "UV_NO_CONFIG": "1",
    }
    assert _step(ci_job, "Install locked release checks")["run"] == (
        "uv sync --locked --all-groups --no-group elevated --no-install-project"
    )
    assert _step(ci_job, "Check PyPI metadata and rendering")["run"] == (
        "uv run --no-sync twine check --strict dist/*"
    )
    assert _step(ci_job, "Verify rendered README links")["run"] == (
        "uv run --no-sync python scripts/verify_readme_rendering.py"
    )
    assert _step(ci_job, "Verify exact artifact contents")["run"] == (
        "uv run --no-sync python scripts/verify_release_artifacts.py --dist dist"
    )
    clean_first_use = _step(ci_job, "Prove clean source and wheel first use")
    assert clean_first_use["if"] == "matrix.python == '3.11'"
    assert clean_first_use["run"] == (
        "uv run --no-sync python scripts/hardening_gate.py "
        "--wheel ./dist/project_atready-0.1.10-py3-none-any.whl"
    )
    assert set(ci_job["strategy"]["matrix"]["os"]) == {
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
    }
    assert _step_index(ci_job, "Build distributions") < _step_index(
        ci_job, "Install locked release checks"
    )
    assert _step_index(ci_job, "Install locked release checks") < _step_index(
        ci_job, "Check PyPI metadata and rendering"
    )
    assert _step_index(ci_job, "Check PyPI metadata and rendering") < _step_index(
        ci_job, "Verify rendered README links"
    )
    assert _step_index(ci_job, "Verify rendered README links") < _step_index(
        ci_job, "Verify exact artifact contents"
    )
    assert _step_index(ci_job, "Verify exact artifact contents") < _step_index(
        ci_job, "Smoke installed wheel"
    )
    assert _step_index(ci_job, "Smoke installed wheel") < _step_index(
        ci_job, "Prove clean source and wheel first use"
    )
