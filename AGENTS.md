# AtReady Agent Guide

AtReady is a public, local-first capability router. The v0.1 boundary is a non-executing
Codex skill plus an offline inventory CLI.

## Work here

- Use `uv sync --all-groups` for the development environment.
- Run `uv run ruff check .`, `uv run ruff format --check .`, and
  `uv run pytest --cov=atready --cov-report=term-missing` before handoff.
- Run the plugin and skill validators after editing `plugins/atready/`:
  `python3 "$CODEX_SYSTEM_SKILLS_DIR/plugin-creator/scripts/validate_plugin.py" plugins/atready`
  and `python3 "$CODEX_SYSTEM_SKILLS_DIR/skill-creator/scripts/quick_validate.py"
  plugins/atready/skills/project-atready`.
  Set `CODEX_SYSTEM_SKILLS_DIR` to the active Codex installation's system-skill directory first.
- After packaging changes, build and run `scripts/smoke_wheel.py` through an isolated environment
  with the built wheel installed; install the locked release group, then run
  `uv run --no-sync twine check --strict dist/*`,
  `uv run --no-sync python scripts/verify_readme_rendering.py`, and the exact artifact verifier
  first. A successful `uv build` alone is not package proof.
- Build release candidates through `build-constraints.txt` with `--require-hashes`, then run
  `scripts/verify_release_artifacts.py` and `scripts/release_bundle.py verify`. The candidate receipt
  is unsigned metadata, never an attestation or publication claim. Follow `docs/RELEASING.md`.
- Use synthetic fixtures only. Keep real inventories, histories, account metadata, and generated
  private plans out of this repository.

## Preserve the trust boundary

- Keep the default path free of network calls, telemetry, provider discovery, connectors, and
  automatic execution.
- Parse configuration as bounded data. Reject ambiguous or secret-bearing inputs.
- Keep handoff commands and prompts inert until a user separately authorizes execution.
- Keep personal-inventory writes preview-first, plan-token and exact-revision bound, privately
  backed up, and atomically replaced. Demo inventories stay read-only and require explicit routing
  opt-in.
- Distinguish stored locally from model processing: sanitized snapshots can enter the user's
  configured host/model context.
- Treat recommendation, authorization, credential access, and execution as separate states.

Changes that expand permissions, discover local capabilities, access billing, invoke resources, or
write outcome history require a threat-model and permissions update in the same change.
