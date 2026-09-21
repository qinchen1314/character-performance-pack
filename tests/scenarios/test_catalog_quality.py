"""Expansion gates exercise executable records, not just YAML row counts."""
from collections import Counter
import json
from pathlib import Path

import pytest

from character_performance.continuity import context_errors, physical_errors, precondition_errors
from character_performance.domain.models import Context, Director, EmotionState, PhysicalState
from character_performance.engine import PerformanceEngine
from character_performance.modifiers import active_modifiers, score_modifiers
from character_performance.ontology.pack import PerformancePack, digest
from character_performance.quality import catalog_report, witness_request
from character_performance.world import validate_world

ROOT = Path(__file__).parents[2]


def test_all_ten_catalog_targets_and_low_textual_duplication(pack):
    report = catalog_report(pack)
    assert all(report["quantity_gates"].values()), report["actual"]
    assert not report["exact_duplicate_pairs"], report["exact_duplicate_pairs"]
    assert report["near_duplicate_unit_fraction"] <= .05, report["near_duplicate_pairs"]
    for label, coverage in report["emotion_coverage"].items():
        assert coverage["candidates"] >= 3 and len(coverage["channels"]) >= 2, (label, coverage)


@pytest.mark.parametrize("category", ["body", "facial", "gaze", "micro_expression", "spatial", "physiology", "speech", "world_specific"])
def test_each_authored_unit_has_an_executable_witness(pack, category):
    for unit in pack.all():
        if unit.status != "active" or unit.category != category or "src.original.catalog.v1" not in unit.source_refs:
            continue
        request = witness_request(unit, pack)
        assert not context_errors(unit, request), unit.id
        assert not physical_errors(unit, request), unit.id
        assert not precondition_errors(unit, request.scene_state, request.relationship.target_id), unit.id
        assert not validate_world(unit, request, request.emotion_state, request.world_state)[0], unit.id
        # Isolate retrieval to prove this unit actually executes; full-pack
        # competition and anti-repetition are exercised by separate scenarios.
        isolated = unit.model_copy(update={"conflicts": frozenset(), "compatible_with": frozenset()})
        engine = PerformanceEngine(PerformancePack(pack.ontology, (isolated,), pack.source_ids))
        try:
            plan = engine.plan(request)
            assert unit.id in plan.unit_ids, (unit.id, plan.suppressed_candidates)
            rendered = engine.render(plan)
            assert rendered.realized_units[unit.id]
            state = engine.commit(plan.plan_id, 0)
            assert state.revision == 1
            assert state.held_objects == request.scene_state.held_objects or unit.effects.get("transfer")
        finally:
            engine.repository.close()


def test_every_required_fact_is_enforced_and_no_world_units_escape_general_genre(pack):
    for unit in pack.all():
        if "src.original.catalog.v1" not in unit.source_refs:
            continue
        request = witness_request(unit, pack)
        for fact in unit.context_requirements.get("required_facts", []):
            missing = request.model_copy(update={"context": request.context.model_copy(update={"facts": request.context.facts - {fact}})})
            assert f"fact:{fact}" in context_errors(unit, missing), (unit.id, fact)
        if unit.world_requirements:
            general = request.model_copy(update={"world_state": request.world_state.model_copy(update={"genre": "general"})})
            assert validate_world(unit, general, general.emotion_state, general.world_state)[0], unit.id
            depleted = request.model_copy(update={"world_state": request.world_state.model_copy(update={"qi": 0})})
            if unit.world_requirements["cost"] > 0:
                assert "world.resource" in validate_world(unit, depleted, depleted.emotion_state, depleted.world_state)[0]


def test_expanded_rules_are_distinct_reachable_and_have_effect(pack, request_data):
    fingerprints = []
    for modifier in pack.modifiers:
        fingerprints.append(digest({"kind": modifier.kind, "when": modifier.model_dump()["when"], "effects": modifier.model_dump()["effects"]}))
        raw = request_data.model_dump(mode="json")
        for path, condition in modifier.when.items():
            root, field = path.split(".")
            target = raw["character"]["personality"]["big_five"] if root == "personality" else raw["world_state" if root == "world" else "physical_state" if root == "physical" else root]
            low = condition.gt if condition.gt is not None else (-1 if path == "relationship.dominance" else 0)
            high = condition.lt if condition.lt is not None else 1
            target[field] = (low + high) / 2
        request = type(request_data).model_validate(raw)
        assert modifier in active_modifiers((modifier,), request), modifier.id
        assert modifier.effects.parameter_add or modifier.effects.budget_add or any(
            score_modifiers((modifier,), unit)[f"modifier:{modifier.id}"] != 0 for unit in pack.all()), modifier.id
    assert len(fingerprints) == len(set(fingerprints))


@pytest.mark.parametrize("emotion", ["anger", "fear", "joy", "gratitude", "sadness", "curiosity", "shame", "anticipation"])
def test_expanded_pack_does_not_rephrase_same_family_in_long_dialogue(pack, request_data, emotion):
    engine = PerformanceEngine(pack)
    state = request_data.scene_state
    history, families = [], Counter()
    emitted = 0
    try:
        for turn in range(20):
            current = request_data.model_copy(update={"scene_state": state, "seed": turn,
                "emotion_state": EmotionState(primary=emotion, intensity=.7,
                    vad=pack.ontology.resolve(emotion).prototype_vad, decay_half_life_ms=90000)})
            plan = engine.plan(current)
            assert not set(plan.unit_ids) & {key for previous in history[-3:] for key in previous}
            groups = [group for key in plan.unit_ids for group in pack.get(key).semantic_groups]
            families.update(groups)
            history.append(plan.unit_ids)
            emitted += len(plan.unit_ids)
            engine.render(plan)
            state = engine.commit(plan.plan_id, state.revision)
        assert emitted >= 8, (emotion, emitted)
        assert max(families.values(), default=0) <= 4, (emotion, families)
    finally:
        engine.repository.close()
