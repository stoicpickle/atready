from __future__ import annotations

import io
import os
import select
import threading
from pathlib import Path

import pytest

import atready.yamlio as yamlio
from atready.errors import ConfigurationError
from atready.yamlio import (
    MAX_FILE_BYTES,
    load_json_line_stdin,
    load_yaml,
    load_yaml_stdin,
    loads_yaml,
)


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


class _InteractiveInput(io.BytesIO):
    def isatty(self) -> bool:
        return True


def test_stdin_loader_accepts_bounded_yaml_and_json() -> None:
    assert load_yaml_stdin(
        io.BytesIO(b'{"value": "safe"}'), option="--test-stdin", subject="test input"
    ) == {"value": "safe"}
    assert load_yaml_stdin(
        io.BytesIO(b"value: safe\n"), option="--test-stdin", subject="test input"
    ) == {"value": "safe"}


def test_stdin_loader_refuses_tty_before_reading() -> None:
    with pytest.raises(ConfigurationError, match="interactive input is refused"):
        load_yaml_stdin(
            _InteractiveInput(b"value: safe\n"),
            option="--test-stdin",
            subject="test input",
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"value":"safe"}', "must end with one newline"),
        (b"x" * (MAX_FILE_BYTES + 1), "exceeds"),
        (b"\xff\n", "valid UTF-8"),
        (b'{"value":1,"value":2}\n', "duplicate JSON mapping key"),
        (b'{"token":"forbidden"}\n', "secret-bearing field"),
    ],
    ids=["missing-newline", "oversized", "invalid-utf8", "duplicate-key", "secret-key"],
)
def test_json_line_stdin_preserves_framing_and_tree_guards(payload: bytes, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_json_line_stdin(io.BytesIO(payload), option="--test-json-line", subject="test input")


def test_json_line_stdin_accepts_one_bounded_record() -> None:
    ready: list[bool] = []
    assert load_json_line_stdin(
        io.BytesIO(b'{"value":"safe"}\n'),
        option="--test-json-line",
        subject="test input",
        on_ready=lambda: ready.append(True),
    ) == {"value": "safe"}
    assert ready == [True]


def test_json_line_stdin_reports_cancel_without_a_traceback() -> None:
    class _InterruptedInput(io.BytesIO):
        def readline(self, _size: int = -1) -> bytes:
            raise KeyboardInterrupt

    with pytest.raises(ConfigurationError, match="test input was cancelled"):
        load_json_line_stdin(_InterruptedInput(), option="--test-json-line", subject="test input")


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="terminal echo proof requires a POSIX PTY")
def test_json_line_tty_disables_echo_before_signaling_ready() -> None:
    import termios

    master, slave = os.openpty()
    configured = termios.tcgetattr(slave)
    configured[6] = configured[6].copy()
    configured[6][termios.VMIN] = 7
    configured[6][termios.VTIME] = 9
    termios.tcsetattr(slave, termios.TCSANOW, configured)
    expected = termios.tcgetattr(slave)
    stream = os.fdopen(slave, "rb", buffering=0)
    ready = threading.Event()
    result: dict[str, object] = {}
    failure: list[BaseException] = []

    def load() -> None:
        try:
            result["value"] = load_json_line_stdin(
                stream,
                option="--test-json-line",
                subject="test input",
                on_ready=ready.set,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            failure.append(exc)

    worker = threading.Thread(target=load)
    try:
        worker.start()
        assert ready.wait(timeout=2)
        sentinel = b"private-project-sentinel" + (b"x" * 8_192)
        trailing = b"SYNTHETIC-TRAILING-INPUT\n"
        os.write(master, b'{"value":"' + sentinel + b'"}\n' + trailing)
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert failure == []
        assert result == {"value": {"value": sentinel.decode("ascii")}}
        restored = termios.tcgetattr(stream.fileno())
        assert restored[6][termios.VMIN] == expected[6][termios.VMIN]
        assert restored[6][termios.VTIME] == expected[6][termios.VTIME]
        queued, _, _ = select.select([stream.fileno()], [], [], 0.1)
        assert queued == []
        readable, _, _ = select.select([master], [], [], 0.1)
        reflected = os.read(master, 4096) if readable else b""
        assert sentinel not in reflected
        assert trailing not in reflected
        assert b"\a" not in reflected
    finally:
        stream.close()
        os.close(master)


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="terminal drain proof requires a POSIX PTY")
def test_json_line_tty_drains_concurrent_trailing_input_before_restoring_echo() -> None:
    import termios

    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    stream = os.fdopen(slave, "rb", buffering=0)
    ready = threading.Event()
    result: dict[str, object] = {}
    failure: list[BaseException] = []
    write_failure: list[BaseException] = []

    def load() -> None:
        try:
            result["value"] = load_json_line_stdin(
                stream,
                option="--test-json-line",
                subject="test input",
                on_ready=ready.set,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            failure.append(exc)

    # Exceed a typical PTY input queue without making the writer depend on consuming
    # several megabytes inside the production two-second drain deadline.
    trailing = b"LATE-SYNTHETIC-INPUT" * 8_192

    def write() -> None:
        remaining = memoryview(b'{"value":"safe"}\n' + trailing)
        try:
            while remaining:
                written = os.write(master, remaining)
                remaining = remaining[written:]
        except BaseException as exc:  # pragma: no cover - surfaced below
            write_failure.append(exc)

    worker = threading.Thread(target=load)
    writer = threading.Thread(target=write)
    try:
        worker.start()
        assert ready.wait(timeout=2)
        writer.start()
        worker.join(timeout=4)
        writer.join(timeout=4)
        assert not worker.is_alive()
        assert not writer.is_alive()
        assert failure == []
        assert write_failure == []
        assert result == {"value": {"value": "safe"}}
        assert termios.tcgetattr(stream.fileno()) == original
        queued, _, _ = select.select([stream.fileno()], [], [], 0.1)
        assert queued == []
        readable, _, _ = select.select([master], [], [], 0.1)
        reflected = os.read(master, 65_536) if readable else b""
        assert b"LATE-SYNTHETIC-INPUT" not in reflected
    finally:
        stream.close()
        os.close(master)


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="terminal state proof requires a POSIX PTY")
def test_json_line_tty_reports_terminal_restoration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termios

    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    stream = os.fdopen(slave, "rb", buffering=0)
    ready = threading.Event()
    failure: list[BaseException] = []
    real_tcsetattr = termios.tcsetattr
    calls: list[int] = []

    def fail_restore(descriptor: int, when: int, attributes: list[object]) -> None:
        calls.append(when)
        if len(calls) == 2:
            raise termios.error("synthetic restoration failure")
        real_tcsetattr(descriptor, when, attributes)

    monkeypatch.setattr(termios, "tcsetattr", fail_restore)

    def load() -> None:
        try:
            load_json_line_stdin(
                stream,
                option="--test-json-line",
                subject="test input",
                on_ready=ready.set,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            failure.append(exc)

    worker = threading.Thread(target=load)
    try:
        worker.start()
        assert ready.wait(timeout=2)
        os.write(master, b'{"value":"safe"}\n')
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert len(failure) == 1
        assert isinstance(failure[0], ConfigurationError)
        assert str(failure[0]) == (
            "cannot confirm terminal state restoration; close this terminal session "
            "before continuing"
        )
        assert calls == [termios.TCSAFLUSH, termios.TCSAFLUSH]
    finally:
        monkeypatch.setattr(termios, "tcsetattr", real_tcsetattr)
        real_tcsetattr(stream.fileno(), termios.TCSAFLUSH, original)
        stream.close()
        os.close(master)


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="terminal state proof requires a POSIX PTY")
def test_json_line_tty_refuses_before_ready_when_protection_is_not_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termios

    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    stream = os.fdopen(slave, "rb", buffering=0)
    ready: list[bool] = []
    real_tcsetattr = termios.tcsetattr
    calls = 0

    def ignore_protection(descriptor: int, when: int, attributes: list[object]) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            real_tcsetattr(descriptor, when, attributes)

    monkeypatch.setattr(termios, "tcsetattr", ignore_protection)
    try:
        with pytest.raises(ConfigurationError, match="cannot confirm terminal echo suppression"):
            load_json_line_stdin(
                stream,
                option="--test-json-line",
                subject="test input",
                on_ready=lambda: ready.append(True),
            )
        assert ready == []
        assert termios.tcgetattr(stream.fileno()) == original
    finally:
        monkeypatch.setattr(termios, "tcsetattr", real_tcsetattr)
        real_tcsetattr(stream.fileno(), termios.TCSAFLUSH, original)
        stream.close()
        os.close(master)


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="terminal state proof requires a POSIX PTY")
def test_json_line_tty_reports_silent_restoration_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termios

    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    stream = os.fdopen(slave, "rb", buffering=0)
    ready = threading.Event()
    failure: list[BaseException] = []
    real_tcsetattr = termios.tcsetattr
    calls = 0

    def ignore_restore(descriptor: int, when: int, attributes: list[object]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            real_tcsetattr(descriptor, when, attributes)

    monkeypatch.setattr(termios, "tcsetattr", ignore_restore)

    def load() -> None:
        try:
            load_json_line_stdin(
                stream,
                option="--test-json-line",
                subject="test input",
                on_ready=ready.set,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            failure.append(exc)

    worker = threading.Thread(target=load)
    try:
        worker.start()
        assert ready.wait(timeout=2)
        os.write(master, b'{"value":"safe"}\n')
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert len(failure) == 1
        assert isinstance(failure[0], ConfigurationError)
        assert "cannot confirm terminal state restoration" in str(failure[0])
    finally:
        monkeypatch.setattr(termios, "tcsetattr", real_tcsetattr)
        real_tcsetattr(stream.fileno(), termios.TCSAFLUSH, original)
        stream.close()
        os.close(master)


@pytest.mark.skipif(
    not hasattr(os, "openpty"),
    reason="terminal timeout proof requires a POSIX PTY",
)
def test_json_line_tty_times_out_on_an_incomplete_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termios

    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    stream = os.fdopen(slave, "rb", buffering=0)
    ready = threading.Event()
    read_seen = threading.Event()
    failure: list[BaseException] = []
    real_os_read = os.read

    def observed_read(descriptor: int, count: int) -> bytes:
        value = real_os_read(descriptor, count)
        if value:
            read_seen.set()
        return value

    monkeypatch.setattr(yamlio, "_TTY_JSON_LINE_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(yamlio.os, "read", observed_read)

    def load() -> None:
        try:
            load_json_line_stdin(
                stream,
                option="--test-json-line",
                subject="test input",
                on_ready=ready.set,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            failure.append(exc)

    worker = threading.Thread(target=load)
    try:
        worker.start()
        assert ready.wait(timeout=2)
        os.write(master, b'{"value":"incomplete"}')
        assert read_seen.wait(timeout=2)
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert len(failure) == 1
        assert isinstance(failure[0], ConfigurationError)
        assert str(failure[0]) == "test input timed out before one complete line"
        assert termios.tcgetattr(stream.fileno()) == original
        os.set_blocking(stream.fileno(), False)
        try:
            queued = real_os_read(stream.fileno(), 65_536)
        except BlockingIOError:
            queued = b""
        assert queued == b""
    finally:
        stream.close()
        os.close(master)


@pytest.mark.skipif(not hasattr(os, "openpty"), reason="terminal cancel proof requires a POSIX PTY")
def test_json_line_tty_reports_cancel_and_restores_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import termios

    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    stream = os.fdopen(slave, "rb", buffering=0)

    def interrupt(*_args: object) -> tuple[list[int], list[int], list[int]]:
        raise KeyboardInterrupt

    monkeypatch.setattr(yamlio.select, "select", interrupt)
    try:
        with pytest.raises(ConfigurationError, match="test input was cancelled"):
            load_json_line_stdin(
                stream,
                option="--test-json-line",
                subject="test input",
            )
        assert termios.tcgetattr(stream.fileno()) == original
    finally:
        stream.close()
        os.close(master)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"x" * (MAX_FILE_BYTES + 1), "exceeds"),
        (b"\xff\n", "valid UTF-8"),
        (b"", "configuration is empty"),
        (b"value: first\nvalue: second\n", "duplicate mapping key"),
        (b"value: &anchor safe\n", "anchors and aliases"),
        (b"token: forbidden\n", "secret-bearing field"),
    ],
    ids=["oversized", "invalid-utf8", "empty", "duplicate-key", "alias", "secret-key"],
)
def test_stdin_loader_preserves_bounded_yaml_guards(payload: bytes, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_yaml_stdin(io.BytesIO(payload), option="--test-stdin", subject="test input")


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
