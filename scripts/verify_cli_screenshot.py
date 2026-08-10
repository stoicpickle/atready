"""Validate the committed AtReady CLI screenshot contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT = ROOT / "docs" / "assets" / "atready-cli.png"
EXPECTED_SIZE = (1728, 1242)


def validation_error(path: Path) -> str | None:
    if not path.is_file():
        return "CLI screenshot is missing"
    try:
        image = Image.open(path)
    except OSError:
        return "CLI screenshot cannot be opened"
    with image:
        if image.size != EXPECTED_SIZE or image.mode != "RGBA":
            return "CLI screenshot has the wrong image contract"
        colors = image.convert("RGB").getcolors(maxcolors=100)
        if colors is not None and len(colors) < 100:
            return "CLI screenshot does not contain enough visual detail"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=SCREENSHOT)
    args = parser.parse_args()
    error = validation_error(args.path)
    if error is not None:
        print(error, file=sys.stderr)
        return 1
    print("CLI screenshot satisfies the committed image contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
