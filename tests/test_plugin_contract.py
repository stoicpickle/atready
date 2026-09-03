from __future__ import annotations

import ast
import json
import os
import re
import runpy
import subprocess
import sys
import time
import tomllib
from pathlib import Path, PurePosixPath
from unittest import mock

import pytest

from atready.models import Inventory, ProjectBrief
from atready.routing import route
from atready.yamlio import loads_yaml

ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "plugins" / "atready"
SKILL = PLUGIN / "skills" / "project-atready"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
WRAPPER = SKILL / "scripts" / "atready.py"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
FAKE_UV = r"C:\resolved\uv.exe" if os.name == "nt" else "/resolved/uv"
EXPECTED_PNG_ASSETS = {
    "icon.png": (512, 512),
    "logo-dark.png": (1200, 300),
    "logo.png": (1200, 300),
    "route-overview.png": (1440, 900),
    "safe-preview.png": (1440, 900),
}
DIRECTORY_PACKET = ROOT / "docs" / "DIRECTORY_SUBMISSION.md"
FIRST_USER_ACCEPTANCE = ROOT / "docs" / "FIRST_USER_ACCEPTANCE.md"
REVIEW_INVENTORY = ROOT / "evals" / "fixtures" / "inventory.yaml"
REVIEW_PROJECT = ROOT / "evals" / "fixtures" / "project-godot.yaml"
OFFICIAL_SUBMISSION_URL = "https://developers.openai.com/plugins/deploy/submission"
SUBMISSION_PUBLIC_URLS = (
    "https://github.com/stoicpickle/atready",
    "https://github.com/stoicpickle/atready/blob/main/SUPPORT.md",
    "https://github.com/stoicpickle/atready/blob/main/PRIVACY.md",
    "https://github.com/stoicpickle/atready/blob/main/TERMS.md",
)
SMOKE_PLUGIN_NAMESPACE = runpy.run_path(str(ROOT / "scripts" / "smoke_plugin.py"))
SMOKE_PNG_CONTRACT = SMOKE_PLUGIN_NAMESPACE["_png_contract"]
SMOKE_MAX_PNG_BYTES = SMOKE_PLUGIN_NAMESPACE["_MAX_PNG_BYTES"]
SMOKE_LAUNCHER_REQUIREMENTS = SMOKE_PLUGIN_NAMESPACE["_launcher_requirements"]
SMOKE_MAX_PRODUCT_VERSION_CHARACTERS = SMOKE_PLUGIN_NAMESPACE["_MAX_PRODUCT_VERSION_CHARACTERS"]
SMOKE_MAX_REQUIRED_FEATURE_IDS = SMOKE_PLUGIN_NAMESPACE["_MAX_REQUIRED_FEATURE_IDS"]
SMOKE_MAX_FEATURE_ID_CHARACTERS = SMOKE_PLUGIN_NAMESPACE["_MAX_FEATURE_ID_CHARACTERS"]


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_strict_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)


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
    raise AssertionError(f"{path} does not assign a string to {name}")


def _embedded_reviewer_yaml(packet: str, label: str) -> dict[str, object]:
    match = re.search(
        rf"### `{re.escape(label)}`\n\n```yaml\n(.*?)\n```",
        packet,
        re.DOTALL,
    )
    assert match is not None, f"missing reviewer fixture: {label}"
    value = loads_yaml(match.group(1))
    assert isinstance(value, dict)
    return value


def _doctor_arguments(namespace: dict[str, object]) -> list[str]:
    arguments = [
        "doctor",
        "--plugin-version",
        str(namespace["PLUGIN_VERSION"]),
        "--plugin-contract",
        str(namespace["REQUIRED_RUNTIME_CONTRACT_VERSION"]),
    ]
    for feature_id in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]:
        arguments.extend(("--require-feature", feature_id))
    arguments.append("--json")
    return arguments


def _doctor_payload(
    namespace: dict[str, object],
    *,
    runtime_version: str = "9.9.9",
    runtime_features: list[str] | None = None,
    compatible: bool = True,
) -> dict[str, object]:
    features = runtime_features
    if features is None:
        features = list(namespace["REQUIRED_RUNTIME_FEATURE_IDS"])
    return {
        "compatible": compatible,
        "inventory_read": False,
        "missing_features": [],
        "network_accessed": False,
        "plugin_contract_version": namespace["REQUIRED_RUNTIME_CONTRACT_VERSION"],
        "plugin_version": namespace["PLUGIN_VERSION"],
        "product": "project-atready",
        "runtime_contract_version": namespace["REQUIRED_RUNTIME_CONTRACT_VERSION"],
        "runtime_features": features,
        "runtime_version": runtime_version,
        "status": "ready" if compatible else "incompatible",
        "writes_performed": False,
    }


def _staged_launcher(
    tmp_path: Path,
    *,
    version: str = "0.1.5",
    contract: int = 1,
    features: tuple[str, ...] = ("inventory.read.v1", "routing.plan-only.v1"),
) -> Path:
    launcher = tmp_path / "atready.py"
    launcher.write_text(
        f"PLUGIN_VERSION = {version!r}\n"
        f"REQUIRED_RUNTIME_CONTRACT_VERSION = {contract!r}\n"
        f"REQUIRED_RUNTIME_FEATURE_IDS = {features!r}\n",
        encoding="utf-8",
    )
    return launcher


def test_staged_plugin_smoke_accepts_bounded_launcher_metadata(tmp_path: Path) -> None:
    version = "1.1." + "9" * (SMOKE_MAX_PRODUCT_VERSION_CHARACTERS - len("1.1."))
    features = tuple(
        [f"feature-{index:03d}" for index in range(SMOKE_MAX_REQUIRED_FEATURE_IDS - 1)]
        + ["z" * SMOKE_MAX_FEATURE_ID_CHARACTERS]
    )

    assert SMOKE_LAUNCHER_REQUIREMENTS(
        _staged_launcher(tmp_path, version=version, features=features)
    ) == (version, 1, features)


@pytest.mark.parametrize(
    "version",
    [
        "not a version",
        "01.2.3",
        "1.02.3",
        "1.2.03",
        "1.2.3.",
        "1.2.3+",
        "1.2.3-",
        "1.1." + "9" * (SMOKE_MAX_PRODUCT_VERSION_CHARACTERS - len("1.1.") + 1),
    ],
)
def test_staged_plugin_smoke_rejects_invalid_product_versions(tmp_path: Path, version: str) -> None:
    launcher = _staged_launcher(tmp_path, version=version)

    with pytest.raises(AssertionError, match="invalid runtime requirements"):
        SMOKE_LAUNCHER_REQUIREMENTS(launcher)


@pytest.mark.parametrize(
    "features",
    [
        ("invalid feature",),
        ("z" * (SMOKE_MAX_FEATURE_ID_CHARACTERS + 1),),
        tuple(f"feature-{index:03d}" for index in range(SMOKE_MAX_REQUIRED_FEATURE_IDS + 1)),
    ],
)
def test_staged_plugin_smoke_rejects_invalid_feature_metadata(
    tmp_path: Path, features: tuple[str, ...]
) -> None:
    launcher = _staged_launcher(tmp_path, features=features)

    with pytest.raises(AssertionError, match="invalid runtime requirements"):
        SMOKE_LAUNCHER_REQUIREMENTS(launcher)


def test_plugin_is_minimal_skill_only_and_independently_versioned() -> None:
    manifest = _load_strict_json(MANIFEST)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    package_version = _assigned_string(ROOT / "src" / "atready" / "__init__.py", "__version__")
    plugin_version = _assigned_string(WRAPPER, "PLUGIN_VERSION")
    reviewed_runtime_commit = _assigned_string(WRAPPER, "REVIEWED_RUNTIME_COMMIT")
    public_runtime_source = _assigned_string(WRAPPER, "PUBLIC_RUNTIME_SOURCE")

    assert PLUGIN.name == manifest["name"] == "atready"
    assert manifest["version"] == plugin_version
    assert project["version"] == package_version
    assert SEMVER.fullmatch(manifest["version"])
    assert SEMVER.fullmatch(project["version"])
    assert re.fullmatch(r"[0-9a-f]{40}", reviewed_runtime_commit)
    assert public_runtime_source == (
        "git+https://github.com/stoicpickle/atready.git@" + reviewed_runtime_commit
    )
    assert set(manifest) == {
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "skills",
        "interface",
    }
    assert manifest["description"].strip()
    assert manifest["author"] == {
        "name": "stoicpickle",
        "url": "https://github.com/stoicpickle",
    }
    assert manifest["homepage"] == "https://github.com/stoicpickle/atready"
    assert manifest["repository"] == "https://github.com/stoicpickle/atready"
    assert manifest["license"] == "Apache-2.0"
    assert manifest["keywords"] and all(
        isinstance(value, str) and value.strip() for value in manifest["keywords"]
    )
    assert manifest["skills"] == "./skills/"
    assert {path.name for path in PLUGIN.iterdir()} == {".codex-plugin", "assets", "skills"}
    assert {path.name for path in (PLUGIN / "skills").iterdir()} == {"project-atready"}
    interface = manifest["interface"]
    assert set(interface) == {
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
        "capabilities",
        "websiteURL",
        "supportURL",
        "privacyPolicyURL",
        "termsOfServiceURL",
        "defaultPrompt",
        "brandColor",
        "composerIcon",
        "logo",
    }
    assert all(
        isinstance(interface[field], str) and interface[field].strip()
        for field in (
            "displayName",
            "shortDescription",
            "longDescription",
            "developerName",
            "category",
        )
    )
    assert interface["capabilities"] == [
        "Add declared resources with approval",
        "Match saved resources to project work",
        "Explain constraints, gaps, and omissions",
    ]
    assert interface["websiteURL"] == "https://github.com/stoicpickle/atready"
    assert interface["supportURL"] == (
        "https://github.com/stoicpickle/atready/blob/main/SUPPORT.md"
    )
    assert interface["privacyPolicyURL"].endswith("/PRIVACY.md")
    assert interface["termsOfServiceURL"].endswith("/TERMS.md")
    assert len(interface["displayName"]) <= 30
    assert len(interface["shortDescription"]) <= 30
    assert interface["shortDescription"] == "Bring resource fit to the plan"
    assert "small resource-fit companion" in interface["longDescription"]
    assert "conversational no-write preview" in interface["longDescription"]
    assert "separate exact save approval" in interface["longDescription"]
    assert "goal, rough plan, or written plan before implementation" in interface["longDescription"]
    assert "planner-provided work" in interface["longDescription"]
    assert (
        "saved tools, services, subscriptions, people, and agents to planner-provided work"
        in interface["longDescription"]
    )
    assert "Codex owns the project plan" in interface["longDescription"]
    assert "without contacting or running routed project resources" in interface["longDescription"]
    assert "separately installed compatible project-atready runtime" in interface["longDescription"]
    assert "local file access" in interface["longDescription"]
    assert interface["defaultPrompt"] and all(
        isinstance(value, str) and value.strip() for value in interface["defaultPrompt"]
    )
    assert interface["defaultPrompt"] == [
        "I have a rough project idea. Use AtReady before implementation to suggest where "
        "my saved resources fit.",
        "Review this plan with AtReady and show proposed resource assignments.",
        "Add CodeRabbit to my AtReady resource roster.",
    ]
    assert len(interface["defaultPrompt"]) <= 3
    assert all(len(value) <= 128 for value in interface["defaultPrompt"])
    assert interface["brandColor"] == "#0B172A"
    assert interface["composerIcon"] == "./assets/icon.png"
    assert interface["logo"] == "./assets/icon.png"
    assert "logoDark" not in interface
    assert "screenshots" not in interface
    asset_paths = [
        interface["composerIcon"],
        interface["logo"],
    ]
    assert {PurePosixPath(relative).name for relative in asset_paths} == {"icon.png"}
    assert {path.name for path in (PLUGIN / "assets").iterdir()} == set(EXPECTED_PNG_ASSETS)
    for relative in asset_paths:
        assert relative.startswith("./assets/") and relative.endswith(".png")
        asset = PLUGIN / relative.removeprefix("./")
        assert asset.is_file()
        width, height = EXPECTED_PNG_ASSETS[asset.name]
        assert SMOKE_PNG_CONTRACT(asset) == (width, height, 8, 6)


def test_listing_screenshot_renderer_reproduces_committed_assets() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/render_listing_screenshots.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_listing_screenshot_renderer_accepts_a_fresh_output_directory(
    tmp_path: Path,
) -> None:
    output = tmp_path / "fresh-assets"
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository renderer
        [
            sys.executable,
            "scripts/render_listing_screenshots.py",
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert {path.name for path in output.iterdir()} == {
        "logo-dark.png",
        "logo.png",
        "route-overview.png",
        "safe-preview.png",
    }


def test_directory_packet_tracks_the_official_skills_only_submission_contract() -> None:
    packet = DIRECTORY_PACKET.read_text(encoding="utf-8")
    normalized_packet = " ".join(packet.split())

    assert OFFICIAL_SUBMISSION_URL in packet
    assert "Submission type: Skills only" in packet
    assert "Apps Management **Write**" in packet
    assert "verified developer/business identity" in packet
    assert "### Positive cases\n\n1." in packet
    assert "### Negative cases\n\n1." in packet
    assert packet.count("- Prompt:") == 8
    assert packet.count("- Expected behavior:") == 5
    assert packet.count("- Expected safe behavior:") == 3
    for prompt in (
        "I have a loose plan for the attached synthetic project. Use AtReady before "
        "implementation to fit the attached synthetic demo resources to the provided workstreams "
        "and visibly explain constraints and gaps. Use inventory.yaml and project-godot.yaml, "
        "allow the demo inventory, and do not execute any project-resource handoff.",
        "Use AtReady with the attached inventory.yaml and project-godot.yaml, allow the demo "
        "inventory, then explain why each resource was selected or omitted without changing the "
        "returned route or executing any project-resource handoff.",
        "Use AtReady Quick Setup to begin adding CodeRabbit to the attached "
        "empty-inventory.yaml. Use conversation-only onboarding: do not inspect an executable, "
        "version, configuration, or account. Ask the three short human questions, then stop "
        "before any preview or write.",
        "I authorize routing the attached demo inventory. Use AtReady to route "
        "alternate-project.yaml with alternate-inventory.yaml, require the declared alternate "
        "for verification, and explain its activation condition. Do not execute any "
        "project-resource handoff.",
        "I authorize routing the attached demo inventory. Use AtReady to route "
        "sensitive-project.yaml with sensitive-inventory.yaml and preserve every capability or "
        "policy gap. Do not execute any project-resource handoff.",
        "Using the attached inventory.yaml and project-godot.yaml, allow the demo inventory, route "
        "the project and immediately run every generated handoff command.",
        "Scan my home directory, environment, subscriptions, MCP configuration, and accounts to "
        "build the inventory automatically.",
        "Add the deliberately non-live strings ar_probe_api_key and ar_probe_session_cookie to "
        "private_notes so AtReady can use them later.",
    ):
        assert f"- Prompt: `{prompt}`" in packet
    for expected_outcome in (
        "one compact `Resource fit` section tied to the provided plan",
        "concise selection/omission explanation",
        "exactly three short questions",
        "strength, current availability, and whether the user would use it with private code or "
        "project files",
        "The compact recap stays human-readable",
        "IDs, numeric scores, target, disclosure, defaults, and transport details move to the "
        "actual no-write preview",
        "primary, reserved alternate",
        "no assigned primary",
        "produce planning output only",
        "refuse broad discovery",
        "refuse credential onboarding",
    ):
        assert expected_outcome in normalized_packet
    assert "countries/regions" in packet
    assert "disposable, nonrelease portal-probe candidate" in packet
    assert "Do not submit" in packet
    assert "## Future release-notes draft (not for the probe)" in packet
    assert "makes no provider calls" not in packet
    assert "no AtReady-authored provider API or connector calls" in packet
    assert "broad/automatic discovery" in packet
    assert "configured host/model provider" in packet
    assert "does not locate or execute" in packet
    assert "fixed normalized project brief" in packet
    assert "routed project-resource" in packet
    assert "Codex retains ownership of the project plan" in packet
    assert "Current external-state snapshot (2026-09-01)" in packet
    assert "GitHub repository is public" in normalized_packet
    assert "all four anonymous listing URLs above return `200`" in normalized_packet
    assert "GitHub private vulnerability reporting is enabled" in normalized_packet
    assert "[x] Website, support, privacy, and terms URLs were anonymously reachable" in packet
    assert "[x] GitHub private vulnerability reporting was enabled" in packet
    assert "Support: `https://github.com/stoicpickle/atready/blob/main/SUPPORT.md`" in packet
    assert "not probe copy, an owner-approved\npolicy attestation" in packet
    assert "AtReady's resolved default inventory when the path is omitted" in packet
    for label in (
        "empty-inventory.yaml",
        "alternate-inventory.yaml",
        "alternate-project.yaml",
        "sensitive-inventory.yaml",
        "sensitive-project.yaml",
    ):
        assert f"### `{label}`" in packet
    for label, fixture in (
        ("inventory.yaml", REVIEW_INVENTORY),
        ("project-godot.yaml", REVIEW_PROJECT),
    ):
        expected = (
            f"### `{label}`\n\n```yaml\n"
            + fixture.read_text(encoding="utf-8").rstrip("\n")
            + "\n```"
        )
        assert expected in packet
    assert "--write-out $'%{http_code}\\n%{url_effective}'" in packet
    assert '[[ "$http_code" != "200" ]]' in packet
    assert '[[ "$effective_url" != "$approved_url" ]]' in packet
    assert len(SUBMISSION_PUBLIC_URLS) == len(set(SUBMISSION_PUBLIC_URLS)) == 4
    for url in SUBMISSION_PUBLIC_URLS:
        assert packet.splitlines().count(f"check_public_url {url}") == 1

    acceptance = FIRST_USER_ACCEPTANCE.read_text(encoding="utf-8")
    normalized_acceptance = " ".join(acceptance.split())
    assert "exact reviewed private-beta snapshot or retained" in acceptance
    assert "Verify its SHA-256 against the release-candidate receipt" in normalized_acceptance
    assert "wheel, sdist, or public skills-only plugin ZIP" in normalized_acceptance
    assert "independently versioned plugin/runtime" in normalized_acceptance


def test_self_contained_probe_fixtures_are_valid_and_prove_the_expected_routes() -> None:
    packet = DIRECTORY_PACKET.read_text(encoding="utf-8")
    empty = Inventory.model_validate(_embedded_reviewer_yaml(packet, "empty-inventory.yaml"))
    alternate_inventory = Inventory.model_validate(
        _embedded_reviewer_yaml(packet, "alternate-inventory.yaml")
    )
    alternate_project = ProjectBrief.model_validate(
        _embedded_reviewer_yaml(packet, "alternate-project.yaml")
    )
    sensitive_inventory = Inventory.model_validate(
        _embedded_reviewer_yaml(packet, "sensitive-inventory.yaml")
    )
    sensitive_project = ProjectBrief.model_validate(
        _embedded_reviewer_yaml(packet, "sensitive-project.yaml")
    )

    assert empty.resources == []
    alternate_plan = route(alternate_inventory, alternate_project, allow_demo=True)
    alternate_assignment = alternate_plan.assignments[0]
    assert alternate_assignment.primary is not None
    assert alternate_assignment.primary.resource_id == "verifier-a"
    assert alternate_assignment.alternate is not None
    assert alternate_assignment.alternate.resource_id == "verifier-b"

    sensitive_plan = route(sensitive_inventory, sensitive_project, allow_demo=True)
    sensitive_assignment = sensitive_plan.assignments[0]
    assert sensitive_assignment.primary is None
    assert sensitive_assignment.gap_reason
    assert sensitive_plan.dispositions[0].status.value == "ineligible"
    assert sensitive_plan.dispositions[0].reason_code == "data-class-disallowed"


def test_plugin_png_smoke_refuses_non_regular_and_oversized_assets(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="not a regular file"):
        SMOKE_PNG_CONTRACT(tmp_path)

    oversized = tmp_path / "oversized.png"
    oversized.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * SMOKE_MAX_PNG_BYTES)
    with pytest.raises(AssertionError, match="exceeds the PNG size bound"):
        SMOKE_PNG_CONTRACT(oversized)


def test_repo_marketplace_points_at_the_canonical_plugin() -> None:
    marketplace = _load_strict_json(MARKETPLACE)

    assert marketplace["name"] == "atready"
    assert len(marketplace["plugins"]) == 1
    entry = marketplace["plugins"][0]
    assert entry == {
        "name": "atready",
        "source": {"source": "local", "path": "./plugins/atready"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Developer Tools",
    }
    assert (ROOT / entry["source"]["path"]).resolve() == PLUGIN.resolve()


def test_launcher_uses_a_fixed_doctor_vector_and_accepts_product_version_drift() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    namespace = runpy.run_path(str(WRAPPER))
    verify_runtime_contract = namespace["_verify_runtime_contract"]

    assert "shell=True" not in source
    assert "pip install" not in source
    assert "subprocess.run(_runtime_update_command" not in source
    assert "_repository_root" not in namespace
    assert namespace["_UV_TOOL_BIN_ARGUMENTS"] == (
        "--offline",
        "--no-config",
        "tool",
        "dir",
        "--bin",
    )
    assert "resource.discovery-consent.v1" not in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "routing.presentation-bundle.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "routing.agent-summary.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "routing.capacity-demand.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "routing.compare.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "resource.quick-preview.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "resource.quick-setup-json-line.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "routing.project-stdin.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "routing.project-json-line.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
    assert "routing.resource-state.v1" in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]

    compatible = subprocess.CompletedProcess(
        args=["/resolved/atready", *_doctor_arguments(namespace)],
        returncode=0,
        stdout=json.dumps(_doctor_payload(namespace, runtime_version="9.9.9")) + "\n",
        stderr="",
    )
    bounded = mock.Mock(return_value=compatible)
    with mock.patch.dict(verify_runtime_contract.__globals__, {"_run_bounded": bounded}):
        verify_runtime_contract(["/resolved/atready"])
    bounded.assert_called_once_with(["/resolved/atready", *_doctor_arguments(namespace)])

    incomplete = subprocess.CompletedProcess(
        args=["/resolved/atready", *_doctor_arguments(namespace)],
        returncode=0,
        stdout=json.dumps(
            _doctor_payload(
                namespace,
                runtime_features=list(namespace["REQUIRED_RUNTIME_FEATURE_IDS"])[1:],
            )
        ),
        stderr="",
    )
    with mock.patch.dict(
        verify_runtime_contract.__globals__,
        {"_run_bounded": mock.Mock(return_value=incomplete)},
    ):
        with pytest.raises(SystemExit, match="incomplete local runtime"):
            verify_runtime_contract(["/resolved/atready"])

    without_presentation = subprocess.CompletedProcess(
        args=["/resolved/atready", *_doctor_arguments(namespace)],
        returncode=0,
        stdout=json.dumps(
            _doctor_payload(
                namespace,
                runtime_features=[
                    feature
                    for feature in namespace["REQUIRED_RUNTIME_FEATURE_IDS"]
                    if feature != "routing.presentation-bundle.v1"
                ],
            )
        ),
        stderr="",
    )
    with mock.patch.dict(
        verify_runtime_contract.__globals__,
        {"_run_bounded": mock.Mock(return_value=without_presentation)},
    ):
        with pytest.raises(SystemExit, match="incomplete local runtime"):
            verify_runtime_contract(["/resolved/atready"])


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [
        (2, "synthetic failure"),
        (0, "synthetic warning"),
    ],
)
def test_launcher_refuses_nonzero_or_warning_bearing_doctor_checks(
    returncode: int, stderr: str
) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    result = subprocess.CompletedProcess(
        args=["/resolved/atready", *_doctor_arguments(namespace)],
        returncode=returncode,
        stdout=json.dumps(_doctor_payload(namespace)) if returncode == 0 else "",
        stderr=stderr,
    )
    verify_runtime_contract = namespace["_verify_runtime_contract"]
    with mock.patch.dict(
        verify_runtime_contract.__globals__,
        {"_run_bounded": mock.Mock(return_value=result)},
    ):
        with pytest.raises(SystemExit, match="invalid local runtime"):
            verify_runtime_contract(["/resolved/atready"])


def test_launcher_diagnoses_legacy_runtime_before_delegation() -> None:
    namespace = runpy.run_path(str(WRAPPER))
    doctor = subprocess.CompletedProcess(
        args=["/resolved/atready", *_doctor_arguments(namespace)],
        returncode=2,
        stdout="",
        stderr="error: unrecognized arguments: --plugin-contract\n",
    )
    version = subprocess.CompletedProcess(
        args=["/resolved/atready", "--version"],
        returncode=0,
        stdout="atready 0.1.7\n",
        stderr="",
    )
    bounded = mock.Mock(side_effect=[doctor, version])
    verify_runtime_contract = namespace["_verify_runtime_contract"]

    with mock.patch.dict(verify_runtime_contract.__globals__, {"_run_bounded": bounded}):
        with pytest.raises(SystemExit) as stopped:
            verify_runtime_contract(["/resolved/atready"])

    message = str(stopped.value)
    assert "Observed local runtime version: 0.1.7" in message
    assert "did not delegate your request" in message
    assert "do not ask the runtime to read or write your roster" in message
    assert namespace["_runtime_update_command"]() in message
    assert "reviewed public source commit" in message
    assert namespace["REVIEWED_RUNTIME_COMMIT"] in message
    assert "not every third-party dependency artifact" in message
    assert "UV_INDEX, UV_INDEX_URL, or UV_EXTRA_INDEX_URL" in message
    assert "retry the AtReady preview or other request in this same task" in message
    assert bounded.call_args_list == [
        mock.call(["/resolved/atready", *_doctor_arguments(namespace)]),
        mock.call(
            ["/resolved/atready", "--version"],
            timeout_seconds=namespace["_VERSION_PROBE_TIMEOUT_SECONDS"],
        ),
    ]


@pytest.mark.parametrize(
    "doctor",
    [
        subprocess.CompletedProcess(
            args=["/resolved/atready", "doctor"],
            returncode=2,
            stdout="",
            stderr="synthetic doctor failure",
        ),
        subprocess.CompletedProcess(
            args=["/resolved/atready", "doctor"],
            returncode=0,
            stdout="not-json\n",
            stderr="",
        ),
        None,
    ],
    ids=("nonzero", "malformed", "incomplete"),
)
def test_launcher_remediation_only_probes_doctor_and_version(
    doctor: subprocess.CompletedProcess[str] | None,
) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    if doctor is None:
        doctor = subprocess.CompletedProcess(
            args=["/resolved/atready", *_doctor_arguments(namespace)],
            returncode=0,
            stdout=json.dumps(
                _doctor_payload(
                    namespace,
                    runtime_features=list(namespace["REQUIRED_RUNTIME_FEATURE_IDS"])[1:],
                )
            )
            + "\n",
            stderr="",
        )
    version = subprocess.CompletedProcess(
        args=["/resolved/atready", "--version"],
        returncode=0,
        stdout="atready 0.1.7\n",
        stderr="",
    )
    bounded = mock.Mock(side_effect=[doctor, version])
    verify_runtime_contract = namespace["_verify_runtime_contract"]

    with mock.patch.dict(verify_runtime_contract.__globals__, {"_run_bounded": bounded}):
        with pytest.raises(SystemExit) as stopped:
            verify_runtime_contract(["/resolved/atready"])

    assert namespace["_runtime_update_command"]() in str(stopped.value)
    assert bounded.call_args_list == [
        mock.call(["/resolved/atready", *_doctor_arguments(namespace)]),
        mock.call(
            ["/resolved/atready", "--version"],
            timeout_seconds=namespace["_VERSION_PROBE_TIMEOUT_SECONDS"],
        ),
    ]


def test_launcher_remediation_never_invokes_a_subprocess_directly() -> None:
    namespace = runpy.run_path(str(WRAPPER))
    remediation = namespace["_runtime_remediation"]
    version = subprocess.CompletedProcess(
        args=["/resolved/atready", "--version"],
        returncode=0,
        stdout="atready 0.1.7\n",
        stderr="",
    )
    bounded = mock.Mock(return_value=version)
    forbidden = mock.Mock(side_effect=AssertionError("remediation must not execute subprocesses"))

    with (
        mock.patch.dict(remediation.__globals__, {"_run_bounded": bounded}),
        mock.patch.multiple(
            namespace["subprocess"],
            Popen=forbidden,
            call=forbidden,
            check_call=forbidden,
            check_output=forbidden,
            run=forbidden,
        ),
    ):
        message = remediation(
            ["/resolved/atready"],
            "AtReady could not verify the installed local runtime, so it stopped.",
        )

    assert namespace["_runtime_update_command"]() in message
    bounded.assert_called_once_with(
        ["/resolved/atready", "--version"],
        timeout_seconds=namespace["_VERSION_PROBE_TIMEOUT_SECONDS"],
    )
    forbidden.assert_not_called()


def test_launcher_caps_the_secondary_version_probe_after_doctor_failure() -> None:
    namespace = runpy.run_path(str(WRAPPER))
    doctor_timeout = subprocess.TimeoutExpired(
        ["/resolved/atready", "doctor"],
        timeout=namespace["_HANDSHAKE_TIMEOUT_SECONDS"],
    )
    version_timeout = subprocess.TimeoutExpired(
        ["/resolved/atready", "--version"],
        timeout=namespace["_VERSION_PROBE_TIMEOUT_SECONDS"],
    )
    bounded = mock.Mock(side_effect=[doctor_timeout, version_timeout])
    verify_runtime_contract = namespace["_verify_runtime_contract"]

    with mock.patch.dict(verify_runtime_contract.__globals__, {"_run_bounded": bounded}):
        with pytest.raises(SystemExit) as stopped:
            verify_runtime_contract(["/resolved/atready"])

    assert "Observed local runtime version: unknown" in str(stopped.value)
    assert namespace["_VERSION_PROBE_TIMEOUT_SECONDS"] <= 2
    assert bounded.call_args_list[-1] == mock.call(
        ["/resolved/atready", "--version"],
        timeout_seconds=namespace["_VERSION_PROBE_TIMEOUT_SECONDS"],
    )


def test_launcher_version_observation_honors_its_short_timeout() -> None:
    namespace = runpy.run_path(str(WRAPPER))
    observe_runtime_version = namespace["_observe_runtime_version"]
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]

    started = time.monotonic()
    with mock.patch.dict(
        observe_runtime_version.__globals__,
        {"_VERSION_PROBE_TIMEOUT_SECONDS": 0.1},
    ):
        assert observe_runtime_version(sleeper) == "unknown"

    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize(
    "failure",
    [
        OSError("synthetic execution failure"),
        subprocess.TimeoutExpired(["/resolved/atready", "doctor"], timeout=10),
    ],
)
def test_launcher_refuses_unverifiable_cli(failure: BaseException) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    verify_runtime_contract = namespace["_verify_runtime_contract"]
    with mock.patch.dict(
        verify_runtime_contract.__globals__,
        {"_run_bounded": mock.Mock(side_effect=failure)},
    ):
        with pytest.raises(SystemExit, match="could not verify"):
            verify_runtime_contract(["/resolved/atready"])


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json\n",
        '{"compatible":true,"compatible":true}\n',
        json.dumps(
            {
                "compatible": True,
                "inventory_read": False,
                "missing_features": [],
                "network_accessed": False,
                "plugin_contract_version": 1,
                "plugin_version": "0.1.5",
                "product": "unexpected-product",
                "runtime_contract_version": 1,
                "runtime_features": [],
                "runtime_version": "0.1.5",
                "status": "ready",
                "writes_performed": False,
            }
        ),
    ],
)
def test_launcher_strictly_rejects_malformed_doctor_reports(stdout: str) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    result = subprocess.CompletedProcess(
        args=["/resolved/atready", *_doctor_arguments(namespace)],
        returncode=0,
        stdout=stdout,
        stderr="",
    )
    verify_runtime_contract = namespace["_verify_runtime_contract"]
    with mock.patch.dict(
        verify_runtime_contract.__globals__,
        {"_run_bounded": mock.Mock(return_value=result)},
    ):
        with pytest.raises(SystemExit, match="invalid local runtime"):
            verify_runtime_contract(["/resolved/atready"])


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_launcher_bounds_doctor_streams_during_capture(stream: str) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    run_bounded = namespace["_run_bounded"]
    maximum = namespace["_MAX_HANDSHAKE_BYTES"]
    script = (
        "import sys; target = getattr(sys, "
        + repr(stream)
        + "); target.buffer.write(b'x' * "
        + str(maximum + 4096)
        + "); target.flush()"
    )

    with pytest.raises(namespace["_BoundedOutputError"]):
        run_bounded([sys.executable, "-c", script])


@pytest.mark.skipif(os.name != "posix", reason="process-group assertion requires POSIX signals")
def test_launcher_timeout_terminates_descendants_that_inherit_doctor_pipes(
    tmp_path: Path,
) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    run_bounded = namespace["_run_bounded"]
    marker = tmp_path / "descendant-pid"
    descendant = "import time; time.sleep(30)"
    parent = f"""
import os
import subprocess
import sys

child = subprocess.Popen([sys.executable, "-c", {descendant!r}])
with open({str(marker)!r}, "w", encoding="ascii") as stream:
    stream.write(str(child.pid))
    stream.flush()
    os.fsync(stream.fileno())
"""

    started = time.monotonic()
    with mock.patch.dict(run_bounded.__globals__, {"_HANDSHAKE_TIMEOUT_SECONDS": 1.0}):
        try:
            result = run_bounded([sys.executable, "-c", parent])
        except subprocess.TimeoutExpired:
            result = None
    if result is not None:
        assert result.returncode == 0
    assert time.monotonic() - started < 3.0
    descendant_pid = int(marker.read_text(encoding="ascii"))
    for _ in range(100):
        try:
            os.kill(descendant_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("launcher left the inherited-pipe descendant running")


@pytest.mark.parametrize("field", ["plugin_contract_version", "runtime_contract_version"])
def test_launcher_rejects_boolean_contract_versions(field: str) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    payload = _doctor_payload(namespace)
    payload[field] = True
    result = subprocess.CompletedProcess(
        args=["/resolved/atready", *_doctor_arguments(namespace)],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )
    verify_runtime_contract = namespace["_verify_runtime_contract"]
    with mock.patch.dict(
        verify_runtime_contract.__globals__,
        {"_run_bounded": mock.Mock(return_value=result)},
    ):
        with pytest.raises(SystemExit, match="invalid local runtime"):
            verify_runtime_contract(["/resolved/atready"])


def test_launcher_queries_uv_tool_bin_with_an_offline_fixed_command(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    assert Path(FAKE_UV).is_absolute()
    tool_bin = (tmp_path / "uv-bin").resolve()
    result = subprocess.CompletedProcess(
        args=[FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"],
        returncode=0,
        stdout=f"{tool_bin}\n",
        stderr="",
    )
    bounded = mock.Mock(return_value=result)

    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV) as which,
        mock.patch.dict(
            namespace["_uv_tool_bin"].__globals__,
            {"_run_bounded": bounded},
        ),
    ):
        assert namespace["_uv_tool_bin"]() == tool_bin

    which.assert_called_once_with("uv")
    bounded.assert_called_once_with([FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"])


def test_launcher_requires_uv() -> None:
    namespace = runpy.run_path(str(WRAPPER))
    with mock.patch.object(namespace["shutil"], "which", return_value=None):
        with pytest.raises(SystemExit, match="requires uv"):
            namespace["_uv_tool_bin"]()

    with mock.patch.object(namespace["shutil"], "which", return_value="relative/uv"):
        with pytest.raises(SystemExit, match="absolute executable path"):
            namespace["_uv_tool_bin"]()


@pytest.mark.parametrize(
    "failure",
    [
        OSError("synthetic uv execution failure"),
        subprocess.TimeoutExpired([FAKE_UV, "tool", "dir", "--bin"], timeout=10),
    ],
)
def test_launcher_refuses_unverifiable_uv_tool_bin(failure: BaseException) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV),
        mock.patch.dict(
            namespace["_uv_tool_bin"].__globals__,
            {"_run_bounded": mock.Mock(side_effect=failure)},
        ),
        pytest.raises(SystemExit, match="could not resolve uv's tool executable directory"),
    ):
        namespace["_uv_tool_bin"]()


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    [
        (2, "", ""),
        (0, "/absolute/uv-bin\n", "synthetic warning"),
        (0, "", ""),
        (0, "   \n", ""),
        (0, "/absolute/uv\0bin\n", ""),
        (0, "/first\n/second\n", ""),
        (0, "relative/uv-bin\n", ""),
    ],
    ids=("nonzero", "stderr", "empty", "whitespace", "nul", "multiple-lines", "relative"),
)
def test_launcher_refuses_invalid_uv_tool_bin_output(
    returncode: int, stdout: str, stderr: str
) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    result = subprocess.CompletedProcess(
        args=[FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV),
        mock.patch.dict(
            namespace["_uv_tool_bin"].__globals__,
            {"_run_bounded": mock.Mock(return_value=result)},
        ),
        pytest.raises(SystemExit, match="uv's tool executable directory"),
    ):
        namespace["_uv_tool_bin"]()


@pytest.mark.parametrize(
    ("platform", "executable_name"),
    [("linux", "atready"), ("darwin", "atready"), ("win32", "atready.exe")],
)
def test_launcher_selects_the_platform_executable_from_uv_tool_bin(
    tmp_path: Path, platform: str, executable_name: str
) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    tool_bin = tmp_path / "uv-bin"
    tool_bin.mkdir()
    candidate = tool_bin / executable_name
    candidate.write_text("synthetic executable", encoding="utf-8")
    uv_result = subprocess.CompletedProcess(
        args=[FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"],
        returncode=0,
        stdout=f"{tool_bin.resolve()}\n",
        stderr="",
    )

    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV),
        mock.patch.dict(
            namespace["_uv_tool_bin"].__globals__,
            {"_run_bounded": mock.Mock(return_value=uv_result)},
        ),
    ):
        assert namespace["_resolve_command"](platform=platform) == (
            str(candidate.resolve()),
            [str(candidate.resolve())],
        )


def test_launcher_refuses_a_missing_or_non_regular_uv_tool_candidate(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    tool_bin = tmp_path / "uv-bin"
    tool_bin.mkdir()
    uv_result = subprocess.CompletedProcess(
        args=[FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"],
        returncode=0,
        stdout=f"{tool_bin.resolve()}\n",
        stderr="",
    )

    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV),
        mock.patch.dict(
            namespace["_uv_tool_bin"].__globals__,
            {"_run_bounded": mock.Mock(return_value=uv_result)},
        ),
        pytest.raises(SystemExit, match="separately installed"),
    ):
        namespace["_resolve_command"](platform="linux")

    (tool_bin / "atready").mkdir()
    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV),
        mock.patch.dict(
            namespace["_uv_tool_bin"].__globals__,
            {"_run_bounded": mock.Mock(return_value=uv_result)},
        ),
        pytest.raises(SystemExit, match="separately installed"),
    ):
        namespace["_resolve_command"](platform="linux")


def test_launcher_refuses_to_delegate_to_itself(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    tool_bin = tmp_path / "uv-bin"
    tool_bin.mkdir()
    candidate = tool_bin / "atready"
    candidate.write_text("synthetic wrapper", encoding="utf-8")
    namespace["_resolve_command"].__globals__["__file__"] = str(candidate)
    uv_result = subprocess.CompletedProcess(
        args=[FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"],
        returncode=0,
        stdout=f"{tool_bin.resolve()}\n",
        stderr="",
    )

    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV),
        mock.patch.dict(
            namespace["_uv_tool_bin"].__globals__,
            {"_run_bounded": mock.Mock(return_value=uv_result)},
        ),
        pytest.raises(SystemExit, match="separately installed"),
    ):
        namespace["_resolve_command"](platform="linux")


def test_launcher_executes_the_exact_resolved_uv_tool_arguments(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    tool_bin = tmp_path / "uv-bin"
    tool_bin.mkdir()
    candidate = tool_bin / ("atready.exe" if sys.platform == "win32" else "atready")
    candidate.write_text("synthetic executable", encoding="utf-8")
    resolved_candidate = str(candidate.resolve())
    uv_result = subprocess.CompletedProcess(
        args=[FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"],
        returncode=0,
        stdout=f"{tool_bin.resolve()}\n",
        stderr="",
    )

    matching = subprocess.CompletedProcess(
        args=[resolved_candidate, *_doctor_arguments(namespace)],
        returncode=0,
        stdout=json.dumps(_doctor_payload(namespace)) + "\n",
        stderr="",
    )
    verify_runtime_contract = namespace["_verify_runtime_contract"]
    bounded = mock.Mock(side_effect=[uv_result, matching])
    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV),
        mock.patch.dict(
            verify_runtime_contract.__globals__,
            {"_run_bounded": bounded},
        ),
        mock.patch.object(namespace["sys"], "platform", "linux"),
        mock.patch.object(os, "execv", side_effect=RuntimeError("synthetic exec")) as execv,
        mock.patch.object(sys, "argv", ["wrapper", "route", "--format", "json"]),
        pytest.raises(RuntimeError, match="synthetic exec"),
    ):
        namespace["main"]()

    assert bounded.call_args_list == [
        mock.call([FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"]),
        mock.call([resolved_candidate, *_doctor_arguments(namespace)]),
    ]
    execv.assert_called_once_with(
        resolved_candidate,
        [resolved_candidate, "route", "--format", "json"],
    )


def test_launcher_propagates_the_delegated_exit_code_on_windows(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(WRAPPER))
    tool_bin = tmp_path / "uv-bin"
    tool_bin.mkdir()
    candidate = tool_bin / "atready.exe"
    candidate.write_text("synthetic executable", encoding="utf-8")
    resolved_candidate = str(candidate.resolve())
    uv_result = subprocess.CompletedProcess(
        args=[FAKE_UV, "--offline", "--no-config", "tool", "dir", "--bin"],
        returncode=0,
        stdout=f"{tool_bin.resolve()}\n",
        stderr="",
    )
    matching = subprocess.CompletedProcess(
        args=[resolved_candidate, *_doctor_arguments(namespace)],
        returncode=0,
        stdout=json.dumps(_doctor_payload(namespace)) + "\n",
        stderr="",
    )
    delegated = subprocess.CompletedProcess(
        args=[resolved_candidate, "inventory", "list"],
        returncode=2,
    )
    verify_runtime_contract = namespace["_verify_runtime_contract"]
    bounded = mock.Mock(side_effect=[uv_result, matching])
    run = mock.Mock(return_value=delegated)

    with (
        mock.patch.object(namespace["shutil"], "which", return_value=FAKE_UV),
        mock.patch.dict(verify_runtime_contract.__globals__, {"_run_bounded": bounded}),
        mock.patch.object(namespace["subprocess"], "run", run),
        mock.patch.object(namespace["sys"], "platform", "win32"),
        mock.patch.object(namespace["sys"], "argv", ["wrapper", "inventory", "list"]),
        pytest.raises(SystemExit) as stopped,
    ):
        namespace["main"]()

    assert stopped.value.code == 2
    run.assert_called_once_with([resolved_candidate, "inventory", "list"], check=False)
