# Permissions

## Principle

AtReady v0.1 is a planner, not an operator. It needs enough
access to read information the user deliberately supplies and produce a visible
plan. It does not need authority over the resources it describes.

Recommendation, authorization, credential access, and execution are distinct.
An inventory field such as `active`, `authenticated`, or `callable` describes
state; it never grants permission.

## v0.1 permission matrix

| Capability | v0.1 default | Boundary |
| --- | --- | --- |
| Install or update AtReady | Explicit user-controlled setup | The Codex plugin and Python local runtime are separate, independently versioned artifacts. A reviewed beta helper or documented manual commands may install both only when the user runs them; the plugin itself never installs, upgrades, or repairs the runtime and declares no apps, MCP servers, connectors, or hooks |
| Read an inventory or preferences file | User-supplied only | The user selects or provides the file; no home-directory search |
| Read one resource declaration | Explicit guided terminal answers, typed arguments, protected file path, or explicit non-interactive stdin | Guided Quick Add reads bounded answers only from the attached terminal and never asks for credentials or private notes. Structured modes read one versioned, bounded resource envelope; file contents/stdin stay out of AtReady argv, but terminal answers, typed arguments, the file path, and routing-visible preview can be retained elsewhere |
| Prepare a resource addition in a Codex conversation | Explicit resource-add request | When the current host grants the installed skill local execution and filesystem access, the request authorizes only bounded reads of the selected local inventory, resource schema, and optional built-in profile plus conversational intake and recap. Rendering the exact CLI preview requires approval of that recap. The skill asks only for routing-visible, non-secret facts supplied or confirmed by the user. It does not scan the computer, inspect accounts, contact a provider, read credentials, check billing or quota, or persist the proposal |
| List or inspect a built-in resource profile | Explicit profile command | Read-only bounded package data containing editable label/unit suggestions, optional provider-specific workflow/question guidance, dated unverified model-routing proposals, and an exact executable probe; profiles are not inventory or provider facts |
| Locate one profiled local executable | Separate exact-profile discovery approval | Bounded lookup of one profile's canonical executable and small platform-scoped exact alias allowlist, or user-supplied exact-path resolution, does not execute the program; different files under multiple allowed names fail as ambiguous, and the sanitized result writes no inventory and remains an unconfirmed proposal |
| Inspect that executable's version | Second explicit version-probe approval | Runs the resolved external program with fixed arguments, no shell, and bounded time/output; AtReady writes no inventory and uses no network itself, but the external program's network/write side effects are not evaluated |
| Create an empty personal inventory | Explicit `init` or a separate exact conversational create approval | The resource-add request alone does not authorize initialization. Conversational setup must name the exact path and stop for approval. Creation is exclusive, includes one OS-CSPRNG revision privacy nonce, never overwrites an existing file, and never prints the nonce |
| Add a resource to a personal inventory | Explicit preview, then separate explicit save/apply approval | Conversational add may prepare and display the same complete no-write preview, but the initial resource-add request does not authorize persistence. Saving requires the user to approve that exact preview in a later message. Guided Quick Add requires an attached terminal, a complete recap, preview approval, and an exact `save <resource-id>` confirmation. Advanced apply requires the previewed revision and plan token. Every path authorizes one preview-bound write, binds operation, canonical physical target and identities, and candidate; creates a target-scoped private exact-byte backup; refuses demo inventories; and refuses private notes on an unblinded target |
| Replace one resource in a personal inventory | Explicit preview, then explicit apply | Complete same-ID replacement only, never merge or rename; preview shows redacted before/after fields, defaults, and note effect; apply binds the complete candidate and creates an exact-byte safety backup |
| Remove one resource from a personal inventory | Explicit preview, then explicit apply | One exact resource ID only, never bulk or pattern based; preview shows the redacted resource and note presence; apply creates an exact-byte safety backup before replacement |
| Set or clear a root inventory annotation | Explicit protected declaration preview for set, value-free preview for clear, then explicit apply | Set accepts protected file/stdin only; both reject no-ops, bind the hidden value or absence to the revision and plan token, print only a value-free effect, and use the shared backup, manifest, lock, and atomic replacement engine |
| List or inspect backups | Explicit inventory target and exact ID for inspect | Read-only, bounded to the adjacent logical-target namespace, and private-note-free; works for valid, missing, or safely readable invalid active state and creates no directory or lock |
| Inspect backup operation history | Explicit inventory target | Read-only validation of target-scoped canonical hash-linked events; sequence is ordering evidence, timestamps are metadata, and the chain is not a signature or trusted clock |
| Roll back a personal inventory | Explicit preview, then explicit apply | Exact backup ID only; apply binds active/source identities and revisions, creates a safety backup, preserves the source, and restores exact bytes |
| Recover a missing or invalid personal inventory | Explicit preview, then explicit apply | Exact backup ID only; accepts no valid/demo/insecure active target, binds the missing/invalid state and source identities, refuses to overwrite a target that appears during missing-target commit, quarantines invalid displaced bytes, preserves the source, and restores exact bytes |
| Delete one backup | Explicit irreversible preview, then explicit apply | Exact validated ID only; no bulk/automatic mode; deleting the last valid backup also requires `--allow-no-backups` in preview and apply |
| Read project context | User/host supplied only | AtReady does not independently crawl repositories or unrelated files |
| Write workspace files | No implicit access | Plans are returned visibly; saving one is a separate explicit user action |
| Resolve the required AtReady local runtime | Explicit skill invocation only | The bundled launcher resolves the already-required trusted `uv` by exact name, asks it offline and without configuration files for one absolute tool-bin directory, and considers only that directory's platform-specific `atready` executable. Before delegation it runs a fixed, read-only `doctor` request and requires the declared runtime contract plus every feature used by the plugin. Product versions are informational and may differ. The launcher never enumerates, installs, or updates tools and ignores other `atready` commands on `PATH`; the trusted uv/startup environment remains the installer authority, and a compatible report is not publisher provenance |
| Broadly discover installed CLIs or applications | Not available | No PATH enumeration, package-manager query, application scan, recursive search, or arbitrary command; the optional local check is limited to one authorized profile's exact executable/version probe |
| Inspect environment variables | Not available | Neither names nor values are enumerated |
| Inspect MCP/app configuration or authentication | Not available | The local check reports no configuration, account, authentication, or credential state |
| Contact provider, billing, or quota APIs | Not available | There are no v0.1 connectors |
| Send a handoff to another resource | Not available | Handoffs are copy-ready, display-only text |
| Run a generated command or invoke a resource | Not available | Output is advisory and never an execution request |
| Purchase, cancel, or modify an account | Not available | Recommendations have no account authority |
| AtReady analytics or crash upload | Not available | No AtReady backend or telemetry |

The profile catalog and local check are exposed by `resource profiles`, `resource profile`, and
`resource discover`. Provider-kit workflow modes and questions are editable proposal copy; they do
not inspect a provider or prove a fact. Dated model-routing suggestions also remain proposal copy:
they do not inspect the configured model list, select a model, assign a capability score, verify
access, or authorize use. The Codex skill invokes profile commands only through its
contract-pinned launcher. Before locate-only `discover`, it must show the exact profile, canonical
executable and aliases or user-supplied path, and returned fact names, then obtain separate
authorization. Before optional version execution, it must
show the resolved absolute path and fixed arguments, disclose unevaluated external side effects,
and obtain a second authorization. Installation and version observations do not evaluate or prove
account, authentication, subscription, billing, quota, capacity, availability, or authorization. Declining
either check leaves conversation-only Assisted Setup available.

The bundled coding-agent checks currently allow the exact canonical executable names `agy`
(Google Antigravity), `claude` (Claude Code), and `copilot` (GitHub Copilot CLI), in addition to
the other profile-specific probes declared by the catalog. Cursor intentionally has no local
probe: its current `agent` CLI name is too generic for AtReady's basename-only identity
boundary. Antigravity is locate-only because no reviewed fixed version argument is declared;
Claude Code uses `claude --version` on POSIX, and GitHub Copilot CLI is locate-only because its
documented version command also checks for updates. Claude Code and GitHub Copilot discovery are
POSIX-only in this catalog version; native Windows remains conversation-only rather than accepting
unreviewed command shims. These checks do not inspect account, authentication, configuration,
subscription, quota, provider usage, projects, or repositories.

The AI host may have permissions independent of AtReady and may send
context to a hosted model. Granting the host filesystem or network access does
not expand AtReady's product contract. Users and implementers must not
infer AtReady authorization from broader host capabilities.

Conversational resource intake is available only when the current Codex host grants the installed
skill the required local execution and filesystem access. A ChatGPT surface without that local
capability may help draft the non-sensitive entry, but it cannot claim to have read or changed the
user's local roster. It must direct the user to the local `atready add` flow to preview and save.

## Local files

Inventory and preference data should live outside public repositories in a
user-controlled per-user location. On POSIX systems, AtReady applies
owner-only mode bits to storage it creates:

- `0700` for a directory created by AtReady; and
- `0600` for a file created by AtReady.

When `init --path` targets a directory that already exists, AtReady
validates that the parent is a real directory rather than a symlink, but does
not change its permissions. v0.1 does not configure or verify Windows ACLs and
therefore makes no owner-only access guarantee on Windows; use a per-user
location whose access controls you have reviewed.

On macOS, sensitive files and directories are accepted only when the opened
descriptor has no extended ACL entries. This is deliberately conservative:
AtReady does not interpret allow versus deny entries. It does not alter
caller-owned ACLs; inspect their intent and choose a different protected location
or remove them separately when appropriate. Ancestor-directory ACL policy outside
the directly validated storage remains the user's responsibility.

Guided Quick Add reads only bounded, user-entered terminal lines after `atready add`; it rejects
redirected/non-interactive input before reading, never performs discovery, and never asks for
credentials or private notes. Terminal history, recording, scrollback, invoking hosts, and model
context remain separate disclosure surfaces. The answers are validated through the same resource
schema as advanced input before a no-write plan is produced.

Conversational add follows the same data and mutation boundary. The skill may collect only the
routing-visible facts needed by the public resource schema, and may use a built-in profile only as
editable suggestion copy. Those answers and the sanitized preview can enter the configured
host/model context. The first request authorizes intake and recap only. The skill must obtain
explicit approval before rendering the exact CLI preview, stop after displaying it, and obtain a
later approval before applying it. Declining, changing, or failing to approve performs no inventory
write.

An explicit resource or inventory-annotation declaration file is read-only input, not
AtReady-owned storage. AtReady never copies, modifies, deletes, or retains it. On POSIX,
the reader requires a current-user-owned, singly linked, regular `0600` file,
opens it without following the final symlink where the platform supports that,
uses a nonblocking open to refuse special-file substitution before reading,
rechecks path/descriptor identity, metadata, and macOS ACL state, and reads at most 1 MiB. The same
Windows ACL limitation applies. Explicit stdin is non-interactive, incremental,
and bounded to the same size. Annotation values have no typed-argument input path. Neither
transport is read unless its corresponding flag is present.

Structured input removes declaration contents from AtReady's process
arguments only. The source path, shell redirection or producer, invoking host,
terminal, logs, model context, and routing-visible preview remain separate
disclosure/retention surfaces. CLI and supported loader diagnostics contain no source values or
YAML source snippets. Low-level Pydantic structured validation errors and Python traceback/frame
introspection are not redacted APIs and must not be logged as privacy-safe diagnostics.

`init` writes `revision_privacy_nonce: nonce-v1:<64-lowercase-hex>` using 32
bytes from the operating system CSPRNG. No network or keychain permission is
required. Validation, listing, routing, preview, and apply never generate, print,
or rotate it. The value remains in raw inventory/backup bytes so their exact
SHA-256 revisions are blinded against private-note guesses. A state such as
`nonce-v1-present` or `legacy-unblinded` may be shown without the value. Presence does not prove
entropy, provenance, uniqueness, or nondisclosure for imported state.

Inventory writers resolve and display a canonical physical target, refuse a
symlinked final target or direct parent, and bind inspected target and parent
identities into each plan. On POSIX they also reject unsafe writable ancestor
chains and a target that is not current-user-owned, exactly `0600`, or singly
linked. The direct parent must be current-user-owned and not group/other-writable.
Before any backup-namespace access, non-Darwin platforms require a fully ASCII
basename with a letter, toggle every cased position separately, and make two
metadata-only, non-following lookups of each exact variant in the target's
direct parent. They do not enumerate the parent or read those siblings'
contents, and every position must agree. Non-Darwin POSIX must prove
case-sensitive; Windows must prove case-insensitive. Unknown, changing, mixed,
or unsupported results fail closed. Darwin instead resolves physical entry
spelling through the opened target descriptor.
Writers take an auto-releasing OS advisory lock on a persistent `0600` lock file,
recheck the full-file SHA-256 revision and identities, and preserve prior bytes
inside a `0700` root plus a `0700` logical-target namespace. Backup files are
content-addressed, singly linked, current-user-owned `0600` regular files on
POSIX. Directories are synced before a same-directory atomic replacement;
syncing the active inventory's parent after replacement is best effort and is
reported in the receipt.

Backup IDs must use canonical lowercase SHA-256 syntax and are converted to
paths internally. Listing is deterministic by ID rather than alleged time.
Inspection and rollback revalidate digest, UTF-8/YAML/schema, personal kind,
mode/ownership/link count, and namespace/file identities. Rollback restores the
selected bytes without reserialization and first stores the current bytes as a
safety backup. Deletion rechecks the complete validated backup set under the
same lock, unlinks one exact file, and syncs its namespace. No operation accepts
an arbitrary backup path, `latest`, a glob, age policy, or bulk selection.
Backup-root and per-target enumeration stop after 4,096 entries; per-target
content work stops after 64 MiB of entry bytes, including unexpected entries.
Capacity never authorizes automatic pruning: a required new safety backup fails
before replacement, while externally over-limit storage may need manual repair.

The advisory lock coordinates AtReady writers and is released by the OS
when the process exits; the inert lock file may remain. It does not lock out
editors that ignore it. Revision checks detect changes through the final
pre-replacement check, but ordinary filesystem replacement is not a
transactional compare-and-swap: a non-cooperating same-account editor can still
race in the final check/replace window. The current user account is trusted in
the v0.1 threat model. Post-replacement verification or POSIX parent-directory
durability, post-unlink verification/durability, or lock-cleanup uncertainty is
returned as an applied-but-uncertain receipt rather than an ordinary pre-commit
failure.

Writers must use secure temporary files, atomic replacement, path containment,
and symlink-safe behavior. AtReady must not write to global agent
instructions, install a skill, modify a project, or merge imported inventory as
a side effect of planning.

Do not rely on `.gitignore` as a security control. It is a useful backstop, but
real inventories should remain outside repositories and contain no secret
values.

## Model context is disclosure

Reading a local file into a hosted model context can disclose that content
outside the machine even when the source file remains local. Before loading
inventory or project material, users should consider:

- whether the selected host/model is approved for that data;
- which fields or excerpts are actually needed;
- whether resource names, costs, quotas, or project names are confidential;
  and
- whether the resulting handoff is safe to copy to its intended destination.

AtReady must not describe hosted model processing as fully local or
offline.

## Generated output

Prompts, missions, checklists, commands, links, and provider recommendations are
text for human review. A consumer must not automatically execute, open, fetch,
or dispatch them. The user remains the approval boundary for destination, data
shared, permissions, cost, and consequential effects.

## Changing this boundary

Any proposal for broader discovery, provider discovery, a connector, telemetry, hosted storage, or
execution must define before implementation:

1. the exact new data and permissions;
2. the user action that grants and revokes access;
3. the destination and retention of transmitted data;
4. least-privilege and failure behavior;
5. a visible preview for consequential actions;
6. deterministic enforcement outside the model; and
7. security, privacy, and abuse-case tests.

Such a feature must update `PRIVACY.md`, `SECURITY.md`, and
`docs/THREAT_MODEL.md`. It must not silently inherit v0.1's offline,
non-executing trust claim.
