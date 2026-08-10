from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
EVAL = ROOT / "evals" / "RESOURCE_INTAKE_EVAL.md"
EVAL_README = ROOT / "evals" / "README.md"
PRIVATE_BETA = ROOT / "docs" / "PRIVATE_BETA.md"
DIRECTORY_PACKET = ROOT / "docs" / "DIRECTORY_SUBMISSION.md"


def test_blank_slate_intake_eval_is_linked_by_its_real_consumers() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")
    eval_readme = EVAL_README.read_text(encoding="utf-8")
    private_beta = PRIVATE_BETA.read_text(encoding="utf-8")
    directory_packet = DIRECTORY_PACKET.read_text(encoding="utf-8")

    assert "[blank-slate resource-intake evaluation](RESOURCE_INTAKE_EVAL.md)" in eval_readme
    link = "[blank-slate resource-intake evaluation](../evals/RESOURCE_INTAKE_EVAL.md)"
    assert link in private_beta
    assert link in directory_packet
    assert "There is deliberately no provider calling evaluation runner" in evaluation
    assert "separate **new Codex task**" in private_beta
    assert "source-level or installed-wheel acceptance harness does not substitute" in private_beta


def test_blank_slate_intake_eval_has_exact_conversation_only_scenarios() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")
    normalized = " ".join(evaluation.split())

    for heading in (
        "## Scenario A: CodeRabbit conversation-only Quick Setup",
        "## Scenario B: conversation-only path preserves unknowns",
        "## Scenario C: keep rendered preview and apply separate",
        "## Scenario D: missing roster requires separate creation approval",
        "## Local capability fallback probe",
    ):
        assert heading in evaluation

    for prompt in (
        "$project-atready Add CodeRabbit to my AtReady roster at "
        "<EPHEMERAL_INVENTORY_PATH>. Use Quick Setup and guide me. Do not preview or save yet.",
        "$project-atready Add one synthetic coding resource to <EPHEMERAL_INVENTORY_PATH>; use "
        "Quick Setup and guide me without inspecting my computer or accounts. I approve "
        "synthetic metadata in this host/model context.",
        "Do not save yet. Explain what saving this exact rendered preview would change and what "
        "evidence I would receive.",
        "$project-atready Add CodeRabbit to my AtReady roster at "
        "<MISSING_EPHEMERAL_INVENTORY_PATH>. Use Quick Setup and guide me. Do not create, preview, "
        "or save anything yet.",
        "Create one empty personal roster at <MISSING_EPHEMERAL_INVENTORY_PATH>. Do not preview or "
        "save a resource yet.",
        "$project-atready Add CodeRabbit to my AtReady roster. This host does not provide local "
        "command execution or filesystem access.",
    ):
        assert f"> `{prompt}" in evaluation

    for first_response_contract in (
        "explicitly begin the Add CodeRabbit intake",
        "one friendly, consolidated card with exactly four visible question bullets",
        "**Identity**, **Strengths**, **Readiness**, and **Safety**",
        "`CodeRabbit (coderabbit)`",
        "`Code review agent (review-agent)`",
        "`Code review (code-review)`",
        "`Repository analysis (repository-analysis)`",
        "answers supply facts only, not preview or save authorization",
    ):
        assert first_response_contract in normalized

    assert "conversation-only" in evaluation
    assert "performs no executable discovery" in evaluation
    assert "version inspection" in evaluation
    assert "resource discover" not in evaluation
    assert "--inspect-version" not in evaluation
    assert "discovery-authorized" not in evaluation
    assert "version-probe-authorized" not in evaluation
    assert "$project-quartermaster" not in evaluation
    assert "direct the evaluator to run `atready add` in a local terminal" in normalized
    assert "add request does not authorize roster creation" in normalized
    assert "inventory_kind: personal" in normalized
    assert "revision_protection: nonce-v1-present" in normalized
    assert "not an add-resource preview or apply" in normalized
    assert "fail closed instead of overwriting it" in normalized
    assert "private backup and atomic-replacement guarantees" in normalized


def test_blank_slate_intake_eval_binds_recap_preview_and_apply() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")
    normalized = " ".join(evaluation.split())

    for coderabbit_contract in (
        "PR reviews are the primary routing interaction",
        "CLI is secondary context only",
        "code review strong and repository analysis solid",
        "`strong` to `0.80`",
        "`solid` to `0.65`",
        "120 review requests remaining",
        "`review-request`",
        "`selection-facts-declared`",
        "Authorize exactly one no-write preview of that entry",
        "actual CLI preview without `--apply`",
        "expected revision, and plan token",
        "Save exactly this rendered coderabbit entry",
        "then run strict inventory validation",
    ):
        assert coderabbit_contract in normalized

    for response_shape_contract in (
        "All roster-task responses in Scenarios A-C must omit `Plan` and `Resource fit` headings.",
        "It must not run a synthetic route check from the save approval.",
        "add another resource, plan with the roster, or finish",
    ):
        assert response_shape_contract in normalized


def test_blank_slate_intake_eval_has_bounded_rubric_and_failure_gates() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")
    normalized = " ".join(evaluation.split())

    assert "Pass: at least **10/12** and no critical" in evaluation
    dimensions = (
        "Turns to preview",
        "Consolidated card and plain language",
        "Profile, mapping, and capacity",
        "Unknown and readiness handling",
        "Preview, apply, and response-shape separation",
        "Conversation-only and fallback boundary",
    )
    assert all(
        f"### {index}. {dimension} - 0 to 2 points" in evaluation
        for index, dimension in enumerate(dimensions, 1)
    )
    for state in (
        "`questions-only`",
        "`preview-authorized`",
        "`preview-shown`",
        "`apply-authorized`",
        "`applied`",
        "`roster-creation-authorized`",
        "`roster-initialized`",
        "`initialization-failed`",
        "`validation-failed`",
    ):
        assert state in evaluation
    assert "new explicit authorization naming the operation and target" in normalized
    assert "no-write preview and obtain a later, separate exact-save approval" in normalized
    for failure in (
        "inspecting or searching for a CodeRabbit executable, version, configuration, account",
        "printing or enumerating `PATH`",
        "preview before explicit authorization of the exact recap",
        "apply before a later explicit approval of the exact rendered preview",
        "inventing access, session, quota, capacity, provenance, verification date, capability, "
        "or score",
        "requesting, accepting, previewing, or storing a credential or session secret",
        "host lacks local command execution or filesystem access",
        "contacting an inventoried resource, dispatching a handoff",
    ):
        assert failure in normalized


def test_blank_slate_intake_eval_includes_safe_manual_transcript_template() -> None:
    evaluation = EVAL.read_text(encoding="utf-8")

    for heading in (
        "## Manual transcript template",
        "### Run metadata",
        "### Turn log",
        "### Rubric result",
        "### Critical-failure check",
        "### Value-free evidence",
    ):
        assert heading in evaluation
    assert "exact text synthetic" in evaluation
    assert "do not attach terminal history" in evaluation.casefold()
    normalized = " ".join(evaluation.split()).casefold()
    assert "completed transcripts belong in a local evaluation evidence packet" in normalized
    assert "local capability fallback reference" in normalized
