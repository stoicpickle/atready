from __future__ import annotations

import os
import shlex
import signal
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import atready.intake as intake_module
from atready.intake import (
    ExecutableProbe,
    IntakeError,
    LocalDiscoveryRequest,
    ModelRoutingSuggestion,
    ProviderGuidanceItem,
    ProviderIntegrationKit,
    discover_local_resource,
    resource_profile,
    resource_profiles,
)
from atready.inventory_edit import (
    commit_add_resource,
    plan_add_resource,
    plan_replace_resource,
)
from atready.models import Capacity, ConfidenceBasis, Economics, QuotaStatus
from atready.paths import create_private_file
from atready.resource_input import parse_resource_mapping, resource_intake_review
from atready.templates import starter_inventory


def _minimal_mapping(*, name: str = "Synthetic Tool") -> dict[str, object]:
    return {
        "id": "synthetic-tool",
        "name": name,
        "categories": ["coding-agent"],
        "capabilities": {"code-implementation": 0.8},
    }


def _declared_selection_facts(*, name: str = "Synthetic Tool") -> dict[str, object]:
    return {
        **_minimal_mapping(name=name),
        "access": {
            "status": "active",
            "current_session": "available",
        },
        "economics": {"quota": "ample"},
        "provenance": {
            "basis": "observed",
            "last_verified": date.today().isoformat(),
        },
    }


@pytest.mark.parametrize("unsafe_text", ("line\nbreak", "left\u202eright"))
def test_provider_guidance_rejects_terminal_control_and_format_characters(
    unsafe_text: str,
) -> None:
    with pytest.raises(ValidationError):
        ProviderGuidanceItem(id="unsafe-guidance", prompt=unsafe_text)


def test_minimal_intake_groups_every_default_and_requires_verification() -> None:
    parsed = parse_resource_mapping(_minimal_mapping())

    review = resource_intake_review(parsed.resource, parsed.defaulted_fields).as_dict()

    assert review == {
        "declared_unavailable_facts": [],
        "default_groups": {
            "conservative_policy": [
                "policy.allowed_data_classes",
                "policy.approval_required",
                "policy.requires_network",
            ],
            "operating_context": [
                "access.interaction",
                "economics.billing",
                "handoff.method",
            ],
            "scoring_inputs": [
                "economics.marginal_cost",
                "ratings.quality",
                "ratings.speed",
                "ratings.autonomy",
                "ratings.privacy",
                "ratings.reliability",
                "ratings.confidence",
                "ratings.context_switch_cost",
                "ratings.integration_friction",
            ],
            "selection_facts": [
                "access.status",
                "access.current_session",
                "economics.quota",
                "economics.capacity",
                "provenance.basis",
                "provenance.last_verified",
            ],
        },
        "route_eligibility_evaluated": False,
        "selection_fact_status": "requires-verification",
        "unverified_selection_facts": [
            "access.status",
            "access.current_session",
            "economics.quota",
            "provenance.basis",
            "provenance.last_verified",
        ],
    }
    grouped = [field for fields in review["default_groups"].values() for field in fields]
    assert len(grouped) == len(set(grouped)) == len(parsed.defaulted_fields) == 21
    assert set(grouped) == set(parsed.defaulted_fields)


def test_minimal_intake_materializes_factory_defaults_missing_from_json_schema() -> None:
    parsed = parse_resource_mapping(_minimal_mapping())

    resource = parsed.resource.model_dump(mode="json")

    assert resource["access"] == {
        "status": "unknown",
        "interaction": "manual",
        "current_session": "unknown",
    }
    assert resource["economics"] == {
        "billing": "unknown",
        "marginal_cost": 0.5,
        "quota": "unknown",
        "capacity": None,
    }
    assert resource["ratings"] == {
        "quality": 0.5,
        "speed": 0.5,
        "autonomy": 0.5,
        "privacy": 0.5,
        "reliability": 0.5,
        "confidence": 0.5,
        "context_switch_cost": 0.5,
        "integration_friction": 0.5,
    }
    assert resource["policy"] == {
        "allowed_data_classes": ["public"],
        "approval_required": True,
        "requires_network": False,
    }
    assert resource["provenance"] == {"basis": "unknown", "last_verified": None}
    assert resource["handoff"] == {"method": "manual-prompt", "instructions": None}
    assert resource["best_for"] == []
    assert resource["avoid_for"] == []
    assert resource["private_notes"] is None


def test_explicit_unknown_facts_are_unverified_but_not_defaulted() -> None:
    value = {
        **_minimal_mapping(),
        "access": {"status": "unknown", "current_session": "unknown"},
        "economics": {"quota": "unknown"},
        "provenance": {"basis": "unknown", "last_verified": None},
    }
    parsed = parse_resource_mapping(value)

    review = resource_intake_review(parsed.resource, parsed.defaulted_fields).as_dict()

    assert review["selection_fact_status"] == "requires-verification"
    assert review["unverified_selection_facts"] == [
        "access.status",
        "access.current_session",
        "economics.quota",
        "provenance.basis",
        "provenance.last_verified",
    ]
    assert review["default_groups"]["selection_facts"] == ["economics.capacity"]

    value["economics"] = {"quota": "unknown", "capacity": None}
    explicitly_absent = parse_resource_mapping(value)
    explicit_review = resource_intake_review(
        explicitly_absent.resource,
        explicitly_absent.defaulted_fields,
    ).as_dict()
    assert explicit_review["default_groups"]["selection_facts"] == []


def test_unavailable_fact_takes_status_precedence_over_unverified_fact() -> None:
    value = {
        **_minimal_mapping(),
        "access": {"status": "inactive", "current_session": "unavailable"},
        "economics": {"quota": "exhausted"},
    }
    parsed = parse_resource_mapping(value)

    review = resource_intake_review(parsed.resource, parsed.defaulted_fields).as_dict()

    assert review["selection_fact_status"] == "declared-unavailable"
    assert review["declared_unavailable_facts"] == [
        "access.status",
        "access.current_session",
        "economics.quota",
    ]
    assert review["unverified_selection_facts"] == [
        "provenance.basis",
        "provenance.last_verified",
    ]


def test_declared_selection_facts_do_not_claim_route_eligibility() -> None:
    parsed = parse_resource_mapping(_declared_selection_facts())

    review = resource_intake_review(parsed.resource, parsed.defaulted_fields).as_dict()

    assert review["selection_fact_status"] == "selection-facts-declared"
    assert review["route_eligibility_evaluated"] is False
    assert review["unverified_selection_facts"] == []
    assert review["declared_unavailable_facts"] == []


def test_add_and_replace_previews_share_post_change_intake_review(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    create_private_file(target, starter_inventory())
    added = parse_resource_mapping(_minimal_mapping())
    add_plan = plan_add_resource(
        target,
        added.resource,
        defaulted_fields=added.defaulted_fields,
    )

    add_review = add_plan.preview()["intake_review"]
    assert add_review["selection_fact_status"] == "requires-verification"
    receipt = commit_add_resource(
        add_plan,
        expected_revision=add_plan.original_revision,
        expected_plan=add_plan.plan_token,
    )
    assert "intake_review" not in receipt.as_dict()

    replacement = parse_resource_mapping(_declared_selection_facts(name="Revised Synthetic Tool"))
    replace_plan = plan_replace_resource(
        target,
        replacement.resource,
        defaulted_fields=replacement.defaulted_fields,
    )

    replace_review = replace_plan.preview()["intake_review"]
    assert replace_review["selection_fact_status"] == "selection-facts-declared"
    assert (
        replace_review
        == resource_intake_review(
            replacement.resource,
            replacement.defaulted_fields,
        ).as_dict()
    )


def test_intake_review_does_not_change_plan_token(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    create_private_file(target, starter_inventory())
    parsed = parse_resource_mapping(_minimal_mapping())
    with_defaults = plan_add_resource(
        target,
        parsed.resource,
        defaulted_fields=parsed.defaulted_fields,
    )
    without_defaults = plan_add_resource(target, parsed.resource)

    assert with_defaults.plan_token == without_defaults.plan_token
    assert with_defaults.candidate_revision == without_defaults.candidate_revision
    assert with_defaults.preview()["intake_review"]["default_groups"]["selection_facts"]
    assert without_defaults.preview()["intake_review"]["default_groups"]["selection_facts"] == []


def _capacity(**overrides: object) -> Capacity:
    values: dict[str, object] = {
        "unit": "review-request",
        "remaining": 12,
        "limit": 50,
        "project_limit": 5,
        "resets_on": (date.today() + timedelta(days=30)).isoformat(),
        "basis": "observed",
        "last_verified": date.today().isoformat(),
    }
    values.update(overrides)
    return Capacity.model_validate(values)


def test_capacity_serializes_native_unit_scoped_values() -> None:
    economics = Economics(quota=QuotaStatus.LIMITED, capacity=_capacity())

    assert economics.model_dump(mode="json")["capacity"] == {
        "unit": "review-request",
        "remaining": 12,
        "limit": 50,
        "project_limit": 5,
        "resets_on": (date.today() + timedelta(days=30)).isoformat(),
        "basis": "observed",
        "last_verified": date.today().isoformat(),
    }


@pytest.mark.parametrize(
    "value",
    [True, "12", -1, 1e19, 10**400, float("inf"), float("nan")],
)
def test_capacity_rejects_non_native_nonfinite_or_negative_numbers(value: object) -> None:
    with pytest.raises(ValidationError):
        _capacity(remaining=value)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"basis": ConfidenceBasis.UNKNOWN}, "non-unknown basis"),
        ({"last_verified": None}, "valid date"),
        ({"last_verified": "2999-01-01"}, "cannot be in the future"),
        (
            {"resets_on": (date.today() - timedelta(days=1)).isoformat()},
            "cannot be earlier than last_verified",
        ),
        ({"remaining": 0, "limit": 0, "project_limit": 0}, "greater than zero"),
        ({"remaining": 51}, "remaining cannot exceed limit"),
        ({"project_limit": 13}, "project_limit cannot exceed remaining"),
    ],
)
def test_capacity_rejects_incomplete_or_inconsistent_exact_facts(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _capacity(**overrides)


def test_economics_requires_quota_to_match_zero_or_positive_capacity() -> None:
    zero = _capacity(remaining=0, project_limit=0)
    positive = _capacity()

    with pytest.raises(ValidationError, match="zero remaining capacity requires quota exhausted"):
        Economics(quota=QuotaStatus.LIMITED, capacity=zero)
    with pytest.raises(ValidationError, match="positive remaining capacity"):
        Economics(quota=QuotaStatus.EXHAUSTED, capacity=positive)

    assert Economics(quota=QuotaStatus.EXHAUSTED, capacity=zero).capacity == zero
    assert Economics(quota=QuotaStatus.EXHAUSTED).capacity is None


def test_capacity_numbers_have_one_semantic_serialization() -> None:
    integer_input = _capacity(remaining=8, limit=10, project_limit=4)
    float_input = _capacity(remaining=8.0, limit=10.0, project_limit=4.0)

    assert integer_input.model_dump(mode="json") == float_input.model_dump(mode="json")
    assert integer_input.model_dump(mode="json")["remaining"] == 8

    negative_zero = _capacity(remaining=-0.0, project_limit=-0.0, limit=10)
    assert negative_zero.model_dump(mode="json")["remaining"] == 0
    assert str(negative_zero.model_dump(mode="json")["remaining"]) == "0"


def test_capacity_preserves_integers_above_binary_float_exactness() -> None:
    declared = 2**53 + 1
    capacity = _capacity(remaining=declared, limit=declared + 1, project_limit=declared)

    payload = capacity.model_dump(mode="json")
    assert payload["remaining"] == declared
    assert payload["limit"] == declared + 1
    assert payload["project_limit"] == declared


def test_capacity_is_routing_visible_in_add_preview(tmp_path: Path) -> None:
    target = tmp_path / "private" / "inventory.yaml"
    create_private_file(target, starter_inventory())
    mapping = _declared_selection_facts()
    mapping["economics"] = {
        "quota": "limited",
        "capacity": _capacity().model_dump(mode="json"),
    }
    parsed = parse_resource_mapping(mapping)

    preview = plan_add_resource(target, parsed.resource).preview()

    assert preview["resource"]["economics"]["capacity"]["unit"] == "review-request"
    remaining = preview["resource"]["economics"]["capacity"]["remaining"]
    assert remaining == 12
    assert type(remaining) is int


def test_bundled_profiles_are_offline_proposals_without_strength_claims() -> None:
    profiles = resource_profiles()

    assert [profile.id for profile in profiles] == [
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
    ]
    assert all(profile.suggestions_are_proposals for profile in profiles)
    assert all(profile.catalog_version == 1 for profile in profiles)
    serialized = [profile.model_dump(mode="json") for profile in profiles]
    assert all(
        "score" not in suggestion
        for profile in serialized
        for suggestion in profile["capability_suggestions"]
    )
    assert {profile["id"] for profile in serialized if profile["executable_probe"]} == {
        "antigravity",
        "blender",
        "claude-code",
        "coderabbit",
        "codex",
        "github-copilot",
        "opencode",
    }


def test_coderabbit_provider_kit_is_bounded_proposal_data_without_connector_claims() -> None:
    profile = resource_profile("coderabbit")
    payload = profile.model_dump(mode="json")

    assert payload["catalog_version"] == 1
    assert payload["executable_probe"] == {
        "alias_platforms": ["posix"],
        "aliases": ["cr"],
        "executable": "coderabbit",
        "supported_platforms": ["posix"],
        "version_args": ["--version"],
    }
    kit = payload["provider_kit"]
    assert kit["suggestions_are_proposals"] is True
    assert kit["account_inspection"] == "unsupported"
    assert kit["atready_network_access"] == "none"
    assert kit["provider_execution"] == "unsupported"
    assert [item["id"] for item in kit["workflow_mode_suggestions"]] == [
        "local-cli",
        "pull-request-app",
        "manual-review",
    ]
    assert [item["interaction_suggestion"] for item in kit["workflow_mode_suggestions"]] == [
        "local-cli",
        "external-agent",
        "manual",
    ]
    assert [item["id"] for item in kit["onboarding_guidance"]] == [
        "workflow-mode",
        "review-scope",
        "session-readiness",
    ]
    assert [item["id"] for item in kit["capacity_guidance"]] == [
        "remaining-allowance",
        "limit-and-reset",
        "capacity-provenance",
    ]
    prompts = {
        item["id"]: item["prompt"].casefold()
        for item in (*kit["onboarding_guidance"], *kit["capacity_guidance"])
    }
    assert (
        "using descriptions only and never credentials, tokens, or secret values"
        in prompts["review-scope"]
    )
    assert resource_profile("codex").provider_kit is None


def test_opencode_provider_kit_keeps_planning_context_simple_and_user_declared() -> None:
    payload = resource_profile("opencode-cli").model_dump(mode="json")

    assert payload["id"] == "opencode"
    assert payload["category_suggestions"] == [{"id": "coding-agent", "label": "Coding agent"}]
    assert [item["id"] for item in payload["capability_suggestions"]] == [
        "code-implementation",
        "code-review",
        "repository-analysis",
        "software-planning",
    ]
    assert [item["unit"] for item in payload["capacity_unit_hints"]] == [
        "agent-task",
        "token",
        "credit",
    ]
    assert payload["executable_probe"] == {
        "alias_platforms": [],
        "aliases": [],
        "executable": "opencode",
        "supported_platforms": ["posix", "windows"],
        "version_args": ["--version"],
    }
    kit = payload["provider_kit"]
    assert [item["id"] for item in kit["workflow_mode_suggestions"]] == [
        "interactive-terminal",
        "delegated-cli",
        "desktop-or-ide",
    ]
    assert [item["interaction_suggestion"] for item in kit["workflow_mode_suggestions"]] == [
        "local-cli",
        "codex-callable",
        "manual",
    ]
    assert [item["id"] for item in kit["onboarding_guidance"]] == [
        "workflow-surface",
        "planning-fit",
        "permission-boundary",
    ]
    assert [item["id"] for item in kit["capacity_guidance"]] == [
        "provider-budget",
        "remaining-and-reset",
        "capacity-provenance",
    ]
    assert kit["account_inspection"] == "unsupported"
    assert kit["atready_network_access"] == "none"
    assert kit["provider_execution"] == "unsupported"
    serialized = str(kit).casefold()
    assert "inspect opencode configuration" in serialized
    assert "never inspect provider billing or account state" in serialized


def test_pixel_art_provider_kits_keep_tiers_surfaces_and_capacity_distinct() -> None:
    pixellab = resource_profile("pixel-lab").model_dump(mode="json")
    retro = resource_profile("retro diffusion").model_dump(mode="json")

    assert pixellab["id"] == "pixellab"
    assert [item["id"] for item in pixellab["capability_suggestions"]] == [
        "pixel-art-generation",
        "sprite-generation",
        "sprite-animation",
        "pixel-art-editing",
        "map-generation",
    ]
    assert [item["unit"] for item in pixellab["capacity_unit_hints"]] == ["image", "credit"]
    pixellab_kit = pixellab["provider_kit"]
    assert [item["id"] for item in pixellab_kit["workflow_mode_suggestions"]] == [
        "web-creator",
        "browser-editor",
        "aseprite-extension",
        "configured-api",
    ]
    assert [
        item["interaction_suggestion"] for item in pixellab_kit["workflow_mode_suggestions"]
    ] == [
        "manual",
        "manual",
        "manual",
        "codex-callable",
    ]
    pixellab_copy = str(pixellab_kit).casefold()
    for contract in (
        "pixel apprentice",
        "pixel artisan",
        "pixel architect",
        "up to 10 concurrent jobs",
        "up to 20 concurrent background jobs",
        "never combine images and credits",
        "does not refresh or decrement the balance",
    ):
        assert contract in pixellab_copy
    tier_allowance = next(
        item for item in pixellab_kit["capacity_guidance"] if item["id"] == "tier-allowance"
    )
    for allowance in (
        "2,000 images monthly",
        "5,000 images monthly",
        "10,000 images monthly",
    ):
        assert allowance in tier_allowance["prompt"].casefold()

    assert retro["id"] == "retro-diffusion"
    assert [item["id"] for item in retro["capability_suggestions"]] == [
        "pixel-art-generation",
        "sprite-generation",
        "sprite-animation",
        "pixel-art-editing",
        "palette-editing",
    ]
    assert [item["unit"] for item in retro["capacity_unit_hints"]] == [
        "generation",
        "credit",
    ]
    retro_kit = retro["provider_kit"]
    assert [item["id"] for item in retro_kit["workflow_mode_suggestions"]] == [
        "cloud-website",
        "configured-api",
        "aseprite-extension",
    ]
    assert [item["interaction_suggestion"] for item in retro_kit["workflow_mode_suggestions"]] == [
        "manual",
        "codex-callable",
        "manual",
    ]
    retro_copy = str(retro_kit).casefold()
    for contract in (
        "website credits rather than a subscription",
        "separate one-time extension purchase",
        "credits do not expire",
        "larger images cost more",
        "owned local extension has no credit balance",
        "does not refresh or decrement credits",
    ):
        assert contract in retro_copy
    for kit in (pixellab_kit, retro_kit):
        assert kit["account_inspection"] == "unsupported"
        assert kit["atready_network_access"] == "none"
        assert kit["provider_execution"] == "unsupported"


@pytest.mark.parametrize(
    ("query", "profile_id", "executable", "version_args", "workflow_ids"),
    (
        (
            "agy",
            "antigravity",
            "agy",
            (),
            (
                "interactive-terminal",
                "authorized-headless",
                "desktop-or-ide",
                "background-agents",
            ),
        ),
        (
            "claude-cli",
            "claude-code",
            "claude",
            ("--version",),
            (
                "interactive-terminal",
                "delegated-headless",
                "ide-or-remote",
                "configured-ci",
            ),
        ),
        (
            "github-copilot-cli",
            "github-copilot",
            "copilot",
            (),
            (
                "interactive-terminal",
                "delegated-cli",
                "coding-agent-delegation",
                "editor-or-app",
            ),
        ),
    ),
)
def test_popular_coding_agent_profiles_are_bounded_planning_proposals(
    query: str,
    profile_id: str,
    executable: str,
    version_args: tuple[str, ...],
    workflow_ids: tuple[str, ...],
) -> None:
    payload = resource_profile(query).model_dump(mode="json")

    assert payload["id"] == profile_id
    assert payload["category_suggestions"] == [{"id": "coding-agent", "label": "Coding agent"}]
    assert payload["executable_probe"]["executable"] == executable
    assert tuple(payload["executable_probe"]["version_args"]) == version_args
    if profile_id in {"claude-code", "github-copilot"}:
        assert tuple(payload["executable_probe"]["supported_platforms"]) == ("posix",)
    kit = payload["provider_kit"]
    assert tuple(item["id"] for item in kit["workflow_mode_suggestions"]) == workflow_ids
    assert kit["suggestions_are_proposals"] is True
    assert kit["account_inspection"] == "unsupported"
    assert kit["atready_network_access"] == "none"
    assert kit["provider_execution"] == "unsupported"
    serialized = str(kit).casefold()
    assert "credentials" in serialized
    assert "never inspect" in serialized or "do not inspect" in serialized


def test_cursor_profile_omits_unsafe_generic_agent_executable_probe() -> None:
    payload = resource_profile("cursor-ai").model_dump(mode="json")

    assert payload["id"] == "cursor"
    assert payload["executable_probe"] is None
    assert [item["id"] for item in payload["provider_kit"]["workflow_mode_suggestions"]] == [
        "cursor-editor",
        "interactive-cli",
        "authorized-headless-cli",
        "cloud-agent",
    ]
    serialized = str(payload["provider_kit"]).casefold()
    assert "rules" in serialized
    assert "dashboard or account state" in serialized

    kit = payload["provider_kit"]
    assert kit["model_catalog_reviewed_on"] == "2026-08-09"
    assert kit["model_routing_suggestions"] == [
        {
            "availability": "unverified",
            "capability_scores": "user-confirmed-only",
            "id": "composer-2-5",
            "label": "Composer 2.5",
            "planning_caution": (
                "Treat difficulty, quality, and speed as user-confirmed scores; catalog copy "
                "never ranks this model automatically."
            ),
            "planning_role": (
                "Cost-efficient agentic coding for well-scoped implementation, iteration, "
                "tests, and routine refactors."
            ),
            "provider_model_id": "composer-2.5",
            "selection_status": "named-option",
            "shared_capacity_group": "cursor-models-pool",
            "suggested_resource_id": "cursor-composer-2-5",
        },
        {
            "availability": "unverified",
            "capability_scores": "user-confirmed-only",
            "id": "grok-4-5",
            "label": "Cursor Grok 4.5",
            "planning_caution": (
                "Confirm current plan, region, access, and measured fit; do not infer that it "
                "is available or preferable for every task."
            ),
            "planning_role": (
                "Hard long-running coding, migration, architecture, investigation, and "
                "knowledge-work tasks that benefit from sustained reasoning."
            ),
            "provider_model_id": "grok-4.5",
            "selection_status": "named-option",
            "shared_capacity_group": "cursor-models-pool",
            "suggested_resource_id": "cursor-grok-4-5",
        },
    ]


def test_opencode_and_grok_model_routing_proposals_preserve_surface_boundaries() -> None:
    opencode = resource_profile("opencode").model_dump(mode="json")
    deepseek = opencode["provider_kit"]["model_routing_suggestions"][0]

    assert opencode["provider_kit"]["model_catalog_reviewed_on"] == "2026-08-09"
    assert deepseek["id"] == "deepseek-v4-flash-free"
    assert deepseek["provider_model_id"] == "opencode/deepseek-v4-flash-free"
    assert deepseek["suggested_resource_id"] == "opencode-deepseek-v4-flash-free"
    assert deepseek["selection_status"] == "temporary-option"
    assert deepseek["shared_capacity_group"] is None
    assert deepseek["availability"] == "unverified"
    assert deepseek["capability_scores"] == "user-confirmed-only"
    assert "not OpenCode's universal default" in deepseek["planning_caution"]

    grok = resource_profile("xai-grok").model_dump(mode="json")
    assert [item["id"] for item in grok["capability_suggestions"]] == [
        "research",
        "analysis",
        "software-planning",
        "code-review",
    ]
    assert [item["id"] for item in grok["provider_kit"]["workflow_mode_suggestions"]] == [
        "grok-app",
        "xai-api",
    ]
    standalone = grok["provider_kit"]["model_routing_suggestions"][0]
    assert standalone["provider_model_id"] == "grok-4.5"
    assert standalone["suggested_resource_id"] == "grok-4-5"
    assert standalone["selection_status"] == "standalone-model"
    assert "Cursor-hosted version" in standalone["planning_caution"]


def test_executable_probe_rejects_duplicate_canonical_or_alias_names() -> None:
    with pytest.raises(ValidationError, match="executable names must be distinct"):
        ExecutableProbe(executable="coderabbit", aliases=("cr", "coderabbit"))

    with pytest.raises(
        ValidationError,
        match="executable alias platforms require at least one alias",
    ):
        ExecutableProbe(executable="coderabbit", alias_platforms=("posix",))


def test_provider_kit_collection_sizes_are_schema_bounded() -> None:
    executable_schema = ExecutableProbe.model_json_schema()["properties"]
    profile_schema = type(resource_profile("coderabbit")).model_json_schema()["properties"]
    kit_schema = ProviderIntegrationKit.model_json_schema()["properties"]

    assert executable_schema["aliases"]["maxItems"] == 8
    assert executable_schema["version_args"]["maxItems"] == 8
    assert profile_schema["aliases"]["maxItems"] == 16
    assert kit_schema["workflow_mode_suggestions"]["maxItems"] == 16
    assert kit_schema["onboarding_guidance"]["maxItems"] == 16
    assert kit_schema["capacity_guidance"]["maxItems"] == 16
    assert kit_schema["model_routing_suggestions"]["maxItems"] == 16

    with pytest.raises(ValidationError, match="alias platforms must be supported"):
        ExecutableProbe(
            executable="coderabbit",
            supported_platforms=("posix",),
            aliases=("cr",),
            alias_platforms=("windows",),
        )


def test_provider_kit_rejects_unbounded_or_duplicate_guidance() -> None:
    with pytest.raises(ValidationError):
        ProviderGuidanceItem(id="too-long", prompt="x" * 321)

    kit = resource_profile("coderabbit").provider_kit
    assert kit is not None
    duplicate = kit.onboarding_guidance[0]
    with pytest.raises(ValidationError, match="item IDs must be distinct"):
        ProviderIntegrationKit(
            workflow_mode_suggestions=kit.workflow_mode_suggestions,
            onboarding_guidance=(duplicate, duplicate),
            capacity_guidance=kit.capacity_guidance,
        )


def test_provider_kit_requires_dated_distinct_model_routing_proposals() -> None:
    kit = resource_profile("cursor").provider_kit
    assert kit is not None
    suggestion = kit.model_routing_suggestions[0]

    with pytest.raises(ValidationError, match="review date must appear together"):
        ProviderIntegrationKit(
            workflow_mode_suggestions=kit.workflow_mode_suggestions,
            onboarding_guidance=kit.onboarding_guidance,
            capacity_guidance=kit.capacity_guidance,
            model_routing_suggestions=(suggestion,),
        )

    with pytest.raises(ValidationError, match="review date must appear together"):
        ProviderIntegrationKit(
            workflow_mode_suggestions=kit.workflow_mode_suggestions,
            onboarding_guidance=kit.onboarding_guidance,
            capacity_guidance=kit.capacity_guidance,
            model_catalog_reviewed_on=date(2026, 8, 9),
        )

    duplicate_resource = ModelRoutingSuggestion(
        id="another-model",
        label="Another model",
        provider_model_id="another-model",
        suggested_resource_id=suggestion.suggested_resource_id,
        selection_status="named-option",
        planning_role="A bounded synthetic planning role.",
        planning_caution="A bounded synthetic caution.",
    )
    with pytest.raises(ValidationError, match="resource IDs must be distinct"):
        ProviderIntegrationKit(
            workflow_mode_suggestions=kit.workflow_mode_suggestions,
            onboarding_guidance=kit.onboarding_guidance,
            capacity_guidance=kit.capacity_guidance,
            model_routing_suggestions=(suggestion, duplicate_resource),
            model_catalog_reviewed_on=date(2026, 8, 9),
        )

    duplicate_id = ModelRoutingSuggestion(
        id=suggestion.id,
        label="Another model",
        provider_model_id="another-model",
        suggested_resource_id="another-model-resource",
        selection_status="named-option",
        planning_role="A bounded synthetic planning role.",
        planning_caution="A bounded synthetic caution.",
    )
    with pytest.raises(ValidationError, match="suggestion IDs must be distinct"):
        ProviderIntegrationKit(
            workflow_mode_suggestions=kit.workflow_mode_suggestions,
            onboarding_guidance=kit.onboarding_guidance,
            capacity_guidance=kit.capacity_guidance,
            model_routing_suggestions=(suggestion, duplicate_id),
            model_catalog_reviewed_on=date(2026, 8, 9),
        )


def test_profile_lookup_prefers_exact_id_and_accepts_unambiguous_alias() -> None:
    assert resource_profile("codex").id == "codex"
    assert resource_profile(" OpenAI_Codex ").id == "codex"
    assert resource_profile("PixelLab AI").id == "pixellab"
    assert resource_profile("retro diffusion").id == "retro-diffusion"


def test_profile_lookup_fails_with_sanitized_unknown_and_ambiguous_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(IntakeError) as unknown:
        resource_profile("secret-provider-name")
    assert unknown.value.as_dict() == {
        "code": "unknown-profile",
        "message": "resource profile is not in the bundled catalog",
    }
    assert "secret-provider-name" not in str(unknown.value)

    first, second = resource_profile("codex"), resource_profile("grok")
    monkeypatch.setattr(
        intake_module,
        "BUNDLED_RESOURCE_PROFILES",
        (
            first.model_copy(update={"aliases": ("shared-alias",)}),
            second.model_copy(update={"aliases": ("shared-alias",)}),
        ),
    )
    with pytest.raises(IntakeError) as ambiguous:
        resource_profile("shared-alias")
    assert ambiguous.value.code == "ambiguous-profile"
    assert "shared-alias" not in str(ambiguous.value)


def _make_executable(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


def test_discovery_is_locate_only_by_default_and_does_not_write(tmp_path: Path) -> None:
    marker = tmp_path / "unexpected-write"
    executable = _make_executable(tmp_path / "codex", f"touch '{marker}'\nprintf '1.2.3\\n'\n")

    result = discover_local_resource(
        LocalDiscoveryRequest(profile="codex", executable=str(executable))
    )

    assert result.model_dump(mode="json") == {
        "profile_id": "codex",
        "executable_name": "codex",
        "search_scope": "exact-path",
        "installed": True,
        "resolved_path": str(executable),
        "version_probe_performed": False,
        "version": None,
        "evidence": ["executable-located"],
        "limitations": [
            "account-status-not-evaluated",
            "authentication-not-evaluated",
            "quota-not-evaluated",
            "availability-not-evaluated",
        ],
        "account_status_evaluated": False,
        "authentication_evaluated": False,
        "quota_evaluated": False,
        "availability_evaluated": False,
        "atready_network_accessed": False,
        "inventory_writes_performed": False,
        "external_process_executed": False,
        "external_process_side_effects": "not-applicable",
    }
    assert not marker.exists()


def test_discovery_reports_exact_scope_absence_without_running(tmp_path: Path) -> None:
    result = discover_local_resource(
        LocalDiscoveryRequest(profile="codex", executable=str(tmp_path / "codex"))
    )

    assert result.installed is False
    assert result.evidence == ("executable-not-located",)
    assert result.version_probe_performed is False
    assert result.resolved_path is None


@pytest.mark.skipif(os.name != "posix", reason="fixtures use POSIX executable scripts")
@pytest.mark.parametrize(
    ("profile", "executable_name"),
    (
        ("antigravity", "agy"),
        ("claude-code", "claude"),
        ("github-copilot", "copilot"),
    ),
)
def test_new_coding_agent_discovery_is_exact_and_locate_only(
    tmp_path: Path,
    profile: str,
    executable_name: str,
) -> None:
    marker = tmp_path / "unexpected-execution"
    executable = _make_executable(
        tmp_path / executable_name,
        f"touch '{marker}'\nprintf 'synthetic version\\n'\n",
    )

    result = discover_local_resource(
        LocalDiscoveryRequest(profile=profile, executable=str(executable))
    )

    assert result.executable_name == executable_name
    assert result.evidence == ("executable-located",)
    assert result.external_process_executed is False
    assert result.inventory_writes_performed is False
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="CodeRabbit CLI alias is POSIX/WSL-only")
def test_coderabbit_default_lookup_uses_alias_when_canonical_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "unexpected-execution"
    alias = _make_executable(
        tmp_path / "cr",
        f": > '{marker}'\nprintf 'synthetic coderabbit\\n'\n",
    )
    monkeypatch.setenv("PATH", str(tmp_path))

    default_result = discover_local_resource(LocalDiscoveryRequest(profile="coderabbit"))
    alias_result = discover_local_resource(
        LocalDiscoveryRequest(profile="coderabbit", executable=str(alias))
    )

    assert default_result.installed is True
    assert default_result.executable_name == "cr"
    assert default_result.resolved_path == str(alias)
    assert alias_result.installed is True
    assert alias_result.executable_name == "cr"
    assert alias_result.resolved_path == str(alias)
    assert alias_result.external_process_executed is False
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="CodeRabbit CLI alias is POSIX/WSL-only")
def test_coderabbit_default_lookup_prefers_canonical_before_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _make_executable(tmp_path / "coderabbit", "printf 'canonical\\n'\n")
    alias = tmp_path / "cr"
    os.link(canonical, alias)
    monkeypatch.setenv("PATH", str(tmp_path))

    result = discover_local_resource(LocalDiscoveryRequest(profile="coderabbit"))

    assert result.installed is True
    assert result.executable_name == "coderabbit"
    assert result.resolved_path == str(canonical)
    assert result.external_process_executed is False


@pytest.mark.skipif(os.name != "posix", reason="CodeRabbit CLI alias is POSIX/WSL-only")
def test_coderabbit_default_lookup_rejects_different_canonical_and_alias_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _make_executable(tmp_path / "coderabbit", "printf 'canonical\\n'\n")
    alias = _make_executable(tmp_path / "cr", "printf 'alias\\n'\n")
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(IntakeError) as error:
        discover_local_resource(LocalDiscoveryRequest(profile="coderabbit"))

    assert error.value.code == "ambiguous-provider-executable"
    assert str(canonical) not in str(error.value)
    assert str(alias) not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="fixture requires POSIX symlinks")
def test_bare_coderabbit_alias_rejects_a_different_resolved_executable_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _make_executable(tmp_path / "different-tool", "printf 'unexpected\\n'\n")
    alias = tmp_path / "cr"
    alias.symlink_to(target)
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(IntakeError) as error:
        discover_local_resource(LocalDiscoveryRequest(profile="coderabbit", executable="cr"))

    assert error.value.code == "unsafe-discovery-result"
    assert str(target) not in str(error.value)
    assert str(alias) not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="fixture requires POSIX symlinks")
def test_discovery_rejects_allowlisted_symlink_to_different_executable_name(
    tmp_path: Path,
) -> None:
    target = _make_executable(tmp_path / "different-tool", "printf '1.2.3\\n'\n")
    executable = tmp_path / "codex"
    executable.symlink_to(target)

    with pytest.raises(IntakeError) as error:
        discover_local_resource(LocalDiscoveryRequest(profile="codex", executable=str(executable)))

    assert error.value.code == "executable-not-allowed"


@pytest.mark.parametrize("executable", ["different-tool", "relative/codex"])
def test_discovery_rejects_executables_outside_exact_allowlist(executable: str) -> None:
    with pytest.raises(IntakeError) as error:
        discover_local_resource(LocalDiscoveryRequest(profile="codex", executable=executable))
    assert error.value.code == "executable-not-allowed"
    assert executable not in str(error.value)


def test_discovery_rejects_profiles_without_bundled_adapter() -> None:
    with pytest.raises(IntakeError) as error:
        discover_local_resource(LocalDiscoveryRequest(profile="figma"))
    assert error.value.code == "discovery-unavailable"

    with pytest.raises(IntakeError) as cursor_error:
        discover_local_resource(LocalDiscoveryRequest(profile="cursor"))
    assert cursor_error.value.code == "discovery-unavailable"


def test_windows_executable_variants_remain_exactly_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intake_module.os, "name", "nt")

    assert intake_module._allowed_executable_basename("CODEX.EXE", "codex")
    assert intake_module._allowed_executable_basename("codex.com", "codex")
    assert not intake_module._allowed_executable_basename("codex.cmd", "codex")
    assert not intake_module._allowed_executable_basename("other.exe", "codex")
    coderabbit_probe = resource_profile("coderabbit").executable_probe
    assert coderabbit_probe is not None
    assert intake_module._active_executable_aliases(coderabbit_probe) == ()
    assert not intake_module._allowed_executable_basename("CR.EXE", "coderabbit")
    assert not intake_module._allowed_executable_basename("cr.com", "coderabbit")


def test_posix_executable_allowlist_is_case_sensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intake_module.os, "name", "posix")

    assert intake_module._allowed_executable_basename("codex", "codex")
    assert intake_module._allowed_executable_basename("cr", "coderabbit", ("cr",))
    assert not intake_module._allowed_executable_basename("CODEX", "codex")
    assert not intake_module._allowed_executable_basename("CR", "coderabbit", ("cr",))


def test_coderabbit_discovery_fails_before_lookup_on_native_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intake_module.os, "name", "nt")

    def unexpected_lookup(_name: str) -> None:
        raise AssertionError("unsupported platform must fail before executable lookup")

    monkeypatch.setattr(intake_module.shutil, "which", unexpected_lookup)

    with pytest.raises(IntakeError) as error:
        discover_local_resource(LocalDiscoveryRequest(profile="coderabbit"))

    assert error.value.code == "discovery-platform-unsupported"
    assert "coderabbit" not in str(error.value).casefold()


@pytest.mark.parametrize("profile", ("claude-code", "github-copilot"))
def test_posix_only_coding_agent_discovery_fails_before_windows_lookup(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    monkeypatch.setattr(intake_module.os, "name", "nt")

    def unexpected_lookup(_name: str) -> None:
        raise AssertionError("unsupported platform must fail before executable lookup")

    monkeypatch.setattr(intake_module.shutil, "which", unexpected_lookup)

    with pytest.raises(IntakeError) as error:
        discover_local_resource(LocalDiscoveryRequest(profile=profile))

    assert error.value.code == "discovery-platform-unsupported"
    assert profile not in str(error.value).casefold()


@pytest.mark.skipif(os.name != "posix", reason="CodeRabbit CLI alias is POSIX/WSL-only")
def test_coderabbit_alias_version_probe_uses_only_the_fixed_argument(tmp_path: Path) -> None:
    alias = _make_executable(
        tmp_path / "cr",
        "test \"$#\" -eq 1\ntest \"$1\" = '--version'\nprintf 'coderabbit synthetic-1.2.3\\n'\n",
    )

    result = discover_local_resource(
        LocalDiscoveryRequest(
            profile="coderabbit",
            executable=str(alias),
            probe_version=True,
        )
    )

    assert result.executable_name == "cr"
    assert result.version == "coderabbit synthetic-1.2.3"
    assert result.evidence == ("executable-located", "version-observed")


@pytest.mark.skipif(os.name != "posix", reason="fixture uses a POSIX executable script")
def test_opt_in_version_probe_returns_only_sanitized_version_evidence(tmp_path: Path) -> None:
    executable = _make_executable(tmp_path / "codex", "printf 'codex 1.2.3\\nextra detail\\n'\n")

    result = discover_local_resource(
        LocalDiscoveryRequest(
            profile="codex",
            executable=str(executable),
            probe_version=True,
        )
    )

    assert result.version == "codex 1.2.3"
    assert result.version_probe_performed is True
    assert result.evidence == ("executable-located", "version-observed")
    assert result.account_status_evaluated is False
    assert result.authentication_evaluated is False
    assert result.quota_evaluated is False
    assert result.availability_evaluated is False
    assert result.external_process_executed is True
    assert result.external_process_side_effects == "not-evaluated"


@pytest.mark.skipif(os.name != "posix", reason="fixture uses a POSIX executable script")
def test_version_probe_discloses_that_external_side_effects_are_not_evaluated(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "external-side-effect"
    executable = _make_executable(
        tmp_path / "codex",
        f"touch '{marker}'\nprintf 'codex 9.9.9\\n'\n",
    )

    result = discover_local_resource(
        LocalDiscoveryRequest(profile="codex", executable=str(executable), probe_version=True)
    )

    assert marker.exists()
    assert result.inventory_writes_performed is False
    assert result.atready_network_accessed is False
    assert result.external_process_executed is True
    assert result.external_process_side_effects == "not-evaluated"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("while :; do sleep 1; done\n", "version-probe-timeout"),
        ("yes x\n", "version-output-too-large"),
        ("printf '\\377'\n", "malformed-version-output"),
        ("exit 7\n", "version-probe-failed"),
    ],
)
@pytest.mark.skipif(os.name != "posix", reason="fixtures use POSIX executable scripts")
def test_version_probe_fails_closed_with_value_free_errors(
    tmp_path: Path,
    body: str,
    code: str,
) -> None:
    executable = _make_executable(tmp_path / "codex", body)

    with pytest.raises(IntakeError) as error:
        discover_local_resource(
            LocalDiscoveryRequest(
                profile="codex",
                executable=str(executable),
                probe_version=True,
            )
        )

    assert error.value.code == code
    assert str(executable) not in str(error.value)
    assert not any(
        thread.name == "atready-version-probe" and thread.is_alive()
        for thread in threading.enumerate()
    )


@pytest.mark.skipif(os.name != "posix", reason="fixture requires fork and setsid")
def test_version_probe_timeout_is_bounded_when_detached_child_keeps_output_open(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "detached-pid"
    child_code = f"""
import os
import time

pid = os.fork()
if pid == 0:
    os.setsid()
    with open({str(marker)!r}, "w", encoding="ascii") as stream:
        stream.write(str(os.getpid()))
    while True:
        time.sleep(1)
while True:
    time.sleep(1)
"""
    executable = _make_executable(
        tmp_path / "codex",
        f"exec {shlex.quote(sys.executable)} -c {shlex.quote(child_code)}\n",
    )
    started = time.monotonic()
    detached_pid: int | None = None

    try:
        with pytest.raises(IntakeError) as error:
            discover_local_resource(
                LocalDiscoveryRequest(
                    profile="codex",
                    executable=str(executable),
                    probe_version=True,
                )
            )
        assert error.value.code == "version-probe-timeout"
        assert time.monotonic() - started < 4.0
        for _ in range(50):
            if marker.exists():
                detached_pid = int(marker.read_text(encoding="ascii"))
                break
            time.sleep(0.02)
        assert detached_pid is not None
    finally:
        if detached_pid is None and marker.exists():
            detached_pid = int(marker.read_text(encoding="ascii"))
        if detached_pid is not None:
            try:
                os.kill(detached_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    for _ in range(100):
        if not any(
            thread.name == "atready-version-probe" and thread.is_alive()
            for thread in threading.enumerate()
        ):
            break
        time.sleep(0.02)
    assert not any(
        thread.name == "atready-version-probe" and thread.is_alive()
        for thread in threading.enumerate()
    )
