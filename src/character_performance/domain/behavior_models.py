from __future__ import annotations

from hashlib import sha256
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from .models import (
    Cognition,
    Context,
    Director,
    DomainModel,
    EmotionState,
    Event,
    NonEmptyId,
    NonNegativeInt,
    PhysicalState,
    RelationshipState,
    SceneState,
    UnitFloat,
    WorldState,
    CharacterProfile,
)


SCHEMA_VERSION = "1.0.0"
SchemaVersion = Literal["1.0.0"]
PositiveRevision = Annotated[int, Field(ge=1)]
ContentHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
NonEmptyText = Annotated[str, Field(min_length=1)]


def content_hash(text: str) -> str:
    """Return the canonical UTF-8 content hash used by audit and commit models."""
    return f"sha256:{sha256(text.encode('utf-8')).hexdigest()}"


def _validate_span(span: "TextSpan", source: str, *, field: str) -> None:
    if span.end > len(source) or source[span.start : span.end] != span.text:
        raise ValueError(f"{field} must point to the exact source text")


class NarrativePosition(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    book_id: NonEmptyId
    volume_id: NonEmptyId | None = None
    chapter_id: NonEmptyId
    scene_id: NonEmptyId
    paragraph_index: NonNegativeInt
    beat_index: NonNegativeInt
    global_beat_index: NonNegativeInt
    timeline_ms: NonNegativeInt | None = None

    @model_validator(mode="after")
    def hierarchy_is_consistent(self) -> "NarrativePosition":
        if self.volume_id == self.book_id:
            raise ValueError("volume_id must differ from book_id")
        if len({self.book_id, self.chapter_id, self.scene_id}) != 3:
            raise ValueError("book_id, chapter_id and scene_id must identify distinct levels")
        return self


class SignatureFamily(DomainModel):
    semantic_group: NonEmptyId
    affinity: UnitFloat
    cooldown_chapters: NonNegativeInt
    maximum_per_volume: Annotated[int, Field(ge=1)]


class RelationshipStrategyOverride(DomainModel):
    preferred_strategies: tuple[NonEmptyId, ...] = ()
    forbidden_strategies: frozenset[NonEmptyId] = frozenset()
    preferred_channels: tuple[NonEmptyId, ...] = ()
    avoided_channels: frozenset[NonEmptyId] = frozenset()
    allowed_exceptions: frozenset[NonEmptyId] = frozenset()

    @model_validator(mode="after")
    def preferences_do_not_conflict(self) -> "RelationshipStrategyOverride":
        if set(self.preferred_strategies) & self.forbidden_strategies:
            raise ValueError("a relationship strategy cannot be preferred and forbidden")
        if set(self.preferred_channels) & self.avoided_channels:
            raise ValueError("a relationship channel cannot be preferred and avoided")
        return self


class ArcState(DomainModel):
    id: NonEmptyId
    openness_delta: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    allowed_exceptions: frozenset[NonEmptyId] = frozenset()


class BehaviorIdentity(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    character_id: NonEmptyId
    version: PositiveRevision
    default_strategies: dict[NonEmptyId, NonEmptyId]
    preferred_channels: dict[NonEmptyId, UnitFloat]
    avoided_channels: dict[NonEmptyId, UnitFloat] = Field(default_factory=dict)
    values: frozenset[NonEmptyId]
    taboos: frozenset[NonEmptyId]
    coping_strategies: frozenset[NonEmptyId]
    social_masks: dict[Literal["public", "private", "intimate"], NonEmptyId]
    signature_families: tuple[SignatureFamily, ...] = ()
    relationship_overrides: dict[NonEmptyId, RelationshipStrategyOverride] = Field(
        default_factory=dict
    )
    arc_state: ArcState | None = None

    @model_validator(mode="after")
    def identity_is_coherent(self) -> "BehaviorIdentity":
        if not self.default_strategies:
            raise ValueError("default_strategies must not be empty")
        if not self.preferred_channels:
            raise ValueError("preferred_channels must not be empty")
        if not self.values:
            raise ValueError("values must not be empty")
        if set(self.preferred_channels) & set(self.avoided_channels):
            raise ValueError("a channel cannot be preferred and avoided")
        groups = [item.semantic_group for item in self.signature_families]
        if len(groups) != len(set(groups)):
            raise ValueError("signature_families must use unique semantic_group values")
        if self.character_id in self.relationship_overrides:
            raise ValueError("relationship_overrides cannot target the identity character")
        return self


# The implementation specification uses both names. Keep one canonical schema/model.
CharacterBehaviorIdentity = BehaviorIdentity


class ReactionStrategyPlan(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    strategy_id: NonEmptyId
    intent: NonEmptyId
    surface_goal: NonEmptyId
    private_goal: NonEmptyId
    applicability_conditions: frozenset[NonEmptyId]
    contraindications: frozenset[NonEmptyId]
    preferred_channels: tuple[NonEmptyId, ...]
    suppressed_channels: frozenset[NonEmptyId] = frozenset()
    allowed_visibility: Literal[
        "hidden", "very_subtle", "subtle", "noticeable", "obvious", "unknown"
    ]
    action_budget: Annotated[int, Field(ge=0, le=6)]
    omit_action_allowed: bool
    relationship_meaning: NonEmptyId
    reasons: tuple[NonEmptyId, ...]
    secondary_strategy_id: NonEmptyId | None = None

    @model_validator(mode="after")
    def plan_is_coherent(self) -> "ReactionStrategyPlan":
        if not self.applicability_conditions:
            raise ValueError("applicability_conditions must not be empty")
        if not self.preferred_channels and self.action_budget:
            raise ValueError("a non-zero action_budget requires preferred_channels")
        if set(self.preferred_channels) & self.suppressed_channels:
            raise ValueError("a channel cannot be preferred and suppressed")
        if self.action_budget == 0 and not self.omit_action_allowed:
            raise ValueError("zero action_budget requires omit_action_allowed")
        if not self.reasons:
            raise ValueError("reasons must not be empty")
        if self.secondary_strategy_id == self.strategy_id:
            raise ValueError("secondary_strategy_id must differ from strategy_id")
        return self


class SyntaxFeatures(DomainModel):
    subject_opening: Literal[
        "actor", "body_part", "object", "environment", "dialogue", "other", "unknown"
    ] = "unknown"
    temporal_shape: NonEmptyId = "unknown"
    reset_pattern: bool = False
    dialogue_position: Literal[
        "before_dialogue", "during_dialogue", "after_dialogue", "no_dialogue", "unknown"
    ] = "unknown"


class BehaviorFingerprint(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    unit_id: NonEmptyId | None = None
    semantic_groups: frozenset[NonEmptyId]
    channel: NonEmptyId
    narrative_functions: frozenset[NonEmptyId]
    strategy_id: NonEmptyId | None = None
    actor_id: NonEmptyId
    target_ids: tuple[NonEmptyId, ...] = ()
    visibility: Literal[
        "hidden", "very_subtle", "subtle", "noticeable", "obvious", "unknown"
    ] = "unknown"
    amplitude_band: Literal["none", "low", "medium", "high", "unknown"] = "unknown"
    syntax_features: SyntaxFeatures = SyntaxFeatures()
    lexical_lemmas: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def fingerprint_is_coherent(self) -> "BehaviorFingerprint":
        if not self.semantic_groups:
            raise ValueError("semantic_groups must not be empty")
        if not self.narrative_functions:
            raise ValueError("narrative_functions must not be empty")
        if self.actor_id in self.target_ids:
            raise ValueError("actor_id cannot also be a target_id")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("target_ids must be unique")
        return self


class TextSpan(DomainModel):
    start: NonNegativeInt
    end: Annotated[int, Field(ge=1)]
    text: NonEmptyText

    @model_validator(mode="after")
    def span_length_matches_text(self) -> "TextSpan":
        if self.end <= self.start:
            raise ValueError("text span end must be greater than start")
        if self.end - self.start != len(self.text):
            raise ValueError("text span length must equal the Unicode code point text length")
        return self


class BehaviorOccurrence(DomainModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "source": {"enum": ["extracted", "human_confirmed"]}
                        },
                        "required": ["source"],
                    },
                    "then": {
                        "properties": {
                            "accepted_revision": {"type": "integer", "minimum": 1}
                        },
                        "required": ["accepted_revision"],
                    },
                    "else": {
                        "properties": {"accepted_revision": {"type": "null"}}
                    },
                }
            ]
        },
    )
    schema_version: SchemaVersion = SCHEMA_VERSION
    occurrence_id: NonEmptyId
    book_id: NonEmptyId
    position: NarrativePosition
    actor_id: NonEmptyId
    target_ids: tuple[NonEmptyId, ...] = ()
    fingerprint: BehaviorFingerprint
    source: Literal["planned", "rendered", "extracted", "human_confirmed"]
    text_span: TextSpan
    confidence: UnitFloat
    generation_run_id: NonEmptyId
    accepted_revision: PositiveRevision | None = None

    @model_validator(mode="after")
    def occurrence_is_coherent(self) -> "BehaviorOccurrence":
        if self.book_id != self.position.book_id:
            raise ValueError("book_id must match position.book_id")
        if self.actor_id != self.fingerprint.actor_id:
            raise ValueError("actor_id must match fingerprint.actor_id")
        if self.target_ids != self.fingerprint.target_ids:
            raise ValueError("target_ids must match fingerprint.target_ids")
        if self.source in {"extracted", "human_confirmed"}:
            if self.accepted_revision is None:
                raise ValueError("accepted occurrence requires accepted_revision")
        elif self.accepted_revision is not None:
            raise ValueError("planned or rendered occurrence cannot have accepted_revision")
        return self


class StyleContext(DomainModel):
    pov: Literal["first_person", "third_limited", "third_omniscient", "second_person"]
    prose_style: NonEmptyId
    paragraph_function: NonEmptyId


class GenerationRequest(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    position: NarrativePosition
    character: CharacterProfile
    behavior_identity: BehaviorIdentity
    relationship: RelationshipState | None = None
    event: Event | None = None
    cognition: Cognition | None = None
    emotion_state: EmotionState | None = None
    physical_state: PhysicalState = PhysicalState()
    scene_state: SceneState
    context: Context = Context()
    director: Director = Director()
    world_state: WorldState = WorldState()
    dialogue_or_plot_constraints: tuple[NonEmptyText, ...] = ()
    style_context: StyleContext
    seed: int = 0

    @model_validator(mode="after")
    def request_is_coherent(self) -> "GenerationRequest":
        actor_id = self.character.id
        if self.behavior_identity.character_id != actor_id:
            raise ValueError("behavior_identity.character_id must match character.id")
        for state in (self.relationship, self.cognition):
            if state is not None and state.subject_id != actor_id:
                raise ValueError("relationship/cognition subject_id must match character.id")
        if self.position.scene_id != self.scene_state.scene_id:
            raise ValueError("position.scene_id must match scene_state.scene_id")
        if len(self.dialogue_or_plot_constraints) != len(
            set(self.dialogue_or_plot_constraints)
        ):
            raise ValueError("dialogue_or_plot_constraints must be unique")
        return self


class OverusedBehavior(DomainModel):
    semantic_group: NonEmptyId
    severity: Literal["block", "rewrite", "warning"]
    reason: NonEmptyText


class CandidateBehavior(DomainModel):
    unit_id: NonEmptyId
    purpose: NonEmptyId
    realization_guidance: NonEmptyText
    channel: NonEmptyId | None = None
    semantic_groups: frozenset[NonEmptyId] = frozenset()


class GenerationBrief(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    strategy: ReactionStrategyPlan
    required_facts: frozenset[NonEmptyId] = frozenset()
    forbidden_facts: frozenset[NonEmptyId] = frozenset()
    recently_overused: tuple[OverusedBehavior, ...] = ()
    avoid_syntax: frozenset[NonEmptyId] = frozenset()
    preferred_channels: tuple[NonEmptyId, ...]
    candidate_behaviors: tuple[CandidateBehavior, ...] = ()
    omit_action_allowed: bool
    maximum_visible_signals: Annotated[int, Field(ge=0, le=6)]
    prompt_fragment: NonEmptyText
    memory_revision: NonNegativeInt

    @model_validator(mode="after")
    def brief_is_coherent(self) -> "GenerationBrief":
        if self.required_facts & self.forbidden_facts:
            raise ValueError("facts cannot be both required and forbidden")
        if self.maximum_visible_signals > self.strategy.action_budget:
            raise ValueError("maximum_visible_signals cannot exceed strategy.action_budget")
        if self.omit_action_allowed and not self.strategy.omit_action_allowed:
            raise ValueError("brief cannot allow omission when strategy forbids it")
        preferred = set(self.preferred_channels)
        if not preferred <= set(self.strategy.preferred_channels):
            raise ValueError("brief preferred_channels must come from strategy")
        if preferred & self.strategy.suppressed_channels:
            raise ValueError("brief preferred_channels cannot be suppressed")
        if len(self.candidate_behaviors) > 3:
            raise ValueError("candidate_behaviors cannot contain more than three items")
        if any(
            item.channel is not None and item.channel not in preferred
            for item in self.candidate_behaviors
        ):
            raise ValueError("candidate behavior channel must be preferred")
        blocked_groups = {
            item.semantic_group for item in self.recently_overused if item.severity == "block"
        }
        if any(item.semantic_groups & blocked_groups for item in self.candidate_behaviors):
            raise ValueError("candidate behavior cannot use a blocked semantic group")
        return self


class ExtractionRequest(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    text: NonEmptyText
    known_characters: tuple[CharacterProfile, ...]
    position: NarrativePosition
    scene_facts: frozenset[NonEmptyId] = frozenset()
    candidate_behaviors: tuple[CandidateBehavior, ...] = ()
    pack_summary: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def characters_are_unique(self) -> "ExtractionRequest":
        ids = [item.id for item in self.known_characters]
        if not ids:
            raise ValueError("known_characters must not be empty")
        if len(ids) != len(set(ids)):
            raise ValueError("known_characters must use unique ids")
        return self

    def validate_result(self, result: "ExtractionResult") -> None:
        if result.run_id != self.run_id:
            raise ValueError("result.run_id must match extraction request")
        known_ids = {item.id for item in self.known_characters}
        unknown = {item.actor_id for item in result.behaviors} - known_ids
        if unknown:
            raise ValueError(f"extracted actor_id is not a known character: {sorted(unknown)}")
        for index, behavior in enumerate(result.behaviors):
            _validate_span(
                behavior.text_span, self.text, field=f"behaviors[{index}].text_span"
            )
        for index, span in enumerate(result.unresolved_spans):
            _validate_span(span, self.text, field=f"unresolved_spans[{index}]")


class ExtractedBehavior(DomainModel):
    actor_id: NonEmptyId
    target_ids: tuple[NonEmptyId, ...] = ()
    text_span: TextSpan
    canonical_action: NonEmptyId
    matched_unit_id: NonEmptyId | None = None
    semantic_groups: frozenset[NonEmptyId]
    channel: NonEmptyId
    narrative_functions: frozenset[NonEmptyId]
    strategy_id: NonEmptyId | None = None
    syntax_features: SyntaxFeatures = SyntaxFeatures()
    lexical_lemmas: tuple[NonEmptyText, ...] = ()
    confidence: UnitFloat
    evidence_sources: frozenset[Literal["rule", "llm", "human"]] = frozenset()

    @model_validator(mode="after")
    def extracted_behavior_is_coherent(self) -> "ExtractedBehavior":
        if not self.semantic_groups or not self.narrative_functions:
            raise ValueError("extracted behavior needs semantic groups and narrative functions")
        if self.actor_id in self.target_ids:
            raise ValueError("actor_id cannot also be a target_id")
        return self


class ExtractionResult(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    behaviors: tuple[ExtractedBehavior, ...] = ()
    unresolved_spans: tuple[TextSpan, ...] = ()


class GeneratedDraft(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    text: NonEmptyText
    revision: PositiveRevision = 1


class SourceSpan(DomainModel):
    start: NonNegativeInt
    end: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def is_ordered(self) -> "SourceSpan":
        if self.end <= self.start:
            raise ValueError("source span end must be greater than start")
        return self


class AuditIssue(DomainModel):
    issue_id: NonEmptyId
    severity: Literal["block", "rewrite", "warning"]
    code: NonEmptyId
    spans: tuple[SourceSpan, ...]
    actor_id: NonEmptyId | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    preserve: frozenset[NonEmptyId] = frozenset()
    alternatives: tuple[NonEmptyId, ...] = ()

    @model_validator(mode="after")
    def issue_has_location(self) -> "AuditIssue":
        if not self.spans:
            raise ValueError("audit issue must contain at least one span")
        return self


class AuditMetrics(DomainModel):
    exact_repeat_count: NonNegativeInt = 0
    semantic_repeat_score: UnitFloat = 0.0
    character_fit_score: UnitFloat = 1.0
    syntax_pattern_score: UnitFloat = 0.0


class AuditResult(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    draft_hash: ContentHash
    accepted: bool
    issues: tuple[AuditIssue, ...] = ()
    metrics: AuditMetrics
    memory_revision: NonNegativeInt
    auto_rewrite_allowed: bool = False
    rewrite_attempts: Annotated[int, Field(ge=0, le=2)] = 0

    @model_validator(mode="after")
    def audit_is_coherent(self) -> "AuditResult":
        ids = [item.issue_id for item in self.issues]
        if len(ids) != len(set(ids)):
            raise ValueError("audit issue ids must be unique")
        actionable = any(item.severity in {"block", "rewrite"} for item in self.issues)
        if self.accepted == actionable:
            raise ValueError("accepted must be false exactly when actionable issues exist")
        if self.accepted and self.auto_rewrite_allowed:
            raise ValueError("accepted audit cannot allow auto rewrite")
        if self.rewrite_attempts >= 2 and self.auto_rewrite_allowed:
            raise ValueError("auto rewrite cannot exceed two attempts")
        return self

    def validate_draft(self, draft: GeneratedDraft) -> None:
        if self.draft_hash != content_hash(draft.text):
            raise ValueError("draft_hash must match generated draft text")
        for issue_index, issue in enumerate(self.issues):
            for span_index, span in enumerate(issue.spans):
                if span.end > len(draft.text):
                    raise ValueError(
                        f"issues[{issue_index}].spans[{span_index}] exceeds draft length"
                    )


class RewriteRequest(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    text: NonEmptyText
    audit: AuditResult
    attempt: Annotated[int, Field(ge=1, le=2)]

    @model_validator(mode="after")
    def request_matches_audit(self) -> "RewriteRequest":
        if self.audit.run_id != self.run_id:
            raise ValueError("audit.run_id must match rewrite run_id")
        self.audit.validate_draft(GeneratedDraft(text=self.text))
        if self.audit.accepted:
            raise ValueError("accepted text must not be rewritten")
        if self.attempt != self.audit.rewrite_attempts + 1:
            raise ValueError("attempt must follow audit.rewrite_attempts")
        return self


class TextReplacement(DomainModel):
    text: str


class ChangedSpan(DomainModel):
    original: TextSpan
    replacement: TextReplacement
    resolved_issue_ids: tuple[NonEmptyId, ...]

    @model_validator(mode="after")
    def resolves_at_least_one_issue(self) -> "ChangedSpan":
        if not self.resolved_issue_ids:
            raise ValueError("changed span must resolve at least one issue")
        return self


class PreservationChecks(DomainModel):
    dialogue_hash: ContentHash
    required_facts: bool
    scene_state: bool


class RewriteResult(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    original_text: NonEmptyText
    text: NonEmptyText
    changed_spans: tuple[ChangedSpan, ...]
    requested_issue_ids: tuple[NonEmptyId, ...]
    preserved_checks: PreservationChecks
    rewrite_attempt: Annotated[int, Field(ge=1, le=2)]

    @model_validator(mode="after")
    def rewrite_is_coherent(self) -> "RewriteResult":
        if not self.changed_spans:
            raise ValueError("rewrite result must contain changed_spans")
        requested = set(self.requested_issue_ids)
        if not requested:
            raise ValueError("requested_issue_ids must not be empty")
        resolved = {
            issue_id for change in self.changed_spans for issue_id in change.resolved_issue_ids
        }
        if not resolved <= requested:
            raise ValueError("resolved_issue_ids must be present in requested_issue_ids")
        if len(self.requested_issue_ids) != len(requested):
            raise ValueError("requested_issue_ids must be unique")
        ordered = sorted(self.changed_spans, key=lambda item: item.original.start)
        for index, change in enumerate(ordered):
            _validate_span(change.original, self.original_text, field=f"changed_spans[{index}]")
            if index and ordered[index - 1].original.end > change.original.start:
                raise ValueError("changed_spans must not overlap")
        cursor = 0
        parts: list[str] = []
        for change in ordered:
            parts.append(self.original_text[cursor : change.original.start])
            parts.append(change.replacement.text)
            cursor = change.original.end
        parts.append(self.original_text[cursor:])
        if "".join(parts) != self.text:
            raise ValueError("changed_spans must reproduce the rewritten text")
        if not self.preserved_checks.required_facts or not self.preserved_checks.scene_state:
            raise ValueError("rewrite must preserve required facts and scene state")
        return self


class AcceptedDraft(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    text: NonEmptyText
    draft_hash: ContentHash
    memory_revision: NonNegativeInt

    @model_validator(mode="after")
    def hash_matches_text(self) -> "AcceptedDraft":
        if self.draft_hash != content_hash(self.text):
            raise ValueError("draft_hash must match accepted draft text")
        return self


class CommitRequest(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    accepted: AcceptedDraft


class CommitResult(DomainModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: NonEmptyId
    accepted_revision: PositiveRevision
    content_hash: ContentHash
    memory_revision: PositiveRevision
    occurrence_ids: tuple[NonEmptyId, ...] = ()
    idempotent_replay: bool

    @model_validator(mode="after")
    def occurrences_are_unique(self) -> "CommitResult":
        if len(self.occurrence_ids) != len(set(self.occurrence_ids)):
            raise ValueError("occurrence_ids must be unique")
        return self


__all__ = [
    "AcceptedDraft",
    "ArcState",
    "AuditIssue",
    "AuditMetrics",
    "AuditResult",
    "BehaviorFingerprint",
    "BehaviorIdentity",
    "BehaviorOccurrence",
    "CandidateBehavior",
    "ChangedSpan",
    "CharacterBehaviorIdentity",
    "CommitRequest",
    "CommitResult",
    "ExtractedBehavior",
    "ExtractionRequest",
    "ExtractionResult",
    "GeneratedDraft",
    "GenerationBrief",
    "GenerationRequest",
    "NarrativePosition",
    "OverusedBehavior",
    "PreservationChecks",
    "ReactionStrategyPlan",
    "RelationshipStrategyOverride",
    "RewriteRequest",
    "RewriteResult",
    "SignatureFamily",
    "SourceSpan",
    "StyleContext",
    "SyntaxFeatures",
    "TextReplacement",
    "TextSpan",
    "content_hash",
]
