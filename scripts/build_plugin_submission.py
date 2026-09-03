"""Build a deterministic, minimal skills-only AtReady submission ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "atready"
# The Directory documents the compressed archive limit in decimal megabytes.
MAX_ARCHIVE_BYTES = 100_000_000
MAX_ARCHIVE_MEMBER_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_PATH_BYTES = 240
MAX_ARCHIVE_PATH_SEGMENTS = 20
MAX_ENTRIES = 5_000
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MAX_PNG_BYTES = 5 * 1024 * 1024
MAX_PNG_CHUNKS = 4096
FINAL_CATEGORIES = {
    "Business & Operations",
    "Communication",
    "Creativity",
    "Data & Analytics",
    "Developer Tools",
    "Education & Research",
    "Entertainment",
    "Finance",
    "Healthcare",
    "Other",
    "Productivity",
    "Security",
    "Travel",
}
INTERFACE_URL_FIELDS = (
    "websiteURL",
    "supportURL",
    "privacyPolicyURL",
    "termsOfServiceURL",
)
PLUGIN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


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


def _unsupported_text(value: str, *, allow_newlines: bool = False) -> bool:
    for character in value:
        if allow_newlines and character == "\n":
            continue
        if unicodedata.category(character) in {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}:
            return True
    return False


def _listing_text(
    value: object,
    *,
    field: str,
    maximum: int,
    allow_newlines: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or (not allow_newlines and ("\n" in value or "\r" in value))
        or _unsupported_text(value, allow_newlines=allow_newlines)
    ):
        line_rule = "" if allow_newlines else ", one-line"
        raise ValueError(
            f"{field} must be a non-empty{line_rule} supported-text string of at most "
            f"{maximum} characters"
        )
    return value


def _https_url(value: object, *, field: str, maximum: int) -> str:
    value = _listing_text(value, field=field, maximum=maximum)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid HTTPS URL without credentials") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "\\" in value
        or any(character.isspace() for character in value)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError(f"{field} must be a valid HTTPS URL without credentials")
    return value


def _contrast_against_white(value: object, *, field: str) -> None:
    value = _listing_text(value, field=field, maximum=7)
    if (
        len(value) != 7
        or value[0] != "#"
        or any(character not in "0123456789abcdefABCDEF" for character in value[1:])
    ):
        raise ValueError(f"{field} must be a six-digit hex color")
    channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    if 1.05 / (luminance + 0.05) < 2:
        raise ValueError(f"{field} must have at least 2:1 contrast against white")


def _validate_archive_names(names: list[str]) -> None:
    normalized: set[str] = set()
    for name in names:
        raw_parts = name.split("/")
        normalized_name = unicodedata.normalize("NFKC", name)
        normalized_parts = normalized_name.split("/")
        if (
            not name
            or name != name.strip()
            or "\\" in name
            or name.startswith("/")
            or "\\" in normalized_name
            or normalized_name.startswith("/")
            or any(part in {"", ".", ".."} for part in raw_parts)
            or any(part in {"", ".", ".."} for part in normalized_parts)
        ):
            raise ValueError(f"submission contains an unsafe archive path: {name!r}")
        if len(normalized_parts) > MAX_ARCHIVE_PATH_SEGMENTS:
            raise ValueError(
                f"submission archive path exceeds {MAX_ARCHIVE_PATH_SEGMENTS} segments: {name}"
            )
        if max(len(name.encode("utf-8")), len(normalized_name.encode("utf-8"))) > (
            MAX_ARCHIVE_PATH_BYTES
        ):
            raise ValueError(
                f"submission archive path exceeds the {MAX_ARCHIVE_PATH_BYTES}-byte internal "
                f"limit: {name}"
            )
        folded = "/".join(part.casefold() for part in normalized_parts)
        if folded in normalized:
            raise ValueError(
                "submission archive paths collide after case and Unicode normalization"
            )
        if any(
            folded.startswith(existing + "/") or existing.startswith(folded + "/")
            for existing in normalized
        ):
            raise ValueError(
                "submission archive paths conflict as a file and directory after case and "
                "Unicode normalization"
            )
        normalized.add(folded)


def _validate_listing_metadata(manifest: dict[str, object], interface: dict[str, object]) -> None:
    _listing_text(interface.get("displayName"), field="interface.displayName", maximum=30)
    _listing_text(
        interface.get("shortDescription"),
        field="interface.shortDescription",
        maximum=30,
    )
    _listing_text(
        interface.get("longDescription"),
        field="interface.longDescription",
        maximum=4_000,
        allow_newlines=True,
    )
    developer = _listing_text(
        interface.get("developerName"),
        field="interface.developerName",
        maximum=80,
    )
    author = manifest.get("author")
    if not isinstance(author, dict) or author.get("name") != developer:
        raise ValueError("author.name and interface.developerName must match")

    category = interface.get("category")
    if category not in FINAL_CATEGORIES:
        raise ValueError("interface.category must be a supported Directory category")

    capabilities = interface.get("capabilities")
    if not isinstance(capabilities, list) or len(capabilities) > 20:
        raise ValueError("interface.capabilities must be a list of at most 20 strings")
    for index, capability in enumerate(capabilities):
        _listing_text(
            capability,
            field=f"interface.capabilities[{index}]",
            maximum=120,
        )

    for field in INTERFACE_URL_FIELDS:
        if field in interface:
            _https_url(interface[field], field=f"interface.{field}", maximum=1_024)
    for field in ("homepage", "repository"):
        if field in manifest:
            _https_url(manifest[field], field=field, maximum=2_048)

    prompts = interface.get("defaultPrompt")
    if isinstance(prompts, str):
        prompts = [prompts]
    if not isinstance(prompts, list) or len(prompts) > 3:
        raise ValueError("interface.defaultPrompt must contain at most three strings")
    normalized_prompts: set[str] = set()
    for index, prompt in enumerate(prompts):
        prompt = _listing_text(
            prompt,
            field=f"interface.defaultPrompt[{index}]",
            maximum=128,
        )
        if re.search(r"@[A-Za-z0-9_]", prompt):
            raise ValueError("interface.defaultPrompt entries must not contain app @mentions")
        normalized = unicodedata.normalize("NFKC", " ".join(prompt.split())).casefold()
        if normalized in normalized_prompts:
            raise ValueError(
                "interface.defaultPrompt entries must be unique after Unicode and whitespace "
                "normalization"
            )
        normalized_prompts.add(normalized)

    if "brandColor" in interface:
        _contrast_against_white(interface["brandColor"], field="interface.brandColor")


def _square_png(path: Path) -> None:
    _safe_file(path)
    content = path.read_bytes()
    if len(content) > MAX_PNG_BYTES:
        raise ValueError(
            f"submission image must be square, 48-4096 px, and at most 5 MiB: {path.name}"
        )
    if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"submission image is not a readable PNG: {path.name}")

    offset = 8
    chunks = 0
    ihdr: bytes | None = None
    saw_idat = False
    saw_iend = False
    while offset < len(content):
        chunks += 1
        if chunks > MAX_PNG_CHUNKS or len(content) - offset < 12:
            raise ValueError(f"submission image is not a readable PNG: {path.name}")
        length = int.from_bytes(content[offset : offset + 4], "big")
        chunk_type = content[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if length > MAX_PNG_BYTES or crc_end > len(content):
            raise ValueError(f"submission image is not a readable PNG: {path.name}")
        chunk_data = content[data_start:data_end]
        expected_crc = int.from_bytes(content[data_end:crc_end], "big")
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise ValueError(f"submission image is not a readable PNG: {path.name}")
        if chunks == 1:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError(f"submission image is not a readable PNG: {path.name}")
            ihdr = chunk_data
        elif chunk_type == b"IHDR":
            raise ValueError(f"submission image is not a readable PNG: {path.name}")
        if chunk_type == b"IDAT":
            saw_idat = True
        if chunk_type == b"IEND":
            if length != 0 or saw_iend or crc_end != len(content):
                raise ValueError(f"submission image is not a readable PNG: {path.name}")
            saw_iend = True
        offset = crc_end

    if ihdr is None or not saw_idat or not saw_iend:
        raise ValueError(f"submission image is not a readable PNG: {path.name}")
    width = int.from_bytes(ihdr[0:4], "big")
    height = int.from_bytes(ihdr[4:8], "big")
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
    name = manifest.get("name")
    if not isinstance(name, str) or PLUGIN_NAME.fullmatch(name) is None:
        raise ValueError(
            "plugin manifest name must start with an ASCII letter or digit, contain only ASCII "
            "letters, digits, underscores, or hyphens, and be at most 64 characters"
        )
    _listing_text(
        manifest.get("description"),
        field="description",
        maximum=1_024,
        allow_newlines=True,
    )
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        raise ValueError("plugin manifest lacks interface metadata")
    if "screenshots" in interface:
        raise ValueError("skills-only submission must not declare screenshots")
    _validate_listing_metadata(manifest, interface)
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
    _validate_archive_names(names)
    sizes = [path.stat().st_size for _, path in files]
    if any(size > MAX_ARCHIVE_MEMBER_BYTES for size in sizes):
        raise ValueError("submission contains a file over the 100 MiB archive-member limit")
    total = sum(sizes)
    if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise ValueError("submission exceeds the 512 MiB uncompressed size bound")
    version = manifest.get("version")
    if not isinstance(version, str) or len(version) > 64 or SEMVER.fullmatch(version) is None:
        raise ValueError(
            "plugin manifest version must be semantic versioning at most 64 characters"
        )
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
        if temporary.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("submission ZIP exceeds the 100 MB compressed size bound")
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
