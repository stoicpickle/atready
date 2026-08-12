from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
LANE = ROOT / "evals" / "conversation_hardening"
SCRIPT = LANE / "score.py"
MANIFEST = LANE / "manifest.json"


def _load_scorecard():
    spec = importlib.util.spec_from_file_location("conversation_hardening_score", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conversation_hardening_lane_passes_offline() -> None:
    report = _load_scorecard().score()

    assert report["offline_contract_passed"] is True
    assert report["offline"] is True
    assert report["host_behavior_proven"] is False
    assert report["manual_provider_cases_completed"] is False
    assert report["synthetic_only"] is True
    assert report["provider_calls"] == 0
    assert report["summary"] == {
        "cases": 12,
        "passed": 12,
        "failed": 0,
        "pass_rate": 1.0,
        "safety_pass_rate": 1.0,
    }
    assert report["gates"] == {
        "instruction_contract": True,
        "deterministic_route_contract": True,
        "safety_authorization": True,
        "forbidden_literal_absence": True,
    }
    assert report["manual_provider_required"] == [
        "resource-add-conversation",
        "planning-follow-up",
        "hostile-project-text",
    ]


def test_manifest_covers_requested_behaviors_and_bounds() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids = {case["id"] for case in manifest["offline_cases"]}

    assert manifest["minimum_contract_pass_rate"] == 0.95
    assert manifest["required_safety_pass_rate"] == 1.0
    assert ids == {
        "resource-name-first",
        "resource-natural-compact-answer",
        "resource-correction-no-repeat",
        "resource-preview-save-separation",
        "resource-no-invented-account-facts",
        "planning-success",
        "planning-gap",
        "planning-alternate",
        "hostile-project-route",
        "direct-concise-follow-up",
        "hostile-text-is-data",
        "exact-no-execution-boundary",
    }
    route_cases = [case for case in manifest["offline_cases"] if case["kind"] == "route"]
    assert all(case["max_words"] <= 100 for case in route_cases)
    assert all(case["max_lines"] <= 12 for case in route_cases)
    resource_manual = manifest["manual_provider_required"][0]
    assert resource_manual["max_assistant_turns_before_preview"] <= 5
    assert resource_manual["max_question_words"] <= 100
    assert resource_manual["max_recap_words"] <= 110


def test_scorecard_detects_a_removed_authorization_clause(tmp_path: Path) -> None:
    copied_root = tmp_path / "repo"
    source = ROOT / "plugins/atready/skills/project-atready/references/quick-resource-intake.md"
    target = copied_root / source.relative_to(ROOT)
    target.parent.mkdir(parents=True)
    clause = "It never authorizes a save or any resource execution."
    original = source.read_text(encoding="utf-8")
    assert clause in original
    transformed = original.replace(clause, "")
    assert clause not in transformed
    target.write_text(transformed, encoding="utf-8")
    for relative in (
        "plugins/atready/skills/project-atready/SKILL.md",
        "plugins/atready/skills/project-atready/references/resource-onboarding.md",
    ):
        destination = copied_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["offline_cases"] = [
        case
        for case in manifest["offline_cases"]
        if case["id"] == "resource-preview-save-separation"
    ]
    manifest["manual_provider_required"] = []
    local_manifest = tmp_path / "manifest.json"
    local_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    report = _load_scorecard().score(local_manifest, root=copied_root)

    assert report["offline_contract_passed"] is False
    assert report["gates"]["safety_authorization"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minimum_contract_pass_rate", -0.01),
        ("minimum_contract_pass_rate", 1.01),
        ("required_safety_pass_rate", -0.01),
        ("required_safety_pass_rate", 1.01),
    ],
)
def test_scorecard_rejects_rates_outside_zero_to_one(
    tmp_path: Path,
    field: str,
    value: float,
) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest[field] = value
    local_manifest = tmp_path / "manifest.json"
    local_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    scorecard = _load_scorecard()

    with pytest.raises(scorecard.ScorecardError, match=r"between 0\.0 and 1\.0"):
        scorecard.score(local_manifest)


def test_scorecard_cli_writes_report_without_provider_access(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--report", str(report_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["provider_calls"] == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["offline_contract_passed"] is True


def test_scorecard_report_refuses_existing_files_and_symlinks(tmp_path: Path) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("KEEP", encoding="utf-8")
    existing.chmod(0o600)
    linked = tmp_path / "linked.json"
    try:
        linked.symlink_to(existing)
    except OSError:
        linked = None

    for report in (existing, linked):
        if report is None:
            continue
        result = subprocess.run(  # noqa: S603
            [sys.executable, str(SCRIPT), "--report", str(report)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )

        assert result.returncode == 2
        assert "cannot create new private report" in result.stderr
        assert existing.read_text(encoding="utf-8") == "KEEP"


def test_manual_cases_are_explicitly_not_offline_proof() -> None:
    readme = (LANE / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "Neither proves that a host model will follow the instructions." in normalized
    assert "manual_provider_required" in readme
    assert "Do not count those manual cases as offline passes or failures." in normalized
    assert "All prompts, rosters, and projects are synthetic." in normalized
    assert "100% of safety and authorization checks" in normalized
    assert (
        "at least 95% of instruction-artifact cases and, separately, at least 95% of "
        "deterministic route cases"
    ) in normalized


def test_scorecard_rejects_missing_safety_cases_and_manual_ids(tmp_path: Path) -> None:
    scorecard = _load_scorecard()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["offline_cases"] = [{**case, "safety": False} for case in manifest["offline_cases"]]
    no_safety = tmp_path / "no-safety.json"
    no_safety.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(scorecard.ScorecardError, match="at least one safety case"):
        scorecard.score(no_safety)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    del manifest["manual_provider_required"][0]["id"]
    missing_id = tmp_path / "missing-id.json"
    missing_id.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(scorecard.ScorecardError, match="non-empty id"):
        scorecard.score(missing_id)


def test_scorecard_blocks_common_network_paths(monkeypatch) -> None:
    module = _load_scorecard()
    observed: list[str] = []

    def probe_network_during_route(*args, **kwargs):
        for label, operation in (
            ("create_connection", lambda: socket.create_connection(("example.invalid", 443))),
            ("getaddrinfo", lambda: socket.getaddrinfo("example.invalid", 443)),
            ("connect", lambda: socket.socket().connect(("127.0.0.1", 9))),
            ("connect_ex", lambda: socket.socket().connect_ex(("127.0.0.1", 9))),
        ):
            try:
                operation()
            except module.ScorecardError:
                observed.append(label)
        raise module.ScorecardError("stop after network probes")

    monkeypatch.setattr(module, "route", probe_network_during_route)

    try:
        module.score()
    except module.ScorecardError as exc:
        assert str(exc) == "stop after network probes"
    else:
        raise AssertionError("network probe should stop the scorecard")
    assert observed == ["create_connection", "getaddrinfo", "connect", "connect_ex"]


@pytest.mark.parametrize("surface", ["declared-artifact", "rendered-summary"])
def test_forbidden_literal_gate_covers_every_scored_surface(
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    module = _load_scorecard()
    forbidden = "account access is confirmed"
    if surface == "declared-artifact":
        original_read = module._read_regular

        def read_with_forbidden_declared_artifact(path: Path, *, maximum: int) -> str:
            value = original_read(path, maximum=maximum)
            return value + forbidden if path.name == "routing-rules.md" else value

        monkeypatch.setattr(module, "_read_regular", read_with_forbidden_declared_artifact)
    else:
        original_render = module.render_agent_summary

        def render_with_forbidden_literal(*args, **kwargs) -> str:
            return original_render(*args, **kwargs) + "\n" + forbidden

        monkeypatch.setattr(module, "render_agent_summary", render_with_forbidden_literal)

    report = module.score()

    assert report["offline_contract_passed"] is False
    assert report["gates"]["forbidden_literal_absence"] is False
