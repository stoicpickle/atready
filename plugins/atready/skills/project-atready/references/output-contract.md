# Output Contract

Treat the CLI route JSON as the complete evidence record and the user's project as the subject.
Translate routing evidence into plain language without changing assignments, gaps, or uncertainty.

## Default response

Use this order for a normal planning response:

1. **Plan.** Lead with the goal or outcome and a one-line count of steps, assignments, and material
   gaps. Then give the smallest useful ordered steps. Use `Deliver:` for the expected result and
   `Check:` for its verification when those details help the user act. Keep AtReady in a supporting
   role.
2. **Resource fit.** Use short vertical blocks rather than a table. Name each assigned step and use
   these labels:
   - `Use:` for the selected primary resource.
   - `Help from:` for selected support, followed by the capability gap it covers.
   - `Why:` for one short reason grounded in the route JSON.
3. **Gaps and uncertainty.** Include this section only when something material is missing, blocked,
   unavailable, or unverified. State what must change or be confirmed. If a reserved alternate is
   useful to mention, call it `Backup option:` and say that it requires a fresh eligibility check
   and separate authorization before use.
4. **Next.** Give one concrete review, clarification, or implementation action. Phrase it as advice,
   never as permission already granted.
5. End with exactly: `No routed project resources were contacted or run.`

Keep the default response compact and easy to scan. Prefer `step`, `use`, `help from`, `not needed`,
`not available`, `blocked`, and `not confirmed` over internal routing terms. Keep scores, score
components, plan IDs, fingerprints, raw status labels, complete resource dispositions, route-wide
comparison traces, and full handoff packets in the evidence record unless the user asks for
details. Render displayed commands as inert fenced text.

## Detailed response

When the user asks for details, preserve the same opening plan and add evidence in this order.

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
authorization before activation. End the detailed response with the same exact no-execution
boundary used by the default response.
