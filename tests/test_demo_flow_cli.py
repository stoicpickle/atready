from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

import atready.cli as cli
from atready.catalog import InventoryCatalog
from atready.cli import _NO_EXECUTION_BOUNDARY, main
from atready.project import project_from_text
from atready.render import render_summary
from atready.routing import route
from atready.templates import demo_inventory, starter_project


def test_bare_demo_attempts_no_network_or_private_file_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("bare demo attempted an external side effect")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ATREADY_HOME", str(tmp_path / "private-home"))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(cli, "create_private_file", forbidden)
    before = list(tmp_path.iterdir())

    assert main(["demo"]) == 0

    output = capsys.readouterr().out
    assert "Resource fit: Synthetic CLI Release" in output
    assert output.endswith(_NO_EXECUTION_BOUNDARY + "\n")
    assert list(tmp_path.iterdir()) == before


def test_bare_demo_routes_synthetic_fixtures_in_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ATREADY_HOME", str(tmp_path / "private-home"))
    before = list(tmp_path.iterdir())

    assert main(["demo"]) == 0

    output = capsys.readouterr().out
    project = project_from_text(starter_project())
    inventory = InventoryCatalog.from_text(demo_inventory(), today=project.as_of).inventory
    plan = route(inventory, project, allow_demo=True)
    canonical = render_summary(plan, goal=project.goal, width=80, include_next_action=False)
    boundary = _NO_EXECUTION_BOUNDARY + "\n"
    canonical_without_boundary = canonical.removesuffix(boundary)

    assert output.startswith(canonical_without_boundary)
    assert "Resource fit: Synthetic CLI Release" in output
    assert "Use: Synthetic Local Coding Agent" in output
    assert "--format markdown" not in output
    cta = (
        "Ready to try your own roster?\n"
        "1. atready init\n"
        "2. atready add\n"
        "3. atready plan\n"
        f"{_NO_EXECUTION_BOUNDARY}\n"
    )
    assert cta in output
    assert output.index("Ready to try your own roster?") < output.index("1. atready init")
    assert output.index("1. atready init") < output.index("2. atready add")
    assert output.index("2. atready add") < output.index("3. atready plan")
    assert output.index("3. atready plan") < output.index(_NO_EXECUTION_BOUNDARY)
    assert output.endswith(boundary)
    assert output.count(_NO_EXECUTION_BOUNDARY) == 1
    assert list(tmp_path.iterdir()) == before


def test_demo_inventory_subcommand_remains_machine_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("ATREADY_HOME", str(tmp_path / "private-home"))
    before = list(tmp_path.iterdir())

    assert main(["demo", "inventory", "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["inventory_kind"] == "demo"
    assert len(payload["resources"]) == 3
    assert list(tmp_path.iterdir()) == before

    assert main(["demo", "inventory"]) == 0
    assert capsys.readouterr().out == demo_inventory()
    assert list(tmp_path.iterdir()) == before


def test_welcome_and_progressive_help_point_to_bare_demo(capsys) -> None:
    assert main(["welcome", "--color", "never"]) == 0
    welcome = capsys.readouterr().out
    assert "Try the safe demo   atready demo" in welcome
    assert "atready demo inventory >" not in welcome

    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert "demo      Run a complete synthetic resource fit example" in help_text

    assert main(["help", "planning"]) == 0
    assert "See the complete flow: atready demo" in capsys.readouterr().out
