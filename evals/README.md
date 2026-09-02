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

Planning communication is checked separately across the default CLI summary and optional Codex
skill. The [plan communication evaluation](PLAN_COMMUNICATION_EVAL.md) compares both human
responses with the same CLI JSON evidence. The Codex skill uses the deterministic `summary` from a
single presentation envelope rather than asking the host model to rewrite the route. Explicit word
and line limits are enforced by the CLI; an impossible limit returns deterministic conflict copy
without changing route evidence. The evaluation covers straightforward assignment, an unconfirmed
resource that leaves a gap, complementary support, a reserved alternate, and exact summary parity.
It also measures five reader comprehension questions with a 100% safety comprehension requirement. Run
`uv run pytest tests/test_plan_communication_eval_contract.py` for its static contract, then run
the manual cases in fresh Codex tasks. Static tests do not prove real model behavior.

Elevated checks add two bounded implementation lanes. `scripts/elevated_install_matrix.py`
exercises a synthetic staged launcher handshake plus complete, incomplete, and conflicting
duplicate-skill states. `tests/test_routing_stress.py` generates seeded synthetic route cases. The
install matrix does not substitute for a clean-machine wheel installation.

The [model behavior scorecard](model_behavior/README.md) is retained as a historical research
comparison for the prose-rendering approach that preceded deterministic CLI presentation. It never
calls a model and is not a current release gate. Actual model behavior still requires running the
unchanged prompts in fresh host sessions and preserving the resulting local evidence.

Resource-intake behavior is covered separately because it spans the host skill and the preview-first
CLI contract rather than the deterministic routing fixture set. The synthetic first-user acceptance
journey exercises a Quick Add declaration with explicit readiness, safety, and provenance facts;
checks the grouped `intake_review`; proves a first route from that resource; and then replaces it
with a fully detailed declaration. That journey runs against both the source checkout and the
installed wheel. The skill contract tests cover the host-facing Quick Add and Detailed Setup
instructions. Run `uv run pytest tests/test_first_user_acceptance.py tests/test_skill_contract.py`.

The [blank-slate resource-intake evaluation](RESOURCE_INTAKE_EVAL.md) is the manual host surface
check for turns to preview, repeated questions, plain language explanations, technical mapping
confirmation, unknown handling, and preview and apply separation. Run it in a new Codex task with
only synthetic data before a release that changes resource intake. Its transcript template belongs
in a local evaluation evidence packet. Do not commit real user or account context here.

The [provider-free conversation hardening lane](conversation_hardening/README.md) turns the shared
intake, routing, correction, and authorization contracts into a repeatable offline scorecard. It
scores actual deterministic route summaries where possible and reports host-model probes
separately instead of treating instruction text as proof of model behavior. Run
`uv run python evals/conversation_hardening/score.py` before a release that changes conversational
workflow or output.

The [fresh-host conversation matrix](conversation_hardening/fresh_host/README.md) prepares a
private, disposable packet for a human-observed host run. It checks correction, approval, concise
follow-up, hostile text, and exact deterministic summaries without storing a real roster or account
facts. Its offline scorer remains operator-attested: preparing or scoring a packet does not prove a
fresh host was isolated or that the model behaved correctly.

The [decision-change benchmark](decision_change/README.md) asks the product question behind those
contracts: does roster context change a fresh host's proposed resource choices in a useful,
understandable, actionable way? It pairs a baseline response with an exact AtReady route across five
synthetic projects. Route fidelity is deterministic; usefulness and task isolation remain explicitly
operator-attested and are not independent user-value proof.

Routing invariants also have a bounded Hypothesis property and state-machine lane in
`tests/test_routing_properties.py`. The optional [mutation-testing runbook](../docs/MUTATION_TESTING.md)
describes a slower, manual routing audit. An interrupted mutation sample is evidence that the lane
runs, not a passing release gate.

The fixtures describe products only. They do not authenticate, call, or endorse the named services.
