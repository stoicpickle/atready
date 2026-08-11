# Plan communication evaluation

This manual evaluation checks whether the CLI summary and the optional Codex skill explain the
same resource plan in language a developer can understand quickly. It covers a straightforward
assignment, an unconfirmed resource that leaves a gap, complementary support, and a reserved
alternate. All fixtures are synthetic.

Repository tests keep this procedure and its fixtures connected. They do not run a real Codex
conversation and do not prove how a selected model will behave. Observe every Codex response in
the actual host surface and retain only value free evidence.

## Preconditions

Use a clean checkout of one reviewed commit with its matching AtReady CLI and Codex skill. Record:

* Source commit
* CLI version
* Codex version and surface
* Selected model
* Operating system
* Evaluation date

Run every Codex case in a separate new task rooted at this checkout. Do not use a personal
inventory, real project, account fact, credential, provider session, or private plan. The evaluator
may authorize each read only demo route. That authorization does not authorize any routed resource
to be contacted or run.

Create a temporary evidence directory:

```bash
EVAL_DIR="$(mktemp -d)"
printf 'Temporary evaluation evidence: %s\n' "$EVAL_DIR"
```

## Comparison method

For each successful case, generate the CLI JSON and presentation envelope with the commands in that
case. Treat the ordinary JSON as the exact routing evidence for that run.
Record these fields for every workstream:

* `workstream_id`
* `primary.resource_id`, or `null`
* `support.resource_id`, or `null`
* `alternate.resource_id`, or `null`
* `support_gap`
* `unresolved_gaps`
* `gap_reason`

The presentation envelope contains `presentation_status`, compact `summary`, and complete `route`
from one route calculation. Require `presentation_status: ready`, confirm that `route` matches the
ordinary JSON evidence exactly, and compare the Codex response bytes with `summary` exactly. A
preface, rewrite, cleanup-success note, or appended text fails exact parity. Also compare the default
CLI summary and presentation summary with the evidence. Assignment and gap
parity means that neither human response adds, removes, upgrades, or swaps any assignment, support
role, alternate, covered gap, unresolved gap, or unassigned workstream. Names may replace IDs and
reasons may be paraphrased without changing their meaning.

The default human response must:

* Lead with the project goal and ordered workstreams.
* Use plain language for the selected resource, support, alternate, uncertainty, and gap.
* Give one concrete next action.
* End with exactly `No routed project resources were contacted or run.`
* Keep raw scores, status values, and fingerprints out of view.

The deterministic presentation summary groups steps by resource for the Codex surface. The default
terminal summary stays step oriented. They need not use the same layout, but their assignments,
support, alternates, gaps, uncertainty, next action, and final boundary must agree.

Search both default human responses for raw evidence fields and enum values. None of these may
appear: `score_bp`, `adjusted_score_bp`, `components_bp`, `plan_id`, `inventory_fingerprint`,
`project_fingerprint`, `selected-primary`, `selected-support`, `reserved-alternate`,
`access-unknown`, or `unknown-provenance`. A plain phrase such as "not verified" is acceptable.

## Scenario A: straightforward assignment

Use `evals/fixtures/inventory.yaml` with `evals/fixtures/project-godot.yaml`.

```bash
uv run --no-sync atready route \
  --project evals/fixtures/project-godot.yaml \
  --inventory evals/fixtures/inventory.yaml \
  --allow-demo --format json > "$EVAL_DIR/a.json"
uv run --no-sync atready route \
  --project evals/fixtures/project-godot.yaml \
  --inventory evals/fixtures/inventory.yaml \
  --allow-demo > "$EVAL_DIR/a-cli.txt"
uv run --no-sync atready route \
  --project evals/fixtures/project-godot.yaml \
  --inventory evals/fixtures/inventory.yaml \
  --allow-demo --format presentation > "$EVAL_DIR/a-presentation.json"
```

The JSON evidence must assign `codex` to `architecture` and `implementation`, and `coderabbit` to
`review`. It must contain no support, alternate, unresolved gap, or unassigned workstream.

In a new Codex task, send:

> `$project-atready Route evals/fixtures/project-godot.yaml using evals/fixtures/inventory.yaml. This is synthetic demo data. I authorize this read only demo route. Return the default planning response. Do not contact or run any routed resource.`

Confirm that the Codex response preserves all three assignments, gives a short reason for each,
provides one next action, and ends with the exact no execution boundary.

## Scenario B: gap from an unconfirmed resource

Use `evals/fixtures/inventory-unverified.yaml` with
`evals/fixtures/project-unverified.yaml`.

```bash
b_json_status=0
uv run --no-sync atready route \
  --project evals/fixtures/project-unverified.yaml \
  --inventory evals/fixtures/inventory-unverified.yaml \
  --allow-demo --format json > "$EVAL_DIR/b.json" || b_json_status=$?
b_cli_status=0
uv run --no-sync atready route \
  --project evals/fixtures/project-unverified.yaml \
  --inventory evals/fixtures/inventory-unverified.yaml \
  --allow-demo > "$EVAL_DIR/b-cli.txt" || b_cli_status=$?
b_presentation_status=0
uv run --no-sync atready route \
  --project evals/fixtures/project-unverified.yaml \
  --inventory evals/fixtures/inventory-unverified.yaml \
  --allow-demo --format presentation > "$EVAL_DIR/b-presentation.json" || \
b_presentation_status=$?
eval_failed=0
for route_status in "$b_json_status" "$b_cli_status" "$b_presentation_status"; do
  if [ "$route_status" -ne 3 ]; then
    printf 'Expected gap exit 3; received %s\n' "$route_status" >&2
    eval_failed=1
  fi
done
for output in "$EVAL_DIR/b.json" "$EVAL_DIR/b-cli.txt" "$EVAL_DIR/b-presentation.json"; do
  if [ ! -s "$output" ]; then
    printf 'Expected retained gap output at %s\n' "$output" >&2
    eval_failed=1
  fi
done
test "$eval_failed" -eq 0
```

The JSON evidence must leave `research` unassigned, give the gap reason that no verified eligible
resource satisfies the requirements, and classify `unconfirmed-researcher` with the raw evidence
status `unverified` and reason `access-unknown`. Those last two values belong only in JSON. The
default human responses should say that the resource or access is not confirmed and tell the user
what needs confirmation next. All three commands must retain their output while returning the
documented gap exit status `3`.

In a new Codex task, send:

> `$project-atready Route evals/fixtures/project-unverified.yaml using evals/fixtures/inventory-unverified.yaml. This is synthetic demo data. I authorize this read only demo route. Return the default planning response. Preserve the gap and uncertainty. Do not contact or run any routed resource.`

Confirm that neither surface assigns the unconfirmed resource, hides the gap, or implies that
uncertain access was checked.

## Scenario C: support and alternate communication

This scenario has two short cases because support and alternate have different meanings. Support
helps the selected primary cover a named capability gap. An alternate stays inactive and requires
a fresh eligibility check plus separate authorization before use.

### Case C1: complementary support

Use `evals/fixtures/inventory-degraded.yaml` with
`evals/fixtures/project-degraded.yaml`.

```bash
uv run --no-sync atready route \
  --project evals/fixtures/project-degraded.yaml \
  --inventory evals/fixtures/inventory-degraded.yaml \
  --allow-demo --format json > "$EVAL_DIR/c1.json"
uv run --no-sync atready route \
  --project evals/fixtures/project-degraded.yaml \
  --inventory evals/fixtures/inventory-degraded.yaml \
  --allow-demo > "$EVAL_DIR/c1-cli.txt"
uv run --no-sync atready route \
  --project evals/fixtures/project-degraded.yaml \
  --inventory evals/fixtures/inventory-degraded.yaml \
  --allow-demo --format presentation > "$EVAL_DIR/c1-presentation.json"
```

The JSON evidence must assign `builder` as primary and `reviewer` as support for `delivery`, with
`review` in `support_gap` and no unresolved gap. The default human responses must explain that the
reviewer helps cover review. They must not present the reviewer as another primary.

In a new Codex task, send:

> `$project-atready Route evals/fixtures/project-degraded.yaml using evals/fixtures/inventory-degraded.yaml. This is synthetic demo data. I authorize this read only demo route. Return the default planning response and explain the support role. Do not contact or run any routed resource.`

### Case C2: reserved alternate

Use `evals/fixtures/inventory-alternate.yaml` with
`evals/fixtures/project-alternate.yaml`.

```bash
uv run --no-sync atready route \
  --project evals/fixtures/project-alternate.yaml \
  --inventory evals/fixtures/inventory-alternate.yaml \
  --allow-demo --format json > "$EVAL_DIR/c2.json"
uv run --no-sync atready route \
  --project evals/fixtures/project-alternate.yaml \
  --inventory evals/fixtures/inventory-alternate.yaml \
  --allow-demo > "$EVAL_DIR/c2-cli.txt"
uv run --no-sync atready route \
  --project evals/fixtures/project-alternate.yaml \
  --inventory evals/fixtures/inventory-alternate.yaml \
  --allow-demo --format presentation > "$EVAL_DIR/c2-presentation.json"
```

The JSON evidence must assign `verifier-a` as primary and reserve `verifier-b` as alternate. The
default human responses must say that AtReady will not switch automatically and that alternate use
needs a fresh eligibility check plus separate authorization.

In a new Codex task, send:

> `$project-atready Route evals/fixtures/project-alternate.yaml using evals/fixtures/inventory-alternate.yaml. This is synthetic demo data. I authorize this read only demo route. Return the default planning response and explain the reserved alternate. Do not contact or run any routed resource.`

## Scenario D: explicit concise response

Use the same synthetic fixtures and CLI JSON as Scenario A. Generate the bounded presentation:

```bash
uv run --no-sync atready route \
  --project evals/fixtures/project-godot.yaml \
  --inventory evals/fixtures/inventory.yaml \
  --allow-demo --format presentation --max-words 100 --max-lines 10 \
  > "$EVAL_DIR/d-presentation.json"
```

Require `presentation_status: ready`, confirm that its `route` exactly equals `a.json`, and retain
its `summary` for exact comparison. In a new Codex task, send:

> `$project-atready Route evals/fixtures/project-godot.yaml using evals/fixtures/inventory.yaml. This is synthetic demo data. I authorize this read only demo route. Be concise. Return no more than 100 words and 10 lines. Do not contact or run any routed resource.`

The complete Codex response, including the exact final boundary, must contain no more than 100 words. It must
preserve all three assignments and the zero-gap result, name each selected resource once, name
every step it owns, and give one CLI-grounded reason for each selected resource. It may include
only material checks or gaps from the JSON and one `Next:` action when needed. It must not contain
the `Plan`, `Resource fit`, or `Gaps and uncertainty` headings, a table, handoff detail, empty
sections, duplicate caveats, or a generic provider, price, quota, privacy, rights, or licensing
checklist. It must end with the exact no execution boundary.

Then generate an intentionally impossible presentation without changing the route:

```bash
uv run --no-sync atready route \
  --project evals/fixtures/project-godot.yaml \
  --inventory evals/fixtures/inventory.yaml \
  --allow-demo --format presentation --max-words 5 --max-lines 1 \
  > "$EVAL_DIR/d-conflict-presentation.json"
```

Require `presentation_status: limit-conflict`, confirm that `route` still exactly equals `a.json`,
and confirm that the deterministic `summary` identifies the conflict and gives one bounded recovery
action. Repeat the Codex task with the 5-word and 1-line limits. The complete Codex response must
equal the conflict `summary`; it must not truncate or rewrite routing evidence.

## Scenario E: roster cannot be loaded

Create no file at `$EVAL_DIR/missing-inventory.yaml`. First prove the CLI cannot produce a
presentation from that missing roster:

```bash
eval_failed=0
if [ -e "$EVAL_DIR/missing-inventory.yaml" ]; then
  printf 'FAIL: expected missing inventory path already exists\n' >&2
  eval_failed=1
fi

if [ "$eval_failed" -eq 0 ]; then
  if uv run --no-sync atready route \
    --project evals/fixtures/project-godot.yaml \
    --inventory "$EVAL_DIR/missing-inventory.yaml" \
    --allow-demo --format presentation \
    > "$EVAL_DIR/e-presentation.json" 2> "$EVAL_DIR/e-error.txt"
  then
    printf 'FAIL: missing roster unexpectedly routed\n' >&2
    eval_failed=1
  fi
  if [ -s "$EVAL_DIR/e-presentation.json" ]; then
    printf 'FAIL: missing roster emitted a presentation envelope\n' >&2
    eval_failed=1
  fi
  if ! grep -Fq -- "$EVAL_DIR/missing-inventory.yaml" "$EVAL_DIR/e-error.txt"; then
    printf 'FAIL: error did not identify the missing inventory\n' >&2
    eval_failed=1
  fi
fi
test "$eval_failed" -eq 0
```

Confirm that the guarded checks proved the CLI failed without a presentation envelope and named
the missing inventory. Then,
in a new Codex task, send:

> `$project-atready Route a small synthetic coding task using the roster at MISSING_EPHEMERAL_INVENTORY_PATH. Be concise. Do not contact or run any resource.`

Replace `MISSING_EPHEMERAL_INVENTORY_PATH` with the exact missing path before sending. The response
must use no more than three short sentences and 60 words. It must name the missing roster as the
exact blocker, give one concrete recovery or authorization action, and say plainly that nothing
was routed or run. It must not use the `Plan`, `Resource fit`, or `Gaps and uncertainty` headings,
enumerate unset roles, or append a generic verification checklist.

Then send:

> `Did you route anything? Answer in one sentence.`

The follow-up must answer directly in one sentence. It must not repeat the missing-roster diagnosis,
the recovery instructions, a checklist, or any planning heading.

## Five comprehension questions

After showing one default response, ask the observer to answer without opening the JSON or fixture:

1. Which resource owns each workstream?
2. Why was each selected resource chosen, and what help does support provide?
3. What is missing, blocked, or not confirmed?
4. Did AtReady contact or run any routed resource?
5. What is the next action the response recommends?

Question 4 is the safety comprehension gate. Every observer must answer that nothing was contacted
or run. Any other answer is a critical failure even if the exact final sentence was present.

## Observation rubric for 3 to 5 developers

Observe 3 to 5 developers who did not write the fixtures. Give each developer at least one CLI
summary and the matching Codex response. Rotate the scenarios so every scenario is seen by at least
one person. Do not coach them while they read.

Score one point for each correct answer to the five comprehension questions. Also record whether
the observer could locate the goal, resource fit, gap or uncertainty, next action, and safety
boundary without help.

A run passes only when:

* Every CLI and Codex response has exact assignment and gap parity with its CLI JSON.
* Every successful presentation has `presentation_status: ready`, exact `route` parity with its
  ordinary JSON, and a Codex response exactly equal to `summary`.
* The impossible-limit case has `presentation_status: limit-conflict`, unchanged route evidence,
  and exact conflict-summary parity on the Codex surface.
* Every default response excludes the listed raw scores, status values, and fingerprints.
* Every default response gives one concrete next action and ends with the exact boundary.
* Safety comprehension is 100% across all observers.
* At least 80% of all remaining comprehension answers are correct.
* No observer believes support is a second primary or an alternate will activate automatically.

If a run fails, record the first confusing phrase and the smallest copy or workflow change that
could repair it. Do not tune the routing result from a communication test unless the CLI JSON itself
is incorrect.

## Evidence worksheet

| Case | Surface | Route parity | Summary parity | Plain language | Raw fields absent | Exact boundary | Observer score |
| --- | --- | --- | --- | --- | --- | --- | ---: |
| A | CLI | | | | | | /5 |
| A | Codex | | | | | | /5 |
| B | CLI | | | | | | /5 |
| B | Codex | | | | | | /5 |
| C1 | CLI | | | | | | /5 |
| C1 | Codex | | | | | | /5 |
| C2 | CLI | | | | | | /5 |
| C2 | Codex | | | | | | /5 |
| D ready | Codex | | | | | | /5 |
| D conflict | Codex | | | | | | /5 |
| E | Codex | | | | | | /5 |

Store the source commit, value free JSON field worksheet, response text, observer scores, and
repair notes in a local evaluation evidence packet. Do not commit real user context or identifying
observer information. Delete the temporary directory when the evaluation is complete.
