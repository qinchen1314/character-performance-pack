import pytest
from pydantic import ValidationError

from character_performance.domain.models import (
    Appraisal,
    CharacterProfile,
    EmotionState,
    PerformanceRequest,
    PerformanceUnit,
    PhysicalState,
    RelationshipState,
    SceneState,
    VAD,
)


def test_emotion_state_keeps_labels_and_continuous_vad_together() -> None:
    state = EmotionState(
        primary="anger",
        secondary="disappointment",
        families={"conflict", "relational"},
        intensity=0.68,
        vad=VAD(valence=-0.74, arousal=0.61, dominance=0.72),
        restraint=0.87,
        awareness=0.76,
        duration_ms=48_000,
        decay_half_life_ms=90_000,
        trigger_refs=("event.public_humiliation",),
        appraisal=Appraisal(
            goal_congruence=-0.9,
            controllability=0.7,
            responsibility="target",
            certainty=0.85,
        ),
    )

    assert state.primary == "anger"
    assert state.vad.dominance == 0.72


def test_emotion_state_rejects_out_of_range_vad() -> None:
    with pytest.raises(ValidationError):
        VAD(valence=-1.01, arousal=0.2, dominance=0.1)


def test_performance_unit_requires_traceable_source_and_nonempty_semantics() -> None:
    with pytest.raises(ValidationError):
        PerformanceUnit(
            id="body.hand_clench",
            category="body",
            channel="hands",
            atomic_action="hand_clench",
            semantic_groups={"hand_tension"},
            semantics={},
            intensity_range={"min": 0.25, "max": 0.85},
            visibility="subtle",
            narrative_weight=0.62,
            repeat_group="hand_tension",
            source_refs=(),
            license_class="original",
        )


def test_performance_request_round_trips_through_canonical_schema() -> None:
    request = PerformanceRequest(
        request_id="req.001",
        character=CharacterProfile(id="char.luo_han"),
        relationship=RelationshipState(
            subject_id="char.luo_han", target_id="char.enemy"
        ),
        physical_state=PhysicalState(),
        scene_state=SceneState(scene_id="scene.001", turn_index=1),
        seed=938102,
    )

    restored = PerformanceRequest.model_validate_json(request.model_dump_json())

    assert restored == request


def test_unknown_enum_value_is_representable_without_accepting_arbitrary_values() -> None:
    unit = PerformanceUnit(
        id="world.unknown_signal",
        category="unknown",
        channel="unknown",
        atomic_action="unknown_signal",
        semantic_groups={"unknown_signal"},
        semantics={"ambiguity": 1.0},
        intensity_range={"min": 0.0, "max": 0.0},
        visibility="unknown",
        narrative_weight=0.0,
        repeat_group="unknown_signal",
        source_refs=("src.original.core.v1",),
        license_class="original",
        status="unknown",
    )

    assert unit.category == "unknown"
