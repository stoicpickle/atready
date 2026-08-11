from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "elevated_install_matrix.py"


def _namespace() -> dict[str, object]:
    spec = importlib.util.spec_from_file_location("elevated_install_matrix", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return vars(module)


def test_elevated_install_matrix_passes_inside_a_disposable_root(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--root", str(tmp_path / "matrix")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["result"] == "passed"
    assert receipt["synthetic_only"] is True
    assert receipt["mutation_scope"] == "caller-provided-isolated-directory-only"
    assert receipt["checks"] == [
        "fresh-compatible-runtime-handshake",
        "stale-runtime-rejected-before-delegation",
        "incomplete-runtime-rejected-before-delegation",
        "complete-skill-bundle-detected",
        "incomplete-skill-bundle-detected",
        "divergent-duplicate-skill-precedence-risk-detected",
        "no-private-state-write",
    ]
    assert receipt["duplicate_probe"]["duplicate_risk"] is True
    assert receipt["duplicate_probe"]["content_mismatch"] is True
    assert not list(tmp_path.rglob("private-state-must-not-exist"))

    payload = _namespace()["_runtime_payload"](plugin_version="0.1.7")
    assert payload["plugin_version"] == "0.1.7"
    assert "routing.presentation-bundle.v1" in payload["runtime_features"]


def test_skill_precedence_probe_distinguishes_missing_incomplete_and_matching_duplicates(
    tmp_path: Path,
) -> None:
    inspect = _namespace()["inspect_skill_precedence"]
    complete = tmp_path / "complete"
    matching = tmp_path / "matching"
    incomplete = tmp_path / "incomplete"
    required = (
        Path("SKILL.md"),
        Path("scripts/atready.py"),
        Path("references/output-contract.md"),
        Path("references/routing-rules.md"),
        Path("references/runtime-setup.md"),
    )
    for root in (complete, matching):
        for relative in required:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"synthetic {relative.as_posix()}\n", encoding="utf-8")
    incomplete.mkdir()
    (incomplete / "SKILL.md").write_text("synthetic incomplete\n", encoding="utf-8")

    report = inspect([tmp_path / "missing", incomplete, complete, matching])

    assert [location["status"] for location in report["locations"]] == [
        "not-found",
        "incomplete",
        "ready",
        "ready",
    ]
    assert report["assumed_effective_path"] == str(complete)
    assert report["ready_count"] == 2
    assert report["duplicate_risk"] is True
    assert report["content_mismatch"] is False


def test_matrix_refuses_to_reuse_a_nonempty_or_existing_root(tmp_path: Path) -> None:
    run_matrix = _namespace()["run_matrix"]
    existing = tmp_path / "existing"
    existing.mkdir()

    with pytest.raises(FileExistsError):
        run_matrix(existing)


def test_root_help_requires_a_new_path_beneath_a_disposable_directory() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    normalized = " ".join(result.stdout.split())
    assert "new path beneath a disposable directory" in normalized
    assert "path must not already exist" in normalized
