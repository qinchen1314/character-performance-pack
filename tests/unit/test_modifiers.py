import pytest
from pydantic import ValidationError

from character_performance.modifiers import Modifier, active_modifiers, parameter_modifiers, score_modifiers
from character_performance.ontology.pack import PerformancePack


def modifier(id="modifier.test", **kwargs):
    return Modifier(id=id, kind=kwargs.pop("kind", "personality"), when={"personality.extraversion": {"gt": 0}}, **kwargs)


def test_modifier_terms_cannot_override_base_or_repetition_scores(pack):
    terms = score_modifiers((modifier("repetition", effects={"score_add": {}}),), pack.get("body.hand_clench"))
    assert terms == {"modifier:repetition": 0}


def test_modifier_score_is_independent_of_mapping_order(pack):
    terms = {"channel.facial": 1, "semantic.tension": 1e-16, "category.facial": -1}
    a = modifier(effects={"score_add": terms})
    b = modifier(effects={"score_add": dict(reversed(list(terms.items())))})
    assert score_modifiers((a,), pack.get("facial.brow_contract")) == score_modifiers((b,), pack.get("facial.brow_contract"))


def test_modifier_pipeline_order_and_clamps(request_data):
    physical = modifier("modifier.p", kind="physical", effects={"parameter_add": {"amplitude": -.2}})
    personality = modifier("modifier.a", effects={"parameter_add": {"amplitude": 1}})
    active = active_modifiers((physical, personality), request_data)
    assert [m.id for m in active] == ["modifier.a", "modifier.p"]
    assert parameter_modifiers(active, {"amplitude": .8}) == {"amplitude": .8}


@pytest.mark.parametrize("when", [{"character.secret": {"gt": 0}}, {"personality.extraversion": {}}, {"personality.extraversion": {"gt": 1, "lt": 0}}])
def test_invalid_conditions_fail(when):
    with pytest.raises(ValidationError):
        Modifier(id="modifier.bad", kind="personality", when=when, effects={})


def test_unknown_modifier_selector_is_rejected_by_pack(pack):
    invalid = modifier(effects={"score_add": {"channel.invented": 1}})
    with pytest.raises(ValueError, match="unreachable"):
        PerformancePack(pack.ontology, pack.all(), pack.source_ids, (invalid,))
