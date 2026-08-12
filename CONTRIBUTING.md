# Contributing

AtReady is an early public project. Small changes that preserve its explicit trust boundary
are easiest to review.

## Set up

```bash
uv sync --locked --all-groups --no-group release --no-install-project
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
PYTHONPATH=src uv run --no-sync pytest --cov=atready --cov-report=term-missing
UV_INDEX="" UV_NO_CONFIG=1 uv build --clear --no-create-gitignore --no-sources \
  --build-constraints build-constraints.txt --require-hashes \
  --default-index https://pypi.org/simple
UV_INDEX="" UV_NO_CONFIG=1 uv sync --locked --all-groups --no-install-project
uv run --no-sync twine check --strict dist/*
uv run --no-sync python scripts/verify_readme_rendering.py
uv run --no-sync python scripts/verify_release_artifacts.py --dist dist
uv run --isolated --no-project \
  --with ./dist/project_atready-0.1.7-py3-none-any.whl \
  python scripts/smoke_wheel.py
uv run --isolated --no-project \
  --with ./dist/project_atready-0.1.7-py3-none-any.whl \
  python scripts/smoke_plugin.py
uv run --no-sync python scripts/hardening_gate.py \
  --wheel ./dist/project_atready-0.1.7-py3-none-any.whl
```

The clean first-use lane performs real, non-editable source and wheel installs into separate
disposable `uv` tool roots. The install phase uses normal `uv` dependency resolution and may contact
the configured package index; running the repository command is the developer or CI authorization
for that bounded install. The wheel lane rejects symlinks and binds the child install to the exact
artifact SHA-256. After each install it blocks common Python socket paths in each AtReady process,
redirects AtReady,
legacy AtReady, Codex, and home-directory state into the disposable root, then proves version,
doctor, demo, init, exact preview/apply resource addition, project validation, and routing with
synthetic data. It neither installs a Codex plugin nor reads the developer's actual roster.

Run the Codex plugin and skill validators after changing the plugin:

```bash
export CODEX_SYSTEM_SKILLS_DIR=/absolute/path/to/.codex/skills/.system
python3 scripts/validate_plugin_contract.py plugins/atready \
  --system-skills-dir "$CODEX_SYSTEM_SKILLS_DIR"
python3 "$CODEX_SYSTEM_SKILLS_DIR/skill-creator/scripts/quick_validate.py" \
  plugins/atready/skills/project-atready
```

Set `CODEX_SYSTEM_SKILLS_DIR` to the system-skill directory in the Codex installation being used
for validation. The repository wrapper delegates to OpenAI's installed plugin validator and adds
the current documented `policy.products` rule when an older local validator has not learned that
field yet. It executes only validator bytes matching the repository's reviewed SHA-256 and does not
suppress any other error. A validator update therefore requires a reviewed digest change. CI also
checks the plugin and skill's portable structural contracts.

## Change rules

- Use synthetic inventories and projects. Never submit real account, cost, quota, path, credential,
  or private project data.
- Keep the pure router deterministic: no filesystem, clock, random, model, provider, or network calls.
- Render generated commands as inert text and never pass inventory/project fields to a shell.
- Preserve strict schema validation and complete resource dispositions.
- Preserve preview-first, canonical-target/identity plan binding, exact-revision, private-backup
  durability, and atomic-replacement semantics for personal inventory updates; demo inventories
  remain read-only and require route opt-in.
- Add exact tests for hard gates, score changes, tie-breaks, and plan hashes.
- Update `PRIVACY.md`, `SECURITY.md`, `docs/PERMISSIONS.md`, and `docs/THREAT_MODEL.md` before any
  discovery, connector, telemetry, hosted storage, or execution expansion.
- Pin GitHub Actions by full commit SHA and keep workflow permissions minimal.

## Pull requests

Explain the user-facing outcome, trust-boundary effect, test evidence, and any remaining gap. Keep
unrelated cleanup out of the change. Security issues belong in the private reporting path described
in `SECURITY.md`, not in a public pull request.
