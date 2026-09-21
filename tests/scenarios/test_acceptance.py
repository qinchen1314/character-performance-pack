from collections import Counter
from itertools import combinations

from character_performance.domain.models import (
    CharacterProfile, Director, EmotionState, Masking, Personality, PhysicalState,
    RelationshipState, RenderContext, SceneState, VAD, WorldState,
)
from character_performance.engine import PerformanceEngine
from character_performance.renderer import ChineseNovelRenderer, ConstrainedLLMRenderer
from character_performance.world import validate_world


def test_t1_same_event_different_personalities(pack, request_data):
    profiles = [
        dict(conscientiousness=.95, extraversion=.1, agreeableness=.5, neuroticism=.1),
        dict(conscientiousness=.1, extraversion=.95, agreeableness=.05, neuroticism=.2),
        dict(conscientiousness=.95, extraversion=.7, agreeableness=.65, neuroticism=.05),
        dict(conscientiousness=.2, extraversion=.05, agreeableness=.7, neuroticism=.95),
    ]
    signatures = []
    for traits in profiles:
        character = CharacterProfile(id="char.hero", personality=Personality(big_five=traits))
        plan = PerformanceEngine(pack).plan(request_data.model_copy(update={"character": character}))
        signatures.append({(pack.get(u).channel, group) for u in plan.unit_ids for group in pack.get(u).semantic_groups})
        assert any(abs(plan.scores[u]["personality_modifier"]) > .05 for u in plan.unit_ids)
    average = sum(len(a & b) / len(a | b) for a, b in combinations(signatures, 2)) / 6
    assert average <= .55, (average, signatures)


def test_t2_relationships_change_multiple_dimensions(pack, request_data):
    values = []
    for dominance, intimacy, hostility in [(-.8, .1, 0), (.8, .1, 0), (0, .9, 0), (.2, 0, .9), (0, 0, 0)]:
        relation = RelationshipState(subject_id="char.hero", target_id="char.target", dominance=dominance, intimacy=intimacy, hostility=hostility)
        plan = PerformanceEngine(pack).plan(request_data.model_copy(update={"relationship": relation}))
        first = plan.parameters[plan.primary_signal]
        values.append(tuple(first[key] for key in ("amplitude", "directness", "preferred_distance")))
    assert len(set(values)) >= 4
    assert sum(a != b for a, b in zip(values[0], values[3])) >= 2


def test_t3_high_mask_limits_fear_and_preserves_surface(pack, request_data):
    emotion = EmotionState(primary="fear", intensity=.85, restraint=.95, vad=VAD(valence=-.7, arousal=.7, dominance=-.6), decay_half_life_ms=90000)
    surface_count = 0
    for seed in range(30):
        engine = PerformanceEngine(pack)
        plan = engine.plan(request_data.model_copy(update={"seed": seed, "emotion_state": emotion, "masking": Masking(mask_strength=.95, control_capacity=.9)}))
        assert all(pack.get(u).visibility in {"subtle", "very_subtle"} for u in plan.unit_ids)
        surface_count += bool(plan.surface_signals)
        text = engine.render(plan).text
        assert not any(word in text for word in ("害怕", "恐惧", "强装镇定"))
    assert surface_count / 30 >= .8


def test_t4_twenty_turns_semantic_repetition(pack, request_data):
    engine = PerformanceEngine(pack)
    counts = Counter()
    previous = []
    scene = request_data.scene_state
    total = 0
    for turn in range(20):
        plan = engine.plan(request_data.model_copy(update={"scene_state": scene, "seed": turn, "request_id": f"req.turn.{turn}"}))
        assert not set(plan.unit_ids) & set(u for recent in previous[-3:] for u in recent)
        previous.append(plan.unit_ids)
        counts.update(group for u in plan.unit_ids for group in pack.get(u).semantic_groups)
        total += len(plan.unit_ids)
        engine.render(plan)
        scene = engine.commit(plan.plan_id, scene.revision)
    assert max(counts.values()) <= 4, counts
    assert sum(counts[group] for group in ("brow_tension", "hand_tension", "mouth_change", "gaze_flash", "deep_breath")) / total <= .3


def test_t5_injuries_objects_and_wall_are_preserved(pack, request_data):
    engine = PerformanceEngine(pack)
    scene = SceneState(scene_id="scene.wall", pose="leaning_wall", position="pos.wall", support_contact="wall.north", held_objects={"right_hand": "object.sword"})
    physical = PhysicalState(injuries=[dict(body_part="left_shoulder", severity=.45, constraints=["no_overhead_reach"])])
    for turn in range(8):
        plan = engine.plan(request_data.model_copy(update={"scene_state": scene, "physical_state": physical, "seed": turn}))
        assert "body.hand_clench" not in plan.unit_ids
        assert "body.arms_fold" not in plan.unit_ids
        assert "spatial.sit_down" not in plan.unit_ids
        assert plan.state_transition.after.held_objects == scene.held_objects
        assert plan.state_transition.after.position == "pos.wall"
        engine.render(plan)
        scene = engine.commit(plan.plan_id, scene.revision)


def test_t6_world_realms_and_control(pack, request_data):
    caps = {"qi_control", "aura_control", "spiritual_sense", "intent_control", "pressure_control"}
    sets = []
    for realm in ("qi_refining", "foundation", "golden_core"):
        world = WorldState(genre="xianxia", realm=realm, target_realm="qi_refining")
        request = request_data.model_copy(update={"world_state": world,
            "character": CharacterProfile(id="char.hero", capabilities=caps),
            "director": Director(allow_world=True)})
        eligible = {u.id for u in pack.all() if u.category == "world_specific" and not validate_world(u, request, request.emotion_state, world)[0]}
        sets.append(eligible)
    assert sets[0] < sets[1] < sets[2]
    assert "world.sense_focus" not in sets[0]
    low_control = request.model_copy(update={"physical_state": PhysicalState(pain=.9)})
    assert all(validate_world(u, low_control, request.emotion_state, world)[0] for u in pack.all() if u.category == "world_specific")


def test_t7_replacing_renderer_preserves_plan_and_rejects_invention(pack, request_data):
    class InventingModel:
        def choose(self, payload):
            return '{"text": "他拔出一把剑，击碎了桌子。"}'
    engine = PerformanceEngine(pack)
    plan = engine.plan(request_data)
    before = plan.model_dump_json()
    context = RenderContext(subject_name="洛寒", dialogue="此事到此为止。")
    deterministic = engine.render(plan, context, ChineseNovelRenderer(pack))
    guarded = engine.render(plan, context, ConstrainedLLMRenderer(pack, InventingModel()))
    assert guarded.text == deterministic.text
    assert guarded.warnings and not guarded.introduced_facts
    assert plan.model_dump_json() == before
    assert "此事到此为止。" in guarded.text
