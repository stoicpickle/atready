"""Project brief loading and validation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import ValidationError

from atready.diagnostics import PROJECT_LOCATION_FIELDS, validation_configuration_error
from atready.errors import ConfigurationError
from atready.models import ProjectBrief
from atready.yamlio import load_json_line_stdin, load_yaml, load_yaml_stdin, loads_yaml


def project_from_mapping(value: Any) -> ProjectBrief:
    if not isinstance(value, dict):
        raise ConfigurationError("project root must be a mapping")
    failure: ConfigurationError | None = None
    try:
        return ProjectBrief.model_validate(value)
    except ValidationError as exc:
        failure = validation_configuration_error(
            exc,
            subject="project",
            allowed_fields=PROJECT_LOCATION_FIELDS,
        )
    assert failure is not None
    raise failure


def project_from_path(path: Path) -> ProjectBrief:
    return project_from_mapping(load_yaml(path))


def project_from_text(text: str) -> ProjectBrief:
    return project_from_mapping(loads_yaml(text))


def project_from_stdin(stream: BinaryIO) -> ProjectBrief:
    """Read one bounded project brief from explicit non-interactive stdin."""

    return project_from_mapping(
        load_yaml_stdin(stream, option="--project-stdin", subject="project brief")
    )


def project_from_json_line(
    stream: BinaryIO, *, on_ready: Callable[[], None] | None = None
) -> ProjectBrief:
    """Read one bounded line-framed JSON project brief from an agent stdin channel."""

    return project_from_mapping(
        load_json_line_stdin(
            stream,
            option="--project-json-line",
            subject="project brief",
            on_ready=on_ready,
        )
    )
