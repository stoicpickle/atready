from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
import yaml

from scripts.validate_plugin_contract import validate

ROOT = Path(__file__).parents[1]


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
