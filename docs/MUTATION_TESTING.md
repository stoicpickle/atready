# Targeted mutation testing

Mutation testing is an elevated manual audit for routing and inventory-safety tests. It is not a
required check on every pull request. The ordinary suite, seeded routing stress tests, Hypothesis
properties, and state machine remain the fast gates.

## Fast default gate

Ordinary pytest and pull-request runs use a bounded generative profile:

```console
time uv run pytest -q tests/test_routing_properties.py
```

The tests use synthetic fixtures and temporary personal rosters only. They deny network access in
routing cases, never read the configured personal roster, and retain 12 composite route examples,
8 dominated-resource transformations, and 6 state-machine examples of 5 steps. The existing
96-case seeded routing corpus remains unchanged.

## Elevated generative profile

Before a release or after changing routing or inventory mutation semantics, restore the deeper
campaign explicitly:

```console
time env ATREADY_ELEVATED_HYPOTHESIS=1 \
  uv run pytest -q tests/test_routing_properties.py
```

The elevated profile runs 40 composite route examples, 24 dominated-resource transformations, and
20 state-machine examples of 8 steps. Setting any value other than exact `1` keeps the fast default.

## Prepare the mutation tool

Install the optional elevated group without changing the application runtime:

```console
uv sync --group dev --group elevated
uv run mutmut --version
```

The checked-in `tool.mutmut` configuration mutates only `src/atready/routing.py`, copies the
synthetic fixtures, and selects only routing, seeded-stress, and property/stateful tests. Mutmut
generates its configured source tree before filtering named mutants, so keep each audit targeted
and time-boxed.

## Focused audit

Start with the deterministic router, using one worker to keep the run predictable:

```console
time uv run mutmut run "atready.routing*" --max-children 1
uv run mutmut results
```

Mutant names can drift between Mutmut releases. If a pattern matches nothing, run
`uv run mutmut browse`, copy the current fully qualified names, and retry the narrow selection.
Do not broaden automatically to the inventory-edit module. Its safety surface is large and already
has fault-injection tests; schedule any future inventory mutation campaign as a separately scoped
change with its own time budget and test selection.

## Review survivors

For each surviving mutant:

1. Inspect it with `uv run mutmut show <mutant-name>`.
2. Decide whether it exposes a missing public-behavior assertion, an equivalent mutation, or dead
   code.
3. Add a focused public-seam regression test only for a real gap.
4. Rerun that mutant and the ordinary focused suite.

Record the source commit, Mutmut version, exact target patterns, elapsed time, killed/survived
counts, and any deliberately accepted equivalent mutants. Do not commit Mutmut's generated
`mutants/` workspace or treat an interrupted run as a passing audit.

The first bounded baseline on 2026-08-12 generated 1,085 routing mutants. The interrupted sample
reached 207 mutants, killed 179, and left 28 unreviewed survivors; the remaining mutants were not
run. This proves the lane is executable, not that the mutation gate passes. Review a smaller named
function slice before using mutation results as release evidence.
