# Local runtime setup and unsupported surfaces

This AtReady probe candidate is a Codex-only skills plugin. Its planning and inventory operations
delegate to a separately distributed local `project-atready` runtime. The plugin never
installs, upgrades, or searches broadly for that runtime.

## Supported local setup

The host must be able to run a local Python 3 interpreter, the bundled launcher, and an already
installed trusted `uv`. After the maintainer publishes a reviewed runtime release to PyPI, the user
installs the exact release named in the release notes themselves:

```bash
uv tool install --no-config --default-index https://pypi.org/simple \
  'project-atready==RELEASE_VERSION'
```

Do not replace `RELEASE_VERSION` with a guessed, moving, or unreleased version. The bundled
launcher performs the authoritative compatibility check before every operation. Return to the
AtReady plugin flow and retry there after installation; do not invoke a bare `atready`
executable as a substitute for the bundled launcher. Plugin and runtime product versions may
differ; compatibility requires the same runtime contract version and every feature required by the
plugin.

If the launcher reports an incompatible runtime, the user may explicitly update the runtime to a
reviewed release and retry in a fresh task. Never run an install or update command on the user's
behalf, never bypass the launcher, and never weaken its contract or feature checks.

## Unsupported host surface

If the current Codex surface cannot execute the bundled local launcher or cannot access
the user's local inventory, stop before inventory access, preview, routing, or mutation. Explain in
plain language that this AtReady release requires a compatible local runtime and local file
access. You may explain the product or help the user prepare non-sensitive setup steps, but do not
pretend the inventory was loaded, a route was generated, or a write was completed.

Do not ask the user to paste private inventory, private notes, credentials, environment variables,
or account configuration into chat as a workaround.
