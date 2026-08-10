# Front-page sync

Run this checkpoint after the implementation and tests are stable, before requesting review or
creating a commit. The goal is to keep the repository's front page aligned with the product people
will actually encounter.

## Review

Open the rendered `README.md` as a first-time visitor and check every item:

- The name, tagline, opening explanation, and current availability still describe the product.
- The primary screenshot shows the current real CLI and remains readable at normal GitHub width.
- Installation and first-use commands work in the order shown.
- New or changed user-facing commands, capabilities, defaults, and limitations are reflected where
  a newcomer would expect to find them.
- Safety, privacy, execution, and support claims remain narrow and true.
- Versions, repository links, file paths, and examples are current.

When the CLI welcome changes, capture the real terminal rather than recreating it. Replace
`docs/assets/atready-cli.png`, run `uv run python scripts/verify_cli_screenshot.py`, and visually
inspect the resulting image.

Run `uv run python scripts/verify_readme_rendering.py` after any README edit.

## Completion receipt

Finish with exactly one of these statements in the review handoff or pull request:

- `Front page: updated`
- `Front page: reviewed; no change needed`

The second receipt is a deliberate decision, not a shortcut: it means every checklist item above
was inspected and the current front page remains accurate.
