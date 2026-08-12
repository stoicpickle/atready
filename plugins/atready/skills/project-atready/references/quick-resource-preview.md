# Protected Quick Setup Preview and Save

Use this short reference only after the user approves an unchanged bundled-purpose recap for one
unambiguous profile with definite strength, availability, and private-work answers. Use
[resource-onboarding.md](resource-onboarding.md) for Detailed Setup, custom or ambiguous resources,
corrected purposes, extra facts, `Not sure` answers, or complete declarations. Keep one resource per workflow.

## Facts envelope

Encode exactly the approved facts as bounded JSON and keep the same envelope for preview and apply:

```json
{"schema_version":1,"name":"CodeRabbit","strength":"strong","available_now":true,"private_work":true}
```

Allowed keys are only `schema_version`, `name`, `strength`, `available_now`, and `private_work`.
Strength is `basic`, `solid`, `strong`, or `exceptional`; availability and private work are strict
booleans. Never include credentials, private content, inferred provider/account state, or extra
fields. Use only the user-approved facts.

## Preview

Require approved local execution and filesystem access. Otherwise request that authorization or
provide the exact resolved bundled-launcher command below as an inert user-run instruction; never
offer or invoke a bare `atready add`.
Start the exact pinned bundled launcher command with non-TTY piped stdin:

```bash
"/absolute/path/to/python3" "/absolute/path/to/project-atready/scripts/atready.py" \
  resource quick-add --facts-stdin --json
```

Send one bounded exact JSON line plus a newline through the host's stdin channel; the CLI consumes
that line and exits. Never place the JSON or resource name in a shell command and never create a
temporary file.

For a user-selected roster add `--path /absolute/path/to/inventory.yaml`. The configured roster
omits `--path`. The add request does not authorize roster creation; if the target is missing, ask
before separately initializing it under the Detailed Setup target contract.

Accept a preview only with exit `0`, strict JSON, `status: preview-ready`, format
`atready-resource-quick-preview-v1`, and exactly these false effects: `network_accessed`,
`provider_or_account_inspected`, `resource_run`, and `writes_performed`. `inventory_read` must be
true. Require one canonical nested `preview` with the intended resource, exact target, expected
revision, plan token, and no `applied` mutation claim. Treat mapping values as visible proposals,
not provider verification. Display the actual nested preview unchanged and ask separately:

> Save exactly this entry?

## Mismatch recovery

On a no-write roster/revision mismatch before a complete preview, discard old revision and plan
tokens, retain only the latest approved facts in this task, and say the roster changed, nothing was
saved, and the user may say `retry preview`. Exact same-task `retry preview` re-resolves the target
and repeats the preview command with the same facts. This is the only retry. If it also mismatches,
say the roster keeps changing and nothing was saved, and do not offer another retry in this task.
Do not repeat intake or recap approval. A fact change returns to recap. A different task restarts
intake.

## Apply and verify

Only a later explicit yes to `Save exactly this entry?` authorizes apply. Resend the same facts and
the exact latest preview tokens:

```bash
"/absolute/path/to/python3" "/absolute/path/to/project-atready/scripts/atready.py" \
  resource quick-add --facts-stdin --apply \
  --expect-revision PREVIEW_EXPECT_REVISION --expect-plan PREVIEW_EXPECT_PLAN --json
```

Again send the unchanged bounded JSON line plus a newline through the host's non-TTY stdin channel;
the CLI consumes that line and exits. No shell interpolation or temporary declaration is permitted.

Include the same `--path` choice used for preview. Never retry apply. Accept success only with exit
`0`, strict JSON, format `atready-resource-quick-apply-v1`, `status: applied`, the same mapping,
and a nested receipt proving the intended ID, `applied: true`, `replacement_verified: true`,
revision equal to candidate revision, no warnings, observed revision protection, and POSIX
directory sync where applicable. Then run strict inventory validation and listing through the
bundled launcher and require the same revision and resource ID. Report uncertainty exactly; do not
claim a save.

Preview and apply never contact or run the resource. Preview is no-write; apply writes only the
separately approved local roster update. Neither approval authorizes provider access or execution.
