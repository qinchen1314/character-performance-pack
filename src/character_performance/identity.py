"""Character behavior identities and deterministic reaction strategy planning.

This module is the T3 seam.  It deliberately knows about character identity,
relationships and scene context, while leaving action selection to the existing
performance engine.  The planner returns a :class:`ReactionStrategyPlan` that
can be consumed by a prompt builder without exposing storage or scoring
internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Iterable, Mapping, Protocol, Sequence

from character_performance.domain.behavior_models import (
    BehaviorIdentity,
    BehaviorOccurrence,
    ReactionStrategyPlan,
)
from character_performance.domain.models import (
    CharacterProfile,
    Cognition,
    EmotionState,
    Event,
    PhysicalState,
    RelationshipState,
    SceneState,
)


class BehaviorIdentityMissingError(LookupError):
    """Raised when planning is attempted without a registered identity."""

    code = "BEHAVIOR_IDENTITY_MISSING"

    def __init__(self, character_id: str, book_id: str | None = None) -> None:
        scope = f" for book {book_id}" if book_id else ""
        super().__init__(f"{self.code}: no behavior identity for {character_id}{scope}")
        self.character_id = character_id
        self.book_id = book_id


class IdentityRepository(Protocol):
    def save_identity(self, book_id: str, identity: BehaviorIdentity) -> None: ...

    def load_identity(
        self, book_id: str, character_id: str, version: int | None = None
    ) -> BehaviorIdentity | None: ...


class BehaviorIdentityRegistry:
    """Version-aware identity loader with an optional durable repository.

    The in-memory cache is useful for writing agents and tests.  When a
    repository is provided, the repository remains the source of truth and the
    cache only avoids repeated JSON validation in one generation run.
    """

    def __init__(self, repository: IdentityRepository | None = None) -> None:
        self.repository = repository
        self._identities: dict[tuple[str, str, int], BehaviorIdentity] = {}

    def register(self, book_id: str, identity: BehaviorIdentity, *, persist: bool = True) -> None:
        key = (book_id, identity.character_id, identity.version)
        self._identities[key] = identity.model_copy(deep=True)
        if persist and self.repository is not None:
            self.repository.save_identity(book_id, identity)

    save = register
    save_identity = register

    def load(
        self, book_id: str, character_id: str, version: int | None = None
    ) -> BehaviorIdentity | None:
        if version is not None:
            cached = self._identities.get((book_id, character_id, version))
            if cached is not None:
                return cached.model_copy(deep=True)
        elif self._identities:
            matches = [
                value
                for (b, c, _), value in self._identities.items()
                if b == book_id and c == character_id
            ]
            if matches:
                return max(matches, key=lambda item: item.version).model_copy(deep=True)
        if self.repository is None:
            return None
        identity = self.repository.load_identity(book_id, character_id, version)
        if identity is not None:
            self._identities[(book_id, character_id, identity.version)] = identity.model_copy(deep=True)
            return identity.model_copy(deep=True)
        return None

    def require(
        self, book_id: str, character_id: str, version: int | None = None
    ) -> BehaviorIdentity:
        identity = self.load(book_id, character_id, version)
        if identity is None:
            raise BehaviorIdentityMissingError(character_id, book_id)
        return identity

    def load_for_request(self, request: object) -> BehaviorIdentity:
        """Resolve the identity declared by a generation request's scope."""
        position = request.position
        return self.require(position.book_id, request.character.id)

    load_identity = load

    def clear(self) -> None:
        self._identities.clear()


IdentityLoader = BehaviorIdentityRegistry
IdentityRegistry = BehaviorIdentityRegistry


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """Normalized planner input independent of the generation request model."""

    character: CharacterProfile
    relation: RelationshipState | None = None
    event: Event | None = None
    cognition: Cognition | None = None
    emotion: EmotionState | None = None
    physical: PhysicalState = field(default_factory=PhysicalState)
    scene: SceneState | None = None
    publicness: float = 0.0
    intent: str = "conflict"
    target_id: str | None = None
    seed: int = 0

    @classmethod
    def from_request(cls, request: object) -> "StrategyContext":
        request_context = getattr(request, "context", None)
        event_publicness = request.event.publicness if request.event else None
        privacy = getattr(request_context, "privacy", "private")
        publicness = event_publicness if event_publicness is not None else (1.0 if privacy == "public" else 0.0)
        return cls(
            character=request.character,
            relation=request.relationship,
            event=request.event,
            cognition=request.cognition,
            emotion=request.emotion_state,
            physical=request.physical_state,
            scene=request.scene_state,
            publicness=publicness,
            intent=_infer_intent(request),
            target_id=request.relationship.target_id if request.relationship else None,
            seed=request.seed,
        )


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """A catalog entry, including hard constraints and human-readable meaning."""

    strategy_id: str
    intent: str
    surface_goal: str
    private_goal: str
    applicability_conditions: frozenset[str]
    contraindications: frozenset[str]
    preferred_channels: tuple[str, ...]
    suppressed_channels: frozenset[str]
    allowed_visibility: str
    action_budget: int
    omit_action_allowed: bool
    relationship_meaning: str

    @property
    def id(self) -> str:
        return self.strategy_id

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "intent": self.intent,
            "surface_goal": self.surface_goal,
            "private_goal": self.private_goal,
            "applicability_conditions": sorted(self.applicability_conditions),
            "contraindications": sorted(self.contraindications),
            "preferred_channels": list(self.preferred_channels),
            "suppressed_channels": sorted(self.suppressed_channels),
            "allowed_visibility": self.allowed_visibility,
            "action_budget": self.action_budget,
            "omit_action_allowed": self.omit_action_allowed,
            "relationship_meaning": self.relationship_meaning,
        }

    as_dict = model_dump

    def hard_contradictions(self, context: StrategyContext) -> tuple[str, ...]:
        reasons: list[str] = []
        relation = context.relation
        event = context.event
        if "requires_speech" in self.contraindications and "speech" not in context.character.capabilities:
            reasons.append("missing_speech_capability")
        if "requires_mobility" in self.contraindications and (
            "walking" not in context.character.capabilities or context.physical.mobility < 0.2
        ):
            reasons.append("insufficient_mobility")
        if "requires_target" in self.contraindications and not context.target_id:
            reasons.append("missing_target")
        if "public_only" in self.contraindications and context.publicness < 0.45:
            reasons.append("not_public")
        if "private_only" in self.contraindications and context.publicness > 0.65:
            reasons.append("not_private")
        if "requires_relationship" in self.contraindications and relation is None:
            reasons.append("missing_relationship")
        if "requires_low_hostility" in self.contraindications and relation and relation.hostility > 0.8:
            reasons.append("relationship_too_hostile")
        if "requires_intimacy" in self.contraindications and relation and relation.intimacy < 0.25:
            reasons.append("insufficient_intimacy")
        if "requires_event" in self.contraindications and event is None:
            reasons.append("missing_event")
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class StrategyRanking:
    strategy_id: str
    score: float
    accepted: bool
    reasons: tuple[str, ...] = ()
    breakdown: Mapping[str, float] = field(default_factory=dict)

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "score": self.score,
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "breakdown": dict(self.breakdown),
        }

    as_dict = model_dump


ReactionStrategyDefinition = StrategyDefinition
StrategyScore = StrategyRanking


def _definition(
    strategy_id: str,
    *,
    intent: str,
    surface: str,
    private: str,
    conditions: Iterable[str],
    contraindications: Iterable[str] = (),
    channels: Sequence[str],
    suppressed: Iterable[str] = (),
    visibility: str = "subtle",
    budget: int = 2,
    omit: bool = True,
    meaning: str,
) -> StrategyDefinition:
    # DomainModel uses identifier-shaped strings for strategy semantics.  Keep
    # the catalog readable above while normalizing display labels at the seam.
    normalize = lambda value: value.strip().lower().replace(" ", "_").replace("-", "_")
    return StrategyDefinition(
        strategy_id=strategy_id,
        intent=intent,
        surface_goal=normalize(surface),
        private_goal=normalize(private),
        applicability_conditions=frozenset(conditions),
        contraindications=frozenset(contraindications),
        preferred_channels=tuple(channels),
        suppressed_channels=frozenset(suppressed),
        allowed_visibility=visibility,
        action_budget=budget,
        omit_action_allowed=omit,
        relationship_meaning=normalize(meaning),
    )


class StrategyCatalog:
    """Immutable-by-default catalog of the supported reaction strategies."""

    def __init__(self, definitions: Iterable[StrategyDefinition] | None = None) -> None:
        values = tuple(definitions or default_strategy_definitions())
        if len({item.strategy_id for item in values}) != len(values):
            raise ValueError("strategy ids must be unique")
        self._definitions = {item.strategy_id: item for item in values}

    @classmethod
    def default(cls) -> "StrategyCatalog":
        return cls()

    def get(self, strategy_id: str) -> StrategyDefinition:
        try:
            return self._definitions[strategy_id]
        except KeyError as exc:
            raise KeyError(f"unknown reaction strategy: {strategy_id}") from exc

    def all(self) -> tuple[StrategyDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    @property
    def strategies(self) -> tuple[StrategyDefinition, ...]:
        return self.all()

    def __contains__(self, strategy_id: str) -> bool:
        return strategy_id in self._definitions

    def register(self, definition: StrategyDefinition, *, replace: bool = False) -> None:
        if definition.strategy_id in self._definitions and not replace:
            raise ValueError(f"strategy already registered: {definition.strategy_id}")
        self._definitions[definition.strategy_id] = definition

    def validate_identity(self, identity: BehaviorIdentity) -> None:
        referenced: set[str] = set(identity.default_strategies.values())
        for override in identity.relationship_overrides.values():
            referenced.update(override.preferred_strategies)
            referenced.update(override.forbidden_strategies)
        unknown = sorted(strategy_id for strategy_id in referenced if strategy_id not in self)
        if unknown:
            raise ValueError("unknown reaction strategies in identity: " + ", ".join(unknown))


def default_strategy_definitions() -> tuple[StrategyDefinition, ...]:
    # Every entry declares conditions, channel identity, visibility and a
    # relationship meaning.  Keeping this table data-like makes it easy for a
    # project to replace or extend without changing planner code.
    return (
        _definition("confront", intent="conflict", surface="challenge the threat", private="force clarity", conditions=("conflict", "high_hostility"), contraindications=("requires_target", "requires_speech"), channels=("speech_rhythm", "gaze", "spatial"), suppressed=("hands", "physiology"), visibility="noticeable", meaning="status_challenge"),
        _definition("pressure", intent="conflict", surface="increase pressure", private="make retreat costly", conditions=("conflict", "initiative"), contraindications=("requires_target",), channels=("speech_rhythm", "spatial", "gaze"), suppressed=("physiology",), visibility="noticeable", meaning="controlled_escalation"),
        _definition("boundary_assertion", intent="conflict", surface="mark a limit", private="protect agency", conditions=("conflict", "self_protection"), contraindications=("requires_target",), channels=("speech_rhythm", "spatial", "gaze"), suppressed=("exaggerated_facial",), meaning="boundary"),
        _definition("appease", intent="conflict", surface="lower immediate friction", private="buy safety or time", conditions=("conflict", "low_dominance"), contraindications=("requires_target", "requires_speech"), channels=("speech_rhythm", "spatial", "gaze"), suppressed=("hands",), meaning="deescalation"),
        _definition("repair_attempt", intent="intimacy", surface="repair contact", private="restore reciprocity", conditions=("intimacy", "relationship"), contraindications=("requires_target", "requires_low_hostility"), channels=("speech_rhythm", "gaze", "spatial"), suppressed=("obvious_facial",), meaning="relationship_repair"),
        _definition("guarded_disclosure", intent="intimacy", surface="offer a controlled truth", private="test safe vulnerability", conditions=("intimacy", "private"), contraindications=("requires_target", "requires_relationship", "requires_intimacy"), channels=("speech_rhythm", "gaze"), suppressed=("hands", "obvious_facial"), visibility="subtle", meaning="measured_vulnerability"),
        _definition("withdraw", intent="threat", surface="reduce contact", private="protect resources", conditions=("threat", "self_protection"), contraindications=("requires_target",), channels=("spatial", "gaze", "speech_rhythm"), suppressed=("hands",), meaning="distance"),
        _definition("freeze", intent="threat", surface="hold still", private="avoid revealing a decision", conditions=("threat", "overload"), contraindications=(), channels=("spatial", "physiology", "gaze"), suppressed=("speech_rhythm",), visibility="very_subtle", budget=1, meaning="concealed_alarm"),
        _definition("seek_protection", intent="threat", surface="move toward safety", private="delegate risk", conditions=("threat", "dependence"), contraindications=("requires_target", "requires_mobility"), channels=("spatial", "gaze", "speech_rhythm"), suppressed=("hands",), visibility="noticeable", meaning="reliance"),
        _definition("conceal", intent="conceal", surface="maintain the social mask", private="retain information control", conditions=("conceal", "self_control"), contraindications=(), channels=("speech_rhythm", "gaze", "spatial"), suppressed=("physiology", "hands", "exaggerated_facial"), meaning="information_control"),
        _definition("deflect", intent="conceal", surface="redirect attention", private="avoid commitment", conditions=("conceal", "uncertainty"), contraindications=("requires_speech",), channels=("speech_rhythm", "gaze"), suppressed=("physiology",), meaning="avoidance"),
        _definition("observe", intent="observe", surface="gather information", private="delay commitment", conditions=("observe", "uncertainty"), contraindications=(), channels=("gaze", "spatial", "speech_rhythm"), suppressed=("hands", "physiology"), visibility="subtle", budget=1, meaning="information_gathering"),
        _definition("delay_response", intent="observe", surface="withhold an immediate answer", private="retain initiative", conditions=("observe", "uncertainty"), contraindications=("requires_speech",), channels=("speech_rhythm", "gaze"), suppressed=("hands",), visibility="subtle", budget=1, meaning="tempo_control"),
        _definition("formal_compliance", intent="authority", surface="perform required courtesy", private="preserve room to maneuver", conditions=("authority", "public"), contraindications=("requires_target", "public_only"), channels=("speech_rhythm", "gaze", "spatial"), suppressed=("hands", "physiology"), meaning="role_compliance"),
        _definition("indirect_disagreement", intent="authority", surface="signal dissent without open challenge", private="keep initiative", conditions=("authority", "self_control"), contraindications=("requires_target",), channels=("speech_rhythm", "gaze"), suppressed=("hands", "obvious_facial"), meaning="guarded_dissent"),
        _definition("conceal_then_counter", intent="conflict", surface="maintain courtesy while preparing a reply", private="retain initiative", conditions=("conflict", "self_control"), contraindications=("requires_target",), channels=("speech_rhythm", "gaze", "spatial"), suppressed=("hands", "physiology"), meaning="hidden_counter"),
        _definition("controlled_exit", intent="threat", surface="end contact on chosen terms", private="preserve agency", conditions=("threat", "self_protection"), contraindications=("requires_target", "requires_mobility"), channels=("spatial", "speech_rhythm", "gaze"), suppressed=("physiology",), visibility="noticeable", meaning="chosen_departure"),
    )


DEFAULT_STRATEGY_CATALOG = StrategyCatalog(default_strategy_definitions())


def _infer_intent(request: object) -> str:
    relation = getattr(request, "relationship", None)
    event = getattr(request, "event", None)
    cognition = getattr(request, "cognition", None)
    request_context = getattr(request, "context", None)
    if request_context and getattr(request_context, "danger_level", 0.0) >= 0.55:
        return "threat"
    if request_context and getattr(request_context, "activity", "unknown") == "confrontation":
        return "conflict"
    if request_context and getattr(request_context, "formality", 0.0) >= 0.7:
        return "authority"
    if relation and relation.intimacy >= 0.65:
        return "intimacy"
    if event and max(event.threat.values(), default=0.0) >= 0.55:
        return "threat"
    if relation and (relation.hostility >= 0.35 or relation.tension >= 0.4):
        return "conflict"
    if relation and relation.dominance < -0.35:
        return "authority"
    if cognition and cognition.certainty < 0.35:
        return "observe"
    return "conflict"


def _stable_jitter(seed: int, strategy_id: str) -> float:
    digest = sha256(f"{seed}:{strategy_id}".encode("utf-8")).digest()
    return (int.from_bytes(digest[:8], "big") / 2**64 - 0.5) * 0.10


def _value(mapping: Mapping[str, float], keys: Iterable[str]) -> float:
    values = [mapping[key] for key in keys if key in mapping]
    return sum(values) / len(values) if values else 0.0


class ReactionStrategyPlanner:
    """Select a primary and optional secondary strategy deterministically."""

    def __init__(self, catalog: StrategyCatalog | None = None) -> None:
        self.catalog = catalog or StrategyCatalog.default()

    def rank(
        self,
        request_or_context: object,
        *,
        identity: BehaviorIdentity | None = None,
        history: Sequence[BehaviorOccurrence] | object = (),
    ) -> tuple[StrategyRanking, ...]:
        context = self._context(request_or_context)
        identity = identity or getattr(request_or_context, "behavior_identity", None)
        if identity is None:
            raise BehaviorIdentityMissingError(context.character.id)
        self.catalog.validate_identity(identity)
        recent_strategy_ids = self._recent_strategies(history)
        override = identity.relationship_overrides.get(context.target_id) if context.target_id else None
        mask = self._mask(identity, context)
        ranked: list[StrategyRanking] = []
        for definition in self.catalog.all():
            hard = list(definition.hard_contradictions(context))
            arc_exception = bool(
                identity.arc_state
                and definition.strategy_id in identity.arc_state.allowed_exceptions
            )
            relationship_exception = bool(
                override and definition.strategy_id in override.allowed_exceptions
            )
            if (
                (definition.strategy_id in identity.taboos or f"strategy.{definition.strategy_id}" in identity.taboos)
                and not arc_exception
            ):
                hard.append("identity_taboo")
            if override and definition.strategy_id in override.forbidden_strategies and not relationship_exception:
                hard.append("relationship_forbidden")
            if set(definition.preferred_channels) & set(identity.taboos) and not arc_exception:
                hard.append("taboo_channel")
            breakdown = self._score(identity, definition, context, override, mask, recent_strategy_ids)
            reasons = list(self._reasons(identity, definition, context, override, mask, breakdown))
            if arc_exception or relationship_exception:
                reasons.append("arc.allowed_exception" if arc_exception else "relationship.allowed_exception")
            if hard:
                reasons.extend(hard)
            ranked.append(
                StrategyRanking(
                    strategy_id=definition.strategy_id,
                    score=float(sum(breakdown.values()) + _stable_jitter(context.seed, definition.strategy_id)),
                    accepted=not hard,
                    reasons=tuple(dict.fromkeys(reasons)),
                    breakdown=breakdown,
                )
            )
        return tuple(sorted(ranked, key=lambda item: (-item.accepted, -item.score, item.strategy_id)))

    def plan(
        self,
        request_or_context: object,
        *,
        identity: BehaviorIdentity | None = None,
        history: Sequence[BehaviorOccurrence] | object = (),
    ) -> ReactionStrategyPlan:
        context = self._context(request_or_context)
        identity = identity or getattr(request_or_context, "behavior_identity", None)
        if identity is None:
            raise BehaviorIdentityMissingError(context.character.id)
        ranked = self.rank(context, identity=identity, history=history)
        accepted = [item for item in ranked if item.accepted]
        if not accepted:
            raise ValueError(f"no reaction strategy satisfies hard constraints for {context.character.id}")
        primary = accepted[0]
        secondary = next((item for item in accepted[1:] if item.strategy_id != primary.strategy_id), None)
        definition = self.catalog.get(primary.strategy_id)
        preferred_channels = list(definition.preferred_channels)
        override = identity.relationship_overrides.get(context.target_id) if context.target_id else None
        if override and override.preferred_channels:
            preferred_channels = list(
                dict.fromkeys(
                    [channel for channel in override.preferred_channels if channel in definition.preferred_channels]
                    + preferred_channels
                )
            )
        preferred_channels = [
            channel
            for channel in preferred_channels
            if channel not in identity.avoided_channels
            and (not override or channel not in override.avoided_channels)
        ]
        action_budget = definition.action_budget
        if not preferred_channels:
            # An identity may explicitly avoid every channel offered by the
            # chosen strategy.  Preserve that hard preference by selecting the
            # formal omit-action outcome instead of silently reintroducing a
            # forbidden channel.
            action_budget = 0
        reasons = tuple(item for item in primary.reasons if not item.endswith("_taboo")) or ("strategy.catalog_match",)
        return ReactionStrategyPlan(
            strategy_id=definition.strategy_id,
            intent=definition.intent,
            surface_goal=definition.surface_goal,
            private_goal=definition.private_goal,
            applicability_conditions=definition.applicability_conditions,
            contraindications=definition.contraindications,
            preferred_channels=tuple(preferred_channels),
            suppressed_channels=definition.suppressed_channels,
            allowed_visibility=definition.allowed_visibility,
            action_budget=action_budget,
            omit_action_allowed=definition.omit_action_allowed,
            relationship_meaning=definition.relationship_meaning,
            reasons=reasons,
            secondary_strategy_id=secondary.strategy_id if secondary else None,
        )

    def explain(
        self,
        request_or_context: object,
        *,
        identity: BehaviorIdentity | None = None,
        history: Sequence[BehaviorOccurrence] | object = (),
    ) -> tuple[StrategyRanking, ...]:
        return self.rank(request_or_context, identity=identity, history=history)

    def scene_mask(self, request_or_context: object, identity: BehaviorIdentity) -> str:
        return self._mask(identity, self._context(request_or_context))

    plan_for = plan

    @staticmethod
    def _context(value: object) -> StrategyContext:
        return value if isinstance(value, StrategyContext) else StrategyContext.from_request(value)

    @staticmethod
    def _mask(identity: BehaviorIdentity, context: StrategyContext) -> str:
        if context.publicness >= 0.55:
            return identity.social_masks.get("public", "public")
        if context.relation and context.relation.intimacy >= 0.65:
            return identity.social_masks.get("intimate", "intimate")
        return identity.social_masks.get("private", "private")

    @staticmethod
    def _recent_strategies(history: Sequence[BehaviorOccurrence] | object) -> tuple[str, ...]:
        if hasattr(history, "immediate"):
            history = history.immediate
        return tuple(
            item.fingerprint.strategy_id
            for item in list(history or ())[-5:]
            if item.fingerprint.strategy_id
        )

    def _score(
        self,
        identity: BehaviorIdentity,
        definition: StrategyDefinition,
        context: StrategyContext,
        override: object,
        mask: str,
        recent_strategy_ids: Sequence[str],
    ) -> dict[str, float]:
        relation = context.relation
        event = context.event
        high_hostility = relation.hostility if relation else 0.0
        dominance = relation.dominance if relation else 0.0
        intimacy = relation.intimacy if relation else 0.0
        threat = max(event.threat.values(), default=0.0) if event else 0.0
        certainty = context.cognition.certainty if context.cognition else 0.5
        initiative = context.character.expression_baseline.initiative
        self_control = context.character.personality.big_five.conscientiousness
        relationship_fit = 0.0
        default_strategy = identity.default_strategies.get(context.intent) or identity.default_strategies.get("conflict")
        if definition.strategy_id == default_strategy:
            relationship_fit += 2.1
        elif definition.strategy_id in identity.default_strategies.values():
            relationship_fit += 0.3
        if override and definition.strategy_id in override.preferred_strategies:
            relationship_fit += 2.8
        if mask in definition.applicability_conditions:
            relationship_fit += 0.35
        context_fit = {
            "conflict": high_hostility * 1.4 + (0.4 if threat else 0.0),
            "threat": threat * 1.6,
            "intimacy": intimacy * 1.5,
            "authority": max(0.0, -dominance) * 1.3 + context.publicness * 0.4,
            "observe": (1.0 - certainty) * 1.2,
            "conceal": self_control * 0.9,
        }.get(definition.intent, 0.2)
        goal_fit = initiative * (0.5 if definition.strategy_id in {"pressure", "confront", "conceal_then_counter"} else 0.25)
        emotion_fit = (context.emotion.intensity if context.emotion else 0.35) * (0.4 if threat or high_hostility else 0.2)
        identity_fit = _value(identity.preferred_channels, definition.preferred_channels) - _value(identity.avoided_channels, definition.preferred_channels)
        recent_penalty = 0.75 * recent_strategy_ids.count(definition.strategy_id)
        taboo_penalty = 0.0
        if any(token in identity.taboos for token in definition.preferred_channels):
            taboo_penalty = 2.0
        return {
            "identity_affinity": identity_fit,
            "relationship_fit": relationship_fit,
            "goal_fit": goal_fit,
            "emotion_fit": emotion_fit,
            "context_fit": context_fit,
            "arc_fit": (identity.arc_state.openness_delta * 0.3 if identity.arc_state else 0.0),
            "recent_strategy_penalty": -recent_penalty,
            "taboo_penalty": -taboo_penalty,
        }

    @staticmethod
    def _reasons(
        identity: BehaviorIdentity,
        definition: StrategyDefinition,
        context: StrategyContext,
        override: object,
        mask: str,
        breakdown: Mapping[str, float],
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if definition.strategy_id in identity.default_strategies.values():
            reasons.append("identity.default_strategy")
        if override and definition.strategy_id in override.preferred_strategies:
            reasons.append("relationship.preferred_strategy")
        if mask in definition.applicability_conditions:
            reasons.append("scene.social_mask")
        if breakdown.get("context_fit", 0) > 0.8:
            reasons.append(f"context.{definition.intent}")
        if breakdown.get("recent_strategy_penalty", 0) < 0:
            reasons.append("recent_strategy_overuse")
        if identity.arc_state and definition.strategy_id in identity.arc_state.allowed_exceptions:
            reasons.append("arc.versioned_exception")
        if not reasons:
            reasons.append("strategy.fallback")
        return tuple(reasons)


def sample_identity_shells() -> tuple[BehaviorIdentity, ...]:
    """Return ten deliberately different identity shells for regression fixtures."""
    profiles = (
        ("char.controlled", "conceal_then_counter", ("gaze", "speech_rhythm"), "self_control"),
        ("char.direct", "confront", ("speech_rhythm", "spatial"), "candor"),
        ("char.peacemaker", "repair_attempt", ("speech_rhythm", "gaze"), "reciprocity"),
        ("char.wary", "observe", ("gaze", "spatial"), "information"),
        ("char.frightened", "freeze", ("physiology", "spatial"), "survival"),
        ("char.formal", "formal_compliance", ("speech_rhythm", "gaze"), "status"),
        ("char.rebellious", "indirect_disagreement", ("speech_rhythm", "spatial"), "autonomy"),
        ("char.dependent", "seek_protection", ("spatial", "gaze"), "safety"),
        ("char.guarded", "guarded_disclosure", ("speech_rhythm", "gaze"), "trust"),
        ("char.exit", "controlled_exit", ("spatial", "speech_rhythm"), "agency"),
    )
    result: list[BehaviorIdentity] = []
    for character_id, preferred, channels, value in profiles:
        result.append(
            BehaviorIdentity(
                character_id=character_id,
                version=1,
                default_strategies={"conflict": preferred, "threat": preferred, "intimacy": preferred},
                preferred_channels={channels[0]: 0.9, channels[1]: 0.7},
                values=frozenset({value}),
                taboos=frozenset(),
                coping_strategies=frozenset({preferred}),
                social_masks={"public": "public", "private": "private", "intimate": "intimate"},
            )
        )
    return tuple(result)


__all__ = [
    "BehaviorIdentityMissingError",
    "BehaviorIdentityRegistry",
    "IdentityLoader",
    "IdentityRegistry",
    "IdentityRepository",
    "ReactionStrategyPlanner",
    "StrategyCatalog",
    "StrategyContext",
    "StrategyDefinition",
    "ReactionStrategyDefinition",
    "StrategyRanking",
    "StrategyScore",
    "default_strategy_definitions",
    "DEFAULT_STRATEGY_CATALOG",
    "sample_identity_shells",
]
