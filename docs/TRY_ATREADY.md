# Try AtReady

This is a short first-time test of AtReady's complete loop: install it, try the safe demo, add one
resource you really use, and see where that resource fits in a small plan. Allow about 10 minutes.

AtReady will not scan your computer, contact the resource, run project work, or spend credits.
Your resource roster stays in a local inventory file. Do not put credentials, private account
details, client information, or proprietary plans into AtReady or your feedback report.

## 1. Install the public source beta

You need Python 3.11 or newer and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/stoicpickle/atready.git
cd atready
uv tool install .
atready --version
cd ..
mkdir atready-first-test
cd atready-first-test
```

The last three commands move you into a separate sibling working folder. Keep the demo files and
your personal project there so they never become files in the AtReady source checkout.

## 2. Run the safe demo

The demo uses bundled fake resources. It does not read or change your personal inventory.

```bash
atready demo inventory > demo-inventory.yaml
atready project template > demo-project.yaml
atready route --project demo-project.yaml --inventory demo-inventory.yaml --allow-demo
```

Read the result once as a plan: what resource did it choose, why, and what did it leave out?

## 3. Add one resource you really use

Create your local roster, then open the guided setup:

```bash
atready init
atready add
```

Choose one tool, agent, service, subscription, app, or person you actually have available. A
built-in starter profile can save typing, but its suggestions are editable and are not verified
facts about your account. `Not sure` is a valid answer when the flow offers it.

AtReady shows a no-write preview first. Nothing is saved until you separately type the exact save
confirmation it gives you. The inventory remains on your computer; do not upload it or paste its
contents into the feedback form.

If `atready init` says an inventory already exists, keep it and continue with `atready add`.

## 4. Route one small project

Start the guided planner:

```bash
atready plan
```

Use a real but non-sensitive goal. Choose one to three steps, state the expected result and check,
and select only capabilities you recognize from the roster shown by AtReady. Confirm the minimum
strength and eligibility controls before asking it to route. The planner does not infer
capabilities from your prose and does not write a project file.

A useful result should make the assignment, reasoning, deliverable, check, and any gap easy to
understand. It is advice, not an executed workflow: edit it, ignore it, or use it in your plan.

If you prefer an editable project file, run `atready help planning` after this test. It shows the
advanced `project template` and `route --project` workflow.

## 5. Tell us how it went

[Open the first-use feedback form](https://github.com/stoicpickle/atready/issues/new?template=first-use-feedback.yml)
and answer these five questions:

1. How far did you get?
2. What were you trying to plan, and what did AtReady produce?
3. Where did you slow down or feel unsure?
4. How easy was the resource plan to understand?
5. Did the plan change what you would do, and what one improvement would help most?

Please describe rather than paste sensitive material. Do not attach your inventory, terminal
history, credentials, private notes, local file paths, account details, or a proprietary plan.
