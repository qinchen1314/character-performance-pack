from pathlib import Path

import pytest

from character_performance.domain.models import VAD
from character_performance.ontology.emotion import EmotionOntology, UnknownEmotionError


ONTOLOGY = Path(__file__).parents[1] / "fixtures" / "emotions.yaml"


def test_resolve_returns_canonical_emotion_with_family_and_vad() -> None:
    ontology = EmotionOntology.from_yaml(ONTOLOGY)

    anger = ontology.resolve("anger")

    assert anger.id == "anger"
    assert "conflict" in anger.families
    assert anger.prototype_vad == VAD(
        valence=-0.65, arousal=0.70, dominance=0.55
    )


def test_alias_resolves_without_duplicating_the_emotion() -> None:
    ontology = EmotionOntology.from_yaml(ONTOLOGY)

    assert ontology.resolve("恼怒").id == "anger"
    assert len(ontology) == 3


def test_unknown_emotion_fails_explicitly() -> None:
    ontology = EmotionOntology.from_yaml(ONTOLOGY)

    with pytest.raises(UnknownEmotionError, match="not registered"):
        ontology.resolve("schadenfreude")
