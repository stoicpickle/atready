# Release Runbook

AtReady has three deliberately separate release lanes:

- `release-candidate.yml` builds unsigned private beta evidence;
- `public-release.yml` is the source-public GitHub release and provenance lane; and
- `runtime-release.yml` is an optional later PyPI lane that can publish `project-atready` from the
  private development repository through protected Trusted Publishing.

The first public product surface is the open-source CLI repository. The bundled Codex skill is an
optional adapter, and Plugin Directory submission is deferred. Committed workflow code is not
evidence that a GitHub environment, PyPI publisher, package, public release, OpenAI draft, approval,
or directory listing exists.

## What the private lane proves

`.github/workflows/release-candidate.yml` accepts one exact `main` commit and package version. It
refuses any dispatch or rerun not initiated by the configured release owner, and it requires a
successful push-CI run for that exact commit before checking out repository code. The job then:

- installs the locked test environment with pinned Python and uv setup actions;
- runs lint, formatting, plugin/skill contract tests, and the full branch-coverage suite;
- resolves the exact Hatchling build-backend set from `build-constraints.txt` with required
  SHA-256 hashes and an explicit PyPI index;
- builds the sdist and wheel twice with timestamps bound to the source commit and requires the two
  pairs to be byte-identical;
- checks both distributions strictly for PyPI metadata and long-description rendering, then parses
  the pinned renderer's HTML to refuse channel-relative or unsafe active links;
- verifies the sdist allowlist, wheel file set, source-byte identity, metadata, licenses, entry
  point, public project URLs, newline-normalized UTF-8 README text (CRLF and CR are treated as LF),
  and wheel `RECORD` hashes;
- smokes the exact wheel and staged plugin; and
- uploads only the wheel, sdist, `SHA256SUMS`, and `release-receipt.json` for seven days.

The receipt is canonical, deterministic, **unsigned candidate metadata**. It records the artifact
hashes and self-reported source/workflow identity so accidental drift and later substitution are
detectable. It is not an attestation, signature, trusted timestamp, protected-branch proof, or
publisher identity proof.

## Dispatch and inspect a candidate

Push the intended commit to `main`, wait for its six CI jobs to pass, and confirm the worktree and
remote agree. The repository Actions secret `ATREADY_RELEASE_OWNER` must contain the exact
GitHub username authorized to dispatch candidates; this works for both personal and
organization-owned repositories without granting every organization writer release authority.
Then dispatch the exact version at that commit:

```bash
set -euo pipefail
uv sync --locked --all-groups --no-group elevated --no-install-project
source_sha="$(git rev-parse HEAD)"
version="$(PYTHONPATH=src uv run --no-sync python -c \
  'import atready; print(atready.__version__)')"
git fetch --no-tags origin main:refs/remotes/origin/main
test "$(git rev-parse origin/main)" = "$source_sha"
gh workflow run release-candidate.yml \
  --ref main \
  -f source_sha="$source_sha" \
  -f version="$version"
```

After the run succeeds, download its exact named artifact into a new empty directory. Do not merge
files from two candidate runs:

```bash
set -euo pipefail
uv sync --locked --all-groups --no-group elevated --no-install-project
source_sha="$(git rev-parse HEAD)"
git fetch --no-tags origin main:refs/remotes/origin/main
test "$(git rev-parse origin/main)" = "$source_sha"
run_id="REPLACE_WITH_COMPLETED_RUN_ID"
candidate_dir="$(mktemp -d)"
gh run download "$run_id" \
  --repo stoicpickle/atready-dev \
  --name "release-candidate-$source_sha" \
  --dir "$candidate_dir"
uv run --no-sync python scripts/verify_release_artifacts.py --dist "$candidate_dir"
uv run --no-sync python scripts/release_bundle.py verify \
  --dist "$candidate_dir" \
  --repository stoicpickle/atready-dev \
  --source-commit "$source_sha" \
  --workflow-commit "$source_sha"
(cd "$candidate_dir" && shasum -a 256 -c SHA256SUMS)
```

This direct workflow is loaded from the same exact `main` commit required as `source_sha`, so its
expected workflow commit is the same SHA. If the workflow is later made reusable or loaded from a
different ref, this verification contract must change rather than assuming the digests coincide.

Record the run URL, source SHA, artifact name, GitHub-reported artifact digest, and local
verification result in release-review notes. Do not retain or publish a failed, partial, or locally
modified bundle.

To let a small named group exercise the successful bundle while the repository remains private,
use [`PRIVATE_BETA.md`](PRIVATE_BETA.md). The owner must approve access through an organization-owned
private beta repository and read-only tester team; do not add testers to the personal development
repository. The tester guide does not grant access or broaden the candidate's unsigned evidence
claims.

## Publish the public runtime from private source

`.github/workflows/runtime-release.yml` is the optional later PyPI lane. It accepts one
exact private `stoicpickle/atready-dev` `main` commit and runtime version, requires the owner
to dispatch it, and confirms successful push CI for that commit before checkout. Its build job runs
the same lint, format, branch-coverage, plugin/skill contract, reproducible-build, metadata,
rendering, exact-content, wheel, and staged-plugin gates as the candidate lane. It then uploads one
review bundle containing the exact wheel, source distribution, `SHA256SUMS`, and
`runtime-release-manifest.json`.

When `publish_pypi=true`, the second job waits at the protected `pypi` environment. After approval,
it downloads that exact build artifact, rejects any extra or missing file, verifies the manifest and
every digest against the run identity, and passes only the reviewed wheel and source distribution
to `uv publish`. It does not check out source or rebuild. Trusted Publishing supplies short-lived
OIDC upload identity; no PyPI API token belongs in the repository. A run with
`publish_pypi=false` is a non-publishing rehearsal and cannot later be promoted without a new build.

Before the first authorized runtime publication, Russ must perform these external actions:

1. Merge the reviewed workflow and release changes to private
   `stoicpickle/atready-dev/main`, then require all six platform/Python push-CI jobs to pass at
   the exact merge SHA.
2. Create the GitHub environment `pypi`, restrict it to `main`, and add the intended required
   reviewer. A sole owner approving their own deployment is a deliberate pause, not independent
   review; do not enable prevention of self-review unless another authorized reviewer exists.
3. Publish the final website, support, privacy, and terms pages, update the plugin and PyPI metadata
   together, and verify all four URLs anonymously. Do not set the workflow confirmation from an
   authenticated browser result or from planned content.
4. Immediately before release, confirm that the PyPI name `project-atready` is still
   available. Configure a pending Trusted Publisher with owner `stoicpickle`, repository
   `atready-dev`, workflow filename `runtime-release.yml`, and environment `pypi`. A pending
   publisher does not reserve the name.
5. Confirm repository Actions policy permits the exact pinned GitHub-owned actions and
   `astral-sh/setup-uv`, retains read-only defaults, and does not grant OIDC outside the protected
   publish job.

Dispatch the publishing run from the exact green private `main` commit:

```bash
set -euo pipefail
repository="stoicpickle/atready-dev"
source_sha="$(git rev-parse HEAD)"
version="$(PYTHONPATH=src uv run --no-sync python -c \
  'import atready; print(atready.__version__)')"
test "$(git branch --show-current)" = "main"
git fetch --no-tags origin main:refs/remotes/origin/main
test "$(git rev-parse origin/main)" = "$source_sha"
test "$(gh api "repos/$repository" --jq .visibility)" = "private"
gh api "repos/$repository/environments/pypi"
test "$(gh api --method GET "repos/$repository/actions/workflows/ci.yml/runs" \
  -f branch=main -f event=push -f status=success -f head_sha="$source_sha" \
  -f per_page=1 --jq .total_count)" -ge 1
gh workflow run runtime-release.yml \
  --repo "$repository" \
  --ref main \
  -f source_sha="$source_sha" \
  -f version="$version" \
  -f public_metadata_urls_verified=true \
  -f publish_pypi=true
```

While the publish job is waiting for `pypi` approval, download the build artifact into a new empty
directory. Inspect its schema-v2 `runtime-release-manifest.json`, verify `publish_requested` and
`public_metadata_urls_verified` are both `true`, confirm the separately recorded runtime and plugin
product versions, repository, source/workflow SHA, filenames, and hashes, then run:

```bash
set -euo pipefail
repository="stoicpickle/atready-dev"
uv sync --locked --all-groups --no-group elevated --no-install-project
source_sha="$(git rev-parse HEAD)"
version="$(PYTHONPATH=src uv run --no-sync python -c \
  'import atready; print(atready.__version__)')"
git fetch --no-tags origin main:refs/remotes/origin/main
test "$(git rev-parse origin/main)" = "$source_sha"
run_id="REPLACE_WITH_WAITING_RUN_ID"
review_dir="$(mktemp -d)"
artifact_dist="$(mktemp -d)"
gh run download "$run_id" \
  --repo "$repository" \
  --name "runtime-release-$source_sha" \
  --dir "$review_dir"
test "$(find "$review_dir" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')" = "4"
(cd "$review_dir" && shasum -a 256 -c SHA256SUMS)
cp "$review_dir/project_atready-${version}-py3-none-any.whl" "$artifact_dist/"
cp "$review_dir/project_atready-${version}.tar.gz" "$artifact_dist/"
uv run --no-sync python scripts/verify_release_artifacts.py --dist "$artifact_dist"
uv run --no-sync twine check --strict "$artifact_dist"/*
```

Only after that review should the owner approve the `pypi` environment. When the workflow succeeds,
download the exact version from PyPI, verify PyPI's advertised hashes, compare those bytes with the
reviewed wheel and source distribution, perform the external clean-install journey, and retain the
run URL, artifact digest, approval, PyPI version URL, hashes, and acceptance result. Workflow
success alone is not first-user proof.

## Public-source release lane

GitHub artifact attestations for private repositories require GitHub Enterprise Cloud; Free, Pro,
and Team support them only for public repositories. The private `atready-dev` repository
cannot honestly prove a GitHub build attestation. See GitHub's
[artifact-attestation availability](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations).

Opening the repository for an early source beta does not require a tagged GitHub release. Before
using this source-public release lane for immutable artifacts:

1. Make the repository public or move it to an eligible Enterprise Cloud organization.
2. Enable reviewed-branch/tag protections, immutable releases, workflow restrictions, full-SHA
   action enforcement, and an explicit release approver boundary where the plan supports them.
3. Configure a protected `github-release` environment with the intended maintainer as required
   reviewer. The workflow's publication job must stop at this boundary while the draft and its
   four exact assets are reviewed.
4. Verify the actual repository, signer-workflow path, source digest, signer digest, source ref, and
   GitHub-hosted runner policy. Do not replace any of those with placeholders or infer them from the
   unsigned candidate receipt.
5. Configure a separately protected `pypi` environment and PyPI Trusted Publisher only after
   explicit publishing authorization. The publisher identity must exactly name this repository,
   the workflow filename `public-release.yml`, and the `pypi` environment. The publish job must
   consume the already-reviewed immutable GitHub-release bytes rather than rebuild them.
6. Complete an external clean-account install, fresh-task plugin discovery, explicit activation,
   three synthetic routes, first-user mutation/recovery journey, removal, and data-preservation
   proof.

The source tree's `.github/workflows/public-release.yml` is intentionally manual. It refuses a
non-public repository, an owner dispatch without the explicit immutability-verification
confirmation, tag/version/source drift, or a source commit without successful `main` push CI. It
rebuilds twice through the constrained backend, attests only the reviewed wheel and sdist in a
least-privilege job, and creates a mutable draft with four exact assets in a separate no-OIDC job.
The protected `github-release` job rechecks the tag, publishes the approved draft, and requires
GitHub's release-attestation verification and `isImmutable` result to pass. Only then may the
independently protected `pypi` job download the four release assets, reject any extra/missing asset,
verify each asset against the immutable release attestation, byte-compare it with the reviewed
workflow artifact, and upload the released wheel and sdist without rebuilding. Adding this
workflow does not configure repository protections, environments, a Trusted Publisher, tags, or
any release.

GitHub documents that immutability applies only to releases published after it is enabled. It also
recommends the draft -> attach all assets -> publish sequence used here and automatically creates a
release attestation when that draft becomes immutable. See [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
and [release integrity verification](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity).

## Authority-gated public-source provenance checklist

Treat each group below as a separate owner decision. Source-complete workflow code is not evidence
that any repository or publisher setting has been changed.

1. **Merge authority:** merge the reviewed release PR to `main`, record the exact merge SHA, and
   require all six `main` push-CI jobs to pass at that SHA: Python 3.11 and 3.14 on Ubuntu, macOS,
   and Windows.
2. **Repository-owner authority:** make the repository public (or move it to an eligible Enterprise
   Cloud organization), enable immutable releases, retain read-only default workflow permissions,
   restrict Actions to GitHub-owned actions plus `astral-sh/setup-uv@*`, and require full-length SHA
   pins. If the repository owner, organization, or configured release owner changes, re-review the
   workflow's dispatch check and the PyPI publisher identity before proceeding.
3. **Protection authority:** create `github-release` and `pypi` environments with `v*` deployment
   tag rules and required reviewers. Add `main` and `v*` rulesets that block deletion and force
   pushes and require the exact checks `ubuntu-latest / Python 3.11`,
   `ubuntu-latest / Python 3.14`, `macos-latest / Python 3.11`,
   `macos-latest / Python 3.14`, `windows-latest / Python 3.11`, and
   `windows-latest / Python 3.14`. A required review by the same sole owner is a deliberate pause,
   not independent approval; enable prevention of self-review only when another authorized
   reviewer exists.
4. **PyPI-owner authority:** immediately before the first authorized upload, confirm that
   `project-atready` remains available and configure a pending Trusted Publisher with PyPI
   project `project-atready`, GitHub owner `stoicpickle`, repository `atready`, workflow
   filename `public-release.yml`, and environment `pypi`. A pending publisher does not reserve the
   project name. Do not add a PyPI API token or long-lived publishing secret.
5. **Tag authority:** only after the preceding settings are independently reviewed, create one new
   annotated `v<version>` tag at the recorded SHA, prove the created local and remote tag resolve to
   that SHA, and dispatch `public-release.yml` from the tag with the same version and SHA.
6. **Publication authority:** review the draft's exact four assets before approving
   `github-release`. Approve `pypi` only after the release is public, immutable, bound to the exact
   tag SHA, and every GitHub asset and build attestation verifies.
7. **Post-publication evidence:** download the exact four GitHub basenames, verify the release and
   each asset, verify the wheel and sdist build attestations, then download PyPI's exact authorized
   wheel and sdist and byte-compare them to the GitHub assets. Retain the commands, outputs,
   approvers, run URL, release URL, and PyPI version URL.

The current workflow proves GitHub build provenance and immutable-release integrity and uses PyPI
Trusted Publishing for short-lived upload identity. It does not create a separate PyPI publish
attestation bundle; do not describe Trusted Publishing or byte equality as that additional proof.

## Public-release preflight

Run these read-only checks against the actual public repository immediately before tagging. A 404
from the immutability endpoint means the control is not enabled. Inspect both environment responses
and confirm the expected required reviewer and deployment-branch/tag rules; their mere existence is
not approval proof.

The immutability endpoint requires repository Administration (read), a permission unavailable to a
workflow `GITHUB_TOKEN`. The owner therefore runs this check using their authenticated `gh` session
and explicitly confirms it in the dispatch input. The protected `github-release` reviewer must
reconfirm it before approval; GitHub's release attestation and `isImmutable` result are the hard
post-publication proof. Do not add a long-lived administrator token to the workflow for this check.

```bash
set -euo pipefail
repository="stoicpickle/atready"
source_sha="$(git rev-parse HEAD)"
version="$(PYTHONPATH=src uv run --no-sync python -c \
  'import atready; print(atready.__version__)')"
tag="v$version"

test "$(git branch --show-current)" = "main"
git fetch --no-tags origin main:refs/remotes/origin/main
test "$(git rev-parse origin/main)" = "$source_sha"
test "$(gh api "repos/$repository" --jq .visibility)" = "public"
test "$(gh api -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/$repository/immutable-releases" --jq .enabled)" = "true"
test "$(gh api "repos/$repository/actions/permissions" --jq .allowed_actions)" = "selected"
test "$(gh api "repos/$repository/actions/permissions" --jq .sha_pinning_required)" = "true"
test "$(gh api "repos/$repository/actions/permissions/workflow" \
  --jq .default_workflow_permissions)" = "read"
selected_actions="$(gh api "repos/$repository/actions/permissions/selected-actions")"
test "$(jq -r .github_owned_allowed <<<"$selected_actions")" = "true"
test "$(jq -r .verified_allowed <<<"$selected_actions")" = "false"
test "$(jq -c .patterns_allowed <<<"$selected_actions")" = \
  '["astral-sh/setup-uv@*"]'
gh api "repos/$repository/environments/github-release"
gh api "repos/$repository/environments/pypi"
test "$(gh api --method GET "repos/$repository/actions/workflows/ci.yml/runs" \
  -f branch=main -f event=push -f status=success -f head_sha="$source_sha" \
  -f per_page=1 --jq .total_count)" -ge 1
```

Also inspect the two environment responses for the intended required reviewers and `v*` deployment
tag policy. Confirm the `main` and `v*` rulesets cover this release and that no environment
administrator can bypass the intended reviewers. These controls are external state and cannot be
proved by committed YAML or the commands above.

## Tag and dispatch the exact public workflow

After explicit release authorization, create the annotated tag at that reviewed commit and push
only that tag. Dispatch the workflow from that exact tag so the GitHub OIDC source ref, workflow
definition, checkout, and tag target all bind to the same reviewed commit. Set `publish_pypi=false`
when the authorized outcome is GitHub release only. Either choice still pauses at `github-release`
for review before the draft can become public and immutable.

```bash
set -euo pipefail
if git show-ref --verify --quiet "refs/tags/$tag"; then
  echo "refusing to replace existing local tag: $tag" >&2
  exit 1
fi
if git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
  echo "refusing to replace existing remote tag: $tag" >&2
  exit 1
fi
git tag --annotate "$tag" "$source_sha" --message "AtReady $tag"
test "$(git rev-parse "$tag^{}")" = "$source_sha"
git push origin "refs/tags/$tag"
test "$(git ls-remote origin "refs/tags/$tag^{}" | awk '{print $1}')" = "$source_sha"
gh workflow run public-release.yml \
  --repo "$repository" \
  --ref "$tag" \
  -f source_sha="$source_sha" \
  -f tag="$tag" \
  -f version="$version" \
  -f immutable_releases_verified=true \
  -f publish_pypi=true
```

Before approving `github-release`, inspect the draft, its generated notes, and the exact asset set:
`SHA256SUMS`, `public-release-manifest.json`, the wheel, and the sdist. Approval publishes the draft;
immutable release verification is then a hard prerequisite for any PyPI job. If PyPI publication
was requested, its separate `pypi` environment must be approved only after the immutable-release
job succeeds. If GitHub's automatically generated release attestation is not immediately visible,
the publication job retries for a bounded 55 seconds and fails closed. Rerunning that failed job is
safe only for the same tag/source pair: it accepts either the expected draft or an already-published
immutable release at the exact source SHA and rejects every other state.

## Post-publication verification

Use a new empty directory, download from GitHub rather than the workflow artifact, and retain these
results with the release review record:

```bash
set -euo pipefail
verification_dir="$(mktemp -d)"
signer_workflow="$repository/.github/workflows/public-release.yml"
gh release verify "$tag" --repo "$repository"
test "$(gh release view "$tag" --repo "$repository" \
  --json isDraft --jq .isDraft)" = "false"
test "$(gh release view "$tag" --repo "$repository" \
  --json isImmutable --jq .isImmutable)" = "true"
test "$(gh api "repos/$repository/commits/$tag" --jq .sha)" = "$source_sha"
gh release download "$tag" --repo "$repository" --dir "$verification_dir"
expected_assets="$(mktemp)"
actual_assets="$(mktemp)"
printf '%s\n' \
  SHA256SUMS \
  public-release-manifest.json \
  "project_atready-${version}-py3-none-any.whl" \
  "project_atready-${version}.tar.gz" | sort > "$expected_assets"
for asset in "$verification_dir"/*; do
  test -f "$asset"
  basename "$asset"
done | sort > "$actual_assets"
cmp "$expected_assets" "$actual_assets"
for asset in "$verification_dir"/*; do
  gh release verify-asset "$tag" "$asset" --repo "$repository"
done
(cd "$verification_dir" && shasum -a 256 -c SHA256SUMS)
for artifact in \
  "$verification_dir/project_atready-${version}-py3-none-any.whl" \
  "$verification_dir/project_atready-${version}.tar.gz"; do
  gh attestation verify "$artifact" \
    --repo "$repository" \
    --signer-workflow "$signer_workflow" \
    --source-digest "$source_sha" \
    --signer-digest "$source_sha" \
    --source-ref "refs/tags/$tag" \
    --deny-self-hosted-runners
done
```

If PyPI publication was authorized, independently download the exact version's only wheel and sdist
from PyPI's release API, verify PyPI's advertised hashes, and require those bytes to equal the
already-verified GitHub release assets:

```bash
set -euo pipefail
pypi_dir="$(mktemp -d)"
PYPI_DIR="$pypi_dir" RELEASE_VERSION="$version" python - <<'PY'
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

version = os.environ["RELEASE_VERSION"]
root = Path(os.environ["PYPI_DIR"])
expected = {
    f"project_atready-{version}-py3-none-any.whl": "bdist_wheel",
    f"project_atready-{version}.tar.gz": "sdist",
}
api_url = f"https://pypi.org/pypi/project-atready/{version}/json"
request = Request(api_url, headers={"User-Agent": "atready-release-verifier/1"})
with urlopen(request, timeout=30) as response:
    payload = json.load(response)
records = payload.get("urls")
if (
    not isinstance(records, list)
    or len(records) != len(expected)
    or any(not isinstance(item, dict) for item in records)
    or {item.get("filename") for item in records} != set(expected)
):
    raise SystemExit("PyPI release does not contain the exact authorized wheel and sdist")
for item in records:
    name = item["filename"]
    url = item.get("url")
    digest = item.get("digests", {}).get("sha256")
    parsed = urlparse(url) if isinstance(url, str) else None
    if (
        item.get("packagetype") != expected[name]
        or item.get("yanked") is not False
        or not isinstance(digest, str)
        or parsed is None
        or parsed.scheme != "https"
        or parsed.hostname != "files.pythonhosted.org"
    ):
        raise SystemExit(f"PyPI returned unsafe metadata for {name}")
    request = Request(url, headers={"User-Agent": "atready-release-verifier/1"})
    with urlopen(request, timeout=60) as response:
        content = response.read(64 * 1024 * 1024 + 1)
    if len(content) > 64 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != digest:
        raise SystemExit(f"PyPI bytes failed the bounded SHA-256 check for {name}")
    (root / name).write_bytes(content)
PY
cmp \
  "$verification_dir/project_atready-${version}-py3-none-any.whl" \
  "$pypi_dir/project_atready-${version}-py3-none-any.whl"
cmp \
  "$verification_dir/project_atready-${version}.tar.gz" \
  "$pypi_dir/project_atready-${version}.tar.gz"
```

Record the release URL, workflow run URL, protected
environment approvers, source/workflow SHA, release verification output, asset hashes, build
attestation verification, and PyPI project/version URL if publication was authorized. Then perform
the external clean-account journey in `FIRST_USER_ACCEPTANCE.md`; workflow success alone is not
first-user proof.

Until these release gates pass, do not describe a GitHub source release as immutable, signed, or
attested. A public source beta may still exist without a tagged release, PyPI package, or OpenAI
directory listing; describe only the channels that have actually been verified.
