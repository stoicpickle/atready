"""Build a deterministic, minimal skills-only AtReady submission ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "atready"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_ENTRIES = 5_000
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _strict_json(path: Path) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def _safe_file(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ValueError(f"submission input is not a regular file: {path.relative_to(PLUGIN)}")


def _safe_directory(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise ValueError(f"submission input is not a real directory: {path.relative_to(PLUGIN)}")


def _square_png(path: Path) -> None:
    _safe_file(path)
    content = path.read_bytes()
    if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n" or content[12:16] != b"IHDR":
        raise ValueError(f"submission image is not a readable PNG: {path.name}")
    width = int.from_bytes(content[16:20], "big")
    height = int.from_bytes(content[20:24], "big")
    if width != height or not 48 <= width <= 4096 or len(content) > 5 * 1024 * 1024:
        raise ValueError(
            f"submission image must be square, 48-4096 px, and at most 5 MiB: {path.name}"
        )


def _inputs() -> tuple[str, list[tuple[PurePosixPath, Path]]]:
    for directory in (
        PLUGIN,
        PLUGIN / ".codex-plugin",
        PLUGIN / "assets",
        PLUGIN / "skills",
        PLUGIN / "skills" / "project-atready",
    ):
        _safe_directory(directory)
    manifest_path = PLUGIN / ".codex-plugin" / "plugin.json"
    manifest = _strict_json(manifest_path)
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        raise ValueError("plugin manifest lacks interface metadata")
    if "screenshots" in interface:
        raise ValueError("skills-only submission must not declare screenshots")
    for field in ("displayName", "shortDescription"):
        value = interface.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 30:
            raise ValueError(
                f"interface.{field} must be a non-empty string of at most 30 characters"
            )
    if (
        interface.get("logo") != "./assets/icon.png"
        or interface.get("composerIcon") != "./assets/icon.png"
    ):
        raise ValueError(
            "skills-only submission must use the reviewed square icon for logo and composerIcon"
        )
    icon = PLUGIN / "assets" / "icon.png"
    _square_png(icon)

    skill_root = PLUGIN / "skills" / "project-atready"
    if not (skill_root / "SKILL.md").is_file():
        raise ValueError("submission lacks skills/project-atready/SKILL.md")
    files = [
        (PurePosixPath(".codex-plugin/plugin.json"), manifest_path),
        (PurePosixPath("assets/icon.png"), icon),
    ]
    for path in sorted(skill_root.rglob("*")):
        metadata = path.lstat()
        if path.is_symlink():
            raise ValueError(f"submission input is a symbolic link: {path.relative_to(PLUGIN)}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        _safe_file(path)
        relative = PurePosixPath("skills/project-atready") / PurePosixPath(
            path.relative_to(skill_root).as_posix()
        )
        if any(part in {"__pycache__", ".git"} for part in relative.parts):
            raise ValueError(
                f"submission contains a forbidden cache or repository path: {relative}"
            )
        files.append((relative, path))
    files.sort(key=lambda item: str(item[0]))
    names = [str(name) for name, _ in files]
    if len(names) > MAX_ENTRIES or len(names) != len(set(names)):
        raise ValueError("submission entry count is invalid")
    if any(name.startswith("/") or ".." in PurePosixPath(name).parts for name in names):
        raise ValueError("submission contains an unsafe archive path")
    total = sum(path.stat().st_size for _, path in files)
    if total > MAX_ARCHIVE_BYTES:
        raise ValueError("submission exceeds the uncompressed size bound")
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("plugin manifest lacks a version")
    return version, files


def build(output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing submission bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    version, files = _inputs()
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for archive_path, source in files:
                info = zipfile.ZipInfo(str(archive_path), ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, source.read_bytes())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {
        "entries": len(files),
        "output": str(output.resolve()),
        "plugin_version": version,
        "sha256": digest,
        "submission_type": "skills-only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
