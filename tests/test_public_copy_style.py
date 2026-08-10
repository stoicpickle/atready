from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DASHES = (chr(0x2013), chr(0x2014))
PUBLIC_COPY_FILES = (
    ROOT / "README.md",
    ROOT / "PRIVACY.md",
    ROOT / "SECURITY.md",
)
PUBLIC_COPY_TREES = {
    ROOT / ".github" / "ISSUE_TEMPLATE": {".yml", ".yaml"},
    ROOT / "docs": {".md"},
    ROOT / "plugins" / "atready": {".json", ".md", ".yaml", ".yml"},
    ROOT / "scripts": {".py"},
    ROOT / "src" / "atready": {".py"},
    ROOT / "trust-site" / "app": {".ts", ".tsx"},
}


def _authored_copy_files() -> list[Path]:
    files = list(PUBLIC_COPY_FILES)
    for tree, suffixes in PUBLIC_COPY_TREES.items():
        files.extend(path for path in tree.rglob("*") if path.is_file() and path.suffix in suffixes)
    return sorted(files)


def test_authored_public_copy_avoids_em_and_en_dashes() -> None:
    offenders = []
    for path in _authored_copy_files():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(dash in line for dash in FORBIDDEN_DASHES):
                offenders.append(f"{path.relative_to(ROOT)}:{line_number}")

    assert offenders == [], (
        "Use a period, comma, colon, or a clearer sentence instead of em/en dashes: "
        + ", ".join(offenders)
    )
