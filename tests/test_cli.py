from __future__ import annotations

import argparse
import io
import json
import os
import stat
import sys
from datetime import date
from itertools import pairwise
from pathlib import Path

import pytest

import atready.cli as cli
import atready.inventory_edit as inventory_edit
from atready.catalog import InventoryCatalog
from atready.cli import _WORDMARK, _capacity_number, _date_value, _welcome_text, main
from atready.errors import ConfigurationError, StorageError
from atready.models import DataClass
from atready.templates import demo_inventory, starter_inventory, starter_project


def test_bare_cli_is_a_plain_language_welcome(capsys) -> None:
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "Plan with what you have at the ready." in captured.out
    assert "Turn a rough plan and your available tools" in captured.out
    assert "Create your roster  atready init" in captured.out
    assert "Add a resource      atready add" in captured.out
    assert "Try the safe demo   atready demo" in captured.out
    assert "never runs a tool, spends a credit, or starts the work" in captured.out
    assert " - " not in captured.out
    assert "\033[" not in captured.out
    assert captured.err == ""


def test_presentation_line_limit_uses_widest_default_before_reporting_conflict(capsys) -> None:
    fixtures = Path(__file__).parents[1] / "evals" / "fixtures"

    assert (
        main(
            [
                "route",
                "--project",
                str(fixtures / "project-godot.yaml"),
                "--inventory",
                str(fixtures / "inventory.yaml"),
                "--allow-demo",
                "--format",
                "presentation",
                "--max-lines",
                "8",
            ]
        )
        == 0
    )
    presentation = json.loads(capsys.readouterr().out)

    assert presentation["presentation_status"] == "ready"
    assert presentation["limits"]["requested"] == {"lines": 8, "words": None}
    assert presentation["limits"]["required"]["lines"] == 8


def test_welcome_supports_explicit_plain_and_gradient_output(capsys) -> None:
    assert main(["welcome", "--color", "never"]) == 0
    plain = capsys.readouterr().out
    assert "\033[" not in plain

    assert main(["welcome", "--color", "always"]) == 0
    colored = capsys.readouterr().out
    assert "\033[38;2;24;76;174m" in colored
    assert "\033[0m" in colored
    assert "Plan with what you have at the ready." in colored


def test_welcome_keeps_the_toolbox_rows_on_one_fixed_axis() -> None:
    banner = _welcome_text(color=False, block_art=True).splitlines()[:6]
    toolbox_axis = max(len(line) for line in _WORDMARK) + 2

    assert banner[0].index("▉", toolbox_axis) == toolbox_axis + 6
    assert banner[1].index("▉", toolbox_axis) == toolbox_axis + 5
    assert banner[2].index("▉", toolbox_axis) == toolbox_axis + 2
    assert banner[3].index("TOOL KIT") == toolbox_axis + 6
    assert banner[4].index("▉", toolbox_axis) == toolbox_axis + 2


class _TTYInput(io.StringIO):
    def isatty(self) -> bool:
        return True


class _EncodinglessOutput:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, value: str) -> int:
        self.parts.append(value)
        return len(value)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True


def test_welcome_uses_ascii_art_when_stdout_has_no_encoding(monkeypatch) -> None:
    output = _EncodinglessOutput()
    monkeypatch.setattr(sys, "stdout", output)

    assert main(["welcome", "--color", "auto"]) == 0

    rendered = "".join(output.parts)
    assert "Plan with what you have at the ready." in rendered
    assert "▉" not in rendered
    assert "#" in rendered


def _guided_codex_answers(*, save: bool, cost: str = "low") -> str:
    answers = [
        "",  # use the displayed inventory
        "",  # proposed name
        "",  # proposed stable ID
        "",  # proposed categories
        "",  # proposed capabilities
        "strong",
        "strong",
        "strong",
        "terminal",
        "yes",
        "yes",
        "some",
        "judgment",
        "today",
        "internal",
        "yes",
        "subscription",
        cost,
        "",  # Quick Add defaults
        "yes",  # preview authorization
        "save codex" if save else "cancel",
    ]
    return "\n".join(answers) + "\n"


def test_guided_add_refuses_non_terminal_input_before_reading(tmp_path: Path, capsys) -> None:
    target = tmp_path / "inventory.yaml"

    assert main(["add", "--path", str(target), "--profile", "codex"]) == 2

    captured = capsys.readouterr()
    assert "interactive and requires a terminal" in captured.err
    assert "atready inventory add --help" in captured.err
    assert not target.exists()


def test_guided_add_missing_inventory_points_to_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "inventory.yaml"
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)

    assert main(["add", "--path", str(target), "--profile", "codex"]) == 2

    captured = capsys.readouterr()
    assert "personal inventory does not exist" in captured.err
    assert f"atready init --path {target}" in captured.err
    assert not target.exists()


def test_guided_add_missing_inventory_escapes_terminal_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "missing\x1binventory\nline\tfile.yaml"
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)

    assert main(["add", "--path", str(target), "--profile", "codex"]) == 2

    error = capsys.readouterr().err
    assert "\x1b" not in error
    assert "\t" not in error
    assert 1 <= error.count("\n") <= 2
    assert error.startswith("error: ")
    assert "\\x1b" in error
    assert "\\n" in error
    assert "\\t" in error


def test_guided_add_preview_can_be_cancelled_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(target)]) == 0
    capsys.readouterr()
    original = target.read_bytes()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(sys, "stdin", _TTYInput(_guided_codex_answers(save=False)))

    assert main(["add", "--path", str(target), "--profile", "codex"]) == 0

    output = capsys.readouterr().out
    assert "REVIEW WHAT ATREADY UNDERSTOOD" in output
    assert "COMPLETE NO-WRITE PREVIEW" in output
    assert "Comparison ratings:" in output
    assert '"context_switch_cost":' not in output
    assert "Type 'save codex'" in output
    assert "Cancelled. No files changed." in output
    assert target.read_bytes() == original
    assert not (tmp_path / ".quartermaster-backups").exists()


def test_guided_add_saves_the_exact_preview_after_separate_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(target)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(sys, "stdin", _TTYInput(_guided_codex_answers(save=True)))

    assert main(["add", "--path", str(target), "--profile", "codex"]) == 0

    output = capsys.readouterr().out
    assert "Added resource 'codex'" in output
    assert "Replacement verified: true" in output
    saved = inventory_edit.read_inventory_file(target).inventory.resources
    assert len(saved) == 1
    assert saved[0].id == "codex"
    assert saved[0].capabilities == {
        "code-implementation": 0.8,
        "code-review": 0.8,
        "repository-analysis": 0.8,
    }
    assert saved[0].access.interaction.value == "local-cli"
    assert saved[0].access.status.value == "active"
    assert saved[0].access.current_session.value == "available"
    assert saved[0].economics.billing.value == "subscription"
    assert saved[0].economics.marginal_cost == 0.25
    assert saved[0].economics.quota.value == "limited"
    assert [item.value for item in saved[0].policy.allowed_data_classes] == [
        "public",
        "internal",
    ]
    assert saved[0].policy.approval_required is True
    assert saved[0].policy.requires_network is True
    assert (tmp_path / ".quartermaster-backups").is_dir()


def test_guided_add_interruption_after_save_reports_uncertain_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(target)]) == 0
    capsys.readouterr()
    real_commit = cli._commit_inventory_add

    def commit_then_interrupt(*args, **kwargs) -> int:
        assert real_commit(*args, **kwargs) == 0
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(cli, "_commit_inventory_add", commit_then_interrupt)
    monkeypatch.setattr(sys, "stdin", _TTYInput(_guided_codex_answers(save=True)))

    assert main(["add", "--path", str(target), "--profile", "codex"]) == 130

    captured = capsys.readouterr()
    assert "state may be uncertain" in captured.err
    assert "Inspect the inventory and backups before retrying" in captured.err
    assert "No files changed" not in captured.err
    assert inventory_edit.read_inventory_file(target).inventory.resources[0].id == "codex"


def test_guided_add_custom_resource_preserves_declared_unknowns_and_can_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(target)]) == 0
    capsys.readouterr()
    original = target.read_bytes()
    answers = [
        "",  # use inventory
        str(len(cli.resource_profiles()) + 1),
        "Build Farm",
        "",  # derived build-farm ID
        "Bad Category",
        "build",
        "Build Farm",
        "",  # derived build-farm ID after local validation retry
        "compute",
        "build, testing",
        "0.7",
        "exceptional",
        "separate",
        "no",
        "no",
        "none",
        "not sure",
        "sensitive",
        "no",
        "owned",
        "high",
        "",  # Quick Add defaults
        "yes",  # preview
        "cancel",
    ]
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(sys, "stdin", _TTYInput("\n".join(answers) + "\n"))

    assert main(["add", "--path", str(target)]) == 0

    output = capsys.readouterr().out
    assert "Something else" in output
    assert "Please correct those identity fields" in output
    assert "Build Farm (build-farm)" in output
    assert "build 0.70" in output
    assert "testing 0.95" in output
    assert "Selection facts: declared-unavailable" in output
    assert "Cancelled. No files changed." in output
    assert target.read_bytes() == original


def test_guided_recap_explains_unverified_selection_consequence(tmp_path: Path, capsys) -> None:
    parsed = cli.parse_resource_mapping(
        {
            "id": "uncertain-tool",
            "name": "Uncertain Tool",
            "categories": ["tool"],
            "capabilities": {"research": 0.5},
        }
    )

    cli._print_guided_recap(parsed, tmp_path / "inventory.yaml")

    output = capsys.readouterr().out
    assert "Selection facts: requires-verification" in output
    assert "will not normally select this resource" in output
    assert "separately allow unverified resources" in output


def test_guided_output_escapes_declared_controls_and_uses_explicit_data_ladder(
    tmp_path: Path, capsys
) -> None:
    target = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(target)]) == 0
    capsys.readouterr()
    parsed = cli.parse_resource_mapping(
        {
            "id": "unsafe-tool",
            "name": "Unsafe Tool",
            "categories": ["tool"],
            "capabilities": {"research": 0.5},
            "policy": {"allowed_data_classes": ["sensitive", "public"]},
        }
    )

    cli._print_guided_recap(parsed, Path("inventory\npath.yaml"))
    plan = cli.plan_add_resource(
        target,
        parsed.resource,
        defaulted_fields=parsed.defaulted_fields,
    )
    preview = plan.preview()
    preview["resource"]["name"] = "Unsafe\x1b[31m\rName"
    preview["resource"]["best_for"] = ["line\nbreak"]
    preview["resource"]["avoid_for"] = ["tab\tvalue"]
    cli._print_guided_inventory_add_preview(preview)

    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "\r" not in output
    assert "\t" not in output
    assert "Unsafe\\x1b[31m\\rName" in output
    assert "line\\nbreak" in output
    assert "tab\\tvalue" in output
    assert "Inventory: inventory\\npath.yaml" in output
    assert "Safety: data up to sensitive" in output
    assert cli._DATA_SENSITIVITY_LADDER == (
        DataClass.PUBLIC,
        DataClass.INTERNAL,
        DataClass.PRIVATE,
        DataClass.SENSITIVE,
    )


def test_guided_prompt_helpers_reprompt_and_bound_input(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", _TTYInput("maybe\nyes\nwrong\napp\n\na, a, b\nbad\n0.75\n"))

    assert cli._guided_yes_no("Continue?") is True
    assert cli._guided_choice("Mode", {"app": "manual"}) == "manual"
    assert cli._guided_csv("IDs") == ("a", "b")
    assert cli._guided_strength("testing") == 0.75
    assert "Please answer yes or no." in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "stdin",
        _TTYInput("x" * (cli._MAX_GUIDED_INPUT_CHARACTERS + 1) + "\n"),
    )
    with pytest.raises(ConfigurationError, match="guided answer is too long"):
        cli._guided_read("Bounded")

    assert cli._guided_slug_proposal("  My New Tool!  ") == "my-new-tool"


def test_guided_add_eof_before_preview_is_a_no_write_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(target)]) == 0
    capsys.readouterr()
    original = target.read_bytes()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(sys, "stdin", _TTYInput(""))

    assert main(["add", "--path", str(target), "--profile", "codex"]) == 2

    assert "guided input ended before saving" in capsys.readouterr().err
    assert target.read_bytes() == original


def test_guided_add_unknown_cost_remains_a_defaulted_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    target = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(target)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(cli, "_guided_terminal_available", lambda: True)
    monkeypatch.setattr(
        sys,
        "stdin",
        _TTYInput(_guided_codex_answers(save=False, cost="not sure")),
    )

    assert main(["add", "--path", str(target), "--profile", "codex"]) == 0

    output = capsys.readouterr().out
    assert "relative cost 0.50 (baseline default)" in output
    assert "comparison ratings, relative cost, and handoff shown above" in output


def test_help_describes_the_beginner_facing_job(capsys) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "Plan a project around the tools and resources you already have." in output
    assert "Add one resource with guided, preview-first setup" in output
    assert "welcome" in output


def _resource_add_args(
    inventory: Path | None = None,
    *,
    resource_id: str = "local-coding-agent",
) -> list[str]:
    args = [
        "inventory",
        "add",
        "--id",
        resource_id,
        "--name",
        "Personal Local Coding Agent",
        "--category",
        "coding-agent",
        "--capability",
        "code-implementation=0.90",
        "--capability",
        "test-automation=0.85",
        "--access",
        "active",
        "--interaction",
        "local-cli",
        "--session",
        "available",
        "--billing",
        "owned",
        "--marginal-cost",
        "0.05",
        "--quota",
        "ample",
        "--allowed-data-class",
        "internal",
        "--confidence-basis",
        "observed",
        "--verified-on",
        date.today().isoformat(),
        "--handoff-method",
        "manual-prompt",
    ]
    if inventory is not None:
        args[2:2] = ["--path", str(inventory)]
    return args


_PRIVATE_SENTINEL = "SYNTHETIC-PRIVATE-SENTINEL"


def _resource_declaration(*, note: str | None = _PRIVATE_SENTINEL) -> bytes:
    private_note = f"  private_notes: {note}\n" if note is not None else ""
    return (
        "schema_version: 1\n"
        "resource:\n"
        "  id: structured-tool\n"
        "  name: Structured Tool\n"
        "  categories: [coding-agent]\n"
        "  capabilities:\n"
        "    code-implementation: 0.9\n" + private_note
    ).encode()


class _BinaryInput:
    def __init__(self, raw: bytes) -> None:
        self.buffer = io.BytesIO(raw)


class _UnreadableInput:
    class _Buffer:
        def read(self, _size: int) -> bytes:
            raise AssertionError("stdin must not be read")

    buffer = _Buffer()


def _preview_and_apply(args: list[str], capsys) -> tuple[dict, dict]:
    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["applied"] is False
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["applied"] is True
    return preview, receipt


def test_backup_manifest_cli_reports_order_without_claiming_trusted_time(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    _preview_and_apply(_resource_add_args(inventory), capsys)

    assert (
        main(
            [
                "inventory",
                "backup",
                "manifest",
                "--path",
                str(inventory),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["initialized"] is True
    assert result["authoritative_order"] == "sequence"
    assert result["tamper_evidence"] == "local-hash-chain-not-a-signature"
    assert [event["phase"] for event in result["events"]] == [
        "completed",
        "prepared",
        "completed",
    ]
    sequences = [event["sequence"] for event in result["events"]]
    assert sequences == list(range(len(sequences)))
    assert len(sequences) == len(set(sequences))
    assert all(left < right for left, right in pairwise(sequences))
    assert all(event["recorded_at_is_history"] is False for event in result["events"])


@pytest.mark.parametrize("value", ["20260806", "2026-W32-4"])
def test_cli_date_requires_canonical_calendar_form(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="YYYY-MM-DD"):
        _date_value(value)


@pytest.mark.parametrize("value", ["NaN", "-1", "1e19", "9" * 10_000])
def test_cli_capacity_rejects_nonfinite_negative_or_out_of_range_numbers(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="non-negative JSON number") as error:
        _capacity_number(value)
    assert value not in str(error.value)


def test_cli_capacity_sanitizes_parser_recursion_error(monkeypatch) -> None:
    def recurse(_value: str) -> object:
        raise RecursionError

    monkeypatch.setattr("atready.cli.json.loads", recurse)
    with pytest.raises(argparse.ArgumentTypeError, match="non-negative JSON number"):
        _capacity_number("1")


def test_init_validate_and_snapshot_round_trip(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ATREADY_HOME", str(tmp_path / "private-home"))

    assert main(["init", "--json"]) == 0
    init_output = capsys.readouterr().out
    initialized = json.loads(init_output)
    created = initialized["created"]
    inventory = Path(created)
    nonce = InventoryCatalog.from_path(inventory).inventory.revision_privacy_nonce
    assert nonce is not None
    assert initialized["revision_protection"] == "nonce-v1-present"
    assert nonce not in init_output
    assert inventory.exists()
    if os.name == "posix":
        assert stat.S_IMODE(inventory.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(inventory.stat().st_mode) == 0o600

    assert main(["inventory", "validate", "--json"]) == 0
    validation_output = capsys.readouterr().out
    validation = json.loads(validation_output)
    assert validation["valid"] is True
    assert validation["inventory_kind"] == "personal"
    assert validation["revision_protection"] == "nonce-v1-present"
    assert validation["resources"] == 0
    assert nonce not in validation_output

    assert main(["inventory", "snapshot"]) == 0
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["inventory_fingerprint"].startswith("sha256:")
    assert snapshot["inventory_kind"] == "personal"
    assert snapshot["resources"] == []
    assert "revision_privacy_nonce" not in snapshot
    assert nonce not in str(snapshot)


def test_inventory_annotation_set_and_clear_round_trip_without_exposure(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    declaration = tmp_path / "annotation.yaml"
    sentinel = "SYNTHETIC-ROOT-ANNOTATION-CLI"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    declaration.write_text(f"schema_version: 1\nprivate_notes: {sentinel}\n", encoding="utf-8")
    if os.name == "posix":
        declaration.chmod(0o600)

    args = [
        "inventory",
        "annotate",
        "set",
        "--path",
        str(inventory),
        "--annotation-file",
        str(declaration),
    ]
    assert main([*args, "--json"]) == 0
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err
    preview = json.loads(captured.out)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err
    receipt = json.loads(captured.out)
    assert preview["private_notes_effect"] == "will-add"
    assert receipt["private_notes_effect"] == "will-add"
    assert receipt["operation"] == "annotate-inventory"
    assert sentinel not in json.dumps(preview)
    assert sentinel not in json.dumps(receipt)
    assert InventoryCatalog.from_path(inventory).inventory.private_notes == sentinel

    clear_preview, clear_receipt = _preview_and_apply(
        ["inventory", "annotate", "clear", "--path", str(inventory)], capsys
    )
    assert clear_preview["private_notes_effect"] == "will-remove"
    assert clear_receipt["private_notes_effect"] == "will-remove"
    assert InventoryCatalog.from_path(inventory).inventory.private_notes is None


def test_inventory_annotation_schema_is_exposed(capsys) -> None:
    assert main(["schema", "inventory-annotation-declaration"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["private_notes"]["maxLength"] == 20_000


def test_inventory_annotation_stdin_preview_is_value_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    sentinel = "SYNTHETIC-ROOT-ANNOTATION-STDIN"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(
        sys,
        "stdin",
        _BinaryInput(f"schema_version: 1\nprivate_notes: {sentinel}\n".encode()),
    )

    assert (
        main(
            [
                "inventory",
                "annotate",
                "set",
                "--path",
                str(inventory),
                "--annotation-stdin",
                "--json",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert json.loads(output)["private_notes_effect"] == "will-add"
    assert sentinel not in output


def test_init_entropy_failure_leaves_target_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "private" / "inventory.yaml"

    def fail_entropy(_byte_count: int) -> str:
        raise OSError("synthetic entropy failure")

    monkeypatch.setattr("atready.templates.secrets.token_hex", fail_entropy)

    assert main(["init", "--path", str(inventory)]) == 2
    captured = capsys.readouterr()
    assert "cannot generate inventory revision privacy nonce" in captured.err
    assert not inventory.exists()
    assert not inventory.parent.exists()


@pytest.mark.parametrize("command", ["validate", "snapshot", "route"])
def test_core_inventory_reads_use_acl_aware_descriptor_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    command: str,
) -> None:
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(starter_inventory(), encoding="utf-8")
    if os.name == "posix":
        inventory.chmod(0o600)
    project = tmp_path / "project.yaml"
    project.write_text(starter_project(), encoding="utf-8")
    monkeypatch.setattr(inventory_edit, "darwin_fd_has_extended_acl", lambda _fd: True)
    argv = {
        "validate": ["inventory", "validate", str(inventory)],
        "snapshot": ["inventory", "snapshot", str(inventory)],
        "route": [
            "route",
            "--project",
            str(project),
            "--inventory",
            str(inventory),
        ],
    }[command]

    assert main(argv) == 2
    captured = capsys.readouterr()
    assert "macOS extended ACL" in captured.err


def test_init_refuses_to_overwrite(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_text(encoding="utf-8")
    assert main(["init", "--path", str(inventory)]) == 2
    captured = capsys.readouterr()
    assert "refusing to overwrite" in captured.err
    assert inventory.read_text(encoding="utf-8") == original


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertion")
def test_init_preserves_existing_parent_mode_on_success(tmp_path: Path, capsys) -> None:
    parent = tmp_path / "custom-parent"
    parent.mkdir()
    parent.chmod(0o755)

    inventory = parent / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()

    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(inventory.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertion")
def test_init_preserves_existing_parent_mode_on_refusal(tmp_path: Path, capsys) -> None:
    parent = tmp_path / "custom-parent"
    parent.mkdir()
    parent.chmod(0o755)
    inventory = parent / "inventory.yaml"
    inventory.write_text("do not replace\n", encoding="utf-8")

    assert main(["init", "--path", str(inventory)]) == 2
    captured = capsys.readouterr()

    assert "refusing to overwrite" in captured.err
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert inventory.read_text(encoding="utf-8") == "do not replace\n"


def test_init_rejects_non_directory_parent(tmp_path: Path, capsys) -> None:
    parent = tmp_path / "not-a-directory"
    parent.write_text("leave me alone\n", encoding="utf-8")

    assert main(["init", "--path", str(parent / "inventory.yaml")]) == 2
    captured = capsys.readouterr()

    assert "refusing non-directory AtReady path" in captured.err
    assert parent.read_text(encoding="utf-8") == "leave me alone\n"


def test_init_rejects_symlinked_parent(tmp_path: Path, capsys) -> None:
    target = tmp_path / "actual-directory"
    target.mkdir()
    parent = tmp_path / "linked-directory"
    try:
        parent.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")

    assert main(["init", "--path", str(parent / "inventory.yaml")]) == 2
    captured = capsys.readouterr()

    assert "refusing symlinked AtReady directory" in captured.err
    assert not (target / "inventory.yaml").exists()


def test_config_path_is_read_only(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "private-home"
    monkeypatch.setenv("ATREADY_HOME", str(home))
    assert main(["config", "path", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["inventory"] == str(home / "inventory.yaml")
    assert not home.exists()


def test_strict_validation_fails_on_unknown_state(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    text = demo_inventory().replace("current_session: available", "current_session: unknown", 1)
    inventory.write_text(text, encoding="utf-8")
    assert main(["inventory", "validate", str(inventory), "--strict", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["valid"] is False
    assert any("unknown current-session availability" in warning for warning in result["warnings"])


def test_schema_command_uses_pydantic_v2_schema_api(capsys) -> None:
    assert main(["schema", "inventory"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "Inventory"
    assert schema["additionalProperties"] is False


def test_project_route_yaml_snapshot_and_all_schemas(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "private-home"
    monkeypatch.setenv("ATREADY_HOME", str(home))
    assert main(["init"]) == 0
    capsys.readouterr()
    preview, receipt = _preview_and_apply(_resource_add_args(), capsys)
    assert receipt["previous_revision"] == preview["expect_revision"]

    assert main(["config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(home / "inventory.yaml")

    assert main(["inventory", "validate"]) == 0
    captured = capsys.readouterr()
    assert "Inventory is valid: 1 resources" in captured.out
    assert captured.err == ""

    assert main(["inventory", "snapshot", "--format", "yaml"]) == 0
    snapshot = capsys.readouterr().out
    assert "inventory_fingerprint:" in snapshot
    assert "private_notes:" not in snapshot

    assert main(["project", "template"]) == 0
    project_path = tmp_path / "project.yaml"
    project_path.write_text(capsys.readouterr().out, encoding="utf-8")

    assert main(["project", "validate", str(project_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert main(["project", "validate", str(project_path)]) == 0
    assert "Project is valid" in capsys.readouterr().out

    assert main(["route", "--project", str(project_path), "--format", "json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["assignments"][0]["primary"]["resource_id"] == "local-coding-agent"
    assert plan["warnings"] == []

    assert main(["route", "--project", str(project_path), "--format", "presentation"]) == 0
    presentation = json.loads(capsys.readouterr().out)
    assert presentation["format"] == "atready-route-presentation-v1"
    assert presentation["presentation_status"] == "ready"
    assert presentation["route"] == plan
    assert presentation["limits"]["requested"] == {"lines": None, "words": None}
    assert presentation["limits"]["required"]["words"] == len(presentation["summary"].split())
    assert presentation["limits"]["required"]["lines"] == len(presentation["summary"].splitlines())
    assert presentation["summary"].startswith(
        "Goal: Ship a tested local CLI without network access or telemetry.\n"
        "Route: 1 step assigned.\n"
    )
    assert presentation["summary"].count("Personal Local Coding Agent") == 1
    assert presentation["summary"].endswith("No routed project resources were contacted or run.\n")

    assert main(["route", "--project", str(project_path), "--format", "markdown"]) == 0
    markdown = capsys.readouterr().out
    assert "# AtReady route" in markdown
    assert "## Authorization boundary" in markdown

    assert main(["route", "--project", str(project_path)]) == 0
    summary = capsys.readouterr().out
    assert "Resource plan:" in summary
    assert "Use: Personal Local Coding Agent" in summary
    assert "AtReady made this plan only." in summary
    assert "## Authorization boundary" not in summary
    assert "Adjusted score" not in summary

    assert main(["route", "--project", str(project_path), "--width", "40"]) == 0
    narrow_summary = capsys.readouterr().out
    assert all(
        len(line) <= 40 or line == "No routed project resources were contacted or run."
        for line in narrow_summary.splitlines()
    )

    with pytest.raises(SystemExit) as invalid_width:
        main(["route", "--project", str(project_path), "--width", "39"])
    assert invalid_width.value.code == 2
    assert "expected an integer from 40 to 120" in capsys.readouterr().err

    assert main(["route", "--project", str(project_path), "--format", "json", "--width", "80"]) == 2
    assert (
        "--width is only available with --format summary or presentation" in capsys.readouterr().err
    )

    assert (
        main(
            [
                "route",
                "--project",
                str(project_path),
                "--format",
                "presentation",
                "--width",
                "40",
            ]
        )
        == 0
    )
    narrow_presentation = json.loads(capsys.readouterr().out)
    assert narrow_presentation["route"] == plan
    assert all(
        len(line) <= 40 or line == "No routed project resources were contacted or run."
        for line in narrow_presentation["summary"].splitlines()
    )

    assert (
        main(
            [
                "route",
                "--project",
                str(project_path),
                "--format",
                "presentation",
                "--max-words",
                "1",
                "--max-lines",
                "1",
            ]
        )
        == 0
    )
    limited_presentation = json.loads(capsys.readouterr().out)
    assert limited_presentation["presentation_status"] == "limit-conflict"
    assert limited_presentation["route"] == plan
    assert limited_presentation["limits"]["requested"] == {"lines": 1, "words": 1}
    assert (
        limited_presentation["limits"]["required"]["words"]
        == presentation["limits"]["required"]["words"]
    )
    assert (
        limited_presentation["limits"]["required"]["lines"]
        <= presentation["limits"]["required"]["lines"]
    )
    assert "Requested maximum: 1 word and 1 line." in limited_presentation["summary"]
    assert "Rerun without --max-words and --max-lines" in limited_presentation["summary"]
    assert limited_presentation["summary"].endswith(
        "No routed project resources were contacted or run.\n"
    )

    assert main(["route", "--project", str(project_path), "--max-words", "20"]) == 2
    assert (
        "--max-words and --max-lines are only available with --format presentation"
        in capsys.readouterr().err
    )

    with pytest.raises(SystemExit) as invalid_max_words:
        main(
            [
                "route",
                "--project",
                str(project_path),
                "--format",
                "presentation",
                "--max-words",
                "501",
            ]
        )
    assert invalid_max_words.value.code == 2
    assert "expected an integer from 1 to 500" in capsys.readouterr().err

    with pytest.raises(SystemExit) as invalid_max_lines:
        main(
            [
                "route",
                "--project",
                str(project_path),
                "--format",
                "presentation",
                "--max-lines",
                "0",
            ]
        )
    assert invalid_max_lines.value.code == 2
    assert "expected an integer from 1 to 50" in capsys.readouterr().err

    assert main(["skill", "path"]) == 0
    skill_path = Path(capsys.readouterr().out.strip())
    assert (skill_path / "SKILL.md").is_file()

    for kind, title in (("project", "ProjectBrief"), ("route-plan", "RoutePlan")):
        assert main(["schema", kind]) == 0
        assert json.loads(capsys.readouterr().out)["title"] == title


def test_route_returns_gap_exit_when_required_alternate_is_unavailable(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "private-home"
    monkeypatch.setenv("ATREADY_HOME", str(home))
    assert main(["init"]) == 0
    capsys.readouterr()
    _preview_and_apply(_resource_add_args(), capsys)

    assert main(["project", "template"]) == 0
    project_path = tmp_path / "project.yaml"
    project_path.write_text(
        capsys.readouterr().out.replace("alternate_required: false", "alternate_required: true"),
        encoding="utf-8",
    )

    assert main(["route", "--project", str(project_path), "--format", "json"]) == 3
    plan = json.loads(capsys.readouterr().out)
    assignment = plan["assignments"][0]
    assert assignment["primary"]["resource_id"] == "local-coding-agent"
    assert assignment["alternate"] is None
    assert assignment["unresolved_gaps"] == [
        {
            "code": "required-alternate-unavailable",
            "reason": (
                "An alternate is required, but no additional standalone-eligible resource remains "
                "after primary and support selection."
            ),
        }
    ]

    assert main(["route", "--project", str(project_path), "--format", "presentation"]) == 3
    presentation = json.loads(capsys.readouterr().out)
    assert presentation["presentation_status"] == "ready"
    assert presentation["route"] == plan
    assert "1 open gap" in presentation["summary"]
    assert presentation["summary"].endswith("No routed project resources were contacted or run.\n")

    assert main(["route", "--project", str(project_path), "--format", "markdown"]) == 3
    markdown = capsys.readouterr().out
    assert "required-alternate-unavailable" in markdown
    assert "Primary: **Personal Local Coding Agent**" in markdown

    assert main(["route", "--project", str(project_path)]) == 3
    summary = capsys.readouterr().out
    assert "1 open gap" in summary
    assert "Gaps and decisions" in summary
    assert "required-alternate-unavailable" not in summary
    assert "No routed project resources were contacted or run." in summary


def test_inventory_add_is_preview_first_and_requires_exact_revision(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()
    args = _resource_add_args(inventory)

    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["operation"] == "add-resource"
    assert preview["resource_count_before"] == 0
    assert preview["resource_count_after"] == 1
    assert preview["canonicalizes_yaml"] is True
    assert preview["resource"]["name"] == "Personal Local Coding Agent"
    assert preview["resource"]["capabilities"] == {
        "code-implementation": 0.9,
        "test-automation": 0.85,
    }
    assert preview["resource"]["ratings"]["quality"] == 0.5
    assert "private_notes" not in preview["resource"]
    assert inventory.read_bytes() == original

    assert main([*args, "--apply", "--json"]) == 2
    assert "requires --expect-revision and --expect-plan" in capsys.readouterr().err
    assert inventory.read_bytes() == original

    assert main([*args, "--expect-revision", preview["expect_revision"], "--json"]) == 2
    assert "only valid with --apply" in capsys.readouterr().err
    assert inventory.read_bytes() == original

    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                "sha256:wrong",
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 2
    )
    assert "does not match this preview" in capsys.readouterr().err
    assert inventory.read_bytes() == original

    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                "sha256:wrong",
                "--json",
            ]
        )
        == 2
    )
    assert "--expect-plan does not match" in capsys.readouterr().err
    assert inventory.read_bytes() == original

    changed_args = _resource_add_args(inventory, resource_id="different-tool")
    assert (
        main(
            [
                *changed_args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 2
    )
    assert "--expect-plan does not match" in capsys.readouterr().err
    assert inventory.read_bytes() == original

    _, receipt = _preview_and_apply(args, capsys)
    assert receipt["resource_id"] == "local-coding-agent"
    assert Path(receipt["backup_path"]).read_bytes() == original

    assert main(["inventory", "list", str(inventory), "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing["inventory_kind"] == "personal"
    assert listing["revision"] == receipt["revision"]
    assert [item["id"] for item in listing["resources"]] == ["local-coding-agent"]

    assert main([*args, "--json"]) == 2
    assert "already exists" in capsys.readouterr().err


def test_inventory_replace_and_remove_are_preview_first_and_backed_up(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    _preview_and_apply(_resource_add_args(inventory), capsys)
    before_replace = inventory.read_bytes()

    replace_args = _resource_add_args(inventory)
    replace_args[1] = "replace"
    replace_args[replace_args.index("--name") + 1] = "Revised Local Coding Agent"
    replace_preview, replace_receipt = _preview_and_apply(replace_args, capsys)

    assert replace_preview["operation"] == "replace-resource"
    assert replace_preview["resource_before"]["name"] == "Personal Local Coding Agent"
    assert replace_preview["resource_after"]["name"] == "Revised Local Coding Agent"
    assert replace_preview["intake_review"]["selection_fact_status"] == ("selection-facts-declared")
    assert replace_preview["intake_review"]["route_eligibility_evaluated"] is False
    assert replace_receipt["operation"] == "replace-resource"
    assert replace_receipt["backup_id"].startswith("sha256:")
    replace_backup = Path(replace_receipt["backup_path"])
    assert replace_backup.read_bytes() == before_replace
    assert replace_receipt["backup_id"].removeprefix("sha256:") in replace_backup.name
    before_remove = inventory.read_bytes()

    remove_args = [
        "inventory",
        "remove",
        "--path",
        str(inventory),
        "--resource",
        "local-coding-agent",
    ]
    remove_preview, remove_receipt = _preview_and_apply(remove_args, capsys)

    assert remove_preview["operation"] == "remove-resource"
    assert remove_preview["resource"]["name"] == "Revised Local Coding Agent"
    assert remove_preview["resource_count_before"] == 1
    assert remove_preview["resource_count_after"] == 0
    assert remove_receipt["operation"] == "remove-resource"
    assert remove_receipt["backup_id"].startswith("sha256:")
    remove_backup = Path(remove_receipt["backup_path"])
    assert remove_backup.read_bytes() == before_remove
    assert remove_receipt["backup_id"].removeprefix("sha256:") in remove_backup.name
    assert main(["inventory", "list", str(inventory), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["resources"] == []


def test_inventory_replace_and_remove_human_output_explains_full_effect(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    _preview_and_apply(_resource_add_args(inventory), capsys)
    replace_args = _resource_add_args(inventory)
    replace_args[1] = "replace"
    replace_args[replace_args.index("--name") + 1] = "Revised Local Coding Agent"

    assert main(replace_args) == 0
    replace_output = capsys.readouterr().out
    assert "replacement preview (no files changed)" in replace_output
    assert "Current resource (private notes omitted)" in replace_output
    assert "Replacement resource (private notes omitted)" in replace_output
    assert "Private notes effect:" in replace_output
    assert "Selection-fact status: selection-facts-declared" in replace_output
    assert "Scoring-input defaults:" in replace_output
    assert "Route eligibility evaluated: false." in replace_output

    assert main([*replace_args, "--json"]) == 0
    replace_preview = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                *replace_args,
                "--apply",
                "--expect-revision",
                replace_preview["expect_revision"],
                "--expect-plan",
                replace_preview["expect_plan"],
            ]
        )
        == 0
    )
    assert "Replaced resource 'local-coding-agent'" in capsys.readouterr().out

    remove_args = [
        "inventory",
        "remove",
        "--path",
        str(inventory),
        "--resource",
        "local-coding-agent",
    ]
    assert main(remove_args) == 0
    remove_output = capsys.readouterr().out
    assert "removal preview (no files changed)" in remove_output
    assert "Resource to remove (private notes omitted)" in remove_output
    assert "Resource count: 1 -> 0" in remove_output

    assert main([*remove_args, "--json"]) == 0
    remove_preview = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                *remove_args,
                "--apply",
                "--expect-revision",
                remove_preview["expect_revision"],
                "--expect-plan",
                remove_preview["expect_plan"],
            ]
        )
        == 0
    )
    assert "Removed resource 'local-coding-agent'" in capsys.readouterr().out


def test_preview_plan_token_binds_absolute_target_across_working_directories(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for directory in (first, second):
        assert main(["init", "--path", str(directory / "inventory.yaml")]) == 0
        capsys.readouterr()
    (second / "inventory.yaml").write_bytes((first / "inventory.yaml").read_bytes())

    monkeypatch.chdir(first)
    relative_args = _resource_add_args(Path("inventory.yaml"))
    assert main([*relative_args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["target"] == str(first / "inventory.yaml")

    monkeypatch.chdir(second)
    assert (
        main(
            [
                *relative_args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 2
    )
    assert "--expect-plan does not match" in capsys.readouterr().err

    assert main(["inventory", "list", str(first / "inventory.yaml"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["resources"] == []
    assert main(["inventory", "list", str(second / "inventory.yaml"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["resources"] == []


def test_preview_plan_token_binds_canonical_target_across_ancestor_retarget(
    tmp_path: Path, capsys
) -> None:
    first = tmp_path / "first" / "nested" / "inventory.yaml"
    second = tmp_path / "second" / "nested" / "inventory.yaml"
    for inventory in (first, second):
        assert main(["init", "--path", str(inventory)]) == 0
        capsys.readouterr()
    second.write_bytes(first.read_bytes())
    first_original = first.read_bytes()
    second_original = second.read_bytes()

    selected = tmp_path / "selected"
    try:
        selected.symlink_to(first.parents[1], target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")
    args = _resource_add_args(selected / "nested" / "inventory.yaml")
    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["target"] == str(first.resolve())

    selected.unlink()
    selected.symlink_to(second.parents[1], target_is_directory=True)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 2
    )
    assert "--expect-plan does not match" in capsys.readouterr().err
    assert first.read_bytes() == first_original
    assert second.read_bytes() == second_original


def test_human_path_output_escapes_terminal_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    unsafe_home = tmp_path / "private\x1bhome\nline\tdir"
    monkeypatch.setenv("ATREADY_HOME", str(unsafe_home))

    assert main(["config", "path"]) == 0
    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "\t" not in output
    assert output.count("\n") == 1
    assert "\\x1b" in output
    assert "\\n" in output
    assert "\\t" in output

    missing = tmp_path / "missing\x1binventory\nline\tfile.yaml"
    assert main(["inventory", "validate", str(missing)]) == 2
    error = capsys.readouterr().err
    assert "\x1b" not in error
    assert "\t" not in error
    lines = error.splitlines()
    assert len(lines) in {1, 2}
    assert lines[0].startswith("error: ")
    if len(lines) == 2:
        assert lines[1] == "next: Create your roster: atready init"
    assert "\\x1b" in error
    assert "\\n" in error
    assert "\\t" in error


def test_human_apply_receipt_prints_backup_path(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    args = _resource_add_args(inventory)

    assert main(args) == 0
    human_preview = capsys.readouterr().out
    assert "Candidate resource (all persisted routing fields):" in human_preview
    assert '"quality": 0.5' in human_preview
    assert "Expected plan: sha256:" in human_preview

    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)

    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "Replacement verified: true" in captured.out
    assert "Backup ID: sha256:" in captured.out
    assert "Backup path:" in captured.out

    assert main(["inventory", "list", str(inventory)]) == 0
    listing = capsys.readouterr().out
    assert "Inventory: personal · 1 resources" in listing
    assert "local-coding-agent: Personal Local Coding Agent" in listing


def test_inventory_add_from_private_file_previews_and_applies_hidden_notes(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    source = tmp_path / "resource.yaml"
    raw = _resource_declaration()
    source.write_bytes(raw)
    if os.name == "posix":
        source.chmod(0o600)
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    args = [
        "inventory",
        "add",
        "--path",
        str(inventory),
        "--resource-file",
        str(source),
    ]

    assert main(args) == 0
    human = capsys.readouterr()
    assert "Private notes: present; value omitted and bound to this plan" in human.out
    assert "Selection-fact status: requires-verification" in human.out
    assert "Unverified selection facts: access.status" in human.out
    assert "Conservative-policy defaults:" in human.out
    assert "Route eligibility evaluated: false." in human.out
    assert _PRIVATE_SENTINEL not in human.out + human.err

    assert main([*args, "--json"]) == 0
    captured = capsys.readouterr()
    assert _PRIVATE_SENTINEL not in captured.out + captured.err
    preview = json.loads(captured.out)
    assert preview["private_notes_present"] is True
    assert preview["private_notes_exposed"] is False
    assert preview["private_notes_bound_to_plan"] is True
    assert preview["intake_review"]["selection_fact_status"] == "requires-verification"
    assert preview["intake_review"]["unverified_selection_facts"] == [
        "access.status",
        "access.current_session",
        "economics.quota",
        "provenance.basis",
        "provenance.last_verified",
    ]
    assert preview["intake_review"]["route_eligibility_evaluated"] is False

    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert _PRIVATE_SENTINEL not in captured.out + captured.err
    receipt = json.loads(captured.out)
    assert receipt["private_notes_present"] is True
    assert receipt["private_notes_exposed"] is False
    assert source.read_bytes() == raw
    stored = InventoryCatalog.from_path(inventory).inventory.resources[0]
    assert stored.private_notes == _PRIVATE_SENTINEL


def test_inventory_add_from_stdin_is_bounded_preview_then_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    raw = _resource_declaration(note="stdin-private-note")
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    args = ["inventory", "add", "--path", str(inventory), "--resource-stdin", "--json"]

    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))
    assert main(args) == 0
    preview = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(sys, "stdin", _BinaryInput(raw))
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["replacement_verified"] is True
    assert InventoryCatalog.from_path(inventory).inventory.resources[0].private_notes == (
        "stdin-private-note"
    )


def test_file_and_stdin_formatting_bind_the_same_semantic_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    source = tmp_path / "resource.yaml"
    source.write_bytes(_resource_declaration())
    if os.name == "posix":
        source.chmod(0o600)
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(inventory),
                "--resource-file",
                str(source),
                "--json",
            ]
        )
        == 0
    )
    file_preview = json.loads(capsys.readouterr().out)
    reordered = (
        "# Transport formatting is intentionally not plan-bound.\n"
        "resource:\n"
        f"  private_notes: {_PRIVATE_SENTINEL}\n"
        "  capabilities: {code-implementation: 0.9}\n"
        "  categories:\n"
        "    - coding-agent\n"
        "  name: Structured Tool\n"
        "  id: structured-tool\n"
        "schema_version: 1\n"
    ).encode()
    monkeypatch.setattr(sys, "stdin", _BinaryInput(reordered))
    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(inventory),
                "--resource-stdin",
                "--json",
            ]
        )
        == 0
    )
    stdin_preview = json.loads(capsys.readouterr().out)

    assert stdin_preview["expect_plan"] == file_preview["expect_plan"]
    assert stdin_preview["candidate_revision"] == file_preview["candidate_revision"]
    assert stdin_preview["defaulted_fields"] == file_preview["defaulted_fields"]


def test_changed_private_note_invalidates_stdin_apply_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    args = ["inventory", "add", "--path", str(inventory), "--resource-stdin", "--json"]
    monkeypatch.setattr(sys, "stdin", _BinaryInput(_resource_declaration(note="note-one")))
    assert main(args) == 0
    preview = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(sys, "stdin", _BinaryInput(_resource_declaration(note="note-two")))
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "expect-plan does not match" in captured.err
    assert "note-one" not in captured.out + captured.err
    assert "note-two" not in captured.out + captured.err
    assert InventoryCatalog.from_path(inventory).inventory.resources == []
    assert not (tmp_path / ".quartermaster-backups").exists()


def test_structured_add_mode_errors_refuse_before_reading_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    source = tmp_path / "resource.yaml"
    source.write_bytes(_resource_declaration())
    if os.name == "posix":
        source.chmod(0o600)
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(sys, "stdin", _UnreadableInput())

    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(inventory),
                "--resource-stdin",
                "--resource-file",
                str(source),
            ]
        )
        == 2
    )
    assert "choose exactly one" in capsys.readouterr().err

    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(inventory),
                "--resource-stdin",
                "--id",
                "mixed-tool",
            ]
        )
        == 2
    )
    assert "cannot be combined" in capsys.readouterr().err

    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(inventory),
                "--resource-stdin",
                "--apply",
            ]
        )
        == 2
    )
    assert "requires --expect-revision and --expect-plan" in capsys.readouterr().err


def test_structured_stdin_errors_never_echo_source_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    malformed = b"schema_version: 1\nresource:\n  private_notes: [SYNTHETIC-PRIVATE-SENTINEL\n"
    monkeypatch.setattr(sys, "stdin", _BinaryInput(malformed))

    assert main(["inventory", "add", "--path", str(inventory), "--resource-stdin"]) == 2
    captured = capsys.readouterr()
    assert "invalid YAML at line" in captured.err
    assert _PRIVATE_SENTINEL not in captured.out + captured.err
    assert InventoryCatalog.from_path(inventory).inventory.resources == []


def test_inventory_add_requires_one_complete_input_mode(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()

    assert main(["inventory", "add", "--path", str(inventory)]) == 2
    error = capsys.readouterr().err
    assert "typed resource input requires --id, --name, --category, --capability" in error
    assert "--resource-file or --resource-stdin" in error


def test_legacy_unblinded_inventory_accepts_note_free_add_but_refuses_private_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    initialized = InventoryCatalog.from_path(inventory).inventory
    nonce = initialized.revision_privacy_nonce
    assert nonce is not None
    inventory.write_text(
        inventory.read_text(encoding="utf-8").replace(f'revision_privacy_nonce: "{nonce}"\n', ""),
        encoding="utf-8",
    )
    original = inventory.read_bytes()

    note_free_args = [
        "inventory",
        "add",
        "--path",
        str(inventory),
        "--resource-stdin",
        "--json",
    ]
    monkeypatch.setattr(sys, "stdin", _BinaryInput(_resource_declaration(note=None)))
    assert main(note_free_args) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["revision_protection"] == "legacy-unblinded"
    monkeypatch.setattr(sys, "stdin", _BinaryInput(_resource_declaration(note=None)))
    assert (
        main(
            [
                *note_free_args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["candidate_revision_protection"] == "legacy-unblinded"
    assert receipt["observed_revision_protection"] == "legacy-unblinded"
    assert "revision_privacy_nonce" not in inventory.read_text(encoding="utf-8")

    second_inventory = tmp_path / "legacy-private" / "inventory.yaml"
    second_inventory.parent.mkdir()
    second_inventory.write_bytes(original)
    if os.name == "posix":
        second_inventory.chmod(0o600)
    monkeypatch.setattr(sys, "stdin", _BinaryInput(_resource_declaration()))
    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(second_inventory),
                "--resource-stdin",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "legacy-unblinded inventories cannot contain private notes" in captured.err
    assert "do not add a nonce manually" in captured.err
    assert _PRIVATE_SENTINEL not in captured.out + captured.err
    assert second_inventory.read_bytes() == original
    assert not second_inventory.with_name(f".{second_inventory.name}.lock").exists()
    assert not (second_inventory.parent / ".quartermaster-backups").exists()


def test_inventory_add_help_names_typed_mode_requirements(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["inventory", "add", "--help"])

    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    assert "Typed mode requires --id, --name" in help_text
    assert "one or more --category" in help_text
    assert "one or more --capability" in help_text


def test_resource_declaration_schema_is_publicly_discoverable(capsys) -> None:
    assert main(["schema", "resource-declaration"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "ResourceDeclaration"
    assert set(schema["required"]) == {"resource", "schema_version"}

    definitions = schema["$defs"]
    resource = definitions["Resource"]
    assert set(resource["required"]) == {"id", "name", "categories", "capabilities"}
    assert "schema_version" not in resource["properties"]
    assert definitions["AccessStatus"]["enum"] == ["active", "limited", "inactive", "unknown"]
    assert definitions["SessionAvailability"]["enum"] == [
        "available",
        "unavailable",
        "unknown",
    ]
    assert definitions["InteractionMode"]["enum"] == [
        "codex-callable",
        "local-cli",
        "external-agent",
        "manual",
    ]
    assert definitions["BillingModel"]["enum"] == [
        "free",
        "owned",
        "subscription",
        "usage",
        "unknown",
    ]
    assert definitions["QuotaStatus"]["enum"] == [
        "ample",
        "limited",
        "exhausted",
        "unknown",
    ]
    assert definitions["DataClass"]["enum"] == [
        "public",
        "internal",
        "private",
        "sensitive",
    ]
    assert definitions["ConfidenceBasis"]["enum"] == [
        "observed",
        "user-judgment",
        "vendor-claim",
        "unknown",
    ]
    assert definitions["HandoffMethod"]["enum"] == [
        "direct",
        "manual-prompt",
        "interactive",
        "file-export",
    ]

    access = definitions["Access"]["properties"]
    assert access["status"]["default"] == "unknown"
    assert access["interaction"]["default"] == "manual"
    assert access["current_session"]["default"] == "unknown"
    economics = definitions["Economics"]["properties"]
    assert economics["billing"]["default"] == "unknown"
    assert economics["marginal_cost"]["default"] == 0.5
    assert economics["quota"]["default"] == "unknown"
    assert economics["capacity"] == {
        "anyOf": [{"$ref": "#/$defs/Capacity"}, {"type": "null"}],
        "default": None,
    }
    capacity = definitions["Capacity"]
    assert capacity["additionalProperties"] is False
    assert set(capacity["required"]) == {"unit", "remaining", "basis", "last_verified"}
    assert capacity["properties"]["unit"]["pattern"] == "^[a-z0-9][a-z0-9._-]*$"
    assert capacity["properties"]["remaining"]["minimum"] == 0
    assert capacity["properties"]["limit"]["default"] is None
    assert capacity["properties"]["project_limit"]["default"] is None
    assert capacity["properties"]["resets_on"]["default"] is None
    ratings = definitions["Ratings"]["properties"]
    assert {name: field["default"] for name, field in ratings.items()} == {
        "autonomy": 0.5,
        "confidence": 0.5,
        "context_switch_cost": 0.5,
        "integration_friction": 0.5,
        "privacy": 0.5,
        "quality": 0.5,
        "reliability": 0.5,
        "speed": 0.5,
    }
    policy = definitions["Policy"]["properties"]
    assert policy["approval_required"]["default"] is True
    assert policy["requires_network"]["default"] is False
    provenance = definitions["Provenance"]["properties"]
    assert provenance["basis"]["default"] == "unknown"
    assert provenance["last_verified"]["default"] is None
    handoff = definitions["Handoff"]["properties"]
    assert handoff["method"]["default"] == "manual-prompt"
    assert handoff["instructions"]["default"] is None


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("--capability", "missing-score", "must use ID=SCORE"),
        ("--capability", "=0.5", "ID must not be empty"),
        ("--capability", "build=not-a-number", "score must be a number"),
        ("--capability", "build=nan", "score must be a finite number"),
        ("--rating", "speed=inf", "score must be a finite number"),
        ("--marginal-cost", "nan", "marginal cost must be a finite number"),
        ("--rating", "mystery=0.5", "unknown rating names"),
    ],
)
def test_inventory_add_rejects_malformed_scored_flags(
    tmp_path: Path, capsys, flag: str, value: str, message: str
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    args = [
        "inventory",
        "add",
        "--path",
        str(inventory),
        "--id",
        "bad-tool",
        "--name",
        "Bad Tool",
        "--category",
        "tool",
        flag,
        value,
    ]
    if flag != "--capability":
        args.extend(["--capability", "build=0.5"])

    assert main(args) == 2
    assert message in capsys.readouterr().err


def test_inventory_add_typed_capacity_is_previewed_without_applying(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    before = inventory.read_bytes()
    today = date.today().isoformat()
    args = [
        *_resource_add_args(inventory),
        "--capacity-unit",
        "requests",
        "--capacity-remaining",
        "250",
        "--capacity-limit",
        "1000",
        "--capacity-project-limit",
        "100",
        "--capacity-resets-on",
        today,
        "--capacity-basis",
        "observed",
        "--capacity-verified-on",
        today,
        "--json",
    ]

    assert main(args) == 0
    preview = json.loads(capsys.readouterr().out)

    assert preview["applied"] is False
    assert preview["resource"]["economics"]["capacity"] == {
        "basis": "observed",
        "last_verified": today,
        "limit": 1000,
        "project_limit": 100,
        "remaining": 250,
        "resets_on": today,
        "unit": "requests",
    }
    assert inventory.read_bytes() == before


def test_inventory_add_structured_capacity_is_previewed_without_applying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    before = inventory.read_bytes()
    today = date.today().isoformat()
    declaration = (
        "schema_version: 1\n"
        "resource:\n"
        "  id: capacity-tool\n"
        "  name: Capacity Tool\n"
        "  categories: [tool]\n"
        "  capabilities: {build: 0.8}\n"
        "  economics:\n"
        "    quota: limited\n"
        "    capacity:\n"
        "      unit: tokens\n"
        "      remaining: 125000.5\n"
        "      limit: 1000000\n"
        "      project_limit: 50000\n"
        "      basis: user-judgment\n"
        f"      last_verified: {today}\n"
    ).encode()
    monkeypatch.setattr(sys, "stdin", _BinaryInput(declaration))

    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(inventory),
                "--resource-stdin",
                "--json",
            ]
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)

    assert preview["resource"]["economics"]["capacity"] == {
        "basis": "user-judgment",
        "last_verified": today,
        "limit": 1000000,
        "project_limit": 50000,
        "remaining": 125000.5,
        "resets_on": None,
        "unit": "tokens",
    }
    assert inventory.read_bytes() == before


def test_structured_capacity_rejects_huge_integer_without_traceback_or_value_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    huge_value = "9" * 400
    today = date.today().isoformat()
    declaration = (
        "schema_version: 1\n"
        "resource:\n"
        "  id: huge-capacity\n"
        "  name: Huge Capacity\n"
        "  categories: [tool]\n"
        "  capabilities: {build: 0.8}\n"
        "  economics:\n"
        "    quota: limited\n"
        "    capacity:\n"
        "      unit: tokens\n"
        f"      remaining: {huge_value}\n"
        "      basis: observed\n"
        f"      last_verified: {today}\n"
    ).encode()
    monkeypatch.setattr(sys, "stdin", _BinaryInput(declaration))

    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(inventory),
                "--resource-stdin",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "resource declaration validation failed" in captured.err
    assert huge_value not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err
    assert InventoryCatalog.from_path(inventory).inventory.resources == []


def test_resource_profiles_and_alias_show_catalog_proposals_only(capsys) -> None:
    assert main(["resource", "profiles", "--json"]) == 0
    listing = json.loads(capsys.readouterr().out)

    assert listing["catalog_version"] == 1
    assert listing["catalog_proposals_only"] is True
    assert listing["resource_or_account_facts"] is False
    assert listing["discovery_performed"] is False
    assert listing["writes_performed"] is False
    assert [profile["id"] for profile in listing["profiles"]] == sorted(
        profile["id"] for profile in listing["profiles"]
    )
    assert "codex" in {profile["id"] for profile in listing["profiles"]}

    assert main(["resource", "profile", "codex", "--json"]) == 0
    exact = json.loads(capsys.readouterr().out)
    assert main(["resource", "profile", "openai-codex", "--json"]) == 0
    alias = json.loads(capsys.readouterr().out)

    assert exact["id"] == alias["id"] == "codex"
    assert exact["catalog_version"] == alias["catalog_version"] == 1
    assert alias["catalog_proposals_only"] is True
    assert alias["resource_or_account_facts"] is False
    assert alias["suggestions_are_proposals"] is True

    assert main(["resource", "profile", "coderabbit", "--json"]) == 0
    coderabbit = json.loads(capsys.readouterr().out)
    assert coderabbit["executable_probe"]["executable"] == "coderabbit"
    assert coderabbit["executable_probe"]["supported_platforms"] == ["posix"]
    assert coderabbit["executable_probe"]["aliases"] == ["cr"]
    assert coderabbit["executable_probe"]["alias_platforms"] == ["posix"]
    assert coderabbit["provider_kit"]["account_inspection"] == "unsupported"
    assert coderabbit["provider_kit"]["atready_network_access"] == "none"
    assert coderabbit["provider_kit"]["provider_execution"] == "unsupported"
    assert [mode["id"] for mode in coderabbit["provider_kit"]["workflow_mode_suggestions"]] == [
        "local-cli",
        "pull-request-app",
        "manual-review",
    ]

    assert main(["resource", "profile", "opencode-cli", "--json"]) == 0
    opencode = json.loads(capsys.readouterr().out)
    assert opencode["id"] == "opencode"
    assert opencode["executable_probe"]["executable"] == "opencode"
    assert opencode["executable_probe"]["version_args"] == ["--version"]
    assert [mode["id"] for mode in opencode["provider_kit"]["workflow_mode_suggestions"]] == [
        "interactive-terminal",
        "delegated-cli",
        "desktop-or-ide",
    ]
    assert opencode["provider_kit"]["account_inspection"] == "unsupported"
    assert opencode["provider_kit"]["provider_execution"] == "unsupported"
    assert opencode["provider_kit"]["model_catalog_reviewed_on"] == "2026-08-09"
    assert opencode["provider_kit"]["model_routing_suggestions"][0] == {
        "availability": "unverified",
        "capability_scores": "user-confirmed-only",
        "id": "deepseek-v4-flash-free",
        "label": "DeepSeek V4 Flash Free",
        "planning_caution": (
            "It is temporary and not OpenCode's universal default; confirm data policy, "
            "current availability, and task quality before routing."
        ),
        "planning_role": (
            "A currently free OpenCode Zen option to calibrate on well-scoped coding tasks "
            "when cost sensitivity matters."
        ),
        "provider_model_id": "opencode/deepseek-v4-flash-free",
        "selection_status": "temporary-option",
        "shared_capacity_group": None,
        "suggested_resource_id": "opencode-deepseek-v4-flash-free",
    }

    for query, expected_id, executable in (
        ("agy", "antigravity", "agy"),
        ("claude-cli", "claude-code", "claude"),
        ("github-copilot-cli", "github-copilot", "copilot"),
    ):
        assert main(["resource", "profile", query, "--json"]) == 0
        coding_agent = json.loads(capsys.readouterr().out)
        assert coding_agent["id"] == expected_id
        assert coding_agent["executable_probe"]["executable"] == executable
        if expected_id in {"claude-code", "github-copilot"}:
            assert coding_agent["executable_probe"]["supported_platforms"] == ["posix"]
        if expected_id == "github-copilot":
            assert coding_agent["executable_probe"]["version_args"] == []
        assert coding_agent["provider_kit"]["account_inspection"] == "unsupported"
        assert coding_agent["provider_kit"]["provider_execution"] == "unsupported"

    assert main(["resource", "profile", "cursor-editor", "--json"]) == 0
    cursor = json.loads(capsys.readouterr().out)
    assert cursor["id"] == "cursor"
    assert cursor["executable_probe"] is None
    assert [mode["id"] for mode in cursor["provider_kit"]["workflow_mode_suggestions"]] == [
        "cursor-editor",
        "interactive-cli",
        "authorized-headless-cli",
        "cloud-agent",
    ]
    assert cursor["provider_kit"]["model_catalog_reviewed_on"] == "2026-08-09"
    assert [
        (item["id"], item["suggested_resource_id"], item["shared_capacity_group"])
        for item in cursor["provider_kit"]["model_routing_suggestions"]
    ] == [
        ("composer-2-5", "cursor-composer-2-5", "cursor-models-pool"),
        ("grok-4-5", "cursor-grok-4-5", "cursor-models-pool"),
    ]

    assert main(["resource", "profile", "xai-grok", "--json"]) == 0
    grok = json.loads(capsys.readouterr().out)
    assert grok["id"] == "grok"
    assert grok["provider_kit"]["model_catalog_reviewed_on"] == "2026-08-09"
    assert grok["provider_kit"]["model_routing_suggestions"] == [
        {
            "availability": "unverified",
            "capability_scores": "user-confirmed-only",
            "id": "grok-4-5",
            "label": "Grok 4.5",
            "planning_caution": (
                "The app, API, and the Cursor-hosted version have different access, policy, "
                "and capacity; confirm the exact surface rather than treating them as one "
                "resource."
            ),
            "planning_role": (
                "Complex reasoning across code, architecture, research, analysis, and "
                "multi-step professional work."
            ),
            "provider_model_id": "grok-4.5",
            "selection_status": "standalone-model",
            "shared_capacity_group": None,
            "suggested_resource_id": "grok-4-5",
        }
    ]

    assert main(["resource", "profile", "pixellab-ai", "--json"]) == 0
    pixellab = json.loads(capsys.readouterr().out)
    assert pixellab["id"] == "pixellab"
    assert [item["unit"] for item in pixellab["capacity_unit_hints"]] == ["image", "credit"]
    assert [item["id"] for item in pixellab["provider_kit"]["workflow_mode_suggestions"]] == [
        "web-creator",
        "browser-editor",
        "aseprite-extension",
        "configured-api",
    ]
    assert "2,000 images monthly" in str(pixellab["provider_kit"])
    allowance = next(
        item
        for item in pixellab["provider_kit"]["capacity_guidance"]
        if item["id"] == "tier-allowance"
    )
    assert "5,000 images monthly" in allowance["prompt"]
    assert "10,000 images monthly" in allowance["prompt"]
    assert "up to 20 concurrent background jobs" in allowance["prompt"]

    assert main(["resource", "profile", "retrodiffusion", "--json"]) == 0
    retro = json.loads(capsys.readouterr().out)
    assert retro["id"] == "retro-diffusion"
    assert [item["unit"] for item in retro["capacity_unit_hints"]] == [
        "generation",
        "credit",
    ]
    assert [item["id"] for item in retro["provider_kit"]["workflow_mode_suggestions"]] == [
        "cloud-website",
        "configured-api",
        "aseprite-extension",
    ]
    assert "website credits rather than a subscription" in str(retro["provider_kit"])

    assert main(["resource", "profile", "figma-design"]) == 0
    human = capsys.readouterr().out
    assert "Resource profile proposal: Figma (figma)" in human
    assert "Catalog proposals only; no resource or account facts were inspected." in human
    assert "Writes performed: false" in human

    assert main(["resource", "profile", "code-rabbit"]) == 0
    coderabbit_human = capsys.readouterr().out
    assert "Provider workflow-mode proposals:" in coderabbit_human
    assert "Local discovery executable proposals: coderabbit, cr" in coderabbit_human
    assert "Local discovery platforms: posix" in coderabbit_human
    assert "pull-request-app: Pull-request app review (interaction: external-agent)" in (
        coderabbit_human
    )
    assert "Provider onboarding guidance:" in coderabbit_human
    assert "Provider capacity guidance:" in coderabbit_human
    assert (
        "Provider kit limits: account inspection unsupported; AtReady network access none; "
        "provider execution unsupported." in coderabbit_human
    )

    assert main(["resource", "profile", "open-code"]) == 0
    opencode_human = capsys.readouterr().out
    assert "Resource profile proposal: OpenCode (opencode)" in opencode_human
    assert "Local discovery executable proposals: opencode" in opencode_human
    assert "Interactive terminal session (interaction: local-cli)" in opencode_human
    assert "Separately authorized CLI task (interaction: codex-callable)" in opencode_human
    assert "Catalog proposals only; no resource or account facts were inspected." in opencode_human
    assert "DeepSeek V4 Flash Free" in opencode_human
    assert "status: temporary-option" in opencode_human
    assert "not OpenCode's universal default" in opencode_human

    assert main(["resource", "profile", "cursor"]) == 0
    cursor_human = capsys.readouterr().out
    assert "Provider model-routing proposals (reviewed 2026-08-09" in cursor_human
    assert "Composer 2.5 (provider model: composer-2.5" in cursor_human
    assert "Cursor Grok 4.5 (provider model: grok-4.5" in cursor_human
    assert cursor_human.count("Shared capacity proposal: cursor-models-pool") == 2

    assert main(["resource", "profile", "grok"]) == 0
    grok_human = capsys.readouterr().out
    assert "Grok 4.5 (provider model: grok-4.5" in grok_human
    assert "status: standalone-model" in grok_human
    assert "the Cursor-hosted version have different access" in grok_human

    assert main(["resource", "profile", "pixellab"]) == 0
    pixellab_human = capsys.readouterr().out
    assert "Resource profile proposal: PixelLab (pixellab)" in pixellab_human
    assert "Capacity unit hints: image, credit" in pixellab_human
    assert "Pixel Apprentice, Pixel Artisan, and Pixel Architect" in pixellab_human
    assert "10,000 images monthly" in pixellab_human
    assert "up to 20 concurrent background jobs" in pixellab_human
    assert "AtReady does not refresh or decrement the balance" in pixellab_human

    assert main(["resource", "profile", "retro-diffusion"]) == 0
    retro_human = capsys.readouterr().out
    assert "Resource profile proposal: Retro Diffusion (retro-diffusion)" in retro_human
    assert "Person-mediated cloud website (interaction: manual)" in retro_human
    assert "website credits rather than a subscription" in retro_human
    assert "owned local extension has no credit balance" in retro_human.casefold()

    assert main(["resource", "profile", "claudecode"]) == 0
    claude_human = capsys.readouterr().out
    assert "Resource profile proposal: Claude Code (claude-code)" in claude_human
    assert "Local discovery executable proposals: claude" in claude_human
    assert "Separately configured CI automation (interaction: external-agent)" in claude_human

    assert main(["resource", "profile", "cursor-ai"]) == 0
    cursor_human = capsys.readouterr().out
    assert "Resource profile proposal: Cursor (cursor)" in cursor_human
    assert "Local discovery executable proposals:" not in cursor_human
    assert "Separately configured Cloud Agent (interaction: external-agent)" in cursor_human


def test_resource_discovery_absent_exact_path_is_read_only(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    before = inventory.read_bytes()
    executable = tmp_path / "missing" / "codex"

    assert (
        main(
            [
                "resource",
                "discover",
                "codex-cli",
                "--executable",
                str(executable),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)

    assert result["profile_id"] == "codex"
    assert result["search_scope"] == "exact-path"
    assert result["installed"] is False
    assert result["version_probe_performed"] is False
    assert result["evidence"] == ["executable-not-located"]
    assert result["authentication_evaluated"] is False
    assert result["quota_evaluated"] is False
    assert result["availability_evaluated"] is False
    assert result["atready_network_accessed"] is False
    assert result["inventory_writes_performed"] is False
    assert result["external_process_executed"] is False
    assert result["external_process_side_effects"] == "not-applicable"
    assert inventory.read_bytes() == before

    assert (
        main(
            [
                "resource",
                "discover",
                "codex",
                "--executable",
                str(executable),
            ]
        )
        == 0
    )
    human = capsys.readouterr().out
    assert "Bounded local executable discovery (no inventory write)" in human
    assert "Authentication evaluated: false" in human
    assert "Quota evaluated: false" in human
    assert "Availability evaluated: false" in human
    assert "Inventory writes performed: false" in human
    assert "External process executed: false" in human
    assert "External process side effects: not-applicable" in human


@pytest.mark.skipif(os.name != "posix", reason="synthetic executable fixture uses POSIX mode bits")
def test_resource_discovery_reports_the_exact_coderabbit_alias(
    tmp_path: Path,
    capsys,
) -> None:
    executable = tmp_path / "cr"
    marker = tmp_path / "unexpected-execution"
    executable.write_text(
        f"#!/bin/sh\n: > '{marker}'\nprintf 'synthetic coderabbit\\n'\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)

    assert (
        main(
            [
                "resource",
                "discover",
                "coderabbit",
                "--executable",
                str(executable),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)

    assert result["profile_id"] == "coderabbit"
    assert result["executable_name"] == "cr"
    assert result["resolved_path"] == str(executable)
    assert result["external_process_executed"] is False
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="synthetic executable fixture uses POSIX mode bits")
def test_resource_discovery_finds_the_coderabbit_alias_on_current_path(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "cr"
    executable.write_text("#!/bin/sh\nprintf 'synthetic coderabbit\\n'\n", encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))

    assert main(["resource", "discover", "coderabbit", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["profile_id"] == "coderabbit"
    assert result["executable_name"] == "cr"
    assert result["resolved_path"] == str(executable)
    assert result["external_process_executed"] is False


@pytest.mark.skipif(os.name != "posix", reason="synthetic executable fixture uses POSIX mode bits")
def test_resource_discovery_only_probes_version_when_explicit(tmp_path: Path, capsys) -> None:
    executable = tmp_path / "codex"
    executable.write_text("#!/bin/sh\nprintf 'synthetic-codex 1.2.3\\n'\n", encoding="utf-8")
    executable.chmod(0o700)

    base_args = ["resource", "discover", "codex", "--executable", str(executable), "--json"]
    assert main(base_args) == 0
    unprobed = json.loads(capsys.readouterr().out)
    assert unprobed["installed"] is True
    assert unprobed["version_probe_performed"] is False
    assert unprobed["version"] is None
    assert unprobed["evidence"] == ["executable-located"]

    assert main([*base_args, "--inspect-version"]) == 0
    probed = json.loads(capsys.readouterr().out)
    assert probed["version_probe_performed"] is True
    assert probed["version"] == "synthetic-codex 1.2.3"
    assert probed["evidence"] == ["executable-located", "version-observed"]
    assert probed["external_process_executed"] is True
    assert probed["external_process_side_effects"] == "not-evaluated"


def test_resource_version_probe_requires_a_reviewed_absolute_path(capsys) -> None:
    assert main(["resource", "discover", "codex", "--inspect-version"]) == 2
    captured = capsys.readouterr()

    assert "requires an explicitly supplied absolute executable path" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    ("arguments", "message", "private_value"),
    [
        (
            ["resource", "profile", "missing-profile"],
            "not in the bundled catalog",
            "missing-profile",
        ),
        (
            [
                "resource",
                "discover",
                "codex",
                "--executable",
                "./private-relative-codex",
            ],
            "must be an absolute path",
            "private-relative-codex",
        ),
        (
            ["resource", "discover", "codex", "--executable", "private-codex-sentinel"],
            "must be an absolute path",
            "private-codex-sentinel",
        ),
        (
            [
                "resource",
                "discover",
                "codex",
                "--executable",
                str(Path.cwd() / "private-not-codex-sentinel"),
            ],
            "outside the profile allowlist",
            "private-not-codex-sentinel",
        ),
    ],
)
def test_resource_commands_reject_unknown_or_unsafe_inputs(
    capsys, arguments: list[str], message: str, private_value: str
) -> None:
    assert main(arguments) == 2
    captured = capsys.readouterr()
    assert message in captured.err
    assert private_value not in captured.out + captured.err


def test_resource_discovery_sanitizes_validation_failures(capsys) -> None:
    sentinel = "private-discovery-value-" + ("x" * 5_000)
    oversized_path = str(Path.cwd() / sentinel)

    assert main(["resource", "discover", "codex", "--executable", oversized_path]) == 2
    captured = capsys.readouterr()

    assert "outside the bounded input contract" in captured.err
    assert sentinel not in captured.out + captured.err


def test_inventory_add_rejects_duplicate_capability_flags(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "inventory",
                "add",
                "--path",
                str(inventory),
                "--id",
                "bad-tool",
                "--name",
                "Bad Tool",
                "--category",
                "tool",
                "--capability",
                "build=0.5",
                "--capability",
                "build=0.6",
            ]
        )
        == 2
    )
    assert "duplicate capability ID: build" in capsys.readouterr().err


def test_applied_but_uncertain_cli_receipt_uses_distinct_exit_code(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    args = _resource_add_args(inventory)
    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    real_release = inventory_edit._release_lock

    def release_then_report(descriptor: int, lock_path: Path) -> None:
        real_release(descriptor, lock_path)
        raise StorageError("synthetic cleanup uncertainty")

    monkeypatch.setattr(inventory_edit, "_release_lock", release_then_report)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 4
    )
    captured = capsys.readouterr()
    assert "Added resource" in captured.out
    assert "warning: synthetic cleanup uncertainty" in captured.err
    assert "update may already be applied; do not retry this apply" in captured.err


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory durability contract")
def test_add_post_replace_directory_sync_failure_uses_exit_four(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    args = _resource_add_args(inventory)
    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    calls = 0

    def fail_post_replace_sync(_path: Path) -> bool:
        nonlocal calls
        calls += 1
        return calls != 4

    monkeypatch.setattr(inventory_edit, "_fsync_directory", fail_post_replace_sync)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 4
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["applied"] is True
    assert receipt["replacement_verified"] is True
    assert receipt["directory_synced"] is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory durability contract")
def test_rollback_post_replace_directory_sync_failure_uses_exit_four(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    _, added = _preview_and_apply(_resource_add_args(inventory), capsys)
    args = [
        "inventory",
        "backup",
        "rollback",
        "--path",
        str(inventory),
        "--backup",
        added["backup_id"],
    ]
    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    calls = 0

    def fail_post_replace_sync(_path: Path) -> bool:
        nonlocal calls
        calls += 1
        return calls != 4

    monkeypatch.setattr(inventory_edit, "_fsync_directory", fail_post_replace_sync)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 4
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["applied"] is True
    assert receipt["replacement_verified"] is True
    assert receipt["directory_synced"] is False


def test_precommit_cleanup_failure_note_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    args = _resource_add_args(inventory)
    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    real_release = inventory_edit._release_lock

    def fail_before_write(_target: Path, _raw: bytes):
        raise StorageError("synthetic precommit failure")

    def release_then_report(descriptor: int, lock_path: Path) -> None:
        real_release(descriptor, lock_path)
        raise StorageError("synthetic sensitive cleanup failure")

    monkeypatch.setattr(inventory_edit, "_backup_current", fail_before_write)
    monkeypatch.setattr(inventory_edit, "_release_lock", release_then_report)
    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "error: synthetic precommit failure" in captured.err
    assert "note: synthetic sensitive cleanup failure" in captured.err


def test_empty_personal_and_demo_inventories_require_explicit_routes(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "private-home"
    monkeypatch.setenv("ATREADY_HOME", str(home))
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["project", "template"]) == 0
    project = tmp_path / "project.yaml"
    project.write_text(capsys.readouterr().out, encoding="utf-8")

    assert main(["route", "--project", str(project), "--format", "json"]) == 2
    assert "personal inventory has no resources" in capsys.readouterr().err

    demo_path = tmp_path / "demo.yaml"
    demo_path.write_text(demo_inventory(), encoding="utf-8")
    assert main(["route", "--project", str(project), "--inventory", str(demo_path)]) == 2
    assert "--allow-demo" in capsys.readouterr().err

    assert (
        main(
            [
                "route",
                "--project",
                str(project),
                "--inventory",
                str(demo_path),
                "--allow-demo",
                "--format",
                "json",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["warnings"][0].startswith("[demo-inventory]")


def test_demo_command_is_read_only_and_marks_synthetic_data(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "private-home"
    monkeypatch.setenv("ATREADY_HOME", str(home))

    assert main(["demo", "inventory", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["inventory_kind"] == "demo"
    assert len(payload["resources"]) == 3
    assert not home.exists()


def test_backup_cli_lists_inspects_and_rolls_back_without_exposing_private_notes(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    sentinel = "CLI-PRIVATE-NOTE-MUST-STAY-HIDDEN"
    initial = starter_inventory().replace(
        "resources: []", f"private_notes: {sentinel}\nresources: []"
    )
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text(initial, encoding="utf-8")
    if os.name == "posix":
        inventory.chmod(0o600)
    original = inventory.read_bytes()
    _, add_receipt = _preview_and_apply(_resource_add_args(inventory), capsys)
    active_after_add = inventory.read_bytes()

    assert (
        main(
            [
                "inventory",
                "backup",
                "list",
                "--path",
                str(inventory),
                "--json",
            ]
        )
        == 0
    )
    listing_text = capsys.readouterr().out
    listing = json.loads(listing_text)
    assert sentinel not in listing_text
    assert listing["backup_count"] == 1
    assert listing["backups"][0]["backup_id"] == add_receipt["backup_id"]
    assert listing["backups"][0]["filesystem_modified_at_is_history"] is False

    assert (
        main(
            [
                "inventory",
                "backup",
                "inspect",
                "--path",
                str(inventory),
                "--backup",
                add_receipt["backup_id"],
                "--json",
            ]
        )
        == 0
    )
    inspection_text = capsys.readouterr().out
    inspection = json.loads(inspection_text)
    assert sentinel not in inspection_text
    assert inspection["private_notes_exposed"] is False
    assert inspection["comparison"]["resource_changes"]["removed"] == ["local-coding-agent"]

    rollback_args = [
        "inventory",
        "backup",
        "rollback",
        "--path",
        str(inventory),
        "--backup",
        add_receipt["backup_id"],
    ]
    preview, rollback_receipt = _preview_and_apply(rollback_args, capsys)

    assert sentinel not in repr(preview)
    assert preview["canonicalizes_yaml"] is False
    assert preview["safety_backup_on_apply"] is True
    assert inventory.read_bytes() == original
    assert rollback_receipt["source_backup_id"] == add_receipt["backup_id"]
    assert Path(rollback_receipt["source_backup_path"]).read_bytes() == original
    assert Path(rollback_receipt["safety_backup_path"]).read_bytes() == active_after_add


def test_backup_recover_cli_handles_invalid_active_with_redacted_preview(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    original = inventory.read_bytes()
    _, added = _preview_and_apply(_resource_add_args(inventory), capsys)
    corrupt_sentinel = "SYNTHETIC-CORRUPT-CLI-SENTINEL"
    corrupt = f"invalid: [\n{corrupt_sentinel}\n".encode()
    inventory.write_bytes(corrupt)

    assert (
        main(
            [
                "inventory",
                "backup",
                "list",
                "--path",
                str(inventory),
                "--json",
            ]
        )
        == 0
    )
    listing = json.loads(capsys.readouterr().out)
    assert listing["active_state"] == "invalid"
    assert listing["active_revision"] is None

    args = [
        "inventory",
        "backup",
        "recover",
        "--path",
        str(inventory),
        "--backup",
        added["backup_id"],
    ]
    assert main([*args, "--json"]) == 0
    captured = capsys.readouterr()
    assert corrupt_sentinel not in captured.out + captured.err
    preview = json.loads(captured.out)
    assert preview["expect_state"] == "invalid"

    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-state",
                preview["expect_state"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert corrupt_sentinel not in captured.out + captured.err
    receipt = json.loads(captured.out)
    assert receipt["replacement_verified"] is True
    assert receipt["previous_state"] == "invalid"
    assert receipt["quarantine_path"] is not None
    assert Path(receipt["quarantine_path"]).read_bytes() == corrupt
    assert inventory.read_bytes() == original


def test_backup_recover_cli_requires_separate_state_and_plan_tokens(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    _, added = _preview_and_apply(_resource_add_args(inventory), capsys)
    inventory.unlink()
    args = [
        "inventory",
        "backup",
        "recover",
        "--path",
        str(inventory),
        "--backup",
        added["backup_id"],
    ]

    assert main([*args, "--apply", "--json"]) == 2
    assert "--expect-state and --expect-plan" in capsys.readouterr().err


def test_backup_delete_cli_requires_preview_and_explicit_last_backup_override(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    _, first = _preview_and_apply(_resource_add_args(inventory, resource_id="one"), capsys)
    _, second = _preview_and_apply(_resource_add_args(inventory, resource_id="two"), capsys)
    active = inventory.read_bytes()
    delete_first = [
        "inventory",
        "backup",
        "delete",
        "--path",
        str(inventory),
        "--backup",
        first["backup_id"],
    ]

    assert main([*delete_first, "--apply", "--json"]) == 2
    assert "prior backup deletion preview" in capsys.readouterr().err
    preview, deleted = _preview_and_apply(delete_first, capsys)
    assert preview["irreversible"] is True
    assert deleted["deletion_verified"] is True
    assert inventory.read_bytes() == active
    assert not Path(first["backup_path"]).exists()
    assert Path(second["backup_path"]).exists()

    delete_last = [
        "inventory",
        "backup",
        "delete",
        "--path",
        str(inventory),
        "--backup",
        second["backup_id"],
    ]
    assert main([*delete_last, "--json"]) == 2
    assert "requires --allow-no-backups" in capsys.readouterr().err
    _, last_deleted = _preview_and_apply([*delete_last, "--allow-no-backups"], capsys)
    assert last_deleted["remaining_valid_backups"] == 0
    assert inventory.read_bytes() == active


def test_backup_rollback_cli_enforces_apply_tokens(tmp_path: Path, capsys) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    _, added = _preview_and_apply(_resource_add_args(inventory), capsys)
    args = [
        "inventory",
        "backup",
        "rollback",
        "--path",
        str(inventory),
        "--backup",
        added["backup_id"],
    ]
    assert main([*args, "--apply", "--json"]) == 2
    assert "prior rollback preview" in capsys.readouterr().err
    assert main([*args, "--expect-plan", "sha256:wrong", "--json"]) == 2
    assert "only valid with --apply" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="POSIX delete durability contract")
def test_backup_delete_cli_uses_exit_four_after_unlink_sync_uncertainty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    _, added = _preview_and_apply(_resource_add_args(inventory), capsys)
    args = [
        "inventory",
        "backup",
        "delete",
        "--path",
        str(inventory),
        "--backup",
        added["backup_id"],
        "--allow-no-backups",
    ]
    assert main([*args, "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(inventory_edit, "_fsync_directory", lambda _path: False)

    assert (
        main(
            [
                *args,
                "--apply",
                "--expect-revision",
                preview["expect_revision"],
                "--expect-plan",
                preview["expect_plan"],
                "--json",
            ]
        )
        == 4
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["applied"] is True
    assert receipt["deletion_verified"] is True
    assert receipt["directory_synced"] is False
    assert not Path(added["backup_path"]).exists()


def test_human_backup_lifecycle_output_labels_sources_and_irreversible_steps(
    tmp_path: Path, capsys
) -> None:
    inventory = tmp_path / "inventory.yaml"
    assert main(["init", "--path", str(inventory)]) == 0
    capsys.readouterr()
    sentinel = "HUMAN-BACKUP-OUTPUT-MUST-NOT-EXPOSE-THIS"
    inventory.write_text(
        starter_inventory().replace("resources: []", f"private_notes: {sentinel}\nresources: []"),
        encoding="utf-8",
    )
    if os.name == "posix":
        inventory.chmod(0o600)
    _, added = _preview_and_apply(_resource_add_args(inventory), capsys)

    assert main(["inventory", "backup", "list", "--path", str(inventory)]) == 0
    listing_output = capsys.readouterr().out
    assert "Validated backups: 1" in listing_output
    assert "not backup history" in listing_output

    assert (
        main(
            [
                "inventory",
                "backup",
                "inspect",
                "--path",
                str(inventory),
                "--backup",
                added["backup_id"],
            ]
        )
        == 0
    )
    inspection_output = capsys.readouterr().out
    assert "private notes omitted" in inspection_output
    assert "Sanitized comparison:" in inspection_output
    assert "Sanitized active snapshot:" in inspection_output
    assert "Sanitized backup snapshot:" in inspection_output
    assert "code-implementation" in inspection_output
    assert sentinel not in inspection_output

    rollback_args = [
        "inventory",
        "backup",
        "rollback",
        "--path",
        str(inventory),
        "--backup",
        added["backup_id"],
    ]
    assert main(rollback_args) == 0
    rollback_preview_output = capsys.readouterr().out
    assert "rollback preview (no files changed)" in rollback_preview_output
    assert "Hidden private notes will be restored exactly" in rollback_preview_output
    assert "Sanitized active snapshot:" in rollback_preview_output
    assert "Sanitized rollback candidate snapshot:" in rollback_preview_output
    assert "code-implementation" in rollback_preview_output
    assert sentinel not in rollback_preview_output
    assert main([*rollback_args, "--json"]) == 0
    rollback_preview = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                *rollback_args,
                "--apply",
                "--expect-revision",
                rollback_preview["expect_revision"],
                "--expect-plan",
                rollback_preview["expect_plan"],
            ]
        )
        == 0
    )
    rollback_output = capsys.readouterr().out
    assert "Source backup retained:" in rollback_output
    assert "Safety backup ID:" in rollback_output

    assert (
        main(
            [
                "inventory",
                "backup",
                "list",
                "--path",
                str(inventory),
                "--json",
            ]
        )
        == 0
    )
    backups = json.loads(capsys.readouterr().out)["backups"]
    deletion_id = next(
        backup["backup_id"] for backup in backups if backup["backup_id"] != added["backup_id"]
    )
    delete_args = [
        "inventory",
        "backup",
        "delete",
        "--path",
        str(inventory),
        "--backup",
        deletion_id,
    ]
    assert main(delete_args) == 0
    delete_preview_output = capsys.readouterr().out
    assert "deletion preview (no files changed)" in delete_preview_output
    assert "This deletion is irreversible" in delete_preview_output
    assert main([*delete_args, "--json"]) == 0
    delete_preview = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                *delete_args,
                "--apply",
                "--expect-revision",
                delete_preview["expect_revision"],
                "--expect-plan",
                delete_preview["expect_plan"],
            ]
        )
        == 0
    )
    delete_output = capsys.readouterr().out
    assert "Deleted backup" in delete_output
    assert "Remaining validated backups: 1" in delete_output
