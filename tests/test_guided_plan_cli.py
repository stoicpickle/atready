from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path

import pytest

import atready.cli as cli
from atready.cli import main
from atready.models import ProjectBrief
from atready.templates import demo_inventory
from atready.yamlio import dumps_yaml


class _TTYInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def _demo_path(tmp_path: Path) -> Path:
    path = tmp_path / "inventory.yaml"
    path.write_text(demo_inventory(), encoding="utf-8")
    return path


def _successful_answers(*, approval: str = "") -> str:
    return (
        "\n".join(
            [
                "Ship a small feature",
                "1",
                "Implement and test it",
                "2",  # code-implementation from the sorted declared capability list
                "",  # basic minimum strength
                "",  # empty expected result is rejected
                "A working change with focused tests",
                "",  # empty check is rejected
                "The focused tests pass",
                "",  # standard eligibility
                approval,  # approve, edit, or accept the default
            ]
        )
        + "\n"
    )


def test_guided_plan_can_revise_the_recap_before_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = _demo_path(tmp_path)
    original = inventory.read_bytes()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(
        sys,
        "stdin",
        _TTYInput(_successful_answers(approval="edit") + _successful_answers()),
    )

    assert (
        main(
            [
                "plan",
                "--mode",
                "detailed",
                "--inventory",
                str(inventory),
                "--allow-demo",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert output.count("REVIEW WHAT ATREADY UNDERSTOOD") == 2
    assert "The previous recap was not routed" in output
    assert output.count("Resource fit: Guided AtReady plan") == 1
    assert inventory.read_bytes() == original


def test_guided_plan_refuses_non_terminal_input_before_reading(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing.yaml"

    assert main(["plan", "--inventory", str(missing)]) == 2

    captured = capsys.readouterr()
    assert "interactive and requires a terminal" in captured.err
    assert "atready route --help" in captured.err
    assert not missing.exists()


def test_guided_plan_quick_fit_is_the_default_and_routes_after_three_replies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = _demo_path(tmp_path)
    original = inventory.read_bytes()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(
        sys,
        "stdin",
        _TTYInput("Implement and test a small feature\n2\n\n"),
    )

    assert main(["plan", "--inventory", str(inventory), "--allow-demo"]) == 0

    output = capsys.readouterr().out
    before_result = output[: output.index("Resource fit:")]
    assert "QUICK FIT REVIEW" in before_result
    assert "Work: Implement and test a small feature" in before_result
    assert "Needs: code-implementation (basic or better)" in before_result
    assert (
        "public data; internet allowed; any workflow or cost; verified facts only" in before_result
    )
    assert "For private data or other limits" in before_result
    assert "Check this resource fit? [Y/n/edit]:" in before_result
    assert "How many steps" not in output
    assert "Expected result" not in output
    assert "Eligibility controls" not in output
    assert len(before_result.split()) <= 180
    assert "Resource fit: Quick Fit" in output
    assert inventory.read_bytes() == original


def test_guided_quick_recap_bounds_display_without_changing_project(capsys) -> None:
    work = "x" * cli._MAX_GUIDED_INPUT_CHARACTERS
    capability_ids = [f"capability-{index}" for index in range(5)]
    project = ProjectBrief.model_validate(
        {
            "schema_version": 1,
            "id": "bounded-display",
            "name": "Bounded display",
            "goal": work,
            "as_of": date.today(),
            "constraints": {},
            "workstreams": [
                {
                    "id": "work",
                    "name": "Work",
                    "objective": work,
                    "required_capabilities": [
                        {"id": capability, "importance": 1.0, "minimum": 0.40}
                        for capability in capability_ids
                    ],
                    "inputs": ["User description"],
                    "allowed_scope": ["Requested work"],
                    "exclusions": ["Other work"],
                    "deliverable": "Requested result",
                    "acceptance_criteria": ["User accepts the result"],
                    "verification": ["User review"],
                    "stop_conditions": ["Stop before resource use"],
                    "next_owner": "User",
                }
            ],
        }
    )

    cli._print_guided_quick_recap(project)

    output = capsys.readouterr().out
    work_line = next(line for line in output.splitlines() if line.startswith("Work: "))
    assert len(work_line.removeprefix("Work: ")) == 80
    assert "capability-0, capability-1, capability-2 (+2 more)" in output
    assert project.goal == work
    assert project.workstreams[0].objective == work
    assert [item.id for item in project.workstreams[0].required_capabilities] == capability_ids


def test_guided_plan_quick_fit_can_edit_before_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = _demo_path(tmp_path)
    original = inventory.read_bytes()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(
        sys,
        "stdin",
        _TTYInput("Draft a feature\n2\nedit\nImplement and test the feature\n2\n\n"),
    )

    assert main(["plan", "--inventory", str(inventory), "--allow-demo"]) == 0

    output = capsys.readouterr().out
    assert output.count("QUICK FIT REVIEW") == 2
    assert "The previous recap was not routed" in output
    assert output.count("Resource fit: Quick Fit") == 1
    assert inventory.read_bytes() == original


def test_guided_plan_missing_inventory_points_to_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)

    assert main(["plan", "--inventory", str(missing)]) == 2

    captured = capsys.readouterr()
    assert "configuration file does not exist" in captured.err
    assert "atready init" in captured.err
    assert not missing.exists()


def test_guided_plan_can_cancel_without_writing_or_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = _demo_path(tmp_path)
    original = inventory.read_bytes()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(sys, "stdin", _TTYInput("cancel\n"))

    assert (
        main(
            [
                "plan",
                "--mode",
                "detailed",
                "--inventory",
                str(inventory),
                "--allow-demo",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "Cancelled. No files changed and no resources were run." in output
    assert inventory.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["inventory.yaml"]


def test_guided_plan_reprompts_after_terminal_controls_without_echoing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = _demo_path(tmp_path)
    original = inventory.read_bytes()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(sys, "stdin", _TTYInput("unsafe\x1b[31m goal\n" + _successful_answers()))

    assert (
        main(
            [
                "plan",
                "--mode",
                "detailed",
                "--inventory",
                str(inventory),
                "--allow-demo",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "Remove control or zero-width characters, or type cancel." in captured.out
    assert "Resource fit: Guided AtReady plan" in captured.out
    assert "\x1b" not in captured.out + captured.err
    assert "unsafe\\x1b" not in captured.out + captured.err
    assert inventory.read_bytes() == original


def test_guided_plan_bounds_expected_result_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = _demo_path(tmp_path)
    original = inventory.read_bytes()
    answers = (
        "\n".join(
            [
                "Ship a small feature",
                "1",
                "Implement it",
                "2",
                "basic",
                "x" * (cli._MAX_GUIDED_INPUT_CHARACTERS + 1),
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(sys, "stdin", _TTYInput(answers))

    assert (
        main(
            [
                "plan",
                "--mode",
                "detailed",
                "--inventory",
                str(inventory),
                "--allow-demo",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert "guided answer is too long" in captured.err
    assert "x" * 20 not in captured.out + captured.err
    assert inventory.read_bytes() == original


def test_guided_plan_routes_in_memory_and_matches_canonical_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = _demo_path(tmp_path)
    original = inventory.read_bytes()
    captured_project = None
    real_route = cli.route

    def capture_route(inventory_value, project_value, *, allow_demo=False):
        nonlocal captured_project
        captured_project = project_value
        return real_route(inventory_value, project_value, allow_demo=allow_demo)

    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(cli, "route", capture_route)
    monkeypatch.setattr(sys, "stdin", _TTYInput(_successful_answers()))

    assert (
        main(
            [
                "plan",
                "--mode",
                "detailed",
                "--inventory",
                str(inventory),
                "--allow-demo",
            ]
        )
        == 0
    )
    guided_output = capsys.readouterr().out
    assert captured_project is not None
    assert guided_output.startswith("CHECK RESOURCE FIT\nInventory:")
    assert "Check resource fit for these steps? [Y/n/edit]:" in guided_output
    assert "PLAN A PROJECT" not in guided_output
    assert "Make this resource plan?" not in guided_output
    assert "No project file will be written." in guided_output
    assert "No routed project resources were contacted or run." in guided_output
    workstream = captured_project.workstreams[0]
    assert workstream.required_capabilities[0].minimum == 0.40
    assert workstream.deliverable == "A working change with focused tests"
    assert workstream.acceptance_criteria == ["A working change with focused tests"]
    assert workstream.verification == ["The focused tests pass"]
    assert "code-implementation (minimum basic: 0.40)" in guided_output
    assert "Strength scale: basic 0.40, solid 0.65, strong 0.80, exceptional 0.95" in guided_output
    assert "Enter the result this step should produce" in guided_output
    assert "Enter one way to check the result" in guided_output
    assert "Expected result: A working change with focused tests" in guided_output
    assert "Check: The focused tests pass" in guided_output
    assert "Deliver: A working change with focused tests" in guided_output
    assert inventory.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["inventory.yaml"]

    project_path = tmp_path / "project.yaml"
    project_path.write_text(
        dumps_yaml(captured_project.model_dump(mode="json")),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert (
        main(
            [
                "route",
                "--project",
                str(project_path),
                "--inventory",
                str(inventory),
                "--allow-demo",
            ]
        )
        == 0
    )
    route_output = capsys.readouterr().out
    assert guided_output[guided_output.index("Resource fit:") :] == route_output


def test_guided_plan_surfaces_a_gap_from_custom_eligibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = _demo_path(tmp_path)
    answers = (
        "\n".join(
            [
                "Create private concept art",
                "1",
                "Explore a visual direction",
                "3",  # concept-art
                "",  # basic minimum strength
                "Three private concept directions",
                "Review all three against the style brief",
                "no",  # customize eligibility
                "private",
                "",  # internet allowed
                "",  # verified only
                "",  # any cost
                "",  # all workflows
                "",  # exclude none
                "",  # make the plan
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(sys, "stdin", _TTYInput(answers))

    assert (
        main(
            [
                "plan",
                "--mode",
                "detailed",
                "--inventory",
                str(inventory),
                "--allow-demo",
            ]
        )
        == 3
    )

    output = capsys.readouterr().out
    assert "Gaps and decisions" in output
    assert "Use: Unassigned" in output
    assert "No routed project resources were contacted or run." in output


def test_help_is_progressive_and_complete_help_remains_available(capsys) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
    beginner = capsys.readouterr().out
    assert "Get started:" in beginner
    assert "plan      Check resource fit" in beginner
    assert "Advanced command names:" in beginner
    assert "doctor  runtime  config  resource  state  skill  schema" in beginner
    assert "demo      Run a complete synthetic resource fit example" in beginner
    get_started = beginner.split("Get started:", 1)[1].split("Manage:", 1)[0]
    assert get_started.index("demo") < get_started.index("init")
    assert get_started.index("init") < get_started.index("add")
    assert get_started.index("add") < get_started.index("plan")

    headings = {"Get started:", "Manage:", "More:", "Advanced command names:"}
    displayed_commands: set[str] = set()
    active_heading = None
    for line in beginner.splitlines():
        if line in headings:
            active_heading = line
            continue
        if active_heading and line.startswith("  ") and line.strip():
            if active_heading == "Advanced command names:":
                displayed_commands.update(line.split())
            else:
                displayed_commands.add(line.split()[0])
        elif line and not line.startswith(" "):
            active_heading = None
    assert displayed_commands == set(cli._command_parsers(cli.build_parser()))

    assert main(["help", "--all"]) == 0
    complete = capsys.readouterr().out
    assert "doctor" in complete
    assert "schema" in complete
    assert "resource" in complete

    assert main(["help", "planning"]) == 0
    planning = capsys.readouterr().out
    assert "atready plan" in planning
    assert "atready route --project project.yaml" in planning

    assert main(["help", "route"]) == 0
    assert "--project" in capsys.readouterr().out


def test_skill_status_is_read_only_and_reports_personal_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    personal = tmp_path / ".agents" / "skills" / "project-atready"
    for relative in cli._REQUIRED_SKILL_FILES:
        target = personal / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic skill file\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(workspace)

    assert main(["skill", "status"]) == 0

    output = capsys.readouterr().out
    assert f"Personal location: {personal} (ready)" in output
    assert "Standalone skill copy ready: yes" in output
    assert "Plugin-managed Codex installations are not checked" in output
    assert "No files changed." in output
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert after == before


def test_skill_status_rejects_an_incomplete_discovery_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    personal = tmp_path / ".agents" / "skills" / "project-atready"
    personal.mkdir(parents=True)
    (personal / "SKILL.md").write_text("synthetic skill\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(workspace)

    assert main(["skill", "status"]) == 0

    output = capsys.readouterr().out
    assert f"Personal location: {personal} (incomplete)" in output
    assert "Standalone skill copy ready: no" in output
    assert "Plugin-managed Codex installations are not checked" in output
    assert "follow the guarded copy command in the AtReady README" in output
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert after == before


def test_skill_status_handles_an_unresolvable_home_directory(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def fail_home() -> Path:
        raise RuntimeError("synthetic home failure")

    monkeypatch.setattr(Path, "home", fail_home)

    assert main(["skill", "status"]) == 2

    captured = capsys.readouterr()
    assert "cannot resolve the personal Codex skill location" in captured.err
    assert "synthetic home failure" not in captured.out + captured.err
