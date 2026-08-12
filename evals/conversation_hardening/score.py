"""Score AtReady's offline conversation contract without calling a provider."""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from pathlib import Path
from typing import Any

from atready.catalog import InventoryCatalog
from atready.errors import StorageError
from atready.paths import create_private_file
from atready.project import project_from_path
from atready.render import render_agent_summary
from atready.routing import route

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("manifest.json")
_MAX_MANIFEST_BYTES = 256_000
_MAX_ARTIFACT_BYTES = 1_000_000


class ScorecardError(ValueError):
    """Raised when the scorecard cannot be interpreted safely."""


def _read_regular(path: Path, *, maximum: int) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ScorecardError(f"cannot inspect {path}: {exc}") from exc
    if not path.is_file() or path.is_symlink():
        raise ScorecardError(f"expected one regular file: {path}")
    if size > maximum:
        raise ScorecardError(f"file exceeds {maximum} bytes: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ScorecardError(f"cannot read {path}: {exc}") from exc


def _inside(root: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ScorecardError(f"{label} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise ScorecardError(f"{label} must stay inside the repository")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ScorecardError(f"{label} must stay inside the repository") from exc
    return candidate


def _strings(value: object, *, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ScorecardError(f"{label} must be a non-empty string list")
    return value


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _check(case_id: str, name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"case": case_id, "name": name, "passed": passed, "detail": detail}


def _score_artifact(root: Path, case: dict[str, Any]) -> list[dict[str, Any]]:
    case_id = str(case["id"])
    files = _strings(case.get("files"), label=f"{case_id}.files")
    content = "\n".join(
        _read_regular(_inside(root, value, label=f"{case_id}.files"), maximum=_MAX_ARTIFACT_BYTES)
        for value in files
    )
    normalized = _normalize(content)
    checks = [
        _check(case_id, f"required-{index}", _normalize(required) in normalized, required)
        for index, required in enumerate(
            _strings(case.get("required"), label=f"{case_id}.required"), start=1
        )
    ]
    return checks


def _score_route(root: Path, case: dict[str, Any], boundary: str) -> list[dict[str, Any]]:
    case_id = str(case["id"])
    inventory_path = _inside(root, case.get("inventory"), label=f"{case_id}.inventory")
    project_path = _inside(root, case.get("project"), label=f"{case_id}.project")
    project = project_from_path(project_path)
    inventory = InventoryCatalog.from_path(inventory_path, today=project.as_of).inventory
    result = route(inventory, project, allow_demo=True)
    summary = render_agent_summary(result, goal=project.goal, width=120)
    max_words = case.get("max_words")
    max_lines = case.get("max_lines")
    if not isinstance(max_words, int) or isinstance(max_words, bool) or max_words < 1:
        raise ScorecardError(f"{case_id}.max_words must be a positive integer")
    if not isinstance(max_lines, int) or isinstance(max_lines, bool) or max_lines < 1:
        raise ScorecardError(f"{case_id}.max_lines must be a positive integer")

    checks = [
        _check(
            case_id,
            "word-limit",
            len(summary.split()) <= max_words,
            f"{len(summary.split())}/{max_words}",
        ),
        _check(
            case_id,
            "line-limit",
            len(summary.splitlines()) <= max_lines,
            f"{len(summary.splitlines())}/{max_lines}",
        ),
        _check(case_id, "exact-boundary", summary.count(boundary) == 1, "boundary occurs once"),
        _check(
            case_id,
            "boundary-last",
            summary.rstrip().endswith(boundary),
            "boundary is the final line",
        ),
    ]
    checks.extend(
        _check(case_id, f"required-{index}", required in summary, required)
        for index, required in enumerate(
            _strings(case.get("required"), label=f"{case_id}.required"), start=1
        )
    )
    has_gap = any(assignment.primary is None for assignment in result.assignments)
    expected_gap = case.get("expected_gap")
    if not isinstance(expected_gap, bool):
        raise ScorecardError(f"{case_id}.expected_gap must be boolean")
    checks.append(_check(case_id, "gap-parity", has_gap is expected_gap, f"gap={has_gap}"))
    return checks


def score(manifest_path: Path = DEFAULT_MANIFEST, *, root: Path = ROOT) -> dict[str, Any]:
    try:
        manifest = json.loads(_read_regular(manifest_path, maximum=_MAX_MANIFEST_BYTES))
    except json.JSONDecodeError as exc:
        raise ScorecardError(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ScorecardError("manifest must be a schema_version 1 object")
    boundary = manifest.get("safety_boundary")
    if not isinstance(boundary, str) or not boundary:
        raise ScorecardError("safety_boundary must be a non-empty string")
    cases = manifest.get("offline_cases")
    if not isinstance(cases, list) or not cases:
        raise ScorecardError("offline_cases must be a non-empty list")

    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def reject_network(*_args: object, **_kwargs: object) -> None:
        raise ScorecardError("conversation hardening scorecard must remain offline")

    socket.create_connection = reject_network
    socket.getaddrinfo = reject_network
    socket.socket.connect = reject_network
    socket.socket.connect_ex = reject_network
    try:
        scored_cases: list[dict[str, Any]] = []
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("id"), str):
                raise ScorecardError("each offline case requires an id")
            kind = case.get("kind")
            if kind == "artifact":
                checks = _score_artifact(root, case)
            elif kind == "route":
                checks = _score_route(root, case, boundary)
            else:
                raise ScorecardError(f"unsupported case kind: {kind!r}")
            passed = all(item["passed"] for item in checks)
            scored_cases.append(
                {
                    "id": case["id"],
                    "kind": kind,
                    "safety": case.get("safety") is True,
                    "passed": passed,
                    "checks": checks,
                }
            )
    finally:
        socket.create_connection = original_create_connection
        socket.getaddrinfo = original_getaddrinfo
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex

    safety_cases = [case for case in scored_cases if case["safety"]]
    if not safety_cases:
        raise ScorecardError("offline_cases must include at least one safety case")
    pass_rate = sum(case["passed"] for case in scored_cases) / len(scored_cases)
    safety_rate = sum(case["passed"] for case in safety_cases) / len(safety_cases)
    forbidden = _strings(
        manifest.get("forbidden_invented_fact_terms"),
        label="forbidden_invented_fact_terms",
    )
    artifact_text = "\n".join(
        _read_regular(path, maximum=_MAX_ARTIFACT_BYTES)
        for path in (
            root / "plugins/atready/skills/project-atready/SKILL.md",
            root / "plugins/atready/skills/project-atready/references/quick-resource-intake.md",
        )
    ).casefold()
    invented_fact_gate = not any(term.casefold() in artifact_text for term in forbidden)
    minimum = manifest.get("minimum_contract_pass_rate")
    required_safety = manifest.get("required_safety_pass_rate")
    if (
        not isinstance(minimum, (int, float))
        or isinstance(minimum, bool)
        or not 0.0 <= float(minimum) <= 1.0
    ):
        raise ScorecardError("minimum_contract_pass_rate must be between 0.0 and 1.0")
    if (
        not isinstance(required_safety, (int, float))
        or isinstance(required_safety, bool)
        or not 0.0 <= float(required_safety) <= 1.0
    ):
        raise ScorecardError("required_safety_pass_rate must be between 0.0 and 1.0")

    manual = manifest.get("manual_provider_required")
    if not isinstance(manual, list):
        raise ScorecardError("manual_provider_required must be a list")
    for item in manual:
        if not isinstance(item, dict):
            raise ScorecardError("manual_provider_required entries must be objects")
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise ScorecardError("manual_provider_required entries require a non-empty id")
        _read_regular(
            _inside(root, item.get("prompt_file"), label="manual.prompt_file"),
            maximum=_MAX_ARTIFACT_BYTES,
        )

    artifact_cases = [case for case in scored_cases if case["kind"] == "artifact"]
    route_cases = [case for case in scored_cases if case["kind"] == "route"]
    artifact_rate = (
        sum(case["passed"] for case in artifact_cases) / len(artifact_cases)
        if artifact_cases
        else 0.0
    )
    route_rate = (
        sum(case["passed"] for case in route_cases) / len(route_cases) if route_cases else 0.0
    )
    gates = {
        "instruction_contract": artifact_rate >= float(minimum),
        "deterministic_route_contract": route_rate >= float(minimum),
        "safety_authorization": safety_rate >= float(required_safety),
        "forbidden_literal_absence": invented_fact_gate,
    }
    return {
        "offline_contract_passed": all(gates.values()),
        "offline": True,
        "host_behavior_proven": False,
        "manual_provider_cases_completed": False,
        "provider_calls": 0,
        "synthetic_only": True,
        "summary": {
            "cases": len(scored_cases),
            "passed": sum(case["passed"] for case in scored_cases),
            "failed": sum(not case["passed"] for case in scored_cases),
            "pass_rate": pass_rate,
            "safety_pass_rate": safety_rate,
        },
        "gates": gates,
        "cases": scored_cases,
        "manual_provider_required": [item["id"] for item in manual],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = score(args.manifest)
    except ScorecardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        try:
            create_private_file(args.report, rendered)
        except (OSError, StorageError) as exc:
            print(f"error: cannot create new private report: {exc}", file=sys.stderr)
            return 2
    print(rendered, end="")
    return 0 if report["offline_contract_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
