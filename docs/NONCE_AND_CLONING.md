# Revision privacy nonce and cloning

Every inventory created by the current `atready init` contains a fresh `nonce-v1` value. The
nonce blinds exact-file revisions and backup IDs while it remains undisclosed. It is not encryption,
authentication, access control, a credential, or proof that imported state was generated safely.
Normal CLI output reports only `nonce-v1-present`; that proves syntax and presence, not freshness,
uniqueness, provenance, or secrecy.

## Choose the intended lineage

| Situation | Supported v0.1 action | Why |
| --- | --- | --- |
| Move or restore one private inventory as continuity of the same lineage | Preserve the exact inventory or use an exact AtReady backup | Exact continuity intentionally retains the nonce, notes, formatting, and revision identity. Keep only the intended active lineage private. |
| Use one raw inventory as two independently maintained inventories | Initialize a new target and re-declare resources there | A raw copy reuses the nonce. `nonce-v1-present` cannot establish an independent private lineage. |
| A raw inventory or its nonce may have been exposed | Preserve the old file privately, initialize a new target, and re-declare resources | Disclosure removes the revision-blinding property. There is no supported in-place recovery claim. |
| Import a legacy inventory with no nonce and no private notes | It can remain `legacy-unblinded`, or resources can be re-declared into a newly initialized target | v0.1 never injects a nonce silently. |
| Import a legacy inventory with private notes | Do not use it as active v0.1 state; initialize a new target | Note-bearing unblinded state fails closed. |

For a new independent lineage, review and re-declare routing-visible resource data through normal
previews. Re-enter resource-level private notes through protected structured file or stdin input only
after reviewing the new target. Re-enter root inventory-level notes with `inventory annotate set`
from a protected note-only declaration; use `inventory annotate clear` when the reviewed intent is
to remove them. Both operations require preview, exact revision, exact plan token, private backup,
and atomic replacement. Keep the old inventory until the new target has been validated and its
required annotations have been accounted for.

## Deliberate non-features

v0.1 has no `rotate`, `migrate`, clone, merge, or in-place nonce-injection command. It also does not
rewrite historical backups. Adding fresh entropy during preview would break deterministic plan
replay, while rotating only active state would leave older backups carrying the old nonce. A future
migration needs a separately reviewed backup, rollback, disclosure, and authorization contract.

The synthetic acceptance harness in [`FIRST_USER_ACCEPTANCE.md`](FIRST_USER_ACCEPTANCE.md) checks the
current boundary: an exact continuity copy has the same nonce-backed bytes, a separately initialized
target does not, and neither nonce is emitted by normal CLI output.
