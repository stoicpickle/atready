from __future__ import annotations

import hashlib
import os
import shutil
from datetime import date
from pathlib import Path

from atready.catalog import InventoryCatalog
from atready.paths import create_private_file
from atready.templates import starter_inventory


def _exact_revision(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_exact_copy_is_continuity_but_fresh_init_is_an_independent_lineage(
    tmp_path: Path,
) -> None:
    original_text = starter_inventory().replace(
        "resources: []",
        "private_notes: synthetic hidden note\nresources: []",
    )
    source = tmp_path / "inventory.yaml"
    create_private_file(source, original_text)
    clone = tmp_path / "clone.yaml"
    shutil.copyfile(source, clone)
    if os.name == "posix":
        clone.chmod(0o600)
    continuity_copy = clone.read_text(encoding="utf-8")
    independent_text = starter_inventory().replace(
        "resources: []",
        "private_notes: synthetic hidden note\nresources: []",
    )

    original = InventoryCatalog.from_path(source)
    copied = InventoryCatalog.from_path(clone)
    independent = InventoryCatalog.from_text(independent_text)

    assert copied.inventory.revision_privacy_nonce == original.inventory.revision_privacy_nonce
    assert _exact_revision(continuity_copy) == _exact_revision(original_text)
    assert independent.inventory.revision_privacy_nonce != original.inventory.revision_privacy_nonce
    assert _exact_revision(independent_text) != _exact_revision(original_text)

    # The nonce changes exact-state identity, not the routing-visible meaning.
    today = date(2026, 8, 8)
    assert independent.fingerprint() == original.fingerprint()
    assert independent.snapshot(today=today) == original.snapshot(today=today)
    assert original.inventory.revision_protection() == "nonce-v1-present"
    assert independent.inventory.revision_protection() == "nonce-v1-present"


def test_nonce_clone_contract_is_explicitly_non_migrating() -> None:
    path = Path(__file__).resolve().parents[1] / "docs" / "NONCE_AND_CLONING.md"
    documentation = path.read_text(encoding="utf-8")

    assert "same lineage" in documentation
    assert "independent lineage" in documentation
    assert (
        "no `rotate`, `migrate`, clone, merge, or in-place nonce-injection command" in documentation
    )
    assert "not freshness" in documentation
