from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

from atready.runtime_contract import (
    RUNTIME_CONTRACT_VERSION,
    SUPPORTED_RUNTIME_FEATURE_IDS,
    doctor_payload,
)

SKILL = Path(__file__).parents[1] / "plugins" / "atready" / "skills" / "project-atready"


def _markdown_h3_section(text: str, heading: str) -> str:
    marker = f"### {heading}"
    match = re.search(rf"^{re.escape(marker)}$", text, re.MULTILINE)
    assert match is not None, f"missing H3 section: {heading}"
    remainder = text[match.end() :]
    next_heading = re.search(r"^#{1,3} ", remainder, re.MULTILINE)
    section = remainder if next_heading is None else remainder[: next_heading.start()]
    return marker + section


def _write_cli_fixture_wheel(
    path: Path,
    *,
    version: str,
    required_features: tuple[str, ...] = SUPPORTED_RUNTIME_FEATURE_IDS,
) -> Path:
    distribution = "atready_fixture"
    dist_info = f"{distribution}-{version}.dist-info"
    wheel = path / f"{distribution}-{version}-py3-none-any.whl"
    fixture_report = json.dumps(
        doctor_payload(
            plugin_version=version,
            plugin_contract_version=RUNTIME_CONTRACT_VERSION,
            required_features=required_features,
        )
    )
    expected_doctor = [
        "doctor",
        "--plugin-version",
        version,
        "--plugin-contract",
        str(RUNTIME_CONTRACT_VERSION),
    ]
    for feature in required_features:
        expected_doctor.extend(("--require-feature", feature))
    expected_doctor.append("--json")
    members = {
        "atready_fixture.py": (
            "import json\n"
            "import sys\n\n"
            "def main():\n"
            f"    if sys.argv[1:] == ['--version']:\n"
            f"        print('atready {version}')\n"
            "        return\n"
            f"    if sys.argv[1:] == {expected_doctor!r}:\n"
            f"        print({fixture_report!r})\n"
            "        return\n"
            "    raise SystemExit(2)\n"
        ).encode(),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.4\nName: atready-fixture\nVersion: {version}\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: atready-tests\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n"
        ),
        f"{dist_info}/entry_points.txt": (b"[console_scripts]\natready = atready_fixture:main\n"),
    }
    record = []
    for name, contents in members.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=").decode()
        record.append(f"{name},sha256={digest},{len(contents)}")
    record.append(f"{dist_info}/RECORD,,")
    members[f"{dist_info}/RECORD"] = ("\n".join(record) + "\n").encode()

    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in sorted(members.items()):
            archive.writestr(name, contents)
    return wheel


def test_skill_frontmatter_and_resources_are_portable() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---", 2)
    normalized_body = " ".join(body.split())
    metadata = yaml.safe_load(frontmatter)

    assert metadata["name"] == "project-atready"
    assert set(metadata) == {"name", "description"}
    assert "TODO" not in body
    assert body.count('"/absolute/path/to/project-atready/scripts/atready.py"') >= 8
    assert "Never invoke the bare CLI or bypass the launcher" in normalized_body
    assert "never searches `PATH` for `atready`" in normalized_body
    assert "offline and without configuration files" in normalized_body
    assert re.search(r"(?m)^\s*atready(?:\s|$)", body) is None
    assert "inventory validate /absolute/path/to/inventory.yaml" in body
    assert "inventory list /absolute/path/to/inventory.yaml --json" in body
    assert "--resource-file /absolute/private/resource.yaml" in body
    assert "--resource-stdin --json" in body
    assert "schema resource-declaration" in body
    assert "argv-safe only" in body
    assert "host/model context" in body
    assert "never use `echo`, `printf`, a shell literal, or a heredoc" in normalized_body
    assert "review them in the source" in body
    assert "remove the exact temporary file and directory before yielding" in body
    assert "new protected" in body
    assert "temporary directory" in body
    assert "--inventory /absolute/path/to/inventory.yaml" in body
    assert "explicitly approves that complete preview" in body
    assert "--expect-plan <preview" in body
    assert "Exit code `4`" in body
    assert "Never retry it" in body
    assert "command history" in body
    assert "inventory backup rollback" in body
    assert "inventory backup delete" in body
    assert "--allow-no-backups" in body
    assert "separately approves that rendered preview" in body
    assert "Never infer approval for recovery, rollback" in body
    assert "Do not substitute bundled synthetic resources" in body
    assert all(
        f"`{status}`" in body
        for status in (
            "selected-primary",
            "selected-support",
            "reserved-alternate",
            "deliberately-unused",
            "unavailable",
            "ineligible",
            "unverified",
        )
    )
    assert "never replace their exact statuses" in normalized_body
    assert "explicit inventory/project/resource-declaration paths" in body
    assert "explicit non-interactive" in body
    assert "resource stdin" in body
    assert "hidden revision privacy nonce" in body
    assert "Never" in body
    assert "ask the user to paste that nonce" in body
    assert "There is no supported in-place migration or rotation" in body
    assert "inventory annotate set" in body
    assert "inventory annotate clear" in body
    assert "## Choose the intent" in body
    assert "**Resource setup:**" in body
    assert "**Project planning:**" in body
    assert "**Maintenance or recovery:**" in body
    assert "Do not combine setup and routing" in body
    assert "Keep the user's project plan primary" in body
    assert "Meet the user at the planning pivot" in body
    assert "goal, loose plan, or written plan" in normalized_body
    assert "a user-authored formal brief is not a prerequisite" in normalized_body
    assert "smallest useful ordered workstreams" in normalized_body
    assert "references/model-routing.md" in body
    assert "references/runtime-setup.md" in body
    assert "never override the CLI's resource assignment" in normalized_body
    assert "Return the user's project plan first" in normalized_body
    assert "show them only" in normalized_body
    assert "when requested or when a material gap requires the detail" in normalized_body
    assert "Lead with the selected resources, then the route and handoffs" not in normalized_body
    assert "Do not activate for ordinary project planning" in metadata["description"]
    assert len(text.splitlines()) < 500
    assert (SKILL / "scripts" / "atready.py").is_file()
    assert (SKILL / "references" / "routing-rules.md").is_file()
    assert (SKILL / "references" / "output-contract.md").is_file()
    assert (SKILL / "references" / "runtime-setup.md").is_file()
    assert (SKILL / "references" / "resource-onboarding.md").is_file()
    assert (SKILL / "references" / "model-routing.md").is_file()


def test_guided_resource_onboarding_contract_is_one_at_a_time_and_preview_first() -> None:
    body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference_path = SKILL / "references" / "resource-onboarding.md"
    reference = reference_path.read_text(encoding="utf-8")
    normalized = " ".join(reference.split())
    folded = normalized.casefold()

    assert "[resource-onboarding.md](references/resource-onboarding.md)" in body
    assert "one resource at a time" in folded
    assert "keep additional resources in a names-only queue" in folded
    assert "**Quick Setup**" in reference
    assert "**Detailed Setup**" in reference
    assert "Assisted Setup presented as Quick Setup" in reference
    assert reference.count("`schema resource-declaration`") == 1
    assert "exactly once for this onboarding task" in folded
    assert "default to assisted setup" in folded
    assert "do not spend a turn on a mode choice" in folded
    assert "put all four groups in one intake card" in folded
    assert "keep the first assistant response under 250 words" in folded
    assert "one compact, prefilled card" in folded
    assert "render exactly the four visible bullets" in folded
    assert "the goal is one easy reply, not a schema interview" in folded
    assert "**Easy reply:**" in reference

    output_contract = (SKILL / "references" / "output-contract.md").read_text(encoding="utf-8")
    output_folded = " ".join(output_contract.split())
    assert "keep the user's project plan primary" in output_folded
    assert "Do not render score traces, every omission, the full execution route" in output_folded
    assert "When the user requests the expanded AtReady result" in output_folded
    assert "lead with the proposed useful entry" in folded
    assert "one grouped human-language intake card" in " ".join(body.split())
    assert "a lowercase resource id only as a proposal" in folded
    assert "require the user to confirm it" in folded
    assert "label proposals only, not claims" in folded
    assert "stable, machine-readable label" in folded
    assert all(
        phrase in reference
        for phrase in (
            "`basic` -> `0.40`",
            "`solid` -> `0.65`",
            "`strong` -> `0.80`",
            "`exceptional` -> `0.95`",
        )
    )
    assert all(
        phrase in folded
        for phrase in (
            "**identity:**",
            "**strengths:**",
            "**readiness and capacity:**",
            "**safety:**",
        )
    )
    assert "Accept these remaining first-pass defaults" in reference
    assert "an undecided baseline, not verified quality" in folded
    assert "do not replace them with raw enum labels" in folded
    assert "Review agent (review-agent)" in reference
    assert "code review (code-review)" in folded
    assert re.search(r'"not sure" is valid for\s*>?\s*readiness facts', normalized, re.IGNORECASE)
    assert "whether it requires internet access" in folded
    assert "unknown network boolean is a repair item" in folded
    assert "answering this intake card supplies facts only" in folded
    assert "does not authorize a preview or save" in folded
    assert "at most one consolidated repair question" in folded
    assert "never drip one field per turn" in folded
    assert "one substantive intake reply" in folded
    assert "**Scoring-input defaults:**" in reference
    assert "Do not call these universally" in reference
    assert "task-local safety baseline" in folded
    assert "require per-resource confirmation" in folded
    assert "never reuse capabilities" in folded
    assert "Never infer" in reference
    assert all(
        phrase in folded
        for phrase in (
            "identity and categories",
            "capabilities and scores",
            "access and provenance",
            "economics",
            "eight ratings",
            "policy",
            "handoff",
            "best/avoid",
        )
    )
    assert "neutral `0.5` defaults" in reference
    for rating_name in (
        "quality",
        "speed",
        "autonomy",
        "privacy",
        "reliability",
        "confidence",
        "context_switch_cost",
        "integration_friction",
    ):
        assert f"`{rating_name}`" in body
    assert "never ask for its value in chat" in folded
    assert "do not ask a separate private-note question" in folded
    assert "do not echo it" in reference
    assert "revoke or rotate it" in reference
    assert "AtReady cannot perform or verify that rotation" in reference
    assert "billing and best/avoid values are descriptive only" in folded
    assert "`approval_required: false` never authorizes execution" in reference
    assert all(
        status in reference
        for status in (
            "`declared-unavailable`",
            "`requires-verification`",
            "`selection-facts-declared`",
        )
    )
    assert "does not prove live availability" in reference
    assert "assess staleness separately" in folded
    assert "explicit preview authorization" in folded
    assert "Ready for the no-write preview?" in reference
    assert "It will not save" in reference
    assert "Save exactly this entry?" in reference
    assert "back up the current roster" in reference
    assert "general intent such as `preview-first`" in folded
    assert "is not authorization for the exact recap" in folded
    assert "Show the actual CLI preview" in reference
    assert "second explicit approval" in folded
    assert "do not preview or apply a second resource" in folded
    assert "inventory validate" in reference
    assert "--strict" in reference
    assert "separate, explicit route authorization" in folded
    assert "AtReady can now consider it in future plans" in reference
    assert "only when the user explicitly asks to test the new entry" in folded
    assert "made-up public project" in folded
    assert "without contacting the resource" in folded
    assert "creates inert handoff text" in folded
    assert "dispatching the handoff, or executing" in folded
    assert "fixed normalized project brief and inventory snapshot" in folded
    assert "fixed-input deterministic routing wiring" in folded
    assert "complete same-ID declaration, not a merge" in reference
    assert "`resource profiles --json`" in reference
    assert "public plugin workflow is conversation-only" in folded
    assert "performs no local executable or version inspection" in folded
    assert "`resource discover" not in reference
    assert "--inspect-version" not in reference
    assert "measured capacity" in folded
    assert "never compare or convert unlike units" in folded
    assert "one resource at a time" in folded


def test_coderabbit_quick_setup_is_tailored_editable_and_nonexecuting() -> None:
    reference = (SKILL / "references" / "resource-onboarding.md").read_text(encoding="utf-8")
    section = _markdown_h3_section(reference, "CodeRabbit Quick Setup")
    folded = " ".join(section.split()).casefold()

    for proposal in (
        "`coderabbit`",
        "`Code review agent (review-agent)`",
        "`Code review (code-review)`",
        "`Repository analysis (repository-analysis)`",
        "`Review requests (review-request)`",
        "`Files reviewed (review-file)`",
    ):
        assert proposal.casefold() in folded
    assert "### coderabbit quick setup" in folded
    assert "show these catalog values as editable proposals" in folded
    assert "render exactly these four visible question bullets" in folded
    assert "choose cli, pr reviews, or both" in folded
    assert "rate code review and repository analysis separately" in folded
    assert "**cli:**" in folded
    assert "**pr reviews:**" in folded
    assert "**both:**" in folded
    assert "which path should be the one routing-visible `interaction`" in folded
    assert "`coderabbit-cli` and `coderabbit-pr`" in folded
    assert "one measured-capacity envelope" in folded
    assert "never convert or combine unlike units" in folded
    assert (
        "no onboarding answer authorizes a coderabbit review, pull request, "
        "login, installation, update, settings change, provider contact, declaration preview, or "
        "roster save"
    ) in folded
    assert "rely on your declared readiness" in folded
    assert "executable, version, configuration, or account" in folded
    assert "keep all profile labels" in folded
    assert "strengths, usage mode, readiness, capacity, safety, and defaults editable" in folded


def test_opencode_quick_setup_collects_only_planning_relevant_declared_facts() -> None:
    reference = (SKILL / "references" / "resource-onboarding.md").read_text(encoding="utf-8")
    section = _markdown_h3_section(reference, "OpenCode Quick Setup")
    folded = " ".join(section.split()).casefold()

    for proposal in (
        "`OpenCode`",
        "`Coding agent (coding-agent)`",
        "`Code implementation (code-implementation)`",
        "`Code review (code-review)`",
        "`Repository analysis (repository-analysis)`",
        "`Software planning (software-planning)`",
        "`Agent tasks (agent-task)`",
        "`Tokens (token)`",
        "`Provider credits (credit)`",
    ):
        assert proposal.casefold() in folded
    assert "### opencode quick setup" in folded
    assert "facts that change a project plan" in folded
    assert "interactive terminal session (`local-cli`)" in folded
    assert "non-interactive cli task (`codex-callable`)" in folded
    assert "desktop/ide use (`manual`)" in folded
    assert "only when it materially changes" in folded
    assert "never request or retain its api key" in folded
    assert (
        "no onboarding answer authorizes opencode execution, provider "
        "access, model enumeration, configuration changes, declaration preview, or roster save"
    ) in folded
    assert "rely on your declared readiness" in folded
    assert "installation, configuration, providers, models, or an account" in folded
    assert "render exactly these four visible question bullets" in folded
    assert "rate only the work your configured opencode setup actually handles well" in folded


def test_pixel_art_quick_setups_distinguish_tiers_products_and_manual_capacity() -> None:
    reference = (SKILL / "references" / "resource-onboarding.md").read_text(encoding="utf-8")
    section = _markdown_h3_section(reference, "Pixel-art tool Quick Setup profiles")
    folded = " ".join(section.split()).casefold()

    for profile in ("**pixellab (`pixellab`):**", "**retro diffusion (`retro-diffusion`):**"):
        assert profile in folded
    for capability in (
        "pixel-art generation",
        "sprite generation",
        "animation",
        "pixel-art editing",
    ):
        assert capability in folded
    for tier_contract in (
        "pixel apprentice with 2,000 images per month up to 320x320",
        "pixel artisan with 5,000 images per month up to 512x512 plus up to 10 concurrent jobs",
        "pixel architect with 10,000 images per month plus up to 20 concurrent background jobs",
        "only as dated vendor proposals",
    ):
        assert tier_contract in folded
    for retro_contract in (
        "credit-based cloud website",
        "one-time-purchase local aseprite extension",
        "found no website subscription",
        "website credits do not expire",
        "larger images can cost more than one credit",
        "never translate a credit balance into a fixed image count",
    ):
        assert retro_contract in folded
    for capacity_contract in (
        "one governing capacity unit",
        "exact remaining amount",
        "basis, and checked date",
        "does not refresh or decrement balances",
        "complete `inventory replace` request",
    ):
        assert capacity_contract in folded
    assert (
        "do not inspect a project gallery, provider account, authentication, purchase history, "
        "subscription, credit balance, api configuration, or credentials"
    ) in folded
    assert (
        "no tier, product surface, declared balance, or catalog proposal authorizes api use, "
        "asset generation, account access, declaration preview, roster save, or any provider "
        "action"
    ) in folded


def test_model_routing_reference_keeps_provider_copy_out_of_scores_and_hidden_selection() -> None:
    reference = (SKILL / "references" / "resource-onboarding.md").read_text(encoding="utf-8")
    model_routing = (SKILL / "references" / "model-routing.md").read_text(encoding="utf-8")
    onboarding_section = _markdown_h3_section(reference, "Model-aware resource variants")
    folded = " ".join((onboarding_section + "\n" + model_routing).split()).casefold()
    # The model-aware section and model-routing reference own routing claims. The generic Quick
    # Setup section owns the confirmed-value exceptions, so those four checks use the full corpus.
    full_folded = " ".join((reference + "\n" + model_routing).split()).casefold()

    for resource_id in (
        "`cursor-composer-2-5`",
        "`cursor-grok-4-5`",
        "`opencode-deepseek-v4-flash-free`",
        "`grok-4-5`",
    ):
        assert resource_id in folded
    assert "dated catalog proposals" in folded
    assert "not live provider facts" in folded
    assert "not opencode's universal default" in folded
    assert "each requires its own user-confirmed capabilities" in folded
    assert "generic provider entry when model selection is automatic, unknown" in folded
    assert "provider metadata to one compact line" in folded
    assert "entire first response still stays under 250 words" in folded
    assert "do not copy them into capability scores" in folded
    assert "do not invite them to accept baseline `0.5`" in folded
    assert "relevant capability strengths, speed, and relative marginal cost" in folded
    assert "`0.25`, `0.50`, `0.75`, and `0.95`" in folded
    assert "roster does not yet encode a model-aware preference" in folded
    assert "the dated planning role changed routing by itself" in folded
    assert "keep the relative cost and speed you just confirmed" in full_folded
    assert "other seven comparison ratings at 0.5" in full_folded
    assert "marginal cost `0.5` unless model-aware relative cost was confirmed" in full_folded
    assert "except a confirmed model-aware speed value" in full_folded
    assert "deterministic router still selects resource entries, not hidden models" in folded
    assert "shared_capacity_group" in model_routing
    assert "does not coordinate or reserve a shared pool" in folded
    assert "cursor-hosted grok and standalone xai grok" in folded
    assert "never turn a promotional allowance, provider benchmark" in folded


def test_popular_coding_agent_quick_setups_share_the_planning_only_boundary() -> None:
    reference = (SKILL / "references" / "resource-onboarding.md").read_text(encoding="utf-8")
    section = _markdown_h3_section(reference, "Other coding-agent Quick Setup profiles")
    folded = " ".join(section.split()).casefold()

    for profile in (
        "**cursor (`cursor`):**",
        "**claude code (`claude-code`):**",
        "**google antigravity (`antigravity`):**",
        "**github copilot (`github-copilot`):**",
    ):
        assert profile in folded
    for capability in (
        "code implementation",
        "code review",
        "repository analysis",
        "software planning",
        "multi-agent orchestration",
        "debugging",
        "github workflow support",
    ):
        assert capability in folded
    assert "rely on your declared readiness" in folded
    assert "installation, configuration, models, providers" in folded
    assert "exactly four visible bullets" in folded
    assert "one routing-visible workflow" in folded
    assert "only when it materially changes declared capability" in folded
    for boundary in (
        "no profile lookup or onboarding answer authorizes login",
        "account or usage inspection, repository analysis, file changes, shell commands",
        "cloud/background delegation, model selection, provider contact",
        "declaration preview, or roster save",
        "never inspect cursor rules or dashboard state",
        "any credential store, or environment-variable values",
    ):
        assert boundary in folded


def test_guided_resource_input_transport_prefers_real_stdin_and_exact_cleanup() -> None:
    body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    folded = " ".join(body.split()).casefold()

    assert "signal an explicit end-of-input without a terminal" in folded
    assert "cannot close stdin does not qualify" in folded
    assert "do not rewrite a created `/var/...` source path" in folded
    assert "remove only the exact file with `unlink`" in folded
    assert "exact empty directory with `rmdir`" in folded
    assert "do not use `rm`, recursive cleanup" in folded
    assert (
        "do not create a directory or materialize declaration bytes before that authorization"
        in folded
    )


def test_openai_metadata_matches_skill_name() -> None:
    metadata = yaml.safe_load((SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]

    assert interface["display_name"] == "AtReady"
    assert interface["short_description"] == "Plan with what's at the ready"
    assert len(interface["short_description"]) <= 30
    assert "$project-atready" not in interface["default_prompt"]
    assert "Use AtReady" in interface["default_prompt"]
    assert "rough project idea" in interface["default_prompt"]
    assert "before implementation" in interface["default_prompt"]
    assert "saved resources fit" in interface["default_prompt"]
    assert set(metadata) == {"interface", "policy"}
    assert metadata["policy"] == {
        "allow_implicit_invocation": False,
        "products": ["CODEX"],
    }


def test_runtime_setup_reference_is_safe_and_self_contained() -> None:
    reference = (SKILL / "references" / "runtime-setup.md").read_text(encoding="utf-8")
    normalized = " ".join(reference.split())

    assert "uv tool install --no-config --default-index https://pypi.org/simple" in reference
    assert "project-atready==RELEASE_VERSION" in reference
    assert "atready runtime contract --json" not in reference
    assert "retry there after installation" in normalized
    assert "do not invoke a bare `atready` executable" in normalized
    assert "Plugin and runtime product versions may differ" in normalized
    assert "Never run an install or update command on the user's behalf" in normalized
    assert "cannot execute the bundled local launcher" in normalized
    assert "do not pretend the inventory was loaded" in normalized
    assert "Do not ask the user to paste private inventory" in normalized


def test_checkout_wrapper_ignores_an_earlier_path_atready(tmp_path: Path) -> None:
    wrapper = SKILL / "scripts" / "atready.py"
    launcher = runpy.run_path(str(wrapper))
    plugin_version = launcher["PLUGIN_VERSION"]

    uv = shutil.which("uv")
    assert uv is not None
    tool_bin = tmp_path / "uv-bin"
    tool_dir = tmp_path / "uv-tools"
    fixture_wheel = _write_cli_fixture_wheel(
        tmp_path,
        version=plugin_version,
        required_features=launcher["REQUIRED_RUNTIME_FEATURE_IDS"],
    )
    install_environment = os.environ.copy()
    install_environment["UV_TOOL_BIN_DIR"] = str(tool_bin)
    install_environment["UV_TOOL_DIR"] = str(tool_dir)
    installed = subprocess.run(  # noqa: S603
        [
            uv,
            "--offline",
            "--no-config",
            "tool",
            "install",
            "--no-cache",
            "--no-python-downloads",
            "--python",
            sys.executable,
            str(fixture_wheel),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=install_environment,
        timeout=30,
    )
    assert installed.returncode == 0, installed.stderr
    installed_cli = tool_bin / ("atready.exe" if sys.platform == "win32" else "atready")
    assert installed_cli.is_file()

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_name = "atready.exe" if sys.platform == "win32" else "atready"
    fake = fake_bin / fake_name
    fake.write_text("not the installed AtReady CLI", encoding="utf-8")
    fake.chmod(0o700)

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    environment["UV_TOOL_BIN_DIR"] = str(tool_bin)
    environment["UV_TOOL_DIR"] = str(tool_dir)
    assert Path(shutil.which("atready", path=environment["PATH"]) or "") == fake

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(wrapper), "--version"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"atready {plugin_version}\n"
