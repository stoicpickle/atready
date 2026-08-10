from __future__ import annotations

import os
from pathlib import Path

import pytest

import atready.yamlio as yamlio
from atready.errors import ConfigurationError
from atready.project import project_from_path, project_from_text
from atready.templates import starter_project


def test_project_root_must_be_mapping() -> None:
    with pytest.raises(ConfigurationError, match="project root must be a mapping"):
        project_from_text("- not\n- a\n- project\n")


def test_project_validation_has_actionable_locations() -> None:
    with pytest.raises(ConfigurationError, match="project validation failed") as error:
        project_from_text("schema_version: 1\nid: demo\n")
    assert "name: Field required" in str(error.value)
    assert "workstreams: Field required" in str(error.value)


def test_project_validation_redacts_unknown_fields_and_drops_input_exception() -> None:
    sentinel = "confidential-project-sentinel"
    invalid = starter_project().replace("goal:", f"{sentinel}: hidden\ngoal:", 1)

    with pytest.raises(ConfigurationError) as caught:
        project_from_text(invalid)

    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("version", ["true", "1.0", "'1'"])
def test_project_schema_version_requires_exact_native_integer(version: str) -> None:
    invalid = starter_project().replace("schema_version: 1", f"schema_version: {version}")

    with pytest.raises(ConfigurationError, match="native YAML/JSON integer"):
        project_from_text(invalid)


def test_project_custom_validator_does_not_echo_unknown_capability_gap() -> None:
    sentinel = "confidential-project-capability"
    invalid = starter_project().replace(
        "allowed: false\n      capability_gaps: []",
        f"allowed: true\n      capability_gaps: [{sentinel}]",
    )

    with pytest.raises(ConfigurationError) as caught:
        project_from_text(invalid)

    assert sentinel not in str(caught.value)
    assert "support capability_gaps must be required capabilities" in str(caught.value)


@pytest.mark.skipif(
    not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"),
    reason="FIFO substitution regression requires POSIX nonblocking descriptors",
)
def test_project_fifo_substitution_cannot_block_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project.yaml"
    project.write_text(starter_project(), encoding="utf-8")
    real_open = yamlio.os.open

    def substitute_fifo(path: Path, flags: int) -> int:
        assert flags & os.O_NONBLOCK
        project.unlink()
        os.mkfifo(project, mode=0o600)
        return real_open(path, flags)

    monkeypatch.setattr(yamlio.os, "open", substitute_fifo)

    with pytest.raises(ConfigurationError, match="not a regular file"):
        project_from_path(project)
