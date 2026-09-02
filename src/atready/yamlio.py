"""Bounded, safe YAML input for local configuration files."""

from __future__ import annotations

import json
import os
import select
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from typing import Any, BinaryIO

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import (
    AliasToken,
    AnchorToken,
    BlockEndToken,
    BlockMappingStartToken,
    BlockSequenceStartToken,
    FlowMappingEndToken,
    FlowMappingStartToken,
    FlowSequenceEndToken,
    FlowSequenceStartToken,
)

from atready.errors import ConfigurationError
from atready.fsprivacy import (
    darwin_fd_has_extended_acl,
    descriptor_snapshot_unchanged,
    path_snapshot_unchanged,
    same_file_identity,
)

MAX_FILE_BYTES = 1_048_576
MAX_DEPTH = 32
MAX_ITEMS = 10_000
MAX_STRING_LENGTH = 65_536
_STREAM_READ_BYTES = 65_536
_TTY_JSON_LINE_TIMEOUT_SECONDS = 30.0
_TTY_TRAILING_INPUT_QUIET_SECONDS = 0.05
_TTY_TRAILING_INPUT_DRAIN_SECONDS = 2.0

_BLOCKED_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "passwd",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}


class UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that refuses ambiguous duplicate mapping keys."""


class _DuplicateJsonKeyError(ValueError):
    """Internal marker for duplicate JSON object keys."""


def _construct_unique_json_mapping(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key, value in pairs:
        if key in mapping:
            raise _DuplicateJsonKeyError
        mapping[key] = value
    return mapping


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader, node: MappingNode, deep: bool = False
) -> dict[Any, Any]:
    for key_node, _value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            raise ConfigurationError(
                f"YAML merge keys are not supported at line {key_node.start_mark.line + 1}"
            )
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        key_failure: ConfigurationError | None = None
        try:
            duplicate = key in mapping
        except TypeError:
            key_failure = ConfigurationError(
                f"mapping keys must be scalar values at line {key_node.start_mark.line + 1}"
            )
            duplicate = False
        if key_failure is not None:
            raise key_failure
        if duplicate:
            raise ConfigurationError(
                f"duplicate mapping key at line {key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _reject_aliases(text: str) -> None:
    failure: ConfigurationError | None = None
    collection_depth = 0
    collection_starts = (
        BlockMappingStartToken,
        BlockSequenceStartToken,
        FlowMappingStartToken,
        FlowSequenceStartToken,
    )
    collection_ends = (BlockEndToken, FlowMappingEndToken, FlowSequenceEndToken)
    try:
        tokens = yaml.scan(text, Loader=UniqueKeySafeLoader)
        for token in tokens:
            if isinstance(token, (AliasToken, AnchorToken)):
                raise ConfigurationError(
                    f"YAML anchors and aliases are not supported (line {token.start_mark.line + 1})"
                )
            if isinstance(token, collection_starts):
                collection_depth += 1
                if collection_depth > MAX_DEPTH:
                    raise ConfigurationError(
                        f"configuration exceeds maximum nesting depth {MAX_DEPTH}"
                    )
            elif isinstance(token, collection_ends):
                collection_depth = max(0, collection_depth - 1)
    except RecursionError:
        failure = ConfigurationError(f"configuration exceeds maximum nesting depth {MAX_DEPTH}")
    except yaml.YAMLError as exc:
        failure = _invalid_yaml_error(exc)
    if failure is not None:
        raise failure


def _invalid_yaml_error(exc: yaml.YAMLError) -> ConfigurationError:
    """Return a source-free YAML diagnostic that cannot echo private input."""

    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    if mark is None:
        return ConfigurationError("invalid YAML")
    return ConfigurationError(f"invalid YAML at line {mark.line + 1}, column {mark.column + 1}")


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def _validate_tree(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
    count: list[int] | None = None,
) -> None:
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > MAX_ITEMS:
        raise ConfigurationError(f"configuration exceeds {MAX_ITEMS} values")
    if depth > MAX_DEPTH:
        raise ConfigurationError(f"configuration exceeds maximum nesting depth {MAX_DEPTH}")

    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise ConfigurationError(
                f"configuration contains a string exceeding {MAX_STRING_LENGTH} characters"
            )
        return

    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ConfigurationError("configuration mapping keys must be strings")
            if _normalize_key(key) in _BLOCKED_KEYS:
                raise ConfigurationError(
                    "configuration contains a forbidden secret-bearing field name; "
                    "store credentials in an OS credential manager"
                )
            _validate_tree(child, path=f"{path}.{key}", depth=depth + 1, count=count)
        return

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for index, child in enumerate(value):
            _validate_tree(child, path=f"{path}[{index}]", depth=depth + 1, count=count)
        return

    if value is None or isinstance(value, (bool, int, date, datetime)):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ConfigurationError("configuration contains a non-finite number")
        return
    raise ConfigurationError("configuration contains an unsupported YAML value type")


def loads_yaml(text: str) -> Any:
    """Load bounded YAML into simple Python objects."""

    encoded_size: int | None = None
    try:
        encoded_size = len(text.encode("utf-8"))
    except UnicodeError:
        pass
    if encoded_size is None:
        raise ConfigurationError("configuration must be valid UTF-8 text")
    if encoded_size > MAX_FILE_BYTES:
        raise ConfigurationError(f"configuration exceeds {MAX_FILE_BYTES} bytes")
    _reject_aliases(text)
    failure: ConfigurationError | None = None
    try:
        # The loader subclasses SafeLoader and only changes duplicate-key handling.
        value = yaml.load(text, Loader=UniqueKeySafeLoader)  # noqa: S506  # nosec B506
    except ConfigurationError:
        raise
    except RecursionError:
        failure = ConfigurationError(f"configuration exceeds maximum nesting depth {MAX_DEPTH}")
        value = None
    except (OverflowError, TypeError, ValueError):
        failure = ConfigurationError("invalid YAML scalar value")
        value = None
    except yaml.YAMLError as exc:
        failure = _invalid_yaml_error(exc)
        value = None
    if failure is not None:
        raise failure
    if value is None:
        raise ConfigurationError("configuration is empty")
    _validate_tree(value)
    return value


def load_yaml_stdin(stream: BinaryIO, *, option: str, subject: str) -> Any:
    """Read one bounded YAML/JSON document from explicit non-interactive stdin."""

    isatty = getattr(stream, "isatty", None)
    if callable(isatty) and isatty():
        raise ConfigurationError(
            f"{option} requires piped or redirected input; interactive input is refused"
        )

    chunks: list[bytes] = []
    total = 0
    try:
        while total <= MAX_FILE_BYTES:
            chunk = stream.read(min(_STREAM_READ_BYTES, MAX_FILE_BYTES + 1 - total))
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise ConfigurationError(f"{subject} must provide bytes")
            chunks.append(chunk)
            total += len(chunk)
    except ConfigurationError:
        raise
    except (OSError, ValueError):
        raise ConfigurationError(f"cannot read {subject}") from None

    if total > MAX_FILE_BYTES:
        raise ConfigurationError(f"{subject} exceeds {MAX_FILE_BYTES} bytes")
    text: str | None = None
    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError:
        pass
    if text is None:
        raise ConfigurationError(f"{subject} must be valid UTF-8") from None
    return loads_yaml(text)


def _read_bounded_json_line(
    stream: BinaryIO,
    *,
    subject: str,
    max_bytes: int = MAX_FILE_BYTES,
) -> bytes:
    try:
        raw = stream.readline(max_bytes + 2)
    except KeyboardInterrupt:
        raise ConfigurationError(f"{subject} was cancelled") from None
    except (OSError, ValueError):
        raise ConfigurationError(f"cannot read {subject}") from None
    if not isinstance(raw, bytes):
        raise ConfigurationError(f"{subject} must provide bytes")
    if not raw.endswith(b"\n"):
        if len(raw) > max_bytes:
            raise ConfigurationError(f"{subject} exceeds {max_bytes} bytes")
        raise ConfigurationError(f"{subject} must end with one newline")
    payload = raw[:-1]
    if len(payload) > max_bytes:
        raise ConfigurationError(f"{subject} exceeds {max_bytes} bytes")
    return payload


def _read_bounded_tty_json_line(
    descriptor: int,
    *,
    subject: str,
    max_bytes: int,
) -> bytes:
    """Read exactly one terminal record without buffering bytes past its newline."""

    payload = bytearray()
    deadline = time.monotonic() + _TTY_JSON_LINE_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ConfigurationError(f"{subject} timed out before one complete line")
        try:
            readable, _, _ = select.select([descriptor], [], [], remaining)
        except KeyboardInterrupt:
            raise ConfigurationError(f"{subject} was cancelled") from None
        except InterruptedError:
            continue
        except (OSError, ValueError):
            raise ConfigurationError(f"cannot read {subject}") from None
        if not readable:
            raise ConfigurationError(f"{subject} timed out before one complete line")
        try:
            byte = os.read(descriptor, 1)
        except KeyboardInterrupt:
            raise ConfigurationError(f"{subject} was cancelled") from None
        except OSError:
            raise ConfigurationError(f"cannot read {subject}") from None
        if byte == b"\n":
            return bytes(payload)
        if not byte:
            raise ConfigurationError(f"{subject} must end with one newline")
        payload.extend(byte)
        if len(payload) > max_bytes:
            raise ConfigurationError(f"{subject} exceeds {max_bytes} bytes")


def _discard_tty_input_until_quiet(descriptor: int) -> bool:
    """Discard protocol-violating trailing input while terminal echo remains disabled."""

    hard_deadline = time.monotonic() + _TTY_TRAILING_INPUT_DRAIN_SECONDS
    quiet_deadline = time.monotonic() + _TTY_TRAILING_INPUT_QUIET_SECONDS
    while True:
        now = time.monotonic()
        remaining = min(hard_deadline, quiet_deadline) - now
        if remaining <= 0:
            return now < hard_deadline
        try:
            readable, _, _ = select.select([descriptor], [], [], remaining)
        except (KeyboardInterrupt, InterruptedError, OSError, ValueError):
            return False
        if not readable:
            return True
        try:
            chunk = os.read(descriptor, _STREAM_READ_BYTES)
        except (KeyboardInterrupt, OSError):
            return False
        if not chunk:
            return True
        quiet_deadline = time.monotonic() + _TTY_TRAILING_INPUT_QUIET_SECONDS


def _restore_tty_state(termios: Any, descriptor: int, original: list[Any]) -> None:
    try:
        termios.tcsetattr(descriptor, termios.TCSAFLUSH, original)
        restored = termios.tcgetattr(descriptor)
    except (KeyboardInterrupt, OSError, ValueError, termios.error):
        raise ConfigurationError(
            "cannot confirm terminal state restoration; close this terminal session "
            "before continuing"
        ) from None
    if restored != original:
        raise ConfigurationError(
            "cannot confirm terminal state restoration; close this terminal session "
            "before continuing"
        ) from None


def _read_tty_json_line_without_echo(
    stream: BinaryIO,
    *,
    option: str,
    subject: str,
    on_ready: Callable[[], None] | None,
    max_bytes: int,
) -> bytes:
    """Read one terminal line without reflecting private project text into tool output."""

    try:
        import termios
    except ImportError:
        raise ConfigurationError(
            f"{option} cannot safely read terminal input on this platform; use the command's "
            "non-terminal input mode"
        ) from None

    try:
        descriptor = stream.fileno()
        original = termios.tcgetattr(descriptor)
    except KeyboardInterrupt:
        raise ConfigurationError(f"{subject} was cancelled") from None
    except (AttributeError, OSError, ValueError, termios.error):
        raise ConfigurationError(
            f"{option} cannot suppress terminal echo; input was not read"
        ) from None

    protected = original.copy()
    protected[6] = original[6].copy()
    protected[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON)
    protected[6][termios.VMIN] = 1
    protected[6][termios.VTIME] = 0
    try:
        termios.tcsetattr(descriptor, termios.TCSAFLUSH, protected)
    except KeyboardInterrupt:
        _restore_tty_state(termios, descriptor, original)
        raise ConfigurationError(f"{subject} was cancelled") from None
    except (OSError, ValueError, termios.error):
        _restore_tty_state(termios, descriptor, original)
        raise ConfigurationError(
            f"{option} cannot suppress terminal echo; input was not read"
        ) from None

    try:
        applied = termios.tcgetattr(descriptor)
    except KeyboardInterrupt:
        _restore_tty_state(termios, descriptor, original)
        raise ConfigurationError(f"{subject} was cancelled") from None
    except (OSError, ValueError, termios.error):
        _restore_tty_state(termios, descriptor, original)
        raise ConfigurationError(
            f"{option} cannot confirm terminal echo suppression; input was not read"
        ) from None
    if (
        applied[3] & (termios.ECHO | termios.ECHONL | termios.ICANON)
        or applied[6][termios.VMIN] != 1
        or applied[6][termios.VTIME] != 0
    ):
        _restore_tty_state(termios, descriptor, original)
        raise ConfigurationError(
            f"{option} cannot confirm terminal echo suppression; input was not read"
        ) from None

    read_completed = False
    try:
        if on_ready is not None:
            on_ready()
        raw = _read_bounded_tty_json_line(
            descriptor,
            subject=subject,
            max_bytes=max_bytes,
        )
        read_completed = True
        return raw
    finally:
        trailing_input_quiet = _discard_tty_input_until_quiet(descriptor)
        _restore_tty_state(termios, descriptor, original)
        if read_completed and not trailing_input_quiet:
            raise ConfigurationError(
                "terminal input did not become idle; close this terminal session before continuing"
            ) from None


def load_json_line_stdin(
    stream: BinaryIO,
    *,
    option: str,
    subject: str,
    on_ready: Callable[[], None] | None = None,
    max_bytes: int = MAX_FILE_BYTES,
) -> Any:
    """Read one bounded JSON record from stdin, including an explicitly requested agent PTY."""

    isatty = getattr(stream, "isatty", None)
    interactive = bool(callable(isatty) and isatty())
    if interactive:
        raw = _read_tty_json_line_without_echo(
            stream,
            option=option,
            subject=subject,
            on_ready=on_ready,
            max_bytes=max_bytes,
        )
    else:
        if on_ready is not None:
            on_ready()
        raw = _read_bounded_json_line(stream, subject=subject, max_bytes=max_bytes)

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_construct_unique_json_mapping,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except UnicodeDecodeError:
        raise ConfigurationError(f"{subject} must be valid UTF-8") from None
    except _DuplicateJsonKeyError:
        raise ConfigurationError(f"{subject} contains a duplicate JSON mapping key") from None
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"invalid JSON at line {exc.lineno}, column {exc.colno}") from None
    except (RecursionError, ValueError):
        raise ConfigurationError(f"invalid {subject}") from None

    _validate_tree(value)
    return value


def load_yaml(path: Path) -> Any:
    """Read bounded YAML through an identity-checked, nonblocking descriptor."""

    path = path.expanduser()
    try:
        inspected = path.lstat()
    except FileNotFoundError as exc:
        raise ConfigurationError(f"configuration file does not exist: {path}") from exc
    except OSError as exc:
        raise ConfigurationError(f"cannot inspect configuration {path}: {exc}") from exc
    if stat.S_ISLNK(inspected.st_mode):
        raise ConfigurationError(f"refusing to read symlinked configuration: {path}")
    if not stat.S_ISREG(inspected.st_mode):
        raise ConfigurationError(f"configuration path is not a regular file: {path}")
    if inspected.st_size > MAX_FILE_BYTES:
        raise ConfigurationError(f"configuration exceeds {MAX_FILE_BYTES} bytes: {path}")

    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= int(getattr(os, flag_name, 0))
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ConfigurationError(f"cannot open configuration {path}") from None

    failure: ConfigurationError | None = None
    opened: os.stat_result | None = None
    raw = b""
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            failure = ConfigurationError(f"configuration path is not a regular file: {path}")
        elif not same_file_identity(opened, inspected):
            failure = ConfigurationError(f"configuration changed while being opened: {path}")
        elif opened.st_size > MAX_FILE_BYTES:
            failure = ConfigurationError(f"configuration exceeds {MAX_FILE_BYTES} bytes: {path}")
        else:
            try:
                if darwin_fd_has_extended_acl(descriptor):
                    failure = ConfigurationError(
                        f"refusing configuration with a macOS extended ACL: {path}"
                    )
            except OSError:
                failure = ConfigurationError(
                    f"cannot verify configuration extended access controls: {path}"
                )
        if failure is None:
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            try:
                if darwin_fd_has_extended_acl(descriptor):
                    failure = ConfigurationError(
                        f"configuration gained a macOS extended ACL while being read: {path}"
                    )
            except OSError:
                failure = ConfigurationError(
                    f"cannot recheck configuration extended access controls: {path}"
                )
            if failure is None:
                os.lseek(descriptor, 0, os.SEEK_SET)
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    confirmed_raw = stream.read(MAX_FILE_BYTES + 1)
                if confirmed_raw != raw:
                    failure = ConfigurationError(f"configuration changed while being read: {path}")
            if failure is None:
                after = os.fstat(descriptor)
                if not descriptor_snapshot_unchanged(after, opened):
                    failure = ConfigurationError(f"configuration changed while being read: {path}")
    except OSError:
        failure = ConfigurationError(f"cannot read configuration {path}")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            if failure is None:
                failure = ConfigurationError(f"cannot close configuration after reading: {path}")
    if failure is None:
        try:
            final = path.lstat()
        except OSError:
            failure = ConfigurationError(f"cannot verify configuration after reading: {path}")
        else:
            assert opened is not None
            if not path_snapshot_unchanged(final, inspected=inspected, opened=opened):
                failure = ConfigurationError(f"configuration changed while being read: {path}")
    if failure is not None:
        raise failure
    if len(raw) > MAX_FILE_BYTES:
        raise ConfigurationError(f"configuration exceeds {MAX_FILE_BYTES} bytes: {path}")
    text: str | None = None
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        pass
    if text is None:
        raise ConfigurationError(f"cannot read UTF-8 configuration {path}") from None
    return loads_yaml(text)


def dumps_yaml(value: Any) -> str:
    """Serialize simple objects without Python-specific YAML tags."""

    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
