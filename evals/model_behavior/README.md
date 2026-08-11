# Historical model behavior scorecard

This historical research scorecard checks whether a host model communicates saved AtReady route
evidence accurately, briefly, and within the non execution boundary. It never calls a model,
provider, resource, or production service. Every committed case is synthetic. AtReady's current
release path uses deterministic CLI presentation instead, so this scorecard is not a release gate.

## Run a model manually

1. Start a fresh host session with the AtReady skill enabled.
2. Send `shared-instructions.txt`, followed by one unchanged file from `prompts/`, as one request.
   Do not add instructions between them. This gives every model the same compact response contract
   without duplicating it across four cases.
3. Save only the response text as `<case-id>.txt` in a temporary directory outside the repository.
4. Repeat for all four cases with the same model and settings.
5. Score the saved text:

```console
uv run python scripts/score_model_behavior.py /tmp/atready-model-responses \
  --report /tmp/atready-model-score.json
```

The command exits zero only when every case passes. The JSON report records the manifest path,
response path, counts, and every deterministic check. Preserve the model name, version, host,
settings, source commit, and report beside the temporary evidence. Do not commit transcripts.

The checks require assignment and gap facts to occur together in one sentence or line and enforce
the expected number of explicit gap claims. Order-independent synonym groups cover uncertainty,
support closure, and reserved-alternate safeguards without requiring one exact phrasing. The
scorecard also enforces the shared 80-word and six-nonempty-line caps, one exact final safety
boundary, selected resource mention counts, absence of raw router internals, and absence of claims
that execution or authorization occurred. These checks measure contract compliance, not writing quality or
whether a model is generally capable.

## Later RunPod lane

RunPod is an optional model diversity evaluation surface, not an AtReady runtime dependency. Do
not start a pod or spend credits without a separate, explicit authorization naming the model,
region, GPU, maximum wall time, and maximum credit spend.

The first authorized lane should use this unchanged manifest, synthetic prompts only, one GPU,
at most two hours, and at most USD 10 in credits, stopping at whichever cap occurs first. The
operator may invoke a model on RunPod and save its response files, but AtReady and this scorer must
remain offline and provider neutral. Never upload a personal roster, account metadata, credentials,
private project text, or prior private plans. Stop the pod after collection and score the saved text
locally.

Passing this lane would show only that the tested model version followed this response contract on
these cases. It would not make RunPod a production dependency or prove compatibility with other
models.

## First model-diversity baseline

On 2026-08-10, the first authorized RunPod baseline used
`Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8`, one RTX 6000 Ada GPU, temperature `0.2`, top-p `0.9`, and
300 output tokens. It sent the four case files without a shared response contract. All four failed:
answers exceeded the caps, repeated evidence, weakened gap or role language, and omitted the exact
final boundary. No personal data was used, the temporary Pods were deleted, the account showed no
active Pods afterward, and the displayed balance changed by about USD 0.10.

That baseline motivated `shared-instructions.txt`. It is historical evidence, not a result for the
hardened prompt and not a claim about the model's general quality. Do not spend more credits until
the offline contract tests pass; a later provider run requires a new explicit authorization.

The separately authorized hardened rerun used the same model, GPU class, and sampling settings,
with `shared-instructions.txt` prepended to each unchanged case. It also scored 0/4. Brevity
improved materially, but the model still emitted extra line fragments, repeated resource names,
invented empty gaps or actions, and sometimes wrote after the final boundary. The temporary Pod was
deleted, no active Pod was shown immediately after cleanup, and the displayed balance changed by
roughly another USD 0.10.

This result is evidence against relying on a prose-only prompt as a universal final renderer for
smaller models. AtReady now uses a deterministic presentation built from the same calculation as
the complete route JSON. The bundled skill returns that summary verbatim for normal and concise
responses instead of asking the host model to reconstruct it. Offline fixture tests cover the
straightforward, unconfirmed, support, and alternate cases and require assignment meaning, compact
resource grouping, plain language, and the exact final boundary. No additional paid model run is
needed to prove this renderer because model generation is no longer in that output path.
