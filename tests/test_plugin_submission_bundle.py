from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_plugin_submission.py"
SPEC = importlib.util.spec_from_file_location("atready_submission_builder", BUILDER_PATH)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _build(output: Path) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/build_plugin_submission.py", "--output", str(output)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_submission_bundle_is_minimal_safe_and_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first_receipt = _build(first)
    second_receipt = _build(second)

    assert first.read_bytes() == second.read_bytes()
    assert first_receipt["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first_receipt["sha256"] == second_receipt["sha256"]
    assert first_receipt["plugin_version"] == "0.1.11"
    assert first_receipt["submission_type"] == "skills-only"

    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert len(names) == len(set(names)) == first_receipt["entries"]
        assert ".codex-plugin/plugin.json" in names
        assert "assets/icon.png" in names
        assert "skills/project-atready/SKILL.md" in names
        assert "skills/project-quartermaster/SKILL.md" not in names
        assert not any(name.startswith("apps/") or "/__pycache__/" in name for name in names)
        assert not any("screenshot" in name or name.endswith("logo.png") for name in names)
        manifest = json.loads(archive.read(".codex-plugin/plugin.json"))
        assert manifest["version"] == first_receipt["plugin_version"] == "0.1.11"
        assert "screenshots" not in manifest["interface"]
        assert manifest["interface"]["logo"] == "./assets/icon.png"
        assert manifest["interface"]["composerIcon"] == "./assets/icon.png"


def test_submission_builder_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "submission.zip"
    _build(output)
    original = output.read_bytes()
    result = subprocess.run(  # noqa: S603
        [sys.executable, "scripts/build_plugin_submission.py", "--output", str(output)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "refusing to overwrite existing submission bundle" in result.stderr
    assert output.read_bytes() == original


def test_submission_builder_rejects_symlinked_directories(monkeypatch, tmp_path: Path) -> None:
    plugin = tmp_path / "atready"
    shutil.copytree(builder.PLUGIN, plugin)
    target = tmp_path / "outside"
    target.mkdir()
    link = plugin / "skills" / "project-atready" / "references" / "linked-directory"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("this platform does not permit directory symlinks")
    monkeypatch.setattr(builder, "PLUGIN", plugin)

    with pytest.raises(ValueError, match="symbolic link"):
        builder._inputs()


def test_submission_builder_rejects_a_symlinked_skill_root(monkeypatch, tmp_path: Path) -> None:
    plugin = tmp_path / "atready"
    shutil.copytree(builder.PLUGIN, plugin)
    skill_root = plugin / "skills" / "project-atready"
    shutil.rmtree(skill_root)
    try:
        skill_root.symlink_to(
            builder.PLUGIN / "skills" / "project-atready",
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("this platform does not permit directory symlinks")
    monkeypatch.setattr(builder, "PLUGIN", plugin)

    with pytest.raises(ValueError, match="not a real directory"):
        builder._inputs()
