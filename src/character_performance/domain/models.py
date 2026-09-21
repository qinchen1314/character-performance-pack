from __future__ import annotations

from math import pow
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]
SignedUnitFloat = Annotated[float, Field(ge=-1.0, le=1.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonEmptyId = Annotated[str, Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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
    visibility: Literal["hidden", "very_subtle", "subtle", "noticeable", "obvious"]
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
    status: Literal["active", "deprecated", "disabled"] = "active"

    @model_validator(mode="after")
    def require_semantics_and_provenance(self) -> "PerformanceUnit":
        if not self.semantic_groups:
            raise ValueError("semantic_groups must not be empty")
        if not self.semantics:
            raise ValueError("semantics must not be empty")
        if not self.source_refs:
            raise ValueError("source_refs must not be empty")
        return self


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

