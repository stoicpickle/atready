from __future__ import annotations

import ctypes
import errno
from types import SimpleNamespace

import pytest

import atready.fsprivacy as fsprivacy


def _snapshot(**changes: int) -> SimpleNamespace:
    values = {
        "st_dev": 7,
        "st_ino": 11,
        "st_size": 13,
        "st_mtime_ns": 17,
        "st_ctime_ns": 19,
    }
    values.update(changes)
    return SimpleNamespace(**values)


class _FakeFunction:
    def __init__(self, callback):
        self._callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self._callback(*args)


class _FakeLibc:
    def __init__(
        self,
        *,
        acl: int,
        acl_errno: int = 0,
        free_result: int = 0,
        free_errno: int = 0,
    ) -> None:
        def get_acl(_descriptor: int, _acl_type: int) -> int:
            ctypes.set_errno(acl_errno)
            return acl

        def free_acl(_acl: int) -> int:
            ctypes.set_errno(free_errno)
            return free_result

        self.acl_get_fd_np = _FakeFunction(get_acl)
        self.acl_free = _FakeFunction(free_acl)


def _install_fake_libc(monkeypatch: pytest.MonkeyPatch, libc: object) -> None:
    monkeypatch.setattr(fsprivacy.sys, "platform", "darwin")
    monkeypatch.setattr(fsprivacy.ctypes, "CDLL", lambda *_args, **_kwargs: libc)


def test_non_darwin_acl_check_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fsprivacy.sys, "platform", "linux")
    monkeypatch.setattr(
        fsprivacy.ctypes,
        "CDLL",
        lambda *_args, **_kwargs: pytest.fail("non-Darwin must not load libc ACL symbols"),
    )

    assert fsprivacy.darwin_fd_has_extended_acl(7) is False


def test_snapshot_identity_helpers_fail_closed_for_zero_or_changed_values() -> None:
    baseline = _snapshot()
    matching = _snapshot()
    unknown = _snapshot(st_ino=0)

    assert fsprivacy.file_identity_is_known(baseline) is True
    assert fsprivacy.file_identity_is_known(unknown) is False
    assert fsprivacy.same_file_identity(baseline, matching) is True
    assert fsprivacy.same_file_identity(unknown, unknown) is False
    assert fsprivacy.descriptor_snapshot_unchanged(matching, baseline) is True
    assert fsprivacy.descriptor_snapshot_unchanged(_snapshot(st_ctime_ns=23), baseline) is False
    assert (
        fsprivacy.path_snapshot_unchanged(
            matching,
            inspected=baseline,
            opened=baseline,
        )
        is True
    )
    assert (
        fsprivacy.path_snapshot_unchanged(
            _snapshot(st_mtime_ns=29),
            inspected=baseline,
            opened=baseline,
        )
        is False
    )


def test_darwin_acl_check_distinguishes_absent_and_present_acl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_libc(monkeypatch, _FakeLibc(acl=0, acl_errno=errno.ENOENT))
    assert fsprivacy.darwin_fd_has_extended_acl(7) is False

    _install_fake_libc(monkeypatch, _FakeLibc(acl=1))
    assert fsprivacy.darwin_fd_has_extended_acl(7) is True


def test_darwin_acl_check_fails_closed_for_missing_api_or_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_libc(monkeypatch, object())
    with pytest.raises(OSError) as unavailable:
        fsprivacy.darwin_fd_has_extended_acl(7)
    assert unavailable.value.errno == errno.ENOSYS

    _install_fake_libc(monkeypatch, _FakeLibc(acl=0, acl_errno=errno.EIO))
    with pytest.raises(OSError) as lookup_failure:
        fsprivacy.darwin_fd_has_extended_acl(7)
    assert lookup_failure.value.errno == errno.EIO


def test_darwin_acl_check_fails_closed_when_acl_cannot_be_freed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_libc(
        monkeypatch,
        _FakeLibc(acl=1, free_result=-1, free_errno=errno.EIO),
    )

    with pytest.raises(OSError) as caught:
        fsprivacy.darwin_fd_has_extended_acl(7)

    assert caught.value.errno == errno.EIO
