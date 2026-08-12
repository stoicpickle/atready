# Distribution Contract

AtReady is a CLI-first open-source product. The Python package contains the deterministic engine
and the `atready` command. The repository also carries an optional Codex skill that can guide the
same workflow conversationally; it does not replace the CLI or broaden its permissions.

## Artifact split

| Artifact | Identity | Contains | Does not contain |
| --- | --- | --- | --- |
| Python package and CLI | `project-atready` / `atready` | The deterministic command, schemas, routing logic, and a bundled copy of the optional skill | Telemetry, connectors, provider execution, or automatic handoff execution |
| Optional Codex skill package | `atready` | `.codex-plugin/plugin.json` and the canonical `project-atready` skill | The Python package, hooks, apps, MCP servers, connectors, telemetry, or an implicit installer |

The CLI runtime currently uses product version `0.1.8`, while the optional Codex plugin uses
product version `0.1.9`, but product-version equality is no longer the compatibility boundary. The plugin
declares runtime contract version `1` and its required stable
feature IDs. Its launcher resolves the already-required `uv` executable through the caller's
`PATH`, asks it offline and with configuration files disabled for the absolute tool-bin directory,
selects only the platform's exact `atready` executable there, and invokes `doctor` with a
fixed argument vector and no shell. It strictly parses the bounded JSON result and delegates only
when the runtime contract version matches and every required feature is present. Plugin and runtime
product versions remain visible diagnostics but may differ.

`atready runtime contract --json` reports the runtime's canonical contract, while
`atready doctor --plugin-version VERSION --plugin-contract 1 --require-feature ID --json`
checks a proposed plugin requirement set. Both reports are value-free: they read no inventory,
access no network, and write nothing. The launcher never installs, upgrades, repairs, or enumerates
tools. A trusted `uv` executable and startup environment remain prerequisites, and a compatible
report does not prove who supplied the executable. Users remain responsible for installing both
artifacts from intended release channels.

The plugin manifest's `Read`, `Write`, and `Interactive` capability labels describe the host
workflow candidly. They are not grants. The skill's narrower contract still limits reads to
approved project/inventory inputs, uses only private temporary project-brief writes, and keeps every
inventory mutation preview-first and separately authorized.

## Channel topology

The private development and candidate source of truth is `stoicpickle/atready-dev`. Reviewed
snapshots are promoted to the public `stoicpickle/atready` repository. The first public beta uses a
source install from that repository; PyPI is a later convenience after its exact release lane is
ready and independently verified. Local/repository plugin marketplaces remain optional authoring
and testing channels.

The `stoicpickle/atready` repository received its first clean source snapshot and was anonymously
verified as public on 2026-08-09. That proves only the public source-beta channel; it is not a PyPI
package, immutable release, general-availability claim, or OpenAI review.

This means the intended promotion flow is:

```text
private development -> reviewed public source beta -> optional PyPI package
```

OpenAI's skills-only package validator permits website, support, privacy, and terms URLs to be
omitted from the manifest; MCP-backed packages require them there. The public submission guide
still requires all four materials for its listing and final checklist. Those listing materials are
deferred with directory submission. The open-source beta can use the public repository's README,
issues, security policy, license, and project documents as its initial support and trust surfaces
once their anonymous URLs are verified.

## Source and private-release validation

The canonical plugin is [`plugins/atready`](../plugins/atready). The repository
marketplace is [`.agents/plugins/marketplace.json`](../.agents/plugins/marketplace.json). The host
must already have a trusted `uv` on the Codex process's `PATH`, a plugin-capable Codex release, and
a directly invocable Python 3 interpreter for the stdlib-only launcher. `uv tool install` may use
an isolated managed Python and does not by itself satisfy that launcher prerequisite. Before
installation, verify `python3 --version` on POSIX or `py -3 --version` on Windows from the
environment that will start Codex; do not install an interpreter implicitly during skill use.

A local development install is explicit:

```bash
uv tool install --force /absolute/path/to/atready
codex plugin marketplace add /absolute/path/to/atready
codex plugin add atready@atready
```

`uv tool install` creates an isolated CLI environment and exposes its console command through uv's
tool-bin directory; it does not make the Python module importable in the host interpreter. The
plugin asks that same trusted `uv` for the directory and does not resolve `atready` from
`PATH`. Verify the intended installer authority and install:

```bash
uv --version
ar_uv_bin="$(uv --offline --no-config tool dir --bin)"
"$ar_uv_bin/atready" --version
codex plugin list --marketplace atready
```

On Windows, invoke `atready.exe` from the absolute directory reported by that same uv command.

Start a new Codex task after installation; an already-running task does not prove fresh plugin
discovery. Invoke the `project-atready` skill explicitly and use only synthetic data for the
first-user proof. Remove a disposable local plugin, marketplace, and CLI install with:

```bash
codex plugin remove atready@atready
codex plugin marketplace remove atready
uv tool uninstall project-atready
```

Those commands change the user's Codex plugin configuration and cache. The automated repository
smokes instead copy the plugin to a temporary directory and run it against an isolated installed
wheel, so routine CI does not edit a developer's Codex configuration.

The manually dispatched private candidate workflow is documented in
[`docs/RELEASING.md`](RELEASING.md). It builds twice through a hash-constrained exact backend,
enforces the sdist/wheel content and public-metadata boundaries, checks PyPI rendering strictly,
runs the repository gates and smokes, and retains one four-file candidate bundle. Its receipt and
checksums are unsigned review metadata, not release provenance or publication.

Named private-repository collaborators can test one exact successful candidate without a public
release by following [`PRIVATE_BETA.md`](PRIVATE_BETA.md). That path uses an exact source checkout
for the local Codex marketplace and its workflow-built compatible local runtime. Candidate metadata
records plugin and runtime product versions separately; the contract/feature handshake, not label
equality, is the compatibility gate. This path does not claim PyPI publication, OpenAI review,
public provenance, or general availability.

## Deferred plugin install contract

The following is retained as a possible later path. It is not part of the first open-source beta
and is not a claim that either channel is live today:

1. Install the version of the local runtime named by the release notes from the official PyPI
   project. This is supporting infrastructure; normal use begins in the plugin rather than the
   terminal.
2. Install AtReady from the universal Plugins Directory in a supported ChatGPT or Codex
   surface.
3. Start a fresh task, ask AtReady to check runtime compatibility, and follow its specific
   remediation command only if the check fails.

The same trusted `uv`, directly invocable Python 3, and startup-environment prerequisites apply.
The public runtime command is intentionally version-bounded until the compatibility contract has a
stable release range:

```bash
uv tool install --no-config --default-index https://pypi.org/simple \
  'project-atready==0.1.8'
```

The explicit index applies to the runtime and its dependencies, and `--no-config` prevents user uv
configuration from selecting another index. PyPI artifacts are publicly downloadable and
inspectable even when their source repository remains private. The plugin must never silently
install or upgrade the runtime; it diagnoses compatibility, presents an exact command, and verifies
the result after the user runs it.

## Later package and plugin gates

- Use `public-release.yml` only when a tagged, immutable, attested GitHub/PyPI release is desired;
  opening the reviewed source beta does not itself claim those release properties. The optional
  `runtime-release.yml` lane can later publish the package from private development source. Both are
  workflow code, not evidence that external controls or publication exist.
- Confirm ownership of the `project-atready` PyPI name, configure a protected Trusted
  Publisher for the actual private source repository and workflow, publish only after explicit
  owner approval, and independently install the exact wheel and source distribution from PyPI.
- Replace the reserved private GitHub website/support/privacy/terms URLs with anonymously reachable
  HTTPS pages that match the verified publisher identity. Then update the plugin manifest, PyPI
  project URLs, and directory packet together.
- Maintainer-review the source-complete public-directory metadata, privacy/terms copy, and synthetic
  artwork in [`DIRECTORY_SUBMISSION.md`](DIRECTORY_SUBMISSION.md). Skills-only plugins are submitted
  through the OpenAI Platform plugin submission portal documented in
  [Submit plugins](https://developers.openai.com/plugins/deploy/submission); the owner must first
  confirm verified identity and Apps Management write permission, then explicitly authorize the
  external submission and retain review evidence. No directory submission is claimed yet.
- Before PyPI or directory publication, prove those channels' installation, discovery,
  compatibility, removal, and data-preservation behavior from an external clean account or machine.
- Verify any published release artifacts against the committed public source and retain
  cross-platform CI evidence.

Describe AtReady as a public open-source beta. Do not use “generally available,” “immutable
release,” “published on PyPI,” or “OpenAI-reviewed” until those separate package, release,
directory, review, and external first-user gates are verified.
