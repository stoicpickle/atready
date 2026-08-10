"""Verify the exact wheel and source-distribution content boundary."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
import stat
import sys
import tarfile
import tomllib
import zipfile
from collections import Counter
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from release_bundle import (
    ReleaseBundleError,
    _expected_artifacts,
    _refuse_unexpected_entries,
    _release_contract,
    _resolve_dist,
)

_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_FILE = _ROOT / "pyproject.toml"
_PACKAGE_SOURCE = _ROOT / "src" / "atready"
_SKILL_SOURCE = _ROOT / "plugins" / "atready" / "skills" / "project-atready"
_MAX_ARCHIVE_MEMBERS = 512
_MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
_DEPENDENCY_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(.*)$")
_SPECIFIER_PATTERN = re.compile(r"(?:===|==|~=|!=|<=|>=|<|>)[^,;\s]+")


def _validate_member_names(names: list[str], *, archive_name: str) -> None:
    if len(names) > _MAX_ARCHIVE_MEMBERS:
        raise ReleaseBundleError(f"{archive_name} contains too many members")
    if len(names) != len(set(names)):
        raise ReleaseBundleError(f"{archive_name} contains duplicate member names")
    folded = [name.casefold() for name in names]
    if len(folded) != len(set(folded)):
        raise ReleaseBundleError(f"{archive_name} contains case-colliding member names")
    for name in names:
        path = PurePosixPath(name)
        raw_parts = name.split("/")
        if (
            not name
            or "\\" in name
            or name.startswith("/")
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in raw_parts)
        ):
            raise ReleaseBundleError(f"{archive_name} contains an unsafe member name")


def _source_map(root: Path, destination: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ReleaseBundleError(
                f"release source contains a symlink: {path.relative_to(_ROOT)}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise ReleaseBundleError(
                f"release source is not a regular file: {path.relative_to(_ROOT)}"
            )
        name = f"{destination}/{relative.as_posix()}"
        files[name] = path.read_bytes()
    return files


def _dependency_identity(value: str, *, filename: str) -> tuple[str, tuple[str, ...]]:
    match = _DEPENDENCY_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ReleaseBundleError(f"{filename} contains an invalid dependency requirement")
    name, specifier_text = match.groups()
    if any(marker in specifier_text for marker in (";", "@", "[", "]")):
        raise ReleaseBundleError(f"{filename} uses an unsupported dependency requirement form")
    specifiers = tuple(sorted(part.strip() for part in specifier_text.split(",") if part.strip()))
    if any(_SPECIFIER_PATTERN.fullmatch(specifier) is None for specifier in specifiers):
        raise ReleaseBundleError(f"{filename} contains an invalid dependency specifier")
    normalized_name = re.sub(r"[-_.]+", "-", name).lower()
    return normalized_name, specifiers


def _project_document() -> dict[str, object]:
    try:
        document = tomllib.loads(_PROJECT_FILE.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise ReleaseBundleError("pyproject.toml is not valid UTF-8 TOML") from exc
    if not isinstance(document, dict):
        raise ReleaseBundleError("pyproject.toml does not contain a document")
    return document


def _canonical_utf8_text(data: object, *, filename: str) -> str:
    if not isinstance(data, bytes):
        raise ReleaseBundleError(f"{filename} is not byte content")
    try:
        text = data.decode("utf-8")
    except UnicodeError as exc:
        raise ReleaseBundleError(f"{filename} is not valid UTF-8") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _metadata_identity(data: bytes, *, filename: str) -> None:
    project, _, version, _ = _release_contract()
    metadata = BytesParser(policy=policy.default).parsebytes(data)
    try:
        project_table = _project_document()["project"]
    except KeyError as exc:
        raise ReleaseBundleError("pyproject.toml does not contain a valid project table") from exc
    if not isinstance(project_table, dict):
        raise ReleaseBundleError("pyproject.toml does not contain a valid project table")
    requires_python = project_table.get("requires-python")
    dependencies = project_table.get("dependencies")
    optional_dependencies = project_table.get("optional-dependencies")
    summary = project_table.get("description")
    authors = project_table.get("authors")
    license_expression = project_table.get("license")
    license_files = project_table.get("license-files")
    keywords = project_table.get("keywords")
    classifiers = project_table.get("classifiers")
    project_urls = project_table.get("urls")
    readme = project_table.get("readme")
    if not isinstance(requires_python, str) or not isinstance(dependencies, list):
        raise ReleaseBundleError("pyproject.toml has an invalid installation metadata contract")
    if optional_dependencies not in (None, {}):
        raise ReleaseBundleError(
            "release metadata verification does not support optional dependencies"
        )
    if any(not isinstance(dependency, str) for dependency in dependencies):
        raise ReleaseBundleError("pyproject.toml contains a non-string dependency")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or not isinstance(authors, list)
        or len(authors) != 1
        or not isinstance(authors[0], dict)
        or set(authors[0]) != {"name"}
        or not isinstance(authors[0]["name"], str)
        or not authors[0]["name"].strip()
        or not isinstance(license_expression, str)
        or not license_expression.strip()
        or not isinstance(license_files, list)
        or not license_files
        or any(not isinstance(value, str) or not value for value in license_files)
        or len(license_files) != len(set(license_files))
        or not isinstance(keywords, list)
        or not keywords
        or any(not isinstance(value, str) or not value for value in keywords)
        or len(keywords) != len(set(keywords))
        or not isinstance(classifiers, list)
        or not classifiers
        or any(not isinstance(value, str) or not value for value in classifiers)
        or len(classifiers) != len(set(classifiers))
        or not isinstance(project_urls, dict)
        or not project_urls
        or any(
            not isinstance(label, str)
            or not label
            or not isinstance(url, str)
            or not url.startswith("https://")
            for label, url in project_urls.items()
        )
        or readme != "README.md"
    ):
        raise ReleaseBundleError("pyproject.toml has an invalid public metadata contract")

    exact_headers = {
        "Metadata-Version": "2.4",
        "Name": project,
        "Version": version,
        "Requires-Python": requires_python,
        "Summary": summary,
        "Author": authors[0]["name"],
        "License-Expression": license_expression,
        "Keywords": ",".join(sorted(keywords)),
        "Description-Content-Type": "text/markdown",
    }
    if any(metadata.get_all(header) != [expected] for header, expected in exact_headers.items()):
        raise ReleaseBundleError(f"{filename} does not match the project identity")
    expected_urls = [f"{label}, {url}" for label, url in project_urls.items()]
    if (
        metadata.get_all("License-File") != license_files
        or metadata.get_all("Classifier") != classifiers
        or metadata.get_all("Project-URL") != expected_urls
    ):
        raise ReleaseBundleError(f"{filename} does not match the public project metadata")
    description_bytes = metadata.get_payload(decode=True)
    description = _canonical_utf8_text(description_bytes, filename=f"{filename} long description")
    committed = _canonical_utf8_text(
        (_ROOT / readme).read_bytes(),
        filename="committed README.md",
    )
    if description != committed:
        raise ReleaseBundleError(f"{filename} long description differs from committed README.md")
    prohibited_headers = (
        "Author-email",
        "Dynamic",
        "Home-page",
        "License",
        "Maintainer",
        "Maintainer-email",
        "Obsoletes",
        "Obsoletes-Dist",
        "Provides",
        "Provides-Dist",
        "Provides-Extra",
        "Requires",
        "Requires-External",
    )
    if any(metadata.get_all(header) for header in prohibited_headers):
        raise ReleaseBundleError(f"{filename} contains unexpected or legacy project metadata")

    expected_dependencies = Counter(
        _dependency_identity(dependency, filename="pyproject.toml") for dependency in dependencies
    )
    actual_dependencies = Counter(
        _dependency_identity(dependency, filename=filename)
        for dependency in metadata.get_all("Requires-Dist", [])
    )
    if actual_dependencies != expected_dependencies:
        raise ReleaseBundleError(f"{filename} dependencies do not match pyproject.toml")


def _verify_record(contents: dict[str, bytes], *, record_name: str) -> None:
    try:
        text = contents[record_name].decode("utf-8")
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except (KeyError, UnicodeError, csv.Error) as exc:
        raise ReleaseBundleError("wheel RECORD is unavailable or invalid") from exc
    if any(len(row) != 3 for row in rows):
        raise ReleaseBundleError("wheel RECORD contains a malformed row")
    recorded = {row[0]: (row[1], row[2]) for row in rows}
    if len(recorded) != len(rows) or set(recorded) != set(contents):
        raise ReleaseBundleError("wheel RECORD does not enumerate every member exactly once")
    for name, data in contents.items():
        digest, size = recorded[name]
        if name == record_name:
            if digest or size:
                raise ReleaseBundleError("wheel RECORD hashes itself")
            continue
        expected_digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
        if digest != f"sha256={expected_digest.decode('ascii')}" or size != str(len(data)):
            raise ReleaseBundleError(f"wheel RECORD does not match member: {name}")


def _verify_wheel(path: Path) -> None:
    _, normalized, version, _ = _release_contract()
    dist_info = f"{normalized}-{version}.dist-info"
    expected = _source_map(_PACKAGE_SOURCE, "atready")
    expected.update(_source_map(_SKILL_SOURCE, "atready/bundled_skill"))
    generated = {
        f"{dist_info}/METADATA",
        f"{dist_info}/WHEEL",
        f"{dist_info}/entry_points.txt",
        f"{dist_info}/licenses/LICENSE",
        f"{dist_info}/licenses/NOTICE",
        f"{dist_info}/RECORD",
    }
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            _validate_member_names(names, archive_name=path.name)
            total = 0
            contents: dict[str, bytes] = {}
            for member in members:
                mode = member.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if member.is_dir() or file_type not in {0, stat.S_IFREG} or member.flag_bits & 0x1:
                    raise ReleaseBundleError(
                        f"wheel contains a non-regular member: {member.filename}"
                    )
                total += member.file_size
                if member.file_size > _MAX_UNCOMPRESSED_BYTES or total > _MAX_UNCOMPRESSED_BYTES:
                    raise ReleaseBundleError("wheel expands beyond the release bound")
                contents[member.filename] = archive.read(member)
    except zipfile.BadZipFile as exc:
        raise ReleaseBundleError("wheel is not a valid ZIP archive") from exc

    if set(contents) != set(expected) | generated:
        raise ReleaseBundleError(
            "wheel contents do not match the package and bundled-skill contract"
        )
    for name, data in expected.items():
        if contents[name] != data:
            raise ReleaseBundleError(f"wheel member differs from committed source: {name}")
    if contents[f"{dist_info}/licenses/LICENSE"] != (_ROOT / "LICENSE").read_bytes():
        raise ReleaseBundleError("wheel LICENSE differs from committed source")
    if contents[f"{dist_info}/licenses/NOTICE"] != (_ROOT / "NOTICE").read_bytes():
        raise ReleaseBundleError("wheel NOTICE differs from committed source")
    _metadata_identity(contents[f"{dist_info}/METADATA"], filename="wheel METADATA")
    document = _project_document()
    project_table = document.get("project")
    build_system = document.get("build-system")
    if not isinstance(project_table, dict) or not isinstance(build_system, dict):
        raise ReleaseBundleError("pyproject.toml does not contain the release build contract")
    scripts = project_table.get("scripts")
    build_requirements = build_system.get("requires")
    if (
        not isinstance(scripts, dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in scripts.items()
        )
        or not isinstance(build_requirements, list)
        or len(build_requirements) != 1
        or not isinstance(build_requirements[0], str)
        or not build_requirements[0].startswith("hatchling==")
    ):
        raise ReleaseBundleError("pyproject.toml has an invalid wheel installation contract")
    expected_entry_points = "[console_scripts]\n" + "".join(
        f"{name} = {target}\n" for name, target in sorted(scripts.items())
    )
    if contents[f"{dist_info}/entry_points.txt"] != expected_entry_points.encode():
        raise ReleaseBundleError("wheel entry points do not match pyproject.toml")
    backend_version = build_requirements[0].partition("==")[2]
    expected_wheel_metadata = (
        "Wheel-Version: 1.0\n"
        f"Generator: hatchling {backend_version}\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode()
    if contents[f"{dist_info}/WHEEL"] != expected_wheel_metadata:
        raise ReleaseBundleError("wheel build metadata does not match the release contract")
    _verify_record(contents, record_name=f"{dist_info}/RECORD")


def _verify_sdist(path: Path) -> None:
    _, normalized, version, _ = _release_contract()
    prefix = f"{normalized}-{version}"
    expected = _source_map(_PACKAGE_SOURCE, f"{prefix}/src/atready")
    expected.update(
        _source_map(
            _SKILL_SOURCE,
            f"{prefix}/plugins/atready/skills/project-atready",
        )
    )
    for name in (
        ".gitignore",
        "LICENSE",
        "NOTICE",
        "PRIVACY.md",
        "README.md",
        "TERMS.md",
        "pyproject.toml",
    ):
        expected[f"{prefix}/{name}"] = (_ROOT / name).read_bytes()
    pkg_info = f"{prefix}/PKG-INFO"

    try:
        with tarfile.open(path, mode="r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            _validate_member_names(names, archive_name=path.name)
            total = 0
            contents: dict[str, bytes] = {}
            for member in members:
                if not member.isfile():
                    raise ReleaseBundleError(f"sdist contains a non-regular member: {member.name}")
                total += member.size
                if member.size > _MAX_UNCOMPRESSED_BYTES or total > _MAX_UNCOMPRESSED_BYTES:
                    raise ReleaseBundleError("sdist expands beyond the release bound")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ReleaseBundleError(f"sdist member is unreadable: {member.name}")
                contents[member.name] = stream.read()
    except tarfile.TarError as exc:
        raise ReleaseBundleError("sdist is not a valid tar archive") from exc

    if set(contents) != set(expected) | {pkg_info}:
        raise ReleaseBundleError("sdist contents exceed the explicit source-build allowlist")
    for name, data in expected.items():
        if contents[name] != data:
            raise ReleaseBundleError(f"sdist member differs from committed source: {name}")
    _metadata_identity(contents[pkg_info], filename="sdist PKG-INFO")


def verify_release_artifacts(dist: Path) -> None:
    resolved = _resolve_dist(dist)
    wheel, source = _expected_artifacts(resolved)
    _refuse_unexpected_entries(resolved, (wheel, source))
    _verify_wheel(wheel)
    _verify_sdist(source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        verify_release_artifacts(args.dist)
    except (OSError, ReleaseBundleError, SyntaxError, UnicodeError) as exc:
        print(f"release artifact error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
