# First-user acceptance

This contract proves the public CLI journey without reading or modifying a real AtReady
inventory. It uses only synthetic declarations, passes an explicit inventory path to every mutating
command, forces `ATREADY_HOME` to an ephemeral temporary directory, and deletes that directory
when the run ends.

Run it against the CLI executable you intend to evaluate (POSIX shell):

```bash
python3 scripts/first_user_acceptance.py --executable /absolute/path/to/atready
```

For a source checkout after `uv sync --group dev` (POSIX shell):

```bash
uv run python scripts/first_user_acceptance.py \
  --executable "$(uv run --no-sync which atready)"
```

For the same source checkout in PowerShell:

```powershell
$atready = uv run --no-sync python -c "import shutil; print(shutil.which('atready') or '')"
if (-not $atready) { throw "atready executable not found" }
uv run python scripts/first_user_acceptance.py --executable $atready
```

The receipt is value-free JSON. A passing run covers:

1. exact runtime version identity, the inert compatibility contract, and the expected resource
   command surface;
2. catalog version `1` and the exact bundled profile set;
3. exclusive initialization of clean personal state;
4. an exact continuity copy that retains the same private lineage bytes;
5. a separately initialized independent lineage with different nonce-backed bytes;
6. add preview/apply, redacted list output, and a personal-inventory route;
7. refusal of a stale plan without changing active inventory bytes;
8. complete replacement and exact-ID removal;
9. redacted backup listing/inspection and exact-byte rollback; and
10. omission of the synthetic hidden note and both nonce values from normal command output.

A passing private candidate reports its actual `cli_version`, `catalog_version: 1`, and checked
command count. This protects against an installation that exposes an older command
surface even when `--version` alone appears correct.

The harness does not install or uninstall anything, mutate Codex marketplace/plugin configuration,
access the network, prove artifact provenance, or prove discovery in a fresh Codex task. It is one
local prerequisite for the external acceptance run, not a substitute for it.

## External release evidence

After a reviewed runtime is published and the exact plugin bundle is available to the tester,
repeat the journey from an unrelated clean machine or account and retain a synthetic-only evidence
bundle containing:

- operating system, Python, uv, AtReady, and Codex versions;
- the verified runtime version and hashes, plugin version and bundle hash, and available source or
  publication provenance for each independently versioned artifact;
- proof that the CLI, plugin, marketplace entry, and inventory were absent before installation;
- the harness receipt and command transcript;
- evidence showing plugin discovery and explicit activation in a fresh supported Codex task; and
- before/after hashes proving plugin and CLI removal did not remove or change the inventory.

Installation, marketplace changes, plugin removal, and publication are deliberate external-state
changes. Run those steps only with the user's authorization. Use synthetic fixtures throughout; do
not retain a real inventory, private notes, account metadata, or generated private plan.

## Directory acceptance run

After OpenAI approval and owner-authorized publication, use a signed-out/unrelated account and a
clean profile that has never installed AtReady:

1. Record that no AtReady plugin is installed in this account/profile and that no
   `atready` CLI or local marketplace entry is installed.
2. Find the public directory listing, open its website/support/privacy/terms links, and compare the
   live name, descriptions, developer identity, category, prompts, and square logo to the approved
   submission packet.
3. Install the plugin through the supported product UI, start a fresh task, and invoke each starter
   prompt using only synthetic fixtures. Confirm activation is explicit and no handoff executes.
4. Run `scripts/first_user_acceptance.py` from the exact reviewed private-beta snapshot or retained
   submission evidence against the compatible independently installed runtime. Verify its SHA-256
   against the release-candidate receipt before execution and retain its value-free receipt. The
   harness is not shipped in the wheel, sdist, or public skills-only plugin ZIP; a package-only or
   directory installation is not its retrieval source.
5. Remove the plugin and CLI through their supported interfaces. Prove removal did not delete or
   change a separately retained synthetic inventory, then remove that synthetic test state yourself.

Record product surface, account class, country/region, date, independently versioned plugin/runtime
artifacts, hashes, evidence captures, and any review-only setup. A source-checkout run, local
marketplace install, authenticated maintainer session, or portal draft is not unrelated-user
directory proof.
