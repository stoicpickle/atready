from __future__ import annotations

import json
import os
import runpy
import stat
from pathlib import Path

import pytest

from atready import __version__
from atready.cli import main
from atready.runtime_contract import (
    RUNTIME_CONTRACT_VERSION,
    SUPPORTED_RUNTIME_FEATURE_IDS,
    doctor_payload,
    runtime_contract_payload,
)

ROOT = Path(__file__).parents[1]
SMOKE_WHEEL_NAMESPACE = runpy.run_path(str(ROOT / "scripts" / "smoke_wheel.py"))
PRIVATE_STATE_SNAPSHOT = SMOKE_WHEEL_NAMESPACE["_private_state_snapshot"]


def test_wheel_smoke_private_state_snapshot_records_directories_and_symlinks(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(nested, target_is_directory=True)
    except OSError:
        link = None

    snapshot = PRIVATE_STATE_SNAPSHOT(tmp_path)
    root_entry = next(entry for entry in snapshot if entry[:2] == (".", "directory"))
    root_metadata = tmp_path.lstat()
    assert root_entry[2] == (
        root_metadata.st_dev,
        root_metadata.st_ino,
        stat.S_IMODE(root_metadata.st_mode),
        root_metadata.st_ctime_ns,
    )
    assert ("nested", "directory", None) in snapshot
    if link is not None:
        assert ("link", "symlink", os.readlink(link)) in snapshot


@pytest.mark.parametrize("replacement", ["missing", "file", "symlink"])
def test_wheel_smoke_private_state_snapshot_rejects_non_directory_roots(
    tmp_path: Path, replacement: str
) -> None:
    root = tmp_path / "state"
    if replacement == "file":
        root.write_text("synthetic", encoding="utf-8")
    elif replacement == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        try:
            root.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("this platform does not permit symlink creation")

    with pytest.raises(AssertionError, match="private state root"):
        PRIVATE_STATE_SNAPSHOT(root)


def test_wheel_smoke_private_state_snapshot_detects_root_replacement(tmp_path: Path) -> None:
    root = tmp_path / "state"
    root.mkdir()
    before = PRIVATE_STATE_SNAPSHOT(root)
    assert PRIVATE_STATE_SNAPSHOT(root) == before
    root.rmdir()
    root.mkdir()

    assert PRIVATE_STATE_SNAPSHOT(root) != before


def test_runtime_contract_is_deterministic_value_free_and_side_effect_free(capsys) -> None:
    expected = runtime_contract_payload()

    assert expected == {
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "features": list(SUPPORTED_RUNTIME_FEATURE_IDS),
        "inventory_read": False,
        "network_accessed": False,
        "product": "project-atready",
        "runtime_version": __version__,
        "writes_performed": False,
    }
    assert list(SUPPORTED_RUNTIME_FEATURE_IDS) == sorted(set(SUPPORTED_RUNTIME_FEATURE_IDS))
    assert "routing.presentation-bundle.v1" in SUPPORTED_RUNTIME_FEATURE_IDS
    assert "routing.agent-summary.v1" in SUPPORTED_RUNTIME_FEATURE_IDS
    assert "routing.capacity-demand.v1" in SUPPORTED_RUNTIME_FEATURE_IDS
    assert "routing.compare.v1" in SUPPORTED_RUNTIME_FEATURE_IDS
    assert "resource.quick-preview.v1" in SUPPORTED_RUNTIME_FEATURE_IDS

    assert main(["runtime", "contract", "--json"]) == 0
    first = capsys.readouterr()
    assert main(["runtime", "contract", "--json"]) == 0
    second = capsys.readouterr()
    assert first.err == second.err == ""
    assert first.out == second.out
    assert json.loads(first.out) == expected
    assert "inventory_path" not in first.out.casefold()
    assert json.loads(first.out)["inventory_read"] is False


def test_doctor_human_output_explains_effect_boundaries(capsys) -> None:
    required = SUPPORTED_RUNTIME_FEATURE_IDS[:2]
    arguments = [
        "doctor",
        "--plugin-version",
        "9.9.9",
        "--plugin-contract",
        str(RUNTIME_CONTRACT_VERSION),
    ]
    for feature_id in required:
        arguments.extend(("--require-feature", feature_id))
    assert main(arguments) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "local runtime is ready for this plugin contract" in captured.out
    assert "Plugin version checked: 9.9.9 (informational only)" in captured.out
    assert "Inventory read: false" in captured.out
    assert "Network accessed: false" in captured.out
    assert "Writes performed: false" in captured.out
    for feature_id in SUPPORTED_RUNTIME_FEATURE_IDS:
        assert feature_id in captured.out


def test_bare_doctor_reports_a_runtime_self_check_not_plugin_compatibility(capsys) -> None:
    assert main(["doctor"]) == 0

    captured = capsys.readouterr()
    assert "runtime self-check passed" in captured.out
    assert "no plugin requirements were supplied" in captured.out
    assert "ready for this plugin contract" not in captured.out
    assert captured.err == ""


def test_doctor_rejects_incompatible_contract_without_exposing_values(capsys) -> None:
    assert (
        main(
            [
                "doctor",
                "--plugin-version",
                "9.9.9",
                "--plugin-contract",
                str(RUNTIME_CONTRACT_VERSION + 1),
                "--require-feature",
                "synthetic.unsupported.v1",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload == doctor_payload(
        plugin_version="9.9.9",
        plugin_contract_version=RUNTIME_CONTRACT_VERSION + 1,
        required_features=("synthetic.unsupported.v1",),
    )
    assert payload["compatible"] is False
    assert payload["status"] == "incompatible"


def test_doctor_rejects_a_missing_feature_with_a_matching_contract(capsys) -> None:
    assert (
        main(
            [
                "doctor",
                "--plugin-version",
                "9.9.9",
                "--plugin-contract",
                str(RUNTIME_CONTRACT_VERSION),
                "--require-feature",
                "synthetic.unsupported.v1",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["compatible"] is False
    assert payload["status"] == "incompatible"
    assert payload["missing_features"] == ["synthetic.unsupported.v1"]
