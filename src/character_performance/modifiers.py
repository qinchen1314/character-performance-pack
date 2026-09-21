"""A small declarative modifier language; no eval, code strings, or hard constraints."""
from __future__ import annotations

from typing import Annotated, Literal
from math import fsum

from pydantic import Field, model_validator

from character_performance.domain.models import DomainModel, NonEmptyId, PerformanceRequest, PerformanceUnit
from character_performance.scoring import clamp

Scalar = Annotated[float, Field(ge=-2, le=2)]
PATHS = {
    "personality.openness", "personality.conscientiousness", "personality.extraversion",
    "personality.agreeableness", "personality.neuroticism",
    "relationship.dominance", "relationship.intimacy", "relationship.hostility", "relationship.trust",
    "context.formality", "context.danger_level", "physical.fatigue", "physical.pain",
    "director.beat_importance", "world.control",
}
ORDER = {kind: index for index, kind in enumerate(("personality", "relationship", "context", "physical", "director", "world"))}


class Condition(DomainModel):
    lt: Scalar | None = None
    gt: Scalar | None = None

    @model_validator(mode="after")
    def has_comparison(self):
        if self.lt is None and self.gt is None:
            raise ValueError("modifier condition requires lt or gt")
        if self.lt is not None and self.gt is not None and self.gt >= self.lt:
            raise ValueError("modifier condition is unreachable")
        return self


class ModifierEffects(DomainModel):
    score_add: dict[str, Scalar] = Field(default_factory=dict)
    parameter_add: dict[Literal["amplitude", "directness", "volume", "pace"], Scalar] = Field(default_factory=dict)
    budget_add: dict[Literal["total", "speech", "body", "facial", "gaze", "spatial", "physiology", "world_specific"], Annotated[int, Field(ge=-6, le=6)]] = Field(default_factory=dict)


class Modifier(DomainModel):
    id: NonEmptyId
    kind: Literal["personality", "relationship", "context", "physical", "director", "world"]
    when: dict[str, Condition]
    effects: ModifierEffects
    priority: int = 50
    stacking: Literal["additive_clamped"] = "additive_clamped"
    source_refs: tuple[NonEmptyId, ...] = ("src.original.performance.v1",)

    @model_validator(mode="after")
    def validate_language(self):
        if not self.when or set(self.when) - PATHS:
            raise ValueError("unknown or empty modifier condition path")
        if not self.source_refs:
            raise ValueError("modifier requires source_refs")
        for selector in self.effects.score_add:
            prefix, separator, value = selector.partition(".")
            if not separator or prefix not in {"channel", "category", "semantic"} or not value:
                raise ValueError("invalid modifier score selector")
        return self


def active_modifiers(modifiers: tuple[Modifier, ...], request: PerformanceRequest) -> tuple[Modifier, ...]:
    roots = {"personality": request.character.personality.big_five,
        "relationship": request.relationship, "context": request.context,
        "physical": request.physical_state, "director": request.director, "world": request.world_state}
    active = []
    for modifier in modifiers:
        matches = True
        for path, condition in modifier.when.items():
            root, key = path.split(".")
            value = getattr(roots[root], key, None)
            if value is None or (condition.lt is not None and value >= condition.lt) or (condition.gt is not None and value <= condition.gt):
                matches = False
                break
        if matches:
            active.append(modifier)
    return tuple(sorted(active, key=lambda m: (ORDER[m.kind], m.priority, m.id)))


def score_modifiers(modifiers: tuple[Modifier, ...], unit: PerformanceUnit) -> dict[str, float]:
    result = {}
    for modifier in modifiers:
        terms = []
        for selector, value in sorted(modifier.effects.score_add.items()):
            prefix, key = selector.split(".", 1)
            if prefix == "semantic":
                terms.append(value * unit.semantics.get(key, 0))
            elif (prefix == "channel" and key == unit.channel) or (prefix == "category" and key == unit.category):
                terms.append(value)
        result[f"modifier:{modifier.id}"] = fsum(terms)
    return result


def parameter_modifiers(modifiers: tuple[Modifier, ...], parameters: dict[str, float]) -> dict[str, float]:
    result = dict(parameters)
    for modifier in modifiers:
        for name, amount in modifier.effects.parameter_add.items():
            if name in result:
                result[name] = round(clamp(result[name] + amount), 4)
    return result
