from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).parents[1]
SCREENSHOT = ROOT / "docs" / "assets" / "atready-cli.png"
EXPECTED_SIZE = (1728, 1242)


def _verify(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "scripts/verify_cli_screenshot.py", str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_committed_cli_screenshot_satisfies_the_image_contract() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_cli_screenshot.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "satisfies the committed image contract" in result.stdout

    with Image.open(SCREENSHOT) as image:
        assert image.size == EXPECTED_SIZE
        assert image.mode == "RGBA"


def test_screenshot_contract_rejects_missing_and_corrupt_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.png"
    result = _verify(missing)
    assert result.returncode != 0
    assert result.stderr == "CLI screenshot is missing\n"

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not a png")
    result = _verify(corrupt)
    assert result.returncode != 0
    assert result.stderr == "CLI screenshot cannot be opened\n"


@pytest.mark.parametrize(
    ("size", "mode"),
    [((20, 20), "RGBA"), (EXPECTED_SIZE, "RGB")],
)
def test_screenshot_contract_rejects_wrong_shape_or_mode(
    tmp_path: Path,
    size: tuple[int, int],
    mode: str,
) -> None:
    candidate = tmp_path / "candidate.png"
    Image.new(mode, size).save(candidate)
    result = _verify(candidate)
    assert result.returncode != 0
    assert result.stderr == "CLI screenshot has the wrong image contract\n"


def test_screenshot_contract_rejects_flat_images(tmp_path: Path) -> None:
    candidate = tmp_path / "flat.png"
    Image.new("RGBA", EXPECTED_SIZE, "black").save(candidate)
    result = _verify(candidate)
    assert result.returncode != 0
    assert result.stderr == "CLI screenshot does not contain enough visual detail\n"


def test_screenshot_contract_accepts_more_than_one_hundred_colors(tmp_path: Path) -> None:
    candidate = tmp_path / "detailed.png"
    image = Image.new("RGBA", EXPECTED_SIZE, "black")
    draw = ImageDraw.Draw(image)
    stripe_width = EXPECTED_SIZE[0] // 101
    for index in range(101):
        draw.rectangle(
            (index * stripe_width, 0, (index + 1) * stripe_width, EXPECTED_SIZE[1]),
            fill=(index, 255 - index, (index * 7) % 256, 255),
        )
    image.save(candidate)
    result = _verify(candidate)
    assert result.returncode == 0
