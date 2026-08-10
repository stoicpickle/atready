# AtReady plugin surface probe

This source-controlled document is a synthetic, value-free probe contract. It is not a live
receipt, submission, approval, publication, publisher-account record, or general-availability
claim. Keep dated runs, commit identifiers, account permissions, portal state, and transcripts in
the private release evidence store rather than this repository.

## Candidate policy

The disposable probe candidate must declare exactly:

```yaml
policy:
  products: [CODEX]
  allow_implicit_invocation: false
```

The probe artifact is not the final release artifact and must never be submitted or published.

## Stop/go rule

**STOP PUBLIC SUBMISSION / CONTINUE LOCAL PROBE DEVELOPMENT** until every claimed surface has a
retained synthetic result. An unsupported surface must either hide AtReady or communicate the
incompatibility before presenting an actionable starter workflow. Stop when a user can begin an
advertised workflow on a surface that cannot run the compatible local runtime or access the
selected local inventory.

Portal acceptance, publisher approval, clean-machine installation, and other operating systems
remain unproved until a value-free external receipt demonstrates them. Submission for review
requires separate owner authorization. Later publication requires a second separate owner
authorization.

## Evidence matrix

Every live probe run must produce exactly one value-free result row for each surface below. The
source template deliberately marks every surface hidden while it is unproved.

| Surface | Required unproved result | Evidence required for a future pass |
| --- | --- | --- |
| OpenAI plugin portal | Unproved; must be hidden | Draft accepts and retains the exact candidate policy without submission |
| ChatGPT web/chat | Unproved; must be hidden | Fresh synthetic conversation proves visibility and a safe pre-invocation boundary |
| ChatGPT desktop chat | Unproved; must be hidden | Fresh synthetic conversation proves visibility and a safe pre-invocation boundary |
| Codex desktop local/worktree | Unproved; must be hidden | Fresh task proves explicit activation, runtime compatibility, and synthetic routing |
| Codex CLI | Unproved; must be hidden | Fresh task proves packaged-path resolution and the bounded runtime handshake |
| Codex IDE | Unproved; must be hidden | Supported host proves explicit activation and local-filesystem compatibility |
| Codex cloud/Remote | Unproved; must be hidden | Surface hides AtReady or stops before local inventory/filesystem work |

## Generic probe checklist

1. Obtain the required publisher identity and portal permissions outside this repository.
2. Build a disposable probe ZIP from a clean reviewed commit.
3. Create a draft only; do not submit it.
4. Verify that the portal accepts and retains the exact candidate policy.
5. Collect the evidence required by each matrix row: draft-policy retention for the portal, fresh
   synthetic conversations for ChatGPT, fresh tasks for Codex desktop and CLI, a supported-host
   check for Codex IDE, and the defined stop condition for Codex cloud/Remote.
6. Record versioned host/runtime details, the exact result, and value-free evidence privately.
7. Apply the stop/go rule without inferring support from visibility alone.
8. Build a distinct final ZIP only after every required surface passes.
