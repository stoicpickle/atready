from __future__ import annotations

import io
import os
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

import atready.resource_input as resource_input
from atready.errors import ConfigurationError
from atready.models import InventoryAnnotationDeclaration
from atready.resource_input import (
    load_inventory_annotation_declaration_file,
    load_inventory_annotation_declaration_stdin,
    load_resource_declaration_file,
    load_resource_declaration_stdin,
    parse_inventory_annotation_declaration,
    parse_resource_declaration,
)
from atready.yamlio import MAX_FILE_BYTES

_SENTINEL = "SYNTHETIC-PRIVATE-SENTINEL"


def _declaration(*, private_notes: str | None = _SENTINEL) -> bytes:
    note = f"  private_notes: {private_notes}\n" if private_notes is not None else ""
    return (
        "schema_version: 1\n"
        "resource:\n"
        "  id: local-tool\n"
        "  name: Local Tool\n"
        "  categories: [coding-agent]\n"
        "  capabilities:\n"
        "    code-implementation: 0.9\n"
        "  access:\n"
        "    status: active\n"
        "  provenance:\n"
        "    last_verified: " + date.today().isoformat() + "\n" + note
    ).encode()


def _annotation_declaration(*, private_notes: str = _SENTINEL) -> bytes:
    return f"schema_version: 1\nprivate_notes: {private_notes}\n".encode()


def _write_private(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    if os.name == "posix":
        path.chmod(0o600)


def test_inventory_annotation_declaration_is_strict_and_repr_redacted() -> None:
    declaration = InventoryAnnotationDeclaration.model_validate(
        {"schema_version": 1, "private_notes": _SENTINEL}
    )

    assert declaration.private_notes == _SENTINEL
    assert _SENTINEL not in repr(declaration)
    schema = InventoryAnnotationDeclaration.model_json_schema()
    assert schema["required"] == ["schema_version", "private_notes"]
    assert schema["properties"]["private_notes"]["maxLength"] == 20_000

    with pytest.raises(ValidationError) as caught:
        InventoryAnnotationDeclaration.model_validate(
            {"schema_version": 1, "private_notes": _SENTINEL, "extra": "rejected"}
        )

    assert _SENTINEL not in str(caught.value)
    assert "extra inputs are not permitted" in str(caught.value).lower()


def test_parse_inventory_annotation_declaration_accepts_only_the_direct_envelope() -> None:
    parsed = parse_inventory_annotation_declaration(
        {"schema_version": 1, "private_notes": _SENTINEL}
    )

    assert parsed.private_notes == _SENTINEL
    assert _SENTINEL not in repr(parsed)

    with pytest.raises(ConfigurationError) as caught:
        parse_inventory_annotation_declaration(
            {
                "schema_version": 1,
                "private_notes": _SENTINEL,
                "unexpected": _SENTINEL,
            }
        )

    assert "inventory annotation declaration validation failed" in str(caught.value)
    assert _SENTINEL not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_annotation_stdin_accepts_one_versioned_yaml_or_json_declaration() -> None:
    parsed = load_inventory_annotation_declaration_stdin(io.BytesIO(_annotation_declaration()))
    parsed_json = load_inventory_annotation_declaration_stdin(
        io.BytesIO(b'{"schema_version":1,"private_notes":"SYNTHETIC-PRIVATE-SENTINEL"}')
    )

    assert parsed.private_notes == _SENTINEL
    assert parsed_json.private_notes == _SENTINEL
    assert _SENTINEL not in repr(parsed)


@pytest.mark.parametrize(
    "value",
    [
        {"private_notes": _SENTINEL},
        {"schema_version": 2, "private_notes": _SENTINEL},
        {"schema_version": 1},
        {"schema_version": 1, "private_notes": None},
        {"schema_version": 1, "private_notes": _SENTINEL.encode()},
        {"schema_version": 1, "private_notes": [_SENTINEL]},
    ],
)
def test_annotation_declaration_requires_versioned_strict_string_envelope(
    value: object,
) -> None:
    with pytest.raises(ConfigurationError) as caught:
        parse_inventory_annotation_declaration(value)

    assert _SENTINEL not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "raw",
    [
        b"schema_version: 1\nprivate_notes: [SYNTHETIC-PRIVATE-SENTINEL\n",
        b"schema_version: 1\nprivate_notes: SYNTHETIC-PRIVATE-SENTINEL\nprivate_notes: changed\n",
        b"schema_version: 1\nprivate_notes: SYNTHETIC-PRIVATE-SENTINEL\nunexpected: rejected\n",
        b"schema_version: 1\nprivate_notes: SYNTHETIC-PRIVATE-SENTINEL\n---\n{}\n",
        b"schema_version: 1\nprivate_notes: SYNTHETIC-PRIVATE-SENTINEL\napi_key: rejected\n",
        _SENTINEL.encode() + b"\xff",
    ],
)
def test_annotation_stdin_errors_do_not_echo_values_or_chain_source_exceptions(
    raw: bytes,
) -> None:
    with pytest.raises(ConfigurationError) as caught:
        load_inventory_annotation_declaration_stdin(io.BytesIO(raw))

    assert _SENTINEL not in str(caught.value)
    assert _SENTINEL not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def _assert_value_free_error(raw: bytes) -> ConfigurationError:
    with pytest.raises(ConfigurationError) as caught:
        load_resource_declaration_stdin(io.BytesIO(raw))
    rendered = str(caught.value)
    assert _SENTINEL not in rendered
    assert _SENTINEL not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    return caught.value


def test_stdin_accepts_one_versioned_yaml_or_json_declaration() -> None:
    parsed = load_resource_declaration_stdin(io.BytesIO(_declaration()))

    assert parsed.resource.id == "local-tool"
    assert parsed.resource.private_notes == _SENTINEL
    assert "ratings.quality" in parsed.defaulted_fields
    assert _SENTINEL not in repr(parsed)

    parsed_json = load_resource_declaration_stdin(
        io.BytesIO(
            b'{"schema_version":1,"resource":{"id":"json-tool","name":"JSON Tool",'
            b'"categories":["tool"],"capabilities":{"build":0.8}}}'
        )
    )
    assert parsed_json.resource.id == "json-tool"


@pytest.mark.parametrize(
    "raw",
    [
        b"private_notes: [SYNTHETIC-PRIVATE-SENTINEL\n",
        b"value: !SYNTHETIC-PRIVATE-SENTINEL payload\n",
        b"schema_version: 1\nresource: &base {id: one}\ncopy: *base\n",
        b"schema_version: 1\nresource:\n"
        b"  <<: {private_notes: SYNTHETIC-PRIVATE-SENTINEL}\n"
        b"  id: tool\n  name: Tool\n  categories: [tool]\n  capabilities: {build: 0.8}\n",
        b"schema_version: 1\nresource:\n  id: one\n  id: SYNTHETIC-PRIVATE-SENTINEL\n",
        b"schema_version: 1\nresource:\n  api_key: SYNTHETIC-PRIVATE-SENTINEL\n",
        b"schema_version: 1\nresource:\n  id: tool\n  name: Tool\n"
        b"  categories: [tool]\n  capabilities:\n"
        b"    SYNTHETIC-PRIVATE-SENTINEL: not-a-score\n",
    ],
)
def test_private_input_errors_do_not_echo_values_or_chain_source_exceptions(raw: bytes) -> None:
    _assert_value_free_error(raw)


def test_invalid_utf8_error_retains_no_source_exception() -> None:
    error = _assert_value_free_error(_SENTINEL.encode() + b"\xff")
    assert "valid UTF-8" in str(error)


def test_invalid_timestamp_constructor_error_is_source_free() -> None:
    raw = _declaration().replace(
        date.today().isoformat().encode(),
        b"2026-99-99",
    )
    error = _assert_value_free_error(raw)
    assert "invalid YAML scalar value" in str(error)


def test_excessive_flow_nesting_is_an_expected_source_free_error() -> None:
    raw = (
        b"schema_version: 1\nresource:\n  id: tool\n  name: Tool\n"
        b"  categories: [tool]\n  capabilities: {build: 0.8}\n"
        b"  private_notes: " + b"[" * 600 + _SENTINEL.encode() + b"]" * 600 + b"\n"
    )
    error = _assert_value_free_error(raw)
    assert "maximum nesting depth" in str(error)


@pytest.mark.parametrize(
    "value",
    [
        {"id": "bare-resource"},
        [],
        {"schema_version": 2, "resource": {}},
        {"schema_version": 1, "resource": {}, "extra": _SENTINEL},
    ],
)
def test_declaration_requires_exact_versioned_single_resource_envelope(value: object) -> None:
    with pytest.raises(ConfigurationError) as caught:
        parse_resource_declaration(value)

    assert _SENTINEL not in str(caught.value)


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_declaration_schema_version_requires_exact_native_integer(version: object) -> None:
    value = {
        "schema_version": version,
        "resource": {
            "id": "local-tool",
            "name": "Local Tool",
            "categories": ["tool"],
            "capabilities": {"build": 0.9},
        },
    }

    with pytest.raises(ConfigurationError, match="native YAML/JSON integer"):
        parse_resource_declaration(value)


@pytest.mark.parametrize("score", ["true", "'0.9'", ".nan"])
def test_declaration_scores_require_finite_native_numbers(score: str) -> None:
    raw = _declaration().replace(
        b"code-implementation: 0.9", f"code-implementation: {score}".encode()
    )

    with pytest.raises(ConfigurationError):
        load_resource_declaration_stdin(io.BytesIO(raw))


@pytest.mark.parametrize("value", ["'false'", "1", "'yes'"])
def test_declaration_booleans_require_native_boolean_values(value: str) -> None:
    raw = _declaration() + f"  policy:\n    approval_required: {value}\n".encode()

    with pytest.raises(ConfigurationError):
        load_resource_declaration_stdin(io.BytesIO(raw))


def test_declaration_rejects_normalized_capability_key_collisions() -> None:
    raw = _declaration().replace(
        b"    code-implementation: 0.9\n",
        b"    build: 0.1\n    ' build ': 0.9\n",
    )

    with pytest.raises(ConfigurationError, match="unique after normalization"):
        load_resource_declaration_stdin(io.BytesIO(raw))


@pytest.mark.parametrize(
    "raw",
    [
        _declaration().replace(b"categories: [coding-agent]", b"categories: !!set {tool: null}"),
        _declaration().replace(b"name: Local Tool", b"name: !!binary VG9vbA=="),
    ],
)
def test_declaration_rejects_unsupported_safe_loader_types(raw: bytes) -> None:
    with pytest.raises(ConfigurationError, match="unsupported YAML value type"):
        load_resource_declaration_stdin(io.BytesIO(raw))


def test_declaration_rejects_terminal_controls_in_handoff_guidance() -> None:
    raw = _declaration() + b'  handoff:\n    instructions: "safe\\u001b[2Junsafe"\n'

    with pytest.raises(ConfigurationError, match="unsafe control") as caught:
        load_resource_declaration_stdin(io.BytesIO(raw))

    assert "\x1b" not in str(caught.value)


class _InteractiveStream:
    read_called = False

    def isatty(self) -> bool:
        return True

    def read(self, _size: int) -> bytes:
        self.read_called = True
        raise AssertionError("interactive input must not be read")


def test_stdin_rejects_interactive_input_before_reading() -> None:
    stream = _InteractiveStream()
    with pytest.raises(ConfigurationError, match="interactive input is refused"):
        load_resource_declaration_stdin(stream)  # type: ignore[arg-type]
    assert stream.read_called is False


def test_annotation_stdin_rejects_interactive_input_before_reading() -> None:
    stream = _InteractiveStream()
    with pytest.raises(ConfigurationError, match=r"--annotation-stdin.*interactive input"):
        load_inventory_annotation_declaration_stdin(stream)  # type: ignore[arg-type]
    assert stream.read_called is False


class _ChunkedStream:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.offset = 0
        self.maximum_requested = 0

    def isatty(self) -> bool:
        return False

    def read(self, size: int) -> bytes:
        self.maximum_requested = max(self.maximum_requested, size)
        if self.offset >= len(self.raw):
            return b""
        end = min(self.offset + min(size, 17), len(self.raw))
        chunk = self.raw[self.offset : end]
        self.offset = end
        return chunk


def test_stdin_is_incremental_and_never_reads_past_the_bound() -> None:
    stream = _ChunkedStream(b"x" * (MAX_FILE_BYTES + 100))
    with pytest.raises(ConfigurationError, match="exceeds"):
        load_resource_declaration_stdin(stream)  # type: ignore[arg-type]

    assert stream.offset == MAX_FILE_BYTES + 1
    assert stream.maximum_requested <= 64 * 1024


def test_annotation_stdin_is_incremental_and_never_reads_past_the_bound() -> None:
    stream = _ChunkedStream(b"x" * (MAX_FILE_BYTES + 100))
    with pytest.raises(ConfigurationError, match="inventory annotation declaration exceeds"):
        load_inventory_annotation_declaration_stdin(stream)  # type: ignore[arg-type]

    assert stream.offset == MAX_FILE_BYTES + 1
    assert stream.maximum_requested <= 64 * 1024


def test_private_file_is_read_only_and_identity_checked(tmp_path: Path) -> None:
    source = tmp_path / "resource.yaml"
    raw = _declaration()
    _write_private(source, raw)
    before = source.stat()

    parsed = load_resource_declaration_file(source)

    assert parsed.resource.private_notes == _SENTINEL
    assert source.read_bytes() == raw
    after = source.stat()
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_annotation_file_is_read_only_and_identity_checked(tmp_path: Path) -> None:
    source = tmp_path / "annotation.yaml"
    raw = _annotation_declaration()
    _write_private(source, raw)
    before = source.stat()

    parsed = load_inventory_annotation_declaration_file(source)

    assert parsed.private_notes == _SENTINEL
    assert _SENTINEL not in repr(parsed)
    assert source.read_bytes() == raw
    after = source.stat()
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)


def test_annotation_file_parse_error_does_not_echo_contents(tmp_path: Path) -> None:
    source = tmp_path / "annotation.yaml"
    _write_private(
        source,
        b"schema_version: 1\nprivate_notes: [SYNTHETIC-PRIVATE-SENTINEL\n",
    )

    with pytest.raises(ConfigurationError) as caught:
        load_inventory_annotation_declaration_file(source)

    assert _SENTINEL not in str(caught.value)
    assert _SENTINEL not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-only source contract")
def test_annotation_file_requires_exact_owner_only_mode(tmp_path: Path) -> None:
    source = tmp_path / "annotation.yaml"
    source.write_bytes(_annotation_declaration())
    source.chmod(0o644)

    with pytest.raises(ConfigurationError, match="must have mode 0o600"):
        load_inventory_annotation_declaration_file(source)


def test_annotation_file_rejects_symlink_and_hard_link(tmp_path: Path) -> None:
    source = tmp_path / "annotation.yaml"
    _write_private(source, _annotation_declaration())
    symlink = tmp_path / "annotation-link.yaml"
    try:
        symlink.symlink_to(source)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are unavailable on this filesystem: {exc}")
    else:
        with pytest.raises(ConfigurationError, match="symlinked"):
            load_inventory_annotation_declaration_file(symlink)

    hard_link = tmp_path / "annotation-hard-link.yaml"
    try:
        os.link(source, hard_link)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"hard links are unavailable on this filesystem: {exc}")
    with pytest.raises(ConfigurationError, match="hard-linked"):
        load_inventory_annotation_declaration_file(source)


@pytest.mark.parametrize(
    "raw",
    [
        _SENTINEL.encode() + b"\xff",
        b"schema_version: 1\nresource:\n  private_notes: [SYNTHETIC-PRIVATE-SENTINEL\n",
    ],
)
def test_private_file_decode_and_parse_errors_do_not_echo_contents(
    tmp_path: Path, raw: bytes
) -> None:
    source = tmp_path / "resource.yaml"
    _write_private(source, raw)

    with pytest.raises(ConfigurationError) as caught:
        load_resource_declaration_file(source)

    assert _SENTINEL not in str(caught.value)
    assert _SENTINEL not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_private_file_rejects_oversized_input_before_reading(tmp_path: Path) -> None:
    source = tmp_path / "resource.yaml"
    _write_private(source, b"x" * (MAX_FILE_BYTES + 1))

    with pytest.raises(ConfigurationError, match="exceeds"):
        load_resource_declaration_file(source)


def test_private_file_rejects_path_substitution_while_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "resource.yaml"
    replacement = tmp_path / "replacement.yaml"
    displaced = tmp_path / "displaced.yaml"
    _write_private(source, _declaration())
    _write_private(replacement, _declaration(private_notes="different"))
    original_open = resource_input.os.open
    substituted = False

    def substitute_before_open(path: Path, flags: int, *args) -> int:
        nonlocal substituted
        if Path(path) == source and not substituted:
            substituted = True
            source.replace(displaced)
            replacement.replace(source)
        return original_open(path, flags, *args)

    monkeypatch.setattr(resource_input.os, "open", substitute_before_open)

    with pytest.raises(ConfigurationError, match="changed while being opened"):
        load_resource_declaration_file(source)


def test_private_file_rejects_same_file_mutation_after_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "resource.yaml"
    _write_private(source, _declaration())
    original_read = resource_input._read_bounded_stream
    changed_sentinel = "POST-READ-PRIVATE-SENTINEL"

    def mutate_after_read(stream, *, subject: str) -> bytes:
        raw = original_read(stream, subject=subject)
        source.write_bytes(_declaration(private_notes=changed_sentinel))
        return raw

    monkeypatch.setattr(resource_input, "_read_bounded_stream", mutate_after_read)

    with pytest.raises(ConfigurationError, match="changed while being read") as caught:
        load_resource_declaration_file(source)

    assert changed_sentinel not in str(caught.value)
    assert changed_sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_private_file_rejects_mutation_during_post_read_acl_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "resource.yaml"
    _write_private(source, _declaration())
    acl_checks = 0

    def mutate_on_second_check(_descriptor: int, _path: Path, *, subject: str) -> None:
        assert subject == "resource declaration"
        nonlocal acl_checks
        acl_checks += 1
        if acl_checks == 2:
            source.write_bytes(_declaration(private_notes="POST-READ-PRIVATE-SENTINEL"))

    monkeypatch.setattr(resource_input, "_validate_source_acl", mutate_on_second_check)

    with pytest.raises(ConfigurationError, match="changed while being read"):
        load_resource_declaration_file(source)


@pytest.mark.skipif(
    not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"),
    reason="FIFO substitution regression requires POSIX nonblocking descriptors",
)
def test_private_file_fifo_substitution_cannot_block_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "resource.yaml"
    _write_private(source, _declaration())
    original_open = resource_input.os.open

    def substitute_fifo(path: Path, flags: int) -> int:
        assert flags & os.O_NONBLOCK
        source.unlink()
        os.mkfifo(source, mode=0o600)
        return original_open(path, flags)

    monkeypatch.setattr(resource_input.os, "open", substitute_fifo)

    with pytest.raises(ConfigurationError, match="not a regular file"):
        load_resource_declaration_file(source)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS extended ACL contract")
def test_private_file_rejects_macos_extended_acl(tmp_path: Path) -> None:
    source = tmp_path / "resource.yaml"
    _write_private(source, _declaration())
    subprocess.run(  # noqa: S603
        ["/bin/chmod", "+a", "everyone allow read", str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    source.chmod(0o600)

    with pytest.raises(ConfigurationError, match="must not have a macOS extended ACL"):
        load_resource_declaration_file(source)


def test_private_file_rejects_missing_directory_symlink_and_hard_link(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_resource_declaration_file(tmp_path / "missing.yaml")
    with pytest.raises(ConfigurationError, match="not a regular file"):
        load_resource_declaration_file(tmp_path)

    source = tmp_path / "resource.yaml"
    _write_private(source, _declaration())
    symlink = tmp_path / "resource-link.yaml"
    try:
        symlink.symlink_to(source)
    except (NotImplementedError, OSError):
        pass
    else:
        with pytest.raises(ConfigurationError, match="symlinked"):
            load_resource_declaration_file(symlink)

    hard_link = tmp_path / "resource-hard-link.yaml"
    try:
        os.link(source, hard_link)
    except (NotImplementedError, OSError):
        return
    with pytest.raises(ConfigurationError, match="hard-linked"):
        load_resource_declaration_file(source)


@pytest.mark.skipif(os.name != "posix", reason="POSIX owner-only source contract")
def test_private_file_requires_exact_owner_only_mode(tmp_path: Path) -> None:
    source = tmp_path / "resource.yaml"
    source.write_bytes(_declaration())
    source.chmod(0o644)

    with pytest.raises(ConfigurationError, match="must have mode 0o600"):
        load_resource_declaration_file(source)
