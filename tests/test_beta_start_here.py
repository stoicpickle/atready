from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
START = ROOT / "docs" / "BETA_START_HERE.md"


def test_beta_start_here_is_the_short_tester_entrypoint() -> None:
    text = START.read_text(encoding="utf-8")
    folded = " ".join(text.split())
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    private_beta = (ROOT / "docs" / "PRIVATE_BETA.md").read_text(encoding="utf-8")

    assert "Public beta" in readme
    assert "Public beta candidate" not in readme
    assert "docs/BETA_START_HERE.md" not in readme
    assert "[`BETA_START_HERE.md`](BETA_START_HERE.md)" in private_beta
    assert "## Self-serve beta graduation bar" in private_beta
    assert "at least five non-maintainer developers" in private_beta
    assert "at least four of five install" in private_beta
    assert "within 15 minutes without maintainer help" in private_beta
    assert "Any safety-boundary failure blocks graduation" in private_beta
    assert "## Run the quiet-activation check" in private_beta
    assert "`I use CodeRabbit on this repository.`" in private_beta
    assert "`Plan a logging refactor.`" in private_beta
    assert (
        "`I have a rough plan for a logging refactor. Use AtReady before implementation "
        "to briefly show where my saved resources fit in that plan.`" in private_beta
    )
    assert "without demanding a user-authored formal brief" in private_beta
    assert "fail the quiet-output check" in private_beta
    for owner_contract in (
        "organization-owned private beta repository",
        "beta-testers team with read-only repository access",
        "Until that boundary exists",
        "do not add testers to the personal development repository",
        "## Recommended one-command setup and update",
        "never changes GitHub access",
        "BETA_OWNER/BETA_REPOSITORY",
        "runtime-contract",
        "attempts to restore the retained prior verified pair",
    ):
        assert owner_contract in private_beta
    for helper_contract in (
        "release-candidate workflow name",
        "`workflow_dispatch` event",
        "configured release-owner secret",
    ):
        assert helper_contract in text
    assert len(text.splitlines()) < 220
    assert "small resource-fit companion" in text
    assert "before implementation begins" in folded
    assert "goal, rough plan, or written plan" in folded
    assert "matches your declared resources to planner-provided work" in folded
    assert "Codex owns project planning" in folded
    assert "does not log in to, contact, or run saved resources for project work" in folded
    assert "Do not install over an existing AtReady CLI" in folded
    assert "clean-install beta lane" in folded
    assert "does not migrate or remove a former Quartermaster" in folded
    assert "do not pipe a remote script into a shell or Python" in folded
    assert "PRIVATE_BETA.md" in text


def test_beta_start_here_proves_the_real_candidate_surface() -> None:
    text = START.read_text(encoding="utf-8")

    for required in (
        "python3 beta_setup.py install",
        "--repository BETA_OWNER/BETA_REPOSITORY",
        "--source-sha SOURCE_SHA",
        "--run-id RUN_ID",
        "--beta-root /ABSOLUTE/PATH/atready-beta",
        "py -3 .\\beta_setup.py install",
        "python3 beta_setup.py update",
        "--source-sha NEW_SOURCE_SHA",
        "--run-id NEW_RUN_ID",
        "python3 beta_setup.py status",
        "python3 beta_setup.py remove",
        "runtime contract",
        "attempts to restore the prior verified pair",
        "Start a **new Codex task**",
    ):
        assert required in text

    bash_blocks = re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL)
    assert len(bash_blocks) == 3
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to validate the documented beta command blocks")
    for block in bash_blocks:
        checked = subprocess.run(  # noqa: S603
            [bash, "-n"],
            input=block,
            text=True,
            capture_output=True,
            check=False,
        )
        assert checked.returncode == 0, checked.stderr


def test_beta_start_here_has_uncoached_value_and_recovery_prompts() -> None:
    text = START.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for prompt in (
        "Use $project-atready Quick Setup to add CodeRabbit to my resource roster at "
        "TEST_INVENTORY_PATH. Guide me through the preview first; do not save until I "
        "separately approve the exact rendered entry.",
        "Show my AtReady resource roster and explain what is still unknown. "
        "Do not change anything.",
        "I have a loose plan for a small synthetic logging feature: add structured logs, tests, "
        "and an independent review. Use AtReady before implementation to show where my saved "
        "resources fit across those steps. Keep the resource recommendation brief and do not "
        "contact or run anything.",
        "Continue without checking my computer.",
        "Keep unknowns unknown and ask only for information that blocks the preview.",
        "Nothing should be saved yet. Tell me which authorization stage we are at.",
        "Check whether the AtReady plugin and local runtime are compatible. "
        "Do not change my roster.",
    ):
        assert prompt in text

    for feedback in (
        "Did installation and the acceptance check pass on the first try?",
        "Could you add CodeRabbit without outside help?",
        "What was the first confusing phrase or moment?",
        "Did preview versus save feel clear?",
        "useful and quiet, or intrusive?",
    ):
        assert feedback in text

    assert "Never paste API keys" in normalized
    assert "Do not attach an inventory" in normalized
    assert "You should not have to write a formal AtReady brief or YAML" in normalized
    assert "Reply through the same private channel" in normalized
    assert "Removal does not delete an AtReady inventory" in normalized
    assert "move that exact folder to Trash" in normalized


def test_beta_walkthrough_exercises_three_question_coderabbit_quick_setup() -> None:
    start = START.read_text(encoding="utf-8")
    private_beta = (ROOT / "docs" / "PRIVATE_BETA.md").read_text(encoding="utf-8")
    walkthrough = " ".join(
        start.split("## 2. Add one resource", 1)[1]
        .split("## 3. See the quiet payoff", 1)[0]
        .split()
    ).casefold()
    owner_flow = " ".join(
        private_beta.split("Invoke the skill explicitly", 1)[1]
        .split("## Run the quiet-activation check", 1)[0]
        .split()
    ).casefold()

    for phrase in (
        "exactly three questions",
        "how strong it is for that work",
        "whether it is available now",
        "whether you would use it with private code or project files",
        "answer in an ordinary sentence",
        "the compact recap should show only purpose, strength, availability",
        "the later no-write preview carries ids, mappings, defaults, and target details",
    ):
        assert phrase in walkthrough
    for phrase in (
        "category and capability proposals hidden behind plain language",
        "strength for the proposed work, availability now, and whether you would use it with "
        "private code or project files",
        "the compact recap shows only purpose, strength, availability",
        "the no-write preview then carries the proposed ids, numeric mapping",
        "must not invent a plan, usage balance, account state, or evidence source",
    ):
        assert phrase in owner_flow
    assert (
        "atready must not start a review, log in, inspect an account or repository, install or "
        "update coderabbit, change settings, or claim authentication, quota, or availability"
    ) in walkthrough
    assert (
        "neither branch may start a coderabbit review, open or modify a pull request, log in, "
        "inspect repository configuration, install or update the cli or app, change provider "
        "settings, or promote executable presence into an authentication, quota, or availability "
        "claim"
    ) in owner_flow
