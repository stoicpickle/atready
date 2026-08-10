"""Bounded, safe YAML input for local configuration files."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from typing import Any

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
