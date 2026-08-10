import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "docs" / "PLUGIN_SURFACE_PROBE.md"


def _section(receipt: str, heading: str) -> str:
    marker = f"## {heading}"
    start = receipt.index(marker) + len(marker)
    match = re.search(r"^## ", receipt[start:], re.MULTILINE)
    end = len(receipt) if match is None else start + match.start()
    return receipt[start:end]


def test_surface_probe_keeps_publication_fail_closed() -> None:
    receipt = PROBE.read_text(encoding="utf-8")
    policy = _section(receipt, "Candidate policy")
    decision = _section(receipt, "Stop/go rule")
    normalized_decision = " ".join(decision.split())
    policy_blocks = re.findall(r"```yaml\n(.*?)\n```", policy, re.DOTALL)

    assert "STOP PUBLIC SUBMISSION / CONTINUE LOCAL PROBE DEVELOPMENT" in decision
    assert policy_blocks == ["policy:\n  products: [CODEX]\n  allow_implicit_invocation: false"]
    assert "Submission for review requires separate owner authorization." in normalized_decision
    assert (
        "Later publication requires a second separate owner authorization." in normalized_decision
    )


def test_surface_probe_covers_every_claimed_probe_surface() -> None:
    receipt = PROBE.read_text(encoding="utf-8")
    matrix = _section(receipt, "Evidence matrix")
    rows = [
        cells
        for line in matrix.splitlines()
        if line.startswith("|")
        and not line.startswith("| ---")
        and (cells := [cell.strip() for cell in line.strip("|").split("|")])[0] != "Surface"
    ]

    expected_rows = (
        (
            "OpenAI plugin portal",
            "Unproved; must be hidden",
            "Draft accepts and retains the exact candidate policy without submission",
        ),
        (
            "ChatGPT web/chat",
            "Unproved; must be hidden",
            "Fresh synthetic conversation proves visibility and a safe pre-invocation boundary",
        ),
        (
            "ChatGPT desktop chat",
            "Unproved; must be hidden",
            "Fresh synthetic conversation proves visibility and a safe pre-invocation boundary",
        ),
        (
            "Codex desktop local/worktree",
            "Unproved; must be hidden",
            "Fresh task proves explicit activation, runtime compatibility, and synthetic routing",
        ),
        (
            "Codex CLI",
            "Unproved; must be hidden",
            "Fresh task proves packaged-path resolution and the bounded runtime handshake",
        ),
        (
            "Codex IDE",
            "Unproved; must be hidden",
            "Supported host proves explicit activation and local-filesystem compatibility",
        ),
        (
            "Codex cloud/Remote",
            "Unproved; must be hidden",
            "Surface hides AtReady or stops before local inventory/filesystem work",
        ),
    )
    assert all(len(row) == 3 for row in rows)
    assert tuple(tuple(row) for row in rows) == expected_rows

    decision = " ".join(_section(receipt, "Stop/go rule").split()).casefold()
    for limitation in (
        "clean-machine installation",
        "other operating systems",
        "portal acceptance",
        "publisher approval",
    ):
        assert limitation in decision
