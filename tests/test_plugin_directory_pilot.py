from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PILOT_PATH = ROOT / "scripts" / "prepare_plugin_directory_pilot.py"
SPEC = importlib.util.spec_from_file_location("atready_directory_pilot", PILOT_PATH)
assert SPEC is not None and SPEC.loader is not None
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


@pytest.fixture
def clean_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pilot, "_source_state", lambda: ("b" * 40, True))


def test_local_pilot_is_deterministic_value_safe_and_fail_closed(
    clean_source: None, tmp_path: Path
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = pilot.prepare(first_dir)
    second = pilot.prepare(second_dir)

    assert first == second
    assert (first_dir / pilot.BUNDLE_NAME).read_bytes() == (
        second_dir / pilot.BUNDLE_NAME
    ).read_bytes()
    assert (first_dir / pilot.RECEIPT_NAME).read_bytes() == (
        second_dir / pilot.RECEIPT_NAME
    ).read_bytes()
    assert json.loads((first_dir / pilot.RECEIPT_NAME).read_text(encoding="utf-8")) == first
    assert first["development_only"] is False
    assert first["source"]["clean"] is True
    assert first["candidate_policy"] == pilot.EXPECTED_POLICY
    assert first["external_actions"] == {
        "network_accessed": False,
        "portal_draft_created": False,
        "portal_upload_performed": False,
        "submitted_for_review": False,
        "published": False,
        "plugin_installed": False,
        "runtime_installed": False,
    }
    assert first["live_surfaces"] == {surface: "unproved" for surface in pilot.LIVE_SURFACES}
    serialized = json.dumps(first, sort_keys=True)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized


def test_pilot_refuses_dirty_source_unless_explicitly_development_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pilot, "_source_state", lambda: ("a" * 40, False))

    with pytest.raises(ValueError, match="refusing dirty source"):
        pilot.prepare(tmp_path / "refused")
    assert not (tmp_path / "refused").exists()

    receipt = pilot.prepare(tmp_path / "development", allow_dirty=True)
    assert receipt["development_only"] is True
    assert receipt["source"] == {"commit": "a" * 40, "clean": False}


def test_pilot_refuses_existing_or_symlinked_output_directories(
    clean_source: None, tmp_path: Path
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="existing pilot output"):
        pilot.prepare(existing)

    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "link"
    try:
        symlink.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("this platform does not permit directory symlinks")
    with pytest.raises(ValueError, match="existing pilot output"):
        pilot.prepare(symlink)


def test_pilot_refuses_output_inside_the_source_repository(
    clean_source: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    monkeypatch.setattr(pilot, "ROOT", repository)
    output = repository / "pilot-output"

    with pytest.raises(ValueError, match="outside the source repository"):
        pilot.prepare(output)
    assert not output.exists()


def test_clean_pilot_refuses_source_change_during_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    states = iter((("a" * 40, True), ("a" * 40, False)))
    monkeypatch.setattr(pilot, "_source_state", lambda: next(states))
    output = tmp_path / "changed"

    with pytest.raises(ValueError, match="source changed while preparing"):
        pilot.prepare(output)
    assert not output.exists()


def test_pilot_uses_only_fixed_local_git_reads_and_the_existing_builder() -> None:
    tree = ast.parse(PILOT_PATH.read_text(encoding="utf-8"), filename=str(PILOT_PATH))
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert not imports.intersection({"http", "requests", "socket", "urllib"})
    source = PILOT_PATH.read_text(encoding="utf-8")
    assert "submission_builder.build(destination / BUNDLE_NAME)" in source
    assert '"rev-parse", "--verify", "HEAD"' in source
    assert '"status", "--porcelain=v1", "--untracked-files=all"' in source
    assert 'portal_draft_created": False' in source
    assert 'plugin_installed": False' in source
