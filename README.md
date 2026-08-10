# AtReady

**Plan with what you have at the ready.**

AtReady is a small, local-first planning tool. Tell it about the coding agents, creative tools,
subscriptions, services, or people available to you. Give it a rough project plan. It recommends
where those resources fit and explains why.

It does not run the work, contact your tools, or spend your credits. You stay in control.

![AtReady welcome screen](https://raw.githubusercontent.com/stoicpickle/atready/main/docs/assets/atready-cli.png)

> **Public beta:** AtReady works today, but its setup and language will keep improving as people try
> it. Expect changes—and please share what feels confusing or unnecessary.

## The idea in one minute

Maybe you have Codex, CodeRabbit, Cursor, a design subscription, and a small amount of image credit.
A project comes along. Instead of forgetting what is available—or trying to use everything—AtReady
helps answer:

- Which resources are actually useful for this plan?
- What should each one handle?
- Which resources should stay out of the way?
- What is missing, uncertain, or blocked?

AtReady turns those answers into an advisory route and inert handoff notes. Nothing is dispatched.

## Try the synthetic demo

This example uses bundled fake data and does not touch a personal inventory.

```bash
atready demo inventory > inventory.yaml
atready project template > project.yaml
atready route \
  --project project.yaml \
  --inventory inventory.yaml \
  --allow-demo
```

The result looks like this:

```text
Resource plan: Synthetic CLI Release
Goal: Ship a tested local CLI without network access or telemetry.
1 step - 1 assigned - no open gaps

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

Next: Review the assignments. Use --format markdown for scores and full handoff
      details.
AtReady made this plan only.
No routed project resources were contacted or run.
```

## Install the source beta

AtReady currently installs from this repository. You need Python 3.11 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/stoicpickle/atready.git
cd atready
uv tool install .
atready
```

The bare `atready` command opens a short welcome screen with a safe demo path. Run
`atready --help` to see every command.

## Use your own resources

AtReady keeps your declared resources in a local inventory file. A resource can be an AI coding
agent, a reviewer, a creative app, a service, a subscription, a person, or anything else that may
help with a project.

Start an empty inventory:

```bash
atready init
```

Then use the guided Quick Add flow:

```bash
atready add
```

AtReady offers editable starter profiles and asks for routing and safety declarations. `Not sure`
is valid for readiness; whether the resource requires internet needs a yes/no answer. It does not
scan your computer, inspect accounts, contact providers, or run the resource. Quick Add shows a
friendly recap, asks before generating the complete no-write preview, then requires a separate
exact `save <resource-id>` confirmation before writing. Cancelling before that confirmation changes
nothing.

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

Those readiness, cost, data, and date fields are declarations about your setup—not facts AtReady
silently verifies. The advanced preview shows the complete proposed change, an expected revision,
and a plan token. Nothing is saved until you repeat the command with `--apply`, the exact revision,
and the exact plan token. Guided and advanced setup both create a private exact-byte backup and
atomically replace the inventory; both report durability uncertainty instead of pretending a write
was fully proven.

If the typed command feels too long, AtReady also accepts one protected YAML or JSON declaration
through `--resource-file` or `--resource-stdin`. The
[resource intake guide](https://github.com/stoicpickle/atready/blob/main/plugins/atready/skills/project-atready/references/resource-onboarding.md)
explains the same fields in friendlier language.

## Route a real plan

Create a starter project file:

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

The CLI is the product. This repository also includes an optional Codex skill that can guide the
same setup and planning flow conversationally. The skill does not replace the CLI's validation,
preview, or routing engine.

Developers working from this checkout can inspect it with:

```bash
atready skill path
```

The public beta does not depend on OpenAI Plugin Directory publication.

## Useful commands

```text
atready                         Show the welcome screen
atready --help                  List commands
atready init                    Create an empty personal inventory
atready resource profiles      Browse planning-oriented resource suggestions
atready inventory list         List saved resources
atready inventory validate     Check an inventory
atready project template       Print a starter project brief
atready route                  Produce a concise advisory resource plan
```

## Documentation

- [How routing works](https://github.com/stoicpickle/atready/blob/main/plugins/atready/skills/project-atready/references/routing-rules.md)
- [Output contract](https://github.com/stoicpickle/atready/blob/main/plugins/atready/skills/project-atready/references/output-contract.md)
- [Data model](https://github.com/stoicpickle/atready/blob/main/docs/DATA_MODEL.md)
- [Permissions and safety](https://github.com/stoicpickle/atready/blob/main/docs/PERMISSIONS.md)
- [Threat model](https://github.com/stoicpickle/atready/blob/main/docs/THREAT_MODEL.md)
- [Roadmap](https://github.com/stoicpickle/atready/blob/main/docs/ROADMAP.md)

## Feedback and contributing

AtReady is early. The most useful feedback is practical: what you tried, where setup became
confusing, whether the recommendation changed your plan, and whether you wanted to use it again.

If you want to work on the project locally:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Please use synthetic fixtures in issues, tests, and examples. Do not post inventories, credentials,
private notes, account details, or proprietary project plans.

AtReady is licensed under the
[Apache License 2.0](https://github.com/stoicpickle/atready/blob/main/LICENSE).
