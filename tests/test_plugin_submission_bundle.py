from __future__ import annotations

import hashlib
import importlib.util
import json
import runpy
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


def _plugin_with_manifest_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutate,
) -> Path:
    plugin = tmp_path / "atready"
    shutil.copytree(builder.PLUGIN, plugin)
    manifest_path = plugin / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(builder, "PLUGIN", plugin)
    return plugin


def test_submission_bundle_is_minimal_safe_and_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    first_receipt = _build(first)
    second_receipt = _build(second)

    assert first.read_bytes() == second.read_bytes()
    assert first_receipt["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first_receipt["sha256"] == second_receipt["sha256"]
    assert first_receipt["plugin_version"] == "0.1.13"
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
        assert manifest["version"] == first_receipt["plugin_version"] == "0.1.13"
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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda manifest: manifest["interface"].update(
                {"capabilities": [f"Capability {index}" for index in range(21)]}
            ),
            "at most 20 strings",
        ),
        (
            lambda manifest: manifest["interface"].update(
                {"supportURL": "https://user:password@example.com/support"}
            ),
            "valid HTTPS URL without credentials",
        ),
        (
            lambda manifest: manifest["interface"].update(
                {"defaultPrompt": ["Review my plan", "  REVIEW   MY PLAN  "]}
            ),
            "unique after Unicode and whitespace normalization",
        ),
        (
            lambda manifest: manifest["interface"].update(
                {"defaultPrompt": ["Ask @AtReady to review this plan"]}
            ),
            "must not contain app @mentions",
        ),
        (
            lambda manifest: manifest["interface"].update({"brandColor": "#FFFFFF"}),
            "at least 2:1 contrast against white",
        ),
        (
            lambda manifest: manifest["interface"].update({"longDescription": "x" * 4_001}),
            "at most 4000 characters",
        ),
        (
            lambda manifest: manifest.update({"name": "invalid name"}),
            "plugin manifest name must start",
        ),
        (
            lambda manifest: manifest.update({"version": "version-one"}),
            "version must be semantic versioning",
        ),
    ],
    ids=(
        "too-many-capabilities",
        "credentialed-support-url",
        "normalized-duplicate-prompts",
        "app-mention",
        "weak-brand-contrast",
        "long-description",
        "invalid-plugin-name",
        "invalid-version",
    ),
)
def test_submission_builder_enforces_final_directory_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    _plugin_with_manifest_mutation(monkeypatch, tmp_path, mutation)

    with pytest.raises(ValueError, match=message):
        builder._inputs()


def test_submission_zip_round_trips_through_staged_plugin_smoke(tmp_path: Path) -> None:
    bundle = tmp_path / "submission.zip"
    _build(bundle)

    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(extracted)

    plugin = extracted
    assert {path.name for path in (plugin / "assets").iterdir()} == {"icon.png"}

    # Exercise the extracted submission from a disposable shadow checkout rather
    # than accidentally rechecking the canonical plugin tree.
    shadow = tmp_path / "smoke-checkout"
    (shadow / "scripts").mkdir(parents=True)
    shutil.copytree(ROOT / "src", shadow / "src")
    shutil.copytree(ROOT / "evals" / "fixtures", shadow / "evals" / "fixtures")
    shutil.copytree(plugin, shadow / "plugins" / "atready")
    smoke = runpy.run_path(str(ROOT / "scripts" / "smoke_plugin.py"))
    smoke["main_smoke"](
        repository_root=shadow,
        expected_png_assets={"icon.png": (512, 512)},
    )


@pytest.mark.parametrize("mutation", ["truncated", "crc-invalid"])
def test_submission_builder_rejects_truncated_or_crc_invalid_icon(
    monkeypatch, tmp_path: Path, mutation: str
) -> None:
    plugin = tmp_path / "atready"
    shutil.copytree(builder.PLUGIN, plugin)
    icon = plugin / "assets" / "icon.png"
    content = bytearray(icon.read_bytes())
    if mutation == "truncated":
        icon.write_bytes(content[:-1])
    else:
        content[29] ^= 1  # corrupt the IHDR CRC while retaining the PNG shape
        icon.write_bytes(content)
    monkeypatch.setattr(builder, "PLUGIN", plugin)
    output = tmp_path / "submission.zip"

    with pytest.raises(ValueError, match="readable PNG"):
        builder.build(output)
    assert not output.exists()


def test_submission_builder_rejects_deep_long_and_normalized_collision_paths() -> None:
    deep = "/".join(["part"] * builder.MAX_ARCHIVE_PATH_SEGMENTS + ["file.txt"])
    with pytest.raises(ValueError, match="exceeds 20 segments"):
        builder._validate_archive_names([deep])

    long_name = "x" * (builder.MAX_ARCHIVE_PATH_BYTES + 1)
    with pytest.raises(ValueError, match="240-byte internal limit"):
        builder._validate_archive_names([long_name])

    with pytest.raises(ValueError, match="case and Unicode normalization"):
        builder._validate_archive_names(["skills/Café/SKILL.md", "skills/Café/SKILL.md"])

    with pytest.raises(ValueError, match="unsafe archive path"):
        builder._validate_archive_names(["skills/\uff0e\uff0e/SKILL.md"])

    for names in (["Foo", "foo/bar"], ["foo/bar", "Foo"]):
        with pytest.raises(ValueError, match="conflict as a file and directory"):
            builder._validate_archive_names(names)


def test_submission_builder_checks_final_zip_size(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "submission.zip"
    monkeypatch.setattr(builder, "MAX_ARCHIVE_BYTES", 1)

    with pytest.raises(ValueError, match="compressed size bound"):
        builder.build(output)
    assert not output.exists()


def test_submission_builder_accepts_exact_compressed_size_boundary(
    monkeypatch, tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.zip"
    builder.build(baseline)
    exact_size = baseline.stat().st_size
    monkeypatch.setattr(builder, "MAX_ARCHIVE_BYTES", exact_size)

    output = tmp_path / "submission.zip"
    builder.build(output)

    assert output.stat().st_size == exact_size
