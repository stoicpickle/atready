# Local marketplace lifecycle pilot

This is a local-only, reversible lifecycle probe for the AtReady **skills-only** plugin and a
possible future Directory phase. It is not a Directory install, submission, approval, publication,
or general-availability claim. The public source beta remains the normal CLI path.

## Two separate installs

AtReady has two independently installed artifacts:

1. `project-atready` / `atready` is the local Python runtime and standalone CLI. It stores the
   roster and performs the deterministic checks.
2. `atready` is the skills-only plugin. It supplies the Codex conversation, but contains no Python
   runtime and never installs, updates, or repairs one.

The pilot requires both artifacts. A user installs the local runtime themselves, then installs the
plugin from this repository's local marketplace inside an isolated Codex profile. A later,
separately authorized phase may repeat that journey through the Directory. The plugin verifies
compatibility before it delegates an inventory operation. Product versions may differ; the runtime
contract and required features must match.

Do not combine the plugin-managed install with the personal-skill sideload in `~/.agents/skills`.
They have separate discovery, update, and removal behavior.

## Surface boundary

Current OpenAI documentation says plugins work in Chat and Work across ChatGPT web, desktop, and
mobile; in Codex they work in the ChatGPT desktop app, and Codex CLI provides a plugin browser. The
Codex IDE extension does not support plugins. That platform availability is not an AtReady support
claim.

This candidate's bundled `agents/openai.yaml` metadata declares `policy.products: [CODEX]`; its
`SKILL.md` frontmatter remains limited to `name` and `description`. Runtime and filesystem
prerequisites are stated in the skill body and quickstart. The candidate claims only a **local
Codex task or Codex CLI**
that can run Python, invoke trusted `uv`, and access the user's local inventory. ChatGPT Chat/Work,
mobile, Codex remote/cloud, and every other surface are unproved or ineligible for this pilot. They
must hide AtReady or stop before intake, preview, routing, or mutation. Never ask a user to paste an
inventory, private note, credential, environment variable, or account configuration as a
workaround.

See [PLUGIN_SURFACE_PROBE.md](PLUGIN_SURFACE_PROBE.md) for the test matrix. Recheck the official
availability documentation immediately before a portal action; it can change independently of this
source tree.

For the first-time public/reviewer sequence, expected output, and beginner troubleshooting, read
[PLUGIN_DIRECTORY_QUICKSTART.md](PLUGIN_DIRECTORY_QUICKSTART.md). That guide preserves this hybrid
architecture and does not describe the plugin as self-contained.

## First-user pilot journey

Use a clean, isolated Codex CLI profile with synthetic data only. The repository helper performs
this lifecycle without changing the user's normal Codex configuration:

```bash
uv run python scripts/plugin_lifecycle_acceptance.py
```

1. Confirm the isolated profile has no AtReady plugin, personal-skill sideload, or marketplace
   entry. The separately installed runtime remains outside that temporary profile.
2. Add this repository as a local marketplace and confirm AtReady is discoverable but not installed.
3. Install the skills-only plugin and verify that Codex cached an exact copy of the canonical tree.
4. Run the installed launcher's compatibility handshake against synthetic temporary state.
5. Remove the plugin and marketplace, then prove the synthetic inventory is byte-for-byte unchanged.

Stop the pilot if a surface presents an actionable AtReady starter workflow without local runtime
and file access, if the plugin is mistaken for the CLI, or if removal affects the inventory.

After the lifecycle passes, prepare a disposable ZIP and value-safe receipt from a clean reviewed
commit into a new output directory:

```bash
pilot_parent="$(mktemp -d)"
uv run python scripts/prepare_plugin_directory_pilot.py \
  --output-dir "$pilot_parent/atready-directory-pilot"
```

The helper refuses dirty source by default. `--allow-dirty` is only for development proof and marks
the receipt `development_only: true`; never retain or upload that artifact as a candidate.

Prepare the private operator transcript against that exact clean candidate, then score it against
the same directory after the human review is complete:

```bash
conversation_parent="$(mktemp -d)"
chmod 700 "$conversation_parent"
uv run python scripts/plugin_conversation_acceptance.py \
  --candidate-pilot "$pilot_parent/atready-directory-pilot" \
  --prepare "$conversation_parent/atready-directory-conversations"
# Run and record the eight cases, review their meaning, and attest the transcript.
uv run python scripts/plugin_conversation_acceptance.py \
  --candidate-pilot "$pilot_parent/atready-directory-pilot" \
  --transcript "$conversation_parent/atready-directory-conversations/transcript.json"
```

Both steps independently verify the private preparation receipt and ZIP. The transcript and
value-safe score receipt bind the observations to only the candidate's ZIP digest, plugin version,
and clean source commit; neither output discloses a local path. If the ZIP or receipt changes, start
with a new transcript rather than carrying observations forward.

On POSIX systems, the helper verifies that the candidate directory and transcript are owned by the
current user and have no group or world access. Windows does not expose equivalent ACL proof through
these Python mode checks, so use a current-user-only directory, keep the packet synthetic, and treat
ACL privacy as operator-managed and unproved. Symlink, file-type, size, ZIP-integrity, and candidate
binding checks still apply on every platform.

Portal draft, Directory installation, submission for review, and publication are separate
external-state changes. Each requires later explicit owner authorization; none is authorized by
this pilot document.

Platform details above follow OpenAI's current
[plugin availability documentation](https://developers.openai.com/codex/plugins). Recheck it before
every external pilot phase.
