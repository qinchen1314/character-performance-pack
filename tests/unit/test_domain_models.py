import pytest
from pydantic import ValidationError

from character_performance.domain.models import (
    EmotionState,
    PerformanceUnit,
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

