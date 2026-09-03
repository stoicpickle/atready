from __future__ import annotations

import hashlib
import json
import re
import runpy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
VALIDATOR_NAMESPACE = runpy.run_path(str(ROOT / "scripts" / "validate_plugin_contract.py"))
validate = VALIDATOR_NAMESPACE["validate"]


def _write_candidate(tmp_path: Path, products: object) -> Path:
    plugin = tmp_path / "plugin"
    agent = plugin / "skills" / "project-atready" / "agents" / "openai.yaml"
    agent.parent.mkdir(parents=True)
    agent.write_text(
        yaml.safe_dump(
            {
                "interface": {
                    "display_name": "AtReady",
                    "short_description": "Plan with saved resources",
                },
                "policy": {
                    "allow_implicit_invocation": False,
                    "products": products,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return plugin


def _write_upstream(tmp_path: Path, errors: list[str]) -> Path:
    return _write_upstream_source(
        tmp_path,
        f"def validate_plugin(plugin_root):\n    return {errors!r}\n",
    )


def _write_upstream_source(tmp_path: Path, source: str) -> Path:
    system_skills = tmp_path / "system-skills"
    validator = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"
    validator.parent.mkdir(parents=True)
    validator.write_text(source, encoding="utf-8")
    return system_skills


def _write_support_manifest(plugin: Path, support_url: object) -> None:
    manifest = plugin / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"interface": {"supportURL": support_url}}),
        encoding="utf-8",
    )


def _validate(plugin: Path, system_skills: Path) -> list[str]:
    upstream = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"
    return validate(
        plugin,
        system_skills,
        trusted_upstream_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
    )


def test_current_products_field_can_bridge_one_legacy_validator_error(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    system_skills = _write_upstream(
        tmp_path,
        [
            "skill `project-atready` agent field `policy.products` is not accepted by plugin "
            "validation"
        ],
    )

    errors = _validate(plugin, system_skills)

    assert errors == []


def test_current_support_url_can_bridge_one_reviewed_validator_error(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    _write_support_manifest(plugin, "https://github.com/stoicpickle/atready/blob/main/SUPPORT.md")
    system_skills = _write_upstream(
        tmp_path,
        ["plugin.json field `interface.supportURL` is not accepted by plugin validation"],
    )

    errors = _validate(plugin, system_skills)

    assert errors == []


@pytest.mark.parametrize(
    "support_url",
    [
        "http://example.com/support",
        "https://user:password@example.com/support",
        "https://example.com/\ncontrol",
        "x" * 1_025,
        42,
    ],
)
def test_invalid_support_url_is_rejected_before_legacy_compatibility(
    tmp_path: Path, support_url: object
) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    _write_support_manifest(plugin, support_url)
    marker = tmp_path / "validator-ran"
    system_skills = _write_upstream_source(
        tmp_path,
        "from pathlib import Path\n"
        "def validate_plugin(plugin_root):\n"
        f"    Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
        "    return []\n",
    )

    errors = _validate(plugin, system_skills)

    assert errors == ["interface.supportURL must be an HTTPS URL of at most 1024 characters"]
    assert not marker.exists()


def test_production_validator_digest_is_bound_to_an_immutable_official_artifact() -> None:
    assert VALIDATOR_NAMESPACE["OFFICIAL_REFERENCE"] == (
        "https://raw.githubusercontent.com/openai/codex/"
        "5ee6baee2fcc0b6ffd413d9611f5538dad40d0f2/"
        "codex-rs/skills/src/assets/samples/plugin-creator/scripts/validate_plugin.py"
    )
    assert VALIDATOR_NAMESPACE["TRUSTED_UPSTREAM_VALIDATOR_SHA256"] == (
        "6ff4bc1cc8ca94827c30c8299951efdac900ff38a5069c03e9a6554fc194a723"
    )
    assert VALIDATOR_NAMESPACE["OFFICIAL_IDENTIFIER_REFERENCE"] == (
        "https://raw.githubusercontent.com/openai/codex/"
        "5ee6baee2fcc0b6ffd413d9611f5538dad40d0f2/"
        "codex-rs/skills/src/assets/samples/plugin-creator/scripts/identifier_validation.py"
    )
    assert VALIDATOR_NAMESPACE["TRUSTED_IDENTIFIER_VALIDATION_SHA256"] == (
        "a6d51ce4a9a7e8f85626ff5808a467a67574e7f8cdf1167ffb467c5f67e57223"
    )


def test_validate_uses_the_production_digest_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    system_skills = _write_upstream(tmp_path, [])
    upstream = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"
    fixture_digest = hashlib.sha256(upstream.read_bytes()).hexdigest()
    monkeypatch.setitem(validate.__globals__, "TRUSTED_UPSTREAM_VALIDATOR_SHA256", fixture_digest)

    errors = validate(plugin, system_skills)

    assert errors == []
    upstream.write_text(
        "def validate_plugin(plugin_root):\n    return ['changed']\n", encoding="utf-8"
    )
    assert validate(plugin, system_skills) == [
        "OpenAI plugin validator does not match the repository's reviewed SHA-256"
    ]


def test_matching_reviewed_digest_is_accepted(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    system_skills = _write_upstream(tmp_path, [])
    upstream = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"

    errors = validate(
        plugin,
        system_skills,
        trusted_upstream_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
    )

    assert errors == []


def test_invalid_products_are_rejected_before_legacy_compatibility(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX", "UNKNOWN"])
    system_skills = _write_upstream(tmp_path, [])

    errors = _validate(plugin, system_skills)

    assert errors == ["skill `project-atready` policy.products must contain CHAT, CODEX, or both"]


def test_unrelated_upstream_errors_are_never_forgiven(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    system_skills = _write_upstream(
        tmp_path,
        [
            "skill `project-atready` agent field `policy.products` is not accepted by plugin "
            "validation",
            "plugin.json field `version` must be strict semver",
        ],
    )

    errors = _validate(plugin, system_skills)

    assert errors == ["plugin.json field `version` must be strict semver"]


def test_unreviewed_upstream_validator_is_rejected_before_execution(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    marker = tmp_path / "imported-marker"
    system_skills = _write_upstream_source(
        tmp_path,
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "def validate_plugin(plugin_root):\n    return []\n",
    )

    errors = validate(plugin, system_skills, trusted_upstream_sha256="0" * 64)

    assert errors == ["OpenAI plugin validator does not match the repository's reviewed SHA-256"]
    assert not marker.exists()


def test_symlinked_upstream_validator_is_rejected_before_resolution(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    system_skills = _write_upstream_source(
        tmp_path,
        "def validate_plugin(plugin_root):\n    return []\n",
    )
    scripts = system_skills / "plugin-creator" / "scripts"
    upstream = scripts / "validate_plugin.py"
    reviewed = scripts / "reviewed-validator.py"
    reviewed.write_bytes(upstream.read_bytes())
    upstream.unlink()
    upstream.symlink_to(reviewed)

    errors = validate(
        plugin,
        system_skills,
        trusted_upstream_sha256=hashlib.sha256(reviewed.read_bytes()).hexdigest(),
    )

    assert errors == [f"OpenAI plugin validator not found at {upstream}"]


def test_unreviewed_upstream_dependency_is_rejected_before_execution(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    marker = tmp_path / "dependency-marker"
    source = (
        "from identifier_validation import validate_plugin_identifier\n"
        "def validate_plugin(plugin_root):\n"
        "    validate_plugin_identifier('atready')\n"
        "    return []\n"
    )
    system_skills = _write_upstream_source(tmp_path, source)
    dependency = system_skills / "plugin-creator" / "scripts" / "identifier_validation.py"
    dependency.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "def validate_plugin_identifier(value):\n"
        "    return None\n",
        encoding="utf-8",
    )
    upstream = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"

    errors = validate(
        plugin,
        system_skills,
        trusted_upstream_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
        trusted_identifier_sha256="0" * 64,
    )

    assert errors == [
        "OpenAI plugin validator identifier dependency does not match the repository's reviewed "
        "SHA-256"
    ]
    assert not marker.exists()


def test_symlinked_upstream_dependency_is_rejected_before_resolution(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    source = (
        "from identifier_validation import validate_plugin_identifier\n"
        "def validate_plugin(plugin_root):\n"
        "    validate_plugin_identifier('atready')\n"
        "    return []\n"
    )
    system_skills = _write_upstream_source(tmp_path, source)
    scripts = system_skills / "plugin-creator" / "scripts"
    dependency = scripts / "identifier_validation.py"
    reviewed = scripts / "reviewed-identifier.py"
    reviewed.write_text(
        "def validate_plugin_identifier(value):\n    return None\n",
        encoding="utf-8",
    )
    dependency.symlink_to(reviewed)
    upstream = scripts / "validate_plugin.py"

    errors = validate(
        plugin,
        system_skills,
        trusted_upstream_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
        trusted_identifier_sha256=hashlib.sha256(reviewed.read_bytes()).hexdigest(),
    )

    assert errors == [f"OpenAI plugin validator identifier dependency not found at {dependency}"]


def test_reviewed_upstream_dependency_is_loaded_from_verified_bytes(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    source = (
        "from identifier_validation import validate_plugin_identifier\n"
        "def validate_plugin(plugin_root):\n"
        "    validate_plugin_identifier('atready')\n"
        "    return []\n"
    )
    system_skills = _write_upstream_source(tmp_path, source)
    dependency = system_skills / "plugin-creator" / "scripts" / "identifier_validation.py"
    dependency.write_text(
        "def validate_plugin_identifier(value):\n"
        "    if value != 'atready':\n"
        "        raise ValueError('unexpected')\n",
        encoding="utf-8",
    )
    upstream = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"

    errors = validate(
        plugin,
        system_skills,
        trusted_upstream_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
        trusted_identifier_sha256=hashlib.sha256(dependency.read_bytes()).hexdigest(),
    )

    assert errors == []


def test_validator_sys_path_is_restored_when_helper_execution_raises(
    tmp_path: Path,
) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    source = (
        "from identifier_validation import validate_plugin_identifier\n"
        "def validate_plugin(plugin_root):\n"
        "    validate_plugin_identifier('atready')\n"
        "    return []\n"
    )
    system_skills = _write_upstream_source(tmp_path, source)
    dependency = system_skills / "plugin-creator" / "scripts" / "identifier_validation.py"
    dependency.write_text(
        "import sys\nsys.path.insert(0, 'helper-leak')\nraise RuntimeError('helper failed')\n",
        encoding="utf-8",
    )
    upstream = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"
    before = list(sys.path)

    with pytest.raises(RuntimeError, match="helper failed"):
        validate(
            plugin,
            system_skills,
            trusted_upstream_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
            trusted_identifier_sha256=hashlib.sha256(dependency.read_bytes()).hexdigest(),
        )

    assert sys.path == before


def test_validator_sys_path_is_restored_when_validator_execution_raises(
    tmp_path: Path,
) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    system_skills = _write_upstream_source(
        tmp_path,
        "import sys\n"
        "def validate_plugin(plugin_root):\n"
        "    sys.path.append('validator-leak')\n"
        "    raise RuntimeError('validator failed')\n",
    )
    upstream = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"
    before = list(sys.path)

    with pytest.raises(RuntimeError, match="validator failed"):
        validate(
            plugin,
            system_skills,
            trusted_upstream_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
        )

    assert sys.path == before


def test_upstream_validator_that_changes_its_file_is_rejected(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    system_skills = _write_upstream_source(
        tmp_path,
        "from pathlib import Path\n"
        "def validate_plugin(plugin_root):\n"
        "    Path(__file__).write_text('changed', encoding='utf-8')\n"
        "    return []\n",
    )
    upstream = system_skills / "plugin-creator" / "scripts" / "validate_plugin.py"
    trusted_hash = hashlib.sha256(upstream.read_bytes()).hexdigest()

    errors = validate(plugin, system_skills, trusted_upstream_sha256=trusted_hash)

    assert errors == ["OpenAI plugin validator changed while validation was running"]


def test_repository_instructions_use_the_current_policy_validator() -> None:
    command_pattern = re.compile(
        r"python3 scripts/validate_plugin_contract\.py plugins/atready"
        r"(?:\s*\\)?\s+--system-skills-dir \"\$CODEX_SYSTEM_SKILLS_DIR\""
    )
    for path in (
        ROOT / "AGENTS.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "docs/DIRECTORY_SUBMISSION.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert command_pattern.search(text)


def test_agent_yaml_aliases_are_rejected(tmp_path: Path) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    agent = plugin / "skills" / "project-atready" / "agents" / "openai.yaml"
    agent.write_text(
        "interface: &shared\n"
        "  display_name: AtReady\n"
        "  short_description: Plan with saved resources\n"
        "copy: *shared\n"
        "policy:\n"
        "  products: [CODEX]\n",
        encoding="utf-8",
    )
    system_skills = _write_upstream(tmp_path, [])

    errors = _validate(plugin, system_skills)

    assert len(errors) == 1
    assert "must contain readable UTF-8 YAML" in errors[0]
    assert "AtReady" not in errors[0]


@pytest.mark.parametrize(
    "field",
    (
        "api_key",
        "access_token",
        "authorization",
        "credentials",
        "refresh_token",
        "client_secret",
        "passwords",
        "private_key",
        "secrets",
    ),
)
def test_agent_yaml_secret_fields_are_rejected(tmp_path: Path, field: str) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    agent = plugin / "skills" / "project-atready" / "agents" / "openai.yaml"
    payload = yaml.safe_load(agent.read_text(encoding="utf-8"))
    payload[field] = "deliberately-non-secret-test-value"
    agent.write_text(yaml.safe_dump(payload), encoding="utf-8")
    system_skills = _write_upstream(tmp_path, [])

    errors = _validate(plugin, system_skills)

    assert errors == [f"agent YAML contains forbidden secret-bearing field `{field}`"]


@pytest.mark.parametrize("field", ("api_key", "credentials", "private_key"))
def test_nested_agent_yaml_secret_fields_are_rejected(tmp_path: Path, field: str) -> None:
    plugin = _write_candidate(tmp_path, ["CODEX"])
    agent = plugin / "skills" / "project-atready" / "agents" / "openai.yaml"
    payload = yaml.safe_load(agent.read_text(encoding="utf-8"))
    payload["nested"] = {"items": [{field: "deliberately-non-secret-test-value"}]}
    agent.write_text(yaml.safe_dump(payload), encoding="utf-8")
    system_skills = _write_upstream(tmp_path, [])

    errors = _validate(plugin, system_skills)

    assert errors == [f"agent YAML contains forbidden secret-bearing field `{field}`"]
