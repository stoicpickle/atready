# Privacy

This document describes the privacy boundary intended for AtReady
v0.1. It should be updated before any release changes that boundary.

## Short version

The AtReady CLI stores inventory and preferences in files on the user's local filesystem.
AtReady v0.1 operates no backend, telemetry service, connector, subscription-discovery
service, or remote resource-invocation service. It does include a separately authorized,
exact-profile local executable check; that check never contacts the provider or verifies an
account.

When the ChatGPT or Codex skill is used, project details and an inventory snapshot without private notes may
enter the configured host or model provider's context. Resource names, access state, costs, quotas,
and capabilities may still be sensitive. Local storage is therefore not a promise of local-only or
offline model processing.

The ChatGPT/Codex plugin contains only the workflow skill and installs no Python package, connector,
app, MCP server, hook, or telemetry component. The separately installed runtime may use a different
product version; the launcher requires the same runtime contract version and every feature declared
by the plugin. Installing either artifact does not upload an inventory, but later host/model
processing remains subject to the boundary above.

## Data AtReady handles

Depending on what the user supplies, a planning session may handle:

- a capability inventory, including resource names, access state, costs,
  qualitative quota, optional measured capacity, suitability notes, and verification dates;
- an optional local discovery result containing one allowlisted executable name, its resolved
  local path, and—only when separately requested—one bounded version line;
- planning preferences and routing constraints;
- project goals, constraints, and excerpts the user chooses to provide; and
- generated plans, explanations, and copy-ready handoff packets.

This information can reveal commercial relationships, project strategy,
budgets, private work, and installed tooling. Treat it as sensitive even when
it contains no credentials.

AtReady's inventory is not a credential store. Do not put passwords,
API keys, session cookies, OAuth tokens, private keys, recovery codes, or other
secret values in inventory or preference files.

## Local storage and retention

AtReady itself does not upload local files to an AtReady-operated service; no such
service exists in v0.1. The user's operating system, sync software, backup tools, shell, AI host,
model provider, or other software may still copy, retain, or process those files independently.

The CLI reads bounded answers entered after explicit TTY-only `atready add`; the inventory,
project, resource-declaration, and inventory-annotation-declaration paths the user names; explicit
non-interactive resource or inventory-annotation stdin; plus the resolved default inventory path
when no inventory path is supplied. `resource profiles` and `resource profile` read only the
bundled offline proposal catalog. An explicit `resource discover` either checks one user-supplied
absolute executable path or consults the current `PATH` only to locate one profile-allowlisted
command name; it does not print or enumerate `PATH`. After a second explicit authorization,
`--inspect-version` then runs only that
executable with bundled fixed version arguments, no shell, a reduced environment, a two-second
timeout, and a 4 KiB merged-output limit. The result can expose the resolved local path and one
sanitized version line to the terminal, host, logs, or model context. It does not read provider
configuration, credentials, accounts, authentication, subscriptions, billing, quota, or live
availability, and it performs no inventory write. AtReady does not evaluate whether the
external program itself performs network or filesystem side effects. Explicit backup commands
also enumerate/read the adjacent target-scoped namespace for that one inventory;
they do not search other directories or target namespaces. Persistent writes
are limited to `atready init` and explicitly applied resource
add/replace/remove, root-annotation set/clear, exact-byte rollback, exact-ID
recovery, and exact-ID backup deletion. `init` is the one direct-write
exception: it creates only a new inventory and refuses to overwrite an existing target. Every
other mutation is preview-only until a separate approval: advanced commands repeat the previewed
state/revision and plan token, while guided Quick Add requires the exact `save <resource-id>` phrase
after displaying the bound complete preview. Structured inventory edits canonicalize
the YAML; rollback and recovery restore the selected backup's exact bytes,
including private notes and formatting. Replacement operations preserve active
bytes in a private, content-addressed, target-scoped backup directory, sync that
storage on POSIX, and use same-directory atomic replacement. Recovery of a
safely readable invalid target first preserves its exact displaced bytes in a
distinct non-restorable quarantine artifact. Backup deletion is an explicitly
irreversible operation that removes one validated file only. Applied operations
also append value-free events to the target-scoped operation manifest; previews
and inspections do not write. Demo inventories are read-only.

If recovery fails after invalid bytes have been quarantined, the error reports
the retained local quarantine path and the manifest records an uncertain outcome
with its opaque identifier. Neither surface includes the quarantined content or
a content-derived identifier.

New personal inventories include a fresh 256-bit `nonce-v1` revision privacy
nonce generated from the operating system CSPRNG. The persisted value is part of
the raw inventory, protected replacement files, and exact-byte backups. Normal CLI output exposes only a
value-free protection status; routing snapshots/fingerprints, previews,
receipts, diagnostics, and object reprs omit the nonce value.

Guided onboarding reads resource names, access, cost/quota, policy, ratings, and provenance as
bounded terminal answers; typed onboarding places the same kinds of values in command-line
arguments. Terminal scrollback/recording, shell history, process observers, the invoking host,
logs, or endpoint-management software may retain those values independently of AtReady. Guided
onboarding never asks for credentials or private notes.

Versioned file/stdin declarations keep their **contents** out of AtReady's
process arguments. That is argv safety, not an end-to-end confidentiality claim.
An explicit file pathname remains in argv, the source file remains on disk under
the user's lifecycle and backup/sync controls, and a redirected or piped stdin
producer remains under shell/host control. AtReady does not copy, modify, delete, or retain the
declaration source. Declaration stdin is read only after the explicit `--resource-stdin` or
`--annotation-stdin` flag and is refused when interactive; this is separate from the bounded
terminal-question flow used only by `atready add`.

On POSIX, file declarations must be current-user-owned, singly linked, regular
`0600` files and are read through a bounded identity-checked descriptor. Windows
ACL privacy is not verified, so users must choose a protected per-user location.
On macOS, AtReady conservatively rejects any extended ACL on sensitive
declaration, inventory, backup, directory, or replacement storage it validates;
it does not decide whether individual entries are harmless. Both transports
accept one bounded UTF-8 declaration. Syntax and validation diagnostics omit
source values and YAML source lines.

The supported privacy-safe validation boundary is the CLI or the
`InventoryCatalog`/project/resource loader functions. Low-level Pydantic model classes are internal
contracts; Pydantic's structured `ValidationError.errors()` and `.json()` can retain
caller-supplied input and must not be logged or treated as a redacted diagnostic surface. Python
exception tracebacks and in-process frame introspection are also developer surfaces and can retain
objects supplied by the caller; do not expose or log them as privacy-safe diagnostics.

Successful previews still expose every routing-visible resource field and
actual default to stdout. They expose only whether `private_notes` is present;
the note value, excerpt, length, direct hash, and privacy nonce are omitted but
the exact value is persisted and plan-token-bound. CLI output can be retained by a shell, host,
redirect, terminal log, or model context. Supplying declaration content in chat
has already disclosed it to the configured host/model path. These fields can be
sensitive even when they contain no credential; structured input does not make
an otherwise unapproved host or logging environment safe.

Private notes are inert local annotations. They are omitted from routing snapshots and never affect
eligibility, scores, assignments, or handoff packets. Routing-relevant facts must be represented in
the structured visible fields. Resource-level notes can be onboarded through a
protected resource declaration. Root inventory-level notes can be set through a
separate protected note-only declaration or cleared through a value-free command.
Both paths remain inert, preview-first inventory mutations and are not a nonce
migration mechanism.

Because the nonce participates in the exact inventory bytes, full-file revisions,
candidate revisions, plan tokens, and backup IDs cannot practically verify guesses
of low-entropy private-note values while the nonce remains undisclosed. This is
blinding, not encryption, authentication, or access control. Revisions still reveal
whether exact hidden state is equal or changed. Anyone who reads a raw inventory or
backup learns both its nonce and its private notes; a leaked note-free raw inventory
also exposes the nonce that would blind later notes.

Private notes are therefore valid only in an inventory carrying a syntactically
valid revision privacy nonce. Legacy unblinded inventories remain valid only while
they contain no private notes and may accept note-free resources without being
silently changed. AtReady can validate an imported nonce's syntax, but cannot
prove it came from `init`, had sufficient entropy, or stayed undisclosed. There is no
supported in-place injection or rotation in v0.1. Initialize a new path if protection
is missing or may have been exposed, and do not reuse one raw initialized inventory
as an independent private clone.

When the hosted AtReady skill is used on a supported surface, the host may read the minimum project-relevant
files needed to prepare the plan. The skill creates its project brief in a
fresh OS temporary/private directory with owner-only controls (`0700` for the
directory and `0600` for the file on POSIX), then removes that exact temporary
directory after routing. It does not place the brief in the project checkout.
Equivalent platform-native access controls apply where POSIX modes do not.

Inventory backups remain until the user deliberately deletes one exact ID.
AtReady performs no automatic, age-based, chronological, bulk, or
keep-count pruning. Deleting the last valid backup requires the additional
`--allow-no-backups` approval in both preview and apply. A failed add or rollback
can leave a valid safety backup even when the active inventory was not replaced.
Backups contain the complete prior file, including private notes and its revision
privacy nonce, and must be protected like the active inventory.

Backup listing exposes only target/file-time metadata, resource counts, active-match state, and
value-free `nonce-v1-present`/`legacy-unblinded` revision-protection states; exact backup sizes are
omitted. Explicit
backup inspection and rollback previews expose sanitized routing snapshots,
including identifiers/names, capabilities, access/session state, costs/quota,
ratings, policy, provenance, handoff guidance, and best/avoid text, but not
private-note values. Command output may be retained by the shell, invoking host,
terminal logs, or a hosted model context.
Exact-ID reads collapse missing, unsafe, corrupt, digest-mismatched, and non-personal candidates to
one unavailable/non-restorable diagnostic rather than confirming a guessed legacy state.
Backups written by earlier unscoped alpha revisions are reported but not
silently attributed, inspected, restored, or deleted because their target
ownership cannot be proven.

To bound metadata and content processing, the backup root and each target
namespace are capped at 4,096 entries, and a target scan considers at most
64 MiB of entry bytes. Unexpected entries count. AtReady refuses a new
safety backup before active replacement when capacity is exhausted and never
deletes content to make room. Externally modified over-limit storage may require
manual local inspection before supported listing or deletion is available again.

Local files remain until the user edits or deletes them. Deleting local
AtReady files does not delete copies retained by an AI host, model
provider, backup system, source-control remote, or sync service. Those systems
have their own controls and retention policies. The same limit applies when
the skill removes its temporary brief: project content may already exist in
the host/model context, logs, or provider retention systems.

Real inventory, preference, history, and export files should not be committed
to a public repository. Public examples must use synthetic data.

## Model and host processing

When AtReady runs as a skill inside an AI host, the host decides what
context is sent to a model and where that model runs. Users should review the
host's data controls before providing confidential inventory or project
material.

AtReady does not add a separate network transmission or backend to that
host/model path. It also cannot delete content already retained by the host or
provider.

## Network access and telemetry

AtReady v0.1 has:

- no product analytics or unique installation identifier;
- no remote crash reporting;
- no advertising or tracking;
- no provider, billing, quota, or subscription connectors; and
- no automatic discovery of local programs, environment variables, or MCP
  configuration.

The surrounding host may still use the network for model inference, updates,
or its own telemetry. Those activities are outside AtReady's control and
must not be described as AtReady telemetry.

## Generated handoffs

Generated prompts, missions, commands, URLs, and checklists are advisory,
display-only artifacts. AtReady v0.1 does not send them to another
service, invoke an inventoried resource, run a generated command, make a
purchase, or cancel a subscription.

Invoking the AtReady skill grants planning authority only. Broader tool
permissions held by the AI host do not implicitly authorize any generated
handoff; executing one requires a separate, specific user instruction.

Users should review a handoff for confidential content, destination, expected
cost, and safety before copying it elsewhere.

## Future changes

Discovery, connectors, hosted sync, telemetry, or execution would create new
privacy boundaries. Any such feature must be opt-in, documented before release,
and accompanied by updates to this file, `docs/PERMISSIONS.md`, and
`docs/THREAT_MODEL.md`.
