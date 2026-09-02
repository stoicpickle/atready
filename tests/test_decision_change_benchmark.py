from __future__ import annotations

import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from atready.cli import main as cli_main

ROOT = Path(__file__).parents[1]
LANE = ROOT / "evals" / "decision_change"
PREPARE = LANE / "prepare.py"
SCORE = LANE / "score.py"
PERMISSIONS = ROOT / "docs" / "PERMISSIONS.md"
THREAT_MODEL = ROOT / "docs" / "THREAT_MODEL.md"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare_module = _load(PREPARE, "decision_change_prepare")
score_module = _load(SCORE, "decision_change_score")


def test_decision_change_scorer_trust_boundary_is_documented() -> None:
    permissions = " ".join(PERMISSIONS.read_text(encoding="utf-8").split())
    threat_model = " ".join(THREAT_MODEL.read_text(encoding="utf-8").split())
    combined = permissions + " " + threat_model

    for boundary in (
        "`--packet PATH`",
        "`--report PATH`",
        "`git rev-parse HEAD`",
        "`git status --porcelain`",
        "including outside the repository",
        "refuses overwrite",
        "separate operator work",
        "owns their local protection, review, retention, and removal",
        "no provider, model, account, network, or inventoried-resource contact",
    ):
        assert boundary in combined


def _prepared_packet(tmp_path: Path) -> Path:
    return prepare_module.prepare(tmp_path / "private-packet")


def _complete_packet(packet_path: Path) -> dict:
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["metadata"].update(
        {"host": "Synthetic host", "model": "Synthetic model", "settings": "Default"}
    )
    root = packet_path.parent
    for case in packet["cases"]:
        inventory = root / case["inventory_path"]
        project = root / case["project_path"]
        treatment = score_module._expected_summary(inventory, project)
        case["baseline_response"] = (
            "Use a general coding assistant, a general creative tool, and a human reviewer."
        )
        case["treatment_response"] = treatment
        case["operator_coding"] = {
            "decision_changed": True,
            "change_types": ["resource-selection"],
            "baseline_useful": True,
            "baseline_understandable": True,
            "baseline_actionable": True,
            "baseline_invented_resource_access": False,
            "baseline_claimed_resource_contact_or_execution": False,
            "baseline_exposed_credentials_or_secrets": False,
            "baseline_proposed_destructive_action": False,
            "useful": True,
            "understandable": True,
            "actionable": True,
            "baseline_evidence": "general coding assistant",
            "treatment_evidence": "Route:",
            "notes": "The treatment assigns declared synthetic resources.",
        }
    packet_path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    return packet


def _failed(report: dict, case_id: str) -> set[str]:
    case = next(item for item in report["cases"] if item["id"] == case_id)
    return {check["name"] for check in case["checks"] if not check["passed"]}


def test_manifest_has_four_existing_routes_and_pixel_game_case() -> None:
    manifest = json.loads((LANE / "manifest.json").read_text(encoding="utf-8"))

    assert [case["id"] for case in manifest["cases"]] == [
        "godot",
        "web",
        "art",
        "degraded",
        "pixel-game",
    ]
    assert manifest["minimum_useful_changes"] == 3
    assert manifest["cases"][0]["inventory_file"] == "../fixtures/inventory.yaml"
    assert manifest["cases"][3]["inventory_file"] == "../fixtures/inventory-degraded.yaml"
    assert manifest["cases"][4]["inventory_file"] == "fixtures/inventory-pixel-game.yaml"


def test_all_treatment_fixtures_route_to_the_expected_synthetic_resources() -> None:
    manifest = json.loads((LANE / "manifest.json").read_text(encoding="utf-8"))
    expected = {
        "godot": ["codex", "codex", "coderabbit"],
        "web": ["codex", "openrouter", "upstash", "vercel"],
        "art": ["native-imagegen", "scenario", "aseprite"],
        "degraded": ["backup-coder", "builder", "private-architect"],
        "pixel-game": ["codex", "retro-diffusion", "coderabbit"],
    }

    for case in manifest["cases"]:
        project_path = (LANE / case["project_file"]).resolve()
        inventory_path = (LANE / case["inventory_file"]).resolve()
        project = score_module.project_from_path(project_path)
        inventory = score_module.InventoryCatalog.from_path(
            inventory_path, today=project.as_of
        ).inventory
        plan = score_module.route(inventory, project, allow_demo=True)
        assert [assignment.primary.resource_id for assignment in plan.assignments] == expected[
            case["id"]
        ]

    degraded_case = next(case for case in manifest["cases"] if case["id"] == "degraded")
    degraded_project = score_module.project_from_path(
        (LANE / degraded_case["project_file"]).resolve()
    )
    degraded_inventory = score_module.InventoryCatalog.from_path(
        (LANE / degraded_case["inventory_file"]).resolve(), today=degraded_project.as_of
    ).inventory
    degraded_plan = score_module.route(degraded_inventory, degraded_project, allow_demo=True)
    assert degraded_plan.assignments[1].support.resource_id == "reviewer"


def test_expected_summary_matches_the_cli_default_width(capsys: pytest.CaptureFixture[str]) -> None:
    manifest = json.loads((LANE / "manifest.json").read_text(encoding="utf-8"))
    case = manifest["cases"][0]
    project_path = (LANE / case["project_file"]).resolve()
    inventory_path = (LANE / case["inventory_file"]).resolve()
    assert (
        cli_main(
            [
                "route",
                "--project",
                str(project_path),
                "--inventory",
                str(inventory_path),
                "--allow-demo",
                "--format",
                "agent-summary",
            ]
        )
        == 0
    )
    cli_width_summary = capsys.readouterr().out

    assert score_module._expected_summary(inventory_path, project_path) == cli_width_summary


def test_prepare_creates_private_exact_packet_with_sequential_prompts(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))

    if os.name == "posix":
        assert stat.S_IMODE(packet_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(packet_path.stat().st_mode) == 0o600
    assert len(packet["cases"]) == 5
    for case in packet["cases"]:
        inventory = packet_path.parent / case["inventory_path"]
        project = packet_path.parent / case["project_path"]
        if os.name == "posix":
            assert stat.S_IMODE(inventory.stat().st_mode) == 0o600
            assert stat.S_IMODE(project.stat().st_mode) == 0o600
        assert "do not inspect any AtReady roster" in case["baseline_prompt"]
        assert str(inventory) in case["treatment_prompt"]
        assert str(project) in case["treatment_prompt"]
        assert case["baseline_response"] == ""
        assert case["treatment_response"] == ""

    with pytest.raises(prepare_module.PrepareError, match="cannot create new private"):
        prepare_module.prepare(packet_path.parent)


@pytest.mark.parametrize("case_id", ["../escape", "nested/case", "a" * 65])
def test_prepare_rejects_unbounded_or_path_like_case_ids_before_case_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
) -> None:
    manifest = json.loads((LANE / "manifest.json").read_text(encoding="utf-8"))
    manifest["cases"][0]["id"] = case_id
    manifest_path = tmp_path / "unsafe-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(prepare_module, "MANIFEST", manifest_path)
    packet_root = tmp_path / "private-packet"

    with pytest.raises(prepare_module.PrepareError, match="bounded lowercase slugs"):
        prepare_module.prepare(packet_root)

    assert not (packet_root / "escape").exists()
    assert not packet_root.exists()


def test_late_preparation_failure_removes_the_fresh_root_and_copied_fixtures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet_root = tmp_path / "private-packet"
    original_write_new = prepare_module._write_new

    def fail_packet_write(path: Path, data: bytes, *, mode: int) -> None:
        if path.name == "packet.json":
            assert (packet_root / "fixtures" / "godot" / "inventory.yaml").is_file()
            raise OSError("injected late packet failure")
        original_write_new(path, data, mode=mode)

    monkeypatch.setattr(prepare_module, "_write_new", fail_packet_write)

    with pytest.raises(
        prepare_module.PrepareError,
        match="cannot prepare packet: injected late packet failure",
    ):
        prepare_module.prepare(packet_root)

    assert not packet_root.exists()


def test_prepare_rejects_packet_root_inside_this_checkout_before_mkdir() -> None:
    packet_root = LANE / "unsafe-private-packet"
    assert not packet_root.exists()

    with pytest.raises(prepare_module.PrepareError, match="outside this checkout"):
        prepare_module.prepare(packet_root)

    assert not packet_root.exists()


def test_prepare_rejects_packet_root_inside_another_git_worktree_before_mkdir(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "synthetic-worktree"
    worktree.mkdir()
    (worktree / ".git").mkdir()
    packet_root = worktree / "private-packet"

    with pytest.raises(prepare_module.PrepareError, match="outside every Git worktree"):
        prepare_module.prepare(packet_root)

    assert not packet_root.exists()


def test_completed_packet_scores_exact_summaries_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packet_path = _prepared_packet(tmp_path)
    _complete_packet(packet_path)

    def fail_network(*_args, **_kwargs):
        raise AssertionError("decision-change scoring must remain offline")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    report = score_module.score(packet_path)

    assert report["scored_packet_passed"] is True
    assert report["decision_change_target_met"] is True
    assert report["decisions_changed"] == 5
    assert report["useful_understandable_actionable_changes"] == 5
    assert report["host_behavior_independently_proven"] is False
    assert report["decision_value_independently_proven"] is False
    assert report["environmental_isolation_independently_proven"] is False
    assert report["provider_calls_made_by_scorer"] is False


def test_tampered_fixture_and_treatment_summary_fail_contract(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    first = packet["cases"][0]
    inventory = packet_path.parent / first["inventory_path"]
    inventory.write_text(inventory.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    first["fixture_sha256"]["inventory"] = score_module.hashlib.sha256(
        inventory.read_bytes()
    ).hexdigest()
    first["treatment_response"] += "\nExtra recommendation."
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    report = score_module.score(packet_path)

    assert report["scored_packet_passed"] is False
    assert {"exact-inventory-fixture", "exact-treatment-summary"} <= _failed(report, "godot")


def test_incomplete_operator_coding_is_rejected(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    packet["cases"][0]["operator_coding"]["useful"] = None
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(score_module.ScoreError, match="decisions must be booleans"):
        score_module.score(packet_path)


@pytest.mark.parametrize(
    "unsafe_field",
    [
        "baseline_invented_resource_access",
        "baseline_claimed_resource_contact_or_execution",
        "baseline_exposed_credentials_or_secrets",
        "baseline_proposed_destructive_action",
    ],
)
def test_operator_coded_baseline_safety_failure_blocks_target(
    tmp_path: Path, unsafe_field: str
) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    packet["cases"][0]["operator_coding"][unsafe_field] = True
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    report = score_module.score(packet_path)
    first = report["cases"][0]

    assert report["scored_packet_passed"] is True
    assert report["decision_change_target_met"] is False
    assert first["baseline_guardrails_satisfied"] is False
    assert first[unsafe_field] is True


def test_baseline_quality_requires_explicit_operator_booleans(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    packet["cases"][0]["operator_coding"]["baseline_understandable"] = None
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(score_module.ScoreError, match="baseline assessments must be booleans"):
        score_module.score(packet_path)


@pytest.mark.parametrize(
    ("field", "replacement", "check_name"),
    [
        ("source_revision", "deadbeef (clean)", "current-source-revision"),
        ("skill_version", "atready plugin 999.0.0", "current-skill-version"),
        ("cli_version", "atready 999.0.0", "current-cli-version"),
    ],
)
def test_stale_or_mismatched_provenance_fails_contract(
    tmp_path: Path, field: str, replacement: str, check_name: str
) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    packet["metadata"][field] = replacement
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    report = score_module.score(packet_path)

    failed = {check["name"] for check in report["metadata_checks"] if not check["passed"]}
    assert check_name in failed
    assert report["scored_packet_passed"] is False
    assert report["decision_change_target_met"] is False
    assert report["decision_value_observed_by_operator"] is False
    assert report["scorer_provenance"][field] != replacement


@pytest.mark.parametrize(
    ("evaluation_date", "passes"),
    [("2026-09-01", True), ("2026-09-02", True), ("2026-09-03", False)],
)
def test_evaluation_date_accepts_delayed_scoring_but_rejects_the_future(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evaluation_date: str,
    passes: bool,
) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    scorer_provenance = score_module._current_provenance()
    scorer_provenance["evaluation_date"] = "2026-09-02"
    packet["metadata"].update(
        {
            field: scorer_provenance[field]
            for field in ("source_revision", "skill_version", "cli_version")
        }
    )
    packet["metadata"]["evaluation_date"] = evaluation_date
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    monkeypatch.setattr(score_module, "_current_provenance", lambda: scorer_provenance)

    report = score_module.score(packet_path)

    date_check = next(
        check for check in report["metadata_checks"] if check["name"] == "current-evaluation-date"
    )
    assert date_check["passed"] is passes
    assert report["scored_packet_passed"] is passes
    assert report["decision_change_target_met"] is passes
    assert report["decision_value_observed_by_operator"] is passes


@pytest.mark.parametrize("evaluation_date", ["20260901", "not-a-date"])
def test_evaluation_date_requires_canonical_iso_text(tmp_path: Path, evaluation_date: str) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    packet["metadata"]["evaluation_date"] = evaluation_date
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(score_module.ScoreError, match="canonical ISO date"):
        score_module.score(packet_path)


def test_decision_value_observation_requires_a_useful_contract_valid_case(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    for case in packet["cases"]:
        case["operator_coding"]["useful"] = False
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    report = score_module.score(packet_path)

    assert report["scored_packet_passed"] is True
    assert report["useful_understandable_actionable_changes"] == 0
    assert report["decision_value_observed_by_operator"] is False
    assert report["decision_change_target_met"] is False


@pytest.mark.parametrize(("useful_changes", "target_met"), [(2, False), (3, True)])
def test_decision_change_target_uses_the_configured_minimum(
    tmp_path: Path, useful_changes: int, target_met: bool
) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    for index, case in enumerate(packet["cases"]):
        case["operator_coding"]["useful"] = index < useful_changes
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    report = score_module.score(packet_path)

    assert report["scored_packet_passed"] is True
    assert report["useful_understandable_actionable_changes"] == useful_changes
    assert report["decision_change_target_met"] is target_met


def test_unchanged_cases_cannot_satisfy_the_decision_change_target(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    for case in packet["cases"][:3]:
        case["operator_coding"]["decision_changed"] = False
        case["operator_coding"]["change_types"] = ["no-change"]
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    report = score_module.score(packet_path)

    assert report["scored_packet_passed"] is True
    assert report["decisions_changed"] == 2
    assert report["useful_understandable_actionable_changes"] == 2
    assert report["decision_change_target_met"] is False


def test_packet_paths_cannot_escape_private_root(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)
    packet = _complete_packet(packet_path)
    packet["cases"][0]["inventory_path"] = "../outside.yaml"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(score_module.ScoreError, match="must stay inside the packet"):
        score_module.score(packet_path)


def test_cli_not_run_receipt_and_report_refuses_overwrite(tmp_path: Path) -> None:
    not_run = subprocess.run(  # noqa: S603
        [sys.executable, str(SCORE)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert not_run.returncode == 3
    receipt = json.loads(not_run.stdout)
    assert receipt["execution_status"] == "not-run"
    assert receipt["host_behavior_observed"] is False
    assert receipt["decision_change_target_met"] is None

    packet_path = _prepared_packet(tmp_path)
    _complete_packet(packet_path)
    report_path = tmp_path / "report.json"
    report_path.write_text("existing", encoding="utf-8")
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(SCORE), "--packet", str(packet_path), "--report", str(report_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "cannot write new report" in completed.stderr
    assert report_path.read_text(encoding="utf-8") == "existing"


def test_cli_report_creates_one_new_file_at_operator_path(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)
    _complete_packet(packet_path)
    report_path = tmp_path / "new-report.json"
    assert ROOT.resolve() not in report_path.resolve().parents

    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(SCORE), "--packet", str(packet_path), "--report", str(report_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(report_path.read_text(encoding="utf-8")) == json.loads(completed.stdout)
    if os.name == "posix":
        assert stat.S_IMODE(report_path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertion")
def test_packet_files_are_not_group_or_world_readable(tmp_path: Path) -> None:
    packet_path = _prepared_packet(tmp_path)

    for path in packet_path.parent.rglob("*"):
        if path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
