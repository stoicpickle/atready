from __future__ import annotations

import re
from pathlib import Path

from atready.cli import main

ROOT = Path(__file__).parents[1]
README = ROOT / "README.md"
TRY_GUIDE = ROOT / "docs" / "TRY_ATREADY.md"

PUBLIC_INSTALL = (
    "uv tool install --force --no-config --no-python-downloads \\\n"
    "  --default-index https://pypi.org/simple \\\n"
    "  'git+https://github.com/stoicpickle/atready.git@main'"
)
SHELL_FALLBACK = "uv tool update-shell"
THREE_STEP_JOURNEY = "atready init\natready add\natready plan"


def test_readme_leads_with_the_public_install_and_one_command_demo() -> None:
    readme = README.read_text(encoding="utf-8")
    onboarding = readme.split("## Reusable and scripted workflows", 1)[0]
    normalized = " ".join(onboarding.split())

    assert "## Install and try AtReady" in onboarding
    assert PUBLIC_INSTALL in onboarding
    assert SHELL_FALLBACK in onboarding
    assert "close and reopen the terminal, then try again" in normalized
    assert "atready demo\n```" in onboarding
    assert "atready demo inventory" not in onboarding
    assert "uv tool install ." not in onboarding
    assert readme.index(PUBLIC_INSTALL) < readme.index(SHELL_FALLBACK)
    assert "`UV_INDEX`, `UV_INDEX_URL`, or `UV_EXTRA_INDEX_URL`" in onboarding
    assert readme.index(SHELL_FALLBACK) < readme.index("atready demo\n```")
    assert (
        "does not read or change your personal resource list, create\n"
        "files, use the network, or contact or run any resource"
    ) in onboarding


def test_readme_preserves_the_three_step_journey_and_contributor_setup() -> None:
    readme = README.read_text(encoding="utf-8")
    beginner = readme.split("## Your next three steps", 1)[1].split(
        "## Reusable and scripted workflows", 1
    )[0]
    contributing = readme.split("## Feedback and contributing", 1)[1]

    assert "### 1. Create your resource list" in beginner
    assert "### 2. Add one resource" in beginner
    assert "### 3. Check resource fit for a small project" in beginner
    assert beginner.index("atready init") < beginner.index("atready add")
    assert beginner.index("atready add") < beginner.index("atready plan")
    assert "git clone https://github.com/stoicpickle/atready.git" in contributing
    assert "uv sync --group dev" in contributing


def test_first_time_guide_uses_the_same_short_public_journey() -> None:
    guide = TRY_GUIDE.read_text(encoding="utf-8")
    normalized = " ".join(guide.split())

    assert "## 1. Install AtReady" in guide
    assert PUBLIC_INSTALL in guide
    assert SHELL_FALLBACK in guide
    assert "close and reopen the terminal, then try again" in normalized
    assert "## 2. Run the safe demo" in guide
    assert "atready demo\n```" in guide
    assert "## 3. Try your own resource fit check" in guide
    assert THREE_STEP_JOURNEY in guide
    assert guide.index(PUBLIC_INSTALL) < guide.index(SHELL_FALLBACK)
    assert "`UV_INDEX`, `UV_INDEX_URL`, or `UV_EXTRA_INDEX_URL`" in guide
    assert guide.index(SHELL_FALLBACK) < guide.index("atready --version")
    assert guide.index("atready --version") < guide.index("atready demo\n```")
    assert guide.index("atready demo\n```") < guide.index(THREE_STEP_JOURNEY)
    assert "git clone" not in guide
    assert "uv tool install ." not in guide
    assert "atready demo inventory" not in guide


def test_public_copy_positions_atready_as_codex_resource_context() -> None:
    readme = README.read_text(encoding="utf-8")
    guide = TRY_GUIDE.read_text(encoding="utf-8")

    assert "Help Codex plan with what you already have." in readme
    assert "Codex owns the project plan." in readme
    assert "AtReady contributes resource context" in readme
    assert "The Codex skill is the intended conversational experience." in readme
    assert "The CLI is its local engine and a\nstandalone fallback" in readme
    assert "AtReady is a small, local-first planning tool" not in readme
    assert "The CLI is the product" not in readme
    assert "It does not create the complete project plan." in guide
    assert "complete example plan" not in guide.casefold()
    assert "example resource-fit advice" in guide


def test_demo_sample_keeps_the_exact_safety_close_after_next_steps() -> None:
    readme = README.read_text(encoding="utf-8")
    expected_close = (
        "Ready to try your own roster?\n"
        "1. atready init\n"
        "2. atready add\n"
        "3. atready plan\n"
        "No routed project resources were contacted or run."
    )

    assert expected_close in readme


def test_readme_demo_sample_matches_the_real_cli(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ATREADY_HOME", str(tmp_path / "private-home"))

    assert main(["demo"]) == 0
    output = capsys.readouterr().out.rstrip()
    readme = README.read_text(encoding="utf-8")
    match = re.search(r"The result looks like this:\n\n```text\n(.*?)\n```", readme, re.DOTALL)

    assert match is not None
    assert match.group(1) == output
