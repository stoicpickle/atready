"""Project brief loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from atready.diagnostics import PROJECT_LOCATION_FIELDS, validation_configuration_error
from atready.errors import ConfigurationError
from atready.models import ProjectBrief
from atready.yamlio import load_yaml, loads_yaml


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
