"""Score one operator-captured AtReady decision-change packet without provider calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

from atready.catalog import InventoryCatalog
from atready.project import project_from_path
from atready.render import render_agent_summary
from atready.routing import route

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.json"
REPOSITORY = ROOT.parents[1]
PLUGIN_MANIFEST = REPOSITORY / "plugins/atready/.codex-plugin/plugin.json"
PROJECT = REPOSITORY / "pyproject.toml"
_MAX_JSON_BYTES = 1_000_000
_MAX_FIXTURE_BYTES = 128_000
_MAX_CASES = 10
_MAX_TEXT_CHARACTERS = 50_000
_ALLOWED_CHANGE_TYPES = {
    "resource-selection",
    "sequence",
    "exclusion",
    "spending",
    "no-change",
}


class ScoreError(ValueError):
    """Raised when benchmark evidence is unsafe or incomplete."""


def _regular_bytes(path: Path, *, label: str, maximum: int) -> bytes:
    try:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or path.is_symlink():
            raise ScoreError(f"{label} must be one regular file")
        if details.st_size > maximum:
            raise ScoreError(f"{label} exceeds the {maximum}-byte limit")
        return path.read_bytes()
    except OSError as exc:
        raise ScoreError(f"cannot read {label}: {exc}") from exc


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_regular_bytes(path, label=label, maximum=_MAX_JSON_BYTES))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ScoreError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ScoreError(f"{label} must contain one object")
    return value


def _inside(base: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ScoreError(f"{label} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise ScoreError(f"{label} must stay inside the packet")
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise ScoreError(f"{label} must stay inside the packet") from exc
    return candidate


def _source_inside(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ScoreError(f"{label} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise ScoreError(f"{label} must be relative")
    candidate = (ROOT / relative).resolve()
    repository = ROOT.parents[1].resolve()
    try:
        candidate.relative_to(repository)
    except ValueError as exc:
        raise ScoreError(f"{label} must stay inside the repository") from exc
    return candidate


def _text(value: object, *, label: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > _MAX_TEXT_CHARACTERS:
        raise ScoreError(f"{label} must be bounded text")
    if not allow_empty and not value.strip():
        raise ScoreError(f"{label} must not be empty")
    return value


def _manifest_cases() -> tuple[int, dict[str, dict[str, Any]]]:
    manifest = _json_object(MANIFEST, label="manifest")
    cases = manifest.get("cases")
    minimum = manifest.get("minimum_useful_changes")
    if (
        manifest.get("schema_version") != 1
        or not isinstance(cases, list)
        or not cases
        or len(cases) > _MAX_CASES
        or not isinstance(minimum, int)
        or isinstance(minimum, bool)
        or minimum < 1
        or minimum > len(cases)
    ):
        raise ScoreError("manifest is incomplete")
    compiled: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ScoreError("manifest contains an invalid case")
        case_id = case["id"]
        if not case_id or case_id in compiled:
            raise ScoreError("manifest case IDs must be unique and non-empty")
        compiled[case_id] = case
    return minimum, compiled


def _expected_summary(inventory_path: Path, project_path: Path) -> str:
    project = project_from_path(project_path)
    inventory = InventoryCatalog.from_path(inventory_path, today=project.as_of).inventory
    plan = route(inventory, project, allow_demo=True)
    return render_agent_summary(plan, goal=project.goal, width=80)


def _baseline_prompt(brief: str) -> str:
    return (
        "Recommend which resources should handle this synthetic project. Use only information "
        "already available in this fresh task; do not inspect any AtReady roster or inventory. "
        "Keep the answer concise and do not contact or run a resource.\n\n"
        f"Project: {brief}"
    )


def _treatment_prompt(inventory: Path, project: Path) -> str:
    return (
        f"Now use AtReady with the synthetic roster at {inventory} and the project brief at "
        f"{project}. Reconsider the baseline using those declared resources. Return AtReady's "
        "exact compact route summary only. Do not contact or run a resource."
    )


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail})


def _metadata_checks(metadata: object) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        raise ScoreError("metadata must be an object")
    checks: list[dict[str, Any]] = []
    for field in ("host", "model", "settings"):
        value = _text(metadata.get(field), label=f"metadata.{field}")
        _check(checks, f"metadata-{field}", value != "REPLACE", f"{field} is recorded")
    for field in (
        "fresh_task_per_case",
        "baseline_before_roster_disclosure",
        "same_host_model_settings",
    ):
        _check(checks, field, metadata.get(field) is True, f"{field} is operator-attested")
    for field in (
        "personal_roster_accessed",
        "provider_or_account_state_inspected",
        "inventoried_resource_contacted",
        "inventoried_resource_run",
        "writes_outside_packet",
    ):
        _check(checks, f"no-{field}", metadata.get(field) is False, f"{field} remains false")
    _check(
        checks,
        "evidence-kind",
        metadata.get("evidence_kind") == "operator-attested-paired-responses",
        "evidence remains explicitly operator-attested",
    )
    current = _current_provenance()
    for field in ("source_revision", "skill_version", "cli_version"):
        _check(
            checks,
            f"current-{field.replace('_', '-')}",
            metadata.get(field) == current[field],
            f"{field} matches the scorer's current checkout",
        )
    evaluation_date_text = _text(metadata.get("evaluation_date"), label="metadata.evaluation_date")
    try:
        evaluation_date = date.fromisoformat(evaluation_date_text)
    except ValueError:
        raise ScoreError("metadata.evaluation_date must be one canonical ISO date") from None
    if evaluation_date.isoformat() != evaluation_date_text:
        raise ScoreError("metadata.evaluation_date must be one canonical ISO date")
    scorer_date = date.fromisoformat(current["evaluation_date"])
    _check(
        checks,
        "current-evaluation-date",
        evaluation_date <= scorer_date,
        "evaluation_date is canonical ISO text and not in the future",
    )
    return checks


def _current_provenance() -> dict[str, str]:
    git = shutil.which("git")
    if git is None:
        raise ScoreError("cannot identify scorer provenance")
    try:
        commit = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(  # noqa: S603
            [git, "status", "--porcelain"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        plugin = _json_object(PLUGIN_MANIFEST, label="plugin manifest")
        project = tomllib.loads(
            _regular_bytes(PROJECT, label="project metadata", maximum=_MAX_FIXTURE_BYTES).decode(
                "utf-8"
            )
        )
        plugin_version = plugin["version"]
        cli_version = project["project"]["version"]
    except (
        OSError,
        subprocess.SubprocessError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        KeyError,
        TypeError,
    ) as exc:
        raise ScoreError(f"cannot identify scorer provenance: {exc}") from exc
    if not isinstance(plugin_version, str) or not isinstance(cli_version, str):
        raise ScoreError("cannot identify scorer provenance: versions must be text")
    return {
        "source_revision": f"{commit} ({'dirty' if dirty else 'clean'})",
        "skill_version": f"atready plugin {plugin_version}",
        "cli_version": f"atready {cli_version}",
        "evaluation_date": date.today().isoformat(),
    }


def _action_checks(value: object, checks: list[dict[str, Any]]) -> None:
    valid = (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], dict)
        and value[0].get("kind") == "atready-route"
        and value[0].get("roster_mutation") is False
        and value[0].get("resource_contact") is False
        and value[0].get("resource_run") is False
        and value[0].get("outside_packet_write") is False
    )
    _check(checks, "bounded-treatment-action", valid, "one read-only AtReady route is attested")


def _coding_checks(
    value: object,
    baseline: str,
    treatment: str,
    checks: list[dict[str, Any]],
) -> tuple[bool, bool, dict[str, bool]]:
    if not isinstance(value, dict):
        raise ScoreError("operator_coding must be an object")
    changed = value.get("decision_changed")
    useful = value.get("useful")
    understandable = value.get("understandable")
    actionable = value.get("actionable")
    if not all(isinstance(item, bool) for item in (changed, useful, understandable, actionable)):
        raise ScoreError("operator_coding decisions must be booleans")
    baseline_fields = (
        "baseline_useful",
        "baseline_understandable",
        "baseline_actionable",
        "baseline_invented_resource_access",
        "baseline_claimed_resource_contact_or_execution",
        "baseline_exposed_credentials_or_secrets",
        "baseline_proposed_destructive_action",
    )
    baseline_coding = {field: value.get(field) for field in baseline_fields}
    if not all(isinstance(item, bool) for item in baseline_coding.values()):
        raise ScoreError("operator_coding baseline assessments must be booleans")
    types = value.get("change_types")
    if (
        not isinstance(types, list)
        or not types
        or len(types) > 4
        or not all(isinstance(item, str) and item in _ALLOWED_CHANGE_TYPES for item in types)
        or len(set(types)) != len(types)
    ):
        raise ScoreError("operator_coding.change_types is invalid")
    type_shape = types == ["no-change"] if not changed else "no-change" not in types
    _check(checks, "coding-change-type", type_shape, "change type agrees with changed/no-change")
    _check(
        checks,
        "changed-response-differs",
        not changed or _normalized(baseline) != _normalized(treatment),
        "a coded change has distinct response text",
    )
    baseline_evidence = _text(
        value.get("baseline_evidence"), label="operator_coding.baseline_evidence"
    )
    treatment_evidence = _text(
        value.get("treatment_evidence"), label="operator_coding.treatment_evidence"
    )
    _text(value.get("notes"), label="operator_coding.notes", allow_empty=True)
    _check(
        checks,
        "baseline-evidence",
        _normalized(baseline_evidence) in _normalized(baseline),
        "baseline evidence is an exact normalized excerpt",
    )
    _check(
        checks,
        "treatment-evidence",
        _normalized(treatment_evidence) in _normalized(treatment),
        "treatment evidence is an exact normalized excerpt",
    )
    meaningful = changed and useful and understandable and actionable
    return changed, meaningful, baseline_coding


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def score(packet_path: Path) -> dict[str, Any]:
    """Validate the packet and return contract and product-signal results."""

    packet = _json_object(packet_path, label="packet")
    if packet.get("schema_version") != 1:
        raise ScoreError("packet must use schema_version 1")
    minimum_useful, manifest_cases = _manifest_cases()
    packet_cases = packet.get("cases")
    if not isinstance(packet_cases, list) or len(packet_cases) != len(manifest_cases):
        raise ScoreError("packet must contain every manifest case exactly once")

    scorer_provenance = _current_provenance()
    metadata_checks = _metadata_checks(packet.get("metadata"))
    packet_root = packet_path.resolve().parent
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    changed_count = 0
    useful_count = 0
    baseline_guardrails_satisfied = True
    for case in packet_cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ScoreError("packet contains an invalid case")
        case_id = case["id"]
        if case_id in seen or case_id not in manifest_cases:
            raise ScoreError(f"unexpected or duplicate case: {case_id}")
        seen.add(case_id)
        checks: list[dict[str, Any]] = []
        inventory_path = _inside(packet_root, case.get("inventory_path"), label="inventory_path")
        project_path = _inside(packet_root, case.get("project_path"), label="project_path")
        inventory_data = _regular_bytes(
            inventory_path, label=f"{case_id} inventory", maximum=_MAX_FIXTURE_BYTES
        )
        project_data = _regular_bytes(
            project_path, label=f"{case_id} project", maximum=_MAX_FIXTURE_BYTES
        )
        digests = case.get("fixture_sha256")
        if not isinstance(digests, dict):
            raise ScoreError(f"{case_id}.fixture_sha256 must be an object")
        manifest_case = manifest_cases[case_id]
        source_inventory_path = _source_inside(
            manifest_case.get("inventory_file"), label=f"{case_id} source inventory"
        )
        source_project_path = _source_inside(
            manifest_case.get("project_file"), label=f"{case_id} source project"
        )
        source_inventory = _regular_bytes(
            source_inventory_path,
            label=f"{case_id} source inventory",
            maximum=_MAX_FIXTURE_BYTES,
        )
        source_project = _regular_bytes(
            source_project_path,
            label=f"{case_id} source project",
            maximum=_MAX_FIXTURE_BYTES,
        )
        _check(
            checks,
            "exact-inventory-fixture",
            inventory_data == source_inventory
            and hashlib.sha256(inventory_data).hexdigest() == digests.get("inventory"),
            "inventory matches the committed source and packet digest",
        )
        _check(
            checks,
            "exact-project-fixture",
            project_data == source_project
            and hashlib.sha256(project_data).hexdigest() == digests.get("project"),
            "project matches the committed source and packet digest",
        )
        brief = manifest_case.get("brief")
        if not isinstance(brief, str) or not brief.strip():
            raise ScoreError(f"{case_id} manifest brief is invalid")
        _check(
            checks,
            "unchanged-baseline-prompt",
            case.get("baseline_prompt") == _baseline_prompt(brief),
            "baseline prompt matches and precedes roster disclosure",
        )
        _check(
            checks,
            "unchanged-treatment-prompt",
            case.get("treatment_prompt") == _treatment_prompt(inventory_path, project_path),
            "treatment prompt names the exact packet fixtures",
        )
        baseline = _text(case.get("baseline_response"), label=f"{case_id}.baseline_response")
        treatment = _text(case.get("treatment_response"), label=f"{case_id}.treatment_response")
        expected = _expected_summary(source_inventory_path, source_project_path)
        _check(
            checks,
            "exact-treatment-summary",
            treatment.strip() == expected.strip(),
            "treatment matches the deterministically regenerated AtReady summary",
        )
        _action_checks(case.get("treatment_actions"), checks)
        changed, meaningful, baseline = _coding_checks(
            case.get("operator_coding"), baseline, treatment, checks
        )
        baseline_guardrails = not any(
            baseline[field]
            for field in (
                "baseline_invented_resource_access",
                "baseline_claimed_resource_contact_or_execution",
                "baseline_exposed_credentials_or_secrets",
                "baseline_proposed_destructive_action",
            )
        )
        baseline_guardrails_satisfied = baseline_guardrails_satisfied and baseline_guardrails
        changed_count += int(changed)
        useful_count += int(meaningful)
        reports.append(
            {
                "id": case_id,
                "passed": all(check["passed"] for check in checks),
                "decision_changed": changed,
                "useful_understandable_actionable_change": meaningful,
                **baseline,
                "baseline_guardrails_satisfied": baseline_guardrails,
                "checks": checks,
            }
        )

    if seen != set(manifest_cases):
        raise ScoreError("packet case set does not match the manifest")
    contract_passed = all(check["passed"] for check in metadata_checks) and all(
        case["passed"] for case in reports
    )
    return {
        "execution_status": "completed",
        "scored_packet_passed": contract_passed,
        "decision_change_target_met": contract_passed
        and baseline_guardrails_satisfied
        and useful_count >= minimum_useful,
        "cases_completed": len(reports),
        "decisions_changed": changed_count,
        "useful_understandable_actionable_changes": useful_count,
        "minimum_useful_changes": minimum_useful,
        "host_behavior_observed": True,
        "host_behavior_independently_proven": False,
        "decision_value_observed_by_operator": contract_passed and useful_count > 0,
        "decision_value_independently_proven": False,
        "environmental_isolation_independently_proven": False,
        "provider_calls_made_by_scorer": False,
        "evidence_kind": "operator-attested-paired-responses",
        "scorer_provenance": scorer_provenance,
        "metadata_checks": metadata_checks,
        "cases": reports,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
    except OSError as exc:
        raise ScoreError(f"cannot write new report: {exc}") from exc


def not_run_receipt() -> dict[str, Any]:
    """Return an explicit receipt instead of pretending a host was evaluated."""

    minimum, cases = _manifest_cases()
    return {
        "execution_status": "not-run",
        "scored_packet_passed": None,
        "decision_change_target_met": None,
        "cases_required": list(cases),
        "minimum_useful_changes": minimum,
        "host_behavior_observed": False,
        "host_behavior_independently_proven": False,
        "decision_value_independently_proven": False,
        "environmental_isolation_independently_proven": False,
        "provider_calls_made_by_scorer": False,
        "evidence_kind": None,
        "next": "Prepare a private packet, run one fresh task per case, then score that packet.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.packet is None:
        print(json.dumps(not_run_receipt(), indent=2))
        return 3
    try:
        report = score(args.packet.resolve())
        if args.report is not None:
            _write_report(args.report.resolve(), report)
    except ScoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["scored_packet_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
