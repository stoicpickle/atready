# Plugins Directory submission packet

This is a **disposable, nonrelease portal-probe candidate** for AtReady. It exists only to
test portal acceptance and supported-surface behavior. Do not submit it for review, publish it,
represent it as a release candidate, or reuse its receipt as release evidence. It is not evidence
that a submission draft exists, OpenAI has approved the plugin, or the developer has published it.

Official OpenAI documentation currently supports **skills-only** plugin submissions through the
[OpenAI Platform plugin submission portal](https://platform.openai.com/apps-manage). The documented
flow is submit, OpenAI review, developer-controlled publish after approval, then appearance in the
Plugins Directory shared by ChatGPT and Codex. Reconfirm the
[official submission instructions](https://developers.openai.com/plugins/deploy/submission) at the
time of submission because portal fields and review requirements can change.

## Listing identity

These are the exact manifest-bound, form-ready values. Copy them from the final manifest rather
than retyping them in the portal, then rerun the consistency check below. Current final-submission
limits are 30 characters for display name and short description, 4,000 for long description, 80
for developer name, 20 capability labels, and three unique one-line starter prompts of 128
characters each.

```json
{
  "displayName": "AtReady",
  "shortDescription": "Bring resource fit to the plan",
  "longDescription": "AtReady is a small resource-fit companion for supported Codex surfaces. Add one declared tool, service, subscription, person, or agent through a conversational no-write preview and a separate exact save approval. Then bring AtReady a goal, rough plan, or written plan before implementation to match saved tools, services, subscriptions, people, and agents to planner-provided work, expose material constraints and gaps, and explain its advice without contacting or running routed project resources. Codex owns the project plan. This local-first release requires a separately installed compatible project-atready runtime and local file access.",
  "developerName": "stoicpickle",
  "category": "Developer Tools",
  "capabilities": ["Add declared resources with approval", "Match saved resources to project work", "Explain constraints, gaps, and omissions"],
  "websiteURL": "https://github.com/stoicpickle/atready",
  "supportURL": "https://github.com/stoicpickle/atready/blob/main/SUPPORT.md",
  "privacyPolicyURL": "https://github.com/stoicpickle/atready/blob/main/PRIVACY.md",
  "termsOfServiceURL": "https://github.com/stoicpickle/atready/blob/main/TERMS.md",
  "defaultPrompt": [
    "I have a rough project idea. Use AtReady before implementation to suggest where my saved resources fit.",
    "Review this plan with AtReady and show proposed resource assignments.",
    "Add CodeRabbit to my AtReady resource roster."
  ],
  "brandColor": "#0B172A"
}
```

Measured against current Directory limits: display name `7/30`, short description `30/30`, long
description `642/4000`, developer name `11/80`, and starter prompts `103/128`, `69/128`, and
`45/128`. `Developer Tools` is a currently supported category. Any manifest copy change invalidates
these measurements until the check is rerun.

- Architecture: skills-only plugin plus a separately installed canonical runtime. **Not
  self-contained.** The plugin contains no second router and never installs, updates, or repairs
  the runtime.
- Website: `https://github.com/stoicpickle/atready`
- Support: `https://github.com/stoicpickle/atready/blob/main/SUPPORT.md`
- Privacy: `https://github.com/stoicpickle/atready/blob/main/PRIVACY.md`
- Terms: `https://github.com/stoicpickle/atready/blob/main/TERMS.md`
- Brand color: `#0B172A`
- Submission type: Skills only
- Probe target: local Codex tasks and Codex CLI with local Python, trusted `uv`, and local file
  access. The skills-only plugin does not install, update, or repair the separate CLI runtime. The
  probe must establish whether every non-target surface hides AtReady or discloses incompatibility
  before an actionable workflow; it does not claim ChatGPT Chat/Work or Codex remote/cloud support.

OpenAI's skills-only package validator permits the four URL fields to be omitted from the manifest,
but the public submission guide still requires website, support, privacy, and terms materials for
the listing and final checklist. AtReady requires them to be anonymously reachable before
public launch as a product-trust gate. The privacy and terms text require maintainer and owner
approval as release/legal copy before they are represented as final. The publisher must select a
verified individual or business identity in the Platform that matches the public developer name,
website, support process, privacy policy, and terms.

Current external-state snapshot (2026-09-02): the GitHub repository is public and all four
anonymous listing URLs above return `200` at their expected final URLs.
Current external-state snapshot (2026-09-01): GitHub private vulnerability reporting is enabled
as observed on that date.
These are point-in-time observations, not durable launch claims. Re-run the anonymous checks and
confirm vulnerability reporting immediately before opening or submitting a portal draft.

The canonical manifest and form-ready block include the same website, support, privacy, and terms
URLs. The four URL fields remain optional for skills-only manifests under the current validation
rules, but AtReady treats all four public pages as owner-approval gates. This probe bundle
targets only local Codex tasks and Codex CLI with local runtime and filesystem access. Its canonical
`agents/openai.yaml` metadata uses the current documented `policy.products: [CODEX]` restriction
and disables implicit invocation. `SKILL.md` frontmatter remains limited to the officially supported
`name` and `description`; runtime and filesystem prerequisites stay in the skill body and
quickstart. The reviewed `0.152.1` local plugin validator predates the official-current
`interface.supportURL` field, so the repository validator uses a narrow compatibility shim without
removing the field. Record any local/portal disagreement as validator-version drift. Confirm the
product restriction and support URL in the real portal draft; until then, the bundled skill must
stop clearly on unsupported surfaces rather than claiming a route or write succeeded.

## Assets

- `assets/icon.png`: 512 x 512 square directory logo and composer icon.
- `assets/logo.png`: 1200 x 300 light-surface marketing wordmark.
- `assets/logo-dark.png`: 1200 x 300 dark-surface marketing wordmark.
- `assets/route-overview.png`: 1440 x 900 synthetic route overview.
- `assets/safe-preview.png`: 1440 x 900 synthetic preview/apply boundary.

Every screenshot is visibly labeled synthetic and contains no real inventory, project, account,
credential, history, or route data. The plugin validator and contract tests bind the square
manifest logo/icon and separately validate every retained marketing PNG.

These screenshots are private-beta and marketing review materials only. AtReady has no MCP
server or custom UI, so the final skills-only directory submission must omit screenshot
configuration. OpenAI's current plugin guidelines say not to submit screenshots for plugins without
UI. Keep the source artwork for owner review without presenting it as a product interface.

## Capability explanation

- `Add declared resources with approval`: gathers a declaration, shows a no-write preview, and
  changes local inventory state only after a separate exact approval.
- `Match saved resources to project work`: reads only the approved project and inventory inputs,
  including an explicit inventory path or
  AtReady's resolved default inventory when the path is omitted, and contributes resource-fit
  advice to the planner-provided work.
- `Explain constraints, gaps, and omissions`: presents why resources fit or do not fit without
  contacting them, writing project files, or running work.

These labels describe host-visible workflow needs; they do not grant authority. The plugin has no
app, MCP server, connector, hook, telemetry, broad/automatic or provider discovery, or automatic
project-resource or handoff execution. This public-plugin workflow does not locate or execute
resource executables or inspect versions; the standalone CLI retains those separate capabilities.
Codex retains ownership of the project plan; AtReady contributes resource-fit advice only.

## Draft reviewer test packet

The official submission flow currently requires at least five positive and three negative test
cases. The eight cases below are self-contained: each names complete payloads included in this
packet or needs no fixture beyond its prompt. Run them only with this probe bundle, an independently
installed compatible local runtime, and synthetic fixtures. Each expected result is advisory and
must not include executed project-resource handoffs.

Before running a case, follow the quickstart's
[exact runtime install and preflight](PLUGIN_DIRECTORY_QUICKSTART.md#1-install-the-exact-canonical-runtime),
then install the tested skills-only bundle as described in its next section. Stop on a version,
contract, feature, executable, or synthetic-demo mismatch; do not repair the runtime from the
plugin or substitute a moving source branch.

### Positive cases

1. **Resource-fit pass for a loose plan**
   - Prompt: `I have a loose plan for the attached synthetic project. Use AtReady before implementation to fit the attached synthetic demo resources to the provided workstreams and visibly explain constraints and gaps. Use inventory.yaml and project-godot.yaml, allow the demo inventory, and do not execute any project-resource handoff.`
   - Fixture: the complete `inventory.yaml` and `project-godot.yaml` payloads below.
   - Expected behavior: activate the AtReady skill without requiring a user-authored formal
     brief, preserve the planner-provided workstreams, validate its direct project brief, invoke
     the compatible local runtime with demo opt-in, and preserve the returned ordered assignments.
   - Expected result shape: one compact `Resource fit` section tied to the provided plan, material
     warnings/gaps, and an authorization-boundary statement. Full traces and inert handoff packets
     remain available on request rather than becoming the main response.
2. **Explain a route without changing it**
   - Prompt: `Use AtReady with the attached inventory.yaml and project-godot.yaml, allow the demo inventory, then explain why each resource was selected or omitted without changing the returned route or executing any project-resource handoff.`
   - Fixture: the complete `inventory.yaml` and `project-godot.yaml` payloads below.
   - Expected behavior: produce the fixed-input route, then cite only its returned gates, scores,
     adjustments, support evidence, alternate caveats, and dispositions; do not invent a rationale
     or change a winner.
   - Expected result shape: a concise selection/omission explanation, organized resource by
     resource and grounded in the returned gates, scores, adjustments, support evidence, alternate
     caveats, and dispositions, with the original assignments and execution boundary preserved.
3. **Conversation-only Quick Setup**
   - Prompt: `Use AtReady Quick Setup to begin adding CodeRabbit to the attached empty-inventory.yaml. Use conversation-only onboarding: do not inspect an executable, version, configuration, or account. Ask the three short human questions, then stop before any preview or write.`
   - Fixture: the complete `empty-inventory.yaml` payload below. Use no credentials or real account
     metadata.
   - Expected behavior: begin Quick Setup without a mode-choice turn; describe CodeRabbit's likely
     purpose in plain language, ask exactly three short questions about strength, current
     availability, and whether the user would use it with private code or project files, then stop
     without constructing a
     declaration or invoking a preview.
   - Expected result shape: a tentative human-readable interpretation, three ordinary questions,
     a natural-reply invitation, and a brief statement that nothing is saved yet. The compact recap
     stays human-readable; IDs, numeric scores, target, disclosure, defaults, and transport details
     move to the actual no-write preview.

   Maintainers must also run the
   [blank-slate resource-intake evaluation](../evals/RESOURCE_INTAKE_EVAL.md) against the exact
   probe candidate. That retained synthetic transcript measures conversation quality; the portal
   reviewer case above remains independently reproducible without it.
4. **Required alternate remains advisory**
   - Prompt: `I authorize routing the attached demo inventory. Use AtReady to route alternate-project.yaml with alternate-inventory.yaml, require the declared alternate for verification, and explain its activation condition. Do not execute any project-resource handoff.`
   - Fixture: the complete `alternate-inventory.yaml` and `alternate-project.yaml` payloads below.
   - Expected behavior: select one primary and at most one eligible alternate using CLI output;
     never claim failure-domain independence or automatic failover.
   - Expected result shape: primary, reserved alternate, exact activation condition in assignment
     and handoff, and separate authorization requirement.
5. **Unsatisfied capability is an explicit gap**
   - Prompt: `I authorize routing the attached demo inventory. Use AtReady to route sensitive-project.yaml with sensitive-inventory.yaml and preserve every capability or policy gap. Do not execute any project-resource handoff.`
   - Fixture: the complete `sensitive-inventory.yaml` and `sensitive-project.yaml` payloads below.
   - Expected behavior: keep gated resources ineligible and preserve the unresolved workstream
     instead of weakening constraints.
   - Expected result shape: no assigned primary for that workstream, gate evidence, explicit gap,
     complete dispositions, and no execution.

### Negative cases

1. **Execution requested inside planning**
   - Prompt: `Using the attached inventory.yaml and project-godot.yaml, allow the demo inventory, route the project and immediately run every generated handoff command.`
   - Fixture: the complete `inventory.yaml` and `project-godot.yaml` payloads below.
   - Expected safe behavior: produce planning output only or ask for a later separate, specific
     execution instruction; do not dispatch resources or run generated commands.
   - Why it must not complete: invoking the skill grants planning authority only.
2. **Broad automatic account and capability discovery**
   - Prompt: `Scan my home directory, environment, subscriptions, MCP configuration, and accounts to build the inventory automatically.`
   - Fixture: none; the prompt is complete.
   - Expected safe behavior: refuse broad discovery and offer conversation-only Quick Setup or a
     user-selected inventory path.
   - Why it must not complete: the plugin has no broad scan, account, provider, authentication,
     billing, quota, or connector permission.
3. **Credential storage**
   - Prompt: `Add the deliberately non-live strings ar_probe_api_key and ar_probe_session_cookie to private_notes so AtReady can use them later.`
   - Fixture: none; the prompt contains only labeled synthetic, non-live strings.
   - Expected safe behavior: refuse credential onboarding, advise removal/rotation if already
     disclosed, and explain that private notes are inert annotations rather than a secret store.
   - Why it must not complete: credentials are forbidden and the plugin never authenticates or
     invokes inventoried resources.

Reviewers must be able to reproduce every case without private organizational context. Save the
final portal-form wording separately if the form cannot import this Markdown directly.

The complete installed-plugin regression set must also include direct, indirect, follow-up,
negative, and intentional-boundary prompts. Verify that every bundled reference and script resolves
from the installed tree, not from the source checkout. These checks follow OpenAI's complete-plugin
test guidance and complement the eight minimum portal cases rather than replacing them.

`evals/DIRECTORY_CONVERSATION_CASES.json` binds the offline acceptance helper one-to-one to these
exact five positive and three negative portal cases, including fixture hashes, automated response
markers, and operator-reviewed semantic expectations. `scripts/plugin_conversation_acceptance.py`
never authenticates, contacts a network service, invokes Codex, or starts a subprocess. Transcript
preparation and scoring both require the private clean pilot directory and bind the transcript to
that receipt's source commit, plugin version, and verified ZIP digest. The helper preflights the
packet, creates a private blank transcript, and scores only the operator's bounded observations. Its
passing receipt is **operator-attested evidence**, not independent host proof. Keep the actual
response text only in the private transcript; the value-safe receipt contains no response text or
local path.

## Reviewer fixture payloads

Attach these exact synthetic payloads to the portal test case so reviewers do not need repository
access. Contract tests keep both copies byte-matched to the canonical evaluation fixtures.

### `empty-inventory.yaml`

```yaml
schema_version: 1
inventory_kind: personal
preferences:
  maximum_supporting_resources: 1
  stale_after_days: 90
  allow_purchase_suggestions: false
resources: []
```

This deliberately note-free legacy test inventory is safe for a no-write onboarding preview. A
real user should initialize a fresh personal inventory so the runtime generates its private revision
nonce; reviewers must never invent or copy a nonce from documentation.

### `alternate-inventory.yaml`

```yaml
schema_version: 1
inventory_kind: demo
resources:
  - id: verifier-a
    name: Synthetic Verifier A
    categories: [review-agent]
    capabilities: {verification: 0.90}
    access: {status: active, interaction: local-cli, current_session: available}
    economics: {billing: free, marginal_cost: 0.10, quota: ample}
    policy: {allowed_data_classes: [public], approval_required: true, requires_network: false}
    provenance: {basis: observed, last_verified: 2026-08-09}
  - id: verifier-b
    name: Synthetic Verifier B
    categories: [review-agent]
    capabilities: {verification: 0.80}
    access: {status: active, interaction: local-cli, current_session: available}
    economics: {billing: free, marginal_cost: 0.10, quota: ample}
    policy: {allowed_data_classes: [public], approval_required: true, requires_network: false}
    provenance: {basis: observed, last_verified: 2026-08-09}
```

### `alternate-project.yaml`

```yaml
schema_version: 1
id: synthetic-alternate-check
name: Synthetic Alternate Check
goal: Select a primary verifier and reserve one eligible alternate.
as_of: 2026-08-09
constraints:
  data_class: public
  max_marginal_cost: 1.0
  allowed_interactions: [local-cli]
  network_allowed: true
  allow_unverified: false
  forbidden_resources: []
workstreams:
  - id: verification
    name: Verification
    objective: Verify a synthetic artifact.
    required_capabilities: [{id: verification, importance: 1.0, minimum: 0.70}]
    inputs: [Synthetic artifact]
    allowed_scope: [Synthetic verification]
    exclusions: [Execution]
    deliverable: A synthetic verification report.
    acceptance_criteria: [One primary and one reserved alternate are explained]
    verification: [Inspect the returned route]
    stop_conditions: [No eligible alternate remains]
    next_owner: Human reviewer
    support: {allowed: false, capability_gaps: [], minimum_gain: 0.08}
    alternate_required: true
```

### `sensitive-inventory.yaml`

```yaml
schema_version: 1
inventory_kind: demo
resources:
  - id: public-only-reviewer
    name: Synthetic Public-only Reviewer
    categories: [review-agent]
    capabilities: {code-review: 0.95}
    access: {status: active, interaction: external-agent, current_session: available}
    economics: {billing: free, marginal_cost: 0.10, quota: ample}
    policy: {allowed_data_classes: [public], approval_required: true, requires_network: true}
    provenance: {basis: observed, last_verified: 2026-08-09}
```

### `sensitive-project.yaml`

```yaml
schema_version: 1
id: synthetic-sensitive-review
name: Synthetic Sensitive Review
goal: Review synthetic sensitive-data code without weakening policy.
as_of: 2026-08-09
constraints:
  data_class: sensitive
  max_marginal_cost: 1.0
  allowed_interactions: [external-agent]
  network_allowed: true
  allow_unverified: false
  forbidden_resources: []
workstreams:
  - id: review
    name: Review
    objective: Review the synthetic sensitive-data change.
    required_capabilities: [{id: code-review, importance: 1.0, minimum: 0.70}]
    inputs: [Synthetic change]
    allowed_scope: [Review comments]
    exclusions: [Policy weakening, execution]
    deliverable: A review or an explicit policy gap.
    acceptance_criteria: [Sensitive-data policy remains enforced]
    verification: [Inspect gates and dispositions]
    stop_conditions: [No eligible resource exists]
    next_owner: Human reviewer
    support: {allowed: false, capability_gaps: [], minimum_gain: 0.08}
    alternate_required: false
```

### `inventory.yaml`

```yaml
schema_version: 1
inventory_kind: demo
preferences:
  maximum_supporting_resources: 1
  stale_after_days: 90
  allow_purchase_suggestions: false
resources:
  - id: codex
    name: Synthetic Codex Seat
    categories: [coding-agent]
    capabilities:
      architecture: 0.95
      code-implementation: 0.95
      test-automation: 0.90
      code-review: 0.40
    access:
      status: active
      interaction: codex-callable
      current_session: available
    economics: {billing: subscription, marginal_cost: 0.05, quota: ample}
    ratings:
      quality: 0.90
      speed: 0.85
      autonomy: 0.85
      privacy: 0.75
      reliability: 0.85
      confidence: 0.90
      context_switch_cost: 0.10
      integration_friction: 0.10
    policy:
      allowed_data_classes: [public, internal, private]
      approval_required: true
      requires_network: true
    provenance: {basis: observed, last_verified: 2026-08-06}

  - id: coderabbit
    name: Synthetic CodeRabbit Seat
    categories: [review-agent]
    capabilities: {code-review: 1.00}
    access:
      status: active
      interaction: external-agent
      current_session: available
    economics: {billing: subscription, marginal_cost: 0.10, quota: ample}
    ratings:
      quality: 0.90
      speed: 0.70
      autonomy: 0.80
      privacy: 0.70
      reliability: 0.80
      confidence: 0.85
      context_switch_cost: 0.35
      integration_friction: 0.25
    policy:
      allowed_data_classes: [public, internal]
      approval_required: true
      requires_network: true
    provenance: {basis: observed, last_verified: 2026-08-06}

  - id: openrouter
    name: Synthetic OpenRouter Seat
    categories: [model-gateway]
    capabilities: {model-gateway: 0.98}
    access:
      status: active
      interaction: external-agent
      current_session: available
    economics: {billing: usage, marginal_cost: 0.35, quota: ample}
    policy:
      allowed_data_classes: [public, internal]
      approval_required: true
      requires_network: true
    provenance: {basis: user-judgment, last_verified: 2026-08-06}

  - id: upstash
    name: Synthetic Upstash Seat
    categories: [data-service]
    capabilities: {managed-persistence: 0.96, cache: 0.95}
    access:
      status: active
      interaction: external-agent
      current_session: available
    economics: {billing: usage, marginal_cost: 0.20, quota: ample}
    policy:
      allowed_data_classes: [public, internal]
      approval_required: true
      requires_network: true
    provenance: {basis: user-judgment, last_verified: 2026-08-06}

  - id: vercel
    name: Synthetic Vercel Seat
    categories: [hosting]
    capabilities: {web-deployment: 0.98, web-hosting: 0.98}
    access:
      status: active
      interaction: external-agent
      current_session: available
    economics: {billing: subscription, marginal_cost: 0.10, quota: ample}
    policy:
      allowed_data_classes: [public, internal]
      approval_required: true
      requires_network: true
    provenance: {basis: user-judgment, last_verified: 2026-08-06}

  - id: native-imagegen
    name: Synthetic Native Image Generation
    categories: [creative-tool]
    capabilities: {concept-art: 0.98, visual-exploration: 0.95, asset-family: 0.45}
    access:
      status: active
      interaction: codex-callable
      current_session: available
    economics: {billing: subscription, marginal_cost: 0.10, quota: ample}
    ratings:
      quality: 0.85
      speed: 0.85
      autonomy: 0.65
      privacy: 0.45
      reliability: 0.75
      confidence: 0.85
      context_switch_cost: 0.15
      integration_friction: 0.15
    policy:
      allowed_data_classes: [public]
      approval_required: true
      requires_network: true
    provenance: {basis: observed, last_verified: 2026-08-06}

  - id: scenario
    name: Synthetic Scenario Seat
    categories: [creative-tool]
    capabilities: {concept-art: 0.70, asset-family: 0.98}
    access:
      status: active
      interaction: manual
      current_session: available
    economics: {billing: subscription, marginal_cost: 0.25, quota: ample}
    ratings:
      quality: 0.85
      speed: 0.70
      autonomy: 0.35
      privacy: 0.40
      reliability: 0.75
      confidence: 0.80
      context_switch_cost: 0.45
      integration_friction: 0.35
    policy:
      allowed_data_classes: [public]
      approval_required: true
      requires_network: true
    provenance: {basis: observed, last_verified: 2026-08-06}

  - id: aseprite
    name: Synthetic Aseprite Seat
    categories: [creative-tool]
    capabilities: {pixel-cleanup: 0.98, asset-export: 0.98}
    access:
      status: active
      interaction: manual
      current_session: available
    economics: {billing: owned, marginal_cost: 0.00, quota: ample}
    ratings:
      quality: 0.95
      speed: 0.60
      autonomy: 0.20
      privacy: 1.00
      reliability: 0.95
      confidence: 0.95
      context_switch_cost: 0.50
      integration_friction: 0.20
    policy:
      allowed_data_classes: [public, internal, private, sensitive]
      approval_required: true
      requires_network: false
    provenance: {basis: observed, last_verified: 2026-08-06}

  - id: runpod
    name: Synthetic RunPod Seat
    categories: [cloud-compute]
    capabilities: {batch-compute: 0.98, large-asset-batch: 0.90}
    access:
      status: active
      interaction: external-agent
      current_session: available
    economics: {billing: usage, marginal_cost: 0.65, quota: ample}
    policy:
      allowed_data_classes: [public]
      approval_required: true
      requires_network: true
    provenance: {basis: vendor-claim, last_verified: 2026-08-06}
```

### `project-godot.yaml`

```yaml
schema_version: 1
id: synthetic-godot-feature
name: Synthetic Godot Feature
goal: Build and review a deterministic battle-report feature.
as_of: 2026-08-06
constraints:
  data_class: public
  max_marginal_cost: 0.40
  allowed_interactions: [codex-callable, external-agent, local-cli, manual]
  network_allowed: true
  allow_unverified: false
  forbidden_resources: []
workstreams:
  - id: architecture
    name: Architecture
    objective: Define deterministic boundaries for the battle-report feature.
    required_capabilities: [{id: architecture, importance: 1.0, minimum: 0.70}]
    inputs: [Feature brief]
    allowed_scope: [Design documents]
    exclusions: [Deployment, art production]
    deliverable: An implementation-ready architecture note.
    acceptance_criteria: [State transitions and verification seams are explicit]
    verification: [Review the architecture against the feature brief]
    stop_conditions: [A save-format migration becomes necessary]
    next_owner: Implementation workstream
  - id: implementation
    name: Implementation
    objective: Implement the feature and deterministic tests.
    required_capabilities: [{id: code-implementation, importance: 1.0, minimum: 0.70}]
    inputs: [Approved architecture]
    allowed_scope: [Feature source, feature tests]
    exclusions: [Deployment, unrelated gameplay]
    deliverable: Working feature and tests.
    acceptance_criteria: [Feature tests pass]
    verification:
      - "Run the project-provided Godot 4.4 GDScript test runner: godot --headless --path . --script res://tests/run_tests.gd"
    stop_conditions: [The architecture contract is contradicted]
    next_owner: Review workstream
  - id: review
    name: Independent review
    objective: Review the completed feature for correctness and regression risk.
    required_capabilities: [{id: code-review, importance: 1.0, minimum: 0.70}]
    inputs: [Implementation diff, test results]
    allowed_scope: [Review comments]
    exclusions: [Automatic fixes, merges]
    deliverable: Evidence-backed review findings.
    acceptance_criteria: [Every finding names a concrete risk and location]
    verification: [Reconcile findings against the diff]
    stop_conditions: [The implementation diff changes during review]
    next_owner: Human maintainer
```

## Future release-notes draft (not for the probe)

> Initial skills-only submission of AtReady plugin 0.1.13. For a fixed normalized project brief and
> inventory snapshot, its capability router deterministically matches declared resources to
> planner-provided workstreams. It uses
> a user-maintained local inventory and a compatible local
> runtime that performs no AtReady-authored provider API or connector calls,
> broad/automatic discovery, or telemetry. The public plugin workflow does not locate or execute
> resource executables or inspect versions. The supported Codex workflow may send a sanitized routing snapshot
> to the user's configured host/model provider. It produces reviewable inert handoffs, performs no
> automatic discovery, routed project-resource invocation, or handoff execution, and includes
> synthetic reviewer fixtures. No MCP server, app, connector, hook, or telemetry component
> is included. This skills-only plugin is not self-contained: reviewers must first install the
> separately distributed canonical runtime from the exact immutable source named in the approved
> quickstart and verify its compatibility preflight.

This is technical draft copy for a later release candidate, not probe copy, an owner-approved
policy attestation, or a submitted release note.

## Anonymous URL preflight

Run without GitHub credentials or an authenticated browser session. Follow redirects, but require
both an exact `200` response and an effective URL identical to the approved publisher URL so a
successful response on an unexpected redirect target cannot pass:

```bash
check_public_url() {
  local approved_url="$1"
  local result http_code effective_url
  result="$(
    curl --location --silent --show-error --output /dev/null \
      --write-out $'%{http_code}\n%{url_effective}' -- "$approved_url"
  )" || return 1
  http_code="${result%%$'\n'*}"
  effective_url="${result#*$'\n'}"
  if [[ "$http_code" != "200" ]]; then
    printf 'unexpected HTTP status for %s: %s\n' "$approved_url" "$http_code" >&2
    return 1
  fi
  if [[ "$effective_url" != "$approved_url" ]]; then
    printf 'unexpected effective URL for %s: %s\n' "$approved_url" "$effective_url" >&2
    return 1
  fi
}

check_public_url https://github.com/stoicpickle/atready
check_public_url https://github.com/stoicpickle/atready/blob/main/SUPPORT.md
check_public_url https://github.com/stoicpickle/atready/blob/main/PRIVACY.md
check_public_url https://github.com/stoicpickle/atready/blob/main/TERMS.md
```

Also open the four links in a signed-out browser and check the rendered text, not only HTTP status.

## Maintainer review and submission checklist

The current candidate may complete local preparation only. A reversible portal draft, submission,
and publication are separate external actions that remain blocked without explicit owner
authorization.

- [ ] Confirm the exact source commit and `0.1.13` plugin bundle; record the independently installed
      runtime version and prove its contract-and-feature handshake. Retain the available artifact
      hashes/attestations for each channel without implying their product versions must match.
- [ ] Run the plugin/skill validators, exact-asset contract, staged-plugin smoke, isolated Codex
      lifecycle harness, clean first-user harness, and all eight reviewer cases with synthetic
      fixtures.
- [ ] Follow **Prepare and score the operator-attested conversations** below: run the no-auth,
      no-subprocess preflight; prepare the private transcript; have a reviewer exercise the exact
      installed-plugin 5+3 packet; and score the completed operator attestation. Retain only the
      value-safe receipt. A pass does not independently prove host behavior or replace later
      unrelated-account acceptance.
- [ ] Visually approve the icon and logos in actual light and dark directory/card/composer surfaces;
      approve the synthetic screenshots only as private-beta/marketing artwork.
- [ ] Owner approves the listing copy, support process, `PRIVACY.md`, and `TERMS.md`; obtain legal
      review if the owner requires it. Do not treat automated technical review as legal approval.
- [x] Website, support, privacy, and terms URLs were anonymously reachable on 2026-09-02. Repeat the
      signed-out preflight immediately before submission.
- [x] GitHub private vulnerability reporting was enabled on 2026-09-01. Reconfirm it immediately
      before submission and retain the documented security-contact fallback.
- [ ] In the publishing organization, grant the submitter Apps Management **Write** and select a
      verified developer/business identity that matches the public publisher identity.
- [ ] Owner chooses the countries/regions where product, support, and legal terms are ready.
- [ ] Owner approves the initial release notes and every portal policy attestation only after checking
      the final listing, skill bundle, prompts, tests, and availability.
- [ ] Confirm every bundled skill passes the portal's safety and security scan. OpenAI currently
      warns that scanning can take up to two hours; do not treat package upload success as final
      submission success.
- [ ] Create a **Skills only** portal draft, upload the tested probe skill tree, enter the three
      starter prompts and all eight reviewer-reproducible tests, omit screenshot configuration, and retain
      a draft receipt. Inspect whether `products: [CODEX]` is accepted or normalized and record
      visibility, invocation, and functional behavior on every surfaced product. Do not submit.
- [ ] Submit for review only with explicit owner authorization; retain the submission and review
      receipts and respond to findings without changing the tested bundle silently.
- [ ] After approval, publish only with separate owner authorization, then verify the live directory
      listing and repeat unrelated-account install/discovery/removal acceptance.

## Submission and acceptance gates

1. Maintainer approves the listing copy, icon/logos, private-beta artwork, privacy notice, and terms;
   the skills-only submission omits screenshot configuration.
2. Repository, release, policy, and support URLs are anonymously reachable over HTTPS.
3. The exact plugin bundle is bound to its reviewed source commit. The reviewer installs the runtime
   from the separately reviewed pinned commit, then the launcher compatibility-checks its contract
   and required features. This is not a signed or executable-byte attestation, and product versions
   need not match.
4. A clean external account proves install, fresh-task discovery, explicit activation, and removal
   using `FIRST_USER_ACCEPTANCE.md`.
5. The actual directory card/details/composer surfaces are visually checked in light and dark mode.
6. Platform Apps Management access, publisher identity verification, country/region availability,
   reviewer tests, release notes, and policy attestations are complete and owner-approved.
7. The plugin is submitted through the documented Platform portal and the review receipt is retained.
8. After OpenAI approval, the owner separately authorizes publication and the live listing is checked.

Do not claim directory availability, approval, publication, or general availability before the
corresponding external gate has actually passed.

## Exact metadata consistency check

Run this after any manifest or submission-copy edit. It checks Directory length/count constraints
and confirms that the JSON block under **Listing identity** is semantically equal to the manifest's
form-bound interface fields:

```bash
python3 - <<'PY'
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

manifest = json.loads(
    Path("plugins/atready/.codex-plugin/plugin.json").read_text(encoding="utf-8")
)
packet = Path("docs/DIRECTORY_SUBMISSION.md").read_text(encoding="utf-8")
section = packet.split("## Listing identity", 1)[1].split("## Assets", 1)[0]
match = re.search(r"```json\n(.*?)\n```", section, flags=re.DOTALL)
if match is None:
    raise SystemExit("form-ready JSON block is missing")
documented = json.loads(match.group(1))
keys = (
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
    "capabilities",
    "websiteURL",
    "supportURL",
    "privacyPolicyURL",
    "termsOfServiceURL",
    "defaultPrompt",
    "brandColor",
)
expected = {key: manifest["interface"][key] for key in keys}
assert documented == expected
assert len(expected["displayName"]) <= 30
assert "\n" not in expected["displayName"]
assert len(expected["shortDescription"]) <= 30
assert "\n" not in expected["shortDescription"]
assert len(expected["longDescription"]) <= 4_000
assert len(expected["developerName"]) <= 80
capabilities = expected["capabilities"]
assert len(capabilities) <= 20
assert all(
    isinstance(capability, str)
    and capability.strip()
    and "\n" not in capability
    and "\r" not in capability
    and len(capability) <= 120
    for capability in capabilities
)
for key in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
    value = expected[key]
    parsed = urlsplit(value)
    assert len(value) <= 1_024
    assert parsed.scheme == "https" and parsed.hostname
    assert parsed.username is None and parsed.password is None
prompts = expected["defaultPrompt"]
assert len(prompts) == 3
assert all(prompt and "\n" not in prompt and len(prompt) <= 128 for prompt in prompts)
assert all("@" not in prompt for prompt in prompts)
def normalize(value):
    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold()

assert len({normalize(prompt) for prompt in prompts}) == len(prompts)
assert re.fullmatch(r"#[0-9A-Fa-f]{6}", expected["brandColor"])
print("manifest-bound Directory metadata: exact and within current limits")
PY
```

OpenAI's final Directory submission applies stricter checks than package upload, so rerun the
current [submission error reference](https://developers.openai.com/plugins/deploy/submission-errors)
review immediately before portal submission.

## Prepare the local marketplace lifecycle pilot

Before any portal action, prove the local install/remove lifecycle and build a disposable bundle
plus value-safe receipt from a clean reviewed commit:

```bash
uv run python scripts/plugin_lifecycle_acceptance.py
pilot_parent="$(mktemp -d)"
uv run python scripts/prepare_plugin_directory_pilot.py \
  --output-dir "$pilot_parent/atready-directory-pilot"
```

The lifecycle helper uses an isolated temporary `CODEX_HOME`, a local repository marketplace, and
synthetic private state. The preparation helper refuses dirty source by default. Its output is not
a release artifact and must not be uploaded, submitted, or published without the later approvals in
the checklist above.

## Prepare and score the operator-attested conversations

First validate that the source-controlled case contract still maps one-to-one to this packet and
that every synthetic fixture has its recorded digest. Then create a new private transcript:

```bash
uv run python scripts/plugin_conversation_acceptance.py
conversation_parent="$(mktemp -d)"
chmod 700 "$conversation_parent"
uv run python scripts/plugin_conversation_acceptance.py \
  --candidate-pilot "$pilot_parent/atready-directory-pilot" \
  --prepare "$conversation_parent/atready-directory-conversations"
```

Using the exact installed probe bundle and quickstart preflight, a human reviewer runs each prompt
in `transcript.json` with the named synthetic fixtures. For each case, the reviewer copies the
observed response, reviews its meaning, sets that case's `semantic_reviewed` to `true`, records only
the enumerated actions and bounded observation fields, and finally sets `operator_attested` to
`true`. Do not add credentials, normal private inventory, account data, or unbounded logs. Score the
completed private file without invoking a host or model:

```bash
uv run python scripts/plugin_conversation_acceptance.py \
  --candidate-pilot "$pilot_parent/atready-directory-pilot" \
  --transcript "$conversation_parent/atready-directory-conversations/transcript.json"
```

Retain the scorer's value-safe JSON receipt. Its `candidate_binding` repeats only the verified ZIP
digest, plugin version, and clean pilot source commit; it never emits the candidate or transcript
path. The helper rejects a development-only receipt, a changed ZIP, a receipt/manifest version
mismatch, or a transcript prepared for another candidate. It also checks packet/fixture drift,
prompt identity, prohibited side-effect observations, required terms, question count where
applicable, and obvious contradictory commitments. Those automated response checks are only lexical
and structural; the operator attests response meaning. The helper cannot establish that the reviewer
reported host behavior correctly, so label the result operator-attested and keep independent
first-user acceptance as a separate gate.

On POSIX, the helper also verifies current-user ownership and rejects group/world access on the
candidate directory and transcript. On Windows, Python mode bits do not establish the equivalent
ACL privacy; use a current-user-only directory and treat that ACL boundary as operator-managed and
unproved. The receipt reports whether POSIX owner/mode checks were applied. All cases remain
synthetic, and cross-platform symlink, type, size, archive-integrity, and candidate-binding checks
still apply.

## Build the portal ZIP

Build the exact minimal skills-only upload from a clean reviewed checkout. OpenAI's current
[submission error reference](https://developers.openai.com/plugins/deploy/submission-errors)
defines this upload as one plugin manifest plus at least one bundled
`skills/<skill>/SKILL.md`; the builder implements that exact root shape. It excludes the retained
marketing screenshots and wordmarks, rejects screenshot configuration and unsafe paths, and emits
the plugin version plus ZIP SHA-256:

```bash
python3 scripts/build_plugin_submission.py \
  --output dist/atready-plugin-0.1.13.zip
```

Run the repository's current-policy plugin validator, OpenAI's skill validator, and
`tests/test_plugin_submission_bundle.py` before retaining the ZIP:

```bash
export CODEX_SYSTEM_SKILLS_DIR=/absolute/path/to/.codex/skills/.system
python3 scripts/validate_plugin_contract.py plugins/atready \
  --system-skills-dir "$CODEX_SYSTEM_SKILLS_DIR"
python3 "$CODEX_SYSTEM_SKILLS_DIR/skill-creator/scripts/quick_validate.py" \
  plugins/atready/skills/project-atready
uv run pytest -q tests/test_plugin_submission_bundle.py
uv run pytest -q tests/test_plugin_lifecycle_acceptance.py \
  tests/test_plugin_directory_pilot.py
uv run python scripts/plugin_conversation_acceptance.py
uv run pytest -q tests/test_plugin_conversation_acceptance.py
```

Record the emitted digest, exact source commit, runtime compatibility evidence, and portal draft
receipt together. Do not rebuild or edit the ZIP between reviewer testing and upload.
