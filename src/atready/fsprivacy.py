"""Descriptor-level privacy checks shared by sensitive local storage."""

from __future__ import annotations

import ctypes
import errno
import os
import sys

_DARWIN_ACL_TYPE_EXTENDED = 0x00000100


def file_identity_is_known(details: os.stat_result) -> bool:
    """Return whether a stat result contains a usable file identity."""

    return details.st_ino != 0


def same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare usable path identities without accepting an unknown zero inode."""

    return (
        file_identity_is_known(left)
        and file_identity_is_known(right)
        and (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)
    )


def descriptor_snapshot_unchanged(
    current: os.stat_result,
    baseline: os.stat_result,
) -> bool:
    """Compare two metadata snapshots taken from the same open descriptor."""

    return (
        same_file_identity(current, baseline)
        and current.st_size == baseline.st_size
        and current.st_mtime_ns == baseline.st_mtime_ns
        and current.st_ctime_ns == baseline.st_ctime_ns
    )


def path_snapshot_unchanged(
    current: os.stat_result,
    *,
    inspected: os.stat_result,
    opened: os.stat_result,
) -> bool:
    """Compare path metadata to its path baseline and pinned descriptor identity."""

    return (
        same_file_identity(current, opened)
        and current.st_size == inspected.st_size
        and current.st_mtime_ns == inspected.st_mtime_ns
        and current.st_ctime_ns == inspected.st_ctime_ns
    )


def darwin_fd_has_extended_acl(descriptor: int) -> bool:
    """Return whether an opened Darwin file has any extended ACL entry.

    A null ACL with ``ENOENT`` means no extended ACL. Every other API failure
    is surfaced so callers can fail closed with their own public error type.
    """

    if sys.platform != "darwin":
        return False

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        acl_get_fd_np = libc.acl_get_fd_np
        acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
        acl_get_fd_np.restype = ctypes.c_void_p
        acl_free = libc.acl_free
        acl_free.argtypes = [ctypes.c_void_p]
        acl_free.restype = ctypes.c_int
    except (AttributeError, OSError):
        raise OSError(errno.ENOSYS, "macOS extended ACL API is unavailable") from None

    ctypes.set_errno(0)
    acl = acl_get_fd_np(descriptor, _DARWIN_ACL_TYPE_EXTENDED)
    if not acl:
        error_number = ctypes.get_errno()
        if error_number == errno.ENOENT:
            return False
        raise OSError(error_number, "cannot inspect macOS extended ACL")

    ctypes.set_errno(0)
    if acl_free(acl) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, "cannot release macOS extended ACL")
    return True
