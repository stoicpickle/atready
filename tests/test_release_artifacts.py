from __future__ import annotations

import base64
import csv
import hashlib
import io
import runpy
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "verify_release_artifacts.py"
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
VERSION = PROJECT["version"]
NORMALIZED = PROJECT["name"].replace("-", "_")
PACKAGE = ROOT / "src" / "atready"
SKILL = ROOT / "plugins" / "atready" / "skills" / "project-atready"


def _tree(source: Path, destination: str) -> dict[str, bytes]:
    return {
        f"{destination}/{path.relative_to(source).as_posix()}": path.read_bytes()
        for path in sorted(source.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _metadata(*, extra_dependency: str | None = None) -> bytes:
    dependencies = [
        "platformdirs<5,>=4.3",
        "pydantic<3,>=2.10",
        "pyyaml<7,>=6.0.2",
    ]
    if extra_dependency is not None:
        dependencies.append(extra_dependency)
    fields = [
        "Metadata-Version: 2.4",
        f"Name: {PROJECT['name']}",
        f"Version: {VERSION}",
        f"Summary: {PROJECT['description']}",
        f"Author: {PROJECT['authors'][0]['name']}",
        *(f"Project-URL: {label}, {url}" for label, url in PROJECT["urls"].items()),
        f"License-Expression: {PROJECT['license']}",
        *(f"License-File: {name}" for name in PROJECT["license-files"]),
        f"Keywords: {','.join(sorted(PROJECT['keywords']))}",
        *(f"Classifier: {classifier}" for classifier in PROJECT["classifiers"]),
        f"Requires-Python: {PROJECT['requires-python']}",
        *(f"Requires-Dist: {dependency}" for dependency in dependencies),
        "Description-Content-Type: text/markdown",
    ]
    description = (ROOT / "README.md").read_bytes()
    description = description.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return ("\n".join(fields) + "\n\n").encode() + description


def _record_bytes(contents: dict[str, bytes], record_name: str) -> bytes:
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, data in sorted(contents.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
        writer.writerow((name, f"sha256={digest.decode('ascii')}", len(data)))
    writer.writerow((record_name, "", ""))
    return record.getvalue().encode()


def _write_zip(path: Path, contents: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            archive.writestr(name, data)


def _write_wheel(dist: Path, *, extra_dependency: str | None = None) -> Path:
    dist_info = f"{NORMALIZED}-{VERSION}.dist-info"
    contents = _tree(PACKAGE, "atready")
    contents.update(_tree(SKILL, "atready/bundled_skill"))
    contents.update(
        {
            f"{dist_info}/METADATA": _metadata(extra_dependency=extra_dependency),
            f"{dist_info}/WHEEL": (
                b"Wheel-Version: 1.0\n"
                b"Generator: hatchling 1.31.0\n"
                b"Root-Is-Purelib: true\n"
                b"Tag: py3-none-any\n"
            ),
            f"{dist_info}/entry_points.txt": (b"[console_scripts]\natready = atready.cli:main\n"),
            f"{dist_info}/licenses/LICENSE": (ROOT / "LICENSE").read_bytes(),
            f"{dist_info}/licenses/NOTICE": (ROOT / "NOTICE").read_bytes(),
        }
    )
    record_name = f"{dist_info}/RECORD"
    contents[record_name] = _record_bytes(contents, record_name)

    wheel = dist / f"{NORMALIZED}-{VERSION}-py3-none-any.whl"
    _write_zip(wheel, contents)
    return wheel


def _rewrite_wheel(
    wheel: Path,
    updates: dict[str, bytes],
    *,
    rebuild_record: bool,
) -> None:
    with zipfile.ZipFile(wheel) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents.update(updates)
    record_name = next(name for name in contents if name.endswith(".dist-info/RECORD"))
    if rebuild_record:
        contents.pop(record_name)
        contents[record_name] = _record_bytes(contents, record_name)
    replacement = wheel.with_suffix(".replacement")
    _write_zip(replacement, contents)
    replacement.replace(wheel)


def _rewrite_sdist(sdist: Path, additions: dict[str, bytes]) -> None:
    with tarfile.open(sdist, mode="r:gz") as archive:
        contents = {}
        for member in archive.getmembers():
            stream = archive.extractfile(member)
            assert stream is not None
            contents[member.name] = stream.read()
    contents.update(additions)
    replacement = sdist.with_suffix(".replacement")
    with tarfile.open(replacement, mode="w:gz") as archive:
        for name, data in sorted(contents.items()):
            member = tarfile.TarInfo(name)
            member.mode = 0o644
            member.mtime = 0
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    replacement.replace(sdist)


def _write_sdist(dist: Path, *, extra_dependency: str | None = None) -> None:
    prefix = f"{NORMALIZED}-{VERSION}"
    contents = _tree(PACKAGE, f"{prefix}/src/atready")
    contents.update(_tree(SKILL, f"{prefix}/plugins/atready/skills/project-atready"))
    for name in (
        ".gitignore",
        "LICENSE",
        "NOTICE",
        "PRIVACY.md",
        "README.md",
        "TERMS.md",
        "pyproject.toml",
    ):
        contents[f"{prefix}/{name}"] = (ROOT / name).read_bytes()
    contents[f"{prefix}/PKG-INFO"] = _metadata(extra_dependency=extra_dependency)

    with tarfile.open(dist / f"{NORMALIZED}-{VERSION}.tar.gz", mode="w:gz") as archive:
        for name, data in sorted(contents.items()):
            member = tarfile.TarInfo(name)
            member.mode = 0o644
            member.mtime = 0
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def _seed_dist(tmp_path: Path) -> tuple[Path, Path]:
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    wheel = _write_wheel(dist)
    _write_sdist(dist)
    return dist, wheel


def _verify(dist: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--dist", str(dist)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )


def test_release_artifact_verifier_accepts_exact_content_boundary(tmp_path: Path) -> None:
    dist, _ = _seed_dist(tmp_path)

    result = _verify(dist)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("checkout_newline", ["\r\n", "\r"], ids=("crlf", "cr"))
def test_metadata_identity_normalizes_checkout_newlines(
    tmp_path: Path,
    checkout_newline: str,
) -> None:
    checkout_root = tmp_path / "alternate-newline-checkout"
    checkout_root.mkdir()
    readme_bytes = (ROOT / "README.md").read_bytes()
    readme = readme_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode("utf-8")
    (checkout_root / "README.md").write_bytes(readme.replace("\n", checkout_newline).encode())
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(SCRIPT.parent))
        namespace = runpy.run_path(str(SCRIPT))
    namespace["_metadata_identity"].__globals__["_ROOT"] = checkout_root
    metadata = _metadata()
    assert b"\r" not in metadata.split(b"\n\n", 1)[1]

    namespace["_metadata_identity"](metadata, filename="wheel METADATA")


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (b"\xff", "fixture is not valid UTF-8"),
        (None, "fixture is not byte content"),
        ("text", "fixture is not byte content"),
    ],
    ids=("invalid-utf8", "none", "text"),
)
def test_canonical_text_refuses_invalid_payloads(value: object, message: str) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(SCRIPT.parent))
        namespace = runpy.run_path(str(SCRIPT))

    with pytest.raises(namespace["ReleaseBundleError"], match=message):
        namespace["_canonical_utf8_text"](value, filename="fixture")


def test_public_package_metadata_contract_is_exact() -> None:
    assert PROJECT["authors"] == [{"name": "stoicpickle"}]
    assert PROJECT["license"] == "Apache-2.0"
    assert PROJECT["license-files"] == ["LICENSE", "NOTICE"]
    assert PROJECT["urls"] == {
        "Homepage": "https://github.com/stoicpickle/atready",
        "Documentation": "https://github.com/stoicpickle/atready/tree/main/docs",
        "Repository": "https://github.com/stoicpickle/atready",
        "Issues": "https://github.com/stoicpickle/atready/issues",
        "Support": "https://github.com/stoicpickle/atready/blob/main/SUPPORT.md",
        "Security": "https://github.com/stoicpickle/atready/security/policy",
        "Privacy": "https://github.com/stoicpickle/atready/blob/main/PRIVACY.md",
        "Terms": "https://github.com/stoicpickle/atready/blob/main/TERMS.md",
    }


def test_release_artifact_verifier_refuses_extra_wheel_content(tmp_path: Path) -> None:
    dist, wheel = _seed_dist(tmp_path)
    with zipfile.ZipFile(wheel, mode="a") as archive:
        archive.writestr("unexpected.txt", b"unexpected")

    result = _verify(dist)

    assert result.returncode == 2
    assert "wheel contents do not match" in result.stderr


def test_release_artifact_verifier_refuses_modified_wheel_dependencies(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist, extra_dependency="unexpected-package>=1")
    _write_sdist(dist)

    result = _verify(dist)

    assert result.returncode == 2
    assert "wheel METADATA dependencies do not match" in result.stderr


def test_release_artifact_verifier_refuses_modified_sdist_dependencies(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_wheel(dist)
    _write_sdist(dist, extra_dependency="unexpected-package>=1")

    result = _verify(dist)

    assert result.returncode == 2
    assert "sdist PKG-INFO dependencies do not match" in result.stderr


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        (
            f"Summary: {PROJECT['description']}".encode(),
            b"Summary: altered summary",
        ),
        (
            f"Author: {PROJECT['authors'][0]['name']}".encode(),
            b"Author: altered-author",
        ),
        (
            f"Project-URL: Homepage, {PROJECT['urls']['Homepage']}".encode(),
            b"Project-URL: Homepage, https://example.invalid",
        ),
        (
            f"License-Expression: {PROJECT['license']}".encode(),
            b"License-Expression: MIT",
        ),
        (b"License-File: LICENSE", b"License-File: UNEXPECTED"),
        (
            f"Keywords: {','.join(sorted(PROJECT['keywords']))}".encode(),
            b"Keywords: altered",
        ),
        (
            f"Classifier: {PROJECT['classifiers'][0]}".encode(),
            b"Classifier: Development Status :: 5 - Production/Stable",
        ),
        (
            b"Description-Content-Type: text/markdown",
            b"Description-Content-Type: text/plain",
        ),
    ],
    ids=(
        "summary",
        "author",
        "project-url",
        "license-expression",
        "license-file",
        "keywords",
        "classifier",
        "description-content-type",
    ),
)
def test_release_artifact_verifier_refuses_public_wheel_metadata_drift(
    tmp_path: Path,
    original: bytes,
    replacement: bytes,
) -> None:
    dist, wheel = _seed_dist(tmp_path)
    metadata_name = f"{NORMALIZED}-{VERSION}.dist-info/METADATA"
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(metadata_name)
    assert original in metadata
    _rewrite_wheel(
        wheel,
        {metadata_name: metadata.replace(original, replacement, 1)},
        rebuild_record=True,
    )

    result = _verify(dist)

    assert result.returncode == 2
    assert "wheel METADATA" in result.stderr


def test_release_artifact_verifier_refuses_public_sdist_metadata_drift(
    tmp_path: Path,
) -> None:
    dist, _ = _seed_dist(tmp_path)
    sdist = dist / f"{NORMALIZED}-{VERSION}.tar.gz"
    metadata_name = f"{NORMALIZED}-{VERSION}/PKG-INFO"
    with tarfile.open(sdist, mode="r:gz") as archive:
        stream = archive.extractfile(metadata_name)
        assert stream is not None
        metadata = stream.read()
    original = f"Summary: {PROJECT['description']}".encode()
    assert original in metadata
    _rewrite_sdist(sdist, {metadata_name: metadata.replace(original, b"Summary: altered", 1)})

    result = _verify(dist)

    assert result.returncode == 2
    assert "sdist PKG-INFO" in result.stderr


def test_release_artifact_verifier_refuses_long_description_drift(tmp_path: Path) -> None:
    dist, wheel = _seed_dist(tmp_path)
    metadata_name = f"{NORMALIZED}-{VERSION}.dist-info/METADATA"
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(metadata_name)
    _rewrite_wheel(
        wheel,
        {
            metadata_name: metadata.replace(
                b"# AtReady",
                b"# Altered AtReady",
                1,
            )
        },
        rebuild_record=True,
    )

    result = _verify(dist)

    assert result.returncode == 2
    assert "long description differs from committed README.md" in result.stderr


def test_release_artifact_verifier_refuses_wheel_source_byte_drift(tmp_path: Path) -> None:
    dist, wheel = _seed_dist(tmp_path)
    _rewrite_wheel(
        wheel,
        {"atready/__init__.py": (f'__version__ = "{VERSION}"\n# modified\n'.encode())},
        rebuild_record=True,
    )

    result = _verify(dist)

    assert result.returncode == 2
    assert "wheel member differs from committed source" in result.stderr


def test_release_artifact_verifier_refuses_entry_point_drift(tmp_path: Path) -> None:
    dist, wheel = _seed_dist(tmp_path)
    entry_points = f"{NORMALIZED}-{VERSION}.dist-info/entry_points.txt"
    _rewrite_wheel(
        wheel,
        {entry_points: b"[console_scripts]\natready = unexpected:main\n"},
        rebuild_record=True,
    )

    result = _verify(dist)

    assert result.returncode == 2
    assert "wheel entry points do not match" in result.stderr


def test_release_artifact_verifier_refuses_record_drift(tmp_path: Path) -> None:
    dist, wheel = _seed_dist(tmp_path)
    record_name = f"{NORMALIZED}-{VERSION}.dist-info/RECORD"
    with zipfile.ZipFile(wheel) as archive:
        record = archive.read(record_name)
    _rewrite_wheel(
        wheel,
        {record_name: record.replace(b"sha256=", b"sha256=x", 1)},
        rebuild_record=False,
    )

    result = _verify(dist)

    assert result.returncode == 2
    assert "wheel RECORD does not match member" in result.stderr


def test_release_artifact_verifier_refuses_sdist_extra_or_unsafe_members(tmp_path: Path) -> None:
    dist, _ = _seed_dist(tmp_path)
    sdist = dist / f"{NORMALIZED}-{VERSION}.tar.gz"
    _rewrite_sdist(sdist, {f"{NORMALIZED}-{VERSION}/unexpected.py": b"unexpected\n"})
    extra = _verify(dist)
    assert extra.returncode == 2
    assert "sdist contents exceed" in extra.stderr

    dist, _ = _seed_dist(tmp_path / "unsafe")
    sdist = dist / f"{NORMALIZED}-{VERSION}.tar.gz"
    _rewrite_sdist(sdist, {"../unsafe": b"unsafe\n"})
    unsafe = _verify(dist)
    assert unsafe.returncode == 2
    assert "unsafe member name" in unsafe.stderr
