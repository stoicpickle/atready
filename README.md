# AtReady

**Plan with what you have at the ready.**

AtReady is a small, local-first planning tool. Tell it about the coding agents, creative tools,
subscriptions, services, or people available to you. Give it a rough project plan. It recommends
where those resources fit and explains why.

It does not run the work, contact your tools, or spend your credits. You stay in control.

![AtReady welcome screen](https://raw.githubusercontent.com/stoicpickle/atready/main/docs/assets/atready-cli.png)

> **Public beta:** AtReady works today, but its setup and language will keep improving as people try
> it. Expect changes. Please share what feels confusing or unnecessary.

> **[Try AtReady and tell me how it went](https://github.com/stoicpickle/atready/blob/main/docs/TRY_ATREADY.md)**
> One short install, demo, resource, and planning journey for first-time users.

## The idea in one minute

Maybe you have Codex, CodeRabbit, Cursor, a design subscription, and a small amount of image credit.
A project comes along. Instead of forgetting what is available or trying to use everything, AtReady
helps answer:

- Which resources are actually useful for this plan?
- What should each one handle?
- Which resources should stay out of the way?
- What is missing, uncertain, or blocked?

AtReady turns those answers into an advisory route and inert handoff notes. Nothing is dispatched.

## Install and try AtReady

You need Python 3.11 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Install AtReady directly from its
public GitHub repository:

```bash
uv tool install git+https://github.com/stoicpickle/atready.git
```

If your terminal says `atready` was not found, run `uv tool update-shell`, close and reopen the
terminal, then try again.

Run the demo:

```bash
atready demo
```

The demo uses bundled fake data. It does not read or change your personal resource list, create
files, use the network, or contact or run any resource.

The result looks like this:

```text
Resource plan: Synthetic CLI Release
Goal: Ship a tested local CLI without network access or telemetry.
1 step · 1 assigned · no open gaps

Watch
- This uses a demo inventory. Its contents are not verified as resources you can
  use.

1. Core implementation
   Use: Synthetic Local Coding Agent
   Why: Best eligible match after applying the project constraints.
   Deliver: A locally runnable CLI with deterministic tests.
   Check: uv run pytest (+1 more in the detailed view)

Other resources
- Not needed for this plan: Synthetic Asset Studio
- Blocked by a project rule: Synthetic Interactive Debugger

AtReady made this plan only.

Ready to try your own roster?
1. atready init
2. atready add
3. atready plan
No routed project resources were contacted or run.
```

## Your next three steps

AtReady keeps your declared resources in a local inventory file. A resource can be an AI coding
agent, a reviewer, a creative app, a service, a subscription, a person, or anything else that may
help with a project.

### 1. Create your resource list

```bash
atready init
```

This creates an empty local list. If you already have one, AtReady leaves it in place.

### 2. Add one resource

```bash
atready add
```

AtReady offers editable starter profiles and asks for routing and safety declarations. `Not sure`
is valid for readiness; whether the resource requires internet needs a yes/no answer. It does not
scan your computer, inspect accounts, contact providers, or run the resource. Quick Add shows a
friendly recap, asks before generating the complete no-write preview, then requires a separate
exact `save <resource-id>` confirmation before writing. Cancelling before that confirmation changes
nothing.

### 3. Plan a small project

```bash
atready plan
```

Describe a goal and one to three steps. AtReady asks only for the details that can change which
resources fit, shows what it understood, and returns a plan you can accept, change, or ignore. It
does not write a project file, contact a resource, spend a credit, or run work.

## Reusable and scripted workflows

For scripts or detailed setup, the existing preview/apply command remains available:

```bash
today="$(date +%F)"
atready inventory add \
  --id my-coding-agent \
  --name "My Coding Agent" \
  --category coding-agent \
  --capability code-implementation=0.80 \
  --capability test-automation=0.70 \
  --access active \
  --interaction local-cli \
  --session available \
  --billing owned \
  --marginal-cost 0.10 \
  --quota ample \
  --allowed-data-class internal \
  --confidence-basis user-judgment \
  --verified-on "$today"
```

Those readiness, cost, data, and date fields are declarations about your setup. AtReady does not
silently verify them. The advanced preview shows the complete proposed change, an expected revision,
and a plan token. Nothing is saved until you repeat the command with `--apply`, the exact revision,
and the exact plan token. Guided and advanced setup both create a private exact-byte backup and
atomically replace the inventory; both report durability uncertainty instead of pretending a write
was fully proven.

If the typed command feels too long, AtReady also accepts one protected YAML or JSON declaration
through `--resource-file` or `--resource-stdin`. The
[resource intake guide](https://github.com/stoicpickle/atready/blob/main/plugins/atready/skills/project-atready/references/resource-onboarding.md)
explains the same fields in friendlier language.

For a reusable or scripted plan, create a starter project file:

```bash
atready project template > my-project.yaml
```

Edit the title, workstreams, requirements, and constraints, then route it:

```bash
atready route --project my-project.yaml
```

AtReady checks hard constraints first, scores eligible resources with a deterministic rubric, and
selects a primary resource for each ordered workstream. It may also suggest one support resource or
reserve one standalone alternate when the project calls for it. The default output is a concise
human summary of each assignment, result, check, and material gap.

Use the detailed Markdown view when you want scores, exclusions, every resource disposition, and
the complete inert handoff notes:

```bash
atready route --project my-project.yaml --format markdown
```

Use `--format json` for the unchanged complete machine-readable evidence record.
The summary defaults to 80 columns; add `--width 40` through `--width 120` when you want a
different wrap width.

The same project and inventory produce the same route. AtReady does not claim the route is globally
optimal; it is a consistent, inspectable recommendation you can accept, edit, or ignore.

## What AtReady does not do

- It does not execute project work or send handoffs.
- It does not log in to providers or store credentials.
- It does not automatically inspect accounts, subscriptions, or billing.
- It does not silently change your inventory.
- It does not treat a catalog suggestion as a verified fact about your setup.

Your personal inventory is stored locally. Private notes are excluded from normal listings and
routing snapshots, but sanitized routing data can still enter whichever host or model you choose to
use. “Local-first” does not mean model processing is automatically local.

## Optional Codex skill

The CLI is the product. This repository also includes an optional Codex skill that can add one
declared resource through a conversational no-write preview and separate save approval, or turn a
rough project idea into the same CLI-grounded resource plan. The skill does not replace the CLI's
validation, mutation, or routing engine. It uses the bundled launcher only when Codex has approved
local execution and file access; otherwise it directs the same task to `atready add` in a terminal.

Codex discovers personal skills under `~/.agents/skills`. After installing AtReady, keep any
existing destination unchanged by default. On macOS or Linux, this guarded setup copies the
bundled skill only when that destination is absent:

```bash
atready_skill_dest="$HOME/.agents/skills/project-atready"
if [ -e "$atready_skill_dest" ] || [ -L "$atready_skill_dest" ]; then
  printf 'Keeping existing skill: %s\n' "$atready_skill_dest"
else
  mkdir -p "$HOME/.agents/skills"
  cp -R "$(atready skill path)" "$atready_skill_dest"
fi
atready skill status
```

On Windows PowerShell, use the same keep-existing rule, including for an existing Windows link or
reparse point:

```powershell
$skillDest = Join-Path $HOME ".agents\skills\project-atready"
$skillParent = Split-Path -Parent $skillDest
$existingSkill = Get-Item -LiteralPath $skillDest -Force -ErrorAction SilentlyContinue
if ($null -ne $existingSkill) {
  Write-Host "Keeping existing skill: $skillDest"
} else {
  New-Item -ItemType Directory -Force -Path $skillParent | Out-Null
  $skillSource = atready skill path
  Copy-Item -Recurse -LiteralPath $skillSource -Destination $skillDest
}
atready skill status
```

To update an existing skill, review and replace it as a separate deliberate step. After Codex
restarts, try:

```text
$project-atready I have a rough project idea. Use my saved AtReady resources to show where they fit.
```

The skill asks at most one consolidated routing question. The CLI produces the readable response
and complete JSON evidence together, so Codex does not have to rewrite the route. The skill stops
before implementation. The public beta does not depend on OpenAI Plugin Directory publication.

## Useful commands

```text
atready                         Show the welcome screen
atready --help                  List commands
atready demo                    Run the complete fake example
atready init                    Create an empty personal inventory
atready add                     Add one resource through guided setup
atready plan                    Make a guided resource plan
atready resource profiles      Browse planning-oriented resource suggestions
atready inventory list         List saved resources
atready inventory validate     Check an inventory
atready project template       Print a starter project brief
atready route                  Produce a concise advisory resource plan
atready help planning           Show the beginner planning workflow
atready help --all              Show every advanced command
```

## Documentation

- [First-time test journey](https://github.com/stoicpickle/atready/blob/main/docs/TRY_ATREADY.md)
- [How routing works](https://github.com/stoicpickle/atready/blob/main/plugins/atready/skills/project-atready/references/routing-rules.md)
- [Output contract](https://github.com/stoicpickle/atready/blob/main/plugins/atready/skills/project-atready/references/output-contract.md)
- [Data model](https://github.com/stoicpickle/atready/blob/main/docs/DATA_MODEL.md)
- [Permissions and safety](https://github.com/stoicpickle/atready/blob/main/docs/PERMISSIONS.md)
- [Threat model](https://github.com/stoicpickle/atready/blob/main/docs/THREAT_MODEL.md)
- [Roadmap](https://github.com/stoicpickle/atready/blob/main/docs/ROADMAP.md)

## Feedback and contributing

AtReady is early. The most useful feedback is practical: what you tried, where setup became
confusing, whether the recommendation changed your plan, and whether you wanted to use it again.

The quickest way to help is to complete the
[first-time test journey](https://github.com/stoicpickle/atready/blob/main/docs/TRY_ATREADY.md), then
[share first-use feedback](https://github.com/stoicpickle/atready/issues/new?template=first-use-feedback.yml).

If you want to work on the project itself, clone the source and install its development tools:

```bash
git clone https://github.com/stoicpickle/atready.git
cd atready
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Please use synthetic fixtures in issues, tests, and examples. Do not post inventories, credentials,
private notes, account details, or proprietary project plans.

AtReady is licensed under the
[Apache License 2.0](https://github.com/stoicpickle/atready/blob/main/LICENSE).
