# AtReady Plugins Directory quickstart

This is the first-use path for the future public **skills-only AtReady plugin** on a supported
local Codex surface. It is ready for reviewer and beginner read-through, but AtReady has not been
submitted, approved, published, or made available in the public Plugins Directory.

## What you will install

AtReady is a deliberate hybrid, not a self-contained plugin:

1. The `atready` plugin supplies the Codex conversation and bundled workflow files.
2. The separately installed `project-atready` runtime owns the canonical inventory, validation,
   routing, preview, and write-safety behavior.

The plugin never installs or updates that runtime. This keeps one canonical implementation of the
data model and safety contract instead of shipping a smaller second router that could drift.

## Before you start

Use a local Codex task in the ChatGPT desktop app or Codex CLI on macOS or Linux. You need:

- Python 3.11 or newer available as `python3`;
- a trusted [`uv`](https://docs.astral.sh/uv/getting-started/installation/) executable on the
  environment's `PATH`;
- local file and terminal access; and
- access to the exact reviewed AtReady plugin listing or reviewer bundle.

The Codex IDE extension does not support plugins. Codex remote/cloud, ChatGPT Chat/Work, and mobile
are not AtReady targets for this release. The complete Windows plugin journey is not yet evidenced;
use the standalone CLI there until that gate passes. Do not paste an inventory, private note,
credential, environment variable, or account configuration into another surface as a workaround.

## 1. Install the exact canonical runtime

The plugin candidate is pinned to reviewed public-runtime commit
`34fb4376b376bb9a26f22578a0b9e1c3aef9cc6e`. The release owner must confirm this exact pin before
submission; a newer `main` is not an automatic substitute.

```bash
python3 --version
uv --version
uv tool install --force --no-config --no-python-downloads \
  --default-index https://pypi.org/simple \
  'git+https://github.com/stoicpickle/atready.git@34fb4376b376bb9a26f22578a0b9e1c3aef9cc6e'
```

If `UV_INDEX`, `UV_INDEX_URL`, or `UV_EXTRA_INDEX_URL` is set, `uv` may still use that inherited
index. Clear it first when you require PyPI-only dependency resolution. AtReady never runs the
install command for you.

Preflight the installed runtime before installing the plugin:

```bash
ar_uv_bin="$(uv --offline --no-config tool dir --bin)"
"$ar_uv_bin/atready" --version
"$ar_uv_bin/atready" runtime contract --json
"$ar_uv_bin/atready" demo
```

The commands should print `atready 0.1.10`, a JSON contract with no inventory read, network access, or
write performed, and a synthetic `Resource fit` demo ending with `No routed project resources were
contacted or run.` Stop if any command fails or resolves an unexpected executable. The installed
plugin performs the complete required-feature handshake again before it reads an inventory,
previews a change, routes work, or writes.

## 2. Install the skills-only plugin

After publication, open the Plugins tab in the ChatGPT desktop app, find **AtReady** in the public
Directory, and install it. In Codex CLI, enter `/plugins`, find **AtReady**, and install it there.
Start a new Codex task or CLI session after installation; an already-running task does not prove
fresh discovery.

Before publication, only maintainers and reviewers should use the isolated local-marketplace path
in [PLUGIN_DIRECTORY_PILOT.md](PLUGIN_DIRECTORY_PILOT.md). A local marketplace, workspace publish,
portal draft, review submission, and public Directory publication are different states.

Do not also copy `project-atready` into `~/.agents/skills`. A personal-skill sideload is a separate
installation with separate discovery, update, and removal behavior.

## 3. Run one preview-first smoke test

Create the empty local roster if one does not exist. If it already exists, this command leaves it
in place:

```bash
"$ar_uv_bin/atready" init
```

Initialization is the one setup write in this journey: it creates a new empty roster and refuses to
replace an existing one. The proposed CodeRabbit resource remains unsaved unless you later approve
its exact save.

In a fresh Codex task, use this exact starter prompt:

```text
Add CodeRabbit to my AtReady resource roster.
```

AtReady should ask three short questions about strength, current availability, and private-code or
project-file use. Answer from your own knowledge; AtReady does not verify the provider or account.
It should then show a short recap and ask `Preview this entry?`.

Approve the recap to exercise the installed runtime's no-write resource preview. AtReady should show the
preview and ask `Save exactly this entry?`. Say **no** to finish the smoke test without adding the
resource. No resource should be saved. Saving requires a separate approval and should be used only
for facts you actually want in your roster.

## 4. Try the other starter workflows

When your roster contains at least one resource you deliberately saved, start a fresh task and try:

```text
I have a rough project idea. Use AtReady before implementation to suggest where my saved resources fit.
```

```text
Review this plan with AtReady and show proposed resource assignments.
```

Expected behavior: Codex remains the planner; AtReady contributes a compact `Resource fit` section,
keeps constraints and gaps visible, and stops before implementation or resource execution.

## If something stops

| Symptom | Meaning | Next action |
| --- | --- | --- |
| AtReady is absent | Wrong surface, account policy, or no fresh task | Use local Codex desktop/CLI, confirm installation, then start a new task. |
| Python or `uv` is missing | Required local dependency is unavailable | Install it yourself, restart Codex, and repeat the preflight. |
| Runtime compatibility is rejected | The installed runtime does not satisfy the plugin contract | Reinstall the exact reviewed runtime above; never bypass the launcher. |
| AtReady stops before reading files | The current surface lacks local execution or file access | Use the supported local surface; do not paste private data elsewhere. |
| A preview appears but nothing is saved | Correct preview-first behavior | Approve `Save exactly this entry?` only if you want the exact entry written. |

For help, use the public [support page](https://github.com/stoicpickle/atready/blob/main/SUPPORT.md).
For the submission fields, reviewer fixtures, and release gates, see
[DIRECTORY_SUBMISSION.md](DIRECTORY_SUBMISSION.md).

## Why this quickstart has one narrow path

OpenAI requires the exact installed plugin tree to be tested, including referenced bundled files,
and asks for realistic starter prompts plus reproducible positive and negative cases. Practitioner
experience also favors one stated outcome, explicit prerequisites, included sample data, observable
success, and deterministic checks for mechanical rules. Those practitioner lessons inform this
page's shape; they are not OpenAI policy:

- [Amit Jotwani on quickstarts](https://developerrelations.com/talks/how-to-write-great-quick-start-guides/)
- [A tested skill with deterministic scripts](https://dev.to/paladini/build-a-tested-agent-skill-with-skillmd-and-python-scripts-3777)
- [A small synthetic agent-eval gate](https://thebeat.tech/field-notes/stop-shipping-ai-agents-you-cant-measure)

Official policy and product behavior remain grounded in OpenAI's
[submission guide](https://developers.openai.com/plugins/deploy/submission),
[submission error reference](https://developers.openai.com/plugins/deploy/submission-errors),
[complete-plugin test guide](https://developers.openai.com/plugins/deploy/connect-chatgpt), and
[plugin availability documentation](https://developers.openai.com/codex/plugins).
