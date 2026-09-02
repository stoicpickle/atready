"""Argv-safe, bounded adapters for versioned private declaration inputs."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Literal, TypeVar

from pydantic import ValidationError

from atready.diagnostics import RESOURCE_LOCATION_FIELDS, validation_configuration_error
from atready.errors import ConfigurationError
from atready.fsprivacy import (
    darwin_fd_has_extended_acl,
    descriptor_snapshot_unchanged,
    path_snapshot_unchanged,
    same_file_identity,
)
from atready.models import (
    AccessStatus,
    ConfidenceBasis,
    InventoryAnnotationDeclaration,
    QuotaStatus,
    Resource,
    ResourceDeclaration,
    SessionAvailability,
)
from atready.yamlio import MAX_FILE_BYTES, load_yaml_stdin, loads_yaml

_READ_CHUNK_BYTES = 64 * 1024
_INVENTORY_ANNOTATION_LOCATION_FIELDS = frozenset({"private_notes", "schema_version"})
_ParsedDeclaration = TypeVar("_ParsedDeclaration")
_DEFAULTABLE_RESOURCE_FIELDS = (
    "access.status",
    "access.interaction",
    "access.current_session",
    "economics.billing",
    "economics.marginal_cost",
    "economics.quota",
    "economics.capacity",
    "policy.allowed_data_classes",
    "policy.approval_required",
    "policy.requires_network",
    "provenance.basis",
    "provenance.last_verified",
    "handoff.method",
    "ratings.quality",
    "ratings.speed",
    "ratings.autonomy",
    "ratings.privacy",
    "ratings.reliability",
    "ratings.confidence",
    "ratings.context_switch_cost",
    "ratings.integration_friction",
)
_SELECTION_FACT_FIELDS = (
    "access.status",
    "access.current_session",
    "economics.quota",
    "economics.capacity",
    "provenance.basis",
    "provenance.last_verified",
)
_SCORING_INPUT_FIELDS = (
    "economics.marginal_cost",
    "ratings.quality",
    "ratings.speed",
    "ratings.autonomy",
    "ratings.privacy",
    "ratings.reliability",
    "ratings.confidence",
    "ratings.context_switch_cost",
    "ratings.integration_friction",
)
_CONSERVATIVE_POLICY_FIELDS = (
    "policy.allowed_data_classes",
    "policy.approval_required",
    "policy.requires_network",
)
_OPERATING_CONTEXT_FIELDS = (
    "access.interaction",
    "economics.billing",
    "handoff.method",
)

ResourceIntakeStatus = Literal[
    "declared-unavailable",
    "requires-verification",
    "selection-facts-declared",
]


@dataclass(frozen=True)
class ParsedResourceDeclaration:
    """Validated resource plus the defaults the caller must surface for review."""

    resource: Resource = field(repr=False)
    defaulted_fields: tuple[str, ...]


@dataclass(frozen=True)
class ResourceIntakeReview:
    """Preview-only review of declared selection facts and input defaults.

    This does not evaluate project-specific route eligibility or provenance freshness.
    """

    selection_fact_status: ResourceIntakeStatus
    unverified_selection_facts: tuple[str, ...]
    declared_unavailable_facts: tuple[str, ...]
    defaulted_selection_facts: tuple[str, ...]
    defaulted_scoring_inputs: tuple[str, ...]
    defaulted_conservative_policy: tuple[str, ...]
    defaulted_operating_context: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "declared_unavailable_facts": list(self.declared_unavailable_facts),
            "default_groups": {
                "conservative_policy": list(self.defaulted_conservative_policy),
                "operating_context": list(self.defaulted_operating_context),
                "scoring_inputs": list(self.defaulted_scoring_inputs),
                "selection_facts": list(self.defaulted_selection_facts),
            },
            "route_eligibility_evaluated": False,
            "selection_fact_status": self.selection_fact_status,
            "unverified_selection_facts": list(self.unverified_selection_facts),
        }


def resource_intake_review(
    resource: Resource,
    defaulted_fields: tuple[str, ...],
) -> ResourceIntakeReview:
    """Summarize intake facts without claiming project-specific route eligibility."""

    unverified: list[str] = []
    if resource.access.status is AccessStatus.UNKNOWN:
        unverified.append("access.status")
    if resource.access.current_session is SessionAvailability.UNKNOWN:
        unverified.append("access.current_session")
    if resource.economics.quota is QuotaStatus.UNKNOWN:
        unverified.append("economics.quota")
    if resource.provenance.basis is ConfidenceBasis.UNKNOWN:
        unverified.append("provenance.basis")
    if resource.provenance.last_verified is None:
        unverified.append("provenance.last_verified")

    unavailable: list[str] = []
    if resource.access.status is AccessStatus.INACTIVE:
        unavailable.append("access.status")
    if resource.access.current_session is SessionAvailability.UNAVAILABLE:
        unavailable.append("access.current_session")
    if resource.economics.quota is QuotaStatus.EXHAUSTED:
        unavailable.append("economics.quota")

    if unavailable:
        status: ResourceIntakeStatus = "declared-unavailable"
    elif unverified:
        status = "requires-verification"
    else:
        status = "selection-facts-declared"

    defaulted = frozenset(defaulted_fields)

    def selected(paths: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(path for path in paths if path in defaulted)

    return ResourceIntakeReview(
        selection_fact_status=status,
        unverified_selection_facts=tuple(unverified),
        declared_unavailable_facts=tuple(unavailable),
        defaulted_selection_facts=selected(_SELECTION_FACT_FIELDS),
        defaulted_scoring_inputs=selected(_SCORING_INPUT_FIELDS),
        defaulted_conservative_policy=selected(_CONSERVATIVE_POLICY_FIELDS),
        defaulted_operating_context=selected(_OPERATING_CONTEXT_FIELDS),
    )


def _validation_error(exc: ValidationError, *, subject: str) -> ConfigurationError:
    return validation_configuration_error(
        exc,
        subject=subject,
        allowed_fields=RESOURCE_LOCATION_FIELDS,
        dynamic_mapping_fields={"capabilities"},
    )


def _path_is_present(value: Mapping[str, Any], dotted_path: str) -> bool:
    current: Any = value
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return True


def parse_resource_mapping(value: dict[str, Any]) -> ParsedResourceDeclaration:
    """Validate one already-materialized resource mapping."""

    failure: ConfigurationError | None = None
    try:
        resource = Resource.model_validate(value)
    except ValidationError as exc:
        failure = _validation_error(exc, subject="resource")
        resource = None
    if failure is not None:
        raise failure
    assert resource is not None
    defaulted = tuple(
        path for path in _DEFAULTABLE_RESOURCE_FIELDS if not _path_is_present(value, path)
    )
    return ParsedResourceDeclaration(resource=resource, defaulted_fields=defaulted)


def parse_resource_declaration(value: Any) -> ParsedResourceDeclaration:
    """Validate one strict, versioned resource declaration envelope."""

    failure: ConfigurationError | None = None
    try:
        declaration = ResourceDeclaration.model_validate(value)
    except ValidationError as exc:
        failure = _validation_error(exc, subject="resource declaration")
        declaration = None
    if failure is not None:
        raise failure
    assert declaration is not None
    if not isinstance(value, Mapping) or not isinstance(value.get("resource"), Mapping):
        raise ConfigurationError("resource declaration must contain one resource mapping")
    defaulted = tuple(
        path
        for path in _DEFAULTABLE_RESOURCE_FIELDS
        if not _path_is_present(value["resource"], path)
    )
    return ParsedResourceDeclaration(
        resource=declaration.resource,
        defaulted_fields=defaulted,
    )


def parse_inventory_annotation_declaration(value: Any) -> InventoryAnnotationDeclaration:
    """Validate one strict, versioned root annotation declaration envelope."""

    failure: ConfigurationError | None = None
    try:
        declaration = InventoryAnnotationDeclaration.model_validate(value)
    except ValidationError as exc:
        failure = validation_configuration_error(
            exc,
            subject="inventory annotation declaration",
            allowed_fields=_INVENTORY_ANNOTATION_LOCATION_FIELDS,
        )
        declaration = None
    if failure is not None:
        raise failure
    assert declaration is not None
    return declaration


def _decode_and_parse(
    raw: bytes,
    *,
    subject: str,
    parser: Callable[[Any], _ParsedDeclaration],
) -> _ParsedDeclaration:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None:
        raise ConfigurationError(f"{subject} must be valid UTF-8")
    return parser(loads_yaml(text))


def _read_bounded_stream(stream: BinaryIO, *, subject: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    failure: ConfigurationError | None = None
    try:
        while total <= MAX_FILE_BYTES:
            chunk = stream.read(min(_READ_CHUNK_BYTES, MAX_FILE_BYTES + 1 - total))
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                failure = ConfigurationError(f"{subject} must provide bytes")
                break
            chunks.append(chunk)
            total += len(chunk)
    except (OSError, ValueError):
        failure = ConfigurationError(f"cannot read {subject}")
    if failure is not None:
        raise failure
    if total > MAX_FILE_BYTES:
        raise ConfigurationError(f"{subject} exceeds {MAX_FILE_BYTES} bytes")
    return b"".join(chunks)


def _load_declaration_stdin(
    stream: BinaryIO,
    *,
    option: str,
    subject: str,
    parser: Callable[[Any], _ParsedDeclaration],
) -> _ParsedDeclaration:
    return parser(load_yaml_stdin(stream, option=option, subject=subject))


def load_resource_declaration_stdin(stream: BinaryIO) -> ParsedResourceDeclaration:
    """Read one bounded declaration from explicit, non-interactive binary stdin."""

    return _load_declaration_stdin(
        stream,
        option="--resource-stdin",
        subject="resource declaration",
        parser=parse_resource_declaration,
    )


def load_inventory_annotation_declaration_stdin(
    stream: BinaryIO,
) -> InventoryAnnotationDeclaration:
    """Read one root annotation declaration from explicit non-interactive stdin."""

    return _load_declaration_stdin(
        stream,
        option="--annotation-stdin",
        subject="inventory annotation declaration",
        parser=parse_inventory_annotation_declaration,
    )


def _validate_private_source_file(
    path: Path,
    details: os.stat_result,
    *,
    subject: str,
) -> None:
    if not stat.S_ISREG(details.st_mode):
        raise ConfigurationError(f"{subject} is not a regular file: {path}")
    if details.st_nlink != 1:
        raise ConfigurationError(f"refusing hard-linked {subject} file: {path}")
    if os.name == "posix":
        if details.st_uid != os.geteuid():
            raise ConfigurationError(f"{subject} file is not owned by the current user: {path}")
        mode = stat.S_IMODE(details.st_mode)
        if mode != 0o600:
            raise ConfigurationError(
                f"{subject} file must have mode 0o600, found {oct(mode)}: {path}"
            )
    if details.st_size > MAX_FILE_BYTES:
        raise ConfigurationError(f"{subject} exceeds {MAX_FILE_BYTES} bytes: {path}")


def _validate_source_acl(descriptor: int, path: Path, *, subject: str) -> None:
    try:
        has_extended_acl = darwin_fd_has_extended_acl(descriptor)
    except OSError:
        raise ConfigurationError(
            f"cannot verify {subject} extended access controls: {path}"
        ) from None
    if has_extended_acl:
        raise ConfigurationError(f"{subject} must not have a macOS extended ACL: {path}")


def _lstat_source(path: Path, *, subject: str) -> os.stat_result:
    try:
        details = path.lstat()
    except FileNotFoundError:
        raise ConfigurationError(f"{subject} file does not exist: {path}") from None
    except OSError:
        raise ConfigurationError(f"cannot inspect {subject} file: {path}") from None
    if stat.S_ISLNK(details.st_mode):
        raise ConfigurationError(f"refusing symlinked {subject} file: {path}")
    _validate_private_source_file(path, details, subject=subject)
    return details


def _load_declaration_file(
    path: Path,
    *,
    subject: str,
    parser: Callable[[Any], _ParsedDeclaration],
) -> _ParsedDeclaration:
    path = path.expanduser()
    inspected = _lstat_source(path, subject=subject)
    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= int(getattr(os, flag_name, 0))
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ConfigurationError(f"cannot open {subject} file: {path}") from None

    failure: ConfigurationError | None = None
    opened: os.stat_result | None = None
    raw = b""
    try:
        opened = os.fstat(descriptor)
        _validate_private_source_file(path, opened, subject=subject)
        _validate_source_acl(descriptor, path, subject=subject)
        if not same_file_identity(inspected, opened):
            failure = ConfigurationError(f"{subject} file changed while being opened: {path}")
        else:
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = _read_bounded_stream(stream, subject=f"{subject} file")
            _validate_source_acl(descriptor, path, subject=subject)
            if failure is None:
                os.lseek(descriptor, 0, os.SEEK_SET)
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    confirmed_raw = _read_bounded_stream(
                        stream,
                        subject=f"{subject} file",
                    )
                if confirmed_raw != raw:
                    failure = ConfigurationError(f"{subject} file changed while being read: {path}")
            if failure is None:
                after = os.fstat(descriptor)
                if not descriptor_snapshot_unchanged(after, opened):
                    failure = ConfigurationError(f"{subject} file changed while being read: {path}")
    except ConfigurationError as exc:
        failure = exc
    except OSError:
        failure = ConfigurationError(f"cannot read {subject} file: {path}")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            if failure is None:
                failure = ConfigurationError(f"cannot close {subject} file after reading: {path}")
    if failure is None:
        try:
            final = _lstat_source(path, subject=subject)
        except ConfigurationError:
            failure = ConfigurationError(f"cannot verify {subject} file after reading: {path}")
        else:
            assert opened is not None
            if not path_snapshot_unchanged(final, inspected=inspected, opened=opened):
                failure = ConfigurationError(f"{subject} file changed while being read: {path}")
    if failure is not None:
        raise failure
    return _decode_and_parse(
        raw,
        subject=subject,
        parser=parser,
    )


def load_resource_declaration_file(path: Path) -> ParsedResourceDeclaration:
    """Read one protected file through a bounded, identity-checked descriptor."""

    return _load_declaration_file(
        path,
        subject="resource declaration",
        parser=parse_resource_declaration,
    )


def load_inventory_annotation_declaration_file(
    path: Path,
) -> InventoryAnnotationDeclaration:
    """Read one protected root annotation declaration through the shared safe transport."""

    return _load_declaration_file(
        path,
        subject="inventory annotation declaration",
        parser=parse_inventory_annotation_declaration,
    )
