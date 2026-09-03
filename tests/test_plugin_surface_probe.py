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
    matrix = _section(receipt, "Availability and evidence matrix")
    rows = [
        cells
        for line in matrix.splitlines()
        if line.startswith("|")
        and not line.startswith("| ---")
        and (cells := [cell.strip() for cell in line.strip("|").split("|")])[0] != "Surface"
    ]

    expected_rows = (
        (
            "Local repository marketplace",
            "Automated local evidence",
            "Isolated profile proves discover, install, exact cached copy, runtime handshake, "
            "removal, and unchanged synthetic state.",
        ),
        (
            "OpenAI plugin portal",
            "Unproved; not authorized",
            "A future draft retains the exact candidate policy without submission.",
        ),
        (
            "Codex local desktop/task",
            "Claimed target; unproved",
            "Fresh task proves explicit activation, compatibility before inventory access, and "
            "synthetic routing.",
        ),
        (
            "Codex CLI",
            "Claimed target; lifecycle automated, conversation unproved",
            "Automated lifecycle proves packaging and compatibility; a fresh session still must "
            "prove explicit activation and synthetic routing.",
        ),
        (
            "ChatGPT Chat/Work on web, desktop, or mobile",
            "Platform supports plugins generally; CODEX-only AtReady is not a target",
            "Hide AtReady or stop clearly before intake, preview, routing, or mutation.",
        ),
        (
            "Codex remote or cloud",
            "Unproved; not an AtReady target",
            "Hide AtReady or stop clearly before local runtime or inventory work.",
        ),
        (
            "Codex IDE extension",
            "Platform unavailable",
            "Do not claim plugin availability; record any contrary appearance as a platform "
            "finding, not support.",
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
