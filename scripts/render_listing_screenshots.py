"""Render AtReady's synthetic public-listing screenshots.

The compositions intentionally illustrate CLI/skill output. They are not a GUI
claim and contain no real inventory, project, account, or execution data.

Run from the repository root with:
    uv run --with "pillow==12.3.0" python scripts/render_listing_screenshots.py
Verify the committed assets without replacing them with:
    uv run --with "pillow==12.3.0" python scripts/render_listing_screenshots.py --check
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import sys
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont
from PIL import __version__ as pillow_version

WIDTH = 1440
HEIGHT = 900

PAPER = (244, 240, 229, 255)
PAPER_LIGHT = (251, 248, 239, 255)
INK = (11, 23, 42, 255)
COBALT = (24, 76, 174, 255)
TRANSIT_BLUE = (0, 142, 188, 255)
SIGNAL_RED = (224, 65, 55, 255)
MUTED = (89, 92, 91, 255)
RULE = (171, 169, 160, 255)
PALE_BLUE = (228, 235, 242, 255)
PALE_RED = (246, 226, 218, 255)
WHITE = (255, 253, 246, 255)

PINNED_PILLOW_VERSION = "12.3.0"
CANONICAL_BYTE_PLATFORM = "darwin"
FONT_KINDS = frozenset({"display", "sans", "sans_bold", "mono", "mono_bold"})
SCREENSHOT_FILENAMES = ("route-overview.png", "safe-preview.png")
LOGO_FILENAMES = ("logo.png", "logo-dark.png")
OUTPUT_FILENAMES = (*SCREENSHOT_FILENAMES, *LOGO_FILENAMES)
REPOSITORY_ASSET_DIR = Path(__file__).resolve().parents[1] / "plugins" / "atready" / "assets"
CANONICAL_LOGO_SHA256 = {
    "logo.png": "4f1098b133c15a04e0c96cab15bd0139337645ec865b79e0adfc2f8b21406799",
    "logo-dark.png": "215a633e7e95ded73fbb590691db7037066105bdaf1898c6c9dc3876a2ae5bed",
}


@cache
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    if kind not in FONT_KINDS:
        raise ValueError(f"unsupported font kind: {kind}")
    # Pillow embeds Aileron Regular as immutable font bytes. Pinning Pillow and
    # using only that embedded face keeps glyph metrics identical on every OS.
    return ImageFont.load_default(size=size)


def text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    *,
    kind: str = "sans",
    size: int = 20,
    fill: tuple[int, int, int, int] = INK,
    anchor: str | None = None,
    spacing: int = 4,
) -> None:
    draw.multiline_text(
        xy,
        value,
        font=font(kind, size),
        fill=fill,
        anchor=anchor,
        spacing=spacing,
        stroke_width=1 if kind in {"display", "sans_bold"} else 0,
        stroke_fill=fill,
    )


def label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    *,
    fill: tuple[int, int, int, int] = MUTED,
    size: int = 14,
    anchor: str | None = None,
) -> None:
    text(draw, xy, value.upper(), kind="mono_bold", size=size, fill=fill, anchor=anchor)


def rule(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int, int] = INK,
    width: int = 2,
) -> None:
    draw.line(xy, fill=fill, width=width)


def paper_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    # Sparse deterministic flecks suggest stock without making the image "grungy."
    for index in range(540):
        x = (index * 379 + 41) % WIDTH
        y = (index * 197 + 73) % HEIGHT
        tone = (223 + index % 7, 219 + index % 5, 207 + index % 6, 255)
        draw.point((x, y), fill=tone)
    return image, draw


def draw_route_row(
    draw: ImageDraw.ImageDraw,
    *,
    y: int,
    index: str,
    stage: str,
    task: str,
    primary: str,
    field_two_label: str,
    field_two: str,
    field_three_label: str,
    field_three: str,
    note: str,
    shaded: bool = False,
) -> None:
    x0, x1 = 54, 1386
    height = 124
    if shaded:
        draw.rectangle((x0, y, x1, y + height), fill=PALE_BLUE)
    rule(draw, (x0, y, x1, y), width=3)
    rule(draw, (x0, y + height, x1, y + height), width=1)
    for x in (142, 404, 728, 1036):
        rule(draw, (x, y, x, y + height), width=1)

    text(draw, (74, y + 24), index, kind="display", size=48, fill=COBALT)
    label(draw, (166, y + 20), stage, fill=COBALT)
    text(draw, (166, y + 48), task, kind="sans_bold", size=23)

    label(draw, (430, y + 20), "PRIMARY")
    text(draw, (430, y + 48), primary, kind="sans_bold", size=18)
    label(draw, (430, y + 88), note, fill=MUTED, size=12)

    label(draw, (754, y + 20), field_two_label)
    text(draw, (754, y + 48), field_two, kind="sans_bold", size=21)

    label(draw, (1062, y + 20), field_three_label)
    text(draw, (1062, y + 48), field_three, kind="sans_bold", size=20)


def route_overview() -> Image.Image:
    image, draw = paper_canvas()

    draw.rectangle((54, 28, 1386, 90), fill=COBALT)
    label(draw, (78, 50), "ATREADY / ROUTE DOCUMENT 01", fill=WHITE, size=16)
    label(
        draw,
        (1360, 50),
        "SYNTHETIC EXAMPLE / ILLUSTRATED OUTPUT",
        fill=WHITE,
        size=13,
        anchor="ra",
    )
    # A small geometric index, not an airline or aircraft mark.
    draw.ellipse((912, 39, 949, 76), fill=TRANSIT_BLUE)
    draw.ellipse((954, 39, 991, 76), fill=SIGNAL_RED)
    draw.ellipse((996, 39, 1033, 76), fill=WHITE)

    label(draw, (58, 111), "PROJECT")
    text(draw, (54, 125), "SYNTHETIC FEATURE PLAN", kind="display", size=69)
    text(draw, (1386, 138), "ROUTE MANIFEST", kind="display", size=42, anchor="ra", fill=COBALT)
    label(
        draw,
        (1386, 187),
        "ORDERED SELECTION / NO EXECUTION",
        fill=INK,
        size=14,
        anchor="ra",
    )

    meta_y = 211
    draw.rectangle((54, meta_y, 1386, meta_y + 90), fill=PAPER_LIGHT, outline=INK, width=2)
    for x in (354, 632, 910, 1164):
        rule(draw, (x, meta_y, x, meta_y + 90), width=1)
    meta = (
        (78, "STATUS", "ROUTED"),
        (378, "WORKSTREAMS", "03"),
        (656, "INVENTORY", "09 DECLARED"),
        (934, "RESOURCES USED", "02"),
        (1188, "EXECUTION", "NOT AUTHORIZED"),
    )
    for x, key, value in meta:
        label(draw, (x, meta_y + 17), key, fill=COBALT)
        text(draw, (x, meta_y + 43), value, kind="sans_bold", size=21)

    draw_route_row(
        draw,
        y=318,
        index="01",
        stage="ARCHITECTURE",
        task="DEFINE BOUNDARIES",
        primary="DECLARED CODING AGENT",
        field_two_label="DECLARED-INPUT SCORE",
        field_two="8840 BP",
        field_three_label="HANDOFF",
        field_three="INERT",
        note="ELIGIBLE / SELECTED PRIMARY",
    )
    draw_route_row(
        draw,
        y=442,
        index="02",
        stage="IMPLEMENTATION",
        task="BUILD FEATURE",
        primary="DECLARED CODING AGENT",
        field_two_label="DECLARED-INPUT SCORE",
        field_two="9240 BP",
        field_three_label="ADJUSTMENT",
        field_three="+400 CONTINUITY",
        note="ELIGIBLE / SELECTED PRIMARY",
        shaded=True,
    )
    draw_route_row(
        draw,
        y=566,
        index="03",
        stage="INDEPENDENT REVIEW",
        task="REVIEW WORK",
        primary="DECLARED REVIEW AGENT",
        field_two_label="DECLARED-INPUT SCORE",
        field_two="8292 BP",
        field_three_label="NEXT OWNER",
        field_three="HUMAN MAINTAINER",
        note="ELIGIBLE / SELECTED PRIMARY",
    )

    label(draw, (54, 710), "SUMMARY", fill=COBALT)
    text(
        draw,
        (160, 706),
        "WORKSTREAMS 03  /  RESOURCES USED 02  /  DELIBERATELY UNUSED 07  /  GAPS 00",
        kind="mono_bold",
        size=15,
    )

    draw.rectangle((54, 744, 1386, 828), fill=INK)
    label(draw, (78, 774), "NEXT", fill=TRANSIT_BLUE)
    text(draw, (180, 764), "REVIEW HANDOFF PACKETS", kind="display", size=35, fill=WHITE)
    label(draw, (1360, 777), "PLANNING OUTPUT ONLY", fill=WHITE, size=13, anchor="ra")
    label(
        draw,
        (54, 850),
        "WORKSTREAMS ROUTED IN DECLARED ORDER / SEPARATE AUTHORIZATION REQUIRED BEFORE EXECUTION",
        fill=INK,
        size=12,
    )
    return image


def preview_column(
    draw: ImageDraw.ImageDraw,
    *,
    box: tuple[int, int, int, int],
    index: str,
    heading: str,
    capability: str,
    score: str,
    notes: str,
    fill: tuple[int, int, int, int],
    accent: tuple[int, int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    draw.rectangle(box, fill=fill, outline=INK, width=2)
    draw.rectangle((x0, y0, x0 + 84, y1), fill=accent)
    text(draw, (x0 + 42, y0 + 31), index, kind="display", size=48, fill=WHITE, anchor="ma")
    label(draw, (x0 + 110, y0 + 25), heading, fill=accent)
    text(draw, (x0 + 110, y0 + 48), "LOCAL CODING AGENT", kind="sans_bold", size=27)
    rule(draw, (x0 + 110, y0 + 91, x1 - 24, y0 + 91), fill=RULE, width=1)
    fields = (
        ("CAPABILITY", capability),
        ("IMPLEMENTATION FIT", score),
        ("ACCESS", "UNKNOWN"),
        ("PRIVATE NOTES", notes),
        ("DECLARED APPROVAL", "REQUIRED"),
    )
    for offset, (key, value) in enumerate(fields):
        y = y0 + 113 + offset * 30
        label(draw, (x0 + 110, y), key, size=12)
        text(draw, (x1 - 26, y - 2), value, kind="mono_bold", size=14, anchor="ra")


def safe_preview() -> Image.Image:
    image, draw = paper_canvas()

    draw.rectangle((54, 28, 1386, 90), fill=SIGNAL_RED)
    label(draw, (78, 50), "ATREADY / CHANGE CONTROL 02", fill=WHITE, size=16)
    label(
        draw,
        (1360, 50),
        "SYNTHETIC EXAMPLE / ILLUSTRATED OUTPUT",
        fill=WHITE,
        size=13,
        anchor="ra",
    )

    label(draw, (58, 111), "OPERATION")
    text(draw, (54, 125), "RESOURCE REPLACEMENT", kind="display", size=69)
    label(draw, (1386, 111), "PERSONAL INVENTORY", fill=INK, anchor="ra")
    text(draw, (1386, 137), "PREVIEW ONLY", kind="display", size=48, anchor="ra", fill=SIGNAL_RED)

    draw.rectangle((54, 211, 1386, 299), fill=INK)
    label(draw, (80, 228), "WRITE STATUS", fill=WHITE)
    text(draw, (78, 249), "NOT APPLIED", kind="display", size=40, fill=WHITE)
    rule(draw, (468, 211, 468, 299), fill=PAPER, width=1)
    label(draw, (494, 228), "PLAN BINDING", fill=WHITE)
    text(draw, (492, 255), "EXACT REVISION + PLAN TOKEN", kind="mono_bold", size=18, fill=WHITE)
    rule(draw, (978, 211, 978, 299), fill=PAPER, width=1)
    label(draw, (1004, 228), "APPLIED", fill=WHITE)
    text(draw, (1002, 249), "FALSE", kind="display", size=40, fill=SIGNAL_RED)

    preview_column(
        draw,
        box=(54, 326, 680, 580),
        index="01",
        heading="BEFORE",
        capability="CODE-IMPLEMENTATION",
        score="0.72",
        notes="VALUE NOT SHOWN",
        fill=PAPER_LIGHT,
        accent=COBALT,
    )
    preview_column(
        draw,
        box=(760, 326, 1386, 580),
        index="02",
        heading="AFTER",
        capability="CODE-IMPLEMENTATION",
        score="0.88",
        notes="VALUE NOT SHOWN",
        fill=PALE_RED,
        accent=SIGNAL_RED,
    )

    rule(draw, (696, 437, 740, 437), fill=INK, width=2)
    draw.polygon(((740, 431), (750, 437), (740, 443)), fill=INK)
    label(draw, (722, 469), "DECLARED\nCHANGE", fill=INK, size=10, anchor="ma")

    label(draw, (54, 606), "CHANGE METADATA")
    draw.rectangle((54, 632, 1386, 734), fill=PAPER_LIGHT, outline=INK, width=2)
    for x in (382, 732, 1074):
        rule(draw, (x, 632, x, 734), width=1)
    protection = (
        (78, "RESOURCE COUNT", "01 TO 01"),
        (408, "BACKUP ON APPLY", "YES"),
        (758, "DECLARED EFFECT", "NOTES UNCHANGED"),
        (1100, "YAML", "CANONICALIZED"),
    )
    for x, key, value in protection:
        label(draw, (x, 654), key, fill=SIGNAL_RED)
        text(draw, (x, 684), value, kind="mono_bold", size=15)

    draw.rectangle((54, 758, 1386, 832), fill=SIGNAL_RED)
    label(draw, (78, 784), "NEXT", fill=WHITE)
    text(draw, (172, 776), "REVIEW THE COMPLETE PREVIEW", kind="display", size=31, fill=WHITE)
    label(
        draw,
        (1360, 787),
        "APPLY REQUIRES SAME DECLARATION + APPROVAL + REVISION + PLAN TOKEN",
        fill=WHITE,
        size=12,
        anchor="ra",
    )
    label(
        draw,
        (54, 850),
        "SYNTHETIC DATA / NO CREDENTIALS / PREVIEW DOES NOT WRITE",
        fill=INK,
        size=12,
    )
    return image


def save_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", compress_level=9, optimize=False)


def brand_logo(icon_path: Path, *, dark: bool) -> Image.Image:
    background = (4, 17, 34, 255) if dark else (244, 247, 252, 255)
    title_color = (244, 247, 252, 255) if dark else INK
    subtitle_color = (163, 190, 219, 255) if dark else (66, 95, 128, 255)
    image = Image.new("RGBA", (1200, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 1199, 299), radius=42, fill=background)
    with Image.open(icon_path) as source:
        icon = source.convert("RGBA").resize((225, 225), Image.Resampling.LANCZOS)
    image.alpha_composite(icon, (54, 38))
    text(draw, (330, 60), "AtReady", kind="sans", size=78, fill=title_color)
    text(
        draw,
        (334, 170),
        "Plan with what you have at the ready",
        kind="sans",
        size=30,
        fill=subtitle_color,
    )
    return image


def render_assets(output_dir: Path, *, icon_path: Path | None = None) -> None:
    source_icon = icon_path or REPOSITORY_ASSET_DIR / "icon.png"
    if not source_icon.is_file():
        raise SystemExit(f"icon asset does not exist: {source_icon}")
    save_png(route_overview(), output_dir / SCREENSHOT_FILENAMES[0])
    save_png(safe_preview(), output_dir / SCREENSHOT_FILENAMES[1])
    save_png(brand_logo(source_icon, dark=False), output_dir / LOGO_FILENAMES[0])
    save_png(brand_logo(source_icon, dark=True), output_dir / LOGO_FILENAMES[1])


def verify_assets(expected_dir: Path) -> None:
    with TemporaryDirectory(prefix="atready-listing-") as temporary:
        rendered_dir = Path(temporary)
        render_assets(rendered_dir, icon_path=expected_dir / "icon.png")
        mismatches: list[str] = []
        for name in OUTPUT_FILENAMES:
            rendered_path = rendered_dir / name
            expected_path = expected_dir / name
            with Image.open(rendered_path) as rendered, Image.open(expected_path) as expected:
                if rendered.size != expected.size or rendered.mode != expected.mode:
                    mismatches.append(name)
                    continue
            # Pillow embeds identical Aileron bytes on every platform, but the
            # FreeType rasterizers bundled in its OS wheels may antialias those
            # glyphs differently. The macOS render is the canonical byte
            # artifact; other CI platforms prove the pinned renderer completes
            # with the same image geometry and mode.
            if sys.platform == CANONICAL_BYTE_PLATFORM and not filecmp.cmp(
                rendered_path,
                expected_path,
                shallow=False,
            ):
                mismatches.append(name)
        for name, expected_digest in CANONICAL_LOGO_SHA256.items():
            digest = hashlib.sha256((expected_dir / name).read_bytes()).hexdigest()
            if digest != expected_digest and name not in mismatches:
                mismatches.append(name)
    if mismatches:
        joined = ", ".join(mismatches)
        raise SystemExit(f"committed listing assets differ from deterministic render: {joined}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("plugins/atready/assets"),
        help="directory that receives the reviewed screenshots and horizontal logos",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="render into a temporary directory and compare with --output-dir",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if pillow_version != PINNED_PILLOW_VERSION:
        raise SystemExit(f"Pillow {PINNED_PILLOW_VERSION} is required; found {pillow_version}")
    if args.check:
        verify_assets(args.output_dir)
    else:
        render_assets(args.output_dir)


if __name__ == "__main__":
    main()
