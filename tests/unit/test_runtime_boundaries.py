import json

import pytest

from character_performance.continuity import physical_errors
from character_performance.domain.models import EmotionState, PhysicalState, RenderContext, RenderResult, VAD
from character_performance.engine import PerformanceEngine
from character_performance.ontology.pack import PerformancePack
from character_performance.renderer import ConstrainedLLMRenderer
from character_performance.world import apply_world, validate_world
from character_performance.domain.models import CharacterProfile, Director, WorldState


@pytest.mark.parametrize("field,value", [
    ("effects", {"pose": "flying"}),
    ("effects", {"transfer": "sideways"}),
    ("effects", {"distance_delta": 50}),
    ("effects", {"pose": None}),
    ("physical_requirements", {"min_mobility": "broken"}),
    ("physical_requirements", {"min_breath": -1}),
    ("physical_requirements", {"capabilities": "walking"}),
    ("world_requirements", {"min_realm": "golden_core", "cost": -1}),
    ("render_hints", {"subject": 5, "verb": []}),
])
def test_invalid_rule_values_fail_pack_validation(pack, field, value):
    units = list(pack.all())
    units[0] = units[0].model_copy(update={field: value})
    with pytest.raises(ValueError, match="invalid rule values"):
        PerformancePack(pack.ontology, tuple(units), pack.source_ids)


def test_state_effects_cannot_omit_required_facts(pack):
    units = list(pack.all())
    unit = pack.get("spatial.step_closer").model_copy(update={"preconditions": ()})
    units = [unit if u.id == unit.id else u for u in units]
    with pytest.raises(ValueError, match="lacks preconditions"):
        PerformancePack(pack.ontology, tuple(units), pack.source_ids)


def test_custom_renderer_cannot_self_certify_invented_text(pack, request_data):
    class BadRenderer:
        def render(self, plan, context):
            return RenderResult(text="他飞到屋顶，拔出长剑。", realized_units={key: "anything" for key in plan.unit_ids})
    engine = PerformanceEngine(pack)
    plan = engine.plan(request_data)
    with pytest.raises(ValueError, match="FACT_VIOLATION"):
        engine.render(plan, renderer=BadRenderer())
    with pytest.raises(ValueError, match="RENDER_REQUIRED"):
        engine.commit(plan.plan_id, 0)


def test_severe_knee_injury_prevents_weight_bearing_actions(pack, request_data):
    request = request_data.model_copy(update={"physical_state": PhysicalState(injuries=[dict(body_part="left_knee", severity=1, constraints=["no_weight_bearing"])])})
    for unit_id in ("spatial.step_closer", "spatial.step_back", "spatial.stand_up", "body.weight_shift"):
        assert "injury:left_knee" in physical_errors(pack.get(unit_id), request)


def test_vad_changes_scoring_with_fixed_discrete_emotion(pack, request_data):
    engine = PerformanceEngine(pack)
    first = engine.plan(request_data)
    emotion = request_data.emotion_state.model_copy(update={"vad": VAD(valence=-.65, arousal=-.6, dominance=.55)})
    second = engine.plan(request_data.model_copy(update={"emotion_state": emotion}))
    assert first.scores["body.hand_clench"]["vad"] != second.scores["body.hand_clench"]["vad"]
    assert first.scores["speech.pace_slow"]["vad"] > first.scores["body.hand_clench"]["vad"] or second.scores["speech.pace_slow"]["vad"] > second.scores["body.hand_clench"]["vad"]


def test_constrained_model_can_choose_approved_variation(pack, request_data):
    class ValidModel:
        def choose(self, payload):
            return json.dumps({"choices": {key: len(options) - 1 for key, options in payload["allowed_realizations"].items()}})
    engine = PerformanceEngine(pack)
    plan = engine.plan(request_data)
    result = engine.render(plan, renderer=ConstrainedLLMRenderer(pack, ValidModel()))
    assert not result.warnings
    assert set(result.realized_units) == set(plan.unit_ids)


def test_target_substitution_covers_verb_and_complement(pack, request_data):
    request = request_data.model_copy(update={"director": request_data.director.model_copy(update={"disabled_units": frozenset(u.id for u in pack.all() if u.id != "spatial.step_closer")})})
    engine = PerformanceEngine(pack)
    plan = engine.plan(request)
    result = engine.render(plan, RenderContext(subject_name="洛寒", target_name="师尊"))
    assert "spatial.step_closer" in plan.unit_ids
    assert "师尊" in result.text and "对方" not in result.text


def test_world_retraction_requires_prior_activation(pack, request_data):
    world = WorldState(genre="xianxia", realm="golden_core")
    request = request_data.model_copy(update={"director": Director(allow_world=True), "world_state": world,
        "character": CharacterProfile(id="char.hero", capabilities={"spiritual_sense"})})
    retract = pack.get("world.sense_retract")
    assert "world.active_state" in validate_world(retract, request, request.emotion_state, world)[0]
    activated = apply_world(pack.get("world.sense_focus"), world)
    assert "spiritual_sense" in activated.active_capabilities
    assert not validate_world(retract, request, request.emotion_state, activated)[0]
    assert "spiritual_sense" not in apply_world(retract, activated).active_capabilities


def test_two_valid_renderers_can_change_wording_without_changing_actions(pack, request_data):
    class AlternativeModel:
        def choose(self, payload):
            return json.dumps({"choices": {key: len(value) - 1 for key, value in payload["allowed_realizations"].items()}})
    emotion = request_data.emotion_state.model_copy(update={"restraint": .95})
    director = request_data.director.model_copy(update={"disabled_units": frozenset(u.id for u in pack.all() if u.id != "gaze.gaze_steady")})
    engine = PerformanceEngine(pack)
    plan = engine.plan(request_data.model_copy(update={"emotion_state": emotion, "director": director}))
    a = engine.render(plan)
    b = engine.render(plan, renderer=ConstrainedLLMRenderer(pack, AlternativeModel()))
    assert a.text != b.text
    assert set(a.realized_units) == set(b.realized_units) == set(plan.unit_ids)
    assert engine.validate(plan).valid
