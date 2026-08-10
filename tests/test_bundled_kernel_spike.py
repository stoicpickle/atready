from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "experiments" / "bundled-kernel"


def _valid_receipt() -> dict[str, object]:
    return {
        "schema_version": 1,
        "canonical_runtime": {"version": "atready 0.1.5"},
        "synthetic_only": True,
        "ephemeral_temporary_directory_only": True,
        "normal_output_exposed_revision_nonce": False,
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
    }


def test_harness_proves_canonical_journey_and_stops_isolated_candidate() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and repository harness
        [sys.executable, str(SPIKE / "harness.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    canonical = result["canonical_receipt"]
    probe = result["isolated_probe"]

    assert [item["step"] for item in canonical["journey"]] == [
        "init",
        "preview-add",
        "apply-add",
        "route",
    ]
    assert all(item["proved"] is True for item in canonical["journey"])
    assert canonical["synthetic_only"] is True
    assert canonical["ephemeral_temporary_directory_only"] is True
    assert canonical["normal_output_exposed_revision_nonce"] is False
    assert result["ephemeral_directory_removed"] is True

    assert probe["isolated_runtime"]["python_isolated"] is True
    assert probe["isolated_runtime"]["site_initialization_disabled"] is True
    assert probe["isolated_runtime"]["site_packages_present"] is False
    assert probe["isolated_runtime"]["third_party_yaml_available"] is False
    assert probe["isolated_runtime"]["third_party_pydantic_available"] is False
    assert probe["candidate_interface"]["inventory_paths_accepted"] is False
    assert probe["candidate_interface"]["mutation_operations"] == []
    assert probe["comparison"]["full_behavioral_parity"] is False
    assert probe["comparison"]["uncovered_journey_steps"] == [
        "init",
        "preview-add",
        "apply-add",
        "route",
    ]
    assert [gate["id"] for gate in probe["comparison"]["remaining_gates"]] == [
        "inventory-format-parity",
        "write-safety-parity",
        "routing-parity",
        "single-source-maintenance",
    ]
    assert probe["decision"]["status"] == "stop"
    assert probe["decision"]["candidate_is_release_runtime"] is False


def test_isolated_probe_rejects_unproved_receipt_without_writes(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "canonical_runtime": {"version": "atready 0.1.5"},
                "synthetic_only": True,
                "ephemeral_temporary_directory_only": True,
                "normal_output_exposed_revision_nonce": False,
                "journey": [],
            }
        ),
        encoding="utf-8",
    )
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    completed = subprocess.run(  # noqa: S603 - fixed interpreter and repository probe
        [
            sys.executable,
            "-I",
            "-S",
            str(SPIKE / "bundle" / "probe.py"),
            "--canonical-receipt",
            str(receipt),
        ],
        cwd=tmp_path,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    failure = json.loads(completed.stderr)
    assert failure["decision"] == {
        "candidate_is_release_runtime": False,
        "status": "stop",
    }
    assert "complete four-step journey" in failure["error"]
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_isolated_probe_rejects_unknown_fields_and_secret_bearing_version(
    tmp_path: Path,
) -> None:
    sentinel = "SYNTHETIC-SECRET-SENTINEL"
    cases = []

    secret_version = _valid_receipt()
    secret_version["canonical_runtime"] = {"version": f"atready {sentinel}"}
    cases.append(secret_version)

    unknown_field = _valid_receipt()
    unknown_field["unexpected"] = sentinel
    cases.append(unknown_field)

    boolean_schema = _valid_receipt()
    boolean_schema["schema_version"] = True
    cases.append(boolean_schema)

    exposed_nonce = _valid_receipt()
    exposed_nonce["normal_output_exposed_revision_nonce"] = True
    cases.append(exposed_nonce)

    for index, payload in enumerate(cases):
        receipt = tmp_path / f"receipt-{index}.json"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and repository probe
            [
                sys.executable,
                "-I",
                "-S",
                str(SPIKE / "bundle" / "probe.py"),
                "--canonical-receipt",
                str(receipt),
            ],
            cwd=tmp_path,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            check=False,
        )

        assert completed.returncode == 2
        assert sentinel not in completed.stderr
