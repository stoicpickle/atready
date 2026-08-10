from __future__ import annotations

import importlib.util
import runpy
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "verify_readme_rendering.py"
AGENT_GUIDE = ROOT / "AGENTS.md"
FRONT_PAGE_GUIDE = ROOT / "docs" / "FRONT_PAGE_REVIEW.md"
PR_TEMPLATE = ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"


@pytest.fixture(scope="module")
def rendered_link_validator() -> tuple[Callable[[str], None], type[Exception]]:
    namespace = runpy.run_path(str(SCRIPT))
    return namespace["_validate_rendered_links"], namespace["ReadmeRenderingError"]


@pytest.mark.parametrize(
    "rendered",
    [
        '<p><a href="http://example.com">insecure</a></p>',
        '<p><a href="http://www.example.com">bare GFM link</a></p>',
        '<p><a href="docs/relative.md">relative</a></p>',
        '<p><a href="">empty</a></p>',
        '<p><img src="//example.com/image.png"></p>',
        '<p><img src="mailto:image@example.com"></p>',
        '<p><img src="#local-image"></p>',
    ],
    ids=(
        "http",
        "bare-www",
        "relative",
        "empty",
        "protocol-relative",
        "mailto-image",
        "fragment-image",
    ),
)
def test_rendered_link_validator_refuses_channel_relative_or_unsafe_links(
    rendered_link_validator: tuple[Callable[[str], None], type[Exception]],
    rendered: str,
) -> None:
    validator, error_type = rendered_link_validator

    with pytest.raises(error_type, match="channel-relative or unsafe links"):
        validator(rendered)


def test_rendered_link_validator_accepts_channel_safe_links(
    rendered_link_validator: tuple[Callable[[str], None], type[Exception]],
) -> None:
    validator, _ = rendered_link_validator

    validator(
        """
        <p><a href="https://example.com/path">absolute</a></p>
        <p><a href="mailto:maintainer@example.com">email</a></p>
        <p><a href="#section">section</a></p>
        <p><img src="https://example.com/image.png"></p>
        """
    )


def test_current_readme_rendering_is_channel_safe() -> None:
    if importlib.util.find_spec("readme_renderer") is None:
        pytest.skip("locked release checks are not installed in the source-only environment")

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_front_page_review_is_a_pre_review_and_pre_commit_gate() -> None:
    agent_guide = AGENT_GUIDE.read_text(encoding="utf-8")
    front_page_guide = FRONT_PAGE_GUIDE.read_text(encoding="utf-8")
    pull_request_template = PR_TEMPLATE.read_text(encoding="utf-8")

    assert "Before any code review or commit" in agent_guide
    assert "docs/FRONT_PAGE_REVIEW.md" in agent_guide
    assert "Open the rendered `README.md` as a first-time visitor" in front_page_guide
    assert "docs/assets/atready-cli.png" in front_page_guide
    assert "scripts/verify_cli_screenshot.py" in front_page_guide
    assert "scripts/verify_readme_rendering.py" in front_page_guide
    assert "I rendered and reviewed the repository front page" in pull_request_template

    for receipt in (
        "Front page: updated",
        "Front page: reviewed; no change needed",
    ):
        assert receipt in agent_guide
        assert receipt in front_page_guide
