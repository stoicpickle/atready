# AtReady plugin surface probe

This source-controlled document is a synthetic, value-free probe contract for the local marketplace
lifecycle pilot and a possible future Directory phase. It is not a live receipt, submission,
approval, publication, publisher-account record, or general-availability claim. Keep dated runs,
commit identifiers, account permissions, portal state, and transcripts in the private release
evidence store rather than this repository.
Read [PLUGIN_DIRECTORY_PILOT.md](PLUGIN_DIRECTORY_PILOT.md) before running a probe.

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

## Availability and evidence matrix

Current official documentation says plugins work in Chat and Work across ChatGPT web, desktop, and
mobile; in Codex they work in the ChatGPT desktop app, and Codex CLI provides a plugin browser. The
Codex IDE extension does not support plugins. That is a platform matrix, not a promise that this
local-runtime plugin works on every available surface.

Every live probe run must produce one value-free result row for each relevant surface. The candidate
claims only local Codex and Codex CLI. All other surfaces must be hidden or safely stop before an
actionable workflow.

| Surface | Pilot status | Required result/evidence |
| --- | --- | --- |
| Local repository marketplace | Automated local evidence | Isolated profile proves discover, install, exact cached copy, runtime handshake, removal, and unchanged synthetic state. |
| OpenAI plugin portal | Unproved; not authorized | A future draft retains the exact candidate policy without submission. |
| Codex local desktop/task | Claimed target; unproved | Fresh task proves explicit activation, compatibility before inventory access, and synthetic routing. |
| Codex CLI | Claimed target; lifecycle automated, conversation unproved | Automated lifecycle proves packaging and compatibility; a fresh session still must prove explicit activation and synthetic routing. |
| ChatGPT Chat/Work on web, desktop, or mobile | Platform supports plugins generally; CODEX-only AtReady is not a target | Hide AtReady or stop clearly before intake, preview, routing, or mutation. |
| Codex remote or cloud | Unproved; not an AtReady target | Hide AtReady or stop clearly before local runtime or inventory work. |
| Codex IDE extension | Platform unavailable | Do not claim plugin availability; record any contrary appearance as a platform finding, not support. |

## Generic probe checklist

1. Run `uv run python scripts/plugin_lifecycle_acceptance.py` with the current installed runtime.
2. Run a fresh synthetic Codex CLI task through the locally installed plugin.
3. Build a disposable probe ZIP and local receipt from a clean reviewed commit.
4. Apply the stop/go rule without inferring support from visibility alone.
5. Only after separate owner authorization, obtain the required publisher identity and portal
   permissions, create a draft, and verify that it retains the exact candidate policy. Do not submit.
6. Collect hide-or-safe-stop evidence for every non-target surface that exposes the candidate.
7. Record versioned host/runtime details, the exact result, and value-free evidence privately.
8. Build a distinct final ZIP only after every required surface passes.

See OpenAI's current [plugin availability documentation](https://developers.openai.com/codex/plugins)
and [plugin packaging documentation](https://developers.openai.com/plugins/build/plugins). Recheck
both before a portal action.
