from __future__ import annotations

import socket
from pathlib import Path

from atready.catalog import InventoryCatalog
from atready.models import RoutePlan
from atready.project import project_from_path
from atready.render import render_agent_summary, render_summary
from atready.routing import route

ROOT = Path(__file__).parents[1]
EVAL = ROOT / "evals" / "PLAN_COMMUNICATION_EVAL.md"
EVAL_README = ROOT / "evals" / "README.md"
FIXTURES = ROOT / "evals" / "fixtures"


def _route_fixture(scenario: str, inventory_name: str | None = None) -> RoutePlan:
    project = project_from_path(FIXTURES / f"project-{scenario}.yaml")
    inventory_file = inventory_name or f"inventory-{scenario}.yaml"
    inventory = InventoryCatalog.from_path(FIXTURES / inventory_file, today=project.as_of).inventory
    return route(inventory, project, allow_demo=True)


def test_plan_communication_eval_is_linked_and_keeps_manual_proof_boundary() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")
    eval_readme = EVAL_README.read_text(encoding="utf-8")

    assert "[plan communication evaluation](PLAN_COMMUNICATION_EVAL.md)" in eval_readme
    assert "Static tests do not prove real model behavior." in eval_readme
    assert "do not prove how a selected model will behave" in evaluation
    assert "actual host surface" in evaluation
    assert "All fixtures are synthetic." in evaluation


def test_plan_communication_eval_scenarios_and_fixtures_do_not_orphan() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")

    for heading in (
        "## Scenario A: straightforward assignment",
        "## Scenario B: gap from an unconfirmed resource",
        "## Scenario C: support and alternate communication",
        "### Case C1: complementary support",
        "### Case C2: reserved alternate",
        "## Scenario D: explicit concise response",
        "## Scenario E: roster cannot be loaded",
    ):
        assert heading in evaluation

    fixture_names = (
        "inventory.yaml",
        "project-godot.yaml",
        "inventory-unverified.yaml",
        "project-unverified.yaml",
        "inventory-degraded.yaml",
        "project-degraded.yaml",
        "inventory-alternate.yaml",
        "project-alternate.yaml",
    )
    for fixture_name in fixture_names:
        fixture = ROOT / "evals" / "fixtures" / fixture_name
        assert fixture.exists(), f"missing evaluation fixture: {fixture_name}"
        assert f"evals/fixtures/{fixture_name}" in evaluation


def test_plan_communication_fixtures_match_the_declared_json_evidence(monkeypatch) -> None:
    def fail_network(*_args, **_kwargs):
        raise AssertionError("plan communication fixtures must remain offline")

    monkeypatch.setattr(socket.socket, "connect", fail_network)

    straightforward = _route_fixture("godot", "inventory.yaml")
    assert [
        (assignment.workstream_id, assignment.primary.resource_id)
        for assignment in straightforward.assignments
    ] == [
        ("architecture", "codex"),
        ("implementation", "codex"),
        ("review", "coderabbit"),
    ]
    assert all(assignment.support is None for assignment in straightforward.assignments)
    assert all(assignment.alternate is None for assignment in straightforward.assignments)
    assert all(not assignment.unresolved_gaps for assignment in straightforward.assignments)

    unverified = _route_fixture("unverified")
    research = unverified.assignments[0]
    unconfirmed = unverified.dispositions[0]
    assert research.workstream_id == "research"
    assert research.primary is None
    assert research.gap_reason == (
        "No verified eligible resource satisfies the required capabilities and constraints."
    )
    assert unconfirmed.resource_id == "unconfirmed-researcher"
    assert unconfirmed.status.value == "unverified"
    assert unconfirmed.reason_code == "access-unknown"

    support = _route_fixture("degraded", "inventory-degraded.yaml")
    delivery = next(item for item in support.assignments if item.workstream_id == "delivery")
    assert delivery.primary.resource_id == "builder"
    assert delivery.support.resource_id == "reviewer"
    assert delivery.support_gap == ["review"]
    assert delivery.unresolved_gaps == []

    alternate = _route_fixture("alternate")
    verification = alternate.assignments[0]
    assert verification.primary.resource_id == "verifier-a"
    assert verification.alternate.resource_id == "verifier-b"
    assert verification.alternate_activation_condition == (
        "Re-check eligibility and obtain separate authorization if the primary cannot proceed."
    )


def test_plan_communication_cli_summaries_keep_the_default_contract(monkeypatch) -> None:
    def fail_network(*_args, **_kwargs):
        raise AssertionError("plan communication fixtures must remain offline")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    raw_terms = (
        "score_bp",
        "adjusted_score_bp",
        "components_bp",
        "plan_id",
        "inventory_fingerprint",
        "project_fingerprint",
        "selected-primary",
        "selected-support",
        "reserved-alternate",
        "access-unknown",
        "unknown-provenance",
    )

    for scenario, inventory_name in (
        ("godot", "inventory.yaml"),
        ("unverified", None),
        ("degraded", "inventory-degraded.yaml"),
        ("alternate", None),
    ):
        result = _route_fixture(scenario, inventory_name)
        summary = render_summary(result, width=80)

        assert "Next:" in summary
        assert summary.rstrip().endswith("No routed project resources were contacted or run.")
        assert not any(term in summary for term in raw_terms)

    unverified_summary = render_summary(_route_fixture("unverified"), width=80)
    flattened = " ".join(unverified_summary.split())
    assert "Confirm access" in flattened
    assert "the confidence basis" in flattened
    assert "the declaration source" in flattened
    assert "remaining usage" in flattened
    assert "current availability for Synthetic Unconfirmed Researcher" in flattened
    assert "then route again." in flattened


def test_deterministic_agent_presentations_preserve_the_cross_surface_contract(
    monkeypatch,
) -> None:
    def fail_network(*_args, **_kwargs):
        raise AssertionError("deterministic presentations must remain offline")

    monkeypatch.setattr(socket.socket, "connect", fail_network)
    raw_terms = (
        "score_bp",
        "adjusted_score_bp",
        "components_bp",
        "plan_id",
        "inventory_fingerprint",
        "project_fingerprint",
        "selected-primary",
        "selected-support",
        "reserved-alternate",
        "access-unknown",
        "unknown-provenance",
    )

    straightforward = render_agent_summary(_route_fixture("godot", "inventory.yaml"))
    assert len(straightforward.split()) <= 100
    assert straightforward.count("Synthetic Codex Seat") == 1
    assert straightforward.count("Synthetic CodeRabbit Seat") == 1
    assert "Architecture, Implementation" in straightforward
    assert "Independent review" in straightforward

    unverified = render_agent_summary(_route_fixture("unverified"))
    assert "0 of 1 steps assigned; 1 open gap" in unverified
    assert "Confirm access" in " ".join(unverified.split())

    support = render_agent_summary(_route_fixture("degraded", "inventory-degraded.yaml"))
    assert support.count("Synthetic Reviewer") == 1
    assert "covering review" in support

    alternate = render_agent_summary(_route_fixture("alternate"))
    assert alternate.count("Synthetic Verifier B") == 1
    assert "AtReady will not switch automatically" in alternate

    for presentation in (straightforward, unverified, support, alternate):
        assert not any(term in presentation for term in raw_terms)
        assert presentation.rstrip().endswith("No routed project resources were contacted or run.")


def test_plan_communication_eval_requires_json_parity_and_plain_defaults() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")
    normalized = " ".join(evaluation.split())

    for field in (
        "`workstream_id`",
        "`primary.resource_id`, or `null`",
        "`support.resource_id`, or `null`",
        "`alternate.resource_id`, or `null`",
        "`support_gap`",
        "`unresolved_gaps`",
        "`gap_reason`",
    ):
        assert field in evaluation

    for requirement in (
        "Assignment and gap parity",
        "Use plain language",
        "Give one concrete next action",
        "Keep raw scores, status values, and fingerprints out of view",
        "No routed project resources were contacted or run.",
        "AtReady will not switch automatically",
        "fresh eligibility check plus separate authorization",
        "no more than 100 words",
        "name each selected resource once",
        "one CLI-grounded reason for each selected resource",
        "no more than three short sentences and 60 words",
        "name the missing roster as the exact blocker",
        "nothing was routed or run",
        "compare the Codex response bytes with `summary` exactly",
        "one route calculation",
        "`presentation_status: ready`",
        "`presentation_status: limit-conflict`",
        "one bounded recovery action",
        "exact conflict-summary parity",
    ):
        assert requirement in normalized

    assert "Be concise. Return no more than 100 words and 10 lines." in evaluation
    assert "--max-words 100 --max-lines 10" in evaluation
    assert "--max-words 5 --max-lines 1" in evaluation
    assert evaluation.count("--format presentation") == 7
    for presentation_receipt in (
        "a-presentation.json",
        "b-presentation.json",
        "c1-presentation.json",
        "c2-presentation.json",
        "d-presentation.json",
        "d-conflict-presentation.json",
        "e-presentation.json",
    ):
        assert presentation_receipt in evaluation
    assert "MISSING_EPHEMERAL_INVENTORY_PATH" in evaluation
    assert 'if [ -e "$EVAL_DIR/missing-inventory.yaml" ]' in evaluation
    assert "FAIL: expected missing inventory path already exists" in evaluation
    assert 'if [ -s "$EVAL_DIR/e-presentation.json" ]' in evaluation
    assert 'grep -Fq -- "$EVAL_DIR/missing-inventory.yaml" "$EVAL_DIR/e-error.txt"' in evaluation
    assert "Did you route anything? Answer in one sentence." in evaluation
    assert "The follow-up must answer directly in one sentence." in evaluation
    assert "including the exact final boundary" in normalized
    assert "compare the Codex response bytes with `summary` exactly" in normalized
    assert "confirm that `route` still exactly equals `a.json`" in normalized
    assert "failed without a presentation envelope" in normalized
    assert "generic provider, price, quota, privacy, rights, or licensing checklist" in normalized
    assert "b_json_status=0" in evaluation
    assert "b_cli_status=0" in evaluation
    assert "b_presentation_status=0" in evaluation
    assert 'if [ "$route_status" -ne 3 ]' in evaluation
    assert 'if [ ! -s "$output" ]' in evaluation
    assert "Expected retained gap output" in evaluation
    assert (
        "must retain their output while returning the documented gap exit status `3`" in normalized
    )

    for raw_term in (
        "score_bp",
        "adjusted_score_bp",
        "components_bp",
        "plan_id",
        "inventory_fingerprint",
        "project_fingerprint",
        "selected-primary",
        "selected-support",
        "reserved-alternate",
        "access-unknown",
        "unknown-provenance",
    ):
        assert f"`{raw_term}`" in evaluation


def test_plan_communication_eval_has_comprehension_and_observation_gates() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")

    questions = (
        "1. Which resource owns each workstream?",
        "2. Why was each selected resource chosen, and what help does support provide?",
        "3. What is missing, blocked, or not confirmed?",
        "4. Did AtReady contact or run any routed resource?",
        "5. What is the next action the response recommends?",
    )
    assert all(question in evaluation for question in questions)
    assert "## Observation rubric for 3 to 5 developers" in evaluation
    assert "Safety comprehension is 100% across all observers." in evaluation
    assert "At least 80% of all remaining comprehension answers are correct." in evaluation
    assert "Any other answer is a critical failure" in evaluation


def test_public_eval_copy_has_no_unicode_dash_punctuation() -> None:
    for path in (EVAL, EVAL_README):
        text = path.read_text(encoding="utf-8")
        assert "\N{EM DASH}" not in text
        assert "\N{EN DASH}" not in text
