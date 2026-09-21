from __future__ import annotations

from math import pow
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]
SignedUnitFloat = Annotated[float, Field(ge=-1.0, le=1.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonEmptyId = Annotated[str, Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Appraisal(DomainModel):
    goal_congruence: SignedUnitFloat = 0
    controllability: UnitFloat = 0.5
    responsibility: Literal["self", "target", "environment", "unknown"] = "unknown"
    certainty: UnitFloat = 0.5


class VAD(DomainModel):
    valence: SignedUnitFloat
    arousal: SignedUnitFloat
    dominance: SignedUnitFloat


class IntensityRange(DomainModel):
    min: UnitFloat
    max: UnitFloat

    @model_validator(mode="after")
    def ordered(self) -> "IntensityRange":
        if self.min > self.max:
            raise ValueError("intensity_range.min must not exceed max")
        return self


class EmotionState(DomainModel):
    primary: NonEmptyId
    secondary: NonEmptyId | None = None
    families: frozenset[NonEmptyId] = frozenset()
    intensity: UnitFloat
    vad: VAD
    restraint: UnitFloat = 0.0
    awareness: UnitFloat = 1.0
    duration_ms: NonNegativeInt = 0
    decay_half_life_ms: Annotated[int, Field(gt=0)]
    trigger_refs: tuple[NonEmptyId, ...] = ()
    appraisal: Appraisal = Appraisal()

    def decayed(self, elapsed_ms: int) -> "EmotionState":
        """Return a new state after exponential half-life decay."""
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")
        factor = pow(0.5, elapsed_ms / self.decay_half_life_ms)
        return self.model_copy(
            update={
                "intensity": self.intensity * factor,
                "duration_ms": self.duration_ms + elapsed_ms,
            }
        )


class OntologyEmotion(DomainModel):
    id: NonEmptyId
    label_zh: Annotated[str, Field(min_length=1)]
    families: frozenset[NonEmptyId]
    aliases: frozenset[str] = frozenset()
    prototype_vad: VAD
    source_refs: tuple[NonEmptyId, ...]

    @model_validator(mode="after")
    def require_taxonomy_and_source(self) -> "OntologyEmotion":
        if not self.families:
            raise ValueError("emotion must belong to at least one family")
        if not self.source_refs:
            raise ValueError("emotion must have at least one source_ref")
        return self


class Cooldown(DomainModel):
    turns: NonNegativeInt = 0
    scene_scope: bool = True


class FacialAction(DomainModel):
    region: Literal["brow", "lips", "jaw", "mouth", "eyelids", "unknown"]
    action: NonEmptyId
    intensity: UnitFloat
    au_ref: str | None = None


class MicroTiming(DomainModel):
    onset_ms: tuple[NonNegativeInt, NonNegativeInt]
    apex_ms: tuple[NonNegativeInt, NonNegativeInt]
    offset_ms: tuple[NonNegativeInt, NonNegativeInt]
    total_duration_ms: tuple[NonNegativeInt, NonNegativeInt]

    @model_validator(mode="after")
    def consistent(self):
        for interval in (self.onset_ms, self.apex_ms, self.offset_ms, self.total_duration_ms):
            if interval[0] > interval[1]:
                raise ValueError("micro timing intervals must be ordered")
        for index in (0, 1):
            if sum(interval[index] for interval in (self.onset_ms, self.apex_ms, self.offset_ms)) != self.total_duration_ms[index]:
                raise ValueError("micro timing phases must sum to total range")
        return self


class PerformanceUnit(DomainModel):
    id: NonEmptyId
    schema_version: str = "1.0.0"
    category: Literal[
        "facial",
        "micro_expression",
        "gaze",
        "body",
        "spatial",
        "physiology",
        "speech",
        "world_specific",
        "unknown",
    ]
    channel: NonEmptyId
    atomic_action: NonEmptyId
    body_parts: frozenset[NonEmptyId] = frozenset()
    semantic_groups: frozenset[NonEmptyId]
    semantics: dict[NonEmptyId, UnitFloat]
    emotion_affinity: dict[NonEmptyId, UnitFloat] = Field(default_factory=dict)
    intensity_range: IntensityRange
    context_requirements: dict[str, Any] = Field(default_factory=dict)
    physical_requirements: dict[str, Any] = Field(default_factory=dict)
    preconditions: tuple[NonEmptyId, ...] = ()
    conflicts: frozenset[NonEmptyId] = frozenset()
    compatible_with: frozenset[NonEmptyId] = frozenset()
    visibility: Literal["hidden", "very_subtle", "subtle", "noticeable", "obvious", "unknown"]
    narrative_weight: UnitFloat
    cooldown: Cooldown = Cooldown()
    repeat_group: NonEmptyId
    render_hints: dict[str, Any] = Field(default_factory=dict)
    source_refs: tuple[NonEmptyId, ...]
    license_class: Literal[
        "reference_only",
        "derived_metadata",
        "transform_allowed",
        "redistribution_allowed",
        "original",
    ]
    status: Literal["active", "deprecated", "disabled", "unknown"] = "active"
    effects: dict[str, Any] = Field(default_factory=dict)
    vad_affinity: VAD | None = None
    timing_ms: tuple[NonNegativeInt, NonNegativeInt] | None = None
    facial_units: tuple[FacialAction, ...] = ()
    timing: MicroTiming | None = None
    world_requirements: dict[str, Any] = Field(default_factory=dict)
    invocation: Literal["automatic", "blocking"] = "automatic"

    @model_validator(mode="after")
    def require_semantics_and_provenance(self) -> "PerformanceUnit":
        if not self.semantic_groups:
            raise ValueError("semantic_groups must not be empty")
        if not self.semantics:
            raise ValueError("semantics must not be empty")
        if not self.source_refs:
            raise ValueError("source_refs must not be empty")
        if self.timing_ms and self.timing_ms[0] > self.timing_ms[1]:
            raise ValueError("timing_ms must be ordered")
        return self


class BigFive(DomainModel):
    openness: UnitFloat = 0.5
    conscientiousness: UnitFloat = 0.5
    extraversion: UnitFloat = 0.5
    agreeableness: UnitFloat = 0.5
    neuroticism: UnitFloat = 0.5


class Personality(DomainModel):
    big_five: BigFive = BigFive()


class ExpressionBaseline(DomainModel):
    amplitude: UnitFloat = 0.5
    initiative: UnitFloat = 0.5
    speech_volume: UnitFloat = 0.5
    gaze_duration: UnitFloat = 0.5


class SignatureBehaviour(DomainModel):
    unit_id: NonEmptyId
    affinity: UnitFloat = 0.5
    cooldown_turns: NonNegativeInt = 9


class CharacterProfile(DomainModel):
    id: NonEmptyId
    personality: Personality = Personality()
    expression_baseline: ExpressionBaseline = ExpressionBaseline()
    capabilities: frozenset[NonEmptyId] = frozenset({
        "vision", "speech", "hearing", "right_hand_use", "left_hand_use", "walking"
    })
    signature_behaviours: tuple[SignatureBehaviour, ...] = ()


class RelationshipState(DomainModel):
    subject_id: NonEmptyId
    target_id: NonEmptyId
    type_tags: frozenset[NonEmptyId] = frozenset()
    affinity: UnitFloat = 0.5
    trust: UnitFloat = 0.5
    familiarity: UnitFloat = 0.5
    dominance: SignedUnitFloat = 0
    dependence: UnitFloat = 0
    tension: UnitFloat = 0
    hostility: UnitFloat = 0
    intimacy: UnitFloat = 0
    public_role_constraints: frozenset[NonEmptyId] = frozenset()


class Injury(DomainModel):
    body_part: NonEmptyId
    severity: UnitFloat
    constraints: frozenset[NonEmptyId] = frozenset()


class PhysicalState(DomainModel):
    fatigue: UnitFloat = 0
    pain: UnitFloat = 0
    injuries: tuple[Injury, ...] = ()
    mobility: UnitFloat = 1
    breath_capacity: UnitFloat = 1
    motor_control: UnitFloat = 1
    sensory_constraints: frozenset[NonEmptyId] = frozenset()


class EmotionalResidue(DomainModel):
    emotion: NonEmptyId
    intensity: UnitFloat
    expires_after_turn: NonNegativeInt


class Landmark(DomainModel):
    id: NonEmptyId
    label_zh: Annotated[str, Field(min_length=1, max_length=60)]
    seat_id: NonEmptyId | None = None
    seat_label: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    distances: dict[NonEmptyId, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def seat_is_explicit(self):
        if (self.seat_id is None) != (self.seat_label is None):
            raise ValueError("seat_id and seat_label must be supplied together")
        if self.seat_id and not self.seat_id.startswith("seat."):
            raise ValueError("seat_id must use seat. namespace")
        return self


class PathEdge(DomainModel):
    origin: NonEmptyId
    destination: NonEmptyId
    duration_ms: Annotated[int, Field(gt=0, le=3600000)]
    blocked: bool = False


class SceneLayout(DomainModel):
    landmarks: tuple[Landmark, ...]
    edges: tuple[PathEdge, ...] = ()

    @model_validator(mode="after")
    def valid_graph(self):
        ids = {node.id for node in self.landmarks}
        if len(ids) != len(self.landmarks):
            raise ValueError("duplicate landmark id")
        edges = set()
        seats = [node.seat_id for node in self.landmarks if node.seat_id]
        if len(seats) != len(set(seats)):
            raise ValueError("a seat cannot belong to multiple landmarks")
        for edge in self.edges:
            key = (edge.origin, edge.destination)
            if key in edges or edge.origin == edge.destination or not set(key) <= ids:
                raise ValueError("duplicate, self-referencing or dangling path edge")
            edges.add(key)
        return self


class BlockingGoal(DomainModel):
    destination: NonEmptyId
    pose: Literal["standing", "seated"] = "standing"
    interruption_policy: Literal["pause", "forbid"] = "pause"


class ActiveAction(DomainModel):
    id: NonEmptyId
    kind: Literal["navigation"] = "navigation"
    status: Literal["running", "paused"] = "running"
    goal: BlockingGoal
    route: tuple[NonEmptyId, ...]
    edge_index: NonNegativeInt = 0
    elapsed_ms: NonNegativeInt = 0
    pack_hash: str


class BlockingStep(DomainModel):
    unit_id: NonEmptyId
    phase: Literal["instant", "start", "continue", "complete", "pause", "resume"]
    destination: NonEmptyId | None = None
    elapsed_ms: NonNegativeInt = 0
    duration_ms: NonNegativeInt = 0
    render: bool = True


class SceneState(DomainModel):
    scene_id: NonEmptyId
    turn_index: NonNegativeInt = 0
    revision: NonNegativeInt = 0
    pose: Literal["standing", "seated", "leaning_wall", "lying", "unknown"] = "unknown"
    position: NonEmptyId | None = None
    orientation_target: NonEmptyId | None = None
    held_objects: dict[Literal["right_hand", "left_hand"], NonEmptyId] = Field(default_factory=dict)
    distances: dict[NonEmptyId, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)
    support_contact: NonEmptyId | None = None
    unfinished_actions: tuple[NonEmptyId, ...] = ()
    emotional_residue: tuple[EmotionalResidue, ...] = ()
    layout: SceneLayout | None = None
    active_action: ActiveAction | None = None
    time_ms: NonNegativeInt = 0

    @model_validator(mode="after")
    def validate_navigation_state(self):
        action = self.active_action
        if action is None:
            return self
        if self.layout is None or not action.route or action.edge_index >= len(action.route):
            raise ValueError("active navigation requires a valid layout and route index")
        nodes = {node.id: node for node in self.layout.landmarks}
        edges = {(edge.origin, edge.destination): edge for edge in self.layout.edges}
        if not set(action.route) <= nodes.keys() or len(set(action.route)) != len(action.route) or action.goal.destination != action.route[-1]:
            raise ValueError("active navigation route is invalid")
        if any(pair not in edges for pair in zip(action.route, action.route[1:])):
            raise ValueError("active navigation references an unknown edge")
        if action.edge_index == len(action.route) - 1:
            if action.elapsed_ms != 0:
                raise ValueError("completed route cannot have partial edge progress")
        else:
            edge = edges[(action.route[action.edge_index], action.route[action.edge_index + 1])]
            if action.elapsed_ms >= edge.duration_ms:
                raise ValueError("partial edge progress must be below duration")
        expected_position = None if action.elapsed_ms else action.route[action.edge_index]
        permitted_contact = (
            action.edge_index == len(action.route) - 1 and action.goal.pose == "seated"
            and self.support_contact == nodes[action.goal.destination].seat_id
        )
        if self.position != expected_position or self.pose != "standing" or (self.support_contact is not None and not permitted_contact):
            raise ValueError("active navigation pose, support or position is inconsistent")
        return self


class Event(DomainModel):
    id: NonEmptyId
    participants: tuple[NonEmptyId, ...] = ()
    salience: UnitFloat = 0.5
    publicness: UnitFloat = 0
    threat: dict[Literal["physical", "social"], UnitFloat] = Field(default_factory=dict)


class Cognition(DomainModel):
    subject_id: NonEmptyId
    interpretation: NonEmptyId = "unknown"
    goal_impact: SignedUnitFloat = 0
    controllability: UnitFloat = 0.5
    certainty: UnitFloat = 0.5
    target_responsibility: UnitFloat = 0


class Context(DomainModel):
    activity: Literal["conversation", "confrontation", "waiting", "unknown"] = "conversation"
    audience_size: NonNegativeInt = 0
    privacy: Literal["private", "public", "unknown"] = "private"
    formality: UnitFloat = 0
    danger_level: UnitFloat = 0


class Director(DomainModel):
    beat_importance: UnitFloat = 0.5
    max_signals: Annotated[int, Field(ge=0, le=6)] = 2
    desired_visibility: Literal["very_subtle", "subtle", "noticeable", "obvious", "unknown"] = "noticeable"
    allow_world: bool = False
    disabled_units: frozenset[NonEmptyId] = frozenset()


class Masking(DomainModel):
    displayed_emotion: NonEmptyId = "calm"
    mask_strength: UnitFloat = 0
    control_capacity: UnitFloat = 1
    leak_pressure: UnitFloat = 0.5


class WorldState(DomainModel):
    genre: Literal["general", "xianxia", "unknown"] = "general"
    realm: Literal["mortal", "qi_refining", "foundation", "golden_core", "unknown"] = "mortal"
    stage: Annotated[int, Field(ge=1, le=9)] = 1
    qi: UnitFloat = 1
    control: UnitFloat = 1
    target_realm: Literal["mortal", "qi_refining", "foundation", "golden_core", "unknown"] = "unknown"
    suppressed_capabilities: frozenset[NonEmptyId] = frozenset()
    active_capabilities: frozenset[NonEmptyId] = frozenset()
    destruction_limit: UnitFloat = 0


class PerformanceRequest(DomainModel):
    request_id: NonEmptyId
    character: CharacterProfile
    relationship: RelationshipState | None = None
    event: Event | None = None
    cognition: Cognition | None = None
    emotion_state: EmotionState | None = None
    physical_state: PhysicalState = PhysicalState()
    scene_state: SceneState
    context: Context = Context()
    director: Director = Director()
    masking: Masking | None = None
    world_state: WorldState = WorldState()
    seed: int = 0
    blocking_goal: BlockingGoal | None = None
    elapsed_ms: Annotated[int, Field(ge=0, le=60000)] = 0
    action_control: Literal["continue", "pause", "resume"] = "continue"

    @model_validator(mode="after")
    def subject_matches(self) -> "PerformanceRequest":
        for state in (self.relationship, self.cognition):
            if state and state.subject_id != self.character.id:
                raise ValueError("subject_id must match character.id")
        return self


class HistoryEntry(DomainModel):
    turn_index: NonNegativeInt
    unit_id: NonEmptyId
    semantic_groups: frozenset[NonEmptyId]
    channel: NonEmptyId
    intensity: UnitFloat
    render_features: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class StateTransition(DomainModel):
    before: SceneState
    after: SceneState
    world_before: WorldState
    world_after: WorldState


class ValidationReport(DomainModel):
    valid: bool
    errors: tuple[str, ...] = ()


class PerformancePlan(DomainModel):
    plan_id: NonEmptyId
    schema_version: str = "1.0.0"
    subject_id: NonEmptyId
    target_ids: tuple[NonEmptyId, ...] = ()
    scene_id: NonEmptyId
    turn_index: NonNegativeInt
    seed: int
    primary_signal: NonEmptyId | None = None
    secondary_signals: tuple[NonEmptyId, ...] = ()
    surface_signals: tuple[NonEmptyId, ...] = ()
    leak_signals: tuple[NonEmptyId, ...] = ()
    selected: dict[str, tuple[NonEmptyId, ...]] = Field(default_factory=dict)
    parameters: dict[NonEmptyId, dict[str, Any]] = Field(default_factory=dict)
    pack_version: str = "0.3.0"
    pack_hash: str = ""
    rule_version: str = "1.1.0"
    input_hash: str = ""
    emotion_state: EmotionState | None = None
    state_transition: StateTransition | None = None
    suppressed_candidates: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    scores: dict[str, dict[str, float]] = Field(default_factory=dict)
    world_decisions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    sequence: tuple[BlockingStep, ...] = ()
    continuation_signals: tuple[NonEmptyId, ...] = ()

    @property
    def unit_ids(self) -> tuple[str, ...]:
        return tuple(unit for units in self.selected.values() for unit in units)


class RenderContext(DomainModel):
    subject_name: Annotated[str, Field(min_length=1, max_length=50)] = "他"
    target_name: Annotated[str, Field(min_length=1, max_length=50)] = "对方"
    dialogue: Annotated[str, Field(max_length=2000)] | None = None


class RenderResult(DomainModel):
    text: str
    realized_units: dict[str, str] = Field(default_factory=dict)
    omitted_units: tuple[str, ...] = ()
    introduced_facts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
