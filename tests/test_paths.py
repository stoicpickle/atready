from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import atready.paths as paths
from atready.errors import StorageError


def test_resolve_paths_prefers_atready_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tmp_path / "atready-home"
    legacy = tmp_path / "quartermaster-home"
    monkeypatch.setenv("ATREADY_HOME", str(current))
    monkeypatch.setenv("QUARTERMASTER_HOME", str(legacy))

    resolved = paths.resolve_paths()

    assert resolved.config_dir == current
    assert resolved.data_dir == current / "data"


def test_resolve_paths_accepts_legacy_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "quartermaster-home"
    monkeypatch.delenv("ATREADY_HOME", raising=False)
    monkeypatch.setenv("QUARTERMASTER_HOME", str(legacy))

    resolved = paths.resolve_paths()

    assert resolved.config_dir == legacy
    assert resolved.data_dir == legacy / "data"


def test_resolve_paths_reuses_existing_legacy_platform_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tmp_path / "atready"
    legacy = tmp_path / "quartermaster"
    legacy.mkdir()
    monkeypatch.delenv("ATREADY_HOME", raising=False)
    monkeypatch.delenv("QUARTERMASTER_HOME", raising=False)
    applications: list[str] = []

    class FakePlatformDirs:
        def __init__(self, application: str, *, appauthor: bool) -> None:
            assert appauthor is False
            applications.append(application)
            if application == "atready":
                root = current
            elif application == "quartermaster":
                root = legacy
            else:  # pragma: no cover - defensive assertion for future drift
                raise AssertionError(f"unexpected application identity: {application}")
            self.user_config_path = root
            self.user_data_path = root / "data"

    monkeypatch.setattr(paths, "PlatformDirs", FakePlatformDirs)

    resolved = paths.resolve_paths()

    assert resolved.config_dir == legacy
    assert resolved.data_dir == legacy / "data"
    assert applications == ["atready", "quartermaster"]


def _assert_private_content_not_retained(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    traceback = error.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name == "create_private_file":
            assert "content" not in traceback.tb_frame.f_locals
        traceback = traceback.tb_next


def test_darwin_path_acl_validation_uses_open_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_text("synthetic\n", encoding="utf-8")
    details = target.lstat()
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths, "darwin_fd_has_extended_acl", lambda _descriptor: False)

    paths.validate_no_darwin_extended_acl(
        target,
        details,
        subject="inventory",
        directory=False,
    )

    monkeypatch.setattr(paths, "darwin_fd_has_extended_acl", lambda _descriptor: True)
    with pytest.raises(StorageError, match="macOS extended ACL"):
        paths.validate_no_darwin_extended_acl(
            target,
            details,
            subject="inventory",
            directory=False,
        )


def test_darwin_path_acl_validation_fails_closed_on_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    replacement = tmp_path / "replacement.yaml"
    target.write_text("synthetic\n", encoding="utf-8")
    replacement.write_text("replacement\n", encoding="utf-8")
    details = target.lstat()
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.os, "fstat", lambda _descriptor: replacement.lstat())

    with pytest.raises(StorageError, match="changed while checking access controls"):
        paths.validate_no_darwin_extended_acl(
            target,
            details,
            subject="inventory",
            directory=False,
        )


def test_darwin_path_acl_validation_fails_closed_on_api_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_text("synthetic\n", encoding="utf-8")
    details = target.lstat()
    monkeypatch.setattr(paths.sys, "platform", "darwin")

    def fail_acl(_descriptor: int) -> bool:
        raise OSError("synthetic ACL failure")

    monkeypatch.setattr(paths, "darwin_fd_has_extended_acl", fail_acl)
    with pytest.raises(StorageError, match="cannot verify inventory extended access controls"):
        paths.validate_no_darwin_extended_acl(
            target,
            details,
            subject="inventory",
            directory=False,
        )


def test_private_file_acl_refusal_removes_created_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    monkeypatch.setattr(
        paths,
        "validate_no_darwin_extended_acl",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(paths, "darwin_fd_has_extended_acl", lambda _fd: True)

    with pytest.raises(StorageError, match="file with a macOS extended ACL"):
        paths.create_private_file(target, "synthetic private state")

    assert not target.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory-mode contract")
def test_private_directory_secures_every_new_intermediate_with_permissive_umask(
    tmp_path: Path,
) -> None:
    target = tmp_path / "one" / "two" / "three"
    previous = os.umask(0)
    try:
        paths.ensure_private_directory(target)
    finally:
        os.umask(previous)

    for directory in (tmp_path / "one", tmp_path / "one" / "two", target):
        assert directory.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory-mode contract")
def test_private_directory_rejects_writable_existing_intermediate(tmp_path: Path) -> None:
    writable = tmp_path / "writable"
    writable.mkdir(mode=0o700)
    writable.chmod(0o777)
    target = writable / "private" / "report.json"

    with pytest.raises(StorageError, match="writable AtReady directory ancestor"):
        paths.create_private_file(target, "synthetic")

    assert not target.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX shared-temp contract")
def test_private_directory_allows_root_owned_sticky_temp_ancestor() -> None:
    shared_temp = Path(tempfile.gettempdir()).resolve()
    details = shared_temp.stat()
    mode = stat.S_IMODE(details.st_mode)
    if details.st_uid != 0 or not mode & stat.S_ISVTX:
        pytest.skip("platform temp root is not a root-owned sticky directory")

    with tempfile.TemporaryDirectory(dir=shared_temp) as root_name:
        target = Path(root_name) / "private" / "report.json"
        paths.create_private_file(target, "synthetic")

        assert target.read_text(encoding="utf-8") == "synthetic"
        assert target.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(paths.os.name != "posix", reason="fchmod is a POSIX-only contract")
def test_private_file_mode_failure_is_wrapped_and_removes_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"

    def fail_mode(_descriptor: int, _mode: int) -> None:
        raise OSError("synthetic private-state sentinel")

    monkeypatch.setattr(paths.os, "fchmod", fail_mode)

    with pytest.raises(StorageError, match="cannot secure AtReady file mode") as caught:
        paths.create_private_file(target, "synthetic private state")

    assert "synthetic private-state sentinel" not in str(caught.value)
    assert not target.exists()


def test_private_file_fsync_failure_is_sanitized_and_removes_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    sentinel = "SYNTHETIC-PRIVATE-CONTENT-SENTINEL"

    def fail_sync(_descriptor: int) -> None:
        raise OSError(sentinel)

    monkeypatch.setattr(paths.os, "fsync", fail_sync)

    with pytest.raises(StorageError) as caught:
        paths.create_private_file(target, sentinel)

    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert not target.exists()


def test_private_file_descriptor_inspection_failure_is_sanitized_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    sentinel = "SYNTHETIC-PRIVATE-CONTENT-SENTINEL"
    real_identity = paths._descriptor_identity
    inspections = 0

    def fail_first_inspection(descriptor: int):
        nonlocal inspections
        inspections += 1
        if inspections == 1:
            return None
        return real_identity(descriptor)

    monkeypatch.setattr(paths, "_descriptor_identity", fail_first_inspection)

    with pytest.raises(StorageError, match="cannot inspect newly created") as caught:
        paths.create_private_file(target, sentinel)

    _assert_private_content_not_retained(caught.value)
    assert not target.exists()


def test_created_file_cleanup_never_unlinks_unknown_zero_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_text("replacement\n", encoding="utf-8")
    real_lstat = Path.lstat
    unknown = SimpleNamespace(st_dev=0, st_ino=0)

    def zero_identity_for_target(path: Path):
        if path == target:
            return unknown
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", zero_identity_for_target)
    warnings = paths._unlink_created_entry(
        path=target,
        parent_descriptor=None,
        created=unknown,
    )

    assert target.exists()
    assert warnings == ("created-file path changed before cleanup",)


def test_private_file_close_failure_removes_applied_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    real_close = paths.os.close
    failed = False
    monkeypatch.setattr(
        paths,
        "validate_no_darwin_extended_acl",
        lambda *_args, **_kwargs: None,
    )

    def close_then_fail_once(descriptor: int) -> None:
        nonlocal failed
        real_close(descriptor)
        if not failed:
            failed = True
            raise OSError("synthetic close failure")

    monkeypatch.setattr(paths.os, "close", close_then_fail_once)

    with pytest.raises(StorageError, match="cannot close AtReady file") as caught:
        paths.create_private_file(target, "synthetic private state")

    _assert_private_content_not_retained(caught.value)
    assert not target.exists()


@pytest.mark.skipif(
    not (
        paths.os.name == "posix"
        and paths.os.open in paths.os.supports_dir_fd
        and paths.os.stat in paths.os.supports_dir_fd
        and paths.os.unlink in paths.os.supports_dir_fd
    ),
    reason="identity-bound cleanup requires POSIX directory descriptors",
)
def test_private_file_cleanup_cannot_follow_retargeted_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "private"
    displaced = tmp_path / "displaced"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    attacker_file = attacker / "inventory.yaml"
    attacker_file.write_text("keep me\n", encoding="utf-8")
    target = parent / "inventory.yaml"

    def retarget_then_refuse(_descriptor: int) -> bool:
        parent.rename(displaced)
        parent.symlink_to(attacker, target_is_directory=True)
        return True

    monkeypatch.setattr(
        paths,
        "validate_no_darwin_extended_acl",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(paths, "darwin_fd_has_extended_acl", retarget_then_refuse)

    with pytest.raises(StorageError, match="macOS extended ACL"):
        paths.create_private_file(target, "private content")

    assert attacker_file.read_text(encoding="utf-8") == "keep me\n"
    assert not (displaced / "inventory.yaml").exists()
