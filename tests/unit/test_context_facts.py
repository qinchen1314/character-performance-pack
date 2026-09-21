import pytest

from character_performance.domain.models import Context
from character_performance.engine import PerformanceEngine
from character_performance.ontology.pack import PerformancePack


def test_fact_gated_unit_cannot_invent_prop_and_becomes_eligible_with_fact(pack, request_data):
    unit = pack.get("body.palm_open").model_copy(update={"context_requirements": {"required_facts": ["prop.cup.reachable"]}, "conflicts": frozenset(),
        "emotion_affinity": {"anger": .9}})
    subset = PerformancePack(pack.ontology, (unit,), pack.source_ids)
    missing = PerformanceEngine(subset)
    present = PerformanceEngine(subset)
    try:
        blocked = missing.plan(request_data)
        assert not blocked.unit_ids
        assert "fact:prop.cup.reachable" in blocked.suppressed_candidates[unit.id]
        allowed = present.plan(request_data.model_copy(update={"context": Context(facts={"prop.cup.reachable"})}))
        assert allowed.unit_ids == (unit.id,)
        assert present.validate(allowed).valid
    finally:
        missing.repository.close()
        present.repository.close()


def test_unknown_context_requirement_is_rejected(pack):
    unit = pack.get("body.palm_open").model_copy(update={"context_requirements": {"imaginary_fact": True}, "conflicts": frozenset()})
    with pytest.raises(ValueError, match="invalid rule"):
        PerformancePack(pack.ontology, (unit,), pack.source_ids)


@pytest.mark.parametrize("fact", ["held.cup", "held.middle.cup"])
def test_malformed_reserved_held_fact_is_rejected_at_pack_load(pack, fact):
    unit = pack.get("body.palm_open").model_copy(update={"context_requirements": {"required_facts": [fact]}, "conflicts": frozenset()})
    with pytest.raises(ValueError, match="held facts"):
        PerformancePack(pack.ontology, (unit,), pack.source_ids)


def test_declared_held_fact_cannot_override_actual_held_object(pack, request_data):
    from character_performance.continuity import context_errors
    unit = pack.get("body.palm_open").model_copy(update={"context_requirements": {"required_facts": ["held.right.book"]}})
    request = request_data.model_copy(update={"context": Context(facts={"held.right.book"}),
        "scene_state": request_data.scene_state.model_copy(update={"held_objects": {"right_hand": "object.sword"}})})
    assert "held_fact:held.right.book" in context_errors(unit, request)
    request = request.model_copy(update={"scene_state": request.scene_state.model_copy(update={"held_objects": {"right_hand": "object.volume7"}, "object_tags": {"object.volume7": frozenset({"book"})}})})
    assert not context_errors(unit, request)


def test_both_hands_fact_requires_same_object(pack, request_data):
    from character_performance.continuity import context_errors
    unit = pack.get("body.palm_open").model_copy(update={"context_requirements": {"required_facts": ["held.both.tray"]}})
    request = request_data.model_copy(update={"context": Context(facts={"held.both.tray"}),
        "scene_state": request_data.scene_state.model_copy(update={"held_objects": {"left_hand": "object.tray1", "right_hand": "object.tray2"},
            "object_tags": {"object.tray1": frozenset({"tray"}), "object.tray2": frozenset({"tray"})}})})
    assert "held_fact:held.both.tray" in context_errors(unit, request)
