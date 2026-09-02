# AtReady private beta: start here

AtReady is a small resource-fit companion for Codex. Once you know what you want to make, bring it a
goal, rough plan, or written plan before implementation begins. It matches your declared resources
to planner-provided work, explains material constraints and gaps, and returns evidence Codex can use
while refining the plan. Codex owns project planning. AtReady recommends and prepares; it does not
log in to, contact, or run saved resources for project work. The optional, separately authorized
version check does execute one exact external CLI with fixed arguments; its side effects are not
evaluated.

This beta is for invited developers. Use synthetic information for the first run. Never paste API
keys, tokens, cookies, passwords, private notes, client data, or an existing personal inventory into
a beta task or report.

Use a test profile when practical. Do not install over an existing AtReady CLI, marketplace,
plugin, or personal inventory; the setup helper refuses the detectable cases instead of silently
replacing them. The owner never needs your credentials. Authenticate `gh` yourself with the GitHub
account the owner approved for the beta repository.

This AtReady helper is a clean-install beta lane. It does not migrate or remove a former
Quartermaster marketplace, plugin, runtime, beta root, or state file. Remove that retired test
installation separately, or choose a new isolated profile and beta root before continuing.

## 1. Install the exact candidate

The owner will send you five exact inputs:

- the private beta repository in `OWNER/REPOSITORY` form;
- a 40-character source commit;
- a successful release-candidate run ID;
- the `beta_setup.py` file committed at that source commit; and
- one absolute folder that you approve for this isolated beta.

Save and review `beta_setup.py`; do not pipe a remote script into a shell or Python. On macOS or
Linux, replace every uppercase value and run this one command in a fresh terminal:

```bash
python3 beta_setup.py install \
  --repository BETA_OWNER/BETA_REPOSITORY \
  --source-sha SOURCE_SHA \
  --run-id RUN_ID \
  --beta-root /ABSOLUTE/PATH/atready-beta
```

On Windows PowerShell, use the same inputs with `py -3 .\beta_setup.py install` and a fully qualified
folder such as `C:\Users\YOUR_NAME\atready-beta`. The helper has cross-platform unit coverage;
Windows remains a beta evidence target until an invited tester completes the full journey there.

The helper verifies the release-candidate workflow name, `workflow_dispatch` event, successful
conclusion, exact commit, candidate bundle, its own source bytes, CLI version, plugin version,
runtime contract, and the synthetic acceptance journey. The workflow separately enforces the
configured release-owner secret before it builds the candidate.
It creates a synthetic inventory and prints the exact path. It does not inspect accounts,
credentials, personal inventories, or other installed tools. It obtains Python dependencies only
from the explicitly named PyPI index and never publishes anything. Stop if it reports a failure;
the detailed artifact and evidence boundary is in [`PRIVATE_BETA.md`](PRIVATE_BETA.md).

Start a **new Codex task** after installation. An existing task may not load the new plugin version.

### Receive a beta update

For every update, the owner sends a new exact commit, run ID, and matching `beta_setup.py`. Review
the new helper and use the same repository and beta-root values:

```bash
python3 beta_setup.py update \
  --repository BETA_OWNER/BETA_REPOSITORY \
  --source-sha NEW_SOURCE_SHA \
  --run-id NEW_RUN_ID \
  --beta-root /ABSOLUTE/PATH/atready-beta
```

The updater retains old verified candidates, preserves the synthetic inventory, verifies the new
runtime and plugin together, and attempts to restore the prior verified pair if activation fails.
Run `python3 beta_setup.py status --beta-root /ABSOLUTE/PATH/atready-beta` at any time for a
local, non-publishing compatibility check. Start another new Codex task after a successful update.

## 2. Add one resource

Paste this in the new task:

```text
Use $project-atready Quick Setup to add CodeRabbit to my resource roster at TEST_INVENTORY_PATH. Guide me through the preview first; do not save until I separately approve the exact rendered entry.
```

Replace `TEST_INVENTORY_PATH` with the exact printed synthetic inventory path. Every preview, save,
and validation command must show that exact path. Do not read or change any existing inventory.

Expect one short CodeRabbit prompt. It should tentatively describe the resource in plain language,
then ask exactly three questions: how strong it is for that work, whether it is available now, and
whether you would use it with private code or project files. Answer in an ordinary sentence;
`Not sure` is valid.
The compact recap should show only purpose, strength, availability, private-work permission, and
material unknowns. The later no-write preview carries IDs, mappings, defaults, and target details.
AtReady must not start a review, log in, inspect an account or repository, install or
update CodeRabbit, change settings, or claim authentication, quota, or availability. It should then:

1. show a no-write preview only after you approve that preview;
2. stop again before saving;
3. save only after you approve the exact rendered entry; and
4. validate the roster without contacting or running CodeRabbit.

## 3. See the quiet payoff

First, check the roster without changing it:

```text
Show my AtReady resource roster and explain what is still unknown. Do not change anything.
```

Then explicitly bring the roster into a loose plan before implementation:

```text
I have a loose plan for a small synthetic logging feature: add structured logs, tests, and an independent review. Use AtReady before implementation to show where my saved resources fit across those steps. Keep the resource recommendation brief and do not contact or run anything.
```

You should not have to write a formal AtReady brief or YAML. The project plan should remain
the main result. AtReady should add a compact `Resource fit` section, explain any genuine gap,
and leave all handoffs unexecuted.

## If you get stuck

Use one of these prompts:

- `Continue without checking my computer.`
- `Keep unknowns unknown and ask only for information that blocks the preview.`
- `Nothing should be saved yet. Tell me which authorization stage we are at.`
- `Check whether the AtReady plugin and local runtime are compatible. Do not change my roster.`

## Send useful feedback

Please report only synthetic, value-free evidence:

- Did installation and the acceptance check pass on the first try?
- Could you add CodeRabbit without outside help?
- What was the first confusing phrase or moment?
- Did preview versus save feel clear?
- Did the later resource advice feel useful and quiet, or intrusive?
- What did you expect AtReady to do that it did not do?

Include your operating system, Codex version, AtReady version, source commit, and whether you
completed the three prompts. Do not attach an inventory, terminal history, local paths, account
details, credentials, private notes, or a plan based on real work.

Reply through the same private channel where the owner invited you, unless the owner provides a
private issue link. Do not post beta evidence publicly.

## Remove the beta

```bash
python3 beta_setup.py remove \
  --beta-root /ABSOLUTE/PATH/atready-beta
```

The helper first proves that the exact recorded plugin and runtime are still installed. It removes
their Codex and uv configuration but does not delete the beta root or any inventory. The owner
separately removes private-repository access when the beta ends. Review the printed exact beta root,
confirm that it contains only retained candidate files and the synthetic `test-state`, and then move
that exact folder to Trash. Do not delete an existing inventory or a broader directory.

Removal does not delete an AtReady inventory.
