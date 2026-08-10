# Bundled-kernel feasibility spike

This isolated experiment asks whether a plugin-extracted, dependency-free Python kernel can replace
the installed AtReady runtime without weakening the product's safety or routing semantics.
It does **not** create a second router.

The module has one deliberately deep interface: `assess(canonical_receipt, runtime)`. The harness
runs the exact synthetic `init -> preview add -> exact-token apply -> route` journey through the
canonical runtime, then passes a sanitized receipt to the extracted-style bundle under
`python -I -S`. The bundle can validate that receipt using only the standard library. It accepts no
inventory path and exposes no mutation or routing operation.

Run it from the repository development environment:

```console
uv run python experiments/bundled-kernel/harness.py
```

Current decision: **stop**. The isolated probe proves that local bundle loading and receipt
validation work without `uv`, site-packages, or network access. It also proves that the candidate
does not cover any of the four runtime journey steps. Full parity still requires the canonical
model/YAML semantics, revision and plan-token write engine, private backups and atomic replacement,
and deterministic router. Copying subsets of those systems into the plugin would create a drifting
mini-router, so this candidate must not be treated as a release runtime.

This is synthetic-only evidence. The harness confines canonical writes to an ephemeral temporary
directory and removes it before reporting.
