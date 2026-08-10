"""Bundled catalog proposals and explicitly bounded local resource discovery."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from unicodedata import category as unicode_category

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from atready.models import InteractionMode, ResourceName, Slug, StrictBoolean

_VERSION_OUTPUT_LIMIT = 4_096
_VERSION_TIMEOUT_SECONDS = 3.0
_DISCOVERY_LIMITATIONS = (
    "account-status-not-evaluated",
    "authentication-not-evaluated",
    "quota-not-evaluated",
    "availability-not-evaluated",
)


def _reject_control_characters(value: str) -> str:
    if any(unicode_category(character) in {"Cc", "Cf"} for character in value):
        raise ValueError("text must not contain control or format characters")
    return value


CatalogLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
GuidanceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=320),
    AfterValidator(_reject_control_characters),
]
ProfileQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
ExecutableValue = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4_096),
]


class IntakeContract(BaseModel):
    """Immutable, typo-rejecting contract for the public intake seam."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class CatalogSuggestion(IntakeContract):
    id: Slug
    label: CatalogLabel


class CapacityUnitHint(IntakeContract):
    unit: Slug
    label: CatalogLabel


class ExecutableProbe(IntakeContract):
    executable: Slug
    supported_platforms: tuple[Literal["posix", "windows"], ...] = ("posix", "windows")
    aliases: Annotated[tuple[Slug, ...], Field(max_length=8)] = ()
    alias_platforms: tuple[Literal["posix", "windows"], ...] = ()
    version_args: Annotated[tuple[ExecutableValue, ...], Field(max_length=8)] = ()

    @model_validator(mode="after")
    def require_distinct_executable_names(self) -> ExecutableProbe:
        names = (self.executable, *self.aliases)
        if len(names) != len(set(names)):
            raise ValueError("executable names must be distinct")
        if not self.supported_platforms:
            raise ValueError("executable discovery requires at least one supported platform")
        if len(self.supported_platforms) != len(set(self.supported_platforms)):
            raise ValueError("supported executable platforms must be distinct")
        if self.aliases and not self.alias_platforms:
            raise ValueError("executable aliases require at least one platform")
        if self.alias_platforms and not self.aliases:
            raise ValueError("executable alias platforms require at least one alias")
        if len(self.alias_platforms) != len(set(self.alias_platforms)):
            raise ValueError("executable alias platforms must be distinct")
        if not set(self.alias_platforms).issubset(self.supported_platforms):
            raise ValueError("executable alias platforms must be supported")
        return self

    @field_validator("version_args")
    @classmethod
    def require_safe_fixed_arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for argument in value:
            if not argument.startswith("-") or any(
                unicode_category(character) in {"Cc", "Cf"} for character in argument
            ):
                raise ValueError("version arguments must be fixed option tokens")
        return value


class WorkflowModeSuggestion(IntakeContract):
    """One editable provider workflow proposal and its inventory interaction mapping."""

    id: Slug
    label: CatalogLabel
    interaction_suggestion: InteractionMode
    guidance: GuidanceText


class ProviderGuidanceItem(IntakeContract):
    """One bounded prompt that collects a user declaration without inspecting a provider."""

    id: Slug
    prompt: GuidanceText


class ModelRoutingSuggestion(IntakeContract):
    """One dated, editable model-to-resource planning proposal."""

    id: Slug
    label: CatalogLabel
    provider_model_id: CatalogLabel
    suggested_resource_id: Slug
    selection_status: Literal["named-option", "temporary-option", "standalone-model"]
    planning_role: GuidanceText
    planning_caution: GuidanceText
    shared_capacity_group: Slug | None = None
    availability: Literal["unverified"] = "unverified"
    capability_scores: Literal["user-confirmed-only"] = "user-confirmed-only"


class ProviderIntegrationKit(IntakeContract):
    """Provider-specific proposal data, never a connector or execution adapter."""

    workflow_mode_suggestions: Annotated[tuple[WorkflowModeSuggestion, ...], Field(max_length=16)]
    onboarding_guidance: Annotated[tuple[ProviderGuidanceItem, ...], Field(max_length=16)]
    capacity_guidance: Annotated[tuple[ProviderGuidanceItem, ...], Field(max_length=16)]
    model_routing_suggestions: Annotated[
        tuple[ModelRoutingSuggestion, ...], Field(max_length=16)
    ] = ()
    model_catalog_reviewed_on: date | None = None
    suggestions_are_proposals: Literal[True] = True
    account_inspection: Literal["unsupported"] = "unsupported"
    atready_network_access: Literal["none"] = "none"
    provider_execution: Literal["unsupported"] = "unsupported"

    @model_validator(mode="after")
    def require_distinct_guidance_ids(self) -> ProviderIntegrationKit:
        for collection in (
            self.workflow_mode_suggestions,
            self.onboarding_guidance,
            self.capacity_guidance,
        ):
            if not collection:
                raise ValueError("provider kit sections must not be empty")
            identifiers = tuple(item.id for item in collection)
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("provider kit item IDs must be distinct within each section")
        if bool(self.model_routing_suggestions) != bool(self.model_catalog_reviewed_on):
            raise ValueError(
                "model routing suggestions and their catalog review date must appear together"
            )
        if self.model_routing_suggestions:
            identifiers = tuple(item.id for item in self.model_routing_suggestions)
            resource_ids = tuple(
                item.suggested_resource_id for item in self.model_routing_suggestions
            )
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("model routing suggestion IDs must be distinct")
            if len(resource_ids) != len(set(resource_ids)):
                raise ValueError("model routing suggested resource IDs must be distinct")
        return self


class ResourceProfile(IntakeContract):
    """Bundled catalog metadata whose suggestions require separate confirmation."""

    catalog_version: Literal[1] = 1
    id: Slug
    name: ResourceName
    aliases: Annotated[tuple[ProfileQuery, ...], Field(max_length=16)] = ()
    category_suggestions: tuple[CatalogSuggestion, ...]
    capability_suggestions: tuple[CatalogSuggestion, ...]
    capacity_unit_hints: tuple[CapacityUnitHint, ...] = ()
    executable_probe: ExecutableProbe | None = None
    provider_kit: ProviderIntegrationKit | None = None
    suggestions_are_proposals: Literal[True] = True


class LocalDiscoveryRequest(IntakeContract):
    """One explicit grant for one bundled profile and one allowlisted executable."""

    profile: ProfileQuery
    executable: ExecutableValue | None = None
    probe_version: StrictBoolean = False

    @field_validator("executable")
    @classmethod
    def reject_unsafe_executable_text(cls, value: str | None) -> str | None:
        if value is not None and any(
            unicode_category(character) in {"Cc", "Cf"} for character in value
        ):
            raise ValueError("discovery executable must not contain control characters")
        return value


class LocalDiscoveryResult(IntakeContract):
    profile_id: Slug
    executable_name: Slug
    search_scope: Literal["current-path", "exact-path"]
    installed: StrictBoolean
    resolved_path: str | None = None
    version_probe_performed: StrictBoolean
    version: str | None = None
    evidence: tuple[
        Literal["executable-located", "executable-not-located", "version-observed"], ...
    ]
    limitations: tuple[
        Literal[
            "account-status-not-evaluated",
            "authentication-not-evaluated",
            "quota-not-evaluated",
            "availability-not-evaluated",
        ],
        ...,
    ] = _DISCOVERY_LIMITATIONS
    account_status_evaluated: Literal[False] = False
    authentication_evaluated: Literal[False] = False
    quota_evaluated: Literal[False] = False
    availability_evaluated: Literal[False] = False
    atready_network_accessed: Literal[False] = False
    inventory_writes_performed: Literal[False] = False
    external_process_executed: StrictBoolean = False
    external_process_side_effects: Literal["not-applicable", "not-evaluated"] = "not-applicable"

    @model_validator(mode="after")
    def require_consistent_process_disclosure(self) -> LocalDiscoveryResult:
        expected = "not-evaluated" if self.external_process_executed else "not-applicable"
        if self.version_probe_performed != self.external_process_executed:
            raise ValueError("version probe and external process state must agree")
        if self.external_process_side_effects != expected:
            raise ValueError("external process side-effect state is inconsistent")
        return self


class IntakeError(ValueError):
    """A value-free intake failure safe to render at the CLI boundary."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.safe_message}


def _suggestion(identifier: str, label: str) -> CatalogSuggestion:
    return CatalogSuggestion(id=identifier, label=label)


def _unit(identifier: str, label: str) -> CapacityUnitHint:
    return CapacityUnitHint(unit=identifier, label=label)


def _workflow_mode(
    identifier: str,
    label: str,
    interaction: InteractionMode,
    guidance: str,
) -> WorkflowModeSuggestion:
    return WorkflowModeSuggestion(
        id=identifier,
        label=label,
        interaction_suggestion=interaction,
        guidance=guidance,
    )


def _guidance(identifier: str, prompt: str) -> ProviderGuidanceItem:
    return ProviderGuidanceItem(id=identifier, prompt=prompt)


def _model_routing_suggestion(
    identifier: str,
    label: str,
    provider_model_id: str,
    suggested_resource_id: str,
    selection_status: Literal["named-option", "temporary-option", "standalone-model"],
    planning_role: str,
    planning_caution: str,
    *,
    shared_capacity_group: str | None = None,
) -> ModelRoutingSuggestion:
    return ModelRoutingSuggestion(
        id=identifier,
        label=label,
        provider_model_id=provider_model_id,
        suggested_resource_id=suggested_resource_id,
        selection_status=selection_status,
        planning_role=planning_role,
        planning_caution=planning_caution,
        shared_capacity_group=shared_capacity_group,
    )


BUNDLED_RESOURCE_PROFILES: tuple[ResourceProfile, ...] = (
    ResourceProfile(
        id="antigravity",
        name="Google Antigravity",
        aliases=("antigravity-cli", "google-antigravity", "agy"),
        category_suggestions=(_suggestion("coding-agent", "Coding agent"),),
        capability_suggestions=(
            _suggestion("code-implementation", "Code implementation"),
            _suggestion("repository-analysis", "Repository analysis"),
            _suggestion("software-planning", "Software planning"),
            _suggestion("multi-agent-orchestration", "Multi-agent orchestration"),
            _suggestion("research", "Research"),
        ),
        capacity_unit_hints=(
            _unit("agent-task", "Agent tasks"),
            _unit("ai-credit", "AI credits"),
        ),
        executable_probe=ExecutableProbe(executable="agy"),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "interactive-terminal",
                    "Interactive terminal session",
                    InteractionMode.LOCAL_CLI,
                    "Use when a person works in the Antigravity terminal interface; confirm the "
                    "project scope and current readiness before routing.",
                ),
                _workflow_mode(
                    "authorized-headless",
                    "Separately authorized headless task",
                    InteractionMode.CODEX_CALLABLE,
                    "Use only when the user declares that the current host may separately invoke "
                    "Antigravity for one bounded task; onboarding grants no execution authority.",
                ),
                _workflow_mode(
                    "desktop-or-ide",
                    "Person-mediated desktop or IDE use",
                    InteractionMode.MANUAL,
                    "Use when a person transfers work through Antigravity's visual editor or IDE "
                    "rather than exposing a callable agent to AtReady.",
                ),
                _workflow_mode(
                    "background-agents",
                    "Separately configured background agents",
                    InteractionMode.EXTERNAL_AGENT,
                    "Use only for a user-declared background-agent workflow with its own "
                    "readiness, project scope, and later execution authorization.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "workflow-surface",
                    "Ask whether Antigravity is used in the terminal, headlessly, through the "
                    "desktop or IDE, or as separately configured background agents.",
                ),
                _guidance(
                    "planning-fit",
                    "Ask which implementation, repository-analysis, planning, orchestration, and "
                    "research work the user's current setup actually handles well.",
                ),
                _guidance(
                    "permission-boundary",
                    "Ask what project data and actions the user allows. Do not inspect projects, "
                    "settings, models, authentication, account details, or credentials.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "baseline-room",
                    "Ask for qualitative baseline-quota room unless the user has a trustworthy "
                    "exact unit; do not infer capacity from a Google AI plan name.",
                ),
                _guidance(
                    "credits-and-reset",
                    "If known, ask separately for AI credits, the governing model, and reset time; "
                    "never convert baseline room into credits or tasks.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record whether readiness and capacity are observed or user judgment and when "
                    "they were checked; never inspect usage or account state.",
                ),
            ),
        ),
    ),
    ResourceProfile(
        id="coderabbit",
        name="CodeRabbit",
        aliases=("code-rabbit", "coderabbitai", "coderabbit-cli"),
        category_suggestions=(_suggestion("review-agent", "Code review agent"),),
        capability_suggestions=(
            _suggestion("code-review", "Code review"),
            _suggestion("repository-analysis", "Repository analysis"),
        ),
        capacity_unit_hints=(
            _unit("review-request", "Review requests"),
            _unit("review-file", "Files reviewed"),
        ),
        executable_probe=ExecutableProbe(
            executable="coderabbit",
            supported_platforms=("posix",),
            aliases=("cr",),
            alias_platforms=("posix",),
            version_args=("--version",),
        ),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "local-cli",
                    "Local CLI review",
                    InteractionMode.LOCAL_CLI,
                    "Use when the user separately runs CodeRabbit from an authorized terminal "
                    "context; confirm the exact repository scope before any later handoff.",
                ),
                _workflow_mode(
                    "pull-request-app",
                    "Pull-request app review",
                    InteractionMode.EXTERNAL_AGENT,
                    "Use when a separately configured repository app reviews pull requests; "
                    "treat installation and repository access as user-declared facts.",
                ),
                _workflow_mode(
                    "manual-review",
                    "Manual review request",
                    InteractionMode.MANUAL,
                    "Use when a person triggers CodeRabbit and transfers the review result "
                    "without AtReady invoking the provider.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "workflow-mode",
                    "Ask which CodeRabbit workflow the user uses, then confirm or edit the "
                    "suggested interaction mapping; do not infer installation or access.",
                ),
                _guidance(
                    "review-scope",
                    "Ask which repository or pull-request scope may be considered, using "
                    "descriptions only and never credentials, tokens, or secret values.",
                ),
                _guidance(
                    "session-readiness",
                    "Ask whether that workflow is usable in the current session; preserve "
                    "unknown when readiness has not been verified.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "remaining-allowance",
                    "If known, ask for remaining review capacity and its exact unit, such as "
                    "review requests or reviewed files; otherwise preserve unknown.",
                ),
                _guidance(
                    "limit-and-reset",
                    "If known, ask separately for the total limit, project limit, and reset "
                    "date without converting between capacity units.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record whether the capacity declaration is observed or user judgment and "
                    "when it was verified; never infer capacity from a plan name.",
                ),
            ),
        ),
    ),
    ResourceProfile(
        id="codex",
        name="Codex",
        aliases=("openai-codex", "codex-cli"),
        category_suggestions=(_suggestion("coding-agent", "Coding agent"),),
        capability_suggestions=(
            _suggestion("code-implementation", "Code implementation"),
            _suggestion("code-review", "Code review"),
            _suggestion("repository-analysis", "Repository analysis"),
        ),
        capacity_unit_hints=(
            _unit("agent-task", "Agent tasks"),
            _unit("token", "Tokens"),
        ),
        executable_probe=ExecutableProbe(executable="codex", version_args=("--version",)),
    ),
    ResourceProfile(
        id="claude-code",
        name="Claude Code",
        aliases=("claudecode", "anthropic-claude-code", "claude-cli"),
        category_suggestions=(_suggestion("coding-agent", "Coding agent"),),
        capability_suggestions=(
            _suggestion("code-implementation", "Code implementation"),
            _suggestion("code-review", "Code review"),
            _suggestion("repository-analysis", "Repository analysis"),
            _suggestion("software-planning", "Software planning"),
        ),
        capacity_unit_hints=(
            _unit("agent-task", "Agent tasks"),
            _unit("token", "Tokens"),
            _unit("credit", "Usage credits"),
        ),
        executable_probe=ExecutableProbe(
            executable="claude",
            supported_platforms=("posix",),
            version_args=("--version",),
        ),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "interactive-terminal",
                    "Interactive terminal session",
                    InteractionMode.LOCAL_CLI,
                    "Use when a person works with Claude Code in a terminal; confirm project "
                    "scope and current readiness before routing.",
                ),
                _workflow_mode(
                    "delegated-headless",
                    "Separately authorized headless task",
                    InteractionMode.CODEX_CALLABLE,
                    "Use only when the user declares that the current host may separately invoke "
                    "Claude Code for one bounded task; onboarding grants no execution authority.",
                ),
                _workflow_mode(
                    "ide-or-remote",
                    "Person-mediated IDE, desktop, or web use",
                    InteractionMode.MANUAL,
                    "Use when a person transfers work through an IDE, desktop, or web session "
                    "instead of exposing a callable agent to AtReady.",
                ),
                _workflow_mode(
                    "configured-ci",
                    "Separately configured CI automation",
                    InteractionMode.EXTERNAL_AGENT,
                    "Use only for user-declared repository automation with its own access, "
                    "readiness, policy, capacity, and later execution authorization.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "workflow-surface",
                    "Ask whether Claude Code is used interactively, by a separately authorized "
                    "headless caller, through an IDE or remote surface, or in configured CI.",
                ),
                _guidance(
                    "planning-fit",
                    "Ask which implementation, review, repository-analysis, and planning work the "
                    "user's configured Claude Code setup actually handles well.",
                ),
                _guidance(
                    "permission-boundary",
                    "Ask what project data and actions the user allows. Do not inspect Claude "
                    "files, instructions, providers, models, permissions, authentication, or "
                    "credentials.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "usage-room",
                    "Ask for qualitative subscription room or an exact API-governed unit; do not "
                    "infer remaining use from a plan name or model.",
                ),
                _guidance(
                    "remaining-and-reset",
                    "If known, ask for remaining tasks, tokens, credits, or spend and the reset "
                    "time without combining unlike limits.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record whether capability and capacity are observed or user judgment and "
                    "when they were checked; never inspect usage, billing, or account state.",
                ),
            ),
        ),
    ),
    ResourceProfile(
        id="cursor",
        name="Cursor",
        aliases=("cursor-ai", "cursor-editor"),
        category_suggestions=(_suggestion("coding-agent", "Coding agent"),),
        capability_suggestions=(
            _suggestion("code-implementation", "Code implementation"),
            _suggestion("code-review", "Code review"),
            _suggestion("repository-analysis", "Repository analysis"),
            _suggestion("software-planning", "Software planning"),
        ),
        capacity_unit_hints=(
            _unit("agent-task", "Agent tasks"),
            _unit("token", "Tokens"),
            _unit("usage-dollar", "Usage dollars"),
        ),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "cursor-editor",
                    "Person-mediated Cursor editor use",
                    InteractionMode.MANUAL,
                    "Use when a person works with Cursor's editor and Agent surface and transfers "
                    "the result rather than exposing a callable agent to AtReady.",
                ),
                _workflow_mode(
                    "interactive-cli",
                    "Interactive Cursor CLI session",
                    InteractionMode.LOCAL_CLI,
                    "Use when a person works with Cursor's CLI interactively; confirm project "
                    "scope and current readiness before routing.",
                ),
                _workflow_mode(
                    "authorized-headless-cli",
                    "Separately authorized headless CLI task",
                    InteractionMode.CODEX_CALLABLE,
                    "Use only when the user declares that the current host may separately invoke "
                    "Cursor's CLI for one bounded task; onboarding grants no execution authority.",
                ),
                _workflow_mode(
                    "cloud-agent",
                    "Separately configured Cloud Agent",
                    InteractionMode.EXTERNAL_AGENT,
                    "Use only for a user-declared Cloud Agent workflow with its own repository "
                    "scope, readiness, policy, capacity, and later execution authorization.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "workflow-surface",
                    "Ask whether Cursor is used in the editor, interactive CLI, separately "
                    "authorized headless CLI, or as a configured Cloud Agent.",
                ),
                _guidance(
                    "planning-fit",
                    "Ask which implementation, review, repository-analysis, and planning work the "
                    "user's configured Cursor setup actually handles well.",
                ),
                _guidance(
                    "permission-boundary",
                    "Ask what project data and actions the user allows. Do not inspect Cursor "
                    "rules, configuration, models, authentication, repositories, or credentials.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "usage-pool",
                    "Ask which declared usage pool or self-imposed task or spend budget governs "
                    "this workflow; do not infer capacity from a plan name.",
                ),
                _guidance(
                    "remaining-and-reset",
                    "If known, ask for the exact remaining amount, unit, reset date, and any "
                    "separate Cloud Agent cap without converting tokens, money, or tasks.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record whether readiness and capacity are observed or user judgment and when "
                    "they were checked; never inspect dashboard or account state.",
                ),
            ),
            model_routing_suggestions=(
                _model_routing_suggestion(
                    "composer-2-5",
                    "Composer 2.5",
                    "composer-2.5",
                    "cursor-composer-2-5",
                    "named-option",
                    "Cost-efficient agentic coding for well-scoped implementation, iteration, "
                    "tests, and routine refactors.",
                    "Treat difficulty, quality, and speed as user-confirmed scores; catalog copy "
                    "never ranks this model automatically.",
                    shared_capacity_group="cursor-models-pool",
                ),
                _model_routing_suggestion(
                    "grok-4-5",
                    "Cursor Grok 4.5",
                    "grok-4.5",
                    "cursor-grok-4-5",
                    "named-option",
                    "Hard long-running coding, migration, architecture, investigation, and "
                    "knowledge-work tasks that benefit from sustained reasoning.",
                    "Confirm current plan, region, access, and measured fit; do not infer that it "
                    "is available or preferable for every task.",
                    shared_capacity_group="cursor-models-pool",
                ),
            ),
            model_catalog_reviewed_on=date(2026, 8, 9),
        ),
    ),
    ResourceProfile(
        id="github-copilot",
        name="GitHub Copilot",
        aliases=("copilot", "copilot-cli", "github-copilot-cli"),
        category_suggestions=(_suggestion("coding-agent", "Coding agent"),),
        capability_suggestions=(
            _suggestion("code-implementation", "Code implementation"),
            _suggestion("code-review", "Code review"),
            _suggestion("debugging", "Debugging"),
            _suggestion("repository-analysis", "Repository analysis"),
            _suggestion("software-planning", "Software planning"),
            _suggestion("github-workflow", "GitHub workflow support"),
        ),
        capacity_unit_hints=(
            _unit("agent-task", "Agent tasks"),
            _unit("token", "Tokens"),
            _unit("ai-credit", "GitHub AI credits"),
        ),
        executable_probe=ExecutableProbe(
            executable="copilot",
            supported_platforms=("posix",),
        ),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "interactive-terminal",
                    "Interactive terminal session",
                    InteractionMode.LOCAL_CLI,
                    "Use when a person works with Copilot in the terminal; confirm repository "
                    "scope and current readiness before routing.",
                ),
                _workflow_mode(
                    "delegated-cli",
                    "Separately authorized programmatic task",
                    InteractionMode.CODEX_CALLABLE,
                    "Use only when the user declares that the current host may separately invoke "
                    "Copilot for one bounded prompt; onboarding grants no execution authority.",
                ),
                _workflow_mode(
                    "coding-agent-delegation",
                    "Separately configured coding-agent delegation",
                    InteractionMode.EXTERNAL_AGENT,
                    "Use only for a user-declared GitHub-hosted workflow with its own repository "
                    "scope, readiness, policy, capacity, and later execution authorization.",
                ),
                _workflow_mode(
                    "editor-or-app",
                    "Person-mediated editor or app use",
                    InteractionMode.MANUAL,
                    "Use when a person transfers work through an editor or Copilot app rather "
                    "than exposing a callable agent to AtReady.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "workflow-surface",
                    "Ask whether Copilot is used in the terminal, programmatically, through "
                    "coding-agent delegation, or person-mediated in an editor or app.",
                ),
                _guidance(
                    "planning-fit",
                    "Ask which implementation, review, debugging, repository, planning, and "
                    "GitHub workflow tasks the user's configured Copilot setup handles well.",
                ),
                _guidance(
                    "permission-boundary",
                    "Ask what repositories, project data, and actions the user allows. Do not "
                    "inspect Copilot configuration, plugins, models, authentication, or "
                    "credentials.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "plan-and-policy",
                    "Ask for qualitative room and whether organization policy can block this "
                    "surface; do not infer readiness or capacity from a Copilot plan name.",
                ),
                _guidance(
                    "credits-and-reset",
                    "If known, ask for remaining GitHub AI credits or the exact governing unit "
                    "and reset time without converting credits, tokens, or tasks.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record whether readiness and capacity are observed or user judgment and when "
                    "they were checked; never inspect usage, billing, policy, or account state.",
                ),
            ),
        ),
    ),
    ResourceProfile(
        id="opencode",
        name="OpenCode",
        aliases=("open-code", "opencode-cli"),
        category_suggestions=(_suggestion("coding-agent", "Coding agent"),),
        capability_suggestions=(
            _suggestion("code-implementation", "Code implementation"),
            _suggestion("code-review", "Code review"),
            _suggestion("repository-analysis", "Repository analysis"),
            _suggestion("software-planning", "Software planning"),
        ),
        capacity_unit_hints=(
            _unit("agent-task", "Agent tasks"),
            _unit("token", "Tokens"),
            _unit("credit", "Provider credits"),
        ),
        executable_probe=ExecutableProbe(executable="opencode", version_args=("--version",)),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "interactive-terminal",
                    "Interactive terminal session",
                    InteractionMode.LOCAL_CLI,
                    "Use when a person works with OpenCode through its terminal interface; "
                    "confirm the project scope and current readiness before routing.",
                ),
                _workflow_mode(
                    "delegated-cli",
                    "Separately authorized CLI task",
                    InteractionMode.CODEX_CALLABLE,
                    "Use only when the user declares that the current host may separately invoke "
                    "OpenCode for a bounded task; onboarding never grants that authority.",
                ),
                _workflow_mode(
                    "desktop-or-ide",
                    "Person-mediated desktop or IDE use",
                    InteractionMode.MANUAL,
                    "Use when a person transfers work through the OpenCode desktop app or IDE "
                    "extension rather than exposing a callable agent to AtReady.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "workflow-surface",
                    "Ask whether OpenCode is used in a terminal, by a separately authorized CLI "
                    "caller, or through its desktop or IDE surface.",
                ),
                _guidance(
                    "planning-fit",
                    "Ask which coding, review, repository-analysis, and planning work it is "
                    "actually useful for; rate the user's configured setup, not OpenCode in the "
                    "abstract.",
                ),
                _guidance(
                    "permission-boundary",
                    "Ask what project data and actions the user allows. Do not inspect OpenCode "
                    "configuration, providers, models, authentication, or credentials.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "provider-budget",
                    "If usage is limited, ask for the governing provider's exact unit, such as "
                    "tokens, credits, or tasks; do not infer a budget from OpenCode itself.",
                ),
                _guidance(
                    "remaining-and-reset",
                    "If known, ask for the remaining amount, full limit, and reset date; otherwise "
                    "preserve qualitative room or unknown.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record whether capability and capacity are observed or user judgment and "
                    "when they were checked; never inspect provider billing or account state.",
                ),
            ),
            model_routing_suggestions=(
                _model_routing_suggestion(
                    "deepseek-v4-flash-free",
                    "DeepSeek V4 Flash Free",
                    "opencode/deepseek-v4-flash-free",
                    "opencode-deepseek-v4-flash-free",
                    "temporary-option",
                    "A currently free OpenCode Zen option to calibrate on well-scoped coding "
                    "tasks when cost sensitivity matters.",
                    "It is temporary and not OpenCode's universal default; confirm data policy, "
                    "current availability, and task quality before routing.",
                ),
            ),
            model_catalog_reviewed_on=date(2026, 8, 9),
        ),
    ),
    ResourceProfile(
        id="grok",
        name="Grok",
        aliases=("xai-grok", "grok-chat"),
        category_suggestions=(_suggestion("general-agent", "General-purpose AI agent"),),
        capability_suggestions=(
            _suggestion("research", "Research"),
            _suggestion("analysis", "Analysis"),
            _suggestion("software-planning", "Software planning"),
            _suggestion("code-review", "Code review"),
        ),
        capacity_unit_hints=(
            _unit("request", "Requests"),
            _unit("token", "Tokens"),
        ),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "grok-app",
                    "Person-mediated Grok app or web use",
                    InteractionMode.MANUAL,
                    "Use when a person transfers prompts and results through Grok without "
                    "exposing a callable provider to AtReady.",
                ),
                _workflow_mode(
                    "xai-api",
                    "Separately configured xAI API workflow",
                    InteractionMode.EXTERNAL_AGENT,
                    "Use only for a user-declared API workflow with its own access, policy, "
                    "capacity, and later execution authorization.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "workflow-surface",
                    "Ask whether Grok 4.5 is used through the standalone app, web, API, or another "
                    "separately configured surface.",
                ),
                _guidance(
                    "planning-fit",
                    "Ask which research, analysis, planning, and review tasks this configured "
                    "surface actually handles well; never copy vendor claims into scores.",
                ),
                _guidance(
                    "permission-boundary",
                    "Ask what data and actions are allowed. Do not inspect xAI configuration, "
                    "account, models, authentication, usage, or credentials.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "governing-capacity",
                    "Ask whether the governing limit is a subscription allowance, API tokens, "
                    "requests, or spend; never combine unlike surfaces or units.",
                ),
                _guidance(
                    "remaining-and-reset",
                    "If known, ask for the exact remaining amount, limit, and reset date; "
                    "otherwise preserve qualitative room or unknown.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record how and when capacity was checked; never inspect provider billing, "
                    "quota, or account state.",
                ),
            ),
            model_routing_suggestions=(
                _model_routing_suggestion(
                    "grok-4-5",
                    "Grok 4.5",
                    "grok-4.5",
                    "grok-4-5",
                    "standalone-model",
                    "Complex reasoning across code, architecture, research, analysis, and "
                    "multi-step professional work.",
                    "The app, API, and the Cursor-hosted version have different access, policy, "
                    "and capacity; confirm the exact surface rather than treating them as one "
                    "resource.",
                ),
            ),
            model_catalog_reviewed_on=date(2026, 8, 9),
        ),
    ),
    ResourceProfile(
        id="pixellab",
        name="PixelLab",
        aliases=("pixel-lab", "pixellab-ai", "pixel lab"),
        category_suggestions=(_suggestion("creative-tool", "Creative tool"),),
        capability_suggestions=(
            _suggestion("pixel-art-generation", "Pixel art generation"),
            _suggestion("sprite-generation", "Sprite generation"),
            _suggestion("sprite-animation", "Sprite animation"),
            _suggestion("pixel-art-editing", "Pixel art editing"),
            _suggestion("map-generation", "Map generation"),
        ),
        capacity_unit_hints=(
            _unit("image", "Images"),
            _unit("credit", "Credits"),
        ),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "web-creator",
                    "Person-mediated web creator",
                    InteractionMode.MANUAL,
                    "Use when a person generates assets in PixelLab's simple web creator and "
                    "moves reviewed outputs into the project.",
                ),
                _workflow_mode(
                    "browser-editor",
                    "Person-mediated browser editor",
                    InteractionMode.MANUAL,
                    "Use when a person creates and edits assets in PixelLab Pixelorama rather "
                    "than exposing a callable service to AtReady.",
                ),
                _workflow_mode(
                    "aseprite-extension",
                    "Person-mediated Aseprite extension",
                    InteractionMode.MANUAL,
                    "Use when PixelLab is accessed through a user-operated Aseprite workflow; "
                    "confirm Aseprite and extension readiness separately.",
                ),
                _workflow_mode(
                    "configured-api",
                    "Separately configured API workflow",
                    InteractionMode.CODEX_CALLABLE,
                    "Use only when the user declares that this host may separately call an "
                    "already configured PixelLab API integration for a bounded task.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "workflow-surface",
                    "Ask whether PixelLab is used through the web creator, browser editor, "
                    "Aseprite extension, or a separately configured API integration.",
                ),
                _guidance(
                    "subscription-tier",
                    "Ask which tier the user declares. Catalog review on 2026-08-09 lists Pixel "
                    "Apprentice, Pixel Artisan, and Pixel Architect; treat every allowance and "
                    "tier feature as a proposal requiring confirmation.",
                ),
                _guidance(
                    "planning-fit",
                    "Ask which pixel generation, sprite, animation, editing, and map work the "
                    "user's current surface and tier actually handle well; do not infer scores.",
                ),
                _guidance(
                    "permission-boundary",
                    "Ask what project data and actions are allowed. Do not inspect PixelLab "
                    "projects, account, authentication, subscription, usage, or credentials.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "tier-allowance",
                    "Catalog review on 2026-08-09 lists Apprentice at 2,000 images monthly up to "
                    "320x320, Artisan at 5,000 images monthly up to 512x512 with up to 10 "
                    "concurrent jobs, and Architect at 10,000 images monthly with up to 20 "
                    "concurrent background jobs; confirm the user's current account before "
                    "recording any value.",
                ),
                _guidance(
                    "remaining-balance",
                    "If the user checks the PixelLab account page, ask for the exact remaining "
                    "images or credits, full limit, reset date, and one governing unit; never "
                    "combine images and credits.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record whether the balance is observed or user judgment and when it was "
                    "checked. AtReady does not refresh or decrement the balance.",
                ),
            ),
        ),
    ),
    ResourceProfile(
        id="retro-diffusion",
        name="Retro Diffusion",
        aliases=("retrodiffusion", "retro diffusion"),
        category_suggestions=(_suggestion("creative-tool", "Creative tool"),),
        capability_suggestions=(
            _suggestion("pixel-art-generation", "Pixel art generation"),
            _suggestion("sprite-generation", "Sprite generation"),
            _suggestion("sprite-animation", "Sprite animation"),
            _suggestion("pixel-art-editing", "Pixel art editing"),
            _suggestion("palette-editing", "Palette editing"),
        ),
        capacity_unit_hints=(
            _unit("generation", "Image generations"),
            _unit("credit", "Credits"),
        ),
        provider_kit=ProviderIntegrationKit(
            workflow_mode_suggestions=(
                _workflow_mode(
                    "cloud-website",
                    "Person-mediated cloud website",
                    InteractionMode.MANUAL,
                    "Use for the credit-based Retro Diffusion website when a person creates and "
                    "reviews assets before moving them into the project.",
                ),
                _workflow_mode(
                    "configured-api",
                    "Separately configured API workflow",
                    InteractionMode.CODEX_CALLABLE,
                    "Use only when the user declares that this host may separately call an "
                    "already configured Retro Diffusion API integration for a bounded task.",
                ),
                _workflow_mode(
                    "aseprite-extension",
                    "Owned local Aseprite extension",
                    InteractionMode.MANUAL,
                    "Use for the separately purchased local extension operated by a person; it "
                    "is not the cloud website and does not consume website credits.",
                ),
            ),
            onboarding_guidance=(
                _guidance(
                    "product-surface",
                    "Ask whether the resource is the credit-based website, a separately "
                    "configured website API, or the owned local Aseprite extension; never combine "
                    "their access, billing, or readiness.",
                ),
                _guidance(
                    "purchase-model",
                    "Catalog review on 2026-08-09 found website credits rather than a "
                    "subscription and a separate one-time extension purchase; ask the user to "
                    "confirm the current product and purchase model.",
                ),
                _guidance(
                    "planning-fit",
                    "Ask which pixel generation, sprite, animation, editing, and palette work the "
                    "user's selected Retro Diffusion surface actually handles well.",
                ),
                _guidance(
                    "permission-boundary",
                    "Ask what project data and actions are allowed. Do not inspect Retro Diffusion "
                    "projects, account, authentication, purchases, usage, or credentials.",
                ),
            ),
            capacity_guidance=(
                _guidance(
                    "website-credits",
                    "For the website, ask for the exact observed remaining credit balance and "
                    "checked date. Catalog review says credits do not expire; confirm that before "
                    "omitting a reset date.",
                ),
                _guidance(
                    "generation-cost",
                    "One website credit can cover a small image while larger images cost more; "
                    "store credits as the governing unit and never convert them into a fixed image "
                    "count.",
                ),
                _guidance(
                    "extension-capacity",
                    "The owned local extension has no credit balance. Keep capacity qualitative "
                    "unless the user declares a separate operational limit.",
                ),
                _guidance(
                    "capacity-provenance",
                    "Record how and when any balance was checked. AtReady does not refresh "
                    "or decrement credits and never inspects provider billing or account state.",
                ),
            ),
        ),
    ),
    ResourceProfile(
        id="figma",
        name="Figma",
        aliases=("figma-design",),
        category_suggestions=(_suggestion("design-tool", "Design tool"),),
        capability_suggestions=(
            _suggestion("interface-design", "Interface design"),
            _suggestion("design-prototyping", "Design prototyping"),
        ),
        capacity_unit_hints=(_unit("editor-seat", "Editor seats"),),
    ),
    ResourceProfile(
        id="blender",
        name="Blender",
        aliases=("blender-3d",),
        category_suggestions=(_suggestion("creative-tool", "Creative tool"),),
        capability_suggestions=(
            _suggestion("3d-modeling", "3D modeling"),
            _suggestion("3d-rendering", "3D rendering"),
        ),
        capacity_unit_hints=(_unit("render-minute", "Render minutes"),),
        executable_probe=ExecutableProbe(executable="blender", version_args=("--version",)),
    ),
)


def resource_profiles() -> tuple[ResourceProfile, ...]:
    """Return the bundled, offline proposal catalog in stable identifier order."""

    return tuple(sorted(BUNDLED_RESOURCE_PROFILES, key=lambda profile: profile.id))


def _match_key(value: str) -> str:
    return "-".join(value.strip().casefold().replace("_", "-").split())


def resource_profile(query: str) -> ResourceProfile:
    """Resolve one exact profile id or unambiguous alias without echoing failures."""

    if (
        not isinstance(query, str)
        or not 1 <= len(query.strip()) <= 120
        or any(unicode_category(character) in {"Cc", "Cf"} for character in query)
    ):
        raise IntakeError("unknown-profile", "resource profile is not in the bundled catalog")
    candidate = _match_key(query)
    exact = tuple(profile for profile in BUNDLED_RESOURCE_PROFILES if profile.id == candidate)
    if len(exact) == 1:
        return exact[0]
    matches = tuple(
        profile
        for profile in BUNDLED_RESOURCE_PROFILES
        if candidate in {_match_key(alias) for alias in profile.aliases}
    )
    if len(matches) > 1:
        raise IntakeError("ambiguous-profile", "resource profile alias is ambiguous")
    if not matches:
        raise IntakeError("unknown-profile", "resource profile is not in the bundled catalog")
    return matches[0]


def _allowed_executable_basename(
    name: str,
    expected: str,
    aliases: tuple[str, ...] = (),
) -> bool:
    if os.name == "nt":
        candidate = name.casefold()
        allowed = {value.casefold() for value in (expected, *aliases)}
        allowed.update(
            f"{value.casefold()}{suffix}"
            for value in (expected, *aliases)
            for suffix in (".exe", ".com")
        )
        return candidate in allowed
    return name in {expected, *aliases}


def _active_executable_aliases(probe: ExecutableProbe) -> tuple[str, ...]:
    platform = _current_platform()
    return probe.aliases if platform in probe.alias_platforms else ()


def _current_platform() -> Literal["posix", "windows"]:
    return "windows" if os.name == "nt" else "posix"


def _safe_executable_path(path: Path) -> Path:
    absolute = path.absolute()
    resolved = path.resolve()
    for candidate in (absolute, resolved):
        if len(str(candidate)) > 4_096 or any(
            unicode_category(character) in {"Cc", "Cf"} for character in str(candidate)
        ):
            raise IntakeError(
                "unsafe-discovery-result",
                "executable lookup returned an unsafe result",
            )
    return absolute


def _resolve_executable(
    request: LocalDiscoveryRequest,
    profile: ResourceProfile,
) -> tuple[Path | None, Literal["current-path", "exact-path"], str]:
    probe = profile.executable_probe
    if probe is None:
        raise IntakeError(
            "discovery-unavailable",
            "this resource profile has no bundled local discovery adapter",
        )
    if _current_platform() not in probe.supported_platforms:
        raise IntakeError(
            "discovery-platform-unsupported",
            "local discovery is not supported for this profile on the current platform",
        )
    active_aliases = _active_executable_aliases(probe)
    if request.executable is None:
        located_candidates: list[tuple[Path, str]] = []
        for candidate in (probe.executable, *active_aliases):
            located = shutil.which(candidate)
            if located is None:
                continue
            resolved = Path(located)
            if not resolved.is_absolute() or not _allowed_executable_basename(
                resolved.name,
                probe.executable,
                active_aliases,
            ):
                raise IntakeError(
                    "unsafe-discovery-result",
                    "executable lookup returned an unsafe result",
                )
            safe_path = _safe_executable_path(resolved)
            if not _allowed_executable_basename(
                safe_path.resolve().name,
                probe.executable,
                active_aliases,
            ):
                raise IntakeError(
                    "unsafe-discovery-result",
                    "executable lookup returned an unsafe result",
                )
            located_candidates.append((safe_path, resolved.name.casefold()))
        if located_candidates:
            selected_path, selected_name = located_candidates[0]
            # Comparing each candidate with the first is sufficient because file identity is
            # transitive; if every candidate is the first inode, they are all the same inode.
            for candidate_path, _ in located_candidates[1:]:
                try:
                    same_identity = os.path.samefile(selected_path, candidate_path)
                except OSError:
                    raise IntakeError(
                        "unsafe-discovery-result",
                        "executable lookup returned an unsafe result",
                    ) from None
                if not same_identity:
                    raise IntakeError(
                        "ambiguous-provider-executable",
                        "multiple allowlisted provider executables resolved to different files",
                    )
            return selected_path, "current-path", selected_name
        return None, "current-path", probe.executable

    requested = request.executable
    requested_path = Path(requested)
    if not _allowed_executable_basename(
        requested_path.name,
        probe.executable,
        active_aliases,
    ):
        raise IntakeError(
            "executable-not-allowed",
            "discovery executable is outside the profile allowlist",
        )
    if requested_path.name != requested:
        if not requested_path.is_absolute():
            raise IntakeError(
                "executable-not-allowed",
                "discovery paths must be absolute and exactly scoped",
            )
        if not requested_path.is_file() or not os.access(requested_path, os.X_OK):
            return None, "exact-path", requested_path.name.casefold()
        safe_path = _safe_executable_path(requested_path)
        if not _allowed_executable_basename(
            safe_path.resolve().name,
            probe.executable,
            active_aliases,
        ):
            raise IntakeError(
                "executable-not-allowed",
                "discovery executable is outside the profile allowlist",
            )
        return safe_path, "exact-path", safe_path.name.casefold()
    located = shutil.which(requested)
    if located is None:
        return None, "current-path", requested_path.name.casefold()
    resolved = Path(located)
    if not resolved.is_absolute() or not _allowed_executable_basename(
        resolved.name,
        probe.executable,
        active_aliases,
    ):
        raise IntakeError(
            "unsafe-discovery-result",
            "executable lookup returned an unsafe result",
        )
    safe_path = _safe_executable_path(resolved)
    if not _allowed_executable_basename(
        safe_path.resolve().name,
        probe.executable,
        active_aliases,
    ):
        raise IntakeError(
            "unsafe-discovery-result",
            "executable lookup returned an unsafe result",
        )
    return safe_path, "current-path", resolved.name.casefold()


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            if process.poll() is None:
                process.kill()
    elif os.name == "nt":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(32_768)
            length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
            system_directory = Path(buffer.value) if 0 < length < len(buffer) else None
        except (AttributeError, OSError, ValueError):
            system_directory = None
        taskkill = system_directory / "taskkill.exe" if system_directory is not None else None
        if taskkill is not None and taskkill.is_file():
            try:
                subprocess.run(  # noqa: S603 - resolved from the Windows system directory
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            process.kill()
    elif process.poll() is None:  # pragma: no cover - unsupported platform fallback
        process.kill()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _probe_version(path: Path, probe: ExecutableProbe) -> str:
    if not probe.version_args:
        raise IntakeError(
            "version-probe-unavailable",
            "this resource profile has no fixed version command",
        )
    try:
        process = subprocess.Popen(  # noqa: S603 - exact path and args are allowlisted.
            [str(path), *probe.version_args],
            cwd=str(path.parent),
            env={
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": str(path.parent) + os.pathsep + os.defpath,
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            start_new_session=os.name == "posix",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    except OSError:
        raise IntakeError("version-probe-failed", "version probe could not be started") from None
    if process.stdout is None:  # pragma: no cover - Popen contract
        _stop_process(process)
        raise IntakeError("version-probe-failed", "version probe output was unavailable")

    deadline = time.monotonic() + _VERSION_TIMEOUT_SECONDS
    if os.name == "posix":
        captured = bytearray()
        file_descriptor = process.stdout.fileno()
        os.set_blocking(file_descriptor, False)
        reached_eof = False
        error: IntakeError | None = None
        while True:
            try:
                chunk = os.read(file_descriptor, 1_024)
            except BlockingIOError:
                chunk = None
            except OSError:
                error = IntakeError(
                    "version-probe-failed", "version probe output could not be read"
                )
                break
            if chunk == b"":
                reached_eof = True
            elif chunk:
                if len(captured) + len(chunk) > _VERSION_OUTPUT_LIMIT:
                    error = IntakeError(
                        "version-output-too-large",
                        "version probe output exceeded its byte limit",
                    )
                    break
                captured.extend(chunk)
            return_code = process.poll()
            if return_code is not None and reached_eof:
                break
            if time.monotonic() >= deadline:
                error = IntakeError(
                    "version-probe-timeout", "version probe exceeded its time limit"
                )
                break
            time.sleep(0.01)
        _stop_process(process)
        process.stdout.close()
        if error is not None:
            raise error
        raw = bytes(captured)
    else:
        captured = bytearray()
        overflow = threading.Event()
        failures: list[OSError | ValueError] = []

        def drain() -> None:
            try:
                while True:
                    chunk = process.stdout.read(1_024)
                    if not chunk:
                        return
                    if len(captured) + len(chunk) > _VERSION_OUTPUT_LIMIT:
                        overflow.set()
                        return
                    captured.extend(chunk)
            except (OSError, ValueError) as error:
                failures.append(error)

        reader = threading.Thread(target=drain, name="atready-version-probe", daemon=True)
        reader.start()
        timed_out = False
        while process.poll() is None and not overflow.is_set() and not failures:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            overflow.wait(min(0.01, remaining))
        return_code = process.poll()
        _stop_process(process)
        reader.join(1.0)
        if overflow.is_set():
            raise IntakeError(
                "version-output-too-large",
                "version probe output exceeded its byte limit",
            )
        if timed_out or reader.is_alive() or return_code is None:
            raise IntakeError("version-probe-timeout", "version probe exceeded its time limit")
        if failures:
            raise IntakeError("version-probe-failed", "version probe output could not be read")
        process.stdout.close()
        raw = bytes(captured)
    if return_code != 0:
        raise IntakeError("version-probe-failed", "version probe did not complete successfully")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise IntakeError(
            "malformed-version-output",
            "version probe output was not valid UTF-8",
        ) from None
    lines = [line.strip() for line in decoded.splitlines() if line.strip()]
    if (
        not lines
        or len(lines[0]) > 240
        or any(unicode_category(character) in {"Cc", "Cf"} for character in lines[0])
    ):
        raise IntakeError("malformed-version-output", "version probe output was not safe text")
    return lines[0]


def discover_local_resource(request: LocalDiscoveryRequest) -> LocalDiscoveryResult:
    """Locate one allowlisted executable and optionally run its fixed version command."""

    profile = resource_profile(request.profile)
    probe = profile.executable_probe
    path, search_scope, executable_name = _resolve_executable(request, profile)
    if path is None:
        return LocalDiscoveryResult(
            profile_id=profile.id,
            executable_name=executable_name,
            search_scope=search_scope,
            installed=False,
            version_probe_performed=False,
            evidence=("executable-not-located",),
        )
    evidence: tuple[
        Literal["executable-located", "executable-not-located", "version-observed"], ...
    ] = ("executable-located",)
    version = None
    if request.probe_version:
        assert probe is not None
        version = _probe_version(path, probe)
        evidence = ("executable-located", "version-observed")
    return LocalDiscoveryResult(
        profile_id=profile.id,
        executable_name=executable_name,
        search_scope=search_scope,
        installed=True,
        resolved_path=str(path),
        version_probe_performed=request.probe_version,
        version=version,
        evidence=evidence,
        external_process_executed=request.probe_version,
        external_process_side_effects=(
            "not-evaluated" if request.probe_version else "not-applicable"
        ),
    )
