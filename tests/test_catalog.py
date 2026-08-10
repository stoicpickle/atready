from __future__ import annotations

import base64
import os
import re
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from atready.catalog import InventoryCatalog
from atready.errors import ConfigurationError
from atready.models import Inventory, Resource
from atready.templates import demo_inventory, starter_inventory


def test_starter_inventory_is_empty_personal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    generated = iter(("00" * 32, "11" * 32))
    calls: list[int] = []

    def deterministic_nonce(byte_count: int) -> str:
        calls.append(byte_count)
        return next(generated)

    monkeypatch.setattr("atready.templates.secrets.token_hex", deterministic_nonce)
    first_text = starter_inventory()
    second_text = starter_inventory()
    catalog = InventoryCatalog.from_text(first_text)
    assert catalog.inventory.inventory_kind == "personal"
    assert catalog.inventory.resources == []
    assert catalog.warnings == ()
    nonce = catalog.inventory.revision_privacy_nonce
    assert nonce is not None
    assert re.fullmatch(r"nonce-v1:[0-9a-f]{64}", nonce)
    assert nonce not in repr(catalog)
    assert nonce not in repr(catalog.inventory)
    assert first_text != second_text
    assert calls == [32, 32]


@pytest.mark.parametrize("private_notes", ["guessable-note", ""])
def test_private_notes_require_a_revision_privacy_nonce(private_notes: str) -> None:
    text = starter_inventory()
    nonce = InventoryCatalog.from_text(text).inventory.revision_privacy_nonce
    assert nonce is not None
    unblinded = text.replace(f'revision_privacy_nonce: "{nonce}"\n', "").replace(
        "resources: []", f"private_notes: {private_notes!r}\nresources: []"
    )

    with pytest.raises(ConfigurationError) as caught:
        InventoryCatalog.from_text(unblinded)

    assert "legacy-unblinded inventories cannot contain private notes" in str(caught.value)
    assert "do not add a nonce manually" in str(caught.value)
    assert private_notes not in str(caught.value) if private_notes else True
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_legacy_unblinded_inventory_remains_valid_without_private_notes() -> None:
    text = starter_inventory()
    nonce = InventoryCatalog.from_text(text).inventory.revision_privacy_nonce
    assert nonce is not None
    unblinded = text.replace(f'revision_privacy_nonce: "{nonce}"\n', "")

    assert InventoryCatalog.from_text(unblinded).inventory.revision_privacy_nonce is None


@pytest.mark.parametrize(
    "invalid_nonce",
    [
        "nonce-v2:" + "a" * 64,
        "nonce-v1:" + "A" * 64,
        "nonce-v1:" + "a" * 63,
        "SYNTHETIC-NONCE-SENTINEL",
        "123",
    ],
)
def test_invalid_revision_privacy_nonce_is_value_redacted(invalid_nonce: str) -> None:
    text = starter_inventory()
    nonce = InventoryCatalog.from_text(text).inventory.revision_privacy_nonce
    assert nonce is not None
    invalid = text.replace(nonce, invalid_nonce)

    with pytest.raises(ConfigurationError) as caught:
        InventoryCatalog.from_text(invalid)

    assert invalid_nonce not in str(caught.value)
    assert invalid_nonce not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_non_string_revision_privacy_nonce_is_rejected_without_input_echo() -> None:
    text = starter_inventory()
    nonce = InventoryCatalog.from_text(text).inventory.revision_privacy_nonce
    assert nonce is not None
    invalid = text.replace(f'"{nonce}"', "123456")

    with pytest.raises(ConfigurationError) as caught:
        InventoryCatalog.from_text(invalid)

    assert "123456" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_binary_revision_privacy_nonce_is_not_coerced_to_text() -> None:
    text = starter_inventory()
    catalog = InventoryCatalog.from_text(text)
    nonce = catalog.inventory.revision_privacy_nonce
    assert nonce is not None
    value = catalog.inventory.model_dump(mode="json")
    value["revision_privacy_nonce"] = nonce.encode()

    with pytest.raises(ConfigurationError) as direct_error:
        InventoryCatalog.from_mapping(value)

    encoded = base64.b64encode(nonce.encode()).decode()
    binary_yaml = text.replace(
        f'revision_privacy_nonce: "{nonce}"',
        f"revision_privacy_nonce: !!binary {encoded}",
    )
    with pytest.raises(ConfigurationError) as yaml_error:
        InventoryCatalog.from_text(binary_yaml)

    assert nonce not in str(direct_error.value)
    assert nonce not in str(yaml_error.value)


def test_direct_model_validation_hides_nonce_input_in_error_text() -> None:
    sentinel = "nonce-v1:" + "A" * 64
    value = InventoryCatalog.from_text(starter_inventory()).inventory.model_dump(mode="json")
    value["revision_privacy_nonce"] = sentinel

    with pytest.raises(ValidationError) as caught:
        Inventory.model_validate(value)

    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)


@pytest.mark.parametrize("version", ["true", "1.0", "'1'"])
def test_inventory_schema_version_requires_exact_native_integer(version: str) -> None:
    invalid = starter_inventory().replace("schema_version: 1", f"schema_version: {version}")

    with pytest.raises(ConfigurationError, match="native YAML/JSON integer"):
        InventoryCatalog.from_text(invalid)


def test_inventory_validation_location_redacts_dynamic_capability_key() -> None:
    sentinel = "confidential-client-name"
    invalid = starter_inventory().replace(
        "resources: []",
        "resources:\n"
        "  - id: local-tool\n"
        "    name: Local Tool\n"
        "    categories: [tool]\n"
        "    capabilities:\n"
        f"      {sentinel}: invalid-score\n",
    )

    with pytest.raises(ConfigurationError) as caught:
        InventoryCatalog.from_text(invalid)

    assert sentinel not in str(caught.value)
    assert "capabilities.<entry>" in str(caught.value)


def test_inventory_duplicate_id_error_does_not_echo_the_id() -> None:
    sentinel = "confidential-client-resource"
    value = InventoryCatalog.from_text(starter_inventory()).inventory.model_dump(mode="json")
    resource = {
        "id": sentinel,
        "name": "Confidential Client Resource",
        "categories": ["tool"],
        "capabilities": {"build": 0.9},
    }
    value["resources"] = [resource, resource]

    with pytest.raises(ConfigurationError) as caught:
        InventoryCatalog.from_mapping(value)

    assert sentinel not in str(caught.value)
    assert "resource ids must be unique" in str(caught.value)


def test_catalog_path_uses_acl_aware_descriptor_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(starter_inventory(), encoding="utf-8")
    if os.name == "posix":
        inventory.chmod(0o600)
    monkeypatch.setattr(
        "atready.inventory_edit.darwin_fd_has_extended_acl",
        lambda _descriptor: True,
    )

    with pytest.raises(ConfigurationError, match="macOS extended ACL"):
        InventoryCatalog.from_path(inventory)


def test_inventory_kind_is_required_to_prevent_unmarked_demo_state() -> None:
    text = starter_inventory().replace("inventory_kind: personal\n", "")

    with pytest.raises(
        ConfigurationError,
        match="classify user-declared state as 'personal' or synthetic examples as 'demo'",
    ):
        InventoryCatalog.from_text(text)


def test_demo_inventory_is_valid_and_preserves_unknown_state() -> None:
    today = date(2026, 8, 6)
    catalog = InventoryCatalog.from_text(demo_inventory(today), today=today)
    assert catalog.inventory.inventory_kind == "demo"
    assert len(catalog.inventory.resources) == 3
    assert catalog.warnings == ("resource 'asset-studio' has unknown current-session availability",)


def test_exact_capacity_enters_snapshot_fingerprint_and_strict_warnings() -> None:
    today = date(2026, 8, 8)
    value = InventoryCatalog.from_text(demo_inventory(today), today=today).inventory.model_dump(
        mode="json"
    )
    economics = value["resources"][0]["economics"]
    economics["quota"] = "limited"
    economics["capacity"] = {
        "unit": "agent-task",
        "remaining": 8,
        "limit": 50,
        "project_limit": 3,
        "resets_on": "2026-08-31",
        "basis": "observed",
        "last_verified": "2026-08-07",
    }

    catalog = InventoryCatalog.from_mapping(value, today=today)
    snapshot = catalog.snapshot(today=today)
    resource = next(item for item in snapshot["resources"] if item["id"] == "local-coding-agent")
    assert resource["economics"]["capacity"] == {
        "unit": "agent-task",
        "remaining": 8.0,
        "limit": 50.0,
        "project_limit": 3.0,
        "resets_on": "2026-08-31",
        "basis": "observed",
        "last_verified": "2026-08-07",
    }
    first_fingerprint = catalog.fingerprint()
    economics["capacity"]["remaining"] = 7
    assert InventoryCatalog.from_mapping(value, today=today).fingerprint() != first_fingerprint

    economics["capacity"].update(
        {
            "remaining": 7,
            "resets_on": "2026-04-02",
            "last_verified": "2026-04-01",
        }
    )
    stale = InventoryCatalog.from_mapping(value, today=today)
    assert any(
        warning.startswith("resource 'local-coding-agent' exact capacity is stale")
        for warning in stale.warnings
    )
    assert (
        "resource 'local-coding-agent' exact capacity reset date has passed; re-check the balance"
        in stale.warnings
    )


def test_snapshot_omits_private_notes_and_is_stable() -> None:
    today = date(2026, 8, 6)
    text = (
        demo_inventory(today)
        .replace(
            "schema_version: 1",
            "schema_version: 1\n"
            "revision_privacy_nonce: nonce-v1:"
            "5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9\n"
            "private_notes: never expose this",
        )
        .replace(
            "    name: Synthetic Local Coding Agent",
            "    name: Synthetic Local Coding Agent\n    private_notes: private account detail",
        )
    )
    catalog = InventoryCatalog.from_text(text, today=today)
    first = catalog.snapshot(today=today)
    second = catalog.snapshot(today=today)
    assert first == second
    assert "private_notes" not in first
    assert all("private_notes" not in resource for resource in first["resources"])
    assert "never expose this" not in str(first)
    assert "private account detail" not in str(first)
    assert "revision_privacy_nonce" not in first
    assert "5feceb66" not in str(first)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("best_for", [""], "at least 1 character"),
        ("avoid_for", ["   "], "at least 1 character"),
        ("best_for", ["terminal\x1bcontrol"], "control or format characters"),
        ("avoid_for", ["x" * 241], "at most 240 characters"),
    ],
)
def test_advisory_text_is_bounded_and_display_safe(
    field: str,
    value: list[str],
    message: str,
) -> None:
    resource = {
        "id": "local-tool",
        "name": "Local Tool",
        "categories": ["tool"],
        "capabilities": {"build": 0.9},
        field: value,
    }

    with pytest.raises(ValidationError, match=message):
        Resource.model_validate(resource)


@pytest.mark.parametrize("field", ["best_for", "avoid_for"])
def test_advisory_text_rejects_duplicates_after_normalization(field: str) -> None:
    resource = {
        "id": "local-tool",
        "name": "Local Tool",
        "categories": ["tool"],
        "capabilities": {"build": 0.9},
        field: ["bounded work", " bounded work "],
    }

    with pytest.raises(ValidationError, match=f"{field} must not contain duplicates"):
        Resource.model_validate(resource)


def test_routing_snapshot_omits_nonsemantic_resource_advisories_and_billing() -> None:
    catalog = InventoryCatalog.from_text(demo_inventory(date(2026, 8, 6)))

    snapshot = catalog.snapshot(today=date(2026, 8, 6))

    assert all("best_for" not in resource for resource in snapshot["resources"])
    assert all("avoid_for" not in resource for resource in snapshot["resources"])
    assert all("billing" not in resource["economics"] for resource in snapshot["resources"])


def test_duplicate_resource_ids_fail_with_actionable_location() -> None:
    today = date(2026, 8, 6)
    text = demo_inventory(today).replace("id: interactive-debugger", "id: local-coding-agent")
    with pytest.raises(ConfigurationError, match="resource ids must be unique"):
        InventoryCatalog.from_text(text, today=today)


def test_unknown_and_stale_state_remain_visible() -> None:
    text = demo_inventory(date(2025, 1, 1)).replace(
        "current_session: available", "current_session: unknown", 1
    )
    catalog = InventoryCatalog.from_text(text, today=date(2026, 8, 6))
    assert any("unknown current-session availability" in warning for warning in catalog.warnings)
    assert any("verification is stale" in warning for warning in catalog.warnings)
    local = next(
        resource
        for resource in catalog.snapshot(today=date(2026, 8, 6))["resources"]
        if resource["id"] == "local-coding-agent"
    )
    assert local["access"]["current_session"] == "unknown"
    assert local["provenance"]["verification_status"] == "stale"
