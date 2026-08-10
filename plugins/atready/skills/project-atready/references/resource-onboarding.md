# Guided Resource Onboarding

Use this branch when a personal inventory is empty or the user explicitly asks to onboard one or
more resources. The conversation may accept a list; keep additional resources in a names-only
queue. Complete and write one resource at a time; never combine declarations or preview/apply
authorization.

## 1. Resolve the contract and default to Assisted Setup

Resolve the explicit or default inventory target read-only. Before asking intake questions, invoke
the pinned bundled launcher with `schema resource-declaration` exactly once for this onboarding
task. Reuse that result when building the declaration; do not query the schema again unless the
launcher's reported runtime contract or required feature set changes, or the task is restarted.

If the user explicitly says Quick Setup or Assisted Setup, begin without asking them to choose a
mode. Present the default path to users as **Quick Setup**; `Assisted Setup` remains the internal
contract and evaluation name. If they ask generally to add or onboard resources, default to Quick
Setup and mention in one sentence that Detailed Setup remains available; do not spend a turn on a
mode choice. Use Detailed Setup (the internal Advanced Setup branch) only when the user requests it,
supplies a complete declaration, or rejects the assisted defaults.

In the same response as the intake card, identify the target and explain that preview output exposes
every routing-visible field to the terminal, host, logs, and potentially the configured model
provider. A general planning or `preview-first` request permits questions and states a desired
sequence; it is not authorization for an exact declaration preview or write.

Never infer access, authentication, session state, billing, quota, verification, capabilities, or
ratings from a product name, installation, subscription claim, or nearby configuration. Accept
`unknown` where the schema permits it. State that unknown or stale access, session, quota, or
provenance normally makes the resource unverified for routing.

**Quick Setup** collects one short, mostly prefilled human-language card and proposes every
remaining conservative default. **Detailed Setup** reviews every routing, scoring, policy,
provenance, capacity, and handoff field. Both add exactly one resource, require separate preview and
save approvals, perform no account or provider discovery, and never authorize routed project work.

Completion criterion: the contract was queried once, the target is resolved, and the chosen or
default intake depth is known without an extra mode-choice turn.

## 2. Optional catalog profile

Before questions, use the pinned launcher as the source of truth for the current local profile
catalog. `resource profiles --json` lists the bounded built-in profiles. `resource profile
<profile-id> --json` shows catalog version `1` and the selected profile's editable category,
capability, capacity-unit, and model-routing proposals. Catalog values are never inventory facts.

The public plugin workflow is conversation-only and performs no local executable or version
inspection. Those standalone CLI capabilities remain outside this public-plugin candidate. If no profile matches or several
match, use generic Quick Setup and require the user to confirm every proposal.

### CodeRabbit Quick Setup

When the selected catalog profile is exactly `coderabbit`, use a tailored four-group card instead
of reducing CodeRabbit to a generic service. Show these catalog values as editable proposals:

- `CodeRabbit` with stable ID `coderabbit`;
- `Code review agent (review-agent)`;
- `Code review (code-review)` and `Repository analysis (repository-analysis)`, with a separate
  strength requested for each; and
- capacity hints `Review requests (review-request)` and `Files reviewed (review-file)`.

Recognize these user-facing usage modes inside the single **Readiness** group:

- **CLI:** ask whether the user or Codex runs CodeRabbit from a terminal, whether that path is
  usable for this task now, and how and when they checked. Map to `codex-callable` only when the
  user says Codex can call it here; otherwise map a terminal workflow to `local-cli`.
- **PR reviews:** ask whether the user relies on the pull-request app/bot, whether they declare it
  enabled for the relevant repositories and able to review a new PR now, and how and when they
  checked. Map this path to `external-agent`.
- **Both:** ask which path should be the one routing-visible `interaction` for this entry. State in
  the recap that the other path is confirmed context but is not independently selectable by the
  router. If both paths need independent readiness, policy, or capacity, offer to queue
  `coderabbit-cli` and `coderabbit-pr` as two separately confirmed resources after this entry;
  never combine their previews or saves.

Tailor capacity to the chosen path without assuming a plan or limit. For PR reviews, ask for
remaining review requests, the full limit, any repository/project allocation, reset date, basis,
and verification date when known. For CLI use, accept the profile's `review-request` or
`review-file` unit, or the user's exact unit. Preserve `not sure` and qualitative room when no
measured amount is known. A single resource stores one measured-capacity envelope; when CLI and PR
limits differ, ask which limit governs this entry or offer the two-entry queue. Never convert or
combine unlike units.

Render this provider-specific card after the boundary opening in section 3. Keep it under the same
250-word limit and render exactly these four visible question bullets:

> **Proposed:** `CodeRabbit (coderabbit)` · `Code review agent (review-agent)` · `Code review
> (code-review)` and `Repository analysis (repository-analysis)`
>
> **Confirm or correct:**
> - **Identity:** accept or edit the proposed name, stable ID, category, and both capability labels.
> - **Strengths:** rate code review and repository analysis separately as basic, solid, strong,
>   exceptional, or an exact 0.0-1.0 score.
> - **Readiness:** choose CLI, PR reviews, or both; identify the primary path if both; say who can
>   use it now, usage room or a measured limit, and how and when those facts were checked.
> - **Safety:** say which project data it may receive and whether use requires internet access.
>
> I will keep billing unknown, use baseline comparison scores, ask before use, prepare a manual
> text handoff, and add no private note. I will rely on your declared readiness rather than checking
> the executable, version, configuration, or account.
>
> **Easy reply:** `identity: accept/change; strengths: code review strong, repository analysis
> solid; readiness: CLI / PR reviews / both, primary path if both, access yes, available yes, usage
> some or measured, checked today; safety: internal, internet yes; defaults and target: accept`

Treat every answer as a declaration to recap, not provider evidence. Keep all profile labels,
strengths, usage mode, readiness, capacity, safety, and defaults editable. No onboarding answer
authorizes a CodeRabbit review, pull request, login, installation, update, settings change,
provider contact, declaration preview, or roster save.

### OpenCode Quick Setup

When the selected profile is exactly `opencode`, keep the card focused on facts that change a
project plan. Show these catalog values as editable proposals:

- `OpenCode` with stable ID `opencode`;
- `Coding agent (coding-agent)`;
- `Code implementation (code-implementation)`, `Code review (code-review)`, `Repository analysis
  (repository-analysis)`, and `Software planning (software-planning)`, each rated separately; and
- capacity hints `Agent tasks (agent-task)`, `Tokens (token)`, and `Provider credits (credit)`.

Ask which one routing-visible workflow applies: an interactive terminal session (`local-cli`), a
separately authorized non-interactive CLI task (`codex-callable`), or person-mediated desktop/IDE
use (`manual`). The official surfaces and commands justify these proposals, but do not establish
that this user's installation, configured provider, model, permissions, or current session is
ready. Ask about the underlying model/provider only when it materially changes the user's declared
capability, cost, or capacity; never request or retain its API key or other credential.

Render exactly these four visible question bullets in the existing Quick Setup card:

> **Proposed:** `OpenCode (opencode)` · `Coding agent (coding-agent)` · `Code implementation
> (code-implementation)`, `Code review (code-review)`, `Repository analysis
> (repository-analysis)`, and `Software planning (software-planning)`
>
> **Confirm or correct:**
> - **Identity:** accept or edit the proposed name, stable ID, category, and capability labels.
> - **Strengths:** rate only the work your configured OpenCode setup actually handles well.
> - **Readiness:** choose terminal, separately authorized CLI, or desktop/IDE; say who can use it
>   now, its qualitative room or exact provider-governed limit, and how and when you checked.
> - **Safety:** say which project data and actions it may receive and whether use requires internet.
>
> I will keep billing unknown, use baseline comparison scores, ask before use, prepare a manual
> text handoff, and add no private note. I will rely on your declared readiness rather than checking
> installation, configuration, providers, models, or an account.
>
> **Easy reply:** `identity: accept/change; strengths: implementation strong, review solid,
> analysis strong, planning solid; readiness: terminal / delegated CLI / desktop or IDE, access yes,
> available yes, usage some or measured, checked today; safety: internal, internet yes; defaults
> and target: accept`

Treat model choice and configuration as context for the user's ratings, not as an additional
resource automatically. If a separately routable model or provider has materially different
strengths, readiness, policy, or capacity, offer to queue it as its own one-resource setup later.
The catalog reviewed on 2026-08-09 may expose a temporary `DeepSeek V4 Flash Free` suggestion.
Present it as a catalog-listed OpenCode Zen option under review, never as OpenCode's universal
default, and require the user to confirm current access, data policy, and observed fit.
No onboarding answer authorizes OpenCode execution, provider access, model enumeration,
configuration changes, declaration preview, or roster save.

### Pixel-art tool Quick Setup profiles

When the exact profile is `pixellab` or `retro-diffusion`, use the same four-group Quick Setup card
and keep the creative resource secondary to the user's project goal. Show catalog capabilities and
workflow modes as editable proposals. Ask the user to score only the asset work their configured
surface actually handles well. Do not inspect a project gallery, provider account, authentication,
purchase history, subscription, credit balance, API configuration, or credentials.

- **PixelLab (`pixellab`):** ask whether the routing-visible surface is the person-mediated web
  creator, browser editor, Aseprite extension, or a separately configured API integration. Propose
  pixel-art generation, sprite generation and animation, pixel-art editing, and map generation.
  Catalog review on 2026-08-09 lists Pixel Apprentice with 2,000 images per month up to 320x320 and
  Pixel Artisan with 5,000 images per month up to 512x512 plus up to 10 concurrent jobs, and Pixel
  Architect with 10,000 images per month plus up to 20 concurrent background jobs. Present the tier,
  limits, dimensions, and concurrency only as dated vendor proposals; require the user to confirm
  their actual tier, current availability, and useful fit.
- **Retro Diffusion (`retro-diffusion`):** first distinguish the credit-based cloud website or a
  separately configured website API from the one-time-purchase local Aseprite extension. Catalog
  review on 2026-08-09 found no website subscription: cloud use consumes purchased credits, while
  the separately owned local extension has no website-credit balance. If the user calls it a
  subscription, explain the catalog distinction and ask which product they actually have rather
  than silently correcting their declaration. Propose pixel-art and sprite generation, animation,
  pixel-art editing, and palette editing for confirmation.

For either cloud surface, ask the user to check the provider themselves and declare one governing
capacity unit: images or credits for PixelLab, generations or credits for Retro Diffusion. Record
the exact remaining amount, optional full limit/project allocation/reset date, basis, and checked
date only when supplied. Retro Diffusion's catalog says website credits do not expire and that
larger images can cost more than one credit; confirm the no-expiry rule before omitting a reset and
never translate a credit balance into a fixed image count. State that AtReady keeps a
point-in-time snapshot only: it does not refresh or decrement balances. A later balance change is a
complete `inventory replace` request with a new preview and save approval.

No tier, product surface, declared balance, or catalog proposal authorizes API use, asset
generation, account access, declaration preview, roster save, or any provider action.

### Other coding-agent Quick Setup profiles

Use the same compact four-group card for these exact profiles, while preserving each profile's
editable capability and workflow proposals:

- **Cursor (`cursor`):** propose code implementation, code review, repository analysis, and
  software planning. Ask whether the routing-visible workflow is the person-mediated editor,
  interactive CLI, separately authorized headless CLI, or a separately configured Cloud Agent.
  Its dated model suggestions may include Composer 2.5 for cost-efficient agentic coding and
  Cursor Grok 4.5 for hard long-running coding and knowledge work. Both are unverified proposals
  and may share one Cursor Models capacity pool.
- **Claude Code (`claude-code`):** propose code implementation, code review, repository analysis,
  and software planning. Ask whether the workflow is interactive terminal, separately authorized
  headless use, person-mediated IDE/desktop/web, or separately configured CI.
- **Google Antigravity (`antigravity`):** propose code implementation, repository analysis,
  software planning, multi-agent orchestration, and research. Ask whether the workflow is terminal,
  separately authorized headless use, person-mediated desktop/IDE, or separately configured
  background agents.
- **GitHub Copilot (`github-copilot`):** propose code implementation, code review, debugging,
  repository analysis, software planning, and GitHub workflow support. Ask whether the workflow is
  interactive terminal, separately authorized programmatic use, coding-agent delegation, or
  person-mediated editor/app.
- **Grok (`grok`):** propose research, analysis, software planning, and code review. Ask whether the
  surface is the person-mediated Grok app/web experience or a separately configured xAI API
  workflow. Its dated Grok 4.5 suggestion is for complex reasoning across code and knowledge work,
  but the user's scores, access, policy, and exact surface remain unverified.

For each profile, render one card with exactly four visible bullets:

> **Proposed:** `<profile name and stable ID>` · `Coding agent (coding-agent)` · `<the profile's
> editable capability proposals>`
>
> **Confirm or correct:**
> - **Identity:** accept or edit the proposed name, stable ID, category, and capability labels.
> - **Strengths:** rate only the work this configured setup actually handles well.
> - **Readiness:** choose one routing-visible workflow; say who can use it now, qualitative room or
>   one exact governing limit, and how and when those facts were checked.
> - **Safety:** say which project or repository data and actions it may receive and whether use
>   requires internet.
>
> I will keep billing unknown, use baseline comparison scores, ask before use, prepare a manual
> text handoff, and add no private note. I will rely on your declared readiness rather than checking
> installation, configuration, models, providers, authentication, billing, quota, or an account.
>
> **Easy reply:** `identity: accept/change; strengths: implementation strong, review solid,
> analysis strong, planning solid; readiness: choose one listed workflow, access yes, available
> yes, usage some or measured, checked today; safety: internal, internet yes; defaults and target:
> accept`

Ask about a backing model or plan only when it materially changes declared capability, cost,
capacity, policy, or readiness. Do not automatically create a second model/provider resource. If a
backing provider is independently routable with materially different facts, offer to queue it for
its own later preview and save.

No profile lookup or onboarding answer authorizes login, account or usage inspection, repository
analysis, file changes, shell commands, cloud/background delegation, model selection, provider
contact, declaration preview, or roster save. Never inspect Cursor rules or dashboard state,
Claude files or instructions, Antigravity projects/settings/usage, Copilot plugins/policy/usage, any
credential store, or environment-variable values.

### Model-aware resource variants

When a selected profile contains `model_routing_suggestions`, read
[model-routing.md](model-routing.md). Show the review date, named model option, suggested resource
ID, planning role, caution, and any shared-capacity group as editable proposals. Ask whether the
user can actually select that model on the named surface now.

Keep the provider metadata to one compact line before the existing four-bullet card: review date,
model and proposed resource ID, one short role phrase, one short caution, and an optional shared-pool
label. Do not paste the full catalog record or repeat generic provider boundaries in every bullet.
The entire first response still stays under 250 words and presents only the current queue item.

Keep one generic provider resource when the configured model is automatic, unknown, or immaterial.
When confirmed model choices are independently selectable and materially different, offer one
separate resource at a time. For example: `cursor-composer-2-5`, `cursor-grok-4-5`,
`opencode-deepseek-v4-flash-free`, or `grok-4-5`. Each requires its own user-confirmed capabilities,
scores, readiness, policy, preview, and apply approval. Never infer a score from vendor copy, a
benchmark, `Flash`, `Fast`, `Thinking`, or a model's position in a provider list.

When the user's reason for separate entries is different hard-work versus fast/cost-efficient fit,
do not invite them to accept baseline `0.5` for every differentiating input. Keep Quick Setup, but
extend its **Strengths** bullet with only the planning distinctions that justify separate entries:
the relevant capability strengths, speed, and relative marginal cost. Map `basic`, `solid`,
`strong`, and `exceptional` speed to `0.40`, `0.65`, `0.80`, and `0.95`. Map user-judged relative
cost `low`, `medium`, `high`, and `very high` to `0.25`, `0.50`, `0.75`, and `0.95`; this is not a
price, plan lookup, or vendor fact. Show every mapping in the recap and leave the other comparison
ratings at their visible baseline unless the user chooses Detailed Setup. If the user cannot rate
the differences yet, preserve the baseline and say the roster does not yet encode a model-aware
preference; never claim the dated planning role changed routing by itself.

If entries share a proposed capacity group, state that AtReady does not enforce shared-pool
consumption and never present them as independent capacity or redundancy. Cursor-hosted Grok and
standalone xAI Grok remain separate resources because their access, policy, and capacity surfaces
can differ. During planning, the deterministic router selects those declared resource entries; the
skill may explain a selected model role but must not substitute an unconfirmed model after routing.

## 3. Assisted Setup presented as Quick Setup

Use a provider-specific variant above when it applies; otherwise use the generic card in this section.
Use facts already supplied instead of asking twice. Put all four groups in one intake card. Keep the
questions friendly; show schema values only as mappings or in the later recap. Keep the first
assistant response under 250 words. Lead with the proposed useful entry, not the storage machinery.
Do not recite the full schema, internal status names, or every retention caveat in the question card.
Render exactly the four visible bullets shown below. Do not split readiness into a checklist of its
individual fields, repeat the available answer choices outside their group, or add a separate
defaults bullet. The goal is one easy reply, not a schema interview.

Open with this boundary:

> I will add one resource at a time. Nothing is saved until you approve a no-write preview and then
> approve the exact save. Do not paste credentials or private notes here. "Not sure" is valid for
> readiness facts. I will use `<canonical target>`; the visible entry will appear in this task and
> may be retained by its host, logs, or configured model provider.

Then show one compact, prefilled card in this shape, adapting known profile proposals and facts:

> **Proposed:** `<name>` · `<readable category>` · `<readable capability>` · `<strength if known>`
>
> **Confirm or correct:**
> - **Identity:** the proposed name, ID, category, and capability labels.
> - **Strength:** basic, solid, strong, exceptional, or an exact 0.0-1.0 score.
> - **Readiness:** how you use it; whether you have access and can use it now; usage room; how and
>   when you last checked.
> - **Safety:** data it may receive and whether it requires internet access.
>
> I will keep billing unknown, use baseline comparison scores, ask before use, prepare a manual
> text handoff, and add no private note. I will rely on your declared readiness rather than checking
> a CLI, app, configuration, or account. Answering supplies facts only; it does not authorize a
> preview or save.

End with the provider-specific fill-in aid above when it applies; otherwise use this compact aid.
It is a response template, not a fifth question group:

> **Easy reply:** `identity: accept/change; strength: strong; readiness: access yes, separate
> service, available yes, usage some, checked today; safety: internal, internet yes; defaults and
> target: accept`

Use these four internal groups to make sure the compact card is complete:

1. **Identity:** propose the supplied display name and a lowercase resource ID only as a proposal;
   require the user to confirm it. Explain once that the resource ID is AtReady's stable,
   machine-readable label for this entry. Propose plausible category and capability IDs for
   confirmation. Say: "These are label proposals only, not claims about your account, access, or
   what the resource can actually do." A proposal is a question, not an inferred inventory fact.
   Pair every technical ID with a readable label, such as `Review agent (review-agent)` and `Code
   review (code-review)`. Require the user to confirm or edit every proposal; never silently derive
   or persist a category or capability.
2. **Strengths:** ask, "How strong is it at each proposed capability: basic, solid, strong,
   exceptional, or an exact 0.0-1.0 score?" Map labels deterministically: `basic` -> `0.40`,
   `solid` -> `0.65`, `strong` -> `0.80`, and `exceptional` -> `0.95`. Never invent a capability or
   silently raise a score. Show both label and number in the recap.
3. **Readiness and capacity:** ask these human-language questions together:
   - "Do you currently have usable access: yes, limited, no, or not sure?"
   - "How do you use it: Codex can call it here, a terminal command, a separate app/service/bot, or
     you use it manually?"
   - "Can you use it in this task right now: yes, no, or not sure?"
   - "How much usage room remains: plenty, some, none, not sure, or a measured amount?"
   - If an amount is known, ask for its unit, the full plan limit when known, any smaller project
     allocation, any reset date, the basis for the amount, and when it was checked. Preserve the
     user's units; never compare or convert unlike units. A profile may suggest a unit label but
     never supplies a remaining amount.
   - "How do you know these facts: you checked or used it, your judgment, vendor information, or
     not sure?"
   - "When did you last check: today, YYYY-MM-DD, or not sure?"
4. **Safety:** ask, "What project data may it receive: public, internal, private, and/or sensitive?"
   Explain that public-only is the restrictive starting policy. Ask, "Does using it require
   internet access: yes or no?" If the user is unsure about network use, include it in the one
   consolidated repair instead of guessing because the stored field is Boolean.

Use these deterministic friendly mappings:

- access `yes`, `limited`, `no`, `not sure` -> `active`, `limited`, `inactive`, `unknown`;
- interaction `Codex can call it here`, `terminal command`, `separate app/service/bot`, `manual` ->
  `codex-callable`, `local-cli`, `external-agent`, `manual`;
- current use `yes`, `no`, `not sure` -> `available`, `unavailable`, `unknown`;
- usage room `plenty`, `some`, `none`, `not sure` -> `ample`, `limited`, `exhausted`, `unknown`;
- measured capacity -> `economics.capacity` with `unit`, `remaining`, optional `limit`, optional
  `project_limit`, optional `resets_on`, non-unknown `basis`, and required `last_verified`; and
- evidence `checked or used`, `my judgment`, `vendor information`, `not sure` -> `observed`,
  `user-judgment`, `vendor-claim`, `unknown`.

End the same card with one visible batch acceptance for the remaining conservative defaults:

> Accept these remaining first-pass defaults? We do not know its billing; put relative cost and the
> eight ranking comparison scores at 0.5 for now (an undecided baseline, not verified quality).
> For a model-aware entry, keep the relative cost and speed you just confirmed and put only the
> other seven comparison ratings at 0.5. Always ask before use; prepare a text handoff you copy
> manually; add no usage tips; and add no private note.

Use those human phrases in the card. Do not replace them with raw enum labels such as
`codex-callable`, `local-cli`, `user-judgment`, or `manual-prompt`; show exact schema values only in
the recap beside the user's words.

Ask the user to confirm the target and disclosure boundary in the same reply. Accept plain English
or provide one compact response template with labels, strength, access, use, available now, usage
room, basis, last checked, data, internet, remaining defaults, and target/disclosure. State:

> Answering this intake card supplies facts only; it does not authorize a preview or save.

The batch maps exactly to:

- billing `unknown`; marginal cost `0.5` unless model-aware relative cost was confirmed; and all
  eight ratings `0.5` except a confirmed model-aware speed value;
- `approval_required: true`;
- handoff method `manual-prompt` with no instructions;
- empty best/avoid advisory lists; and
- no private note.

Do not describe Assisted Setup as routing-ready. Its conservative scoring defaults may affect
ranking or cost gates, and every project still supplies its own capability, interaction, data,
network, and cost constraints.

Normalize the reply once. If required facts are missing or contradictory, ask at most one
consolidated repair question listing every blocker; never drip one field per turn. Active or limited
access without a real verification date, an unconfirmed proposal, a missing capability score, or an
unknown network Boolean is a repair item. Preserve every other unknown. If blockers remain after
that single repair, stop without previewing. Normally Assisted Setup takes one substantive intake
reply; it must never take more than one consolidated repair reply before the recap.

Completion criterion: all four groups, displayed defaults, target, and disclosure boundary are
confirmed in one intake reply or one intake plus one consolidated repair, or onboarding stops.

## 4. Advanced Setup

Accept a complete protected declaration or collect every visible field in routing-impact order.
Advanced Setup never waives recap, preview, or apply authorization:

1. **Identity and categories:** lowercase resource ID, display name, and one or more categories.
2. **Capabilities and scores:** each capability ID and an exact user-judged score from `0.0` to
   `1.0`.
3. **Access and provenance:** access, interaction mode, current session, qualitative quota,
   confidence basis, and verification date. Active or limited access requires a verification date.
4. **Policy:** allowed data classes, network requirement, and declared resource approval
   requirement.
5. **Economics:** billing label, relative marginal cost, and optional measured capacity.
6. **Eight ratings:** quality, speed, autonomy, privacy, reliability, confidence, context-switch
   cost, and integration friction.
7. **Handoff:** method and optional instructions.
8. **Best/avoid advisory text:** optional bounded human-facing descriptions, never routing rules.

When an optional visible field is omitted, show its exact schema default before the recap:

- access `unknown`, interaction `manual`, and session `unknown`;
- billing `unknown`, marginal cost `0.5`, and quota `unknown`;
- neutral `0.5` defaults for all eight ratings;
- public data only, resource approval required, and no network requirement;
- provenance `unknown` with no verification date;
- handoff method `manual-prompt` with no instructions; and
- empty best/avoid advisory lists.

Billing and best/avoid values are descriptive only: they do not gate, score, enter the routing
snapshot, or change the route fingerprint. The declared approval value is copied to selected
handoff packets but does not affect ranking. `approval_required: false` never authorizes execution
or waives the separate authorization required to run a handoff. Advanced Setup improves route
discrimination; it does not verify account access, authorize execution, or turn advisory text into
routing rules.

Completion criterion: every visible field is user-confirmed or has a displayed, accepted default.

## 5. Reuse only a task-local safety baseline

After one resource has a final receipt, offer to reuse only these confirmed values for the next
names-only queue entry in the same task:

- allowed data classes;
- declared resource approval requirement; and
- network requirement.

Label each reused value in the next recap and require per-resource confirmation. Optionally reuse a
billing label or handoff method only when the user explicitly requests it. Never reuse capabilities
or scores, access, current session, quota, provenance basis or date, marginal cost, ratings, or
private-note state or value. Do not persist a separate defaults profile or apply several resources
together.

## 6. Handle credentials and private notes without soliciting values

Never request, accept, preview, or store a credential, token, key, password, recovery code, or
session secret. If the user exposes one, do not echo it or place it in any declaration. Tell the
user to revoke or rotate it through the relevant provider outside AtReady before continuing
with metadata intake; AtReady cannot perform or verify that rotation.

In Assisted Setup, do not ask a separate private-note question: the visible remaining-defaults group
proposes `absent`, and the user's acceptance confirms that state. In Advanced Setup, or when the
user explicitly asks for a note, ask only whether a private note is desired; never ask for its value
in chat. Private notes are inert, local annotations rather than routing evidence, and credentials
belong in a credential manager. Direct the user to put a desired note into a protected versioned
declaration outside the checkout, then use the file path without reading or copying the value into
host/model context.

If the user already supplied a non-credential private-note value in chat, explain that the
disclosure has already occurred, do not echo it, and obtain explicit authorization before retaining
it in a declaration or preview operation. A legacy-unblinded inventory cannot accept notes; use the
migration boundary in the main skill rather than inserting a nonce.

Completion criterion: note state is absent, or its protected source and disclosure authorization
are explicit without the value appearing in the recap.

## 7. Recap, status, and preview authorization

Present one compact structured recap. Lead with the user's friendly answers and show their exact
schema mappings beside them. Use this order:

- **Confirmed labels:** display name, resource ID, categories, and capabilities.
- **Strength, readiness, and capacity:** each qualitative label and numeric score, access,
  interaction, current session, quota, measured amount/unit/limit/project allocation/reset when
  supplied, provenance basis, and verification date.
- **Safety:** allowed data classes and network requirement.
- **Scoring-input defaults:** marginal cost and any defaulted ratings. Do not call these universally
  neutral: a project's cost ceiling can gate the default marginal cost.
- **Conservative safety defaults:** public-only data, approval required, and no network requirement
  when those values were defaulted.
- **Descriptive and handoff defaults:** billing, handoff, and best/avoid text.
- **Private note:** only `present` or `absent`.

Assign one intake status, in this priority order:

- `declared-unavailable` when access is inactive, the current session is unavailable, or quota is
  exhausted;
- `requires-verification` when access, current session, quota, provenance basis, or verification
  date is unknown; or
- `selection-facts-declared` when those facts are declared. Strict validation and routing assess
  staleness separately against the inventory preference and project date.

Always say:

> This intake status does not prove live availability, authentication, capability, project
> eligibility, selection, or execution authority.

Then request explicit preview authorization with this human-facing copy and a compact details block:

> Ready for the no-write preview? It will show the complete `<resource>` entry in this task, use the
> roster at `<canonical target>`, and remove any temporary input afterward. It will not save
> anything. Proceed?
>
> Details: `<source transport>` · this host/model context · one resource only.

Stop for an answer. Authorization to answer questions is not preview authorization. General intent
such as `preview-first`, `show me a preview`, or `stop before apply` is not authorization for the
exact recap unless the user separately confirms this request. Do not create a declaration source
or invoke `inventory add` until that exact approval is given.

Completion criterion: the user explicitly authorizes the exact preview, or onboarding stops without
a CLI preview or write.

## 8. Preview, approve, and apply

Materialize or use the approved protected declaration according to the main skill, then invoke the
main skill's pinned bundled launcher with `inventory add` and without `--apply`. Never resolve or
invoke a same-name `atready` command from `PATH`. Show the actual CLI preview, including the
canonical target, complete routing-visible resource, grouped defaults, note presence, expected
revision, and plan token.

Stop again and ask:

> Save exactly this entry? AtReady will back up the current roster, apply this reviewed
> version, and validate it. It will not run or contact `<resource>`.

Apply only after a second explicit approval of that rendered preview. Repeat the same
semantic declaration with its exact `--expect-revision` and `--expect-plan`; a changed declaration,
target, revision, or plan requires a fresh preview. Treat an applied-but-uncertain receipt exactly
as specified in the main skill.

Do not preview or apply a second resource until the current resource has a final receipt, is
declined, or is blocked. Then take the next names-only queue entry through this workflow from the
beginning.

Completion criterion: one resource has a verified receipt, or the user receives a precise declined,
blocked, or uncertain status and no claim that another resource was onboarded.

## 9. Validate and offer progressive enrichment

After the first verified add receipt, run the pinned launcher's read-only `inventory validate
--strict` against the explicit target. Report unknown or stale warnings as selection-fact gaps, not
as storage failure.

Close a successful receipt and strict validation with:

> `<resource>` is saved and the roster validates. AtReady can now consider it in future plans;
> no routed project resource was contacted or run. Next: add another resource, plan with the roster,
> or finish.

Only when the user explicitly asks to test the new entry, offer a separate synthetic route check.
Explain that, for one fixed normalized project brief and inventory snapshot, it tests schema and
deterministic routing wiring with a made-up public project and
creates inert handoff text for review without contacting the resource, sending it data, dispatching
the handoff, or executing routed project work. Do not create the temporary project or invoke `route` without
that separate, explicit route authorization. If authorized, follow the main skill's protected
temporary-project and cleanup rules. Describe the result only as a check of schema and fixed-input
deterministic routing wiring, never as proof of conversational interpretation, real-world
usefulness, access, or fitness.

Explain that a Quick Setup entry can be enriched later through `inventory replace` with Detailed
Setup.
Replacement is a complete same-ID declaration, not a merge: omitted fields take defaults and an
omitted private note is removed. It requires a new complete recap, preview authorization, rendered
preview, and apply approval.
