# Data model

All public contracts use `schema_version: 1`, reject unknown fields, and can be emitted as JSON
Schema with `atready schema inventory`, `atready schema project`,
`atready schema resource-declaration`, and `atready schema route-plan`.

## Inventory

An inventory requires an explicit `inventory_kind` of `personal` or `demo`, contains global routing
preferences, and may begin with no resources. Empty state is valid for onboarding but cannot
produce a route. Demo state is read-only and requires explicit route opt-in. The demo label and
resource contents are user-controlled declarations, not proof that the facts are synthetic or
represent personal access. Each resource separates:

- identity, categories, and scored capabilities;
- declared access from current-session availability;
- billing model, relative marginal cost, qualitative quota state, and optional unit-aware capacity;
- the exact eight ratings `quality`, `speed`, `autonomy`, `privacy`, `reliability`, `confidence`,
  `context_switch_cost`, and `integration_friction`;
- allowed data classes and network/approval policy;
- confidence basis and `last_verified` date;
- inert handoff method and guidance, which are preserved in assigned packets;
- optional local-only `private_notes`, which are inert annotations and never routing evidence.

The deterministic router uses capabilities, access/session state, marginal cost/quota, ratings,
allowed data classes, network requirements, and provenance. Billing model and best/avoid text are
persisted descriptive metadata but do not gate, score, enter the routing snapshot, or change its
fingerprint. Best/avoid items are bounded, display-safe text rather than workstream matching rules.
`approval_required` does not gate or score; it is copied into every selected-role handoff as a
declared external prerequisite. A false value never authorizes execution or removes AtReady's
separate user-authorization boundary. Private notes are excluded even from the snapshot; critical
routing facts must not live only there.

Current `init` writes a root `revision_privacy_nonce` with the exact versioned shape
`nonce-v1:<64-lowercase-hex>`. It is generated once from 32 CSPRNG bytes and is not a model default;
parsing and planning remain deterministic. The field is optional only so legacy note-free
inventories remain readable. Any non-null inventory/resource `private_notes`, including an empty
string, requires a nonce. Validation never inserts or rotates one.

Private notes and the nonce are excluded from routing inventory fingerprints and sanitized
snapshots. Credential fields are forbidden. Inventory listing exposes the SHA-256 revision of the
complete raw file and a value-free protection status but omits private notes and the nonce value.
Resource add/replace previews show every routing-visible persisted resource field and actual
default; replacement shows redacted before/after values and the private-note effect. Remove previews
show the exact redacted resource, note presence, and count change. Note values, excerpts, lengths,
direct note hashes, and the nonce are omitted. Their plan tokens bind the operation, canonical
physical target, inspected
target/parent identities, original full-byte revision, and candidate revision. The nonce remains in
those exact bytes, blinding note guesses while undisclosed. Applying an accepted preview serializes
and revalidates the entire nested inventory, canonicalizes YAML, and preserves the exact previous
bytes as a private backup.

The value-free state `nonce-v1-present` proves syntax and presence only. It does not prove that an
imported value was randomly generated, unique, or undisclosed.

## Resource declaration

Argv-safe structured onboarding accepts exactly one direct envelope:

```yaml
schema_version: 1
resource:
  id: local-tool
  name: Local Tool
  categories: [coding-agent]
  capabilities:
    code-implementation: 0.9
```

The `resource` value is the complete `Resource` contract, including optional
handoff/best/avoid fields and `private_notes`. A bare resource, inventory, list,
batch, merge document, second YAML document, unknown field, or unknown version
fails closed. JSON is accepted as a YAML subset. Input transport, pathname,
comments, and key order are not persisted or plan-bound; the fully validated,
default-materialized candidate is. Semantically identical file/stdin declarations
therefore produce the same candidate, while any changed persisted value—including
a hidden note—requires a new preview. A note-bearing declaration also fails when
the target inventory is `legacy-unblinded`; the nonce is inventory state and is
never accepted through a resource declaration.

Add and replace previews also derive an `intake_review` from the already validated, plan-bound
candidate. It groups omitted selection facts, scoring inputs, conservative policy, and operating
context; identifies declared unknown or unavailable access/session/quota/provenance facts; and
always reports `route_eligibility_evaluated: false`. The review is explanatory output, not an
additional persisted or authorization-bearing input. Project requirements, capability fit, cost
limits, and provenance freshness are evaluated only during routing.

## Resource profiles and local observations

`atready resource profiles` and `atready resource profile PROFILE_ID` expose the
bounded built-in catalog used by Assisted Setup. Catalog output includes `catalog_version: 1`; a
profile contains `id`, `name`, `aliases`, readable category and capability suggestions,
capacity-unit hints, and an optional exact executable/version probe. A probe may name a canonical
executable plus a small ordered, platform-scoped alias allowlist. Omitting `--executable` checks
those exact names without enumerating `PATH`; if multiple names resolve to different files, the
observation fails as ambiguous rather than choosing one. An exact-path request must end in one of
the active platform's same allowlisted names.

An optional `provider_kit` adds editable workflow-mode mappings, provider-specific onboarding and
capacity questions, and optionally dated `model_routing_suggestions`. A model suggestion contains
an exact catalog ID and provider model ID, a proposed resource ID, a named/temporary/standalone
selection status, a planning role and caution, optional shared-capacity warning group, fixed
`availability: unverified`, and fixed `capability_scores: user-confirmed-only`. Suggestions and
their `model_catalog_reviewed_on` date must appear together and use distinct suggestion and resource
IDs. This is bounded catalog copy, not provider code: it performs no discovery, account inspection,
network request, authentication, model selection, review, or execution. Provider kits currently
cover CodeRabbit, OpenCode, Cursor, Claude Code, Google Antigravity, GitHub Copilot, Grok, PixelLab,
and Retro Diffusion under the same bounded planning-only contract, without provider,
configuration, or account inspection.
Cursor omits local
discovery because its documented `agent` basename is not provider-specific enough for safe
basename-only identification. Other profiles can adopt the additive contract after their copy and
executable aliases are researched and tested. Profiles and kits are proposal data, not
inventory facts: they establish no installation, access, authentication, capability, score,
quota, capacity, availability, or authorization.

Model suggestions do not add a hidden model dimension to routing. A generic provider remains one
resource when model selection is automatic, unknown, or immaterial. When a user confirms that two
selectable models have materially different planning fit, each may become a separate ordinary
resource with its own complete declaration; the router then evaluates those declared resources.
Equal `shared_capacity_group` values are only a warning that entries may draw from one pool. v0.1
does not coordinate shared consumption, enforce a pooled limit, or treat the entries as independent
capacity, redundancy, or failover.

After separate authorization, locate-only `atready resource discover PROFILE_ID` may return sanitized
local evidence with `profile_id`, `executable_name`, `installed`, `resolved_path`, `version`,
`search_scope`, `version_probe_performed`, `evidence`, and `limitations`; its account,
authentication, quota, and availability evaluation flags are always false, AtReady uses no
network, and it writes no inventory. Optional version inspection requires a second authorization
and reports the external program's network/write side effects as not evaluated. No result is
persisted directly.
The user must confirm any proposed label, installation, or version fact before it enters a recap or
declaration. The observation contains no account, authentication, billing, quota, capacity, or
provider-response data.

## Unit-aware capacity

`economics.capacity` is optional structured evidence alongside the existing qualitative `quota`
gate:

```yaml
capacity:
  unit: reviews
  remaining: 120
  limit: 500
  project_limit: 100
  resets_on: 2026-09-01
  basis: user-judgment
  last_verified: 2026-08-08
```

`unit` is a bounded machine label. Amounts are finite non-negative numbers in that one unit.
`remaining` is required; optional `limit` cannot be lower than `remaining`, and optional
`project_limit` cannot exceed `remaining`. Basis must be `observed`, `user-judgment`, or
`vendor-claim`, and `last_verified` is required and cannot be future-dated. AtReady never
converts or compares unlike units. When present, `resets_on` names the next reset and cannot be
earlier than `last_verified`. A catalog profile may suggest a unit but never an amount.

The router continues to gate and adjust on the declared qualitative `quota` state. Measured
capacity is supporting evidence and display context unless a later contract adds a project
constraint naming the same unit. Zero remaining capacity requires `quota: exhausted`; positive
remaining capacity cannot coexist with exhausted quota. A qualitative status never invents an
amount; inconsistent declarations fail validation.

## Inventory annotation declaration

Root private-note onboarding uses one strict note-only envelope:

```yaml
schema_version: 1
private_notes: Optional inert root annotation, never a credential.
```

`private_notes` is required, string-only, limited to 20,000 characters, and omitted from object
representations. The envelope accepts no inventory target, revision privacy nonce, resource data,
operation, or unknown field. Clearing an annotation is a separate value-free operation rather than
an ambiguous null or omitted value.

Supported value-bearing transports are an explicit protected file or explicit non-interactive
stdin only. They reuse the resource-declaration reader's bounded, identity-checked transport and
source-value-free diagnostics. The declaration value remains available to the local mutation
implementation but never belongs in a preview, receipt, routing snapshot/fingerprint, or handoff.
Providing a declaration does not authorize preview or apply.

Expose the schema with `atready schema inventory-annotation-declaration`. Set with
`atready inventory annotate set --annotation-file ...` or explicit `--annotation-stdin`;
clear with `atready inventory annotate clear`. Set and clear are preview-first, reject no-op
changes, bind the hidden value or absence into the candidate and plan token, and apply only through
the private-backup atomic replacement engine. Output reveals only the value-free note effect.

## Backup states

Backups are exact prior inventory bytes—including any revision privacy nonce—addressed by their
full SHA-256 revision. They live under a hashed logical-target namespace adjacent to the active
inventory. Darwin resolves the physical directory-entry spelling through the opened file
descriptor. Other supported filesystems use the normalized resolved target name rather than a
replaceable inode, but first require a fully ASCII basename containing a letter and prove the
directory's required case behavior by toggling every cased position separately. Each exact variant
gets two read-only, non-following observations against stable target and parent identity, and all
positions must agree. Non-Darwin POSIX requires a case-sensitive result; Windows requires a
case-insensitive result so its normalized namespace stays in that same bounded case domain. A
non-ASCII basename, missing ASCII letter, mixed result, unknown identity, lookup failure,
observation drift,
case-insensitive non-Darwin POSIX directory, or case-sensitive Windows directory fails before a
backup namespace is accessed or an update lock is initially acquired. Apply repeats the check under
that lock before backup or mutation. Two supported inventory files in one parent therefore have
separate backup sets.

Backup metadata is not an operation ledger. Identical states deduplicate, failed replacements can
leave a valid backup, and filesystem modification time can be changed independently. Listing is
therefore deterministic by backup ID and labels mtime as filesystem metadata, not chronology.
Backup-affecting applies additionally maintain immutable canonical-JSON operation events in a
target-scoped manifest. Event sequence is authoritative order; each event names its predecessor's
content hash and an apply records a prepared phase followed by completed, aborted, or uncertain.
Genesis records the count and canonical digest of the currently validated backup-ID set and
explicitly leaves earlier history unknown. Timestamps are metadata. The chain is local
consistency/tamper evidence, not a signature,
trusted time source, or hostile-account security boundary.
Manifest capacity never authorizes implicit pruning or rotation. When its bounded event or byte
limit is reached, the supported continuation is a separately initialized inventory path and
reviewed re-onboarding into that new lineage.
Explicit inspection returns the established private-note-free routing snapshot and a comparison
with active state. When active state is missing or invalid, backup listing/inspection reports that
state and omits the unavailable active snapshot/comparison. Recovery is separate from rollback: it
restores one exact valid personal backup only over a missing or safely readable invalid target,
and quarantines invalid displaced bytes outside the restorable backup namespace. Missing-target
commit is atomically exclusive and refuses to overwrite an entry created after the final recheck.
A later apply failure reports the retained quarantine path and records an uncertain manifest
outcome instead of hiding that side effect. Rollback restores
the selected exact bytes, including hidden private notes,
nonce, and formatting, after preserving active bytes as a safety backup. The preview exposes only
the active/candidate protection statuses. Exact-ID deletion is one-file-at-a-time and has no
automatic policy; deleting the final valid backup needs additional bound approval.

Unscoped backup files written by earlier alpha revisions do not contain trustworthy target
ownership. AtReady reports their count but never silently assigns, inspects, restores, or
deletes them.

## Project brief

A project contains an explicit `as_of` date, data/cost/interaction/network constraints, forbidden
resources, and ordered workstreams. Workstream order matters because a small documented continuity
bonus discourages unnecessary tool switching.

Each workstream owns capability requirements, scope, exclusions, deliverable, acceptance criteria,
verification text, stop conditions, next owner, and optional support/alternate policy.

## Route plan

The pure router returns:

- a canonical hash-derived plan ID and inventory fingerprint;
- a primary assignment or explicit capability gap for every workstream, plus structured unresolved
  constraints such as a required alternate that is unavailable;
- candidate gates, score components, adjustments, and stable tie-break evidence;
- one primary, optional single support, and optional reserved alternate;
- a complete inert handoff packet for every assigned workstream, including the resource's declared
  handoff method, guidance, and declared approval prerequisite;
- exactly one global disposition for every inventory resource; and
- deterministic warnings when a selected resource has stale or unknown state that the project
  explicitly allowed.

Route plans are advisory. Verification commands are data and are never passed to a shell.

## Versioning

After a public tag, schema changes that alter meaning require a new integer version and an explicit
migration path. The required `inventory_kind` field is an intentional pre-tag tightening of the
unpublished schema v1 contract. Inventories from an earlier source checkout fail with an actionable
classification error: add `inventory_kind: personal` only for genuinely user-declared state, or
`inventory_kind: demo` for synthetic examples. Readers otherwise fail closed on unknown fields or
versions. Migration code must preserve a private backup and offer rollback before it can modify user
state. v0.1 performs no migrations or partial resource merge/update. Resource replacement is a
complete same-ID declaration; rollback requires a present, valid personal inventory; and separate
recovery accepts only a missing or safely readable invalid target plus one exact validated personal
backup.
