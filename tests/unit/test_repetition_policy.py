from __future__ import annotations

from character_performance.domain.behavior_models import (
    BehaviorFingerprint,
    BehaviorOccurrence,
    BehaviorIdentity,
    NarrativePosition,
    SignatureFamily,
    TextSpan,
)
from character_performance.memory.repository import BehaviorMemorySnapshot
from character_performance.repetition import RepetitionPolicy, RepetitionWindowConfig, fingerprint_similarity


def _occurrence(index: int, *, group: str = "hand_tension", unit: str = "body.hand_clench", chapter: str = "chapter.1", channel: str = "hands") -> BehaviorOccurrence:
    position = NarrativePosition(
        book_id="book.demo", volume_id="volume.1", chapter_id=chapter,
        scene_id=f"scene.{chapter}", paragraph_index=0, beat_index=index,
        global_beat_index=index,
    )
    fingerprint = BehaviorFingerprint(
        unit_id=unit, semantic_groups=frozenset({group}), channel=channel,
        narrative_functions=frozenset({"anger_leak"}), actor_id="char.a",
    )
    return BehaviorOccurrence(
        occurrence_id=f"occ.{index}", book_id="book.demo", position=position,
        actor_id="char.a", fingerprint=fingerprint, source="extracted",
        text_span=TextSpan(start=0, end=2, text="他。"), confidence=0.9,
        generation_run_id=f"run.{index}", accepted_revision=1,
    )


def _snapshot(*occurrences: BehaviorOccurrence) -> BehaviorMemorySnapshot:
    values = tuple(occurrences)
    return BehaviorMemorySnapshot(
        memory_revision=len(values), immediate=values[-5:], scene=values,
        chapter=values, recent_chapters=values, volume=values, book=values,
        ensemble=values,
    )


def test_exact_unit_is_blocked_but_continuity_is_explicitly_allowed() -> None:
    previous = _occurrence(1)
    candidate = previous.fingerprint
    policy = RepetitionPolicy()
    blocked = policy.score(candidate, _snapshot(previous), position=_occurrence(2).position)
    allowed = policy.score(candidate, _snapshot(previous), position=_occurrence(2).position, continuity_necessary=True)
    assert blocked.hard_block
    assert not allowed.hard_block
    assert allowed.total_penalty == 0
    assert "CONTINUITY_EXCEPTION" in allowed.reasons


def test_candidate_that_would_be_third_chapter_semantic_use_is_blocked() -> None:
    first = _occurrence(1, unit="body.hand_clench")
    second = _occurrence(2, unit="body.nail_palm")
    candidate = _occurrence(3, unit="body.grip_sleeve").fingerprint

    score = RepetitionPolicy().score(
        candidate,
        _snapshot(first, second),
        position=_occurrence(3).position,
    )

    assert score.hard_block
    assert "SEMANTIC_GROUP_CHAPTER_LIMIT" in score.reasons


def test_ensemble_collision_ignores_same_actor_and_penalizes_other_actor() -> None:
    candidate = _occurrence(3).fingerprint
    same_actor = _occurrence(1)
    other_actor = _occurrence(2).model_copy(
        update={
            "actor_id": "char.b",
            "fingerprint": _occurrence(2).fingerprint.model_copy(
                update={"actor_id": "char.b"}
            ),
        }
    )
    same_snapshot = BehaviorMemorySnapshot(
        memory_revision=1,
        immediate=(), scene=(), chapter=(), recent_chapters=(), volume=(), book=(),
        ensemble=(same_actor,),
    )
    other_snapshot = same_snapshot.__class__(
        memory_revision=1,
        immediate=(), scene=(), chapter=(), recent_chapters=(), volume=(), book=(),
        ensemble=(other_actor,),
    )

    assert RepetitionPolicy().score(candidate, same_snapshot).ensemble_collision_penalty == 0
    assert RepetitionPolicy().score(candidate, other_snapshot).ensemble_collision_penalty > 0


def test_semantic_similarity_detects_paraphrase_and_signature_cooldown() -> None:
    left = _occurrence(1).fingerprint
    right = _occurrence(2, unit="body.nail_palm", group="hand_tension").fingerprint
    assert fingerprint_similarity(left, right) >= 0.38
    old = _occurrence(1, chapter="chapter.1")
    identity = BehaviorIdentity(
        character_id="char.a", version=1,
        default_strategies={"conflict": "observe"},
        preferred_channels={"hands": 0.2}, values=frozenset({"control"}),
        taboos=frozenset(), coping_strategies=frozenset({"observe"}),
        social_masks={"public": "public", "private": "private", "intimate": "intimate"},
        signature_families=(SignatureFamily(semantic_group="hand_tension", affinity=0.8, cooldown_chapters=2, maximum_per_volume=8),),
    )
    current = old.position.model_copy(update={"chapter_id": "chapter.4", "scene_id": "scene.4", "global_beat_index": 20})
    score = RepetitionPolicy().score(right, _snapshot(old), position=current, identity=identity)
    assert score.signature_permission > 0


def test_report_covers_distribution_and_all_window_configuration_is_validated() -> None:
    snapshot = _snapshot(_occurrence(1), _occurrence(2, group="gaze_withdrawal", unit="gaze.pass", channel="gaze"))
    report = RepetitionPolicy(RepetitionWindowConfig(scene=10, chapter=10, volume=10, book=10)).report(snapshot)
    assert report.total_occurrences == 2
    assert report.by_channel["hands"] == 1
    assert "hand_tension" in report.by_semantic_group
