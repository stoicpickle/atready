# Try AtReady

This is a short first test of AtReady's complete loop: install it, try the safe demo, add one
resource you really use, and see where that resource fits in a small plan. Allow about 10 minutes.

AtReady will not scan your computer, contact the resource, run project work, or spend credits.
Your resource roster stays in a local inventory file. Do not put credentials, private account
details, client information, or proprietary plans into AtReady or your feedback report.

## 1. Install AtReady

You need Python 3.11 or newer and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv tool install git+https://github.com/stoicpickle/atready.git
```

If your terminal says `atready` was not found, run `uv tool update-shell`, close and reopen the
terminal, then try again.

Check the installed version:

```bash
atready --version
```

This installs the public version directly from GitHub. You do not need to clone the source or set
up a development environment.

## 2. Run the safe demo

The demo uses bundled fake resources. It does not read or change your personal inventory.

```bash
atready demo
```

The command prints a complete example plan without creating files, using the network, or reading or
changing your personal resource list. Read the result once: what resource did it choose, why, and
what did it leave out?

## 3. Try your own resource and plan

Run these three commands in order:

```bash
atready init
atready add
atready plan
```

1. `atready init` creates an empty local resource list. If one already exists, AtReady keeps it.
2. `atready add` guides you through adding one tool, agent, service, subscription, app, or person
   you actually have available. Starter suggestions are editable and are not verified facts about
   your account. `Not sure` is a valid answer when the flow offers it.
3. `atready plan` asks for a real but non-sensitive goal and one to three steps, then suggests where
   your saved resources fit.

During `atready add`, AtReady shows a no-write preview first. Nothing is saved until you separately
type the exact save confirmation it gives you. The inventory remains on your computer; do not
upload it or paste its contents into the feedback form.

A useful result should make the assignment, reasoning, deliverable, check, and any gap easy to
understand. It is advice, not an executed workflow: edit it, ignore it, or use it in your plan.

If you prefer an editable project file, run `atready help planning` after this test. It shows the
advanced `project template` and `route --project` workflow.

## 4. Tell us how it went

[Open the first-use feedback form](https://github.com/stoicpickle/atready/issues/new?template=first-use-feedback.yml)
and answer these five questions:

1. How far did you get?
2. What were you trying to plan, and what did AtReady produce?
3. Where did you slow down or feel unsure?
4. How easy was the resource plan to understand?
5. Did the plan change what you would do, and what one improvement would help most?

Please describe rather than paste sensitive material. Do not attach your inventory, terminal
history, credentials, private notes, local file paths, account details, or a proprietary plan.
