#!/usr/bin/env python3
"""Validate the AtReady plugin against OpenAI's current documented skill policy."""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

OFFICIAL_REFERENCE = "https://developers.openai.com/plugins/deploy/submission-errors"
ALLOWED_PRODUCTS = {"CHAT", "CODEX"}
TRUSTED_UPSTREAM_VALIDATOR_SHA256 = (
    "ebda00d55d7518b127f675f062fb5c6e7a1ffdc0a99df1a55ac594400d7d3228"
)
MAX_AGENT_BYTES = 64_000
MAX_SKILLS = 100
MAX_YAML_DEPTH = 12
MAX_YAML_ITEMS = 1_000
MAX_COLLECTION_ITEMS = 100
MAX_UPSTREAM_BYTES = 1_000_000
SECRET_KEYS = {
    "access-token",
    "api-key",
    "apikey",
    "authorization",
    "client-secret",
    "cookie",
    "credential",
    "credentials",
    "password",
    "passwords",
    "private-key",
    "refresh-token",
    "secret",
    "secrets",
    "token",
}
LEGACY_PRODUCTS_ERROR = re.compile(
    r"^skill `(?P<skill>[^`]+)` agent field `policy\.products` "
    r"is not accepted by plugin validation$"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run OpenAI's installed plugin validator with current policy.products compatibility."
        )
    )
    parser.add_argument("plugin_path", type=Path)
    parser.add_argument(
        "--system-skills-dir",
        type=Path,
        required=True,
        help="Directory containing OpenAI's plugin-creator and skill-creator system skills.",
    )
    return parser.parse_args()


def _load_upstream_validator(path: Path, trusted_sha256: str) -> ModuleType:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"OpenAI plugin validator not found at {path}")
    file_stat = path.stat()
    if file_stat.st_size > MAX_UPSTREAM_BYTES:
        raise ValueError(f"OpenAI plugin validator exceeds {MAX_UPSTREAM_BYTES} bytes")
    if file_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError("OpenAI plugin validator must not be group- or world-writable")
    source_bytes = path.read_bytes()
    expected_hash = hashlib.sha256(source_bytes).hexdigest()
    if expected_hash != trusted_sha256:
        raise ValueError("OpenAI plugin validator does not match the repository's reviewed SHA-256")
    module = ModuleType("atready_openai_plugin_validator")
    module.__file__ = str(path)
    code = compile(source_bytes, str(path), "exec", dont_inherit=True)
    exec(code, module.__dict__)  # noqa: S102 - executes only repository-pinned verified bytes
    if not callable(getattr(module, "validate_plugin", None)):
        raise ValueError("OpenAI plugin validator does not expose validate_plugin")
    return module


class _BoundedSafeLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self.node_count = 0
        self.node_depth = 0

    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not allowed")
        self.node_count += 1
        if self.node_count > MAX_YAML_ITEMS:
            raise yaml.YAMLError("YAML contains too many items")
        self.node_depth += 1
        if self.node_depth > MAX_YAML_DEPTH:
            raise yaml.YAMLError("YAML nesting is too deep")
        try:
            return super().compose_node(parent, index)
        finally:
            self.node_depth -= 1


def _reject_unsafe_values(value: Any, *, depth: int = 0) -> int:
    if depth > MAX_YAML_DEPTH:
        raise ValueError("agent YAML nesting is too deep")
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise ValueError("agent YAML mapping contains too many entries")
        count = 1
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("agent YAML mapping keys must be strings")
            normalized = key.casefold().replace("_", "-")
            if normalized in SECRET_KEYS:
                raise ValueError(f"agent YAML contains forbidden secret-bearing field `{key}`")
            count += _reject_unsafe_values(item, depth=depth + 1)
        return count
    if isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise ValueError("agent YAML list contains too many entries")
        return 1 + sum(_reject_unsafe_values(item, depth=depth + 1) for item in value)
    return 1


def _load_agent_payload(path: Path, plugin_root: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path} must be a regular file")
    resolved = path.resolve()
    if not resolved.is_relative_to(plugin_root):
        raise ValueError(f"{path} must stay inside the plugin root")
    if path.stat().st_size > MAX_AGENT_BYTES:
        raise ValueError(f"{path} exceeds the {MAX_AGENT_BYTES}-byte validation limit")
    try:
        payload = yaml.load(
            path.read_text(encoding="utf-8"),
            Loader=_BoundedSafeLoader,  # noqa: S506 - bounded yaml.SafeLoader subclass
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{path} must contain readable UTF-8 YAML") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    if _reject_unsafe_values(payload) > MAX_YAML_ITEMS:
        raise ValueError(f"{path} contains too many YAML items")
    return payload


def _official_products(plugin_root: Path) -> tuple[set[str], list[str]]:
    skills_root = plugin_root / "skills"
    if not skills_root.is_dir() or skills_root.is_symlink():
        return set(), []
    entries = sorted(skills_root.iterdir())
    symlinked = [path for path in entries if path.is_symlink()]
    if symlinked:
        return set(), [f"skill path must not be a symlink: {symlinked[0]}"]
    skill_roots = [path for path in entries if path.is_dir()]
    if len(skill_roots) > MAX_SKILLS:
        return set(), [f"plugin contains more than {MAX_SKILLS} skill directories"]

    valid_skills: set[str] = set()
    errors: list[str] = []
    for skill_root in skill_roots:
        agent_path = skill_root / "agents" / "openai.yaml"
        if not agent_path.exists():
            continue
        if (skill_root / "agents").is_symlink():
            errors.append(f"agents path must not be a symlink: {skill_root / 'agents'}")
            continue
        try:
            payload = _load_agent_payload(agent_path, plugin_root)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        policy = payload.get("policy")
        if not isinstance(policy, dict) or "products" not in policy:
            continue
        products = policy["products"]
        if (
            not isinstance(products, list)
            or not products
            or any(type(item) is not str or item not in ALLOWED_PRODUCTS for item in products)
            or len(set(products)) != len(products)
        ):
            errors.append(
                f"skill `{skill_root.name}` policy.products must contain CHAT, CODEX, or both"
            )
            continue
        valid_skills.add(skill_root.name)
    return valid_skills, errors


def validate(
    plugin_root: Path,
    system_skills_dir: Path,
    *,
    trusted_upstream_sha256: str = TRUSTED_UPSTREAM_VALIDATOR_SHA256,
) -> list[str]:
    plugin_root = plugin_root.expanduser().resolve()
    valid_product_skills, errors = _official_products(plugin_root)
    if errors:
        return errors

    upstream_path = system_skills_dir / "plugin-creator" / "scripts" / "validate_plugin.py"
    resolved_upstream = upstream_path.resolve()
    if not resolved_upstream.is_relative_to(system_skills_dir):
        return ["OpenAI plugin validator must stay inside the declared system skills directory"]
    try:
        upstream = _load_upstream_validator(resolved_upstream, trusted_upstream_sha256)
    except ValueError as exc:
        return [str(exc)]

    upstream_errors = upstream.validate_plugin(plugin_root)
    try:
        current_upstream_hash = hashlib.sha256(resolved_upstream.read_bytes()).hexdigest()
    except OSError:
        return ["OpenAI plugin validator changed while validation was running"]
    if current_upstream_hash != trusted_upstream_sha256:
        return ["OpenAI plugin validator changed while validation was running"]
    for error in upstream_errors:
        match = LEGACY_PRODUCTS_ERROR.fullmatch(error)
        if match and match.group("skill") in valid_product_skills:
            continue
        errors.append(error)
    return errors


def main() -> None:
    args = _parse_args()
    plugin_root = args.plugin_path.expanduser().resolve()
    system_skills_dir = args.system_skills_dir.expanduser().resolve()
    errors = validate(plugin_root, system_skills_dir)
    if errors:
        print("Plugin validation failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"Plugin validation passed: {plugin_root}")
    print(f"Current policy schema: {OFFICIAL_REFERENCE}")


if __name__ == "__main__":
    main()
