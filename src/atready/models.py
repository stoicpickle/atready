"""Versioned public data contracts for AtReady inventories."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from math import isfinite
from typing import Annotated, Literal
from unicodedata import category as unicode_category

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    field_validator,
    model_validator,
)

Slug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
RevisionPrivacyNonce = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^nonce-v1:[0-9a-f]{64}$"),
]


def _require_native_number(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a native YAML/JSON number")
    return value


def _require_native_integer(value: object) -> object:
    if type(value) is not int:
        raise ValueError("value must be a native YAML/JSON integer")
    return value


def _require_capacity_range(value: int | float) -> int | float:
    if value < 0 or value > 1e18 or (isinstance(value, float) and not isfinite(value)):
        raise ValueError("capacity value must be finite and between zero and 1e18")
    return value


def _require_positive_capacity_range(value: int | float) -> int | float:
    _require_capacity_range(value)
    if value == 0:
        raise ValueError("capacity demand must be greater than zero")
    return value


def _require_basis_point_weight(value: float) -> float:
    if value != 0.0 and value < 0.0001:
        raise ValueError("value must be zero or at least one basis point")
    return value


Score = Annotated[
    float,
    BeforeValidator(_require_native_number),
    Field(ge=0.0, le=1.0),
]
CapacityNumber = Annotated[
    int | float,
    BeforeValidator(_require_native_number),
    AfterValidator(_require_capacity_range),
    WithJsonSchema({"type": "number", "minimum": 0, "maximum": 1e18}),
]
CapacityDemandNumber = Annotated[
    int | float,
    BeforeValidator(_require_native_number),
    AfterValidator(_require_positive_capacity_range),
    WithJsonSchema({"type": "number", "exclusiveMinimum": 0, "maximum": 1e18}),
]
BasisPointWeight = Annotated[
    float,
    BeforeValidator(_require_native_number),
    Field(ge=0.0, le=1.0),
    AfterValidator(_require_basis_point_weight),
]
PositiveWeight = Annotated[
    float,
    BeforeValidator(_require_native_number),
    Field(ge=0.0001, le=1.0),
]
SchemaVersion = Annotated[
    Literal[1],
    BeforeValidator(_require_native_integer),
]
SupportingResourceLimit = Annotated[
    Literal[0, 1],
    BeforeValidator(_require_native_integer),
]
StrictBoolean = Annotated[bool, Field(strict=True)]
StaleAfterDays = Annotated[
    int,
    BeforeValidator(_require_native_integer),
    Field(ge=1, le=3_650),
]


def _reject_display_controls(value: str) -> str:
    if any(unicode_category(character) in {"Cc", "Cf"} for character in value):
        raise ValueError("text must not contain control or format characters")
    return value


def _reject_prose_controls(value: str) -> str:
    if any(
        unicode_category(character) in {"Cc", "Cf"} and character not in {"\n", "\t"}
        for character in value
    ):
        raise ValueError("text must not contain unsafe control or format characters")
    return value


ResourceName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    AfterValidator(_reject_display_controls),
]
OptionalProseText = Annotated[
    str,
    StringConstraints(max_length=2_000),
    AfterValidator(_reject_prose_controls),
]
ResourceAdvisoryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
    AfterValidator(_reject_display_controls),
]


class StrictModel(BaseModel):
    """Reject unknown fields so typos cannot silently alter routing."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        hide_input_in_errors=True,
        validate_assignment=True,
    )


class AccessStatus(StrEnum):
    ACTIVE = "active"
    LIMITED = "limited"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class SessionAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class InteractionMode(StrEnum):
    CODEX_CALLABLE = "codex-callable"
    LOCAL_CLI = "local-cli"
    EXTERNAL_AGENT = "external-agent"
    MANUAL = "manual"


class BillingModel(StrEnum):
    FREE = "free"
    OWNED = "owned"
    SUBSCRIPTION = "subscription"
    USAGE = "usage"
    UNKNOWN = "unknown"


class QuotaStatus(StrEnum):
    AMPLE = "ample"
    LIMITED = "limited"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class DataClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SENSITIVE = "sensitive"


class ConfidenceBasis(StrEnum):
    OBSERVED = "observed"
    USER_JUDGMENT = "user-judgment"
    VENDOR_CLAIM = "vendor-claim"
    UNKNOWN = "unknown"


class HandoffMethod(StrEnum):
    DIRECT = "direct"
    MANUAL_PROMPT = "manual-prompt"
    INTERACTIVE = "interactive"
    FILE_EXPORT = "file-export"


class InventoryKind(StrEnum):
    PERSONAL = "personal"
    DEMO = "demo"


class Access(StrictModel):
    status: AccessStatus = AccessStatus.UNKNOWN
    interaction: InteractionMode = InteractionMode.MANUAL
    current_session: SessionAvailability = SessionAvailability.UNKNOWN


class Capacity(StrictModel):
    """One exact, unit-scoped capacity declaration without implicit conversion."""

    unit: Slug
    remaining: CapacityNumber
    limit: CapacityNumber | None = None
    project_limit: CapacityNumber | None = None
    resets_on: date | None = None
    basis: ConfidenceBasis
    last_verified: date

    @field_validator("remaining", "limit", "project_limit")
    @classmethod
    def canonicalize_numeric_zero(cls, value: int | float | None) -> int | float | None:
        if value == 0:
            return 0
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    @model_validator(mode="after")
    def validate_exact_capacity(self) -> Capacity:
        if self.basis is ConfidenceBasis.UNKNOWN:
            raise ValueError("exact capacity requires a non-unknown basis")
        if self.last_verified > date.today():
            raise ValueError("capacity last_verified cannot be in the future")
        if self.resets_on is not None and self.resets_on < self.last_verified:
            raise ValueError("capacity resets_on cannot be earlier than last_verified")
        if self.limit is not None and self.limit == 0:
            raise ValueError("capacity limit must be greater than zero")
        if self.limit is not None and self.remaining > self.limit:
            raise ValueError("capacity remaining cannot exceed limit")
        if self.project_limit is not None and self.project_limit > self.remaining:
            raise ValueError("capacity project_limit cannot exceed remaining")
        return self


class CapacityDemand(StrictModel):
    """One exact, unit-scoped amount a workstream expects to need."""

    unit: Slug
    amount: CapacityDemandNumber

    @field_validator("amount")
    @classmethod
    def canonicalize_numeric_value(cls, value: int | float) -> int | float:
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value


class Economics(StrictModel):
    billing: BillingModel = BillingModel.UNKNOWN
    marginal_cost: Score = 0.5
    quota: QuotaStatus = QuotaStatus.UNKNOWN
    capacity: Capacity | None = None

    @model_validator(mode="after")
    def require_consistent_capacity_and_quota(self) -> Economics:
        if self.capacity is None:
            return self
        if self.capacity.remaining == 0 and self.quota is not QuotaStatus.EXHAUSTED:
            raise ValueError("zero remaining capacity requires quota exhausted")
        if self.capacity.remaining > 0 and self.quota is QuotaStatus.EXHAUSTED:
            raise ValueError("quota exhausted cannot have positive remaining capacity")
        return self


class Ratings(StrictModel):
    quality: Score = 0.5
    speed: Score = 0.5
    autonomy: Score = 0.5
    privacy: Score = 0.5
    reliability: Score = 0.5
    confidence: Score = 0.5
    context_switch_cost: Score = 0.5
    integration_friction: Score = 0.5


class Policy(StrictModel):
    allowed_data_classes: list[DataClass] = Field(default_factory=lambda: [DataClass.PUBLIC])
    approval_required: StrictBoolean = True
    requires_network: StrictBoolean = False

    @model_validator(mode="after")
    def require_data_class(self) -> Policy:
        if not self.allowed_data_classes:
            raise ValueError("allowed_data_classes must contain at least one value")
        if len(self.allowed_data_classes) != len(set(self.allowed_data_classes)):
            raise ValueError("allowed_data_classes must not contain duplicates")
        return self


class Provenance(StrictModel):
    basis: ConfidenceBasis = ConfidenceBasis.UNKNOWN
    last_verified: date | None = None

    @model_validator(mode="after")
    def reject_future_verification(self) -> Provenance:
        if self.last_verified and self.last_verified > date.today():
            raise ValueError("last_verified cannot be in the future")
        return self


class Handoff(StrictModel):
    method: HandoffMethod = HandoffMethod.MANUAL_PROMPT
    instructions: OptionalProseText | None = None


class Resource(StrictModel):
    id: Slug
    name: ResourceName
    categories: list[Slug] = Field(min_length=1, max_length=20)
    capabilities: dict[Slug, Score] = Field(min_length=1, max_length=100)
    access: Access = Field(default_factory=Access)
    economics: Economics = Field(default_factory=Economics)
    ratings: Ratings = Field(default_factory=Ratings)
    policy: Policy = Field(default_factory=Policy)
    provenance: Provenance = Field(default_factory=Provenance)
    handoff: Handoff = Field(default_factory=Handoff)
    best_for: list[ResourceAdvisoryText] = Field(default_factory=list, max_length=30)
    avoid_for: list[ResourceAdvisoryText] = Field(default_factory=list, max_length=30)
    private_notes: str | None = Field(
        default=None,
        max_length=10_000,
        repr=False,
        description=(
            "Inert local annotation omitted from routing, snapshots, previews, and packets; "
            "never store credentials here."
        ),
    )

    @field_validator("capabilities", mode="before")
    @classmethod
    def reject_normalized_capability_collisions(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        normalized: set[str] = set()
        for key in value:
            if not isinstance(key, str):
                continue
            candidate = key.strip()
            if candidate in normalized:
                raise ValueError("capability ids must remain unique after normalization")
            normalized.add(candidate)
        return value

    @model_validator(mode="after")
    def normalize_and_validate_lists(self) -> Resource:
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("categories must not contain duplicates")
        if len(self.best_for) != len(set(self.best_for)):
            raise ValueError("best_for must not contain duplicates")
        if len(self.avoid_for) != len(set(self.avoid_for)):
            raise ValueError("avoid_for must not contain duplicates")
        if self.access.status in {AccessStatus.ACTIVE, AccessStatus.LIMITED}:
            if self.provenance.last_verified is None:
                raise ValueError("active or limited resources require provenance.last_verified")
        return self


class ResourceDeclaration(StrictModel):
    """One versioned resource payload for argv-safe inventory onboarding."""

    schema_version: SchemaVersion
    resource: Resource


class InventoryAnnotationDeclaration(StrictModel):
    """One versioned root annotation payload for protected inventory onboarding."""

    schema_version: SchemaVersion
    private_notes: Annotated[
        str,
        StringConstraints(strict=True, max_length=20_000),
    ] = Field(repr=False)


class RoutingWeights(StrictModel):
    capability_fit: BasisPointWeight = 1.0
    quality: BasisPointWeight = 0.7
    cost_efficiency: BasisPointWeight = 0.4
    speed: BasisPointWeight = 0.4
    autonomy: BasisPointWeight = 0.3
    privacy: BasisPointWeight = 0.6
    reliability: BasisPointWeight = 0.6
    confidence: BasisPointWeight = 0.5
    low_context_switching: BasisPointWeight = 0.4
    low_integration_friction: BasisPointWeight = 0.4

    @model_validator(mode="after")
    def require_weight(self) -> RoutingWeights:
        if not any(value > 0 for value in self.model_dump().values()):
            raise ValueError("at least one routing weight must be greater than zero")
        return self


class Preferences(StrictModel):
    weights: RoutingWeights = Field(default_factory=RoutingWeights)
    maximum_supporting_resources: SupportingResourceLimit = 1
    stale_after_days: StaleAfterDays = 90
    allow_purchase_suggestions: StrictBoolean = False


class Inventory(StrictModel):
    schema_version: SchemaVersion = 1
    inventory_kind: InventoryKind
    revision_privacy_nonce: RevisionPrivacyNonce | None = Field(default=None, repr=False)
    preferences: Preferences = Field(default_factory=Preferences)
    resources: list[Resource] = Field(default_factory=list, max_length=500)
    private_notes: str | None = Field(
        default=None,
        max_length=20_000,
        repr=False,
        description=(
            "Inert inventory annotation omitted from routing and snapshots; never store "
            "credentials here."
        ),
    )

    @model_validator(mode="after")
    def require_unique_resource_ids(self) -> Inventory:
        ids = [resource.id for resource in self.resources]
        duplicates = sorted({resource_id for resource_id in ids if ids.count(resource_id) > 1})
        if duplicates:
            raise ValueError("resource ids must be unique")
        notes_present = self.private_notes is not None or any(
            resource.private_notes is not None for resource in self.resources
        )
        if notes_present and self.revision_privacy_nonce is None:
            raise ValueError(
                "legacy-unblinded inventories cannot contain private notes; do not add a nonce "
                "manually; preserve this file and use atready init with a new path"
            )
        return self

    def revision_protection(self) -> Literal["nonce-v1-present", "legacy-unblinded"]:
        """Return a value-free state; nonce entropy and provenance remain unverified."""

        return "nonce-v1-present" if self.revision_privacy_nonce is not None else "legacy-unblinded"


class CapabilityRequirement(StrictModel):
    id: Slug
    importance: PositiveWeight = 1.0
    minimum: Score = 0.25


class ProjectConstraints(StrictModel):
    data_class: DataClass = DataClass.PUBLIC
    max_marginal_cost: Score = 1.0
    allowed_interactions: list[InteractionMode] = Field(
        default_factory=lambda: list(InteractionMode)
    )
    network_allowed: StrictBoolean = True
    allow_unverified: StrictBoolean = False
    forbidden_resources: list[Slug] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_unique_constraints(self) -> ProjectConstraints:
        if not self.allowed_interactions:
            raise ValueError("allowed_interactions must contain at least one value")
        if len(self.allowed_interactions) != len(set(self.allowed_interactions)):
            raise ValueError("allowed_interactions must not contain duplicates")
        if len(self.forbidden_resources) != len(set(self.forbidden_resources)):
            raise ValueError("forbidden_resources must not contain duplicates")
        return self


class SupportPolicy(StrictModel):
    allowed: StrictBoolean = False
    capability_gaps: list[Slug] = Field(default_factory=list)
    minimum_gain: BasisPointWeight = 0.08

    @model_validator(mode="after")
    def require_named_gap(self) -> SupportPolicy:
        if self.allowed and not self.capability_gaps:
            raise ValueError("support requires at least one named capability_gaps entry")
        if not self.allowed and self.capability_gaps:
            raise ValueError("capability_gaps require support.allowed: true")
        if len(self.capability_gaps) != len(set(self.capability_gaps)):
            raise ValueError("capability_gaps must not contain duplicates")
        return self


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
    AfterValidator(_reject_prose_controls),
]


class Workstream(StrictModel):
    id: Slug
    name: ResourceName
    objective: NonEmptyText
    required_capabilities: list[CapabilityRequirement] = Field(min_length=1, max_length=30)
    inputs: list[NonEmptyText] = Field(min_length=1, max_length=30)
    allowed_scope: list[NonEmptyText] = Field(min_length=1, max_length=30)
    exclusions: list[NonEmptyText] = Field(min_length=1, max_length=30)
    deliverable: NonEmptyText
    acceptance_criteria: list[NonEmptyText] = Field(min_length=1, max_length=50)
    verification: list[NonEmptyText] = Field(min_length=1, max_length=30)
    stop_conditions: list[NonEmptyText] = Field(min_length=1, max_length=20)
    next_owner: NonEmptyText
    capacity_demand: CapacityDemand | None = None
    support: SupportPolicy = Field(default_factory=SupportPolicy)
    alternate_required: StrictBoolean = False

    @model_validator(mode="after")
    def require_unique_capabilities(self) -> Workstream:
        ids = [requirement.id for requirement in self.required_capabilities]
        if len(ids) != len(set(ids)):
            raise ValueError("required_capabilities ids must not contain duplicates")
        known_ids = set(ids)
        unknown_gaps = sorted(set(self.support.capability_gaps) - known_ids)
        if unknown_gaps:
            raise ValueError("support capability_gaps must be required capabilities")
        return self


class ProjectBrief(StrictModel):
    schema_version: SchemaVersion = 1
    id: Slug
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
        AfterValidator(_reject_display_controls),
    ]
    goal: NonEmptyText
    as_of: date
    constraints: ProjectConstraints = Field(default_factory=ProjectConstraints)
    workstreams: list[Workstream] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_unique_workstream_ids(self) -> ProjectBrief:
        ids = [workstream.id for workstream in self.workstreams]
        if len(ids) != len(set(ids)):
            raise ValueError("workstream ids must not contain duplicates")
        return self


class ScoreAdjustment(StrictModel):
    code: Slug
    basis_points: int


class CandidateEvaluation(StrictModel):
    role: Literal["primary", "support", "alternate"]
    resource_id: Slug
    resource_name: str
    eligible_for_role: bool
    gate_codes: list[Slug] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    components_bp: dict[Slug, int] = Field(default_factory=dict)
    base_score_bp: int | None = None
    adjustments: list[ScoreAdjustment] = Field(default_factory=list)
    adjusted_score_bp: int | None = None
    combined_fit_bp: int | None = None
    fit_gain_bp: int | None = None
    covered_capability_gaps: list[Slug] = Field(default_factory=list)


class ResourceSelection(StrictModel):
    resource_id: Slug
    resource_name: str
    score_bp: int
    reason: NonEmptyText


class HandoffPacket(StrictModel):
    role: Literal["primary", "support", "alternate"]
    activation_condition: NonEmptyText
    owner_resource_id: Slug
    owner_resource_name: str
    handoff_method: HandoffMethod
    handoff_instructions: OptionalProseText | None = None
    declared_resource_approval_required: StrictBoolean
    objective: NonEmptyText
    inputs: list[NonEmptyText]
    allowed_scope: list[NonEmptyText]
    exclusions: list[NonEmptyText]
    deliverable: NonEmptyText
    acceptance_criteria: list[NonEmptyText]
    verification: list[NonEmptyText]
    stop_conditions: list[NonEmptyText]
    next_owner: NonEmptyText


class UnresolvedRouteGap(StrictModel):
    code: Slug
    reason: NonEmptyText


class RouteAssignment(StrictModel):
    workstream_id: Slug
    workstream_name: str
    primary: ResourceSelection | None = None
    support: ResourceSelection | None = None
    support_gap: list[Slug] = Field(default_factory=list)
    alternate: ResourceSelection | None = None
    alternate_activation_condition: NonEmptyText | None = None
    gap_reason: str | None = None
    unresolved_gaps: list[UnresolvedRouteGap] = Field(default_factory=list)
    handoffs: list[HandoffPacket] = Field(default_factory=list)
    candidates: list[CandidateEvaluation]
    support_evaluation: CandidateEvaluation | None = None
    alternate_evaluation: CandidateEvaluation | None = None

    @model_validator(mode="after")
    def require_primary_or_gap(self) -> RouteAssignment:
        candidate_ids = [evaluation.resource_id for evaluation in self.candidates]
        if any(evaluation.role != "primary" for evaluation in self.candidates):
            raise ValueError("candidates must contain only primary-role evaluations")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidates require exactly one primary evaluation per resource")
        if (self.primary is None) == (self.gap_reason is None):
            raise ValueError("assignment requires exactly one of primary or gap_reason")
        if self.primary is None and any((self.support, self.alternate, self.handoffs)):
            raise ValueError("gap assignments cannot include support, alternate, or handoffs")
        if self.primary is not None:
            expected_roles = {"primary": self.primary.resource_id}
            if self.support:
                expected_roles["support"] = self.support.resource_id
            if self.alternate:
                expected_roles["alternate"] = self.alternate.resource_id
            actual_roles = {packet.role: packet.owner_resource_id for packet in self.handoffs}
            if len(actual_roles) != len(self.handoffs) or actual_roles != expected_roles:
                raise ValueError("assigned roles require exactly one matching handoff packet")
            if len(set(expected_roles.values())) != len(expected_roles):
                raise ValueError("assigned roles must use distinct resources")
            primary_evaluations = [
                evaluation
                for evaluation in self.candidates
                if evaluation.role == "primary"
                and evaluation.resource_id == self.primary.resource_id
                and evaluation.resource_name == self.primary.resource_name
                and evaluation.eligible_for_role
                and evaluation.adjusted_score_bp == self.primary.score_bp
            ]
            if len(primary_evaluations) != 1:
                raise ValueError("selected primary requires one matching eligible evaluation")
        if self.support is None and self.support_gap:
            raise ValueError("support_gap requires a selected support resource")
        if self.support is not None and not self.support_gap:
            raise ValueError("selected support requires at least one support_gap")
        if (self.support is None) != (self.support_evaluation is None):
            raise ValueError("selected support requires exactly one support_evaluation")
        if self.support is not None and self.support_evaluation is not None:
            evaluation = self.support_evaluation
            candidate_matches = [
                candidate
                for candidate in self.candidates
                if candidate.resource_id == self.support.resource_id
                and candidate.resource_name == self.support.resource_name
            ]
            if (
                evaluation.role != "support"
                or not evaluation.eligible_for_role
                or evaluation.resource_id != self.support.resource_id
                or evaluation.resource_name != self.support.resource_name
                or evaluation.adjusted_score_bp != self.support.score_bp
                or evaluation.covered_capability_gaps != self.support_gap
                or evaluation.combined_fit_bp is None
                or evaluation.fit_gain_bp is None
                or len(candidate_matches) != 1
            ):
                raise ValueError("selected support requires one matching eligible evaluation")
        if self.alternate is None and self.alternate_activation_condition is not None:
            raise ValueError("alternate_activation_condition requires a selected alternate")
        if self.alternate is not None and not self.alternate_activation_condition:
            raise ValueError("selected alternate requires an activation condition")
        if (self.alternate is None) != (self.alternate_evaluation is None):
            raise ValueError("selected alternate requires exactly one alternate_evaluation")
        if self.alternate is not None and self.alternate_evaluation is not None:
            evaluation = self.alternate_evaluation
            candidate_matches = [
                candidate
                for candidate in self.candidates
                if candidate.resource_id == self.alternate.resource_id
                and candidate.resource_name == self.alternate.resource_name
            ]
            alternate_handoff = next(
                (packet for packet in self.handoffs if packet.role == "alternate"),
                None,
            )
            if (
                evaluation.role != "alternate"
                or not evaluation.eligible_for_role
                or evaluation.resource_id != self.alternate.resource_id
                or evaluation.resource_name != self.alternate.resource_name
                or evaluation.adjusted_score_bp != self.alternate.score_bp
                or len(candidate_matches) != 1
            ):
                raise ValueError("selected alternate requires one matching eligible evaluation")
            if (
                alternate_handoff is None
                or alternate_handoff.activation_condition != self.alternate_activation_condition
            ):
                raise ValueError(
                    "selected alternate handoff requires the assignment activation condition"
                )
        gap_codes = [gap.code for gap in self.unresolved_gaps]
        if len(gap_codes) != len(set(gap_codes)):
            raise ValueError("unresolved gap codes must not contain duplicates")
        return self


class DispositionStatus(StrEnum):
    SELECTED_PRIMARY = "selected-primary"
    SELECTED_SUPPORT = "selected-support"
    RESERVED_ALTERNATE = "reserved-alternate"
    DELIBERATELY_UNUSED = "deliberately-unused"
    UNAVAILABLE = "unavailable"
    INELIGIBLE = "ineligible"
    UNVERIFIED = "unverified"


class ResourceDisposition(StrictModel):
    resource_id: Slug
    resource_name: str
    status: DispositionStatus
    reason_code: Slug
    reason: NonEmptyText
    workstreams: list[Slug] = Field(default_factory=list)


class RoutePlan(StrictModel):
    schema_version: SchemaVersion = 1
    plan_id: Slug
    project_id: Slug
    project_name: str
    as_of: date
    inventory_fingerprint: str
    assignments: list[RouteAssignment]
    dispositions: list[ResourceDisposition]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_complete_plan(self) -> RoutePlan:
        resource_ids = [item.resource_id for item in self.dispositions]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("each resource must have exactly one disposition")
        workstream_ids = [item.workstream_id for item in self.assignments]
        if len(workstream_ids) != len(set(workstream_ids)):
            raise ValueError("each workstream must have exactly one assignment")
        return self
