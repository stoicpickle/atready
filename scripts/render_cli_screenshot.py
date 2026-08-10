"""Render the real AtReady welcome command as a deterministic terminal screenshot."""

from __future__ import annotations

import argparse
import filecmp
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets" / "atready-cli.png"
CANONICAL_BYTE_PLATFORM = "darwin"
WIDTH = 1320
HEIGHT = 680
BACKGROUND = (10, 14, 24)
TERMINAL = (17, 24, 39)
FRAME = (47, 57, 78)
TEXT = (226, 232, 240)
MUTED = (139, 151, 173)
ANSI_RGB = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m|\x1b\[0m")


def _welcome_output() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "atready.cli", "welcome", "--color", "always"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    if result.stderr:
        raise RuntimeError("welcome command unexpectedly wrote to stderr")
    return result.stdout


def _segments(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    color = TEXT
    position = 0
    output: list[tuple[str, tuple[int, int, int]]] = []
    for match in ANSI_RGB.finditer(line):
        if match.start() > position:
            output.append((line[position : match.start()], color))
        color = TEXT if match.group(1) is None else tuple(int(match.group(i)) for i in range(1, 4))
        position = match.end()
    if position < len(line):
        output.append((line[position:], color))
    return output


def render(path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (32, 32, WIDTH - 32, HEIGHT - 32), radius=18, fill=TERMINAL, outline=FRAME
    )
    for x, color in ((62, (224, 65, 55)), (86, (232, 172, 54)), (110, (61, 188, 121))):
        draw.ellipse((x - 7, 56 - 7, x + 7, 56 + 7), fill=color)
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=17)
    draw.text(
        (WIDTH - 58, 48),
        "atready welcome --color always",
        font=small,
        fill=MUTED,
        anchor="ra",
    )
    draw.line((48, 80, WIDTH - 48, 80), fill=FRAME, width=1)

    x_start = 68
    y = 104
    line_height = 30
    for line in _welcome_output().splitlines():
        x = x_start
        for value, color in _segments(line):
            draw.text((x, y), value, font=font, fill=color)
            x += draw.textlength(value, font=font)
        y += line_height
    image.save(path, format="PNG", optimize=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        with TemporaryDirectory() as temporary:
            candidate = Path(temporary) / OUTPUT.name
            render(candidate)
            if not OUTPUT.is_file():
                print("CLI screenshot is missing", file=sys.stderr)
                return 1
            with Image.open(candidate) as candidate_image, Image.open(OUTPUT) as committed_image:
                if candidate_image.size != (WIDTH, HEIGHT) or candidate_image.mode != "RGB":
                    print("rendered CLI screenshot has the wrong image contract", file=sys.stderr)
                    return 1
                if committed_image.size != (WIDTH, HEIGHT) or committed_image.mode != "RGB":
                    print("committed CLI screenshot has the wrong image contract", file=sys.stderr)
                    return 1
            if sys.platform == CANONICAL_BYTE_PLATFORM and not filecmp.cmp(
                candidate, OUTPUT, shallow=False
            ):
                print(
                    "CLI screenshot is stale; rerun scripts/render_cli_screenshot.py",
                    file=sys.stderr,
                )
                return 1
        print("CLI screenshot matches the real welcome command.")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    render(OUTPUT)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
