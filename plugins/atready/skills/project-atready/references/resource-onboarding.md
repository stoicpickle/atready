# Guided Resource Onboarding

Use this branch when a personal inventory is empty or the user explicitly asks to onboard one or
more resources. The conversation may accept a list; keep additional resources in a names-only
queue. Complete and write one resource at a time; never combine declarations or preview/apply
authorization.

## 1. Resolve the contract and default to Assisted Setup

If the user has not supplied a resource name, ask only:

> What resource do you want to add?
>
> A name is enough to start. Do not include passwords, API keys, or private notes.

Stop after that question. Do not invoke the launcher, resolve the target, inspect the roster, show
the intake card, explain setup modes, or expose defaults, disclosure details, or a fill-in template.
This name-first turn must stay under 35 words. If initialization just completed, do not repeat its
target or safety explanation.

After the resource name is known, resolve the explicit or default inventory target read-only.

Before asking the three intake questions, invoke the pinned bundled launcher with
`schema resource-declaration` exactly once for this onboarding
task. Reuse that result when building the declaration; do not query the schema again unless the
launcher's reported runtime contract or required feature set changes, or the task is restarted.

If the user explicitly says Quick Setup or Assisted Setup, begin without asking them to choose a
mode. Present the default path to users as **Quick Setup**; `Assisted Setup` remains the internal
contract and evaluation name. If they ask generally to add or onboard resources, default to Quick
Setup without explaining modes. Use Detailed Setup (the internal Advanced Setup branch) only when
the user requests it, supplies a complete declaration, or rejects the assisted defaults.

Once the resource is known, keep the canonical target and short disclosure line for the actual
no-write preview. A general planning or `preview-first`
request permits questions and states a desired sequence; it is not authorization for an exact
declaration preview or write.

Never infer access, authentication, session state, billing, quota, verification, capabilities, or
ratings from a product name, installation, subscription claim, or nearby configuration. Accept
`unknown` where the schema permits it. State that unknown or stale access, session, quota, or
provenance normally makes the resource unverified for routing.

**Quick Setup** hides the data model. After the name, it proposes a likely purpose and asks no more
than three ordinary-language questions in one turn. The user may answer naturally; no mini-language
or fill-in template is required. **Detailed Setup** exposes every routing, scoring, policy,
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
inspection. Those standalone CLI capabilities remain outside this public-plugin candidate. If no
profile matches or several match, use generic Quick Setup, propose a plain-language purpose, and put
technical proposals in the actual preview for correction before save.

### CodeRabbit Quick Setup

When the selected catalog profile is exactly `coderabbit`, use a tailored Quick Setup card with at
most three questions instead of reducing CodeRabbit to a generic service. Show these catalog
values as editable proposals:

- `CodeRabbit` with stable ID `coderabbit`;
- `Code review agent (review-agent)`;
- `Code review (code-review)` and `Repository analysis (repository-analysis)`; and
- capacity hints `Review requests (review-request)` and `Files reviewed (review-file)`.

Recognize these user-facing usage modes only when the user volunteers one. Otherwise put the
profile's conservative workflow proposal in the actual preview for correction; never add provider-specific
questions:

- **CLI:** determine whether the user or Codex runs CodeRabbit from a terminal and whether that path
  is usable for this task now. Map to `codex-callable` only when the
  user says Codex can call it here; otherwise map a terminal workflow to `local-cli`.
- **PR reviews:** determine whether the user relies on the pull-request app/bot and declares it
  enabled for the relevant repositories and able to review a new PR now, and how and when they
  checked. Map this path to `external-agent`.
- **Both:** use the primary path named in a volunteered answer as the one routing-visible
  `interaction`. State in
  the actual preview that the other path is confirmed context but is not independently selectable by the
  router. If both paths need independent readiness, policy, or capacity, offer to queue
  `coderabbit-cli` and `coderabbit-pr` as two separately confirmed resources after this entry;
  never combine their previews or saves. If the user volunteers both paths without naming a
  primary one, do not choose either interaction. Keep the interaction unconfirmed and stop before
  preview, or offer the two-resource split and save neither entry until the user explicitly
  confirms it.

Tailor volunteered capacity to the chosen path without assuming a plan or limit. For PR reviews,
accept remaining review requests, the full limit, any repository/project allocation, reset date,
basis, and verification date when supplied. For CLI use, accept the profile's `review-request` or
`review-file` unit, or the user's exact unit. Preserve `not sure` and qualitative room when no
measured amount is known. A single resource stores one measured-capacity envelope; when CLI and PR
limits differ, use the primary path's limit or offer the two-entry queue in the recap. Never convert
or combine unlike units. Persist a numeric remaining amount only with a non-unknown evidence basis
and `last_verified` date. If either is absent, omit measured `economics.capacity`; the stated amount
may appear only as an unpersisted preview proposal until the user supplies both facts. Never invent
capacity provenance or a date.

Render this provider-specific card in the short shape from section 3. Keep it under 100 words and
ask only the unanswered subset in the displayed order. The bare-name template has all three
visible bullets. Keep stable IDs, schema labels, numeric scores, capacity fields, defaults, target,
transport, and disclosure details for the actual preview:

> **Got it: CodeRabbit.** I would tentatively treat it as a code-review service for code review and
> pull-request feedback.
>
> - How strong is it for that work: basic, solid, strong, or exceptional?
> - Is it available to you now?
> - Would you use it with private code or project files?
>
> Reply naturally, and correct my tentative purpose if needed. "Not sure" is fine. I will show you
> what I understood before anything is saved.

Treat every answer as a declaration, not provider evidence. Keep all profile labels, strengths,
usage mode, readiness, capacity, safety, and defaults editable in the actual preview. No onboarding answer
authorizes a CodeRabbit review, pull request, login, installation, update, settings change,
provider contact, declaration preview, or roster save.
Rely on the user's declared readiness; do not inspect an executable, version, configuration, or account.

### OpenCode Quick Setup

When the selected profile is exactly `opencode`, keep the card focused on facts that change a
project plan. Show these catalog values as editable proposals:

- `OpenCode` with stable ID `opencode`;
- `Coding agent (coding-agent)`;
- `Code implementation (code-implementation)`, `Code review (code-review)`, `Repository analysis
  (repository-analysis)`, and `Software planning (software-planning)`; and
- capacity hints `Agent tasks (agent-task)`, `Tokens (token)`, and `Provider credits (credit)`.

When the user volunteers a workflow, recognize an interactive terminal session (`local-cli`), a
separately authorized non-interactive CLI task (`codex-callable`), or person-mediated desktop/IDE
use (`manual`). Otherwise propose `manual` in the actual preview for correction. The official surfaces and
commands justify these proposals, but do not establish
that this user's installation, configured provider, model, permissions, or current session is
ready. Treat any voluntarily named underlying model/provider as context only; never request or
retain its API key or other credential.

Ask only the unanswered subset in the displayed order in the existing Quick Setup card, keeping
the whole response under 100 words. The bare-name template has all three visible bullets. Keep
stable IDs, schema labels, numeric scores, capacity fields, defaults, target, transport, and
disclosure details for the actual preview:

> **Got it: OpenCode.** I would tentatively treat it as a coding agent for implementation, review,
> repository analysis, and software planning.
>
> - How strong is it for that work: basic, solid, strong, or exceptional?
> - Is it available to you now?
> - Would you use it with private code or project files?
>
> Reply naturally, and correct my tentative purpose if needed. "Not sure" is fine. I will show you
> what I understood before anything is saved.

Treat model choice and configuration as context for the user's ratings, not as an additional
resource automatically. If a separately routable model or provider has materially different
strengths, readiness, policy, or capacity, offer to queue it as its own one-resource setup later.
The catalog reviewed on 2026-08-09 may expose a temporary `DeepSeek V4 Flash Free` suggestion.
Present it as a catalog-listed OpenCode Zen option under review, never as OpenCode's universal
default. Put its access, data-policy, and fit proposals in the actual preview for correction.
No onboarding answer authorizes OpenCode execution, provider access, model enumeration,
configuration changes, declaration preview, or roster save.
Rely on the user's declared readiness; do not inspect installation, configuration, providers,
models, or an account.

### Pixel-art tool Quick Setup profiles

When the exact profile is `pixellab` or `retro-diffusion`, use the same Quick Setup card with at
most three unanswered questions and keep the creative resource secondary to the user's project goal. Show catalog capabilities and
workflow modes as editable proposals in the actual preview. Apply the first question's one strength only to
the plain-language asset purpose the user affirms. Do not inspect a project gallery, provider account, authentication,
purchase history, subscription, credit balance, API configuration, or credentials.

- **PixelLab (`pixellab`):** when supplied, recognize the routing-visible surface as the person-mediated web
  creator, browser editor, Aseprite extension, or a separately configured API integration. Propose
  pixel-art generation, sprite generation and animation, pixel-art editing, and map generation.
  Catalog review on 2026-08-09 lists Pixel Apprentice with 2,000 images per month up to 320x320 and
  Pixel Artisan with 5,000 images per month up to 512x512 plus up to 10 concurrent jobs, and Pixel
  Architect with 10,000 images per month plus up to 20 concurrent background jobs. Present the tier,
  limits, dimensions, and concurrency only as dated vendor proposals in the actual preview; never treat a
  catalog tier as the user's actual tier.
- **Retro Diffusion (`retro-diffusion`):** first distinguish the credit-based cloud website or a
  separately configured website API from the one-time-purchase local Aseprite extension. Catalog
  review on 2026-08-09 found no website subscription: cloud use consumes purchased credits, while
  the separately owned local extension has no website-credit balance. If the user calls it a
  subscription, explain the catalog distinction inside the tentative purpose and let the user say
  which product they actually have rather
  than silently correcting their declaration. Propose pixel-art and sprite generation, animation,
  pixel-art editing, and palette editing for confirmation.

For either cloud surface, accept one governing capacity unit when the user volunteers it: images or
credits for PixelLab, generations or credits for Retro Diffusion. Record
the exact remaining amount, optional full limit/project allocation/reset date, basis, and checked
date only when supplied. Retro Diffusion's catalog says website credits do not expire and that
larger images can cost more than one credit; use no-expiry only when the user volunteers
confirmation, and never translate a credit balance into a fixed image count. State that AtReady keeps a
point-in-time snapshot only: it does not refresh or decrement balances. A later balance change is a
complete `inventory replace` request with a new preview and save approval.

No tier, product surface, declared balance, or catalog proposal authorizes API use, asset
generation, account access, declaration preview, roster save, or any provider action.

### Other coding-agent Quick Setup profiles

Use the same compact card with at most three unanswered questions for these exact profiles, while preserving each profile's
editable capability and workflow proposals:

- **Cursor (`cursor`):** propose code implementation, code review, repository analysis, and
  software planning. Put the person-mediated editor, interactive CLI, separately authorized
  headless CLI, and separately configured Cloud Agent workflows in the actual preview for correction.
  Its dated model suggestions may include Composer 2.5 for cost-efficient agentic coding and
  Cursor Grok 4.5 for hard long-running coding and knowledge work. Both are unverified proposals
  and may share one Cursor Models capacity pool.
- **Claude Code (`claude-code`):** propose code implementation, code review, repository analysis,
  and software planning. Put interactive terminal, separately authorized headless use,
  person-mediated IDE/desktop/web, and separately configured CI in the actual preview for correction.
- **Google Antigravity (`antigravity`):** propose code implementation, repository analysis,
  software planning, multi-agent orchestration, and research. Put terminal, separately authorized
  headless use, person-mediated desktop/IDE, and separately configured background-agent workflows
  in the actual preview for correction.
- **GitHub Copilot (`github-copilot`):** propose code implementation, code review, debugging,
  repository analysis, software planning, and GitHub workflow support. Put interactive terminal,
  separately authorized programmatic use, coding-agent delegation, and person-mediated editor/app
  in the actual preview for correction.
- **Grok (`grok`):** propose research, analysis, software planning, and code review. Put the
  person-mediated Grok app/web and separately configured xAI API workflows in the actual preview for
  correction. Its dated Grok 4.5 suggestion is for complex reasoning across code and knowledge work,
  but the user's scores, access, policy, and exact surface remain unverified.

For each profile, render one card with only the unanswered subset of the three bullets in the
displayed order and keep it under 100 words. A bare-name request shows all three. Keep stable IDs,
schema labels, numeric scores, defaults, target, transport, and disclosure details for the actual
preview:

> **Got it: `<profile name>`.** I would tentatively treat it as a coding agent for `<plain-language
> capability proposals>`.
>
> - How strong is it for that work: basic, solid, strong, or exceptional?
> - Is it available to you now?
> - Would you use it with private code or project files?
>
> Reply naturally, and correct my tentative purpose if needed. "Not sure" is fine. I will show you
> what I understood before anything is saved.

Do not ask about a backing model or plan in Quick Setup. Do not automatically create a second
model/provider resource. If the user voluntarily names an independently routable backing provider
with materially different facts, offer to queue it for its own later preview and save.
Rely on the user's declared readiness; do not inspect installation, configuration, models,
providers, authentication, billing, quota, or an account.

No profile lookup or onboarding answer authorizes login, account or usage inspection, repository
analysis, file changes, shell commands, cloud/background delegation, model selection, provider
contact, declaration preview, or roster save. Never inspect Cursor rules or dashboard state,
Claude files or instructions, Antigravity projects/settings/usage, Copilot plugins/policy/usage, any
credential store, or environment-variable values.

### Model-aware resource variants

When a selected profile contains `model_routing_suggestions`, read
[model-routing.md](model-routing.md). Mention only the named model and a plain-language tentative
role before the three-question card. Put the review date, suggested resource ID, caution, and any
shared-capacity group in the actual preview as editable proposals. The availability question applies to the
named model on the named surface; do not add a selection or workflow question.

Keep the question-turn provider metadata to one compact line: model name and one short role phrase.
Do not paste the full catalog record or repeat generic provider boundaries in every question.
The entire first response still stays under 250 words and presents only the current queue item.

Keep one generic provider resource when the configured model is automatic, unknown, or immaterial.
When confirmed model choices are independently selectable and materially different, offer one
separate resource at a time. For example: `cursor-composer-2-5`, `cursor-grok-4-5`,
`opencode-deepseek-v4-flash-free`, or `grok-4-5`. Each requires its own user-confirmed capabilities,
scores, readiness, policy, preview, and apply approval. Never infer a score from vendor copy, a
benchmark, `Flash`, `Fast`, `Thinking`, or a model's position in a provider list.

When the user's reason for separate entries is different hard-work versus fast/cost-efficient fit,
apply the first question's one qualitative answer only to the capability the user affirmed. Keep
speed, relative marginal cost, and the other comparison ratings at the visible `0.5` baseline in
the actual preview. Offer Detailed Setup after the first resource when the user wants those distinctions to
affect routing. Never claim the dated planning role changed routing by itself.

If entries share a proposed capacity group, state that AtReady does not enforce shared-pool
consumption and never present them as independent capacity or redundancy. Cursor-hosted Grok and
standalone xAI Grok remain separate resources because their access, policy, and capacity surfaces
can differ. During planning, the deterministic router selects those declared resource entries; the
skill may explain a selected model role but must not substitute an unconfirmed model after routing.

## 3. Assisted Setup presented as Quick Setup

Use a provider-specific variant above when it applies; otherwise use the generic card in this section.
Use facts already supplied instead of asking twice. Ask only the unanswered subset of the three
visible questions in one turn; a bare-name request gets all three. Keep the complete card under 100 words. Lead with a tentative plain-language purpose, not
storage machinery. Stable IDs, schema labels, numeric scores, defaults, target path, declaration
transport, and disclosure details belong only in the actual preview. The goal is one natural reply, not
a schema interview.

Then show one compact, prefilled card in this shape, adapting known profile proposals and facts:

> **Got it: `<name>`.** I would tentatively treat it as `<plain-language category>` for
> `<plain-language capability proposals>`.
>
> - How strong is it for that work: basic, solid, strong, or exceptional?
> - Is it available to you now?
> - Would you use it with private code or project files?
>
> Reply naturally, and correct my tentative purpose if needed. "Not sure" is fine. I will show you
> what I understood before anything is saved.

Interpret the natural reply internally without expanding the visible card:

1. **Purpose and strength:** the catalog or model may propose a readable category and capabilities,
   but the user confirms or corrects the useful purpose. Apply one qualitative strength to the
   stated purpose unless the user naturally distinguishes capabilities. Map `basic` -> `0.40`,
   `solid` -> `0.65`, `strong` -> `0.80`, and `exceptional` -> `0.95`. Keep the number invisible
   until the actual preview. Never invent a capability or silently raise a score.
2. **Availability and use:** map yes, no, or not sure only to the current session or current-use
   field. Keep account access `unknown` unless the user explicitly declares it. When the user does
   not volunteer a workflow, propose person-mediated `manual` use in the actual preview for correction.
   A statement that the resource is available now is a current user declaration: use
   `user-judgment` and the current date unless they provide stronger evidence or another date. Keep
   quota `unknown` unless the user volunteers qualitative or measured room. For a measured amount,
   preserve the supplied unit and any supplied limit, allocation, reset, basis, and checked date;
   never compare or convert unlike units.
3. **Data and network:** map the user's data answer to allowed data classes. Treat a simple yes to
   using it with private code or project files as `public`, `internal`, and `private`. Map an
   explicit no or not sure to `public` only. Preserve sensitive-data permission as unknown unless
   the user explicitly confirms it; until then, `sensitive` remains excluded from the allowed
   list. Infer network use only from the confirmed workflow itself, such as a separate cloud
   service; otherwise use the conservative no-network default and display it for correction in the
   actual preview. This answer configures only the inventoried resource's routing policy. It does
   not authorize loading private project content into this conversation or its configured
   host/model; that remains a separate per-project disclosure decision.
4. **Identity:** prepare a lowercase resource ID and plausible category and capability IDs as
   editable serialization proposals. Never claim they prove account access or product capability.
   Pair every technical ID with a readable label in the actual preview, where the user can correct
   them before save authorization. Do not expose them in Quick Setup questions or the compact recap.

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

Keep conservative defaults out of the question card and compact recap. Materialize them internally
for the no-write preview, where the user can inspect every exact value before save approval. The
preview is the technical audit surface; the recap is only a human confirmation of intent.

Use the user's phrases when interpreting the reply. Exact schema values, target, transport, and
disclosure appear in the actual CLI preview, not the Quick Setup recap. Before the recap, state:

> Answering this intake card supplies facts only; it does not authorize a preview or save.

The batch maps exactly to:

- billing `unknown`, marginal cost `0.5`, and all eight ratings `0.5`;
- `approval_required: true`;
- handoff method `manual-prompt` with no instructions;
- empty best/avoid advisory lists; and
- no private note.

Do not describe Assisted Setup as routing-ready. Its conservative scoring defaults may affect
ranking or cost gates, and every project still supplies its own capability, interaction, data,
network, and cost constraints.

Normalize the reply once. Preserve unknown optional facts instead of interviewing for them. If a
contradiction prevents a valid declaration, show it in the recap and stop before preview until the
user corrects it naturally; never add a fourth Quick Setup question.

Completion criterion: one name-first turn and no more than three Quick Setup questions produce a
compact human recap before preview authorization; the actual preview carries the technical record.

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

## 7. Recap, revise, and preview

For Quick Setup, render no more than 110 words in this shape:

> **Here's what I'll add**
>
> **`<resource>`** for `<plain-language purpose>`
>
> - **Strength:** `<qualitative strength>`
> - **Available now:** `<Yes / No / Not sure>`
> - **Private work:** `<Allowed / Not allowed / Not sure>`
> - **Still unknown:** `<only routing-material unknowns, or omit this line>`
>
> It will be previewed against `<human-readable selected-roster label>`. Nothing has been saved.
>
> **Preview this entry?**

Do not add an `AtReady details` block. Keep IDs, numeric mappings, category and capability labels,
provenance, billing, comparison ratings, handoff defaults, empty fields, exact target, transport,
and disclosure for the actual CLI preview. Do not present an inferred workflow or network default
as user-confirmed. Detailed Setup may use a complete structured recap because the user requested
field-level control.

Derive the recap's roster label from the resolved destination without revealing its path: use
`your personal AtReady roster` only for the configured personal roster, and use `the selected
AtReady roster` for an explicit custom or evaluation target. Preserve the exact target only for the
actual CLI preview.

Assign one intake status, in this priority order:

- `declared-unavailable` when access is inactive, the current session is unavailable, or quota is
  exhausted;
- `requires-verification` when access, current session, quota, provenance basis, or verification
  date is unknown; or
- `selection-facts-declared` when those facts are declared. Strict validation and routing assess
  staleness separately against the inventory preference and project date.

Express status through `Still unknown` only when it matters to routing. For example: `Usage limits,
so AtReady will mark this as needing verification.` Keep the exact internal status and its detailed
limitations for the actual CLI preview.

When the user permits private work but has not explicitly addressed sensitive data, include
`Sensitive-data permission; sensitive work remains excluded until you confirm it` under `Still
unknown` in the compact recap and repeat that statement immediately before the actual CLI preview.
The preview's allowed-data list remains the enforceable routing policy. If the user explicitly
narrows the allowed classes, treat omitted higher-sensitivity classes as excluded rather than
unknown.

Treat any correction as facts, not approval. Apply only the requested edits, recompute dependent
mappings and status, render the entire compact recap again, and ask `Preview this entry?` again.
Do not repeat answered intake questions. Even when one message contains both an edit and preview
language, stop at the revised recap; approval must follow the latest displayed version. Repeat this
loop until the user approves or cancels.

Authorization to answer questions or edit the recap is not preview authorization. General intent
such as `preview-first`, `show me a preview`, or `stop before apply` is not approval of the latest
displayed recap. Do not create a declaration source or invoke `inventory add` until the user
explicitly approves that latest recap.

Completion criterion: the user explicitly approves the latest displayed recap for preview, or
onboarding stops without a CLI preview or write.

## 8. Preview, approve, and apply

Materialize or use the approved protected declaration according to the main skill, then invoke the
main skill's pinned bundled launcher with `inventory add` and without `--apply`. Never resolve or
invoke a same-name `atready` command from `PATH`. Show the actual CLI preview, including the
canonical target, complete routing-visible resource, grouped defaults, note presence, expected
revision, and plan token.

Stop again and ask:

> Save exactly this entry? AtReady will back up the current roster, apply this reviewed
> version, and validate it. It will not run or contact `<resource>`.

If the user corrects the rendered preview instead of saving it, treat the correction as facts only.
Return to the compact recap with the edits applied, then require fresh preview approval and render a
new CLI preview. Never patch or save the old preview.

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
