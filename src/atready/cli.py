"""Dependency-light command-line interface for private inventory operations."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Sequence
from datetime import date, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from unicodedata import category as unicode_category

from atready import __version__
from atready.catalog import InventoryCatalog
from atready.comparison import compare_routes, render_route_comparison
from atready.errors import AtReadyError, ConfigurationError
from atready.intake import (
    IntakeError,
    LocalDiscoveryRequest,
    discover_local_resource,
    resource_profile,
    resource_profiles,
)
from atready.inventory_edit import (
    commit_add_resource,
    commit_inventory_annotation,
    commit_inventory_backup_delete,
    commit_inventory_recovery,
    commit_inventory_rollback,
    commit_remove_resource,
    commit_replace_resource,
    inspect_inventory_backup,
    inspect_inventory_backup_manifest,
    list_inventory_backups,
    plan_add_resource,
    plan_inventory_annotation,
    plan_inventory_backup_delete,
    plan_inventory_recovery,
    plan_inventory_rollback,
    plan_remove_resource,
    plan_replace_resource,
    read_inventory_file,
)
from atready.models import (
    AccessStatus,
    BillingModel,
    ConfidenceBasis,
    DataClass,
    HandoffMethod,
    InteractionMode,
    Inventory,
    InventoryAnnotationDeclaration,
    InventoryKind,
    ProjectBrief,
    QuotaStatus,
    ResourceDeclaration,
    SessionAvailability,
)
from atready.paths import create_private_file, resolve_paths
from atready.project import project_from_path, project_from_text
from atready.quick_setup import (
    load_quick_setup_facts_stdin,
    quick_setup_mapping_summary,
    resource_from_quick_setup,
)
from atready.render import (
    render_agent_presentation,
    render_agent_summary,
    render_markdown,
    render_summary,
)
from atready.resource_input import (
    ParsedResourceDeclaration,
    load_inventory_annotation_declaration_file,
    load_inventory_annotation_declaration_stdin,
    load_resource_declaration_file,
    load_resource_declaration_stdin,
    parse_resource_mapping,
    resource_intake_review,
)
from atready.resource_state import ResourceStateCollection, resource_state_from_path
from atready.routing import route
from atready.runtime_contract import doctor_payload, runtime_contract_payload
from atready.templates import demo_inventory, starter_inventory, starter_project
from atready.yamlio import dumps_yaml

_MAX_CAPACITY_NUMBER_CHARACTERS = 64
_MAX_GUIDED_INPUT_CHARACTERS = 512
_RUNTIME_FEATURE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_RESOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_PLUGIN_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,63}$")
_DATA_SENSITIVITY_LADDER: tuple[DataClass, ...] = (
    DataClass.PUBLIC,
    DataClass.INTERNAL,
    DataClass.PRIVATE,
    DataClass.SENSITIVE,
)
_GUIDED_STRENGTHS = {
    "basic": 0.40,
    "solid": 0.65,
    "strong": 0.80,
    "exceptional": 0.95,
}
if len(_DATA_SENSITIVITY_LADDER) != len(set(_DATA_SENSITIVITY_LADDER)) or set(
    _DATA_SENSITIVITY_LADDER
) != set(DataClass):
    raise RuntimeError("guided data-sensitivity ladder must contain every DataClass exactly once")

_BLOCK_GLYPHS = {
    "A": (" ▉▉▉▉ ", "▉▉  ▉▉", "▉▉▉▉▉▉", "▉▉  ▉▉", "▉▉  ▉▉"),
    "T": ("▉▉▉▉▉▉", "  ▉▉  ", "  ▉▉  ", "  ▉▉  ", "  ▉▉  "),
    "R": ("▉▉▉▉▉ ", "▉▉  ▉▉", "▉▉▉▉▉ ", "▉▉ ▉▉ ", "▉▉  ▉▉"),
    "E": ("▉▉▉▉▉▉", "▉▉    ", "▉▉▉▉▉ ", "▉▉    ", "▉▉▉▉▉▉"),
    "D": ("▉▉▉▉▉ ", "▉▉  ▉▉", "▉▉  ▉▉", "▉▉  ▉▉", "▉▉▉▉▉ "),
    "Y": ("▉▉  ▉▉", " ▉▉ ▉▉", "  ▉▉  ", "  ▉▉  ", "  ▉▉  "),
}
_WORDMARK = tuple(" ".join(_BLOCK_GLYPHS[letter][row] for letter in "ATREADY") for row in range(5))
_TOOLBOX = (
    "      ▉▉▉▉▉▉▉▉      ",
    "     ▉▉      ▉▉     ",
    "  ▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉  ",
    "  ▉▉  TOOL KIT  ▉▉  ",
    "  ▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉  ",
)
_GRADIENT_STOPS = ((24, 76, 174), (124, 82, 184), (224, 65, 55))


class _AtReadyArgumentParser(argparse.ArgumentParser):
    """Keep first-contact help short while retaining normal nested help."""

    def format_help(self) -> str:
        if self.prog != "atready":
            return super().format_help()
        return """usage: atready [--version] <command> ...

Show where your resources fit a project plan.

Get started:
  init      Create your local resource roster
  add       Add one resource with guided, preview-first setup
  plan      Check resource fit through a guided conversation
  demo      Run a complete synthetic resource fit example

Manage:
  inventory Inspect or maintain your roster
  project   Create or validate a project brief
  route     Match an existing project brief to your roster
  compare   Show what changes between two resource-fit routes

More:
  welcome              Show the AtReady welcome screen
  help planning        Learn the beginner resource fit workflow
  help resources       Learn the resource workflow
  help automation      Learn the scriptable workflow
  help --all           See every top-level command

Advanced command names:
  doctor  runtime  config  resource  state  skill  schema

options:
  -h, --help  show this help message and exit
  --version   show the installed version and exit
"""


def _gradient_rgb(position: int, maximum: int) -> tuple[int, int, int]:
    ratio = position / maximum if maximum else 0.0
    segment = min(int(ratio * (len(_GRADIENT_STOPS) - 1)), len(_GRADIENT_STOPS) - 2)
    local = ratio * (len(_GRADIENT_STOPS) - 1) - segment
    start = _GRADIENT_STOPS[segment]
    end = _GRADIENT_STOPS[segment + 1]
    return tuple(round(a + (b - a) * local) for a, b in zip(start, end, strict=True))


def _colorize_banner_line(value: str) -> str:
    last = max(len(value) - 1, 1)
    output: list[str] = []
    active: tuple[int, int, int] | None = None
    for index, character in enumerate(value):
        if character == " ":
            output.append(character)
            continue
        rgb = _gradient_rgb(index, last)
        if rgb != active:
            output.append(f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m")
            active = rgb
        output.append(character)
    if active is not None:
        output.append("\033[0m")
    return "".join(output)


def _shadowed_art(lines: tuple[str, ...]) -> tuple[str, ...]:
    width = max(len(line) for line in lines) + 1
    canvas = [[" "] * width for _ in range(len(lines) + 1)]
    for column, character in enumerate(lines[-1]):
        if character == "▉":
            canvas[-1][column + 1] = "#"
    for row, line in enumerate(lines):
        for column, character in enumerate(line):
            if character != " ":
                canvas[row][column] = character
    return tuple("".join(line).rstrip() for line in canvas)


def _welcome_text(*, color: bool, block_art: bool) -> str:
    if block_art:
        wordmark_lines = _shadowed_art(_WORDMARK)
        toolbox_lines = _shadowed_art(_TOOLBOX)
    else:
        wordmark_lines = tuple(line.replace("▉", "#") for line in _WORDMARK)
        toolbox_lines = tuple(line.replace("▉", "#") for line in _TOOLBOX)
    wordmark_width = max(len(line) for line in wordmark_lines)
    banner = [
        f"{wordmark:<{wordmark_width}}  {toolbox}"
        for wordmark, toolbox in zip(wordmark_lines, toolbox_lines, strict=True)
    ]
    if color:
        banner = [_colorize_banner_line(line) for line in banner]
    return "\n".join(
        [
            *banner,
            "",
            "Plan with what you have at the ready.",
            "",
            "Turn a rough plan and your available tools into a clear workstream route.",
            "AtReady suggests where each resource fits and what should stay out.",
            "It never runs a tool, spends a credit, or starts the work.",
            "",
            "A resource is a tool, agent, service, app, or person AtReady may consider.",
            "",
            "GET STARTED",
            "  Create your roster  atready init",
            "  Add a resource      atready add",
            "  Try the safe demo   atready demo",
            "  See every command   atready --help",
        ]
    )


def _handle_welcome(args: argparse.Namespace) -> int:
    color_mode = getattr(args, "color", "auto")
    use_color = color_mode == "always" or (
        color_mode == "auto"
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
        and sys.stdout.isatty()
    )
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "▉".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        block_art = False
    else:
        block_art = True
    print(_welcome_text(color=use_color, block_art=block_art))
    return 0


def _plugin_version(value: str) -> str:
    if _PLUGIN_VERSION_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("plugin version must be a bounded ASCII token")
    return value


def _runtime_contract_version(value: str) -> int:
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("plugin contract must be a positive integer") from None
    if parsed < 1 or str(parsed) != value:
        raise argparse.ArgumentTypeError("plugin contract must be a positive integer")
    return parsed


def _runtime_feature_id(value: str) -> str:
    if len(value) > 100 or _RUNTIME_FEATURE_ID.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("required feature must be a bounded feature ID")
    return value


def _resource_id(value: str) -> str:
    if _RESOURCE_ID.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("resource ID must be a 1-64 character lowercase ID")
    return value


def _unit_score(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a number from 0.0 to 1.0") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("expected a number from 0.0 to 1.0")
    return parsed


def _configure_resource_declaration_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", type=Path, help="Defaults to user config")
    parser.add_argument(
        "--resource-file",
        type=Path,
        help=(
            "Read one protected versioned YAML/JSON declaration file; POSIX mode must be 0600 "
            "and the pathname remains visible in argv"
        ),
    )
    parser.add_argument(
        "--resource-stdin",
        action="store_true",
        help=(
            "Read one versioned YAML/JSON declaration from non-interactive stdin without "
            "placing its contents in argv"
        ),
    )
    parser.add_argument("--id", help="Typed mode; value is visible in argv")
    parser.add_argument("--name", help="Typed mode; value is visible in argv")
    parser.add_argument(
        "--category", action="append", help="Typed mode; repeat; value is visible in argv"
    )
    parser.add_argument(
        "--capability", action="append", metavar="ID=SCORE", help="Repeat for each capability"
    )
    parser.add_argument("--access", choices=_enum_values(AccessStatus))
    parser.add_argument("--interaction", choices=_enum_values(InteractionMode))
    parser.add_argument("--session", choices=_enum_values(SessionAvailability))
    parser.add_argument("--billing", choices=_enum_values(BillingModel))
    parser.add_argument("--marginal-cost", type=float)
    parser.add_argument("--quota", choices=_enum_values(QuotaStatus))
    parser.add_argument("--capacity-unit")
    parser.add_argument("--capacity-remaining", type=_capacity_number)
    parser.add_argument("--capacity-limit", type=_capacity_number)
    parser.add_argument("--capacity-project-limit", type=_capacity_number)
    parser.add_argument("--capacity-resets-on", type=_date_value, metavar="YYYY-MM-DD")
    parser.add_argument("--capacity-basis", choices=_enum_values(ConfidenceBasis))
    parser.add_argument("--capacity-verified-on", type=_date_value, metavar="YYYY-MM-DD")
    parser.add_argument("--rating", action="append", metavar="NAME=SCORE")
    parser.add_argument("--allowed-data-class", action="append", choices=_enum_values(DataClass))
    parser.add_argument("--approval-required", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--requires-network", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--confidence-basis", choices=_enum_values(ConfidenceBasis))
    parser.add_argument("--verified-on", type=_date_value, metavar="YYYY-MM-DD")
    parser.add_argument("--handoff-method", choices=_enum_values(HandoffMethod))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-revision")
    parser.add_argument("--expect-plan")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")


def _configure_annotation_mutation_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", type=Path, help="Defaults to user config")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-revision")
    parser.add_argument("--expect-plan")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")


def build_parser() -> argparse.ArgumentParser:
    parser = _AtReadyArgumentParser(
        prog="atready",
        description="Show where your resources fit a project plan.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.set_defaults(handler=_handle_welcome, color="auto")
    commands = parser.add_subparsers(dest="command")

    welcome_parser = commands.add_parser("welcome", help="Show the AtReady welcome screen")
    welcome_parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Color mode for the welcome wordmark",
    )
    welcome_parser.set_defaults(handler=_handle_welcome)

    guided_add_parser = commands.add_parser(
        "add",
        help="Add one resource with guided, preview-first setup",
        description=(
            "Add one resource to your local inventory. AtReady asks for planning facts, shows "
            "a no-write preview, then asks separately before saving. It does not scan your "
            "computer, inspect an account, contact the resource, or run it."
        ),
    )
    guided_add_parser.add_argument(
        "--path", type=Path, help="Inventory path; defaults to user config"
    )
    guided_add_parser.add_argument(
        "--profile", help="Optional exact bundled profile ID or alias to start from"
    )
    guided_add_parser.set_defaults(handler=_handle_guided_add)

    guided_plan_parser = commands.add_parser(
        "plan",
        help="Check resource fit through a guided conversation",
        description=(
            "Match a goal and one to three existing plan steps to your declared roster. AtReady "
            "does not create the complete project plan, write a project file, contact a resource, "
            "or run any work."
        ),
    )
    guided_plan_parser.add_argument(
        "--inventory", type=Path, help="Inventory path; defaults to user config"
    )
    guided_plan_parser.add_argument(
        "--mode",
        choices=("quick", "detailed"),
        default="quick",
        help=(
            "quick checks one work item with standard eligibility; detailed collects full controls"
        ),
    )
    guided_plan_parser.add_argument(
        "--format",
        choices=("summary", "markdown"),
        default="summary",
        help="summary is concise; markdown includes scores and complete inert handoffs",
    )
    guided_plan_parser.add_argument(
        "--width",
        type=_summary_width,
        help="Wrap summary text to 40-120 columns (default: 80)",
    )
    guided_plan_parser.add_argument(
        "--allow-demo", action="store_true", help="Explicitly permit synthetic demo resources"
    )
    guided_plan_parser.set_defaults(handler=_handle_guided_plan)

    doctor_parser = commands.add_parser(
        "doctor",
        help="Report local runtime compatibility without reading inventory or changing anything",
        description=(
            "Report the value-free plugin/runtime compatibility contract. This command does not "
            "read inventory, access the network, or write files."
        ),
    )
    doctor_parser.add_argument(
        "--plugin-version",
        type=_plugin_version,
        help="Plugin product version to include in diagnostics; it is not equality-enforced",
    )
    doctor_parser.add_argument(
        "--plugin-contract",
        type=_runtime_contract_version,
        help="Runtime contract version required by the plugin",
    )
    doctor_parser.add_argument(
        "--require-feature",
        action="append",
        default=[],
        type=_runtime_feature_id,
        help="Required runtime feature ID; repeat for each required feature",
    )
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    doctor_parser.set_defaults(handler=_handle_doctor)

    runtime_parser = commands.add_parser(
        "runtime", help="Inspect the value-free local runtime contract"
    )
    runtime_commands = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_contract_parser = runtime_commands.add_parser(
        "contract", help="Report the canonical plugin/runtime compatibility contract"
    )
    runtime_contract_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable output"
    )
    runtime_contract_parser.set_defaults(handler=_handle_runtime_contract)

    init_parser = commands.add_parser(
        "init",
        help="Create an empty private personal inventory",
        description=(
            "Create an empty personal inventory with a fresh 256-bit revision privacy nonce. "
            "The nonce value is written only inside the inventory and is never printed."
        ),
    )
    init_parser.add_argument("--path", type=Path, help="Inventory path; defaults to user config")
    init_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    init_parser.set_defaults(handler=_handle_init)

    demo_parser = commands.add_parser(
        "demo",
        help="Run a complete synthetic resource fit example",
        description=(
            "Run the bundled synthetic inventory and project entirely in memory. "
            "No files are written and no resources are contacted or run."
        ),
    )
    demo_parser.set_defaults(handler=_handle_demo_route)
    demo_commands = demo_parser.add_subparsers(dest="demo_command")
    demo_inventory_parser = demo_commands.add_parser(
        "inventory", help="Print the bundled synthetic inventory without writing it"
    )
    demo_inventory_parser.add_argument("--format", choices=("yaml", "json"), default="yaml")
    demo_inventory_parser.set_defaults(handler=_handle_demo_inventory)

    config_parser = commands.add_parser("config", help="Inspect resolved local paths")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    path_parser = config_commands.add_parser("path", help="Print the default inventory path")
    path_parser.add_argument("--json", action="store_true", help="Emit all resolved paths as JSON")
    path_parser.set_defaults(handler=_handle_config_path)

    resource_parser = commands.add_parser(
        "resource",
        help="Inspect the bundled resource proposal catalog or run bounded local discovery",
    )
    resource_commands = resource_parser.add_subparsers(dest="resource_command", required=True)
    profiles_parser = resource_commands.add_parser(
        "profiles",
        help="List bundled catalog proposals without inspecting local resources",
    )
    profiles_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    profiles_parser.set_defaults(handler=_handle_resource_profiles)
    profile_parser = resource_commands.add_parser(
        "profile",
        help="Show one bundled catalog proposal without inspecting a resource or account",
    )
    profile_parser.add_argument("profile", help="Exact profile ID or bundled alias")
    profile_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    profile_parser.set_defaults(handler=_handle_resource_profile)
    quick_add_parser = resource_commands.add_parser(
        "quick-add",
        help="Preview or apply one approved Quick Setup fact set",
        description=(
            "Read one strict, versioned JSON Quick Setup fact set from non-interactive stdin, "
            "map it through one bundled profile, and delegate to the existing inventory-add "
            "preview/apply contract. This does not inspect providers or accounts, contact the "
            "resource, or run it. Custom resources require detailed inventory add setup."
        ),
    )
    quick_add_parser.add_argument("--path", type=Path, help="Defaults to user config")
    quick_add_parser.add_argument(
        "--facts-stdin",
        action="store_true",
        required=True,
        help=(
            "Read exactly schema_version, name, strength, available_now, and private_work "
            "from the first bounded, newline-terminated JSON line on non-interactive stdin"
        ),
    )
    quick_add_parser.add_argument("--apply", action="store_true")
    quick_add_parser.add_argument("--expect-revision")
    quick_add_parser.add_argument("--expect-plan")
    quick_add_parser.add_argument("--json", action="store_true", help="Emit orchestration JSON")
    quick_add_parser.set_defaults(handler=_handle_resource_quick_add)
    discover_parser = resource_commands.add_parser(
        "discover",
        help="Locate an executable; optional version execution has unknown external side effects",
    )
    discover_parser.add_argument("profile", help="Exact profile ID or bundled alias")
    discover_parser.add_argument(
        "--executable",
        help="Optional exact absolute path to the profile's allowlisted executable",
    )
    discover_parser.add_argument(
        "--inspect-version",
        action="store_true",
        help="Run the fixed version probe for the reviewed --executable absolute path",
    )
    discover_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    discover_parser.set_defaults(handler=_handle_resource_discover)

    inventory_parser = commands.add_parser(
        "inventory", help="Inspect and manage an inventory and its recovery backups"
    )
    inventory_commands = inventory_parser.add_subparsers(dest="inventory_command", required=True)

    validate_parser = inventory_commands.add_parser("validate", help="Validate an inventory")
    validate_parser.add_argument("path", nargs="?", type=Path, help="Defaults to user config")
    validate_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    validate_parser.add_argument(
        "--strict", action="store_true", help="Treat staleness and unknown-state warnings as errors"
    )
    validate_parser.set_defaults(handler=_handle_inventory_validate)

    snapshot_parser = inventory_commands.add_parser(
        "snapshot",
        help="Emit routing fields while omitting private notes and the revision privacy nonce",
    )
    snapshot_parser.add_argument("path", nargs="?", type=Path, help="Defaults to user config")
    snapshot_parser.add_argument("--format", choices=("json", "yaml"), default="json")
    snapshot_parser.set_defaults(handler=_handle_inventory_snapshot)

    list_parser = inventory_commands.add_parser(
        "list", help="List routing-safe resource summaries and the exact file revision"
    )
    list_parser.add_argument("path", nargs="?", type=Path, help="Defaults to user config")
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    list_parser.set_defaults(handler=_handle_inventory_list)

    add_parser = inventory_commands.add_parser(
        "add",
        help="Preview or apply one typed or argv-safe resource addition",
        description=(
            "Preview or apply one resource addition. Choose typed flags, --resource-file, or "
            "--resource-stdin. Typed mode requires --id, --name, one or more --category, and "
            "one or more --capability. Structured input keeps declaration contents out of "
            "process arguments, but routing-visible preview output can still be retained by "
            "the terminal, invoking host, logs, or model context. Private notes require an "
            "inventory created with the current init command."
        ),
    )
    add_parser.add_argument("--path", type=Path, help="Defaults to user config")
    add_parser.add_argument(
        "--resource-file",
        type=Path,
        help=(
            "Read one protected versioned YAML/JSON declaration file; POSIX mode must be 0600 "
            "and the pathname remains visible in argv"
        ),
    )
    add_parser.add_argument(
        "--resource-stdin",
        action="store_true",
        help=(
            "Read one versioned YAML/JSON declaration from non-interactive stdin without "
            "placing its contents in argv"
        ),
    )
    add_parser.add_argument("--id", help="Typed mode; value is visible in argv")
    add_parser.add_argument("--name", help="Typed mode; value is visible in argv")
    add_parser.add_argument(
        "--category", action="append", help="Typed mode; repeat; value is visible in argv"
    )
    add_parser.add_argument(
        "--capability",
        action="append",
        metavar="ID=SCORE",
        help="Repeat for each declared capability",
    )
    add_parser.add_argument("--access", choices=_enum_values(AccessStatus))
    add_parser.add_argument("--interaction", choices=_enum_values(InteractionMode))
    add_parser.add_argument("--session", choices=_enum_values(SessionAvailability))
    add_parser.add_argument("--billing", choices=_enum_values(BillingModel))
    add_parser.add_argument("--marginal-cost", type=float)
    add_parser.add_argument("--quota", choices=_enum_values(QuotaStatus))
    add_parser.add_argument("--capacity-unit")
    add_parser.add_argument("--capacity-remaining", type=_capacity_number)
    add_parser.add_argument("--capacity-limit", type=_capacity_number)
    add_parser.add_argument("--capacity-project-limit", type=_capacity_number)
    add_parser.add_argument("--capacity-resets-on", type=_date_value, metavar="YYYY-MM-DD")
    add_parser.add_argument("--capacity-basis", choices=_enum_values(ConfidenceBasis))
    add_parser.add_argument("--capacity-verified-on", type=_date_value, metavar="YYYY-MM-DD")
    add_parser.add_argument(
        "--rating",
        action="append",
        metavar="NAME=SCORE",
        help="Repeat for quality, speed, autonomy, privacy, reliability, confidence, "
        "context-switch-cost, or integration-friction",
    )
    add_parser.add_argument(
        "--allowed-data-class", action="append", choices=_enum_values(DataClass)
    )
    add_parser.add_argument(
        "--approval-required", action=argparse.BooleanOptionalAction, default=None
    )
    add_parser.add_argument(
        "--requires-network", action=argparse.BooleanOptionalAction, default=None
    )
    add_parser.add_argument("--confidence-basis", choices=_enum_values(ConfidenceBasis))
    add_parser.add_argument("--verified-on", type=_date_value, metavar="YYYY-MM-DD")
    add_parser.add_argument("--handoff-method", choices=_enum_values(HandoffMethod))
    add_parser.add_argument("--apply", action="store_true", help="Apply the previewed addition")
    add_parser.add_argument(
        "--expect-revision",
        help="Exact sha256 revision printed by the preview; required with --apply",
    )
    add_parser.add_argument(
        "--expect-plan",
        help=(
            "Plan token binding the previewed operation, target, and candidate; "
            "required with --apply"
        ),
    )
    add_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    add_parser.set_defaults(handler=_handle_inventory_add)

    replace_parser = inventory_commands.add_parser(
        "replace",
        help="Preview or apply full replacement of one existing resource",
        description=(
            "Replace the existing resource whose ID matches the complete typed or structured "
            "declaration. Omitted fields take declared defaults; omitted private notes are removed."
        ),
    )
    _configure_resource_declaration_parser(replace_parser)
    replace_parser.add_argument(
        "--details",
        action="store_true",
        help="Show complete sanitized before/after snapshots and technical evidence",
    )
    replace_parser.set_defaults(handler=_handle_inventory_replace)

    remove_parser = inventory_commands.add_parser(
        "remove", help="Preview or apply removal of one exact resource ID"
    )
    remove_parser.add_argument("--path", type=Path, help="Defaults to user config")
    remove_parser.add_argument("--resource", required=True, help="Exact resource ID to remove")
    remove_parser.add_argument("--apply", action="store_true")
    remove_parser.add_argument("--expect-revision")
    remove_parser.add_argument("--expect-plan")
    remove_parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    remove_parser.add_argument(
        "--details",
        action="store_true",
        help="Show the complete sanitized resource and technical evidence",
    )
    remove_parser.set_defaults(handler=_handle_inventory_remove)

    annotate_parser = inventory_commands.add_parser(
        "annotate", help="Preview or apply a protected root private-note set or clear"
    )
    annotate_commands = annotate_parser.add_subparsers(dest="annotation_command", required=True)
    annotate_set_parser = annotate_commands.add_parser(
        "set", help="Set root private notes from one protected declaration"
    )
    _configure_annotation_mutation_parser(annotate_set_parser)
    annotation_input = annotate_set_parser.add_mutually_exclusive_group(required=True)
    annotation_input.add_argument(
        "--annotation-file",
        type=Path,
        help="Read a protected versioned declaration file; POSIX mode must be 0600",
    )
    annotation_input.add_argument(
        "--annotation-stdin",
        action="store_true",
        help="Read a versioned declaration from non-interactive stdin",
    )
    annotate_set_parser.set_defaults(handler=_handle_inventory_annotation_set)

    annotate_clear_parser = annotate_commands.add_parser(
        "clear", help="Remove the root private notes without accepting a value"
    )
    _configure_annotation_mutation_parser(annotate_clear_parser)
    annotate_clear_parser.set_defaults(handler=_handle_inventory_annotation_clear)

    backup_parser = inventory_commands.add_parser(
        "backup", help="Inspect, roll back, or explicitly delete exact inventory backups"
    )
    backup_commands = backup_parser.add_subparsers(dest="backup_command", required=True)

    backup_list_parser = backup_commands.add_parser(
        "list", help="List validated backups for one exact inventory target"
    )
    backup_list_parser.add_argument("--path", type=Path, help="Defaults to user config")
    backup_list_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable output"
    )
    backup_list_parser.set_defaults(handler=_handle_inventory_backup_list)

    backup_manifest_parser = backup_commands.add_parser(
        "manifest", help="Inspect ordered backup-operation evidence for one inventory target"
    )
    backup_manifest_parser.add_argument("--path", type=Path, help="Defaults to user config")
    backup_manifest_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable output"
    )
    backup_manifest_parser.set_defaults(handler=_handle_inventory_backup_manifest)

    backup_inspect_parser = backup_commands.add_parser(
        "inspect", help="Compare one exact backup with the active inventory"
    )
    backup_inspect_parser.add_argument("--path", type=Path, help="Defaults to user config")
    backup_inspect_parser.add_argument(
        "--backup", required=True, help="Exact sha256 backup ID from backup list"
    )
    backup_inspect_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable output"
    )
    backup_inspect_parser.add_argument(
        "--details",
        action="store_true",
        help="Show complete sanitized snapshots and technical evidence",
    )
    backup_inspect_parser.set_defaults(handler=_handle_inventory_backup_inspect)

    backup_rollback_parser = backup_commands.add_parser(
        "rollback", help="Preview or apply an exact-byte rollback"
    )
    backup_rollback_parser.add_argument("--path", type=Path, help="Defaults to user config")
    backup_rollback_parser.add_argument(
        "--backup", required=True, help="Exact sha256 backup ID from backup list"
    )
    backup_rollback_parser.add_argument(
        "--apply", action="store_true", help="Apply the previewed rollback"
    )
    backup_rollback_parser.add_argument(
        "--expect-revision", help="Exact active revision printed by the rollback preview"
    )
    backup_rollback_parser.add_argument(
        "--expect-plan", help="Exact plan token printed by the rollback preview"
    )
    backup_rollback_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable output"
    )
    backup_rollback_parser.add_argument(
        "--details",
        action="store_true",
        help="Show complete sanitized snapshots and technical evidence",
    )
    backup_rollback_parser.set_defaults(handler=_handle_inventory_backup_rollback)

    backup_recover_parser = backup_commands.add_parser(
        "recover",
        help="Preview or apply recovery of a missing or invalid active inventory",
    )
    backup_recover_parser.add_argument("--path", type=Path, help="Defaults to user config")
    backup_recover_parser.add_argument(
        "--backup", required=True, help="Exact sha256 backup ID from backup list"
    )
    backup_recover_parser.add_argument(
        "--apply", action="store_true", help="Apply the previewed disaster recovery"
    )
    backup_recover_parser.add_argument(
        "--expect-state", choices=("missing", "invalid"), help="Exact state from the preview"
    )
    backup_recover_parser.add_argument(
        "--expect-plan", help="Exact plan token printed by the recovery preview"
    )
    backup_recover_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable output"
    )
    backup_recover_parser.set_defaults(handler=_handle_inventory_backup_recover)

    backup_delete_parser = backup_commands.add_parser(
        "delete", help="Preview or apply irreversible deletion of one exact backup"
    )
    backup_delete_parser.add_argument("--path", type=Path, help="Defaults to user config")
    backup_delete_parser.add_argument(
        "--backup", required=True, help="Exact sha256 backup ID from backup list"
    )
    backup_delete_parser.add_argument(
        "--allow-no-backups",
        action="store_true",
        help="Required in preview and apply when deleting the last valid backup",
    )
    backup_delete_parser.add_argument(
        "--apply", action="store_true", help="Apply the previewed deletion"
    )
    backup_delete_parser.add_argument(
        "--expect-revision", help="Exact active revision printed by the deletion preview"
    )
    backup_delete_parser.add_argument(
        "--expect-plan", help="Exact plan token printed by the deletion preview"
    )
    backup_delete_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable output"
    )
    backup_delete_parser.set_defaults(handler=_handle_inventory_backup_delete)

    project_parser = commands.add_parser("project", help="Create or validate a project brief")
    project_commands = project_parser.add_subparsers(dest="project_command", required=True)
    project_template_parser = project_commands.add_parser(
        "template", help="Print a synthetic project template without writing a file"
    )
    project_template_parser.set_defaults(handler=_handle_project_template)
    project_validate_parser = project_commands.add_parser(
        "validate", help="Validate a project brief"
    )
    project_validate_parser.add_argument("path", type=Path)
    project_validate_parser.add_argument("--json", action="store_true")
    project_validate_parser.set_defaults(handler=_handle_project_validate)

    route_parser = commands.add_parser(
        "route", help="Deterministically choose resources and render inert handoffs"
    )
    route_parser.add_argument("--project", required=True, type=Path)
    route_parser.add_argument("--inventory", type=Path, help="Defaults to user config")
    route_parser.add_argument(
        "--resource-state",
        type=Path,
        help=(
            "Explicit local state file applied in memory to this route only; CLI captures one "
            "local evaluation time and preserves its fixed UTC offset in route evidence; never "
            "refreshes or writes provider or inventory state"
        ),
    )
    route_parser.add_argument(
        "--format",
        choices=("summary", "agent-summary", "markdown", "json", "presentation"),
        default="summary",
        help=(
            "summary is concise for terminals; agent-summary is the compact exact Codex response; "
            "markdown includes full evidence; presentation returns a bounded JSON envelope"
        ),
    )
    route_parser.add_argument(
        "--width",
        type=_summary_width,
        help=(
            "Wrap summary text, including the presentation summary, to 40-120 columns (default: 80)"
        ),
    )
    route_parser.add_argument(
        "--max-words",
        type=_presentation_max_words,
        help=(
            "Require a complete ready presentation summary to fit within 1-500 words; an "
            "impossible limit returns untruncated conflict guidance"
        ),
    )
    route_parser.add_argument(
        "--max-lines",
        type=_presentation_max_lines,
        help=(
            "Require a complete ready presentation summary to fit within 1-50 lines; an "
            "impossible limit returns untruncated conflict guidance"
        ),
    )
    route_parser.add_argument(
        "--allow-demo", action="store_true", help="Explicitly permit synthetic demo resources"
    )
    route_parser.set_defaults(handler=_handle_route)

    state_parser = commands.add_parser(
        "state",
        help="Validate adapter-neutral resource-state evidence",
        description=(
            "Validate one explicit local state file without contacting a provider, reading an "
            "inventory, or writing anything."
        ),
    )
    state_commands = state_parser.add_subparsers(dest="state_command", required=True)
    state_validate_parser = state_commands.add_parser(
        "validate", help="Validate a bounded resource-state file"
    )
    state_validate_parser.add_argument("path", type=Path)
    state_validate_parser.add_argument(
        "--json", action="store_true", help="Emit a value-free machine-readable receipt"
    )
    state_validate_parser.set_defaults(handler=_handle_resource_state_validate)

    compare_parser = commands.add_parser(
        "compare",
        help="Show what changes between two resource-fit routes",
        description=(
            "Route one baseline and one alternative project brief against the same roster, then "
            "show only changed assignments and gaps. This command is read-only and does not run "
            "or contact resources."
        ),
    )
    compare_parser.add_argument(
        "--project", required=True, type=Path, help="Baseline project brief"
    )
    compare_parser.add_argument(
        "--against",
        type=Path,
        help="Alternative project brief; otherwise use one or more overrides",
    )
    compare_parser.add_argument("--inventory", type=Path, help="Defaults to user config")
    compare_parser.add_argument(
        "--format",
        choices=("summary", "json"),
        default="summary",
        help="summary is concise for people; json is stable machine-readable change evidence",
    )
    compare_parser.add_argument(
        "--width",
        type=_summary_width,
        help=(
            "Wrap summary prose to 40-120 columns (default: 80); the exact final safety "
            "boundary remains one line"
        ),
    )
    compare_parser.add_argument(
        "--allow-demo", action="store_true", help="Explicitly permit synthetic demo resources"
    )
    compare_parser.add_argument(
        "--data-class",
        choices=_enum_values(DataClass),
        help="Compare with this project data classification",
    )
    compare_parser.add_argument(
        "--network-allowed",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Compare with network access allowed or forbidden",
    )
    compare_parser.add_argument(
        "--allow-unverified",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Compare with unverified declarations allowed or blocked",
    )
    compare_parser.add_argument(
        "--max-marginal-cost",
        type=_unit_score,
        help="Compare with a 0.0-1.0 marginal-cost ceiling",
    )
    compare_parser.add_argument(
        "--forbid-resource",
        action="append",
        default=[],
        type=_resource_id,
        metavar="ID",
        help="Exclude an exact resource ID in the alternative; repeat as needed",
    )
    compare_parser.set_defaults(handler=_handle_compare)

    skill_parser = commands.add_parser("skill", help="Inspect the bundled Codex skill")
    skill_commands = skill_parser.add_subparsers(dest="skill_command", required=True)
    skill_path_parser = skill_commands.add_parser(
        "path", help="Print the distributable project-atready skill path"
    )
    skill_path_parser.set_defaults(handler=_handle_skill_path)
    skill_status_parser = skill_commands.add_parser(
        "status", help="Check whether Codex can discover the bundled skill"
    )
    skill_status_parser.set_defaults(handler=_handle_skill_status)

    schema_parser = commands.add_parser("schema", help="Print a JSON Schema")
    schema_parser.add_argument(
        "kind",
        choices=(
            "inventory",
            "inventory-annotation-declaration",
            "project",
            "resource-declaration",
            "resource-state",
            "route-plan",
        ),
    )
    schema_parser.set_defaults(handler=_handle_schema)

    help_parser = commands.add_parser(
        "help", help="Show getting-started, topic, or complete command help"
    )
    help_parser.add_argument("topic", nargs="?", help="Topic or top-level command")
    help_parser.add_argument("--all", action="store_true", help="Show every top-level command")
    help_parser.set_defaults(handler=_handle_help, root_parser=parser)
    return parser


def _enum_values(enum_type: type) -> tuple[str, ...]:
    return tuple(item.value for item in enum_type)


def _date_value(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an ISO date in YYYY-MM-DD form") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("expected an ISO date in YYYY-MM-DD form")
    return parsed


def _summary_width(value: str) -> int:
    try:
        width = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer from 40 to 120") from exc
    if not 40 <= width <= 120:
        raise argparse.ArgumentTypeError("expected an integer from 40 to 120")
    return width


def _presentation_max_words(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer from 1 to 500") from exc
    if not 1 <= limit <= 500:
        raise argparse.ArgumentTypeError("expected an integer from 1 to 500")
    return limit


def _presentation_max_lines(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer from 1 to 50") from exc
    if not 1 <= limit <= 50:
        raise argparse.ArgumentTypeError("expected an integer from 1 to 50")
    return limit


def _capacity_number(value: str) -> int | float:
    if len(value) > _MAX_CAPACITY_NUMBER_CHARACTERS:
        raise argparse.ArgumentTypeError("expected a non-negative JSON number")
    try:
        parsed = json.loads(value)
    except (RecursionError, ValueError) as exc:
        raise argparse.ArgumentTypeError("expected a non-negative JSON number") from exc
    if (
        isinstance(parsed, bool)
        or not isinstance(parsed, (int, float))
        or (isinstance(parsed, float) and not math.isfinite(parsed))
        or parsed < 0
        or parsed > 1e18
    ):
        raise argparse.ArgumentTypeError("expected a non-negative JSON number")
    return parsed


def _inventory_path(candidate: Path | None) -> Path:
    return candidate.expanduser() if candidate else resolve_paths().inventory_path


_HELP_TOPICS = {
    "planning": """PLANNING

For a first resource fit check:
  0. See the complete flow: atready demo
  1. Create your roster:  atready init
  2. Add a resource:      atready add
  3. Check resource fit:  atready plan

Quick Fit asks what you are working on and which declared capabilities it needs.
Use 'atready plan --mode detailed' for one to three steps, expected results,
checks, capability strength, and custom eligibility. Neither mode creates the
complete project plan, writes a project file, or runs a resource.

For a reusable or scripted project brief:
  atready project template > project.yaml
  atready route --project project.yaml
""",
    "resources": """RESOURCES

Add one resource interactively:
  atready add

Inspect the roster:
  atready inventory list

For structured, non-interactive changes:
  atready inventory add --help
  atready inventory replace --help
  atready inventory remove --help

AtReady uses only facts you declare. It does not scan apps, inspect accounts,
contact providers, or run resources.
""",
    "automation": """AUTOMATION

Use the stable file-based commands for scripts:
  atready inventory validate --json
  atready project validate project.yaml --json
  atready route --project project.yaml --format json

Interactive commands such as 'atready add' and 'atready plan' require a real
terminal. JSON output stays on standard output; errors use standard error.
""",
}


def _command_parsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _handle_help(args: argparse.Namespace) -> int:
    root: argparse.ArgumentParser = args.root_parser
    if args.all:
        if args.topic is not None:
            raise ConfigurationError("choose either a help topic or --all")
        print(argparse.ArgumentParser.format_help(root), end="")
        return 0
    if args.topic is None:
        print(root.format_help(), end="")
        return 0
    topic = args.topic.casefold()
    if topic in _HELP_TOPICS:
        print(_HELP_TOPICS[topic], end="")
        return 0
    command_parser = _command_parsers(root).get(topic)
    if command_parser is None:
        available = ", ".join((*sorted(_HELP_TOPICS), *sorted(_command_parsers(root))))
        raise ConfigurationError(f"unknown help topic; choose one of: {available}")
    print(command_parser.format_help(), end="")
    return 0


def _terminal_safe(value: object) -> str:
    """Escape non-printing characters for one human-readable terminal line."""

    return "".join(
        character if character.isprintable() else character.encode("unicode_escape").decode("ascii")
        for character in str(value)
    )


def _require_details_compatible(args: argparse.Namespace) -> None:
    if getattr(args, "details", False) and getattr(args, "json", False):
        raise ConfigurationError("--details cannot be combined with --json")
    if getattr(args, "details", False) and getattr(args, "apply", False):
        raise ConfigurationError("--details is preview-only and cannot be combined with --apply")


def _bounded_terminal_items(values: list[str] | tuple[str, ...], *, limit: int = 3) -> str:
    safe = [_terminal_safe(value) for value in values]
    if not safe:
        return "none"
    visible = ", ".join(safe[:limit])
    remaining = len(safe) - limit
    return f"{visible} (+{remaining} more)" if remaining > 0 else visible


def _bounded_terminal_text(value: object, *, limit: int = 80) -> str:
    safe = _terminal_safe(value)
    return safe if len(safe) <= limit else safe[: limit - 3] + "..."


def _resource_change_summary(before: dict[str, Any], after: dict[str, Any]) -> str:
    changed = [key for key in sorted(before) if before.get(key) != after.get(key)]
    parts: list[str] = []
    if "name" in changed:
        parts.append(
            f'name "{_terminal_safe(before.get("name", ""))}" -> '
            f'"{_terminal_safe(after.get("name", ""))}"'
        )
        changed.remove("name")
    labels = {
        "access": "access",
        "avoid_for": "avoid guidance",
        "best_for": "best-use guidance",
        "capabilities": "capabilities",
        "categories": "categories",
        "economics": "cost or quota",
        "handoff": "handoff",
        "policy": "policy",
        "provenance": "verification",
        "ratings": "comparison ratings",
    }
    parts.extend(labels.get(key, key.replace("_", " ")) for key in changed)
    return "; ".join(parts) if parts else "no visible routing fields"


def _snapshot_resource_count(snapshot: dict[str, Any] | None) -> int | None:
    if snapshot is None:
        return None
    resources = snapshot.get("resources")
    return len(resources) if isinstance(resources, list) else None


def _comparison_change_summary(comparison: dict[str, Any]) -> str:
    resource_changes = comparison["resource_changes"]
    return "; ".join(
        (
            f"add: {_bounded_terminal_items(resource_changes['added'])}",
            f"change: {_bounded_terminal_items(resource_changes['changed'])}",
            f"remove: {_bounded_terminal_items(resource_changes['removed'])}",
        )
    )


def _private_note_count_summary(comparison: dict[str, Any]) -> str:
    counts = comparison["resource_private_note_effect_counts"]
    return (
        ", ".join(
            f"{count} {effect.removeprefix('will-')}" for effect, count in counts.items() if count
        )
        or "none"
    )


def _print_intake_review(review: dict[str, Any]) -> None:
    """Render derived intake guidance without claiming route eligibility."""

    print(f"Selection-fact status: {review['selection_fact_status']}")
    facts = (
        ("Unverified selection facts", review["unverified_selection_facts"]),
        ("Declared unavailable facts", review["declared_unavailable_facts"]),
    )
    for label, values in facts:
        print(f"{label}: {', '.join(values) if values else 'none'}")

    labels = {
        "selection_facts": "Selection-fact defaults",
        "scoring_inputs": "Scoring-input defaults",
        "conservative_policy": "Conservative-policy defaults",
        "operating_context": "Operating-context defaults",
    }
    for group, label in labels.items():
        values = review["default_groups"][group]
        print(f"{label}: {', '.join(values) if values else 'none'}")
    print(
        "Route eligibility evaluated: false. Project constraints, capability fit, cost limits, "
        "and provenance freshness are evaluated only during routing."
    )


_RATING_NAMES = {
    "quality": "quality",
    "speed": "speed",
    "autonomy": "autonomy",
    "privacy": "privacy",
    "reliability": "reliability",
    "confidence": "confidence",
    "context-switch-cost": "context_switch_cost",
    "integration-friction": "integration_friction",
}


def _scored_pairs(values: list[str], *, subject: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ConfigurationError(f"{subject} must use ID=SCORE: {value!r}")
        name, raw_score = value.split("=", 1)
        name = name.strip()
        if not name:
            raise ConfigurationError(f"{subject} ID must not be empty")
        if name in result:
            raise ConfigurationError(f"duplicate {subject} ID: {name}")
        try:
            score = float(raw_score)
        except ValueError as exc:
            raise ConfigurationError(f"{subject} score must be a number: {value!r}") from exc
        if not math.isfinite(score):
            raise ConfigurationError(f"{subject} score must be a finite number: {value!r}")
        result[name] = score
    return result


def _resource_from_args(args: argparse.Namespace) -> ParsedResourceDeclaration:
    capabilities = _scored_pairs(args.capability or [], subject="capability")
    supplied_ratings = _scored_pairs(args.rating or [], subject="rating")
    unknown_ratings = sorted(set(supplied_ratings) - set(_RATING_NAMES))
    if unknown_ratings:
        raise ConfigurationError("unknown rating names: " + ", ".join(unknown_ratings))
    ratings = {_RATING_NAMES[name]: score for name, score in supplied_ratings.items()}

    value: dict[str, Any] = {
        "id": args.id,
        "name": args.name,
        "categories": args.category,
        "capabilities": capabilities,
    }
    access = {
        key: item
        for key, item in {
            "status": args.access,
            "interaction": args.interaction,
            "current_session": args.session,
        }.items()
        if item is not None
    }
    if access:
        value["access"] = access
    if args.marginal_cost is not None and not math.isfinite(args.marginal_cost):
        raise ConfigurationError("marginal cost must be a finite number")
    economics = {
        key: item
        for key, item in {
            "billing": args.billing,
            "marginal_cost": args.marginal_cost,
            "quota": args.quota,
        }.items()
        if item is not None
    }
    capacity = {
        key: item
        for key, item in {
            "unit": args.capacity_unit,
            "remaining": args.capacity_remaining,
            "limit": args.capacity_limit,
            "project_limit": args.capacity_project_limit,
            "resets_on": args.capacity_resets_on,
            "basis": args.capacity_basis,
            "last_verified": args.capacity_verified_on,
        }.items()
        if item is not None
    }
    if capacity:
        economics["capacity"] = capacity
    if economics:
        value["economics"] = economics
    if ratings:
        value["ratings"] = ratings
    policy = {
        key: item
        for key, item in {
            "allowed_data_classes": args.allowed_data_class,
            "approval_required": args.approval_required,
            "requires_network": args.requires_network,
        }.items()
        if item is not None
    }
    if policy:
        value["policy"] = policy
    provenance = {
        key: item
        for key, item in {
            "basis": args.confidence_basis,
            "last_verified": args.verified_on,
        }.items()
        if item is not None
    }
    if provenance:
        value["provenance"] = provenance
    if args.handoff_method is not None:
        value["handoff"] = {"method": args.handoff_method}

    return parse_resource_mapping(value)


_TYPED_RESOURCE_FLAGS = {
    "id": "--id",
    "name": "--name",
    "category": "--category",
    "capability": "--capability",
    "access": "--access",
    "interaction": "--interaction",
    "session": "--session",
    "billing": "--billing",
    "marginal_cost": "--marginal-cost",
    "quota": "--quota",
    "capacity_unit": "--capacity-unit",
    "capacity_remaining": "--capacity-remaining",
    "capacity_limit": "--capacity-limit",
    "capacity_project_limit": "--capacity-project-limit",
    "capacity_resets_on": "--capacity-resets-on",
    "capacity_basis": "--capacity-basis",
    "capacity_verified_on": "--capacity-verified-on",
    "rating": "--rating",
    "allowed_data_class": "--allowed-data-class",
    "approval_required": "--approval-required/--no-approval-required",
    "requires_network": "--requires-network/--no-requires-network",
    "confidence_basis": "--confidence-basis",
    "verified_on": "--verified-on",
    "handoff_method": "--handoff-method",
}
_REQUIRED_TYPED_RESOURCE_FLAGS = {
    "id": "--id",
    "name": "--name",
    "category": "--category",
    "capability": "--capability",
}


def _resource_input(args: argparse.Namespace) -> ParsedResourceDeclaration:
    supplied_typed = [
        flag for name, flag in _TYPED_RESOURCE_FLAGS.items() if getattr(args, name) is not None
    ]
    structured_modes = int(args.resource_file is not None) + int(args.resource_stdin)
    if structured_modes > 1:
        raise ConfigurationError("choose exactly one of --resource-file or --resource-stdin")
    if structured_modes and supplied_typed:
        raise ConfigurationError(
            "structured resource input cannot be combined with typed flags: "
            + ", ".join(supplied_typed)
        )
    if args.resource_file is not None:
        return load_resource_declaration_file(args.resource_file)
    if args.resource_stdin:
        stream = getattr(sys.stdin, "buffer", None)
        if stream is None:
            raise ConfigurationError("--resource-stdin requires binary standard input")
        return load_resource_declaration_stdin(stream)
    missing = [
        flag for name, flag in _REQUIRED_TYPED_RESOURCE_FLAGS.items() if getattr(args, name) is None
    ]
    if missing:
        raise ConfigurationError(
            "typed resource input requires "
            + ", ".join(missing)
            + "; otherwise use --resource-file or --resource-stdin"
        )
    return _resource_from_args(args)


class _GuidedAddCancelledError(Exception):
    """Internal control flow for an intentional pre-commit cancellation."""


class _GuidedPlanCancelledError(Exception):
    """Internal control flow for an intentional guided-plan cancellation."""


def _guided_terminal_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _guided_read(prompt: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    sys.stdout.write(f"{prompt}{suffix}: ")
    sys.stdout.flush()
    value = sys.stdin.readline(_MAX_GUIDED_INPUT_CHARACTERS + 2)
    if value == "":
        raise EOFError
    if len(value.rstrip("\r\n")) > _MAX_GUIDED_INPUT_CHARACTERS:
        raise ConfigurationError("guided answer is too long; nothing was saved")
    value = value.rstrip("\r\n").strip()
    return default if not value and default is not None else value


def _guided_yes_no(prompt: str, *, default: bool | None = None) -> bool:
    label = "Y/n" if default is True else "y/N" if default is False else "yes/no"
    while True:
        answer = _guided_read(f"{prompt} [{label}]").casefold()
        if not answer and default is not None:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def _guided_choice(
    prompt: str,
    choices: dict[str, str],
    *,
    default: str | None = None,
) -> str:
    while True:
        answer = _guided_read(prompt, default=default).casefold()
        if answer in choices:
            return choices[answer]
        print("Choose one of: " + ", ".join(choices))


def _guided_csv(prompt: str, *, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    while True:
        shown_default = ", ".join(default) if default else None
        answer = _guided_read(prompt, default=shown_default)
        values = tuple(dict.fromkeys(item.strip() for item in answer.split(",") if item.strip()))
        if values:
            return values
        print("Enter at least one comma-separated ID.")


def _guided_plan_read(prompt: str, *, default: str | None = None) -> str:
    while True:
        value = _guided_read(prompt, default=default)
        if value.casefold() in {"cancel", "exit", "quit"}:
            raise _GuidedPlanCancelledError
        if any(unicode_category(character) in {"Cc", "Cf"} for character in value):
            print("Remove control or zero-width characters, or type cancel.")
            continue
        return value


def _guided_plan_yes_no(prompt: str, *, default: bool | None = None) -> bool:
    label = "Y/n" if default is True else "y/N" if default is False else "yes/no"
    while True:
        answer = _guided_plan_read(f"{prompt} [{label}]").casefold()
        if not answer and default is not None:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer yes or no, or type cancel.")


def _guided_plan_approval(prompt: str) -> str:
    while True:
        answer = _guided_plan_read(f"{prompt} [Y/n/edit]").casefold()
        if not answer or answer in {"y", "yes"}:
            return "yes"
        if answer in {"n", "no"}:
            return "no"
        if answer in {"e", "edit", "change", "revise"}:
            return "edit"
        print("Please answer yes, no, or edit, or type cancel.")


def _guided_plan_choice(
    prompt: str,
    choices: dict[str, Any],
    *,
    default: str | None = None,
) -> Any:
    while True:
        answer = _guided_plan_read(prompt, default=default).casefold()
        if answer in choices:
            return choices[answer]
        print("Choose one of: " + ", ".join(choices))


def _guided_plan_numbered_selection(
    prompt: str,
    values: Sequence[str],
    *,
    allow_none: bool = False,
) -> tuple[str, ...]:
    while True:
        answer = _guided_plan_read(prompt).casefold()
        if allow_none and answer in {"", "none"}:
            return ()
        if answer == "all":
            return tuple(values)
        raw_choices = tuple(item.strip() for item in answer.split(",") if item.strip())
        try:
            indexes = tuple(dict.fromkeys(int(item) for item in raw_choices))
        except ValueError:
            indexes = ()
        if indexes and all(1 <= index <= len(values) for index in indexes):
            return tuple(values[index - 1] for index in indexes)
        options = f"1-{len(values)}"
        suffix = ", all, or none" if allow_none else ", or all"
        print(f"Choose comma-separated numbers from {options}{suffix}.")


def _guided_plan_interactions() -> list[str]:
    labels = {
        "codex": InteractionMode.CODEX_CALLABLE.value,
        "terminal": InteractionMode.LOCAL_CLI.value,
        "separate": InteractionMode.EXTERNAL_AGENT.value,
        "manual": InteractionMode.MANUAL.value,
    }
    while True:
        answer = _guided_plan_read(
            "Allowed workflows, comma-separated [all/codex/terminal/separate/manual]",
            default="all",
        ).casefold()
        if answer == "all":
            return [item.value for item in InteractionMode]
        selected = tuple(dict.fromkeys(item.strip() for item in answer.split(",") if item.strip()))
        if selected and all(item in labels for item in selected):
            return [labels[item] for item in selected]
        print("Choose all or a comma-separated list of codex, terminal, separate, and manual.")


def _guided_slug_proposal(name: str) -> str:
    proposal = re.sub(r"[^a-z0-9._-]+", "-", name.casefold()).strip("-._")
    return proposal[:64] or "resource"


def _guided_strength(capability: str, *, label: str | None = None) -> float:
    display = f"{label} ({capability})" if label and label != capability else capability
    while True:
        answer = _guided_read(
            f"Strength for {display} [basic/solid/strong/exceptional/0.0-1.0]"
        ).casefold()
        if answer in _GUIDED_STRENGTHS:
            return _GUIDED_STRENGTHS[answer]
        try:
            score = float(answer)
        except ValueError:
            score = -1.0
        if math.isfinite(score) and 0.0 <= score <= 1.0:
            return score
        print("Use basic, solid, strong, exceptional, or a score from 0.0 to 1.0.")


def _guided_profile(query: str | None) -> Any | None:
    if query is not None:
        return resource_profile(query)
    profiles = resource_profiles()
    print("Starter profiles (editable proposals, not facts about your setup):")
    for index, profile in enumerate(profiles, start=1):
        print(f"  {index}. {profile.name} ({profile.id})")
    print(f"  {len(profiles) + 1}. Something else")
    choices = {str(index): profile for index, profile in enumerate(profiles, start=1)}
    while True:
        answer = _guided_read(f"Choose a resource [1-{len(profiles) + 1}]")
        if answer == str(len(profiles) + 1):
            return None
        if answer in choices:
            return choices[answer]
        print("Choose one number from the list.")


def _guided_resource_from_profile(profile: Any | None) -> ParsedResourceDeclaration:
    while True:
        if profile is None:
            print("Use short lowercase IDs such as 'coding-agent' and 'code-review'.")
            name = _guided_read("Resource name")
            if not name:
                print("Enter a resource name.")
                continue
            resource_id = _guided_read("Stable resource ID", default=_guided_slug_proposal(name))
            categories = _guided_csv("Category IDs, comma-separated (example: coding-agent)")
            capability_ids = _guided_csv("Capability IDs, comma-separated (example: code-review)")
            labels: dict[str, str] = {}
        else:
            print(f"Found starter profile: {profile.name}")
            print("These labels are editable suggestions, not facts about your setup.")
            name = _guided_read("Name", default=profile.name)
            resource_id = _guided_read("Stable resource ID", default=profile.id)
            categories = _guided_csv(
                "Category IDs, comma-separated",
                default=tuple(item.id for item in profile.category_suggestions),
            )
            capability_ids = _guided_csv(
                "Capability IDs, comma-separated",
                default=tuple(item.id for item in profile.capability_suggestions),
            )
            labels = {item.id: item.label for item in profile.capability_suggestions}
        try:
            parse_resource_mapping(
                {
                    "id": resource_id,
                    "name": name,
                    "categories": list(categories),
                    "capabilities": {item: 0.5 for item in capability_ids},
                }
            )
        except ConfigurationError as exc:
            print(f"Please correct those identity fields: {_terminal_safe(exc)}")
            continue
        break

    capabilities = {
        capability: _guided_strength(capability, label=labels.get(capability))
        for capability in capability_ids
    }
    print(
        "Workflow choices: codex = Codex can call it here; terminal = terminal command; "
        "separate = separate app, service, or bot; manual = you operate it manually."
    )
    interaction_answer = _guided_choice(
        "How do you use it? [codex/terminal/separate/manual]",
        {
            "terminal": InteractionMode.LOCAL_CLI.value,
            "codex": InteractionMode.CODEX_CALLABLE.value,
            "separate": InteractionMode.EXTERNAL_AGENT.value,
            "manual": InteractionMode.MANUAL.value,
        },
        default="manual",
    )
    interaction = interaction_answer
    access_status = _guided_choice(
        "Usable access? [yes/limited/no/not sure]",
        {
            "yes": AccessStatus.ACTIVE.value,
            "limited": AccessStatus.LIMITED.value,
            "no": AccessStatus.INACTIVE.value,
            "not sure": AccessStatus.UNKNOWN.value,
            "unknown": AccessStatus.UNKNOWN.value,
        },
        default="not sure",
    )
    current_session = _guided_choice(
        "Available for this task now? [yes/no/not sure]",
        {
            "yes": SessionAvailability.AVAILABLE.value,
            "no": SessionAvailability.UNAVAILABLE.value,
            "not sure": SessionAvailability.UNKNOWN.value,
            "unknown": SessionAvailability.UNKNOWN.value,
        },
        default="not sure",
    )
    quota = _guided_choice(
        "Usage room remaining? [plenty/some/none/not sure]",
        {
            "plenty": QuotaStatus.AMPLE.value,
            "some": QuotaStatus.LIMITED.value,
            "none": QuotaStatus.EXHAUSTED.value,
            "not sure": QuotaStatus.UNKNOWN.value,
            "unknown": QuotaStatus.UNKNOWN.value,
        },
        default="not sure",
    )
    basis = _guided_choice(
        "How do you know? [observed/judgment/vendor/not sure]",
        {
            "observed": ConfidenceBasis.OBSERVED.value,
            "judgment": ConfidenceBasis.USER_JUDGMENT.value,
            "vendor": ConfidenceBasis.VENDOR_CLAIM.value,
            "not sure": ConfidenceBasis.UNKNOWN.value,
            "unknown": ConfidenceBasis.UNKNOWN.value,
        },
        default="judgment",
    )
    verified_on: date | None = None
    if basis != ConfidenceBasis.UNKNOWN.value or access_status in {
        AccessStatus.ACTIVE.value,
        AccessStatus.LIMITED.value,
    }:
        while True:
            checked = _guided_read("Last checked [today/YYYY-MM-DD/not sure]", default="today")
            if checked.casefold() == "today":
                verified_on = date.today()
                break
            if checked.casefold() in {"not sure", "unknown"}:
                if access_status in {AccessStatus.ACTIVE.value, AccessStatus.LIMITED.value}:
                    print("Active or limited access needs a real checked date.")
                    continue
                basis = ConfidenceBasis.UNKNOWN.value
                break
            try:
                verified_on = _date_value(checked)
            except argparse.ArgumentTypeError:
                print("Use today, not sure, or an ISO date such as 2026-08-09.")
                continue
            break

    data_ceiling = _guided_choice(
        "Most sensitive project data allowed [public/internal/private/sensitive]",
        {item.value: item.value for item in _DATA_SENSITIVITY_LADDER},
        default=DataClass.PUBLIC.value,
    )
    data_values = tuple(item.value for item in _DATA_SENSITIVITY_LADDER)
    allowed_data = data_values[: data_values.index(data_ceiling) + 1]
    requires_network = _guided_yes_no("Does using it require internet access?")
    billing = _guided_choice(
        "How is it paid for? [free/owned/subscription/usage/not sure]",
        {
            "free": BillingModel.FREE.value,
            "owned": BillingModel.OWNED.value,
            "subscription": BillingModel.SUBSCRIPTION.value,
            "usage": BillingModel.USAGE.value,
            "not sure": BillingModel.UNKNOWN.value,
            "unknown": BillingModel.UNKNOWN.value,
        },
        default="not sure",
    )
    cost = _guided_choice(
        "Relative cost per use [low/medium/high/very high/not sure]",
        {
            "low": "0.25",
            "medium": "0.5",
            "high": "0.75",
            "very high": "0.95",
            "not sure": "",
        },
        default="not sure",
    )

    economics: dict[str, Any] = {
        "billing": billing,
        "quota": quota,
    }
    if cost:
        economics["marginal_cost"] = float(cost)

    value: dict[str, Any] = {
        "id": resource_id,
        "name": name,
        "categories": list(categories),
        "capabilities": capabilities,
        "access": {
            "status": access_status,
            "interaction": interaction,
            "current_session": current_session,
        },
        "economics": economics,
        "policy": {
            "allowed_data_classes": list(allowed_data),
            "approval_required": True,
            "requires_network": requires_network,
        },
        "provenance": {"basis": basis, "last_verified": verified_on},
    }
    return parse_resource_mapping(value)


def _handle_init(args: argparse.Namespace) -> int:
    path = _inventory_path(args.path)
    if path.exists() or path.is_symlink():
        try:
            catalog = InventoryCatalog.from_path(path, today=date.today())
        except ConfigurationError as exc:
            raise ConfigurationError(f"refusing to overwrite existing file: {path}") from exc
        if catalog.inventory.inventory_kind is not InventoryKind.PERSONAL:
            raise ConfigurationError(f"refusing to overwrite existing file: {path}")
        if args.json:
            print(
                json.dumps(
                    {
                        "created": None,
                        "inventory_kind": "personal",
                        "kept": str(path),
                        "resources": len(catalog.inventory.resources),
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"Personal roster already exists at {_terminal_safe(path)}")
            print("Kept unchanged.")
            print("Next: add a resource with 'atready add'.")
        return 0
    create_private_file(path, starter_inventory())
    if args.json:
        print(
            json.dumps(
                {
                    "created": str(path),
                    "inventory_kind": "personal",
                    "revision_protection": "nonce-v1-present",
                    "resources": 0,
                },
                sort_keys=True,
            )
        )
    else:
        print(f"Created empty personal inventory at {_terminal_safe(path)}")
        print(
            "Revision privacy state: nonce-v1-present "
            "(freshly generated; the nonce value is not printed)"
        )
        print("Next: add your first resource with 'atready add'; never include credentials.")
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    payload = doctor_payload(
        plugin_version=args.plugin_version,
        plugin_contract_version=args.plugin_contract,
        required_features=args.require_feature,
    )
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        plugin_requirements_supplied = args.plugin_contract is not None or bool(
            args.require_feature
        )
        if not plugin_requirements_supplied:
            print("AtReady local runtime self-check passed; no plugin requirements were supplied.")
        elif payload["compatible"]:
            print("AtReady local runtime is ready for this plugin contract.")
        else:
            print("AtReady local runtime is not compatible with this plugin contract.")
        print(f"Runtime version: {payload['runtime_version']}")
        print(f"Runtime contract version: {payload['runtime_contract_version']}")
        if payload["plugin_version"] is not None:
            print(f"Plugin version checked: {payload['plugin_version']} (informational only)")
        if payload["plugin_contract_version"] is not None:
            print(f"Plugin contract required: {payload['plugin_contract_version']}")
        print("Runtime features:")
        for feature_id in payload["runtime_features"]:
            print(f"- {feature_id}")
        if payload["missing_features"]:
            print("Missing required features:")
            for feature_id in payload["missing_features"]:
                print(f"- {feature_id}")
        print("Inventory read: false")
        print("Network accessed: false")
        print("Writes performed: false")
    return 0 if payload["compatible"] else 2


def _handle_runtime_contract(args: argparse.Namespace) -> int:
    payload = runtime_contract_payload()
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(f"Product: {payload['product']}")
        print(f"Runtime version: {payload['runtime_version']}")
        print(f"Contract version: {payload['contract_version']}")
        print("Features:")
        for feature_id in payload["features"]:
            print(f"- {feature_id}")
        print("Inventory read: false")
        print("Network accessed: false")
        print("Writes performed: false")
    return 0


_NO_EXECUTION_BOUNDARY = "No routed project resources were contacted or run."


def _handle_demo_route(args: argparse.Namespace) -> int:
    del args
    today = date.today()
    project = project_from_text(starter_project(today))
    catalog = InventoryCatalog.from_text(demo_inventory(today), today=project.as_of)
    plan = route(catalog.inventory, project, allow_demo=True)
    rendered = render_summary(
        plan,
        goal=project.goal,
        width=80,
        include_next_action=False,
    )
    boundary = _NO_EXECUTION_BOUNDARY + "\n"
    if not rendered.endswith(boundary):
        raise RuntimeError("compact route output is missing its execution boundary")

    print(rendered.removesuffix(boundary), end="")
    print("\nReady to try your own roster?")
    print("1. atready init")
    print("2. atready add")
    print("3. atready plan")
    print(_NO_EXECUTION_BOUNDARY)
    has_gap = any(
        assignment.primary is None or assignment.unresolved_gaps for assignment in plan.assignments
    )
    return 3 if has_gap else 0


def _handle_demo_inventory(args: argparse.Namespace) -> int:
    text = demo_inventory()
    if args.format == "json":
        inventory = InventoryCatalog.from_text(text).inventory
        print(json.dumps(inventory.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        print(text, end="")
    return 0


def _handle_config_path(args: argparse.Namespace) -> int:
    paths = resolve_paths()
    if args.json:
        print(
            json.dumps(
                {
                    "config_directory": str(paths.config_dir),
                    "data_directory": str(paths.data_dir),
                    "inventory": str(paths.inventory_path),
                },
                sort_keys=True,
            )
        )
    else:
        print(_terminal_safe(paths.inventory_path))
    return 0


def _profile_payload(profile: Any) -> dict[str, Any]:
    return {
        "catalog_proposals_only": True,
        "discovery_performed": False,
        "resource_or_account_facts": False,
        "writes_performed": False,
        **profile.model_dump(mode="json"),
    }


def _handle_resource_profiles(args: argparse.Namespace) -> int:
    profiles = resource_profiles()
    if args.json:
        print(
            json.dumps(
                {
                    "catalog_version": 1,
                    "catalog_proposals_only": True,
                    "discovery_performed": False,
                    "resource_or_account_facts": False,
                    "writes_performed": False,
                    "profiles": [profile.model_dump(mode="json") for profile in profiles],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("Bundled resource profiles (catalog proposals only; no discovery performed)")
        for profile in profiles:
            aliases = ", ".join(profile.aliases) if profile.aliases else "none"
            print(f"- {profile.id}: {profile.name} (aliases: {aliases})")
        print(
            "Suggestions are not resource, account, authentication, quota, or availability facts."
        )
        print("Writes performed: false")
    return 0


def _handle_resource_profile(args: argparse.Namespace) -> int:
    profile = resource_profile(args.profile)
    if args.json:
        print(json.dumps(_profile_payload(profile), indent=2, sort_keys=True))
    else:
        print(f"Resource profile proposal: {profile.name} ({profile.id})")
        print(f"Aliases: {', '.join(profile.aliases) if profile.aliases else 'none'}")
        print(
            "Suggested categories: " + ", ".join(item.id for item in profile.category_suggestions)
        )
        print(
            "Suggested capabilities: "
            + ", ".join(item.id for item in profile.capability_suggestions)
        )
        print(
            "Capacity unit hints: "
            + (
                ", ".join(item.unit for item in profile.capacity_unit_hints)
                if profile.capacity_unit_hints
                else "none"
            )
        )
        if profile.executable_probe is not None:
            executable_names = (
                profile.executable_probe.executable,
                *profile.executable_probe.aliases,
            )
            print("Local discovery executable proposals: " + ", ".join(executable_names))
            print(
                "Local discovery platforms: "
                + ", ".join(profile.executable_probe.supported_platforms)
            )
        if profile.provider_kit is not None:
            print("Provider workflow-mode proposals:")
            for mode in profile.provider_kit.workflow_mode_suggestions:
                print(
                    f"- {mode.id}: {mode.label} (interaction: {mode.interaction_suggestion.value})"
                )
                print(f"  Guidance: {mode.guidance}")
            print("Provider onboarding guidance:")
            for item in profile.provider_kit.onboarding_guidance:
                print(f"- {item.id}: {item.prompt}")
            print("Provider capacity guidance:")
            for item in profile.provider_kit.capacity_guidance:
                print(f"- {item.id}: {item.prompt}")
            if profile.provider_kit.model_routing_suggestions:
                print(
                    "Provider model-routing proposals "
                    f"(reviewed {profile.provider_kit.model_catalog_reviewed_on}; "
                    "availability unverified; capability scores require user confirmation):"
                )
                for model in profile.provider_kit.model_routing_suggestions:
                    print(
                        f"- {model.id}: {model.label} "
                        f"(provider model: {model.provider_model_id}; "
                        f"suggested resource: {model.suggested_resource_id}; "
                        f"status: {model.selection_status})"
                    )
                    print(f"  Planning role: {model.planning_role}")
                    print(f"  Caution: {model.planning_caution}")
                    if model.shared_capacity_group is not None:
                        print(f"  Shared capacity proposal: {model.shared_capacity_group}")
            print(
                "Provider kit limits: account inspection unsupported; AtReady network "
                "access none; provider execution unsupported."
            )
        print("Catalog proposals only; no resource or account facts were inspected.")
        print("Writes performed: false")
    return 0


def _handle_resource_quick_add(args: argparse.Namespace) -> int:
    _require_preview_apply_contract(args, subject="quick setup addition")
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        raise ConfigurationError("--facts-stdin requires binary standard input")
    facts = load_quick_setup_facts_stdin(stream)
    parsed, profile_id = resource_from_quick_setup(facts)
    try:
        plan = plan_add_resource(
            _inventory_path(args.path),
            parsed.resource,
            defaulted_fields=parsed.defaulted_fields,
        )
    except ConfigurationError as exc:
        message = str(exc)
        if facts.name in message or profile_id in message:
            raise ConfigurationError(
                "quick setup preview could not be prepared; inspect the roster or use "
                "detailed setup"
            ) from None
        raise
    mapping = quick_setup_mapping_summary(facts, profile_id=profile_id)
    if not args.apply:
        preview = plan.preview()
        if args.json:
            print(
                json.dumps(
                    {
                        "correction": {
                            "instruction": (
                                "Rerun this preview with one complete corrected facts envelope."
                            ),
                            "supported": True,
                        },
                        "effects": {
                            "inventory_read": True,
                            "network_accessed": False,
                            "provider_or_account_inspected": False,
                            "resource_run": False,
                            "writes_performed": False,
                        },
                        "format": "atready-resource-quick-preview-v1",
                        "mapping": mapping,
                        "preview": preview,
                        "status": "preview-ready",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print("Quick Setup mappings (bundled proposal plus user-declared facts)")
            print(json.dumps(mapping, indent=2, sort_keys=True))
            _print_inventory_add_preview(preview)
        return 0

    result, uncertain = _inventory_add_receipt_result(
        plan,
        parsed.resource,
        expected_revision=args.expect_revision,
        expected_plan=args.expect_plan,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "effects": {
                        "inventory_read": True,
                        "network_accessed": False,
                        "provider_or_account_inspected": False,
                        "resource_run": False,
                        "writes_performed": True,
                    },
                    "format": "atready-resource-quick-apply-v1",
                    "mapping": mapping,
                    "receipt": result,
                    "status": "applied-with-uncertainty" if uncertain else "applied",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 4 if uncertain else 0
    return _print_inventory_add_receipt(result, resource=parsed.resource, uncertain=uncertain)


def _handle_resource_discover(args: argparse.Namespace) -> int:
    if args.inspect_version and args.executable is None:
        raise IntakeError(
            "version-probe-path-required",
            "version inspection requires an explicitly supplied absolute executable path",
        )
    if args.executable is not None and not Path(args.executable).is_absolute():
        raise IntakeError(
            "executable-not-allowed",
            "an explicitly supplied discovery executable must be an absolute path",
        )
    try:
        request = LocalDiscoveryRequest(
            profile=args.profile,
            executable=args.executable,
            probe_version=args.inspect_version,
        )
    except ValueError:
        raise IntakeError(
            "invalid-discovery-request",
            "local discovery request is outside the bounded input contract",
        ) from None
    result = discover_local_resource(request)
    payload = {
        "discovery_scope": "local-executable-only",
        **result.model_dump(mode="json"),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Bounded local executable discovery (no inventory write)")
        print(f"Profile: {result.profile_id}")
        print(f"Executable: {result.executable_name}")
        print(f"Search scope: {result.search_scope}")
        print(f"Installed: {str(result.installed).lower()}")
        print(f"Resolved path: {_terminal_safe(result.resolved_path or 'not located')}")
        print(f"Version probe performed: {str(result.version_probe_performed).lower()}")
        print(f"Version: {_terminal_safe(result.version or 'not observed')}")
        print(f"Evidence: {', '.join(result.evidence)}")
        print(f"Limitations: {', '.join(result.limitations)}")
        print("Authentication evaluated: false")
        print("Account status evaluated: false")
        print("Quota evaluated: false")
        print("Availability evaluated: false")
        print("AtReady network accessed: false")
        print("Inventory writes performed: false")
        print(f"External process executed: {str(result.external_process_executed).lower()}")
        print(f"External process side effects: {result.external_process_side_effects}")
    return 0


def _handle_inventory_validate(args: argparse.Namespace) -> int:
    path = _inventory_path(args.path)
    catalog = InventoryCatalog.from_path(path)
    valid = not (args.strict and catalog.warnings)
    if args.json:
        print(
            json.dumps(
                {
                    "fingerprint": "sha256:" + catalog.fingerprint(),
                    "inventory_kind": catalog.inventory.inventory_kind.value,
                    "path": str(path),
                    "revision_protection": catalog.inventory.revision_protection(),
                    "resources": len(catalog.inventory.resources),
                    "valid": valid,
                    "warnings": list(catalog.warnings),
                },
                sort_keys=True,
            )
        )
    else:
        status = "valid" if valid else "invalid in strict mode"
        print(f"Inventory is {status}: {len(catalog.inventory.resources)} resources")
        print(
            f"Revision privacy state: {catalog.inventory.revision_protection()} "
            "(presence only; imported nonce provenance is not verified)"
        )
        for warning in catalog.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
    return 0 if valid else 2


def _handle_inventory_snapshot(args: argparse.Namespace) -> int:
    catalog = InventoryCatalog.from_path(_inventory_path(args.path))
    snapshot = catalog.snapshot()
    if args.format == "yaml":
        print(dumps_yaml(snapshot), end="")
    else:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


def _handle_inventory_list(args: argparse.Namespace) -> int:
    current = read_inventory_file(_inventory_path(args.path))
    resources = [
        {
            "access": resource.access.status.value,
            "capabilities": sorted(resource.capabilities),
            "categories": sorted(resource.categories),
            "id": resource.id,
            "name": resource.name,
            "quota": resource.economics.quota.value,
        }
        for resource in sorted(current.inventory.resources, key=lambda item: item.id)
    ]
    result = {
        "inventory_kind": current.inventory.inventory_kind.value,
        "resources": resources,
        "revision": current.revision,
        "revision_protection": current.inventory.revision_protection(),
        "target": str(current.path),
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Inventory: {result['inventory_kind']} · {len(resources)} resources")
        print(f"Revision: {current.revision}")
        print(
            f"Revision privacy state: {result['revision_protection']} "
            "(presence only; imported nonce provenance is not verified)"
        )
        for resource in resources:
            print(
                f"- {_terminal_safe(resource['id'])}: {_terminal_safe(resource['name'])} "
                f"(access={resource['access']}, quota={resource['quota']})"
            )
    return 0


def _require_preview_apply_contract(args: argparse.Namespace, *, subject: str) -> None:
    if args.apply and (not args.expect_revision or not args.expect_plan):
        raise ConfigurationError(
            f"--apply requires --expect-revision and --expect-plan from a prior {subject} preview"
        )
    if (args.expect_revision or args.expect_plan) and not args.apply:
        raise ConfigurationError("--expect-revision and --expect-plan are only valid with --apply")


def _annotation_private_notes(args: argparse.Namespace) -> str:
    if args.annotation_file is not None:
        return load_inventory_annotation_declaration_file(args.annotation_file).private_notes
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        raise ConfigurationError("--annotation-stdin requires binary standard input")
    return load_inventory_annotation_declaration_stdin(stream).private_notes


def _handle_inventory_annotation(args: argparse.Namespace, private_notes: str | None) -> int:
    _require_preview_apply_contract(args, subject="inventory annotation")
    plan = plan_inventory_annotation(_inventory_path(args.path), private_notes)
    if not args.apply:
        result = plan.preview()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Inventory annotation preview (no files changed)")
            print(f"Target: {_terminal_safe(result['target'])}")
            print(f"Private notes effect: {result['private_notes_effect']}")
            print("Private notes: value omitted and bound to this plan.")
            print(f"Expected revision: {result['expect_revision']}")
            print(f"Expected plan: {result['expect_plan']}")
            print("Applying will canonicalize YAML and create a private exact-byte backup.")
        return 0

    receipt = commit_inventory_annotation(
        plan,
        expected_revision=args.expect_revision,
        expected_plan=args.expect_plan,
    )
    result = receipt.as_dict()
    result.update(
        {
            "private_notes_bound_to_plan": True,
            "private_notes_effect": plan.private_notes_effect,
            "private_notes_exposed": False,
            "candidate_revision_protection": plan.revision_protection,
            "observed_revision_protection": (
                plan.revision_protection
                if receipt.replacement_verified and receipt.revision == receipt.candidate_revision
                else None
            ),
        }
    )
    uncertain = (
        not receipt.replacement_verified
        or bool(receipt.warnings)
        or (os.name == "posix" and not receipt.directory_synced)
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Updated inventory annotation in {_terminal_safe(receipt.target)}")
        print(f"Private notes effect: {plan.private_notes_effect}")
        print(f"Candidate revision: {receipt.candidate_revision}")
        print(f"Replacement verified: {str(receipt.replacement_verified).lower()}")
        print(f"Backup ID: {receipt.backup_id}")
        print(f"Backup path: {_terminal_safe(receipt.backup_path)}")
        for warning in receipt.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
        if uncertain:
            print(
                "warning: update may already be applied; do not retry this apply; "
                "inspect the target and backup before another update",
                file=sys.stderr,
            )
    return 4 if uncertain else 0


def _handle_inventory_annotation_set(args: argparse.Namespace) -> int:
    return _handle_inventory_annotation(args, _annotation_private_notes(args))


def _handle_inventory_annotation_clear(args: argparse.Namespace) -> int:
    return _handle_inventory_annotation(args, None)


def _print_inventory_add_preview(result: dict[str, Any], *, guided: bool = False) -> None:
    print("Inventory addition preview (no files changed)")
    print(f"Target: {_terminal_safe(result['target'])}")
    print(f"Resource: {result['resource_id']}")
    print(f"Resource count: {result['resource_count_before']} -> {result['resource_count_after']}")
    print(f"Expected revision: {result['expect_revision']}")
    print(f"Expected plan: {result['expect_plan']}")
    print("Candidate resource (all persisted routing fields):")
    print(json.dumps(result["resource"], indent=2, sort_keys=True))
    if result["private_notes_present"]:
        print(
            "Private notes: present; value omitted and bound to this plan. "
            "Review it in the declaration source before approval."
        )
    else:
        print("Private notes: absent; that state is bound to this plan.")
    if result["defaulted_fields"]:
        print("Defaulted fields: " + ", ".join(result["defaulted_fields"]))
    _print_intake_review(result["intake_review"])
    print("Applying will canonicalize YAML and create a private exact-byte backup.")
    if not guided:
        print(
            "Rerun with --apply --expect-revision <revision> --expect-plan <plan> "
            "after reviewing this preview."
        )


def _inventory_add_receipt_result(
    plan: Any,
    resource: Any,
    *,
    expected_revision: str,
    expected_plan: str,
) -> tuple[dict[str, Any], bool]:
    receipt = commit_add_resource(
        plan,
        expected_revision=expected_revision,
        expected_plan=expected_plan,
    )
    result = receipt.as_dict()
    result["resource_id"] = resource.id
    result["private_notes_bound_to_plan"] = True
    result["private_notes_exposed"] = False
    result["private_notes_present"] = resource.private_notes is not None
    result["candidate_revision_protection"] = plan.revision_protection
    result["observed_revision_protection"] = (
        plan.revision_protection
        if receipt.replacement_verified and receipt.revision == receipt.candidate_revision
        else None
    )
    uncertain = (
        not receipt.replacement_verified
        or bool(receipt.warnings)
        or (os.name == "posix" and not receipt.directory_synced)
    )
    return result, uncertain


def _print_inventory_add_receipt(
    result: dict[str, Any],
    *,
    resource: Any,
    uncertain: bool,
) -> int:
    if uncertain:
        print(
            f"Resource add state is uncertain for {resource.id!r} at "
            f"{_terminal_safe(result['target'])}"
        )
    else:
        print(f"Added resource {resource.id!r} to {_terminal_safe(result['target'])}")
    print(f"Candidate revision: {result['candidate_revision']}")
    print(f"Candidate revision privacy state: {result['candidate_revision_protection']}")
    print(f"Observed revision: {result['revision'] or 'unavailable'}")
    print(
        "Observed revision privacy state: "
        f"{result['observed_revision_protection'] or 'unavailable'}"
    )
    print(f"Replacement verified: {str(result['replacement_verified']).lower()}")
    print(f"Backup ID: {result['backup_id']}")
    print(f"Backup path: {_terminal_safe(result['backup_path'])}")
    if not result["directory_synced"]:
        print("warning: parent-directory fsync was unavailable", file=sys.stderr)
    for warning in result["warnings"]:
        print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
    if uncertain:
        print(
            "warning: update may already be applied; do not retry this apply; "
            "inspect the target and backup before another update",
            file=sys.stderr,
        )
    return 4 if uncertain else 0


def _commit_inventory_add(
    plan: Any,
    resource: Any,
    *,
    expected_revision: str,
    expected_plan: str,
    json_output: bool,
) -> int:
    result, uncertain = _inventory_add_receipt_result(
        plan,
        resource,
        expected_revision=expected_revision,
        expected_plan=expected_plan,
    )
    if json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 4 if uncertain else 0
    return _print_inventory_add_receipt(result, resource=resource, uncertain=uncertain)


def _print_guided_recap(parsed: ParsedResourceDeclaration, target: Path) -> None:
    resource = parsed.resource
    review = resource_intake_review(resource, parsed.defaulted_fields).as_dict()
    data_ceiling = max(
        resource.policy.allowed_data_classes,
        key=_DATA_SENSITIVITY_LADDER.index,
    )
    print("\nREVIEW WHAT ATREADY UNDERSTOOD")
    print(f"Resource: {_terminal_safe(resource.name)} ({_terminal_safe(resource.id)})")
    print("Categories: " + ", ".join(_terminal_safe(item) for item in resource.categories))
    print(
        "Capabilities: "
        + ", ".join(
            f"{_terminal_safe(name)} {score:.2f}" for name, score in resource.capabilities.items()
        )
    )
    print(
        "Readiness: "
        f"{resource.access.status.value}; {resource.access.current_session.value}; "
        f"usage {resource.economics.quota.value}; {resource.access.interaction.value}"
    )
    print(
        "Safety: data up to "
        f"{data_ceiling.value}; "
        f"internet {'required' if resource.policy.requires_network else 'not required'}; "
        "separate approval required"
    )
    cost_is_default = "economics.marginal_cost" in parsed.defaulted_fields
    cost_label = "baseline default" if cost_is_default else "declared"
    print(
        f"Cost: {resource.economics.billing.value}; "
        f"relative cost {resource.economics.marginal_cost:.2f} ({cost_label})"
    )
    print(
        f"Evidence: {resource.provenance.basis.value}; "
        f"checked {resource.provenance.last_verified or 'unknown'}"
    )
    print("Quick defaults: eight comparison ratings at 0.5; manual text handoff; no private note")
    print(f"Selection facts: {review['selection_fact_status']}")
    if review["selection_fact_status"] == "requires-verification":
        labels = {
            "access.status": "access",
            "access.current_session": "current availability",
            "economics.quota": "usage room",
            "provenance.basis": "evidence basis",
            "provenance.last_verified": "checked date",
        }
        unresolved = ", ".join(
            labels.get(path, path) for path in review["unverified_selection_facts"]
        )
        print(
            f"AtReady will not normally select this resource until these facts are confirmed: "
            f"{unresolved}. A project can separately allow unverified resources."
        )
    print(f"Inventory: {_terminal_safe(target)}")
    print("These are your declarations; AtReady did not verify them. No files changed.")


def _print_guided_inventory_add_preview(result: dict[str, Any]) -> None:
    resource = result["resource"]
    access = resource["access"]
    economics = resource["economics"]
    policy = resource["policy"]
    provenance = resource["provenance"]
    handoff = resource["handoff"]
    print("COMPLETE NO-WRITE PREVIEW")
    print("Target:")
    print(f"  {_terminal_safe(result['target'])}")
    print(
        f"Resource: {_terminal_safe(resource['name'])} "
        f"({_terminal_safe(resource['id'])}); "
        f"count {result['resource_count_before']} -> {result['resource_count_after']}"
    )
    print("Categories: " + ", ".join(_terminal_safe(item) for item in resource["categories"]))
    print("Capabilities:")
    for name, score in resource["capabilities"].items():
        print(f"  {_terminal_safe(name)}: {score:.2f}")
    print(f"Access: {access['status']}; {access['current_session']}; {access['interaction']}")
    capacity = economics.get("capacity")
    capacity_label = "none" if capacity is None else json.dumps(capacity, sort_keys=True)
    cost_label = (
        "baseline default"
        if "economics.marginal_cost" in result["defaulted_fields"]
        else "declared"
    )
    print(
        f"Billing: {economics['billing']}; relative cost "
        f"{economics['marginal_cost']:.2f} ({cost_label})"
    )
    print(f"Usage: quota {economics['quota']}; exact capacity {_terminal_safe(capacity_label)}")
    rating_items = [f"{name} {score:.2f}" for name, score in resource["ratings"].items()]
    print("Comparison ratings:")
    for offset in range(0, len(rating_items), 2):
        print("  " + ", ".join(rating_items[offset : offset + 2]))
    print(
        "Allowed data: "
        + ", ".join(_terminal_safe(item) for item in policy["allowed_data_classes"])
    )
    print(f"Internet required: {str(policy['requires_network']).lower()}")
    print(f"Separate approval required: {str(policy['approval_required']).lower()}")
    print(
        "Provenance: "
        f"{provenance['basis']}; last checked {provenance['last_verified'] or 'unknown'}"
    )
    print(
        f"Handoff: {_terminal_safe(handoff['method'])}; instructions "
        f"{'present' if handoff.get('instructions') else 'none'}"
    )
    print(
        "Best for: "
        + (", ".join(_terminal_safe(item) for item in resource["best_for"]) or "none declared")
    )
    print(
        "Avoid for: "
        + (", ".join(_terminal_safe(item) for item in resource["avoid_for"]) or "none declared")
    )
    print("Private notes: absent")
    print("Defaults used:")
    scoring_defaults = "comparison ratings"
    if "economics.marginal_cost" in result["defaulted_fields"]:
        scoring_defaults += ", relative cost"
    print(f"  {scoring_defaults}, and handoff shown above")
    print("  advisory lists empty; exact capacity absent")
    review = result["intake_review"]
    print(f"Selection facts: {review['selection_fact_status']}")
    print("Route eligibility: not evaluated")
    print("Expected revision:")
    print(f"  {result['expect_revision']}")
    print("Expected plan:")
    print(f"  {result['expect_plan']}")
    print("On save: private exact-byte backup + atomic inventory replacement.")
    print("No files changed.")


def _handle_guided_add(args: argparse.Namespace) -> int:
    if not _guided_terminal_available():
        raise ConfigurationError(
            "'atready add' is interactive and requires a terminal; "
            "use 'atready inventory add --help' for non-interactive input"
        )

    target = _inventory_path(args.path)
    try:
        target.lstat()
    except FileNotFoundError:
        safe_target = _terminal_safe(target)
        failure = ConfigurationError(f"personal inventory does not exist: {safe_target}")
        failure.add_note(f"Create it first with: atready init --path {safe_target}")
        raise failure from None
    except OSError:
        pass
    current = read_inventory_file(target)
    if current.inventory.inventory_kind is not InventoryKind.PERSONAL:
        raise ConfigurationError("demo inventories are read-only; initialize a personal inventory")
    try:
        target = current.path.resolve(strict=True)
    except OSError:
        raise ConfigurationError("cannot resolve the inventory's canonical path") from None

    commit_started = False
    try:
        print("ADD A RESOURCE")
        print(f"Inventory: {_terminal_safe(target)}")
        print(
            "AtReady will use only what you declare. It will not scan apps, inspect accounts, "
            "contact providers, or run this resource."
        )
        print("Do not enter credentials or private notes.")
        if not _guided_yes_no("Use this inventory?", default=True):
            raise _GuidedAddCancelledError

        profile = (
            resource_profile(args.profile) if args.profile is not None else _guided_profile(None)
        )
        parsed = _guided_resource_from_profile(profile)
        print(
            "\nQuick Add defaults: eight comparison ratings at 0.5, ask before use, "
            "manual text handoff, no private note."
        )
        if not _guided_yes_no("Use these Quick Add defaults?", default=True):
            print("Use 'atready inventory add --help' for detailed setup. No files changed.")
            return 0

        _print_guided_recap(parsed, target)
        if not _guided_yes_no("Preview this addition?", default=False):
            raise _GuidedAddCancelledError

        plan = plan_add_resource(
            target,
            parsed.resource,
            defaulted_fields=parsed.defaulted_fields,
        )
        preview = plan.preview()
        print()
        _print_guided_inventory_add_preview(preview)
        confirmation = _guided_read(
            f"Type 'save {parsed.resource.id}' to save exactly this preview"
        )
        if confirmation != f"save {parsed.resource.id}":
            raise _GuidedAddCancelledError

        commit_started = True
        return _commit_inventory_add(
            plan,
            parsed.resource,
            expected_revision=preview["expect_revision"],
            expected_plan=preview["expect_plan"],
            json_output=False,
        )
    except _GuidedAddCancelledError:
        print("Cancelled. No files changed.")
        return 0
    except EOFError:
        print("error: guided input ended before saving; no files changed", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(file=sys.stderr)
        if commit_started:
            print(
                "error: interrupted while saving; state may be uncertain. Inspect the inventory "
                "and backups before retrying.",
                file=sys.stderr,
            )
        else:
            print("Cancelled. No files changed.", file=sys.stderr)
        return 130


def _guided_project_capabilities(inventory: Inventory) -> tuple[str, ...]:
    return tuple(
        sorted(
            {capability for resource in inventory.resources for capability in resource.capabilities}
        )
    )


def _print_guided_plan_capabilities(inventory: Inventory, capabilities: Sequence[str]) -> None:
    print("Declared capabilities:")
    for index, capability in enumerate(capabilities, start=1):
        resource_names = sorted(
            resource.name for resource in inventory.resources if capability in resource.capabilities
        )
        names = ", ".join(_terminal_safe(name) for name in resource_names)
        print(f"  {index}. {capability} ({names})")


def _print_guided_quick_capabilities(capabilities: Sequence[str]) -> None:
    print("Capabilities in your roster:")
    for index, capability in enumerate(capabilities, start=1):
        print(f"  {index}. {capability}")


def _guided_project_from_inventory(inventory: Inventory) -> ProjectBrief:
    capabilities = _guided_project_capabilities(inventory)
    if not capabilities:
        raise ConfigurationError("the inventory has no declared capabilities")

    goal = ""
    while not goal:
        goal = _guided_plan_read("What are you trying to accomplish?")
        if not goal:
            print("Enter a project goal, or type cancel.")

    step_count = _guided_plan_choice(
        "How many steps should AtReady route? [1/2/3]",
        {"1": 1, "2": 2, "3": 3},
        default="1",
    )
    _print_guided_plan_capabilities(inventory, capabilities)
    workstreams: list[dict[str, Any]] = []
    for index in range(1, step_count + 1):
        step = ""
        while not step:
            step = _guided_plan_read(f"Step {index}")
            if not step:
                print("Enter a step, or type cancel.")
        selected = _guided_plan_numbered_selection(
            f"Capability numbers needed for step {index}",
            capabilities,
        )
        minimum = _guided_plan_choice(
            "Minimum capability strength [basic/solid/strong/exceptional]",
            _GUIDED_STRENGTHS,
            default="basic",
        )
        expected_result = ""
        while not expected_result:
            expected_result = _guided_plan_read(f"Expected result for step {index}")
            if not expected_result:
                print("Enter the result this step should produce, or type cancel.")
        verification = ""
        while not verification:
            verification = _guided_plan_read(f"How will you check step {index}?")
            if not verification:
                print("Enter one way to check the result, or type cancel.")
        workstreams.append(
            {
                "id": f"step-{index}",
                "name": step[:120],
                "objective": step,
                "required_capabilities": [
                    {"id": capability, "importance": 1.0, "minimum": minimum}
                    for capability in selected
                ],
                "inputs": ["The user-provided project goal"],
                "allowed_scope": [step],
                "exclusions": ["Anything outside this step"],
                "deliverable": expected_result,
                "acceptance_criteria": [expected_result],
                "verification": [verification],
                "stop_conditions": [
                    "Stop before using any resource without separate authorization"
                ],
                "next_owner": "User",
            }
        )

    print("\nEligibility controls decide which declared resources may be considered.")
    use_defaults = _guided_plan_yes_no(
        "Use standard eligibility? Public data, internet allowed, any workflow and cost, "
        "verified facts only",
        default=True,
    )
    constraints: dict[str, Any] = {}
    if not use_defaults:
        constraints["data_class"] = _guided_plan_choice(
            "Project data sensitivity [public/internal/private/sensitive]",
            {item.value: item.value for item in DataClass},
            default=DataClass.PUBLIC.value,
        )
        constraints["network_allowed"] = _guided_plan_yes_no(
            "May resources that require internet be considered?", default=True
        )
        constraints["allow_unverified"] = _guided_plan_yes_no(
            "May resources with unverified eligibility facts be considered?", default=False
        )
        constraints["max_marginal_cost"] = _guided_plan_choice(
            "Maximum relative cost per use [low/medium/high/any]",
            {"low": 0.25, "medium": 0.5, "high": 0.75, "any": 1.0},
            default="any",
        )
        constraints["allowed_interactions"] = _guided_plan_interactions()
        print("Resources that can be excluded:")
        resource_ids = tuple(resource.id for resource in inventory.resources)
        for index, resource in enumerate(inventory.resources, start=1):
            print(f"  {index}. {_terminal_safe(resource.name)} ({resource.id})")
        constraints["forbidden_resources"] = list(
            _guided_plan_numbered_selection(
                "Resource numbers to exclude [none]",
                resource_ids,
                allow_none=True,
            )
        )

    return ProjectBrief.model_validate(
        {
            "schema_version": 1,
            "id": "guided-plan",
            "name": "Guided AtReady plan",
            "goal": goal,
            "as_of": date.today(),
            "constraints": constraints,
            "workstreams": workstreams,
        }
    )


def _guided_quick_project_from_inventory(inventory: Inventory) -> ProjectBrief:
    capabilities = _guided_project_capabilities(inventory)
    if not capabilities:
        raise ConfigurationError("the inventory has no declared capabilities")

    work = ""
    while not work:
        work = _guided_plan_read("What should your resources help with?")
        if not work:
            print("Describe one piece of work, or type cancel.")

    _print_guided_quick_capabilities(capabilities)
    selected = _guided_plan_numbered_selection(
        "Capability numbers this work needs",
        capabilities,
    )
    return ProjectBrief.model_validate(
        {
            "schema_version": 1,
            "id": "guided-quick-fit",
            "name": "Quick Fit",
            "goal": work,
            "as_of": date.today(),
            "constraints": {},
            "workstreams": [
                {
                    "id": "work",
                    "name": work[:120],
                    "objective": work,
                    "required_capabilities": [
                        {"id": capability, "importance": 1.0, "minimum": 0.40}
                        for capability in selected
                    ],
                    "inputs": ["The user-provided work description"],
                    "allowed_scope": [work],
                    "exclusions": ["Anything outside this work"],
                    "deliverable": work,
                    "acceptance_criteria": ["The user confirms the work meets the stated goal"],
                    "verification": ["User review against the stated goal"],
                    "stop_conditions": [
                        "Stop before using any resource without separate authorization"
                    ],
                    "next_owner": "User",
                }
            ],
        }
    )


def _print_guided_plan_recap(project: ProjectBrief) -> None:
    constraints = project.constraints
    print("\nREVIEW WHAT ATREADY UNDERSTOOD")
    print(f"Goal: {_terminal_safe(project.goal)}")
    strength_scale = ", ".join(f"{label} {value:.2f}" for label, value in _GUIDED_STRENGTHS.items())
    print(f"Strength scale: {strength_scale}")
    for index, workstream in enumerate(project.workstreams, start=1):
        minimum_labels = {value: label for label, value in _GUIDED_STRENGTHS.items()}
        capabilities = ", ".join(
            f"{item.id} (minimum {minimum_labels.get(item.minimum, 'custom')}: {item.minimum:.2f})"
            for item in workstream.required_capabilities
        )
        print(f"Step {index}: {_terminal_safe(workstream.objective)}")
        print(f"  Needs: {capabilities}")
        print(f"  Expected result: {_terminal_safe(workstream.deliverable)}")
        print(f"  Check: {_terminal_safe(workstream.verification[0])}")
    interaction_labels = {
        InteractionMode.CODEX_CALLABLE: "Codex",
        InteractionMode.LOCAL_CLI: "terminal",
        InteractionMode.EXTERNAL_AGENT: "separate app or agent",
        InteractionMode.MANUAL: "manual",
    }
    interactions = ", ".join(interaction_labels[item] for item in constraints.allowed_interactions)
    cost_labels = {0.25: "low", 0.5: "medium", 0.75: "high", 1.0: "any declared cost"}
    maximum_cost = cost_labels.get(
        constraints.max_marginal_cost,
        f"relative score {constraints.max_marginal_cost:.2f}",
    )
    print(
        "Eligibility: "
        f"{constraints.data_class.value} data; "
        f"internet {'allowed' if constraints.network_allowed else 'not allowed'}; "
        f"maximum cost {maximum_cost}; "
        f"workflows {interactions}; "
        f"unverified facts {'allowed' if constraints.allow_unverified else 'not allowed'}"
    )
    if constraints.forbidden_resources:
        print("Excluded resources: " + ", ".join(constraints.forbidden_resources))
    print("No project file will be written. No resource will be contacted or run.")


def _print_guided_quick_recap(project: ProjectBrief) -> None:
    workstream = project.workstreams[0]
    capabilities = _bounded_terminal_items([item.id for item in workstream.required_capabilities])
    print("\nQUICK FIT REVIEW")
    print(f"Work: {_bounded_terminal_text(workstream.objective)}")
    print(f"Needs: {capabilities} (basic or better)")
    print("Eligibility: public data; internet allowed; any workflow or cost; verified facts only")
    print("For private data or other limits, choose edit and rerun with --mode detailed.")
    print("Nothing will be written, contacted, purchased, or run.")


def _handle_guided_plan(args: argparse.Namespace) -> int:
    if args.width is not None and args.format != "summary":
        raise ConfigurationError("--width is only available with --format summary")
    if not _guided_terminal_available():
        raise ConfigurationError(
            "'atready plan' is interactive and requires a terminal; "
            "use 'atready route --help' for non-interactive input"
        )

    target = _inventory_path(args.inventory)
    catalog = InventoryCatalog.from_path(target, today=date.today())
    if not catalog.inventory.resources:
        raise ConfigurationError("personal inventory has no resources")
    if catalog.inventory.inventory_kind is InventoryKind.DEMO and not args.allow_demo:
        failure = ConfigurationError("demo inventories require explicit routing permission")
        failure.add_note("Retry this synthetic example with: atready plan --allow-demo")
        raise failure

    try:
        print("CHECK RESOURCE FIT")
        print(f"Inventory: {_terminal_safe(target)}")
        print(
            "AtReady will use only your declared roster. It will not write a project file, "
            "contact a resource, spend a credit, or run any work."
        )
        print("Do not enter credentials or secrets. Type cancel at any prompt.\n")
        while True:
            if args.mode == "quick":
                project = _guided_quick_project_from_inventory(catalog.inventory)
                _print_guided_quick_recap(project)
                approval_prompt = "Check this resource fit?"
            else:
                project = _guided_project_from_inventory(catalog.inventory)
                _print_guided_plan_recap(project)
                approval_prompt = "Check resource fit for these steps?"
            approval = _guided_plan_approval(approval_prompt)
            if approval == "yes":
                break
            if approval == "no":
                raise _GuidedPlanCancelledError
            print("Let's revise the project details. The previous recap was not routed.\n")
        plan = route(catalog.inventory, project, allow_demo=args.allow_demo)
        print()
        return _emit_route_plan(
            plan,
            project,
            output_format=args.format,
            width=args.width or 80,
        )
    except _GuidedPlanCancelledError:
        print("Cancelled. No files changed and no resources were run.")
        return 0
    except EOFError:
        print(
            "error: guided input ended before planning; no files changed and no resources were run",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print(file=sys.stderr)
        print("Cancelled. No files changed and no resources were run.", file=sys.stderr)
        return 130


def _handle_inventory_add(args: argparse.Namespace) -> int:
    _require_preview_apply_contract(args, subject="addition")
    parsed = _resource_input(args)
    resource = parsed.resource
    plan = plan_add_resource(
        _inventory_path(args.path),
        resource,
        defaulted_fields=parsed.defaulted_fields,
    )
    if not args.apply:
        result = plan.preview()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            _print_inventory_add_preview(result)
        return 0

    return _commit_inventory_add(
        plan,
        resource,
        expected_revision=args.expect_revision,
        expected_plan=args.expect_plan,
        json_output=args.json,
    )


def _handle_inventory_replace(args: argparse.Namespace) -> int:
    _require_details_compatible(args)
    _require_preview_apply_contract(args, subject="resource replacement")
    parsed = _resource_input(args)
    plan = plan_replace_resource(
        _inventory_path(args.path),
        parsed.resource,
        defaulted_fields=parsed.defaulted_fields,
    )
    if not args.apply:
        result = plan.preview()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Replace resource preview. Nothing changed.")
            print(f"Target: {_terminal_safe(result['target'])}")
            print(
                f"Resource: {_terminal_safe(result['resource_after']['name'])} "
                f"({_terminal_safe(result['resource_id'])})"
            )
            print(
                "Changes: "
                + _resource_change_summary(result["resource_before"], result["resource_after"])
            )
            print(f"Private notes effect: {result['private_notes_effect']}")
            review = result["intake_review"]
            default_count = sum(len(values) for values in review["default_groups"].values())
            print(
                f"Check: {len(review['unverified_selection_facts'])} routing facts unverified; "
                f"{default_count} values use defaults."
            )
            print("This is a full replacement. Omitted fields use declared defaults.")
            if args.details:
                print("Current resource (private notes omitted):")
                print(json.dumps(result["resource_before"], indent=2, sort_keys=True))
                print("Replacement resource (private notes omitted):")
                print(json.dumps(result["resource_after"], indent=2, sort_keys=True))
                if result["defaulted_fields"]:
                    print("Defaulted fields: " + ", ".join(result["defaulted_fields"]))
                _print_intake_review(review)
            else:
                print("Use --details for complete sanitized before/after evidence.")
            print(f"Expected revision: {result['expect_revision']}")
            print(f"Expected plan: {result['expect_plan']}")
            print(
                "On apply: create a private exact-byte backup, then replace the roster atomically."
            )
            print(
                "Next: rerun with --apply --expect-revision <revision> "
                "--expect-plan <plan> using the values above."
            )
        return 0

    receipt = commit_replace_resource(
        plan,
        expected_revision=args.expect_revision,
        expected_plan=args.expect_plan,
    )
    result = receipt.as_dict()
    result.update(
        {
            "resource_id": plan.resource.id,
            "private_notes_bound_to_plan": True,
            "private_notes_effect": plan.preview()["private_notes_effect"],
            "private_notes_exposed": False,
            "candidate_revision_protection": plan.revision_protection,
            "observed_revision_protection": (
                plan.revision_protection
                if receipt.replacement_verified and receipt.revision == receipt.candidate_revision
                else None
            ),
        }
    )
    uncertain = (
        not receipt.replacement_verified
        or bool(receipt.warnings)
        or (os.name == "posix" and not receipt.directory_synced)
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Replaced resource {plan.resource.id!r} in {_terminal_safe(receipt.target)}")
        print(f"Candidate revision: {receipt.candidate_revision}")
        print(f"Replacement verified: {str(receipt.replacement_verified).lower()}")
        print(f"Backup ID: {receipt.backup_id}")
        print(f"Backup path: {_terminal_safe(receipt.backup_path)}")
        for warning in receipt.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
        if uncertain:
            print(
                "warning: update may already be applied; do not retry this apply; "
                "inspect the target and backup before another update",
                file=sys.stderr,
            )
    return 4 if uncertain else 0


def _handle_inventory_remove(args: argparse.Namespace) -> int:
    _require_details_compatible(args)
    _require_preview_apply_contract(args, subject="resource removal")
    plan = plan_remove_resource(_inventory_path(args.path), args.resource)
    if not args.apply:
        result = plan.preview()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Remove resource preview. Nothing changed.")
            print(f"Target: {_terminal_safe(result['target'])}")
            print(
                f"Resource: {_terminal_safe(result['resource']['name'])} "
                f"({_terminal_safe(result['resource_id'])})"
            )
            print(
                f"Roster: {result['resource_count_before']} -> "
                f"{result['resource_count_after']} resources"
            )
            capabilities = sorted(result["resource"]["capabilities"])
            note_state = (
                "present; removed with the resource"
                if result["private_notes_present"]
                else "absent"
            )
            print(
                f"Capabilities: {_bounded_terminal_items(capabilities)}. "
                f"Private notes: {note_state}; values are never shown."
            )
            if args.details:
                print("Resource to remove (private notes omitted):")
                print(json.dumps(result["resource"], indent=2, sort_keys=True))
            else:
                print("Use --details for the complete sanitized resource.")
            print(f"Expected revision: {result['expect_revision']}")
            print(f"Expected plan: {result['expect_plan']}")
            print("On apply: create a private exact-byte safety backup, then remove this resource.")
            print(
                "Next: rerun with --apply --expect-revision <revision> "
                "--expect-plan <plan> using the values above."
            )
        return 0

    receipt = commit_remove_resource(
        plan,
        expected_revision=args.expect_revision,
        expected_plan=args.expect_plan,
    )
    result = receipt.as_dict()
    result.update(
        {
            "resource_id": plan.resource.id,
            "private_notes_exposed": False,
            "private_notes_present": plan.resource.private_notes is not None,
            "candidate_revision_protection": plan.revision_protection,
            "observed_revision_protection": (
                plan.revision_protection
                if receipt.replacement_verified and receipt.revision == receipt.candidate_revision
                else None
            ),
        }
    )
    uncertain = (
        not receipt.replacement_verified
        or bool(receipt.warnings)
        or (os.name == "posix" and not receipt.directory_synced)
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Removed resource {plan.resource.id!r} from {_terminal_safe(receipt.target)}")
        print(f"Candidate revision: {receipt.candidate_revision}")
        print(f"Replacement verified: {str(receipt.replacement_verified).lower()}")
        print(f"Safety backup ID: {receipt.backup_id}")
        print(f"Safety backup path: {_terminal_safe(receipt.backup_path)}")
        for warning in receipt.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
        if uncertain:
            print(
                "warning: removal may already be applied; do not retry this apply; "
                "inspect the target and backup before another update",
                file=sys.stderr,
            )
    return 4 if uncertain else 0


def _handle_inventory_backup_list(args: argparse.Namespace) -> int:
    listing = list_inventory_backups(_inventory_path(args.path))
    result = listing.as_dict()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Inventory backups for {_terminal_safe(listing.target)}")
        print(f"Active state: {listing.active_state}")
        print(f"Active revision: {listing.active_revision or 'unavailable'}")
        print(f"Active revision protection: {listing.active_revision_protection or 'unavailable'}")
        print(f"Validated backups: {len(listing.backups)}")
        for backup in listing.backups:
            print(
                f"- {backup.backup_id} · {backup.resource_count} resources · active-match="
                f"{str(backup.matches_active).lower()}"
            )
            print(f"  revision protection: {backup.revision_protection}")
            print(
                "  filesystem modified metadata (not backup history): "
                f"{backup.filesystem_modified_at}"
            )
        for warning in listing.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
    return 0


def _handle_inventory_backup_manifest(args: argparse.Namespace) -> int:
    manifest = inspect_inventory_backup_manifest(_inventory_path(args.path))
    result = manifest.as_dict()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Backup operation manifest for {_terminal_safe(manifest.target)}")
        print(f"Initialized: {str(manifest.initialized).lower()}")
        print("Authoritative order: sequence (wall-clock timestamps are metadata only)")
        print("Tamper evidence: local hash chain; not a signature or trusted clock")
        print(f"Validated events: {len(manifest.events)}")
        for event in manifest.events:
            operation = event.operation or "baseline"
            print(f"- {event.sequence}: {operation} · {event.phase} · {event.event_hash}")
        for warning in manifest.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
    return 0


def _handle_inventory_backup_inspect(args: argparse.Namespace) -> int:
    _require_details_compatible(args)
    inspection = inspect_inventory_backup(_inventory_path(args.path), args.backup)
    result = inspection.as_dict()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Backup comparison. Nothing changed.")
        print(f"Backup: {inspection.backup.backup_id}")
        print(f"Target: {_terminal_safe(inspection.target)}")
        print(f"Active state: {inspection.active_state}")
        if inspection.comparison is not None:
            active_count = _snapshot_resource_count(inspection.active_snapshot)
            backup_count = _snapshot_resource_count(inspection.backup_snapshot)
            print(f"Roster in backup: {active_count} -> {backup_count} resources")
            print("Using it would " + _comparison_change_summary(inspection.comparison))
            print(
                "Other changes: preferences "
                f"{inspection.comparison['preferences_change']}; roster notes "
                f"{inspection.comparison['inventory_private_notes']}; revision privacy state "
                f"{inspection.comparison['revision_privacy_nonce_effect']}."
            )
            print(
                "Private resource notes: "
                + _private_note_count_summary(inspection.comparison)
                + "; values are never shown."
            )
        else:
            print("Comparison unavailable because the active roster is not valid.")
        if args.details:
            print(f"Active revision: {inspection.active_revision or 'unavailable'}")
            print(
                "Active revision protection: "
                f"{inspection.active_revision_protection or 'unavailable'}"
            )
            print(f"Backup revision protection: {inspection.backup.revision_protection}")
            if inspection.comparison is not None:
                print("Sanitized comparison:")
                print(json.dumps(inspection.comparison, indent=2, sort_keys=True))
            if inspection.active_snapshot is not None:
                print("Sanitized active snapshot:")
                print(json.dumps(inspection.active_snapshot, indent=2, sort_keys=True))
            print("Sanitized backup snapshot:")
            print(json.dumps(inspection.backup_snapshot, indent=2, sort_keys=True))
        else:
            print("Use --details for complete sanitized snapshots or --json for machine evidence.")
    return 0


def _handle_inventory_backup_rollback(args: argparse.Namespace) -> int:
    _require_details_compatible(args)
    _require_preview_apply_contract(args, subject="rollback")
    plan = plan_inventory_rollback(_inventory_path(args.path), args.backup)
    if not args.apply:
        result = plan.preview()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Rollback preview. Nothing changed.")
            print(f"Target: {_terminal_safe(plan.target)}")
            print(f"Source backup: {plan.source_backup_id}")
            print(
                f"Roster: {_snapshot_resource_count(plan.active_snapshot)} -> "
                f"{_snapshot_resource_count(plan.candidate_snapshot)} resources"
            )
            print("Rollback would " + _comparison_change_summary(plan.comparison))
            print("Private notes: restored exactly from the backup; values are not shown.")
            if plan.comparison["revision_privacy_nonce_effect"] != "unchanged":
                print(
                    "Warning: rollback changes the hidden revision privacy state; confirm the "
                    "backup nonce was not exposed or reused."
                )
            if args.details:
                print(f"Current revision protection: {plan.active_revision_protection}")
                print(f"Restored revision protection: {plan.candidate_revision_protection}")
                print("Sanitized comparison:")
                print(json.dumps(plan.comparison, indent=2, sort_keys=True))
                print("Sanitized active snapshot:")
                print(json.dumps(plan.active_snapshot, indent=2, sort_keys=True))
                print("Sanitized rollback candidate snapshot:")
                print(json.dumps(plan.candidate_snapshot, indent=2, sort_keys=True))
            else:
                print("Use --details for complete sanitized snapshots.")
            print("On apply: create an exact safety backup, then restore this backup.")
            print(f"Expected revision: {plan.original_revision}")
            print(f"Expected plan: {plan.plan_token}")
            print(
                "Next: rerun with --apply --expect-revision <revision> "
                "--expect-plan <plan> using the values above."
            )
        return 0

    receipt = commit_inventory_rollback(
        plan,
        expected_revision=args.expect_revision,
        expected_plan=args.expect_plan,
    )
    result = receipt.as_dict()
    uncertain = (
        not receipt.update.replacement_verified
        or bool(receipt.update.warnings)
        or (os.name == "posix" and not receipt.update.directory_synced)
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Restored {_terminal_safe(receipt.target)} from {receipt.source_backup_id}")
        print(f"Restored revision: {receipt.update.candidate_revision}")
        print(f"Candidate revision privacy state: {receipt.candidate_revision_protection}")
        print(f"Observed revision: {receipt.update.revision or 'unavailable'}")
        print(
            "Observed revision privacy state: "
            f"{receipt.observed_revision_protection or 'unavailable'}"
        )
        print(f"Replacement verified: {str(receipt.update.replacement_verified).lower()}")
        print(f"Source backup retained: {_terminal_safe(receipt.source_backup_path)}")
        print(f"Safety backup ID: {receipt.update.backup_id}")
        print(f"Safety backup path: {_terminal_safe(receipt.update.backup_path)}")
        if not receipt.update.directory_synced:
            print("warning: parent-directory fsync was unavailable", file=sys.stderr)
        for warning in receipt.update.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
        if uncertain:
            print(
                "warning: rollback may already be applied; do not retry this apply; "
                "inspect the target and backups first",
                file=sys.stderr,
            )
    return 4 if uncertain else 0


def _handle_inventory_backup_recover(args: argparse.Namespace) -> int:
    if args.apply and (not args.expect_state or not args.expect_plan):
        raise ConfigurationError(
            "--apply requires --expect-state and --expect-plan from a prior recovery preview"
        )
    if (args.expect_state or args.expect_plan) and not args.apply:
        raise ConfigurationError("--expect-state and --expect-plan are only valid with --apply")
    plan = plan_inventory_recovery(_inventory_path(args.path), args.backup)
    if not args.apply:
        result = plan.preview()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Inventory disaster-recovery preview (no files changed)")
            print(f"Target: {_terminal_safe(plan.target)}")
            print(f"Active state: {plan.active_state}")
            print(f"Source backup: {plan.source_backup_id}")
            print(f"Restored revision: {plan.candidate_revision}")
            print(f"Restored revision protection: {plan.candidate_revision_protection}")
            print("Sanitized recovery candidate snapshot:")
            print(json.dumps(plan.candidate_snapshot, indent=2, sort_keys=True))
            if plan.active_state == "invalid":
                print("Applying will quarantine the exact invalid bytes before replacement.")
            else:
                print("The active target is missing, so no displaced bytes require quarantine.")
            print("The exact source backup will be retained.")
            print(f"Expected state: {plan.state_token}")
            print(f"Expected plan: {plan.plan_token}")
            print(
                "Rerun with --apply --expect-state <state> --expect-plan <plan> "
                "after reviewing this preview."
            )
        return 0

    receipt = commit_inventory_recovery(
        plan,
        expected_state=args.expect_state,
        expected_plan=args.expect_plan,
    )
    result = receipt.as_dict()
    uncertain = (
        not receipt.replacement_verified
        or bool(receipt.warnings)
        or (os.name == "posix" and not receipt.directory_synced)
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Recovered inventory at {_terminal_safe(receipt.target)}")
        print(f"Previous state: {receipt.previous_state}")
        print(f"Restored revision: {receipt.restored_revision}")
        print(f"Observed revision: {receipt.observed_revision or 'unavailable'}")
        print(f"Replacement verified: {str(receipt.replacement_verified).lower()}")
        print(f"Source backup retained: {_terminal_safe(receipt.source_backup_path)}")
        if receipt.quarantine_path is not None:
            print(f"Invalid bytes quarantined: {_terminal_safe(receipt.quarantine_path)}")
        for warning in receipt.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
        if uncertain:
            print(
                "warning: recovery may already be applied; do not retry blindly; "
                "inspect the target and backups first",
                file=sys.stderr,
            )
    return 4 if uncertain else 0


def _handle_inventory_backup_delete(args: argparse.Namespace) -> int:
    _require_preview_apply_contract(args, subject="backup deletion")
    plan = plan_inventory_backup_delete(
        _inventory_path(args.path),
        args.backup,
        allow_no_backups=args.allow_no_backups,
    )
    if not args.apply:
        result = plan.preview()
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Inventory backup deletion preview (no files changed)")
            print(f"Target: {_terminal_safe(plan.target)}")
            print(f"Backup: {plan.backup_id}")
            print(f"Backup path: {_terminal_safe(plan.backup_path)}")
            print(f"Selected revision privacy state: {plan.selected_revision_protection}")
            print(
                "Remaining revision privacy states: "
                + json.dumps(plan.remaining_revision_protection_counts, sort_keys=True)
            )
            print(
                f"Validated backup count: {plan.backup_count_before} -> "
                f"{plan.backup_count_before - 1}"
            )
            print("This deletion is irreversible; no automatic retention policy is applied.")
            print(f"Expected revision: {plan.original_revision}")
            print(f"Expected plan: {plan.plan_token}")
            for warning in plan.warnings:
                print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
            print(
                "Rerun with --apply --expect-revision <revision> --expect-plan <plan> "
                "after reviewing this preview."
            )
        return 0

    receipt = commit_inventory_backup_delete(
        plan,
        expected_revision=args.expect_revision,
        expected_plan=args.expect_plan,
    )
    result = receipt.as_dict()
    uncertain = not receipt.deletion_verified or bool(receipt.warnings)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Deleted backup {receipt.backup_id}")
        print(f"Deleted path: {_terminal_safe(receipt.backup_path)}")
        print(f"Deletion verified: {str(receipt.deletion_verified).lower()}")
        print(f"Remaining validated backups: {receipt.remaining_valid_backups}")
        print(f"Deleted revision privacy state: {receipt.selected_revision_protection}")
        print(
            "Remaining revision privacy states: "
            + (
                json.dumps(receipt.remaining_revision_protection_counts, sort_keys=True)
                if receipt.remaining_revision_protection_counts is not None
                else "unavailable"
            )
        )
        if not receipt.directory_synced:
            print("warning: backup-directory fsync was unavailable", file=sys.stderr)
        for warning in receipt.warnings:
            print(f"warning: {_terminal_safe(warning)}", file=sys.stderr)
        if uncertain:
            print(
                "warning: deletion may already be applied; do not retry blindly; "
                "list and inspect backups first",
                file=sys.stderr,
            )
    return 4 if uncertain else 0


def _handle_project_template(args: argparse.Namespace) -> int:
    del args
    print(starter_project(), end="")
    return 0


def _handle_project_validate(args: argparse.Namespace) -> int:
    project = project_from_path(args.path.expanduser())
    if args.json:
        print(
            json.dumps(
                {
                    "as_of": project.as_of.isoformat(),
                    "project_id": project.id,
                    "valid": True,
                    "workstreams": len(project.workstreams),
                },
                sort_keys=True,
            )
        )
    else:
        print(f"Project is valid: {len(project.workstreams)} workstreams")
    return 0


def _handle_route(args: argparse.Namespace) -> int:
    if args.width is not None and args.format not in {
        "summary",
        "agent-summary",
        "presentation",
    }:
        raise ConfigurationError(
            "--width is only available with --format summary, agent-summary, or presentation"
        )
    if (args.max_words is not None or args.max_lines is not None) and args.format != "presentation":
        raise ConfigurationError(
            "--max-words and --max-lines are only available with --format presentation"
        )
    project_path = args.project.expanduser()
    try:
        project = project_from_path(project_path)
    except ConfigurationError as exc:
        if "configuration file does not exist" in str(exc):
            exc.add_note("Use the guided resource fit check instead: atready plan")
            exc.add_note("Or create a project brief: atready project template > project.yaml")
        raise
    try:
        catalog = InventoryCatalog.from_path(_inventory_path(args.inventory), today=project.as_of)
    except ConfigurationError as exc:
        if "configuration file does not exist" in str(exc):
            exc.add_note("Create your roster first with: atready init")
        raise
    resource_state = (
        resource_state_from_path(args.resource_state) if args.resource_state is not None else None
    )
    if resource_state is None:
        plan = route(catalog.inventory, project, allow_demo=args.allow_demo)
    else:
        evaluated_at = datetime.now().astimezone()
        plan = route(
            catalog.inventory,
            project,
            allow_demo=args.allow_demo,
            resource_state=resource_state,
            resource_state_evaluated_at=evaluated_at,
        )
    width = args.width or 80
    if args.width is None and args.format == "presentation" and args.max_lines is not None:
        default_presentation = render_agent_presentation(
            plan,
            goal=project.goal,
            width=width,
            max_words=args.max_words,
            max_lines=args.max_lines,
        )
        if default_presentation.required_lines > args.max_lines:
            width = 120
    return _emit_route_plan(
        plan,
        project,
        output_format=args.format,
        width=width,
        max_words=args.max_words,
        max_lines=args.max_lines,
    )


def _handle_resource_state_validate(args: argparse.Namespace) -> int:
    state = resource_state_from_path(args.path)
    result = {
        "resources": len(state.snapshots),
        "schema_version": state.schema_version,
        "source_count": len({snapshot.source for snapshot in state.snapshots}),
        "scope": "schema-only",
        "valid": True,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            f"Resource-state file schema is valid: {result['resources']} resource snapshots. "
            "Routing separately checks roster, evaluation time, mode, and confidence."
        )
        print("No inventory was read or changed, and no provider was contacted.")
    return 0


def _handle_compare(args: argparse.Namespace) -> int:
    if args.width is not None and args.format != "summary":
        raise ConfigurationError("--width is only available with --format summary")
    baseline_project = project_from_path(args.project.expanduser())
    overrides_supplied = any(
        (
            args.data_class is not None,
            args.network_allowed is not None,
            args.allow_unverified is not None,
            args.max_marginal_cost is not None,
            bool(args.forbid_resource),
        )
    )
    if args.against is not None and overrides_supplied:
        raise ConfigurationError("choose --against or constraint overrides, not both")
    if args.against is not None:
        alternative_project = project_from_path(args.against.expanduser())
    elif overrides_supplied:
        constraint_values = baseline_project.constraints.model_dump(mode="json")
        if args.data_class is not None:
            constraint_values["data_class"] = args.data_class
        if args.network_allowed is not None:
            constraint_values["network_allowed"] = args.network_allowed
        if args.allow_unverified is not None:
            constraint_values["allow_unverified"] = args.allow_unverified
        if args.max_marginal_cost is not None:
            constraint_values["max_marginal_cost"] = args.max_marginal_cost
        if args.forbid_resource:
            constraint_values["forbidden_resources"] = sorted(
                set([*constraint_values["forbidden_resources"], *args.forbid_resource])
            )
        alternative_project = baseline_project.model_copy(
            update={"constraints": baseline_project.constraints.model_validate(constraint_values)}
        )
    else:
        raise ConfigurationError(
            "provide --against or at least one constraint override such as --data-class private"
        )
    catalog = InventoryCatalog.from_path(
        _inventory_path(args.inventory),
        today=max(baseline_project.as_of, alternative_project.as_of),
    )
    baseline = route(catalog.inventory, baseline_project, allow_demo=args.allow_demo)
    alternative = route(catalog.inventory, alternative_project, allow_demo=args.allow_demo)
    comparison = compare_routes(baseline, alternative)
    if args.format == "json":
        print(json.dumps(comparison.as_dict(), indent=2, sort_keys=True))
    else:
        print(render_route_comparison(comparison, width=args.width or 80), end="")
    has_gap = any(
        assignment.primary is None or assignment.unresolved_gaps
        for assignment in alternative.assignments
    )
    return 3 if has_gap else 0


def _emit_route_plan(
    plan: Any,
    project: ProjectBrief,
    *,
    output_format: str,
    width: int,
    max_words: int | None = None,
    max_lines: int | None = None,
) -> int:
    if output_format == "json":
        print(json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True))
    elif output_format == "markdown":
        print(render_markdown(plan), end="")
    elif output_format == "agent-summary":
        print(render_agent_summary(plan, goal=project.goal, width=width), end="")
    elif output_format == "presentation":
        presentation = render_agent_presentation(
            plan,
            goal=project.goal,
            width=width,
            max_words=max_words,
            max_lines=max_lines,
        )
        print(
            json.dumps(
                {
                    "format": "atready-route-presentation-v1",
                    "presentation_status": presentation.status,
                    "limits": {
                        "requested": {
                            "lines": presentation.max_lines,
                            "words": presentation.max_words,
                        },
                        "required": {
                            "lines": presentation.required_lines,
                            "words": presentation.required_words,
                        },
                    },
                    "route": plan.model_dump(mode="json"),
                    "summary": presentation.summary,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_summary(plan, goal=project.goal, width=width), end="")
    has_gap = any(
        assignment.primary is None or assignment.unresolved_gaps for assignment in plan.assignments
    )
    return 3 if has_gap else 0


def _bundled_skill_path() -> Any:
    source_checkout = (
        Path(__file__).resolve().parents[2] / "plugins" / "atready" / "skills" / "project-atready"
    )
    if source_checkout.is_dir():
        return source_checkout
    bundled = files("atready").joinpath("bundled_skill")
    if not bundled.is_dir():
        raise ConfigurationError("the installed distribution does not contain the bundled skill")
    return bundled


def _handle_skill_path(args: argparse.Namespace) -> int:
    del args
    print(_terminal_safe(_bundled_skill_path()))
    return 0


_REQUIRED_SKILL_FILES = (
    Path("SKILL.md"),
    Path("scripts/atready.py"),
    Path("references/quick-resource-intake.md"),
    Path("references/resource-onboarding.md"),
    Path("references/output-contract.md"),
    Path("references/routing-rules.md"),
    Path("references/runtime-setup.md"),
)


def _skill_location_status(path: Path) -> str:
    if not path.is_dir():
        return "not found"
    if any(not (path / required).is_file() for required in _REQUIRED_SKILL_FILES):
        return "incomplete"
    return "ready"


def _handle_skill_status(args: argparse.Namespace) -> int:
    del args
    bundled = _bundled_skill_path()
    try:
        personal = Path.home() / ".agents" / "skills" / "project-atready"
    except RuntimeError:
        raise ConfigurationError("cannot resolve the personal Codex skill location") from None
    workspace_locations = [
        directory / ".agents" / "skills" / "project-atready"
        for directory in (Path.cwd(), *Path.cwd().parents)
    ]
    workspace_statuses = [(path, _skill_location_status(path)) for path in workspace_locations]
    ready_workspaces = [(path, status) for path, status in workspace_statuses if status == "ready"]
    incomplete_workspaces = [
        (path, status) for path, status in workspace_statuses if status == "incomplete"
    ]
    personal_status = _skill_location_status(personal)

    print(f"Bundled skill: {_terminal_safe(bundled)}")
    print(f"Personal location: {_terminal_safe(personal)} ({personal_status})")
    if ready_workspaces:
        for path, _status in ready_workspaces:
            print(f"Workspace location: {_terminal_safe(path)} (ready)")
    elif incomplete_workspaces:
        for path, _status in incomplete_workspaces:
            print(f"Workspace location: {_terminal_safe(path)} (incomplete)")
    else:
        print(
            "Workspace location: "
            f"{_terminal_safe(workspace_locations[0])} (not found in this directory or a parent)"
        )
    ready = personal_status == "ready" or bool(ready_workspaces)
    print(f"Standalone skill copy ready: {'yes' if ready else 'no'}")
    print("Plugin-managed Codex installations are not checked by this command.")
    if not ready:
        print(
            "Next: if you use the standalone skill, follow the guarded copy command in the "
            "AtReady README, then restart Codex."
        )
    print("No files changed.")
    return 0


def _handle_schema(args: argparse.Namespace) -> int:
    if args.kind == "inventory":
        print(json.dumps(Inventory.model_json_schema(), indent=2, sort_keys=True))
        return 0
    if args.kind == "project":
        from atready.models import ProjectBrief

        print(json.dumps(ProjectBrief.model_json_schema(), indent=2, sort_keys=True))
        return 0
    if args.kind == "inventory-annotation-declaration":
        print(
            json.dumps(InventoryAnnotationDeclaration.model_json_schema(), indent=2, sort_keys=True)
        )
        return 0
    if args.kind == "resource-declaration":
        print(json.dumps(ResourceDeclaration.model_json_schema(), indent=2, sort_keys=True))
        return 0
    if args.kind == "resource-state":
        print(json.dumps(ResourceStateCollection.model_json_schema(), indent=2, sort_keys=True))
        return 0
    if args.kind == "route-plan":
        from atready.models import RoutePlan

        print(json.dumps(RoutePlan.model_json_schema(), indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled schema kind: {args.kind}")


def _suggested_next_actions(args: argparse.Namespace, exc: Exception) -> tuple[str, ...]:
    message = str(exc)
    command = getattr(args, "command", None)
    if "personal inventory has no resources" in message:
        return ("Add one resource: atready add",)
    if "already exists" in message and command in {"add", "inventory"}:
        return ("Review the current roster: atready inventory list",)
    if "configuration file does not exist" not in message:
        return ()
    if command == "project":
        return ("Create a project brief: atready project template > project.yaml",)
    if command in {"inventory", "resource", "plan"}:
        return ("Create your roster: atready init",)
    return ()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (AtReadyError, IntakeError) as exc:
        print(f"error: {_terminal_safe(exc)}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(f"note: {_terminal_safe(note)}", file=sys.stderr)
        existing = set(getattr(exc, "__notes__", ()))
        for action in _suggested_next_actions(args, exc):
            if action not in existing:
                print(f"next: {_terminal_safe(action)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
