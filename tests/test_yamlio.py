from __future__ import annotations

import os
from pathlib import Path

import pytest

import atready.yamlio as yamlio
from atready.errors import ConfigurationError
from atready.yamlio import MAX_FILE_BYTES, load_yaml, loads_yaml


def test_rejects_duplicate_keys() -> None:
    with pytest.raises(ConfigurationError, match="duplicate mapping key at line 2"):
        loads_yaml("id: first\nid: second\n")


def test_rejects_unsafe_python_tags() -> None:
    with pytest.raises(ConfigurationError, match="invalid YAML"):
        loads_yaml("value: !!python/object/apply:os.system ['whoami']\n")


@pytest.mark.parametrize(
    "document",
    [
        "base: &base {value: 1}\ncopy: *base\n",
        "value: &anchor hello\n",
    ],
)
def test_rejects_aliases_and_anchors(document: str) -> None:
    with pytest.raises(ConfigurationError, match="anchors and aliases"):
        loads_yaml(document)


@pytest.mark.parametrize("key", ["api_key", "token", "client-secret", "credentials"])
def test_rejects_secret_bearing_fields(key: str) -> None:
    with pytest.raises(ConfigurationError, match="secret-bearing field"):
        loads_yaml(f"resource:\n  {key}: forbidden\n")


def test_allows_token_related_capability_names() -> None:
    value = loads_yaml("capabilities:\n  token-efficiency: 0.8\n")
    assert value["capabilities"]["token-efficiency"] == 0.8


def test_rejects_empty_oversized_and_non_string_key_input() -> None:
    with pytest.raises(ConfigurationError, match="configuration is empty"):
        loads_yaml("")
    with pytest.raises(ConfigurationError, match="exceeds"):
        loads_yaml("x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ConfigurationError, match="mapping keys must be strings"):
        loads_yaml("1: value\n")


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("value: !!set {one: null}\n", "unsupported YAML value type"),
        ("value: !!binary cHJpdmF0ZQ==\n", "unsupported YAML value type"),
        ("value: .nan\n", "non-finite number"),
        ("value: .inf\n", "non-finite number"),
    ],
)
def test_rejects_unsupported_or_nonfinite_safe_loader_values(document: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        loads_yaml(document)


def test_unhashable_mapping_key_is_sanitized_and_detached() -> None:
    with pytest.raises(ConfigurationError, match="mapping keys must be scalar") as caught:
        loads_yaml("? [SYNTHETIC-PRIVATE-SENTINEL]\n: value\n")

    assert "SYNTHETIC-PRIVATE-SENTINEL" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_unpaired_surrogate_is_rejected_without_unicode_exception_context() -> None:
    with pytest.raises(ConfigurationError, match="valid UTF-8 text") as caught:
        loads_yaml("value: \ud800\n")

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "document",
    [
        "private_notes: [SYNTHETIC-PRIVATE-SENTINEL\n",
        "value: !SYNTHETIC-PRIVATE-SENTINEL payload\n",
    ],
)
def test_yaml_syntax_errors_never_echo_source_lines(document: str) -> None:
    with pytest.raises(ConfigurationError) as caught:
        loads_yaml(document)

    rendered = str(caught.value)
    assert "invalid YAML" in rendered
    assert "SYNTHETIC-PRIVATE-SENTINEL" not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_file_loader_rejects_missing_directory_and_symlink(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_yaml(tmp_path / "missing.yaml")
    with pytest.raises(ConfigurationError, match="not a regular file"):
        load_yaml(tmp_path)

    target = tmp_path / "target.yaml"
    target.write_text("value: safe\n", encoding="utf-8")
    link = tmp_path / "link.yaml"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(ConfigurationError, match="refusing to read symlinked"):
        load_yaml(link)


def test_file_loader_wraps_inspection_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    real_lstat = Path.lstat

    def fail_target_lstat(path: Path):
        if path == target:
            raise OSError("synthetic invalid path")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_target_lstat)
    with pytest.raises(ConfigurationError, match="cannot inspect configuration"):
        load_yaml(target)


@pytest.mark.skipif(os.name != "posix", reason="FIFO substitution requires POSIX")
def test_file_loader_refuses_fifo_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_text("value: safe\n", encoding="utf-8")
    real_open = yamlio.os.open

    def substitute_fifo(path: Path, flags: int, *args: object) -> int:
        assert flags & os.O_NONBLOCK
        target.unlink()
        os.mkfifo(target, mode=0o600)
        return real_open(path, flags, *args)

    monkeypatch.setattr(yamlio.os, "open", substitute_fifo)

    with pytest.raises(ConfigurationError, match="not a regular file"):
        load_yaml(target)


def test_file_loader_refuses_mutation_after_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_text("value: safe\n", encoding="utf-8")
    acl_checks = 0

    def mutate_on_second_check(_descriptor: int) -> bool:
        nonlocal acl_checks
        acl_checks += 1
        if acl_checks == 2:
            target.write_text("value: changed-after-read\n", encoding="utf-8")
        return False

    monkeypatch.setattr(yamlio, "darwin_fd_has_extended_acl", mutate_on_second_check)

    with pytest.raises(ConfigurationError, match="changed while being read"):
        load_yaml(target)


def test_file_loader_compares_final_path_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_text("value: safe\n", encoding="utf-8")
    real_lstat = Path.lstat
    inspections = 0

    def mutate_before_final_lstat(path: Path):
        nonlocal inspections
        if path == target:
            inspections += 1
            if inspections == 2:
                target.write_text("value: changed-before-final-lstat\n", encoding="utf-8")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", mutate_before_final_lstat)

    with pytest.raises(ConfigurationError, match="changed while being read"):
        load_yaml(target)


def test_file_loader_defers_path_identity_check_until_descriptor_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_text("value: safe\n", encoding="utf-8")
    real_open = yamlio.os.open
    real_close = yamlio.os.close
    real_lstat = Path.lstat
    active_descriptors: set[int] = set()

    def tracked_open(path: Path, flags: int, *args) -> int:
        descriptor = real_open(path, flags, *args)
        if Path(path) == target:
            active_descriptors.add(descriptor)
        return descriptor

    def tracked_close(descriptor: int) -> None:
        try:
            real_close(descriptor)
        finally:
            active_descriptors.discard(descriptor)

    def partial_windows_lstat(path: Path):
        details = real_lstat(path)
        if path == target and active_descriptors:
            return os.stat_result(
                (
                    details.st_mode,
                    0,
                    0,
                    0,
                    details.st_uid,
                    details.st_gid,
                    details.st_size,
                    details.st_atime,
                    details.st_mtime,
                    details.st_ctime,
                )
            )
        return details

    monkeypatch.setattr(yamlio.os, "open", tracked_open)
    monkeypatch.setattr(yamlio.os, "close", tracked_close)
    monkeypatch.setattr(Path, "lstat", partial_windows_lstat)

    assert load_yaml(target) == {"value": "safe"}
    assert not active_descriptors


def test_file_loader_rejects_path_retargeted_after_descriptor_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "inventory.yaml"
    replacement = tmp_path / "replacement.yaml"
    displaced = tmp_path / "displaced.yaml"
    target.write_text("value: safe\n", encoding="utf-8")
    replacement.write_text("value: evil\n", encoding="utf-8")
    real_open = yamlio.os.open
    real_close = yamlio.os.close
    target_descriptor: int | None = None

    def tracked_open(path: Path, flags: int, *args) -> int:
        nonlocal target_descriptor
        descriptor = real_open(path, flags, *args)
        if Path(path) == target:
            target_descriptor = descriptor
        return descriptor

    def retarget_after_close(descriptor: int) -> None:
        real_close(descriptor)
        if descriptor == target_descriptor:
            target.replace(displaced)
            replacement.replace(target)

    monkeypatch.setattr(yamlio.os, "open", tracked_open)
    monkeypatch.setattr(yamlio.os, "close", retarget_after_close)

    with pytest.raises(ConfigurationError, match="changed while being read"):
        load_yaml(target)


def test_file_loader_utf8_failure_has_no_os_or_unicode_context(tmp_path: Path) -> None:
    target = tmp_path / "inventory.yaml"
    target.write_bytes(b"value: \xff\n")

    with pytest.raises(ConfigurationError, match="cannot read UTF-8") as caught:
        load_yaml(target)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
