from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def test_synthetic_first_user_acceptance_uses_ephemeral_state() -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "first_user_acceptance.py"
    expected_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    environment = os.environ.copy()
    environment["PATH"] = ""

    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(script), "--module"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout)
    assert receipt["result"] == "passed"
    assert receipt["synthetic_only"] is True
    assert receipt["mutation_scope"] == "ephemeral-temporary-directory-only"
    assert receipt["commands_checked"] == 27
    assert receipt["cli_version"] == expected_version
    assert receipt["catalog_version"] == 1
    assert "version-and-command-surface" in receipt["checks"]
    assert "catalog-and-bounded-local-discovery" in receipt["checks"]
    assert "quick-add-intake-review" in receipt["checks"]
    assert "quick-add-strict-validation" in receipt["checks"]
    assert "quick-add-first-route" in receipt["checks"]
    assert "progressive-intake-enrichment" in receipt["checks"]
    assert "stale-plan-no-write" in receipt["checks"]
    assert "independent-init-creates-new-lineage" in receipt["checks"]
    combined = completed.stdout + completed.stderr
    assert "SYNTHETIC-FIRST-USER-PRIVATE-NOTE" not in combined
    assert "nonce-v1:" not in combined
