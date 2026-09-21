from pathlib import Path

import pytest

from character_performance.domain.models import CharacterProfile, EmotionState, PerformanceRequest, RelationshipState, SceneState, VAD
from character_performance.ontology.pack import PerformancePack

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="session")
def pack():
    return PerformancePack.from_project(ROOT)


@pytest.fixture
def request_data():
    return PerformanceRequest(request_id="req.test", character=CharacterProfile(id="char.hero"),
        relationship=RelationshipState(subject_id="char.hero", target_id="char.target"),
        emotion_state=EmotionState(primary="anger", intensity=.7,
            vad=VAD(valence=-.65, arousal=.7, dominance=.55), decay_half_life_ms=90000),
        scene_state=SceneState(scene_id="scene.test", pose="standing", position="pos.hall", distances={"char.target": 3.2}), seed=10)
