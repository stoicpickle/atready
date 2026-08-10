# Output Contract

Treat the CLI route JSON as the complete evidence record. In normal conversation, keep the user's
project plan primary: return their plan—or the tightened plan derived from their goal or rough
input—as the main result. Add only a
compact `Resource fit` section with assigned resources, short CLI-grounded reasons, and material
gaps, followed by `No routed project resources were contacted or run.` Do not make AtReady the main subject
of the response. Do not render score traces, every omission, the full execution route, or handoff
packets unless the user asks for detail or a material gap cannot be understood without it.

When the user requests the expanded AtReady result, return it in the order below.

## 1. Project interpretation

State the goal, target deliverable, material constraints, data classification, and assumptions.

## 2. Deterministic workstream route

Use a table with resource, assigned workstreams, role, and the CLI-returned selection reason. Include
only assigned resources. When explaining a comparison, cite returned score/component or gate data;
do not invent a causal rationale that is absent from the route JSON.
For support, cite the selected support evaluation's combined fit, fit gain, and covered gaps. For an
alternate, preserve the standalone role evaluation and its activation caveat.

## 3. Execution route

For each workstream, include:

- objective;
- primary resource;
- optional support and its named capability gap;
- optional standalone-eligible alternate and its activation condition;
- inputs;
- deliverable;
- acceptance criteria;
- verification;
- next owner.

## 4. Handoff packets

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

## 5. Complete resource dispositions

List all remaining resources under exactly one heading:

- Resources deliberately not used
- Unavailable resources
- Ineligible resources
- Unverified resources

Give a concrete reason for each. Omit an empty heading.

## 6. Gaps, risks, and decisions

Separate capability gaps from risks. List only decisions that require the user to change a
constraint, accept uncertainty, authorize a purchase, or authorize later execution.

Before returning, verify that every workstream is assigned or marked as a gap, every inventory
resource has one disposition, support count never exceeds one, and every handoff field is present.
State that workstreams are routed in declared order and continuity may affect later selections. Do
not describe the result as a global resource-count minimum. An alternate does not establish
failure-domain independence, redundancy, availability, or automatic failover; require a fresh
eligibility check and separate authorization before activation.
