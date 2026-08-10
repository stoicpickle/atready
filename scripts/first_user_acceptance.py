"""Run the synthetic first-user CLI journey inside an ephemeral state root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

_COMMAND_TIMEOUT_SECONDS = 30
_NONCE_PATTERN = re.compile(
    r'^revision_privacy_nonce:\s+["\']?(nonce-v1:[0-9a-f]{64})["\']?$',
    re.MULTILINE,
)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _nonce(path: Path) -> str:
    match = _NONCE_PATTERN.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError("initialized inventory omitted its revision privacy nonce")
    return match.group(1)


def _json(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise AssertionError("expected a JSON object from AtReady")
    return value


def _intake_review(preview: dict[str, Any], *, subject: str) -> dict[str, Any]:
    review = preview.get("intake_review")
    if not isinstance(review, dict):
        raise AssertionError(f"{subject} preview omitted its intake review")
    if review.get("route_eligibility_evaluated") is not False:
        raise AssertionError(f"{subject} intake review claimed to evaluate route eligibility")
    groups = review.get("default_groups")
    if (
        not isinstance(groups, dict)
        or set(groups)
        != {
            "selection_facts",
            "scoring_inputs",
            "conservative_policy",
            "operating_context",
        }
        or any(not isinstance(fields, list) for fields in groups.values())
    ):
        raise AssertionError(f"{subject} intake review returned unexpected default groups")
    return review


class _Acceptance:
    def __init__(self, command: tuple[str, ...], root: Path, *, expected_version: str) -> None:
        self.command = command
        self.root = root.resolve()
        self.expected_version = expected_version
        self.inventory = self.root / "inventory.yaml"
        self.project = self.root / "project.yaml"
        self._secrets: list[str] = []
        self._checks: list[str] = []
        self.commands = 0

    def _record(self, name: str) -> None:
        self._checks.append(name)

    def run(
        self,
        argv: list[str],
        *,
        expected: int = 0,
        input_text: str | None = None,
    ) -> tuple[str, str]:
        environment = os.environ.copy()
        environment["ATREADY_HOME"] = str(self.root)
        try:
            completed = subprocess.run(  # noqa: S603
                [*self.command, *argv],
                cwd=self.root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                input=input_text,
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(
                f"AtReady command exceeded {_COMMAND_TIMEOUT_SECONDS} seconds: {argv!r}"
            ) from exc
        self.commands += 1
        if completed.returncode != expected:
            raise AssertionError(
                f"AtReady command {argv!r} returned {completed.returncode}, "
                f"expected {expected}: {completed.stderr}"
            )
        combined = completed.stdout + completed.stderr
        for secret in self._secrets:
            if secret in combined:
                raise AssertionError("normal CLI output exposed synthetic private state")
        return completed.stdout, completed.stderr

    def apply(
        self,
        argv: list[str],
        *,
        input_text: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        preview_text, _ = self.run(argv, input_text=input_text)
        preview = _json(preview_text)
        receipt_text, _ = self.run(
            [
                *argv,
                "--apply",
                "--expect-revision",
                str(preview["expect_revision"]),
                "--expect-plan",
                str(preview["expect_plan"]),
            ],
            input_text=input_text,
        )
        return preview, _json(receipt_text)

    def exercise(self) -> dict[str, Any]:
        if self.inventory.exists():
            raise AssertionError("ephemeral acceptance root was not clean")

        version_text, version_error = self.run(["--version"])
        expected_version_text = f"atready {self.expected_version}\n"
        if version_text != expected_version_text or version_error:
            raise AssertionError(
                "installed AtReady identity did not match the reviewed source: "
                f"expected {expected_version_text.strip()!r}"
            )
        self._record("version-and-command-surface")

        profiles_text, _ = self.run(["resource", "profiles", "--json"])
        profiles = _json(profiles_text)
        if profiles.get("catalog_version") != 1:
            raise AssertionError("installed resource catalog version drifted")
        if profiles.get("catalog_proposals_only") is not True:
            raise AssertionError("resource catalog did not label its entries as proposals")
        profile_items = profiles.get("profiles", [])
        if {item["id"] for item in profile_items} != {
            "antigravity",
            "blender",
            "claude-code",
            "coderabbit",
            "codex",
            "cursor",
            "figma",
            "github-copilot",
            "grok",
            "opencode",
            "pixellab",
            "retro-diffusion",
        }:
            raise AssertionError("installed resource catalog profile set drifted")
        profile_by_id = {item["id"]: item for item in profile_items}
        cursor_kit = profile_by_id["cursor"].get("provider_kit") or {}
        cursor_models = cursor_kit.get("model_routing_suggestions") or []
        if cursor_kit.get("model_catalog_reviewed_on") != "2026-08-09" or [
            (
                item.get("provider_model_id"),
                item.get("suggested_resource_id"),
                item.get("shared_capacity_group"),
            )
            for item in cursor_models
        ] != [
            ("composer-2.5", "cursor-composer-2-5", "cursor-models-pool"),
            ("grok-4.5", "cursor-grok-4-5", "cursor-models-pool"),
        ]:
            raise AssertionError("installed Cursor model-routing proposals drifted")
        if any(
            item.get("availability") != "unverified"
            or item.get("capability_scores") != "user-confirmed-only"
            for item in cursor_models
        ):
            raise AssertionError("installed Cursor model proposals overstated live evidence")
        grok_kit = profile_by_id["grok"].get("provider_kit") or {}
        grok_models = grok_kit.get("model_routing_suggestions") or []
        if [
            (
                item.get("provider_model_id"),
                item.get("suggested_resource_id"),
                item.get("selection_status"),
            )
            for item in grok_models
        ] != [("grok-4.5", "grok-4-5", "standalone-model")]:
            raise AssertionError("installed standalone Grok model proposal drifted")
        profile_text, _ = self.run(["resource", "profile", "retro-diffusion", "--json"])
        profile = _json(profile_text)
        if profile.get("resource_or_account_facts") is not False:
            raise AssertionError("resource profile was presented as an account fact")
        retro_kit = profile.get("provider_kit") or {}
        if [item.get("id") for item in retro_kit.get("workflow_mode_suggestions", [])] != [
            "cloud-website",
            "configured-api",
            "aseprite-extension",
        ] or [item.get("unit") for item in profile.get("capacity_unit_hints", [])] != [
            "generation",
            "credit",
        ]:
            raise AssertionError("installed Retro Diffusion planning profile drifted")
        pixellab_profile = profile_by_id["pixellab"]
        pixellab_kit = pixellab_profile.get("provider_kit") or {}
        if [item.get("id") for item in pixellab_kit.get("workflow_mode_suggestions", [])] != [
            "web-creator",
            "browser-editor",
            "aseprite-extension",
            "configured-api",
        ] or [item.get("unit") for item in pixellab_profile.get("capacity_unit_hints", [])] != [
            "image",
            "credit",
        ]:
            raise AssertionError("installed PixelLab planning profile drifted")
        for provider_kit in (pixellab_kit, retro_kit):
            if (
                provider_kit.get("account_inspection") != "unsupported"
                or provider_kit.get("atready_network_access") != "none"
                or provider_kit.get("provider_execution") != "unsupported"
            ):
                raise AssertionError("pixel-art profile widened its planning-only boundary")
        opencode_text, _ = self.run(["resource", "profile", "opencode", "--json"])
        opencode_profile = _json(opencode_text)
        opencode_kit = opencode_profile.get("provider_kit") or {}
        if opencode_profile.get("executable_probe", {}).get("executable") != "opencode":
            raise AssertionError(
                "installed OpenCode profile omitted its bounded executable proposal"
            )
        if [item.get("id") for item in opencode_kit.get("workflow_mode_suggestions", [])] != [
            "interactive-terminal",
            "delegated-cli",
            "desktop-or-ide",
        ]:
            raise AssertionError("installed OpenCode planning workflow proposals drifted")
        if (
            opencode_kit.get("account_inspection") != "unsupported"
            or opencode_kit.get("provider_execution") != "unsupported"
        ):
            raise AssertionError("installed OpenCode profile widened its planning-only boundary")
        opencode_models = opencode_kit.get("model_routing_suggestions") or []
        if [
            (
                item.get("provider_model_id"),
                item.get("suggested_resource_id"),
                item.get("selection_status"),
            )
            for item in opencode_models
        ] != [
            (
                "opencode/deepseek-v4-flash-free",
                "opencode-deepseek-v4-flash-free",
                "temporary-option",
            )
        ]:
            raise AssertionError("installed OpenCode temporary model proposal drifted")

        discovered_executable = self.root / ("codex.exe" if os.name == "nt" else "codex")
        shutil.copy2(sys.executable, discovered_executable)
        if os.name == "posix":
            discovered_executable.chmod(0o700)
        discovery_text, _ = self.run(
            [
                "resource",
                "discover",
                "codex",
                "--executable",
                str(discovered_executable),
                "--json",
            ]
        )
        discovery = _json(discovery_text)
        if (
            discovery.get("installed") is not True
            or discovery.get("version_probe_performed") is not False
            or discovery.get("authentication_evaluated") is not False
            or discovery.get("quota_evaluated") is not False
            or discovery.get("atready_network_accessed") is not False
            or discovery.get("inventory_writes_performed") is not False
            or discovery.get("external_process_executed") is not False
            or discovery.get("external_process_side_effects") != "not-applicable"
        ):
            raise AssertionError("bounded local discovery overstated its evidence or permissions")
        self._record("catalog-and-bounded-local-discovery")

        initialized_text, initialized_error = self.run(
            ["init", "--path", str(self.inventory), "--json"]
        )
        initialized = _json(initialized_text)
        original_nonce = _nonce(self.inventory)
        self._secrets.append(original_nonce)
        if initialized.get("revision_protection") != "nonce-v1-present":
            raise AssertionError("init receipt omitted nonce-v1 presence")
        if original_nonce in initialized_text + initialized_error:
            raise AssertionError("init receipt exposed the nonce")
        self._record("clean-init")

        continuity_copy = self.root / "continuity-copy.yaml"
        shutil.copyfile(self.inventory, continuity_copy)
        if os.name == "posix":
            continuity_copy.chmod(0o600)
        if _sha256(continuity_copy) != _sha256(self.inventory):
            raise AssertionError("exact continuity copy changed inventory bytes")
        if _nonce(continuity_copy) != original_nonce:
            raise AssertionError("exact continuity copy did not preserve its lineage nonce")
        self.run(["inventory", "validate", str(continuity_copy), "--json"])
        self._record("continuity-copy-preserves-lineage")

        independent = self.root / "independent.yaml"
        independent_text, independent_error = self.run(
            ["init", "--path", str(independent), "--json"]
        )
        independent_nonce = _nonce(independent)
        self._secrets.append(independent_nonce)
        if independent_nonce == original_nonce or _sha256(independent) == _sha256(self.inventory):
            raise AssertionError("independent init reused the original lineage state")
        if independent_nonce in independent_text + independent_error:
            raise AssertionError("independent init receipt exposed the nonce")
        self._record("independent-init-creates-new-lineage")

        private_note = "SYNTHETIC-FIRST-USER-PRIVATE-NOTE"
        self._secrets.append(private_note)
        declaration = _quick_declaration(
            "synthetic-builder", "Synthetic Builder", private_note=private_note
        )
        add_args = [
            "inventory",
            "add",
            "--path",
            str(self.inventory),
            "--resource-stdin",
            "--json",
        ]
        add_preview, add_receipt = self.apply(add_args, input_text=declaration)
        if add_preview.get("private_notes_present") is not True:
            raise AssertionError("add preview omitted private-note presence")
        quick_review = _intake_review(add_preview, subject="quick-add")
        if quick_review.get("selection_fact_status") != "selection-facts-declared":
            raise AssertionError("quick-add preview did not recognize declared selection facts")
        if quick_review.get("unverified_selection_facts") != []:
            raise AssertionError("quick-add preview reported unverified selection facts")
        if quick_review.get("declared_unavailable_facts") != []:
            raise AssertionError("quick-add preview reported unavailable selection facts")
        quick_groups = quick_review["default_groups"]
        if quick_groups["selection_facts"]:
            raise AssertionError("quick-add preview defaulted declared readiness facts")
        if quick_groups["conservative_policy"] != ["policy.approval_required"]:
            raise AssertionError(
                "quick-add preview returned the wrong conservative policy defaults"
            )
        expected_scoring_defaults = {
            "economics.marginal_cost",
            "ratings.quality",
            "ratings.speed",
            "ratings.autonomy",
            "ratings.privacy",
            "ratings.reliability",
            "ratings.confidence",
            "ratings.context_switch_cost",
            "ratings.integration_friction",
        }
        if set(quick_groups["scoring_inputs"]) != expected_scoring_defaults:
            raise AssertionError("quick-add preview returned the wrong scoring-input defaults")
        if set(quick_groups["operating_context"]) != {
            "economics.billing",
            "handoff.method",
        }:
            raise AssertionError("quick-add preview returned the wrong operating-context defaults")
        self._record("quick-add-intake-review")
        if add_receipt.get("replacement_verified") is not True:
            raise AssertionError("add receipt did not verify replacement")

        listed_text, _ = self.run(["inventory", "list", str(self.inventory), "--json"])
        listed = _json(listed_text)
        if [resource["id"] for resource in listed.get("resources", [])] != ["synthetic-builder"]:
            raise AssertionError("inventory list did not show the added synthetic resource")

        validated_text, _ = self.run(
            ["inventory", "validate", str(self.inventory), "--strict", "--json"]
        )
        validated = _json(validated_text)
        if validated.get("valid") is not True or validated.get("warnings") != []:
            raise AssertionError("quick-add inventory failed strict post-add validation")
        self._record("quick-add-strict-validation")

        project_text, _ = self.run(["project", "template"])
        project_text, cost_replacements = re.subn(
            r"(?m)^  max_marginal_cost: 0\.30$",
            "  max_marginal_cost: 0.50",
            project_text,
        )
        if cost_replacements != 1:
            raise AssertionError("project template changed its synthetic marginal-cost contract")
        self.project.write_text(project_text, encoding="utf-8")
        route_text, _ = self.run(
            [
                "route",
                "--project",
                str(self.project),
                "--inventory",
                str(self.inventory),
                "--format",
                "json",
            ]
        )
        routed = _json(route_text)
        if not routed.get("assignments"):
            raise AssertionError("personal synthetic inventory produced no assignments")
        self._record("quick-add-first-route")

        stale_declaration = _declaration("stale-candidate", "Stale Candidate")
        stale_args = [
            "inventory",
            "add",
            "--path",
            str(self.inventory),
            "--resource-stdin",
            "--json",
        ]
        stale_preview_text, _ = self.run(stale_args, input_text=stale_declaration)
        stale_preview = _json(stale_preview_text)

        concurrent_declaration = _declaration("synthetic-reviewer", "Synthetic Reviewer")
        _, concurrent_receipt = self.apply(stale_args, input_text=concurrent_declaration)
        if concurrent_receipt.get("replacement_verified") is not True:
            raise AssertionError("intervening accepted plan was not verified")
        before_refusal = self.inventory.read_bytes()
        _, stale_error = self.run(
            [
                *stale_args,
                "--apply",
                "--expect-revision",
                str(stale_preview["expect_revision"]),
                "--expect-plan",
                str(stale_preview["expect_plan"]),
            ],
            expected=2,
            input_text=stale_declaration,
        )
        if "--expect-revision does not match this preview" not in stale_error:
            raise AssertionError("stale plan was not refused as a revision conflict")
        if self.inventory.read_bytes() != before_refusal:
            raise AssertionError("stale plan refusal changed active inventory bytes")
        self._record("stale-plan-no-write")

        replacement = _detailed_declaration("synthetic-builder", "Revised Synthetic Builder")
        replace_args = [
            "inventory",
            "replace",
            "--path",
            str(self.inventory),
            "--resource-stdin",
            "--json",
        ]
        replace_preview, replace_receipt = self.apply(replace_args, input_text=replacement)
        if replace_preview.get("private_notes_effect") != "will-remove":
            raise AssertionError("replacement preview hid private-note removal")
        detailed_review = _intake_review(replace_preview, subject="detailed replacement")
        if detailed_review.get("selection_fact_status") != "selection-facts-declared":
            raise AssertionError("detailed replacement lost declared selection facts")
        if any(detailed_review["default_groups"].values()):
            raise AssertionError("detailed replacement unexpectedly retained defaulted fields")
        self._record("progressive-intake-enrichment")
        if replace_receipt.get("replacement_verified") is not True:
            raise AssertionError("replacement receipt was not verified")

        remove_args = [
            "inventory",
            "remove",
            "--path",
            str(self.inventory),
            "--resource",
            "synthetic-reviewer",
            "--json",
        ]
        _, remove_receipt = self.apply(remove_args)
        if remove_receipt.get("replacement_verified") is not True:
            raise AssertionError("remove receipt was not verified")
        self._record("replace-remove")

        backups_text, _ = self.run(
            ["inventory", "backup", "list", "--path", str(self.inventory), "--json"]
        )
        backups = _json(backups_text)
        if not backups.get("backups"):
            raise AssertionError("accepted mutations did not create recovery backups")
        source_backup_id = str(remove_receipt["backup_id"])
        inspection_text, _ = self.run(
            [
                "inventory",
                "backup",
                "inspect",
                "--path",
                str(self.inventory),
                "--backup",
                source_backup_id,
                "--json",
            ]
        )
        inspection = _json(inspection_text)
        if inspection.get("private_notes_exposed") is not False:
            raise AssertionError("backup inspection did not remain redacted")

        rollback_args = [
            "inventory",
            "backup",
            "rollback",
            "--path",
            str(self.inventory),
            "--backup",
            source_backup_id,
            "--json",
        ]
        _, rollback_receipt = self.apply(rollback_args)
        if rollback_receipt.get("replacement_verified") is not True:
            raise AssertionError("rollback receipt was not verified")
        restored_text, _ = self.run(["inventory", "list", str(self.inventory), "--json"])
        restored_ids = [resource["id"] for resource in _json(restored_text).get("resources", [])]
        if restored_ids != ["synthetic-builder", "synthetic-reviewer"]:
            raise AssertionError("rollback did not restore the selected exact prior state")
        self._record("backup-inspect-rollback")

        for path in self.root.rglob("*"):
            if not path.resolve().is_relative_to(self.root):
                raise AssertionError("acceptance artifact escaped the ephemeral state root")
        self._record("normal-output-redaction")

        return {
            "result": "passed",
            "cli_version": self.expected_version,
            "catalog_version": 1,
            "synthetic_only": True,
            "mutation_scope": "ephemeral-temporary-directory-only",
            "commands_checked": self.commands,
            "checks": list(self._checks),
        }


def _declaration(resource_id: str, name: str, *, private_note: str | None = None) -> str:
    return _detailed_declaration(resource_id, name, private_note=private_note)


def _quick_declaration(resource_id: str, name: str, *, private_note: str | None = None) -> str:
    """Declare routing readiness and safety while accepting benign presentation defaults."""

    note = f"  private_notes: {private_note}\n" if private_note is not None else ""
    return (
        "schema_version: 1\n"
        "resource:\n"
        f"  id: {resource_id}\n"
        f"  name: {name}\n"
        "  categories: [synthetic-tool]\n"
        "  capabilities:\n"
        "    code-implementation: 0.90\n"
        "    test-automation: 0.90\n"
        "  access:\n"
        "    status: active\n"
        "    interaction: local-cli\n"
        "    current_session: available\n"
        "  economics:\n"
        "    quota: ample\n"
        "    capacity: null\n"
        "  policy:\n"
        "    allowed_data_classes: [public, internal]\n"
        "    requires_network: false\n"
        "  provenance:\n"
        "    basis: observed\n"
        f"    last_verified: {date.today().isoformat()}\n"
        f"{note}"
    )


def _detailed_declaration(
    resource_id: str,
    name: str,
    *,
    private_note: str | None = None,
) -> str:
    note = f"  private_notes: {private_note}\n" if private_note is not None else ""
    return (
        "schema_version: 1\n"
        "resource:\n"
        f"  id: {resource_id}\n"
        f"  name: {name}\n"
        "  categories: [synthetic-tool]\n"
        "  capabilities:\n"
        "    code-implementation: 0.90\n"
        "    test-automation: 0.90\n"
        "  access:\n"
        "    status: active\n"
        "    interaction: local-cli\n"
        "    current_session: available\n"
        "  economics:\n"
        "    billing: free\n"
        "    marginal_cost: 0.00\n"
        "    quota: ample\n"
        "    capacity: null\n"
        "  ratings:\n"
        "    quality: 0.80\n"
        "    speed: 0.80\n"
        "    autonomy: 0.80\n"
        "    privacy: 0.80\n"
        "    reliability: 0.80\n"
        "    confidence: 0.80\n"
        "    context_switch_cost: 0.20\n"
        "    integration_friction: 0.20\n"
        "  policy:\n"
        "    allowed_data_classes: [public, internal]\n"
        "    approval_required: false\n"
        "    requires_network: false\n"
        "  provenance:\n"
        "    basis: observed\n"
        f"    last_verified: {date.today().isoformat()}\n"
        "  handoff:\n"
        "    method: manual-prompt\n"
        "    instructions: Review this inert synthetic acceptance handoff.\n"
        f"{note}"
    )


def run_acceptance(executable: str | Path) -> dict[str, Any]:
    resolved = Path(executable).expanduser().resolve()
    if not resolved.is_file():
        raise AssertionError(f"AtReady executable does not exist: {resolved}")
    return _run_acceptance_command((str(resolved),), expected_version=_source_version())


def _source_version() -> str:
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    version = project.get("project", {}).get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise AssertionError("reviewed source does not declare a valid AtReady version")
    return version


def _run_acceptance_command(command: tuple[str, ...], *, expected_version: str) -> dict[str, Any]:
    if not command:
        raise AssertionError("AtReady acceptance command is empty")
    with tempfile.TemporaryDirectory(prefix="atready-first-user-") as directory:
        return _Acceptance(command, Path(directory), expected_version=expected_version).exercise()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise the synthetic first-user CLI journey in an ephemeral directory. "
            "This does not install the CLI or mutate the user's real AtReady config."
        )
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--executable",
        help="AtReady executable to test (defaults to the command resolved from PATH)",
    )
    source.add_argument(
        "--module",
        action="store_true",
        help="test the source checkout via the current Python interpreter",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.module:
        source_root = Path(__file__).resolve().parents[1] / "src"
        source_runner = (
            "import sys;"
            f"sys.path.insert(0, {str(source_root)!r});"
            "from atready.cli import main;"
            "raise SystemExit(main())"
        )
        receipt = _run_acceptance_command(
            (sys.executable, "-c", source_runner), expected_version=_source_version()
        )
    else:
        executable = args.executable or shutil.which("atready")
        if executable is None:
            raise SystemExit("atready executable was not found; pass --executable")
        receipt = run_acceptance(executable)
    receipt["platform"] = platform.system().lower()
    receipt["python"] = platform.python_version()
    json.dump(receipt, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
