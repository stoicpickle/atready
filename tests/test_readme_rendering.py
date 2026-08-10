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
