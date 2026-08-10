# Public synthetic evaluations

These fixtures test AtReady's distinctive routing behavior without using a real person's
inventory, account metadata, billing data, or project names.

- `project-godot.yaml`: Codex owns architecture and implementation; CodeRabbit owns review.
- `project-web.yaml`: Codex builds; OpenRouter, Upstash, and Vercel own their narrow service lanes.
- `project-art.yaml`: native image generation explores concepts; Scenario creates the asset family;
  Aseprite owns cleanup and export.
- `project-degraded.yaml` with `inventory-degraded.yaml`: routing excludes an exhausted preferred
  resource in favor of an available coder, complementary specialists pair as primary and support, and private
  work excludes a higher-scoring public-only resource.

Every run must produce exact primary assignments, one disposition per inventory resource, complete
handoffs, a repeatable plan hash, and no network calls. Run `uv run pytest tests/test_evals.py`.

Resource-intake behavior is covered separately because it spans the host skill and the preview-first
CLI contract rather than the deterministic routing fixture set. The synthetic first-user acceptance
journey exercises a Quick Add declaration with explicit readiness, safety, and provenance facts;
checks the grouped `intake_review`; proves a first route from that resource; and then replaces it
with a fully detailed declaration. That journey runs against both the source checkout and the
installed wheel. The skill contract tests cover the host-facing Quick Add and Detailed Setup
instructions, while the directory reviewer packet retains the manual positive and negative prompt
cases. Run `uv run pytest tests/test_first_user_acceptance.py tests/test_skill_contract.py`.

The [blank-slate resource-intake evaluation](RESOURCE_INTAKE_EVAL.md) is the manual host-surface
check for turns to preview, repeated questions, plain-language explanations, technical mapping
confirmation, unknown handling, and preview/apply separation. Run it in a new Codex task with only
synthetic data during private beta and again for the directory reviewer packet. Its transcript
template belongs in the evidence packet; do not commit real user or account context here.

The fixtures describe products only. They do not authenticate, call, or endorse the named services.
