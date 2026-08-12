#!/usr/bin/env python3
"""Compare an isolated bundled candidate with the canonical AtReady runtime."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_PROBE = Path(__file__).resolve().parent / "bundle" / "probe.py"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _run_atready(args: list[str], *, expected: int = 0) -> str:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(  # noqa: S603 - fixed interpreter; synthetic harness args only
        [sys.executable, "-m", "atready.cli", *args],
        cwd=_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != expected:
        raise RuntimeError(
            f"canonical command failed ({completed.returncode}): {' '.join(args)}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def _json(text: str, label: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} did not return a JSON object")
    return value


def _resource_args(inventory: Path) -> list[str]:
    return [
        "inventory",
        "add",
        "--path",
        str(inventory),
        "--id",
        "synthetic-local-coder",
        "--name",
        "Synthetic Local Coder",
        "--category",
        "coding-agent",
        "--capability",
        "code-implementation=0.95",
        "--capability",
        "test-automation=0.90",
        "--access",
        "active",
        "--interaction",
        "local-cli",
        "--session",
        "available",
        "--billing",
        "owned",
        "--marginal-cost",
        "0",
        "--quota",
        "ample",
        "--allowed-data-class",
        "internal",
        "--confidence-basis",
        "observed",
        "--verified-on",
        "2026-08-09",
        "--handoff-method",
        "manual-prompt",
    ]


def _capture_canonical_journey(root: Path) -> dict[str, Any]:
    inventory = root / "inventory.yaml"
    project = root / "project.yaml"

    version = _run_atready(["--version"]).strip()
    initialized_text = _run_atready(["init", "--path", str(inventory), "--json"])
    initialized = _json(initialized_text, "init")
    if initialized.get("inventory_kind") != "personal" or initialized.get("resources") != 0:
        raise RuntimeError("canonical init did not create an empty personal inventory")
    if initialized.get("revision_protection") != "nonce-v1-present":
        raise RuntimeError("canonical init omitted revision protection")

    resource_args = _resource_args(inventory)
    preview_text = _run_atready([*resource_args, "--json"])
    preview = _json(preview_text, "preview")
    revision = preview.get("expect_revision")
    plan_token = preview.get("expect_plan")
    if preview.get("applied") is not False:
        raise RuntimeError("canonical add preview mutated state")
    if not isinstance(revision, str) or _SHA256.fullmatch(revision) is None:
        raise RuntimeError("canonical preview omitted the exact revision")
    if not isinstance(plan_token, str) or _SHA256.fullmatch(plan_token) is None:
        raise RuntimeError("canonical preview omitted the exact plan token")

    applied_text = _run_atready(
        [
            *resource_args,
            "--apply",
            "--expect-revision",
            revision,
            "--expect-plan",
            plan_token,
            "--json",
        ]
    )
    applied = _json(applied_text, "apply")
    if applied.get("applied") is not True or applied.get("previous_revision") != revision:
        raise RuntimeError("canonical apply did not honor the previewed revision")
    candidate_revision = applied.get("revision")
    if not isinstance(candidate_revision, str) or _SHA256.fullmatch(candidate_revision) is None:
        raise RuntimeError("canonical apply omitted the resulting revision")
    if candidate_revision == revision:
        raise RuntimeError("canonical apply did not change the inventory revision")

    project.write_text(_run_atready(["project", "template"]), encoding="utf-8")
    route_text = _run_atready(
        [
            "route",
            "--project",
            str(project),
            "--inventory",
            str(inventory),
            "--format",
            "json",
        ]
    )
    route = _json(route_text, "route")
    assignments = route.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        raise RuntimeError("canonical route returned no assignment")
    primary = assignments[0].get("primary") if isinstance(assignments[0], dict) else None
    if not isinstance(primary, dict) or primary.get("resource_id") != "synthetic-local-coder":
        raise RuntimeError("canonical route did not select the synthetic resource")

    combined_output = initialized_text + preview_text + applied_text + route_text
    if "nonce-v1:" in combined_output:
        raise RuntimeError("canonical output exposed the private revision nonce")

    return {
        "schema_version": 1,
        "canonical_runtime": {"version": version},
        "synthetic_only": True,
        "ephemeral_temporary_directory_only": True,
        "journey": [
            {"step": "init", "proved": True, "resources": 0},
            {
                "step": "preview-add",
                "proved": True,
                "applied": False,
                "exact_revision_present": True,
                "exact_plan_token_present": True,
            },
            {
                "step": "apply-add",
                "proved": True,
                "applied": True,
                "preview_revision_honored": True,
                "resulting_revision_changed": True,
            },
            {
                "step": "route",
                "proved": True,
                "selected_resource_id": "synthetic-local-coder",
                "handoffs_executed": False,
            },
        ],
        "normal_output_exposed_revision_nonce": False,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="atready-bundled-kernel-") as raw_root:
        ephemeral_root = Path(raw_root).resolve()
        canonical = _capture_canonical_journey(ephemeral_root)
        receipt_path = ephemeral_root / "canonical-receipt.json"
        receipt_path.write_text(json.dumps(canonical, sort_keys=True), encoding="utf-8")
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and local probe path
            [
                sys.executable,
                "-I",
                "-S",
                str(_PROBE),
                "--canonical-receipt",
                str(receipt_path),
            ],
            cwd=ephemeral_root,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"isolated probe failed: {completed.stderr.strip()}")
        isolated_probe = _json(completed.stdout, "isolated probe")

    print(
        json.dumps(
            {
                "schema_version": 1,
                "canonical_receipt": canonical,
                "isolated_probe": isolated_probe,
                "ephemeral_directory_removed": not ephemeral_root.exists(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
