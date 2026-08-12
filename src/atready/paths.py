"""Cross-platform private storage paths and exclusive file creation."""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

from atready.errors import StorageError
from atready.fsprivacy import (
    darwin_fd_has_extended_acl,
    file_identity_is_known,
    same_file_identity,
)


@dataclass(frozen=True)
class AtReadyPaths:
    config_dir: Path
    data_dir: Path

    @property
    def inventory_path(self) -> Path:
        return self.config_dir / "inventory.yaml"


def resolve_paths() -> AtReadyPaths:
    """Resolve user state without creating directories or reading unrelated files."""

    override = os.environ.get("ATREADY_HOME")
    if override:
        root = Path(override).expanduser()
        return AtReadyPaths(config_dir=root, data_dir=root / "data")

    legacy_override = os.environ.get("QUARTERMASTER_HOME")
    if legacy_override:
        root = Path(legacy_override).expanduser()
        return AtReadyPaths(config_dir=root, data_dir=root / "data")

    dirs = PlatformDirs("atready", appauthor=False)
    current = AtReadyPaths(
        config_dir=dirs.user_config_path,
        data_dir=dirs.user_data_path,
    )
    legacy_dirs = PlatformDirs("quartermaster", appauthor=False)
    legacy = AtReadyPaths(
        config_dir=legacy_dirs.user_config_path,
        data_dir=legacy_dirs.user_data_path,
    )
    if not current.config_dir.exists() and legacy.config_dir.exists():
        return legacy
    return current


def ensure_private_directory(path: Path) -> None:
    """Create a user-only directory or validate an existing caller-owned one."""

    path = Path(os.path.abspath(path.expanduser()))
    anchor = Path(path.anchor)
    _validate_existing_ancestor(anchor)
    current = anchor
    for part in path.parts[1:]:
        current /= part
        try:
            current.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError:
            if current == path:
                _validate_existing_directory(current)
            else:
                _validate_existing_ancestor(current)
            continue
        except OSError as exc:
            raise StorageError(f"cannot create private directory {current}: {exc}") from exc
        if os.name == "posix":
            try:
                current.chmod(0o700)
            except OSError as exc:
                raise StorageError(f"cannot secure private directory {current}: {exc}") from exc
        _validate_existing_directory(current)


def validate_no_darwin_extended_acl(
    path: Path,
    details: os.stat_result,
    *,
    subject: str,
    directory: bool,
) -> None:
    """Reject any macOS extended ACL on one identity-checked path."""

    if sys.platform != "darwin":
        return
    flags = os.O_RDONLY
    for flag_name in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= int(getattr(os, flag_name, 0))
    if directory:
        flags |= int(getattr(os, "O_DIRECTORY", 0))
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise StorageError(f"cannot verify {subject} extended access controls: {path}") from None
    try:
        opened = os.fstat(descriptor)
        if not same_file_identity(opened, details):
            raise StorageError(f"{subject} changed while checking access controls: {path}")
        if darwin_fd_has_extended_acl(descriptor):
            raise StorageError(f"refusing {subject} with a macOS extended ACL: {path}")
    except OSError:
        raise StorageError(f"cannot verify {subject} extended access controls: {path}") from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _validate_existing_directory(path: Path) -> None:
    """Reject links and non-directories without changing caller-owned metadata."""

    try:
        details = path.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect AtReady directory {path}: {exc}") from exc
    if stat.S_ISLNK(details.st_mode):
        raise StorageError(f"refusing symlinked AtReady directory: {path}")
    if not stat.S_ISDIR(details.st_mode):
        raise StorageError(f"refusing non-directory AtReady path: {path}")
    if os.name == "posix":
        if details.st_uid != os.geteuid():
            raise StorageError(f"refusing AtReady directory not owned by the current user: {path}")
        mode = stat.S_IMODE(details.st_mode)
        if mode & 0o022:
            raise StorageError(f"refusing writable AtReady directory mode {oct(mode)}: {path}")
    validate_no_darwin_extended_acl(
        path,
        details,
        subject="AtReady directory",
        directory=True,
    )


def _validate_existing_ancestor(path: Path) -> None:
    """Reject a linked, non-directory, or group/world-writable path ancestor."""

    try:
        details = path.lstat()
    except OSError as exc:
        raise StorageError(f"cannot inspect AtReady directory ancestor {path}: {exc}") from exc
    if stat.S_ISLNK(details.st_mode):
        raise StorageError(f"refusing symlinked AtReady directory ancestor: {path}")
    if not stat.S_ISDIR(details.st_mode):
        raise StorageError(f"refusing non-directory AtReady path ancestor: {path}")
    if os.name == "posix" and stat.S_IMODE(details.st_mode) & 0o022:
        raise StorageError(f"refusing writable AtReady directory ancestor: {path}")


def _descriptor_identity(descriptor: int) -> os.stat_result | None:
    """Inspect an open descriptor without allowing the inspection error to escape."""

    try:
        details = os.fstat(descriptor)
        if file_identity_is_known(details):
            return details
    except OSError:
        pass
    if os.stat in os.supports_fd:
        try:
            details = os.stat(descriptor)
            if file_identity_is_known(details):
                return details
        except OSError:
            pass
    return None


def _write_private_descriptor(descriptor: int, path: Path, content: str) -> StorageError | None:
    """Write and sync without propagating an exception that retains private content."""

    try:
        if os.name == "posix":
            try:
                os.fchmod(descriptor, 0o600)
            except OSError:
                return StorageError(f"cannot secure AtReady file mode: {path}")
        try:
            has_extended_acl = darwin_fd_has_extended_acl(descriptor)
        except OSError:
            return StorageError(f"cannot verify AtReady file extended access controls: {path}")
        if has_extended_acl:
            return StorageError(f"refusing AtReady file with a macOS extended ACL: {path}")
        try:
            raw = content.encode("utf-8")
        except UnicodeError:
            return StorageError(f"cannot encode AtReady file as UTF-8: {path}")
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                return StorageError(f"cannot write complete AtReady file: {path}")
            written += count
        os.fsync(descriptor)
        try:
            has_extended_acl = darwin_fd_has_extended_acl(descriptor)
        except OSError:
            return StorageError(f"cannot recheck AtReady file extended access controls: {path}")
        if has_extended_acl:
            return StorageError(f"AtReady file gained a macOS extended ACL: {path}")
    except (OSError, ValueError):
        return StorageError(f"cannot write and sync private AtReady file: {path}")
    return None


def _cleanup_created_file(
    descriptor: int,
    *,
    path: Path,
    parent_descriptor: int | None,
    created: os.stat_result | None,
) -> tuple[str, ...]:
    """Empty the created inode and unlink only its identity-bound directory entry."""

    warnings: list[str] = []
    try:
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
    except OSError:
        warnings.append("created-file content cleanup could not be fully synced")
    if created is None:
        created = _descriptor_identity(descriptor)
    if created is None:
        warnings.append(
            "created-file directory entry cleanup skipped because identity is unavailable"
        )
        return tuple(warnings)
    if os.name != "posix":
        return tuple(warnings)
    warnings.extend(
        _unlink_created_entry(
            path=path,
            parent_descriptor=parent_descriptor,
            created=created,
        )
    )
    return tuple(warnings)


def _unlink_created_entry(
    *,
    path: Path,
    parent_descriptor: int | None,
    created: os.stat_result,
) -> tuple[str, ...]:
    """Unlink only the directory entry still naming the created inode."""

    warnings: list[str] = []
    try:
        if parent_descriptor is not None:
            entry = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
            if same_file_identity(entry, created):
                os.unlink(path.name, dir_fd=parent_descriptor)
            else:
                warnings.append("created-file directory entry changed before cleanup")
        else:
            entry = path.lstat()
            if same_file_identity(entry, created):
                path.unlink()
            else:
                warnings.append("created-file path changed before cleanup")
    except FileNotFoundError:
        pass
    except OSError:
        warnings.append("created-file directory entry cleanup failed")
    return tuple(warnings)


def create_private_file(path: Path, content: str) -> None:
    """Create a new UTF-8 file with exclusive, user-only semantics."""

    path = path.expanduser()
    preparation_failure: StorageError | None = None
    try:
        ensure_private_directory(path.parent)
    except StorageError as exc:
        preparation_failure = StorageError(str(exc))
    if preparation_failure is not None:
        del content
        raise preparation_failure
    if path.is_symlink():
        failure = StorageError(f"refusing symlinked AtReady file: {path}")
        del content
        raise failure

    inspected_parent: os.stat_result | None = None
    try:
        inspected_parent = path.parent.lstat()
    except OSError:
        pass
    if inspected_parent is None:
        failure = StorageError(f"cannot inspect AtReady directory: {path.parent}")
        del content
        raise failure

    parent_descriptor: int | None = None
    use_directory_descriptor = (
        os.name == "posix"
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )
    if use_directory_descriptor:
        parent_flags = os.O_RDONLY
        for flag_name in ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"):
            parent_flags |= int(getattr(os, flag_name, 0))
        opened_parent: os.stat_result | None = None
        try:
            parent_descriptor = os.open(path.parent, parent_flags)
            opened_parent = os.fstat(parent_descriptor)
        except OSError:
            pass
        if opened_parent is None:
            if parent_descriptor is not None:
                try:
                    os.close(parent_descriptor)
                except OSError:
                    pass
            failure = StorageError(f"cannot pin AtReady directory: {path.parent}")
            del content
            raise failure
        if not same_file_identity(opened_parent, inspected_parent):
            try:
                os.close(parent_descriptor)
            except OSError:
                pass
            failure = StorageError(f"AtReady directory changed before file creation: {path.parent}")
            del content
            raise failure

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
        flags |= int(getattr(os, flag_name, 0))
    descriptor: int | None = None
    open_failure: StorageError | None = None
    try:
        if parent_descriptor is not None:
            descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_descriptor)
        else:
            descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        open_failure = StorageError(f"refusing to overwrite existing file: {path}")
    except OSError:
        open_failure = StorageError(f"cannot create private file: {path}")
    if open_failure is not None:
        if parent_descriptor is not None:
            try:
                os.close(parent_descriptor)
            except OSError:
                pass
        del content
        raise open_failure
    assert descriptor is not None
    created = _descriptor_identity(descriptor)
    failure = (
        StorageError(f"cannot inspect newly created AtReady file: {path}")
        if created is None
        else _write_private_descriptor(descriptor, path, content)
    )

    if failure is None:
        try:
            final_file = (
                os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
                if parent_descriptor is not None
                else path.lstat()
            )
            final_parent = path.parent.lstat()
            if (
                not same_file_identity(final_file, created)
                or not same_file_identity(final_parent, inspected_parent)
                or not stat.S_ISREG(final_file.st_mode)
                or final_file.st_nlink != 1
            ):
                failure = StorageError(f"AtReady file target changed during creation: {path}")
            elif os.name == "posix" and (
                final_parent.st_uid != os.geteuid() or stat.S_IMODE(final_parent.st_mode) & 0o022
            ):
                failure = StorageError(
                    f"AtReady directory permissions changed during creation: {path.parent}"
                )
        except OSError:
            failure = StorageError(f"cannot verify AtReady file after creation: {path}")

    if failure is not None:
        if created is None:
            created = _descriptor_identity(descriptor)
        for warning in _cleanup_created_file(
            descriptor,
            path=path,
            parent_descriptor=parent_descriptor,
            created=created,
        ):
            failure.add_note(warning)
    try:
        os.close(descriptor)
    except OSError:
        if failure is None:
            failure = StorageError(f"cannot close AtReady file after creation: {path}")
        else:
            failure.add_note("created-file descriptor cleanup failed")
    if failure is not None and created is not None:
        for warning in _unlink_created_entry(
            path=path,
            parent_descriptor=parent_descriptor,
            created=created,
        ):
            assert failure is not None
            failure.add_note(warning)
    if parent_descriptor is not None:
        try:
            os.close(parent_descriptor)
        except OSError:
            if failure is not None:
                failure.add_note("parent-directory descriptor cleanup failed")
    if failure is not None:
        del content
        raise failure
