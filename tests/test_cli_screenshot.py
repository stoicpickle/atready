from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parents[1]
SCREENSHOT = ROOT / "docs" / "assets" / "atready-cli.png"


def test_committed_cli_screenshot_matches_the_real_welcome_command() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/render_cli_screenshot.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "matches the real welcome command" in result.stdout

    with Image.open(SCREENSHOT) as image:
        assert image.size == (1320, 680)
        assert image.mode == "RGB"
