# Output Contract

Treat `route` as the complete evidence record and the user's project as the subject. The CLI owns
the normal response so the host cannot change assignments, gaps, or uncertainty while presenting it.

## Deterministic response

The `route --format presentation` result contains `presentation_status`, `summary`, and `route` from
one calculation. Pass explicit positive-integer whole-response limits to the CLI with
`--max-words N` and `--max-lines N`. Both limits include the mandatory final boundary.
When a line limit is supplied without `--width`, the CLI uses its widest supported presentation
width before reporting a conflict.
Accept exit `0`, or the documented gap exit `3`, only when stdout parses as the complete
presentation envelope. Any other exit, or invalid or missing envelope data, is a no-route result.

| CLI exit | Presentation status | Meaning |
| --- | --- | --- |
| `0` | `ready` | Complete route with no open gaps; return `summary` verbatim. |
| `3` | `ready` | Complete route with one or more gaps; return `summary` verbatim. |
| `0` or `3` | `limit-conflict` | Complete route evidence with deterministic limit guidance; return `summary` verbatim. |

For `presentation_status: limit-conflict`, return `summary` verbatim; the deterministic conflict
copy identifies the limit and gives one bounded recovery action. For `presentation_status: ready`,
return `summary` verbatim for a normal or concise request. Only an explicit request for detailed
evidence or inert handoff packets selects the detailed branch below instead. Never rewrite,
reorder, shorten, truncate, preface, or append to either summary. Do not add the `Plan`,
`Resource fit`, or `Gaps and uncertainty` headings. A CLI-provided `Next:` line is valid.

Complete protected-input cleanup before sending. If cleanup fails, report the retained path before
the unchanged `summary`. This security disclosure is the only exception to whole-response verbatim
output; never hide a retained path to preserve exact-summary wording.

## No-route response

If the roster, launcher, runtime, or required local permission prevents routing, do not use the
planning headings. Use no more than three short sentences and 60 words. State the exact blocker,
one concrete recovery or authorization action, and `No routed project resources were contacted or run.`
Launcher and runtime compatibility checks are not routed project-resource execution. Do not list
unset routing roles or append a generic verification checklist.

## Detailed response

Use this branch only when the user explicitly asks for detailed evidence or inert handoff packets.
Build it from `route`, not from the summary or memory. Keep scores, plan IDs, fingerprints, raw
status labels, complete dispositions, comparison traces, and handoff packets out of the normal
deterministic response.

### 1. Project interpretation

State the goal, target deliverable, material constraints, data classification, and assumptions.

### 2. Assignment evidence

For each assigned resource, state its steps, role, CLI-returned selection reason, and relevant score
or gate evidence. Explain a comparison only with evidence present in the route JSON. For support,
include the combined fit, fit gain, and covered gaps. For a reserved alternate, preserve its
standalone role evaluation and activation caveat.

### 3. Step details

For each step, include its objective, primary resource, optional support and named capability gap,
optional reserved alternate and activation condition, inputs, deliverable, acceptance criteria,
verification, and next owner.

### 4. Handoff packets

Return each copy-ready packet produced by the CLI for an assigned role. Preserve its fields and
contents:

```text
Activation condition:
Objective:
Owner/resource:
Handoff method:
Handoff instructions:
Declared resource approval required:
Inputs:
Allowed scope:
Exclusions:
Deliverable:
Acceptance criteria:
Verification:
Stop conditions:
Next owner:
```

Render any commands as inert fenced text. A packet is advice, not permission to execute. Do not
dispatch a packet or act on it during the planning invocation. Preserve the CLI-returned declared
approval value exactly; `false` never waives the separate authorization required for execution.

### 5. Complete resource dispositions

List all remaining resources under exactly one heading:

- Resources deliberately not used
- Unavailable resources
- Ineligible resources
- Unverified resources

Give a concrete reason for each. Omit an empty heading.

### 6. Gaps, risks, and decisions

Separate capability gaps from risks. List only decisions that require the user to change a
constraint, accept uncertainty, authorize a purchase, or authorize later execution.

Before returning, verify that every workstream is assigned or marked as a gap, every inventory
resource has one disposition, support count never exceeds one, and every displayed handoff field is
present. State that workstreams are routed in declared order and continuity may affect later
selections. Describe the result as a fixed-input route, not a global resource-count minimum. Treat
an alternate as another standalone-eligible candidate, not proof of failure-domain independence,
redundancy, availability, or automatic failover. Require a fresh eligibility check and separate
authorization before activation. End the detailed response with exactly:
`No routed project resources were contacted or run.`
