# Security Policy

## Supported versions

AtReady is in the `0.x` development series and has not published a stable
release. Until the first tag, security fixes target the latest revision on the
default branch. After `0.x` tags begin, fixes target the newest tagged `0.x`
release and the default branch; older `0.x` releases are unsupported unless a
security advisory says otherwise. Security fixes may require breaking changes
while the project remains pre-1.0.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository when
it is available. Include:

- the affected version or commit;
- the relevant file, command, or workflow;
- clear reproduction steps;
- the security or privacy impact; and
- any suggested mitigation.

Do not include secrets, private inventory, or exploit details in a public
issue. If private reporting is unavailable, open a minimal public issue titled
`Security contact request` without vulnerability details so a private channel
can be arranged.

Please allow maintainers time to reproduce and address a report before public
disclosure. Acknowledgment and remediation timing depend on severity and
maintainer availability; no response-time guarantee is offered.

## v0.1 security boundary

AtReady v0.1 separates a local CLI from optional AI-host skill workflows. The personal skill and
the Codex-only Directory candidate are distinct distribution surfaces. The CLI makes no provider
calls itself and does not dispatch handoffs or invoke resources for project work. Its
separately authorized optional version command executes one external program with fixed arguments
and unevaluated external side effects. When the skill is
used, project and inventory context may be processed by the configured AI host or model provider;
local storage does not mean local-only processing.

The v0.1 boundary is:

- inventory and preferences are user-controlled local files;
- AtReady operates no backend and collects no telemetry;
- it has no connectors or automatic or broad capability discovery;
- its optional local discovery checks one explicitly authorized, profile-allowlisted executable
  name or exact path and treats installation evidence as unconfirmed; optional version execution
  requires a second authorization and has unevaluated external side effects;
- it does not inspect credential values;
- an explicitly named adapter-neutral resource-state file may provide session, quota, and capacity
  evidence for one route only; it is validated, overlaid in memory, and never persisted;
- it does not invoke inventoried resources for project work or dispatch handoffs; and
- generated handoffs and commands are advisory and display-only.

The current Directory candidate is a separate Codex-only, skills-only artifact. It declares no
apps, MCP servers, connectors, hooks, telemetry, or installer. Its launcher resolves the separately
installed runtime without a shell and refuses a runtime-contract mismatch or missing required
feature. Product versions may differ; compatibility is not a substitute for release provenance.
It does not claim ChatGPT Chat/Work or Codex cloud/remote functionality.

Use through an AI host is a separate trust boundary. Inventory and project
context loaded into a hosted model may leave the machine under the host and
model provider's terms. See `PRIVACY.md`.

## Security invariants

Contributions must preserve these properties unless a documented, reviewed
release deliberately changes the product boundary:

1. Recommendation is not authorization or execution.
2. Descriptive fields such as `active` or `callable` never grant permission.
3. Untrusted inventory, project text, and model output are data, not executable
   instructions.
4. No secret value is required in an inventory, preference, example, test
   fixture, log, or generated plan.
5. Generated commands are never passed automatically to a shell or tool.
6. CLI reads are limited to bounded answers entered after explicit TTY-only `atready add`, explicit
   inventory/project/resource-declaration/resource-state paths, explicit non-interactive resource stdin, the
   resolved default inventory path, one explicitly requested profile-allowlisted executable check,
   and the adjacent target-scoped backup namespace for explicit backup commands. The host skill may
   read only project-relevant files needed for the
   requested plan; it does not crawl unrelated directories, the home directory,
   or environment/MCP configuration.
7. Public examples and tests use synthetic projects, inventories, and resource metadata. They
   contain no real credentials or secret values.
8. Synthetic demo inventory is never silently treated as personal state and
   requires explicit opt-in before routing.
9. Persistent inventory updates are preview-first, bound to both the original
   bytes and reviewed candidate/target, backed up, and limited to personal
   inventories.
10. User-facing names reject terminal control and Unicode format characters.
11. Backup operations are scoped to one logical inventory target; exact IDs are
    derived internally and never accepted as arbitrary paths.
12. Rollback restores validated exact bytes only after creating a safety backup.
    Deletion removes one validated exact ID only and has no automatic or bulk mode.
13. Structured resource input is versioned, bounded, single-resource, and
    value-redacted on every diagnostic path. Hidden private notes are represented
    only by presence and remain bound to the plan token. Users must not store
    credentials in private notes.
14. Fresh personal inventories carry an undisclosed, CSPRNG-generated `nonce-v1`
    revision privacy nonce. Any inventory-level or resource-level private note,
    including an empty string, requires one. Its value is persisted in exact bytes
    but omitted from normal output, routing fingerprints/snapshots, supported
    CLI/loader diagnostics, and object reprs. Python traceback/frame introspection
    and low-level Pydantic structured errors are developer surfaces, not redacted APIs.
15. Catalog profiles are editable label proposals, never capability, account, access, billing,
    quota, or availability facts. Locate-only executable discovery is separately authorized and
    exact-scope. Optional version inspection requires a second authorization, is shell-free and
    time/output bounded, and reports the external program's network/write side effects as not
    evaluated. No observation becomes a persisted resource fact without user confirmation.
16. Resource-state evidence is untrusted, provider-neutral input. It is limited to one bounded,
    explicitly named file, exact resource IDs already in the selected inventory, and session/quota/
    capacity fields with source, timestamp, confidence, and expiry metadata. Unknown or duplicate
    IDs, credential/account ID fields, unknown fields, snapshots past a supplied `valid_until`, stale
    manual or estimated state, unknown confidence, or state newer than the project date or route
    evaluation instant fail closed. Expired
    capacity remains an explicit exact-demand gate. The overlay changes only one in-memory route and
    never grants authority, refreshes, contacts a provider, or persists state. Route fingerprints
    are unsalted reproducibility identifiers over routing-visible facts, not confidentiality
    controls; the value-free standalone validation receipt omits them. Field-name rejection is not
    content scanning: allowed string values, including `source`, are not inspected for secrets.
    Users must not put credentials or other sensitive values in any allowed resource-state field.

The detailed permission and threat boundaries are documented in
`docs/PERMISSIONS.md` and `docs/THREAT_MODEL.md`.

## Security-sensitive changes

Changes involving parsing, filesystem access, model context construction,
logging, packaging, dependencies, generated commands, permissions, or release
automation require focused review. Features involving discovery, connectors,
credential access, network requests, telemetry, or execution require a threat
model and privacy review before implementation, not only before release.
Resource-state schema, freshness, overlay precedence, and stale/expiry behavior
also require focused review; they must not broaden the provider-neutral local
boundary.

## User responsibilities

- Keep real inventory and preference files out of public repositories.
- Do not place tokens, passwords, private keys, or cookies in AtReady
  data.
- Review model-provider data controls before supplying confidential context.
- Treat generated handoffs and commands as untrusted suggestions until a human
  reviews them.
- Verify the destination, data shared, permissions, and expected cost before
  copying a handoff to another tool.
- Review every previewed value, canonical target, revision, and plan token before applying any
  inventory or backup mutation. Protect target-scoped backup directories like the active file.
  Rollback restores hidden private notes; deletion is irreversible.
- Treat command-line arguments and output as potentially retained by shell,
  host, process-monitoring, and terminal-history systems.
- Review the exact profile, executable path, and requested fact before local discovery. A located
  command or version does not prove authentication, account status, quota, availability, or safety.
- Treat file/stdin declarations as argv-safe only: protect the source and its
  producer, review hidden notes in that source, and assume routing-visible preview
  output can be retained by the terminal, host, logs, or model context.
- Treat route-only resource-state files as user-supplied evidence: review the exact
  resource IDs and source/timestamp/confidence/expiry fields, and do not interpret
  them as live provider, account, quota, or capacity truth. Field-name validation does not scan
  allowed values for secrets; do not put sensitive values in `source` or other allowed fields.
- Treat the revision privacy nonce as undisclosed blinding state, not a public salt
  or credential. Raw inventory/backup access reveals it; if it may have leaked,
  initialize a new inventory rather than editing or inventing a replacement.
- On macOS, AtReady rejects every extended ACL on sensitive storage it
  validates. Inspect ACL intent before removing entries or choose another protected
  location; AtReady does not classify allow versus deny entries.
