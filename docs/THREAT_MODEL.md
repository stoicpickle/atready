# Threat Model

Last reviewed: 2026-08-10

## Scope

This threat model covers AtReady v0.1: a local-file capability inventory and a non-executing
planning workflow whose local CLI makes no AtReady-authored provider API or connector calls
and produces advisory, display-only plans and handoff packets.

The v0.1 boundary excludes broad or automatic discovery, provider/account discovery, connectors,
provider status or billing checks, telemetry, hosted sync, project-work resource invocation,
generated-command execution, purchasing, and subscription cancellation. One optional, separately authorized local
check may resolve one of a built-in profile's small exact executable-name allowlist without running
it. A second explicit
authorization may run fixed version arguments without a shell; the external program's network and
write side effects are not evaluated. All resulting evidence remains an unconfirmed proposal. The
Codex plugin and Python local runtime are separate artifacts: the plugin delegates only after a
strict, value-free compatibility handshake proves the required runtime contract and features. It
never installs or updates the runtime. On a Codex host with approved local execution and filesystem
access, an explicit resource-add request may authorize bounded inventory/schema/profile reads and
conversational intake and recap. Rendering the exact CLI preview requires approval of that recap,
and a later explicit approval is required before one exact preview-bound inventory write. This does
not add scanning, provider contact, account inspection, credential access, or network authority.
If the selected roster is missing, creating one empty roster requires its own exact path approval;
the resource-add request does not authorize initialization.

## System boundary

The relevant data flow is:

1. A user creates or selects local inventory and preference data. A conversational resource-add
   flow may create a missing empty roster only after a separate exact path approval.
2. The user may declare one resource through bounded guided terminal answers, typed arguments, a
   protected versioned file, explicit non-interactive stdin, or bounded non-sensitive answers in a
   Codex conversation. The conversational request authorizes only selected local
   inventory/schema/profile reads, intake, and recap.
3. After approving the recap and reviewing the complete no-write resource preview, the user may
   separately approve one exact preview-bound save. Without that approval, no inventory write
   occurs.
4. Before declaration, the user may authorize exact-profile executable location without execution;
   after reviewing the resolved path and fixed arguments, they may separately authorize optional
   version execution. They then confirm or reject any proposal-only evidence.
5. The user supplies a project request and any project context they choose.
6. An AI host may load that material into a selected model.
7. AtReady produces a plan and copy-ready handoffs for human review.
8. No project-work request or handoff is sent to an inventoried resource or executed by AtReady.

The AI host and model provider are outside the AtReady product boundary.
They are still part of the user's end-to-end privacy decision because hosted
model processing may leave the machine.

## Assets

- Capability inventory, access state, cost, quota, and suitability notes.
- Project goals, constraints, excerpts, and private identifiers.
- Preferences, routing policy, and any observed-use history.
- Generated plans, commands, URLs, and handoff packets.
- Local filesystem paths and user account information.
- The distributed skill, helper code, dependencies, and release pipeline.

No credential value should be an asset AtReady needs to possess in
v0.1. The parser rejects secret-like field names, but secrets embedded in
allowed free-text values cannot be detected reliably. Users must not put
credentials or other secret values in an inventory; if they do, that content is
sensitive untrusted input that may reach host/model context or generated output.

## Actors and trust assumptions

Potential threat actors include:

- an author of a malicious resource declaration, inventory, or project file;
- an attacker who can influence repository text supplied to the model;
- a compromised dependency, package, release, or CI workflow;
- another local account or process with access to improperly protected files;
- and an accidental operator who copies sensitive or unsafe generated output.

The local operating system and the user's account are trusted for v0.1. A fully
compromised account or host is out of scope, though restrictive file permissions
still reduce accidental cross-user exposure. The selected AI host/model is
trusted according to its own published controls; AtReady does not claim
to secure or audit that provider.

## Security invariants

- Recommendation, authorization, credential access, and execution are separate
  states.
- A conversational resource-add request authorizes bounded local reads, intake, and recap only.
  Rendering the exact CLI preview requires approval of the recap. One exact preview-bound write
  requires a later, separate, explicit save approval enforced by the local runtime rather than
  inferred from model output.
- Model output is never a security decision or execution authority.
- User/imported text is treated as untrusted data even when it resembles an
  instruction.
- No AtReady network service, telemetry channel, connector, broad scan, or provider discovery
  exists in v0.1. Provider-specific kits are inert catalog proposals, not adapters. Exact-profile
  executable location is local, allowlisted, non-executing, and
  separately authorized. Optional version inspection is separately authorized again; it executes
  the external program with fixed arguments and makes no claim about that program's side effects.
  Coding-agent probes are bound to the catalog's exact canonical executable names. Cursor has no
  probe because `agent` is not provider-specific enough for this boundary; Antigravity's `agy`
  and GitHub Copilot's `copilot` checks are locate-only, while Claude Code uses its declared fixed
  version invocation only after the second authorization. Claude Code and GitHub Copilot local
  discovery are POSIX-only in this catalog version rather than accepting unreviewed Windows command
  shims.
- Dated model-routing catalog entries are unverified suggestions, not provider observations,
  benchmarks, scores, defaults, or hidden router rules. They do not inspect provider configuration
  or model availability. A user may confirm model-specific resources separately; shared-capacity
  labels are warnings only, and v0.1 does not coordinate a shared pool or claim independent
  capacity, redundancy, or failover.
- CLI reads are explicit, narrow, and bounded, including resource and inventory-annotation
  file/stdin reads only after their corresponding flags. Persistent writes are limited to exclusive
  empty-personal initialization; previewed resource additions, replacements, removals, root
  annotation set/clear, exact-byte rollback, and missing/invalid-state recovery; explicit exact-ID
  backup deletion; and their value-free operation-manifest events. Mutations bind the original
  bytes or missing/invalid state, canonical physical target, relevant filesystem identities, and
  complete candidate or backup set. The host skill may
  also create one permission-restricted project brief in a fresh per-run
  temporary directory, which it must remove after routing or report if cleanup
  fails.
- Generated handoffs remain visible to the user and are never dispatched or
  executed automatically.
- Fresh personal inventories contain one undisclosed CSPRNG-generated revision
  privacy nonce. It is carried through exact bytes but excluded from normal output,
  routing snapshots/fingerprints, supported CLI/loader diagnostics, and reprs.

## Threats and controls

| Threat | Impact | v0.1 control |
| --- | --- | --- |
| Secret or private project data appears in a plan | Disclosure through a host, copied handoff, log, or public commit | The schema rejects secret-like field names and documentation prohibits secret values, but value scanning is not a guarantee; examples are synthetic; users and hosts must minimize supplied context and review output |
| A resource-add request is treated as permission to create a roster | Unexpected local file creation | A missing roster requires a separate conversational approval naming the exact path. Initialization uses exclusive create, refuses an existing target, and returns a bounded receipt before intake continues |
| A conversational add request is treated as permission to preview or save | Unreviewed disclosure or unintended inventory mutation | The request authorizes bounded selected-inventory/schema/profile reads, intake, and recap only. The skill must obtain approval before rendering the complete candidate and stop after it; the runtime accepts a write only after a later explicit approval bound to that exact preview, revision, target, and candidate |
| Conversational resource intake exposes or invents account facts | Disclosure through host/model retention or misleading routing state | The skill asks only for routing-visible non-secret facts, treats built-in profiles as editable suggestions, and requires user confirmation. It performs no scan, provider contact, credential access, account inspection, or billing/quota check. Sanitized answers and previews may enter the configured host/model context |
| A host without local execution is mistaken for a successful local save | False persistence claim or missing roster entry | The skill must fail closed when local runtime/filesystem access is unavailable, may provide drafting help only, and directs the user to local `atready add`; it must not claim to have read or changed the local roster |
| Direct or indirect prompt injection in inventory or project text | Manipulated recommendations or attempted disclosure | External text is data, not authority; generated actions are display-only; the model has no AtReady execution capability |
| Command injection through a resource field or generated verification step | Local code execution | No generated command is automatically run; helper code must not evaluate fields or invoke a shell with untrusted text |
| Broad filesystem or environment discovery exposes credentials | Disclosure of local configuration or access state | No PATH printing/enumeration, directory crawl, package-manager query, environment-variable enumeration, MCP inspection, or arbitrary search exists; local discovery may consult the current PATH only to resolve one profile's small ordered set of exact executable names, while exact-path mode avoids PATH lookup |
| Provider-specific onboarding copy is mistaken for inspected account state | False readiness, quota, or authorization claims | Provider kits contain editable workflow mappings and questions only; their schema fixes account inspection and provider execution as unsupported and AtReady network access as none. Every proposed field still requires user confirmation |
| A spoofed or malicious same-name executable is mistaken for the intended product | Code execution or external side effects during the fixed version probe; false installation/version evidence | Locate without execution first. Platform-scoped aliases are exact and bounded; if multiple allowed names resolve to different files, fail as ambiguous. Show the resolved path, fixed arguments, unevaluated side-effect boundary, and fact set before a second authorization; invoke without a shell; treat the path/version as unconfirmed evidence, not publisher provenance, access, or authorization. The user-controlled PATH/startup environment and same-account executables remain trusted in v0.1 |
| Local discovery output injects instructions or exposes unexpected text | Misleading recap or disclosure | Discovery returns only a bounded, sanitized first output line plus explicit limitations rather than a raw provider response; no result is persisted until the user confirms it. This is output bounding, not credential detection, so the user must review the proposal before disclosure or persistence |
| Resource metadata is exposed through process arguments | Disclosure through shell history, process observers, endpoint tools, or host logs | Structured file/stdin modes keep declaration contents out of AtReady argv; typed values and the explicit file pathname remain visible there, and routing-visible preview output remains a separate disclosure surface |
| Guided terminal answers expose or invent resource facts | Disclosure or misleading routing state | `atready add` requires attached stdin/stdout terminals, reads bounded answers only, says profiles are editable proposals, accepts uncertainty, never scans or inspects providers, never asks for credentials/private notes, validates the resulting mapping through the public resource schema, and requires separate preview and exact save confirmations. Terminal scrollback/recording and host/model retention remain user-controlled disclosure surfaces |
| Malformed structured input echoes private values through diagnostics | Disclosure to stderr, terminal logs, or host/model context | Supported CLI and loader diagnostics contain only source-free line/column and redacted schema locations; source lines, input values, and dynamic capability keys are omitted and sentinel-tested. Low-level Pydantic errors and Python traceback/frame introspection are developer surfaces, not redacted APIs |
| Symlink, hard link, FIFO substitution, replacement race, loose mode, or extended ACL redirects/exposes a resource or inventory-annotation declaration read | Disclosure of or onboarding from unintended local data | Both declaration adapters share one protected-file implementation. POSIX input requires a current-user-owned, singly linked, regular `0600` file; nonblocking descriptor open, final-link refusal, pre/post identity and same-domain metadata checks, and two exactly matching bounded descriptor reads fail closed. macOS rejects every extended ACL entry conservatively. Windows ACL privacy and ancestor-directory controls remain user responsibilities |
| Hidden private notes are applied without meaningful review | Private-state surprise or unintended persistence in inventory/backups | Structured preview reports presence only, states that notes are omitted and plan-bound, and requires review in the source plus separate apply. Any semantic note change changes the plan token; values, direct hashes, lengths, excerpts, and the privacy nonce are never printed |
| A root annotation leaks through argv, preview, receipt, or operation history | Disclosure of local-only inventory context | Set accepts only protected file/stdin declarations, clear accepts no value, previews and receipts expose only a fixed effect label, plan tokens bind candidate bytes without exposing a direct note hash, and manifest details contain revisions and backup identifiers only |
| A full replacement silently clears defaults or hidden notes | Loss of intended resource metadata | Replace is explicitly a complete same-ID declaration, never a merge; preview shows all routing-visible before/after values, actual defaults, and a value-free private-note effect; no-op replacements fail |
| Removal targets the wrong or many resources | Loss of inventory state | Remove accepts one exact validated resource ID, previews that resource and count change, binds the candidate and operation, and creates an exact-byte safety backup before atomic replacement; there is no bulk or pattern mode |
| Full-file revisions or backup IDs verify guesses of low-entropy hidden notes | Offline inference of omitted private state | Current `init` embeds an undisclosed 256-bit `nonce-v1` value in exact inventory bytes before notes exist, so SHA-256 revisions and backup IDs are practically unguessable without raw-file access. Exact-ID lookup also collapses missing, unsafe, corrupt, mismatched, and non-personal backups to one diagnostic, including for legacy states. Revisions still reveal equality/change, and nonce disclosure removes blinding |
| A legacy/imported inventory claims note protection with no, weak, reused, or disclosed nonce | False privacy assurance | Any note requires syntactically valid versioned nonce state; note-bearing unblinded files fail closed. AtReady generates entropy only during exclusive `init`, never planning. Imported syntax cannot prove entropy/provenance, cloning reuses state, and v0.1 documents new-inventory migration rather than silent injection/rotation |
| Explicit stdin blocks on a terminal or exhausts memory | Availability loss or accidental terminal disclosure | Stdin is read only with `--resource-stdin`, interactive terminals are refused before reading, and incremental input stops after 1 MiB plus one detection byte |
| A descriptive `active` or `callable` field is treated as permission | Unauthorized or costly action | Capability metadata grants no authority; v0.1 performs no project-work resource invocation or handoff execution |
| Inventory or history is exposed to another local user | Disclosure of tools, costs, projects, hidden notes, and their privacy nonce | Use per-user storage; on POSIX, AtReady applies restrictive modes to directories and files it creates. macOS sensitive storage is rejected if any extended ACL is present; Windows access controls remain the user's responsibility |
| Symlink abuse redirects inventory initialization | Write to an unintended target | The initializer creates a new file exclusively, rejects a symlinked file or direct parent, applies owner-only modes on POSIX, and never overwrites; an explicit `--path` remains a user-chosen location |
| Changed preview or substituted target is applied | Unauthorized or unintended inventory state | The apply plan token binds operation, canonical physical target, inspected target/parent identities, original revision, and complete candidate; changed persisted values, candidate drift, working-directory or ancestor-link retargeting, identity substitution, and detected byte conflicts fail closed |
| Concurrent file update overwrites user changes | Loss or corruption of inventory state | AtReady writers coordinate through an auto-releasing OS advisory lock; apply rechecks complete bytes before same-directory replacement; POSIX writes refuse unsafe target links/modes/ownership and group/other-writable or non-owned direct parents. Residual risk: a non-cooperating same-account editor can write in the final recheck/replace window because common filesystem replacement is not compare-and-swap; the current account is trusted in v0.1 |
| Update failure loses the prior inventory | Loss of user state | Before replacement, apply stores the exact original bytes under a content-addressed name in a private adjacent target namespace, then syncs the backup directories and parent entry on POSIX; replacement uses a synced same-directory temporary file; backups persist until the user explicitly deletes an exact ID |
| One inventory reads or restores another inventory's adjacent backup | Cross-inventory disclosure or wrong-state replacement | Each accepted canonical target filename maps to a separate hashed logical-target namespace and IDs derive paths internally. Darwin binds physical directory-entry spelling through the opened file descriptor. Before every namespace consumer, non-Darwin targets require a fully ASCII basename with a letter, toggle every cased position separately, observe each exact variant twice without following it, and require unanimous stable identity behavior. Non-Darwin POSIX requires case-sensitive results; Windows requires case-insensitive results. Unsupported, mixed, unknown, failed, or target/parent-drifting observations fail before initial namespace access or lock acquisition; apply repeats the check under lock before backup or mutation. Legacy unscoped alpha backups are reported but never selected |
| Tampered, linked, corrupt, demo, or substituted backup is restored | State corruption, disclosure, or bypass of demo read-only policy | Backup selection requires canonical lowercase SHA-256 ID; bounded exact bytes must match the filename digest, current schema, and personal kind. POSIX directory/file ownership, mode, link count, and planned identities are rechecked under the inventory lock |
| Rollback is applied without reviewing hidden state | Private-note or routing-state surprise | Rollback is preview-only, emits sanitized current/candidate snapshots and note-change markers, binds the exact source and active state, and requires a second apply. It restores exact bytes only after creating a safety backup and preserves the source |
| Disaster recovery overwrites valid or unsafe active state | Loss, disclosure, or policy bypass | Recovery is separate from rollback and accepts only an absent target or a current-user-owned, single-link, private regular file whose bounded stable bytes are invalid. It refuses valid personal/demo, linked, special, insecure, oversized, unreadable, ACL-bearing, or ambiguous targets; apply binds and rechecks state, parent, source, and identities under lock, and missing-target commit uses an atomic exclusive link that refuses a newly appeared target |
| Invalid active bytes are lost or exposed through a recovery identifier | Loss of forensic or manually repairable state; guessing oracle for invalid private content | Before replacement, exact invalid bytes are durably stored in a private non-restorable quarantine namespace under an opaque apply-time CSPRNG identifier. Output never exposes their contents or a direct/derived content digest; missing targets have no displaced bytes. If a later apply step fails, the error reports the retained path and the manifest records the opaque ID and uncertain outcome |
| Backup filesystem metadata is mistaken for trustworthy chronology | Wrong retention or recovery decisions | Backup mtimes remain explicitly non-historical. Separately authorized applies append canonical, hash-linked prepared/outcome events under the inventory lock; sequence is authoritative, genesis marks earlier history unknown using a bounded backup-count/set-digest baseline, and unclosed operations remain uncertain. Capacity for required closures plus the next prepared/outcome pair is reserved before inventory mutation. The chain detects accidental modification but is not a signature, trusted clock, or hostile-account boundary |
| Retention deletes the wrong or last recovery point | Irrecoverable user-state loss | Deletion accepts one exact validated ID only, previews backup count, selected/remaining revision-privacy states, and irreversible effect, binds the active revision and complete validated backup set, and has no bulk/automatic/age mode. Last-backup deletion additionally binds explicit `--allow-no-backups` approval |
| Delete succeeds but verification or directory sync fails | Misleading retry or uncertain persistence | Once unlink succeeds, verification, POSIX namespace sync, or lock-cleanup failure returns an applied-but-uncertain receipt and exit code `4` with do-not-retry guidance |
| Large backup storage exhausts CPU, memory, or I/O during listing/retention | Local denial of service | Backup root/target scans stop after 4,096 entries and target content work stops after 64 MiB of entry bytes, including invalid entries; new safety backups fail before active replacement at capacity; no automatic pruning occurs |
| Crash leaves a permanent update lock | Availability loss | The lock file is persistent but the actual POSIX/Windows advisory lock is owned by an open descriptor and released automatically by the OS when the process exits |
| Resource name or path manipulates terminal output | Clipboard theft or display spoofing | User-facing resource, workstream, and project names reject control and Unicode format characters before storage or rendering; human-readable CLI paths, warnings, and expected errors escape non-printing characters |
| Demo-labeled data is mistaken for observed user access or verified synthetic content | Misleading routing or public claim | Personal initialization is empty; demo-labeled data is read-only, refused by default at routing, and visibly warned as user-controlled and unverified when explicitly allowed |
| Compromised dependency or release package | Code execution on user machines | Keep runtime dependencies minimal and bounded; lock the development/release test environment; exact-pin and hash-constrain the build backend; allowlist sdist/wheel content; repeat the private candidate build; and use restricted workflow permissions. Candidate checksums and the receipt are explicitly unsigned and do not prove publisher identity. An immutable reviewed commit, explicit trusted dependency index, and verified wheel/sdist attestations remain general-availability gates rather than current public-release claims |
| A substituted or stale installed plugin validator executes during review | Developer-machine code execution or false validation evidence | The repository wrapper requires an explicit system-skills directory, resolves only its expected validator path, rejects symlinks, oversized or group/world-writable files, and requires the reviewed SHA-256 before compiling the already verified bytes. It rechecks the installed file after validation and forgives only the exact legacy `policy.products` error for a locally validated current-policy skill. Any OpenAI validator update requires an explicit reviewed digest change; host capability or a new field never expands this allowlist automatically |
| Plugin resolves the wrong, spoofed, or incompatible local runtime | Incompatible behavior or code execution under the host's existing permissions | Resolve the already-required trusted `uv` by exact name, query only its absolute tool-bin directory offline and without config files, select the platform's exact `atready` executable there, and invoke it without a shell. Before every delegation, run one fixed `doctor` argument vector and accept only a bounded, strict JSON report with the required product, contract version, complete feature set, and explicit no-inventory-read/no-network/no-write effects. Fail closed on malformed lookup, missing file, nonzero output, duplicate or unexpected fields, contract/feature mismatch, or verification failure. Other `atready` commands on `PATH` are ignored. The caller-controlled uv executable, uv environment, and same-account tool bin remain trusted; compatibility is not publisher provenance |
| Markdown or URL output causes an automatic network request | Tracking or data exfiltration | Outputs are text; consumers must not auto-fetch remote images or open links without user action |
| Stale access, quota, cost, or measured-capacity data drives a poor recommendation | Unexpected cost or misleading subscription advice | Preserve amount, unit, scope, source, reset, and verification date; never compare unlike units; represent unknown values honestly; do not perform purchases or cancellations |

## Local file requirements

AtReady-owned local storage within this boundary must:

- use a per-user application data/configuration directory by default, while
  treating an explicit custom path as user-selected and unconstrained;
- on POSIX, use `0700` for a directory AtReady creates and `0600` for a
  sensitive file it creates;
- validate an existing parent directory without changing its permissions;
- on macOS, reject every extended ACL on directly validated sensitive files and
  directories rather than attempting allow/deny policy interpretation; ancestor
  ACL policy remains the user's responsibility;
- read a resource declaration file without modifying, copying, deleting, or
  retaining it; on POSIX require a current-user-owned, singly linked, regular
  `0600` source, use a nonblocking descriptor open to refuse special-file
  substitution, require two bounded descriptor reads to match exactly, and
  recheck descriptor/path identity, same-domain metadata, and macOS ACL state;
- reject a symlinked final parent or file target for sensitive writes;
- create new files exclusively; bind updates to a reviewed operation, canonical
  physical target, inspected target/parent identities, exact-byte revision, and
  complete candidate; preserve and sync a private exact-byte target-scoped
  backup before using same-directory atomic replacement;
- validate backup namespace/file ownership, modes, links, digest, schema, and
  personal classification before inspection, rollback, or deletion; never turn
  an arbitrary path, legacy unscoped file, glob, or time label into a selection;
- on POSIX, reject non-owned or group/other-writable direct parent directories
  for updates, unsafe writable ancestor chains, and unsafe target ownership,
  modes, or hard links;
- reject demo-inventory updates and visibly mark any explicitly allowed demo route;
- generate a fresh revision privacy nonce only during exclusive personal `init`,
  never expose its value through normal output, and reject private notes without one;
- never store credential values.

v0.1 does not configure or verify Windows ACLs, so it makes no owner-only access
guarantee on Windows. Users on non-POSIX platforms must choose a per-user
location with appropriate platform access controls.

If post-replacement validation or POSIX parent-directory durability, post-unlink
durability/verification, or lock cleanup is uncertain, the CLI reports that the mutation was applied, returns
the target and relevant backup IDs, and uses a distinct exit code. This avoids
describing an already-committed mutation as an ordinary pre-commit failure.

## Out of scope for v0.1

- Security of the user's operating system, AI host, or model provider.
- Malicious actions taken manually after a user copies a handoff.
- OAuth, API credentials, remote provider responses, billing APIs, or MCP
  servers, because v0.1 does not connect to them.
- A browser or network service, because v0.1 does not expose one.
- Automatic chronological, age-based, count-based, or bulk retention; no
  trusted clock or automatic retention policy exists for content-addressed,
  deduplicated states.

Out of scope does not mean safe by default. Adding any excluded feature requires
a new trust boundary, abuse cases, deterministic permission checks, privacy
disclosure, and tests before implementation.

## Review triggers

Review and revise this document before adding any of the following:

- broad or automatic CLI, environment, repository, account, provider, or MCP discovery beyond the
  exact-profile allowlisted executable/version check;
- network requests, hosted storage, telemetry, or crash upload;
- connectors, OAuth, provider status, authentication, billing, quota, or capacity access;
- tool invocation, shell/process execution, or automatic handoff delivery;
- purchasing, cancellation, or other consequential account actions; or
- a browser UI, local server, multi-user mode, or synchronization.
