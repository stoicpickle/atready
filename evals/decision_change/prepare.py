"""Prepare one private, provider-free decision-change benchmark packet."""

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

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[1]
MANIFEST = ROOT / "manifest.json"
PLUGIN_MANIFEST = REPOSITORY / "plugins/atready/.codex-plugin/plugin.json"
PROJECT = REPOSITORY / "pyproject.toml"
_MAX_INPUT_BYTES = 128_000
_MAX_CASES = 10
_MAX_CASE_ID_CHARACTERS = 64
_CASE_ID_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")


class PrepareError(ValueError):
    """Raised when a private packet cannot be prepared safely."""


def _regular_bytes(path: Path, *, label: str) -> bytes:
    try:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or path.is_symlink():
            raise PrepareError(f"{label} must be one regular file")
        if details.st_size > _MAX_INPUT_BYTES:
            raise PrepareError(f"{label} exceeds the {_MAX_INPUT_BYTES}-byte limit")
        return path.read_bytes()
    except OSError as exc:
        raise PrepareError(f"cannot read {label}: {exc}") from exc


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_regular_bytes(path, label=label))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PrepareError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PrepareError(f"{label} must contain one object")
    return value


def _inside(base: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise PrepareError(f"{label} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise PrepareError(f"{label} must be relative")
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(REPOSITORY.resolve())
    except ValueError as exc:
        raise PrepareError(f"{label} must stay inside the repository") from exc
    return candidate


def _private_root_outside_worktrees(root: Path) -> Path:
    """Resolve a new packet root and reject repository-contained destinations."""

    try:
        candidate = root.expanduser().resolve(strict=False)
        repository = REPOSITORY.resolve()
    except OSError as exc:
        raise PrepareError(f"cannot resolve private packet root: {exc}") from exc
    if candidate == repository or repository in candidate.parents:
        raise PrepareError("private packet root must stay outside this checkout")
    for ancestor in (candidate, *candidate.parents):
        marker = ancestor / ".git"
        try:
            marker.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PrepareError("cannot verify private packet root ancestry") from exc
        raise PrepareError("private packet root must stay outside every Git worktree")
    return candidate


def _case_root(fixture_root: Path, case_id: object) -> tuple[str, Path]:
    """Return one bounded path-safe case ID and its contained fixture root."""

    if (
        not isinstance(case_id, str)
        or not case_id
        or len(case_id) > _MAX_CASE_ID_CHARACTERS
        or _CASE_ID_PATTERN.fullmatch(case_id) is None
    ):
        raise PrepareError("manifest case IDs must be bounded lowercase slugs")
    fixture_root = fixture_root.resolve()
    candidate = (fixture_root / case_id).resolve()
    try:
        candidate.relative_to(fixture_root)
    except ValueError as exc:
        raise PrepareError("manifest case root must stay inside the fixture root") from exc
    return case_id, candidate


def _source_revision() -> str:
    git = shutil.which("git")
    if git is None:
        raise PrepareError("cannot identify the source revision")
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
    except (OSError, subprocess.SubprocessError) as exc:
        raise PrepareError("cannot identify the source revision") from exc
    return f"{commit} ({'dirty' if dirty else 'clean'})"


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


def _write_new(path: Path, data: bytes, *, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _remove_incomplete_root(root: Path, failure: BaseException) -> None:
    """Remove only the fresh packet root while preserving the triggering failure."""

    try:
        shutil.rmtree(root)
    except FileNotFoundError:
        return
    except OSError as cleanup_error:
        failure.add_note(f"incomplete private packet root could not be removed: {cleanup_error}")


def prepare(root: Path) -> Path:
    """Create a new private root containing exact fixtures and an operator packet."""

    root = _private_root_outside_worktrees(root)
    try:
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise PrepareError(f"cannot create new private packet root: {exc}") from exc
    try:
        if os.name == "posix":
            root.chmod(0o700)
    except OSError as exc:
        failure = PrepareError(f"cannot create new private packet root: {exc}")
        _remove_incomplete_root(root, failure)
        raise failure from exc

    try:
        manifest = _json_object(MANIFEST, label="manifest")
        cases = manifest.get("cases")
        if (
            manifest.get("schema_version") != 1
            or not isinstance(cases, list)
            or not cases
            or len(cases) > _MAX_CASES
        ):
            raise PrepareError("manifest cases must be a non-empty bounded list")

        fixture_root = root / "fixtures"
        fixture_root.mkdir(mode=0o700)
        packet_cases: list[dict[str, Any]] = []
        seen: set[str] = set()
        for case in cases:
            if not isinstance(case, dict):
                raise PrepareError("manifest cases must be objects")
            case_id, case_root = _case_root(fixture_root, case.get("id"))
            brief = case.get("brief")
            if case_id in seen or not isinstance(brief, str) or not brief.strip():
                raise PrepareError("manifest contains an invalid case")
            seen.add(case_id)
            inventory_source = _inside(ROOT, case.get("inventory_file"), label="inventory_file")
            project_source = _inside(ROOT, case.get("project_file"), label="project_file")
            inventory_data = _regular_bytes(inventory_source, label=f"{case_id} inventory")
            project_data = _regular_bytes(project_source, label=f"{case_id} project")
            case_root.mkdir(mode=0o700)
            inventory_target = case_root / "inventory.yaml"
            project_target = case_root / "project.yaml"
            _write_new(inventory_target, inventory_data, mode=0o600)
            _write_new(project_target, project_data, mode=0o600)
            packet_cases.append(
                {
                    "id": case_id,
                    "fixture_sha256": {
                        "inventory": hashlib.sha256(inventory_data).hexdigest(),
                        "project": hashlib.sha256(project_data).hexdigest(),
                    },
                    "inventory_path": str(inventory_target.relative_to(root)),
                    "project_path": str(project_target.relative_to(root)),
                    "baseline_prompt": _baseline_prompt(brief),
                    "baseline_response": "",
                    "treatment_prompt": _treatment_prompt(inventory_target, project_target),
                    "treatment_response": "",
                    "treatment_actions": [
                        {
                            "kind": "atready-route",
                            "roster_mutation": False,
                            "resource_contact": False,
                            "resource_run": False,
                            "outside_packet_write": False,
                        }
                    ],
                    "operator_coding": {
                        "decision_changed": None,
                        "change_types": [],
                        "baseline_useful": None,
                        "baseline_understandable": None,
                        "baseline_actionable": None,
                        "baseline_invented_resource_access": None,
                        "baseline_claimed_resource_contact_or_execution": None,
                        "baseline_exposed_credentials_or_secrets": None,
                        "baseline_proposed_destructive_action": None,
                        "useful": None,
                        "understandable": None,
                        "actionable": None,
                        "baseline_evidence": "",
                        "treatment_evidence": "",
                        "notes": "",
                    },
                }
            )

        plugin = _json_object(PLUGIN_MANIFEST, label="plugin manifest")
        try:
            project_metadata = tomllib.loads(
                _regular_bytes(PROJECT, label="project metadata").decode("utf-8")
            )
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise PrepareError(f"cannot parse project metadata: {exc}") from exc
        packet = {
            "schema_version": 1,
            "metadata": {
                "source_revision": _source_revision(),
                "skill_version": f"atready plugin {plugin['version']}",
                "cli_version": f"atready {project_metadata['project']['version']}",
                "evaluation_date": date.today().isoformat(),
                "host": "REPLACE",
                "model": "REPLACE",
                "settings": "REPLACE",
                "fresh_task_per_case": True,
                "baseline_before_roster_disclosure": True,
                "same_host_model_settings": True,
                "personal_roster_accessed": False,
                "provider_or_account_state_inspected": False,
                "inventoried_resource_contacted": False,
                "inventoried_resource_run": False,
                "writes_outside_packet": False,
                "evidence_kind": "operator-attested-paired-responses",
            },
            "cases": packet_cases,
        }
        target = root / "packet.json"
        _write_new(
            target,
            (json.dumps(packet, indent=2) + "\n").encode("utf-8"),
            mode=0o600,
        )
        return target
    except PrepareError as exc:
        _remove_incomplete_root(root, exc)
        raise
    except (OSError, UnicodeError, KeyError, TypeError) as exc:
        _remove_incomplete_root(root, exc)
        raise PrepareError(f"cannot prepare packet: {exc}") from exc
    except BaseException as exc:
        _remove_incomplete_root(root, exc)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="One new disposable directory")
    args = parser.parse_args(argv)
    try:
        target = prepare(args.root.resolve())
    except PrepareError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
