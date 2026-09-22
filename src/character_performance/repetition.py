"""Cross-chapter, multi-window behavior repetition policy (T4).

The policy consumes the snapshot returned by ``BehaviorMemory.query_history``
and never writes to storage.  It compares behavior fingerprints rather than
surface strings, so a paraphrase such as ``握拳`` / ``指甲陷入掌心`` still
shares the ``hand_tension`` semantic group.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import exp
import re
from typing import Iterable, Mapping, Sequence

from character_performance.domain.behavior_models import (
    BehaviorFingerprint,
    BehaviorIdentity,
    BehaviorOccurrence,
    CandidateBehavior,
    SyntaxFeatures,
)
from character_performance.domain.models import PerformanceUnit
from character_performance.memory.repository import BehaviorMemorySnapshot


@dataclass(frozen=True, slots=True)
class RepetitionWindowConfig:
    """Window and decay settings.  All seven windows are explicit and tunable."""

    immediate: int = 5
    scene: int | None = None
    chapter: int | None = None
    recent_chapters: int = 3
    volume: int | None = None
    book: int | None = None
    ensemble: int = 20
    exact_horizon: int = 3
    chapter_semantic_limit: int = 2
    chapter_syntax_limit: int = 3
    half_life_beats: float = 18.0
    half_life_chapters: float = 3.0

    def __post_init__(self) -> None:
        for name in ("immediate", "recent_chapters", "ensemble", "exact_horizon", "chapter_semantic_limit", "chapter_syntax_limit"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        for name in ("scene", "chapter", "volume", "book"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be positive when configured")
        if self.half_life_beats <= 0 or self.half_life_chapters <= 0:
            raise ValueError("decay half lives must be positive")


@dataclass(frozen=True, slots=True)
class RepetitionWeights:
    exact_unit: float = 4.0
    semantic_group: float = 2.2
    narrative_function: float = 1.6
    channel_saturation: float = 1.2
    syntax_pattern: float = 1.7
    lexical_echo: float = 0.8
    ensemble_collision: float = 1.35
    trope_frequency: float = 0.85


@dataclass(frozen=True, slots=True)
class RepetitionScore:
    """Explainable score for one candidate fingerprint."""

    unit_id: str | None
    total_penalty: float
    exact_unit_penalty: float = 0.0
    semantic_group_penalty: float = 0.0
    narrative_function_penalty: float = 0.0
    channel_saturation_penalty: float = 0.0
    syntax_pattern_penalty: float = 0.0
    lexical_echo_penalty: float = 0.0
    ensemble_collision_penalty: float = 0.0
    trope_frequency_penalty: float = 0.0
    signature_permission: float = 0.0
    continuity_necessity: float = 0.0
    hard_block: bool = False
    reasons: tuple[str, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def penalty(self) -> float:
        return self.total_penalty

    @property
    def blocked(self) -> bool:
        return self.hard_block

    @property
    def allowed(self) -> bool:
        return not self.hard_block

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "total_penalty": self.total_penalty,
            "exact_unit_penalty": self.exact_unit_penalty,
            "semantic_group_penalty": self.semantic_group_penalty,
            "narrative_function_penalty": self.narrative_function_penalty,
            "channel_saturation_penalty": self.channel_saturation_penalty,
            "syntax_pattern_penalty": self.syntax_pattern_penalty,
            "lexical_echo_penalty": self.lexical_echo_penalty,
            "ensemble_collision_penalty": self.ensemble_collision_penalty,
            "trope_frequency_penalty": self.trope_frequency_penalty,
            "signature_permission": self.signature_permission,
            "continuity_necessity": self.continuity_necessity,
            "hard_block": self.hard_block,
            "reasons": list(self.reasons),
            "counts": dict(self.counts),
        }

    as_dict = model_dump


CandidateRepetition = RepetitionScore


@dataclass(frozen=True, slots=True)
class BehaviorStatisticsReport:
    """Distribution report used by chapter and editorial dashboards."""

    total_occurrences: int
    by_unit: Mapping[str, int]
    by_semantic_group: Mapping[str, int]
    by_narrative_function: Mapping[str, int]
    by_channel: Mapping[str, int]
    by_syntax_feature: Mapping[str, int]
    by_actor: Mapping[str, int]
    chapter_repeat_hotspots: Mapping[str, int]
    trope_groups: tuple[str, ...]

    @property
    def channel_share(self) -> Mapping[str, float]:
        denominator = max(1, self.total_occurrences)
        return {key: value / denominator for key, value in self.by_channel.items()}

    @property
    def semantic_group_share(self) -> Mapping[str, float]:
        denominator = max(1, self.total_occurrences)
        return {key: value / denominator for key, value in self.by_semantic_group.items()}

    @property
    def top_channel(self) -> str | None:
        return max(self.by_channel, key=self.by_channel.get) if self.by_channel else None

    def as_dict(self) -> dict[str, object]:
        return {
            "total_occurrences": self.total_occurrences,
            "by_unit": dict(self.by_unit),
            "by_semantic_group": dict(self.by_semantic_group),
            "by_narrative_function": dict(self.by_narrative_function),
            "by_channel": dict(self.by_channel),
            "by_syntax_feature": dict(self.by_syntax_feature),
            "by_actor": dict(self.by_actor),
            "chapter_repeat_hotspots": dict(self.chapter_repeat_hotspots),
            "trope_groups": list(self.trope_groups),
        }


@dataclass(frozen=True, slots=True)
class _Windows:
    immediate: tuple[BehaviorOccurrence, ...]
    scene: tuple[BehaviorOccurrence, ...]
    chapter: tuple[BehaviorOccurrence, ...]
    recent_chapters: tuple[BehaviorOccurrence, ...]
    volume: tuple[BehaviorOccurrence, ...]
    book: tuple[BehaviorOccurrence, ...]
    ensemble: tuple[BehaviorOccurrence, ...]


def fingerprint_similarity(left: BehaviorFingerprint, right: BehaviorFingerprint) -> float:
    """Return a semantic similarity in ``[0, 1]``.

    Exact unit identity dominates; otherwise the score combines the five
    semantic layers plus a small lexical component.  This is intentionally
    deterministic and does not use an embedding service.
    """

    if left.unit_id and right.unit_id and left.unit_id == right.unit_id:
        return 1.0

    def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
        first, second = set(a), set(b)
        if not first and not second:
            return 0.0
        return len(first & second) / len(first | second)

    semantic = jaccard(left.semantic_groups, right.semantic_groups)
    narrative = jaccard(left.narrative_functions, right.narrative_functions)
    channel = 1.0 if left.channel == right.channel else 0.0
    syntax = _syntax_similarity(left.syntax_features, right.syntax_features)
    lexical = jaccard(left.lexical_lemmas, right.lexical_lemmas)
    return min(1.0, 0.38 * semantic + 0.22 * narrative + 0.15 * channel + 0.15 * syntax + 0.10 * lexical)


def _syntax_similarity(left: SyntaxFeatures, right: SyntaxFeatures) -> float:
    if (
        left.subject_opening == right.subject_opening == "unknown"
        and left.temporal_shape == right.temporal_shape == "unknown"
        and left.dialogue_position == right.dialogue_position == "unknown"
        and not left.reset_pattern
        and not right.reset_pattern
    ):
        return 0.0
    features = (
        left.subject_opening == right.subject_opening,
        left.temporal_shape == right.temporal_shape,
        left.reset_pattern == right.reset_pattern,
        left.dialogue_position == right.dialogue_position,
    )
    return sum(features) / len(features)


def _as_fingerprint(candidate: object, actor_id: str | None = None) -> BehaviorFingerprint:
    if isinstance(candidate, BehaviorFingerprint):
        return candidate
    if isinstance(candidate, BehaviorOccurrence):
        return candidate.fingerprint
    if isinstance(candidate, CandidateBehavior):
        groups = candidate.semantic_groups or frozenset({candidate.unit_id})
        return BehaviorFingerprint(
            unit_id=candidate.unit_id,
            semantic_groups=groups,
            channel=candidate.channel or "unknown",
            narrative_functions=frozenset({candidate.purpose}),
            actor_id=actor_id or "char.unknown",
        )
    if isinstance(candidate, PerformanceUnit):
        lemmas: list[str] = []
        for value in candidate.render_hints.values():
            if isinstance(value, str):
                lemmas.extend(value.split())
            elif isinstance(value, (list, tuple)):
                lemmas.extend(str(item) for item in value)
        return BehaviorFingerprint(
            unit_id=candidate.id,
            semantic_groups=candidate.semantic_groups,
            channel=candidate.channel,
            narrative_functions=frozenset({candidate.repeat_group}),
            actor_id=actor_id or "char.unknown",
            visibility=candidate.visibility,
            lexical_lemmas=tuple(lemmas),
        )
    if isinstance(candidate, str):
        return BehaviorFingerprint(
            unit_id=candidate,
            semantic_groups=frozenset({candidate}),
            channel="unknown",
            narrative_functions=frozenset({candidate}),
            actor_id=actor_id or "char.unknown",
        )
    # Adapters can pass a small object from another package as long as it has
    # the fingerprint fields.  Validate the normalized result at this seam.
    return BehaviorFingerprint(
        unit_id=getattr(candidate, "unit_id", None),
        semantic_groups=frozenset(getattr(candidate, "semantic_groups", ())) or frozenset({"unknown"}),
        channel=getattr(candidate, "channel", "unknown"),
        narrative_functions=frozenset(getattr(candidate, "narrative_functions", ())) or frozenset({"unknown"}),
        actor_id=actor_id or getattr(candidate, "actor_id", "char.unknown"),
        syntax_features=getattr(candidate, "syntax_features", SyntaxFeatures()),
        lexical_lemmas=tuple(getattr(candidate, "lexical_lemmas", ())),
    )


class RepetitionPolicy:
    """Score candidates against all seven memory windows."""

    def __init__(
        self,
        config: RepetitionWindowConfig | None = None,
        weights: RepetitionWeights | None = None,
        *,
        window_limits: RepetitionWindowConfig | object | None = None,
        window_sizes: Mapping[str, int] | None = None,
        block_threshold: float = 5.0,
    ) -> None:
        if block_threshold < 0:
            raise ValueError("block_threshold must be non-negative")
        supplied = config or window_limits
        if supplied is None:
            self.config = RepetitionWindowConfig(**(window_sizes or {}))
        elif isinstance(supplied, RepetitionWindowConfig):
            self.config = supplied
        else:
            names = ("immediate", "scene", "chapter", "recent_chapters", "volume", "book", "ensemble")
            values = {name: getattr(supplied, name) for name in names if hasattr(supplied, name)}
            values.update(window_sizes or {})
            self.config = RepetitionWindowConfig(**values)
        self.weights = weights or RepetitionWeights()
        self.block_threshold = block_threshold

    def score(
        self,
        candidate: object,
        history: BehaviorMemorySnapshot | Mapping[str, Sequence[BehaviorOccurrence]] | Sequence[BehaviorOccurrence],
        *,
        position: object | None = None,
        current_position: object | None = None,
        identity: BehaviorIdentity | None = None,
        actor_id: str | None = None,
        continuity_necessary: bool = False,
        continuity: bool | None = None,
        continuity_required: bool | None = None,
        signature_override: bool = False,
    ) -> RepetitionScore:
        if current_position is not None:
            position = current_position
        if continuity_required is not None:
            continuity_necessary = continuity_required
        if continuity is not None:
            continuity_necessary = continuity
        fingerprint = _as_fingerprint(candidate, actor_id)
        windows = self._bounded_windows(self._windows(history))
        current_beat = getattr(position, "global_beat_index", None)
        current_chapter = getattr(position, "chapter_id", None)
        current_volume = getattr(position, "volume_id", None)
        current_scene = getattr(position, "scene_id", None)
        immediate = self._take(windows.immediate, self.config.immediate)
        exact_recent = self._take(immediate, self.config.exact_horizon)
        exact_count = sum(self._same_unit(fingerprint, item.fingerprint) for item in exact_recent)
        semantic_count_chapter = sum(
            bool(fingerprint.semantic_groups & item.fingerprint.semantic_groups)
            for item in self._take(windows.chapter, self.config.chapter or len(windows.chapter))
        )
        syntax_count_chapter = sum(
            _syntax_similarity(fingerprint.syntax_features, item.fingerprint.syntax_features) >= 0.75
            for item in self._take(windows.chapter, self.config.chapter or len(windows.chapter))
        )
        exact_penalty = self.weights.exact_unit * min(1.0, exact_count / max(1, self.config.exact_horizon))
        semantic_penalty = self.weights.semantic_group * self._semantic_penalty(fingerprint, windows, current_beat)
        narrative_penalty = self.weights.narrative_function * self._function_penalty(
            fingerprint, windows, current_chapter
        )
        channel_penalty = self.weights.channel_saturation * self._channel_penalty(fingerprint, windows)
        syntax_penalty = self.weights.syntax_pattern * min(1.0, syntax_count_chapter / max(1, self.config.chapter_syntax_limit))
        lexical_penalty = self.weights.lexical_echo * self._lexical_penalty(
            fingerprint, windows, current_beat
        )
        ensemble_penalty = self.weights.ensemble_collision * self._ensemble_penalty(
            fingerprint, windows.ensemble
        )
        trope_penalty = self.weights.trope_frequency * self._trope_penalty(fingerprint, windows.book)
        signature_permission = self._signature_permission(
            fingerprint, identity, windows, current_chapter, current_volume, signature_override
        )
        raw_penalty = (
            exact_penalty
            + semantic_penalty
            + narrative_penalty
            + channel_penalty
            + syntax_penalty
            + lexical_penalty
            + ensemble_penalty
            + trope_penalty
        )
        # A continuing walk, held-object action, or maintained pose is not a
        # fresh expressive choice.  The exception removes repetition cost but
        # remains visible in the explanation for callers and reports.
        continuity_credit = raw_penalty if continuity_necessary else 0.0
        total = max(
            0.0,
            raw_penalty - signature_permission - continuity_credit,
        )
        reasons: list[str] = []
        hard_block = False
        if exact_count and not continuity_necessary:
            hard_block = True
            reasons.append("EXACT_UNIT_WITHIN_IMMEDIATE_HORIZON")
        if semantic_count_chapter >= self.config.chapter_semantic_limit and not continuity_necessary:
            hard_block = True
            reasons.append("SEMANTIC_GROUP_CHAPTER_LIMIT")
        if syntax_count_chapter >= self.config.chapter_syntax_limit and not continuity_necessary:
            reasons.append("SYNTAX_PATTERN_CHAPTER_LIMIT")
        if self._function_penalty(fingerprint, windows, current_chapter) >= 0.75:
            reasons.append("CROSS_CHAPTER_FUNCTION_CHANNEL_REPEAT")
        if ensemble_penalty > self.weights.ensemble_collision * 0.5:
            reasons.append("ENSEMBLE_COLLISION")
        if signature_permission:
            reasons.append("SIGNATURE_COOLDOWN_SATISFIED")
        if continuity_necessary:
            reasons.append("CONTINUITY_EXCEPTION")
        if not reasons:
            reasons.append("NO_SIGNIFICANT_REPEAT")
        return RepetitionScore(
            unit_id=fingerprint.unit_id,
            total_penalty=total,
            exact_unit_penalty=exact_penalty,
            semantic_group_penalty=semantic_penalty,
            narrative_function_penalty=narrative_penalty,
            channel_saturation_penalty=channel_penalty,
            syntax_pattern_penalty=syntax_penalty,
            lexical_echo_penalty=lexical_penalty,
            ensemble_collision_penalty=ensemble_penalty,
            trope_frequency_penalty=trope_penalty,
            signature_permission=signature_permission,
            continuity_necessity=continuity_credit,
            hard_block=hard_block,
            reasons=tuple(dict.fromkeys(reasons)),
            counts={
                "exact_recent": exact_count,
                "semantic_chapter": semantic_count_chapter,
                "syntax_chapter": syntax_count_chapter,
            },
        )

    score_candidate = score
    calculate_penalty = score
    penalty_for = score

    def rank(
        self,
        candidates: Iterable[object],
        history: BehaviorMemorySnapshot | Mapping[str, Sequence[BehaviorOccurrence]] | Sequence[BehaviorOccurrence],
        **kwargs: object,
    ) -> tuple[tuple[object, RepetitionScore], ...]:
        values = [(candidate, self.score(candidate, history, **kwargs)) for candidate in candidates]
        return tuple(sorted(values, key=lambda item: (item[1].hard_block, item[1].total_penalty, str(item[1].unit_id))))

    def evaluate(self, candidate: object, history: object, **kwargs: object) -> RepetitionScore:
        return self.score(candidate, history, **kwargs)

    def blocked(self, candidate: object, history: object, **kwargs: object) -> bool:
        return self.score(candidate, history, **kwargs).hard_block

    def disabled_units(self, candidates: Iterable[object], history: object, **kwargs: object) -> frozenset[str]:
        return frozenset(
            score.unit_id
            for _, score in self.rank(candidates, history, **kwargs)
            if score.hard_block and score.unit_id
        )

    disabled_set = disabled_units
    blocked_units = disabled_units

    def report(
        self,
        history: BehaviorMemorySnapshot | Mapping[str, Sequence[BehaviorOccurrence]] | Sequence[BehaviorOccurrence],
        *,
        actor_id: str | None = None,
        book_id: str | None = None,
    ) -> BehaviorStatisticsReport:
        windows = self._bounded_windows(self._windows(history))
        occurrences = list(windows.book)
        if actor_id:
            occurrences = [item for item in occurrences if item.actor_id == actor_id]
        if book_id:
            occurrences = [item for item in occurrences if item.book_id == book_id]
        by_unit: Counter[str] = Counter()
        by_group: Counter[str] = Counter()
        by_function: Counter[str] = Counter()
        by_channel: Counter[str] = Counter()
        by_syntax: Counter[str] = Counter()
        by_actor: Counter[str] = Counter()
        by_chapter: Counter[str] = Counter()
        for occurrence in occurrences:
            fp = occurrence.fingerprint
            by_unit[fp.unit_id or "<unmatched>"] += 1
            by_group.update(fp.semantic_groups)
            by_function.update(fp.narrative_functions)
            by_channel[fp.channel] += 1
            by_actor[occurrence.actor_id] += 1
            by_chapter[occurrence.position.chapter_id] += 1
            by_syntax.update(
                {
                    f"subject_opening:{fp.syntax_features.subject_opening}",
                    f"temporal_shape:{fp.syntax_features.temporal_shape}",
                    f"reset_pattern:{fp.syntax_features.reset_pattern}",
                }
            )
        tropes = tuple(group for group, count in by_group.most_common() if count >= 3)
        return BehaviorStatisticsReport(
            total_occurrences=len(occurrences),
            by_unit=dict(by_unit),
            by_semantic_group=dict(by_group),
            by_narrative_function=dict(by_function),
            by_channel=dict(by_channel),
            by_syntax_feature=dict(by_syntax),
            by_actor=dict(by_actor),
            chapter_repeat_hotspots=dict(by_chapter),
            trope_groups=tropes,
        )

    statistics = report
    report_statistics = report

    @staticmethod
    def _windows(history: object) -> _Windows:
        if isinstance(history, BehaviorMemorySnapshot):
            return _Windows(history.immediate, history.scene, history.chapter, history.recent_chapters, history.volume, history.book, history.ensemble)
        if all(hasattr(history, name) for name in ("immediate", "scene", "chapter", "recent_chapters", "volume", "book", "ensemble")):
            return _Windows(
                tuple(history.immediate), tuple(history.scene), tuple(history.chapter),
                tuple(history.recent_chapters), tuple(history.volume), tuple(history.book), tuple(history.ensemble),
            )
        if isinstance(history, Mapping):
            return _Windows(
                tuple(history.get("immediate", ())), tuple(history.get("scene", ())), tuple(history.get("chapter", ())),
                tuple(history.get("recent_chapters", ())), tuple(history.get("volume", ())), tuple(history.get("book", ())), tuple(history.get("ensemble", ())),
            )
        values = tuple(history or ())
        return _Windows(values, values, values, values, values, values, values)

    def _bounded_windows(self, windows: _Windows) -> _Windows:
        return _Windows(
            self._take(windows.immediate, self.config.immediate),
            self._take(windows.scene, self.config.scene),
            self._take(windows.chapter, self.config.chapter),
            self._take_recent_chapters(windows.recent_chapters),
            self._take(windows.volume, self.config.volume),
            self._take(windows.book, self.config.book),
            self._take(windows.ensemble, self.config.ensemble),
        )

    def _take_recent_chapters(
        self, values: Sequence[BehaviorOccurrence]
    ) -> tuple[BehaviorOccurrence, ...]:
        selected: list[str] = []
        for item in reversed(values):
            chapter = item.position.chapter_id
            if chapter not in selected:
                selected.append(chapter)
            if len(selected) == self.config.recent_chapters:
                break
        permitted = set(selected)
        return tuple(item for item in values if item.position.chapter_id in permitted)

    @staticmethod
    def _take(values: Sequence[BehaviorOccurrence], limit: int | None) -> tuple[BehaviorOccurrence, ...]:
        return tuple(values[-limit:] if limit else values)

    @staticmethod
    def _same_unit(candidate: BehaviorFingerprint, previous: BehaviorFingerprint) -> bool:
        return bool(candidate.unit_id and previous.unit_id and candidate.unit_id == previous.unit_id)

    def _decay(self, occurrence: BehaviorOccurrence, current_beat: int | None) -> float:
        if current_beat is None:
            return 1.0
        age = max(0, current_beat - occurrence.position.global_beat_index)
        return exp(-age / self.config.half_life_beats)

    def _semantic_penalty(self, candidate: BehaviorFingerprint, windows: _Windows, current_beat: int | None) -> float:
        maximum = 0.0
        for window, weight in ((windows.immediate, 1.0), (windows.scene, 0.8), (windows.chapter, 0.75), (windows.recent_chapters, 0.9), (windows.volume, 0.45), (windows.book, 0.20)):
            value = sum(bool(candidate.semantic_groups & item.fingerprint.semantic_groups) * self._decay(item, current_beat) for item in window)
            maximum = max(maximum, min(1.0, value * weight / 2.0))
        return maximum

    def _function_penalty(
        self,
        candidate: BehaviorFingerprint,
        windows: _Windows,
        current_chapter: str | None,
    ) -> float:
        if not candidate.narrative_functions:
            return 0.0
        matches = 0.0
        chapter_order = self._chapter_order(windows.recent_chapters)
        current_number = _chapter_number(current_chapter)
        for item in windows.recent_chapters:
            if not (
                candidate.narrative_functions & item.fingerprint.narrative_functions
                and candidate.channel == item.fingerprint.channel
                and (current_chapter is None or item.position.chapter_id != current_chapter)
            ):
                continue
            previous_number = _chapter_number(item.position.chapter_id)
            if current_number is not None and previous_number is not None:
                distance = max(1, current_number - previous_number)
            else:
                distance = max(1, chapter_order.get(item.position.chapter_id, 1))
            matches += exp(-distance / self.config.half_life_chapters)
        return min(1.0, matches / 2.0)

    @staticmethod
    def _channel_penalty(candidate: BehaviorFingerprint, windows: _Windows) -> float:
        recent = windows.chapter[-3:]
        if not recent:
            return 0.0
        return min(1.0, sum(item.fingerprint.channel == candidate.channel for item in recent) / 3.0)

    def _lexical_penalty(self, candidate: BehaviorFingerprint, windows: _Windows, current_beat: int | None) -> float:
        if not candidate.lexical_lemmas:
            return 0.0
        candidate_lemmas = set(candidate.lexical_lemmas)
        echoes: list[float] = []
        for item in windows.book:
            previous = set(item.fingerprint.lexical_lemmas)
            if not previous:
                continue
            overlap = len(candidate_lemmas & previous) / len(candidate_lemmas | previous)
            echoes.append(overlap * self._decay(item, current_beat))
        return min(1.0, max(echoes, default=0.0))

    @staticmethod
    def _ensemble_penalty(candidate: BehaviorFingerprint, ensemble: Sequence[BehaviorOccurrence]) -> float:
        collisions = sum(
            bool(candidate.semantic_groups & item.fingerprint.semantic_groups)
            for item in ensemble
            if item.actor_id != candidate.actor_id
        )
        return min(1.0, collisions / 2.0)

    @staticmethod
    def _chapter_order(history: Sequence[BehaviorOccurrence]) -> dict[str, int]:
        chapters: list[str] = []
        for item in reversed(history):
            if item.position.chapter_id not in chapters:
                chapters.append(item.position.chapter_id)
        return {chapter: index + 1 for index, chapter in enumerate(chapters)}

    @staticmethod
    def _trope_penalty(candidate: BehaviorFingerprint, book: Sequence[BehaviorOccurrence]) -> float:
        if not book or not candidate.semantic_groups:
            return 0.0
        counts = sum(bool(candidate.semantic_groups & item.fingerprint.semantic_groups) for item in book)
        return min(1.0, counts / max(1.0, len(book) * 0.20))

    def _signature_permission(
        self,
        candidate: BehaviorFingerprint,
        identity: BehaviorIdentity | None,
        windows: _Windows,
        current_chapter: str | None,
        current_volume: str | None,
        override: bool,
    ) -> float:
        if identity is None and not override:
            return 0.0
        for signature in (identity.signature_families if identity else ()):
            if signature.semantic_group not in candidate.semantic_groups:
                continue
            volume_count = sum(
                signature.semantic_group in item.fingerprint.semantic_groups
                and (current_volume is None or item.position.volume_id == current_volume)
                for item in windows.volume
            )
            if override or (volume_count < signature.maximum_per_volume and self._chapter_gap(current_chapter, windows.book) >= signature.cooldown_chapters):
                return signature.affinity * 0.5
        return 0.0

    @staticmethod
    def _chapter_gap(current_chapter: str | None, history: Sequence[BehaviorOccurrence]) -> int:
        if not history:
            return 999
        chapters: list[str] = []
        for item in reversed(history):
            chapter = item.position.chapter_id
            if chapter not in chapters:
                chapters.append(chapter)
            if len(chapters) >= 20:
                break
        if current_chapter is None or current_chapter not in chapters:
            # Chapter identifiers in callers are commonly ``chapter.0017``.
            # Use their ordinal when available; otherwise fall back to the
            # number of distinct historical chapters.
            current_number = _chapter_number(current_chapter)
            historical_numbers = [_chapter_number(chapter) for chapter in chapters]
            if current_number is not None and historical_numbers and all(number is not None for number in historical_numbers):
                return max(0, current_number - max(number for number in historical_numbers if number is not None))
            return len(chapters)
        return chapters.index(current_chapter)


def _chapter_number(chapter_id: str | None) -> int | None:
    if not chapter_id:
        return None
    match = re.search(r"(?:^|[._-])(\d+)$", chapter_id)
    return int(match.group(1)) if match else None


MultiWindowRepetitionPolicy = RepetitionPolicy
RepetitionEngine = RepetitionPolicy
WindowedRepetitionPolicy = RepetitionPolicy
RepetitionConfig = RepetitionWindowConfig

__all__ = [
    "BehaviorStatisticsReport",
    "CandidateRepetition",
    "MultiWindowRepetitionPolicy",
    "WindowedRepetitionPolicy",
    "RepetitionEngine",
    "RepetitionConfig",
    "RepetitionPolicy",
    "RepetitionScore",
    "RepetitionWeights",
    "RepetitionWindowConfig",
    "fingerprint_similarity",
]
