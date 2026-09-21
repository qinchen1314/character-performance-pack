import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

import pytest
import yaml

from character_performance.build import PackBuildError, build_pack
from character_performance.domain.models import CharacterProfile, SceneState
from character_performance.engine import PerformanceEngine
from character_performance.ontology.pack import PerformancePack
from character_performance.sources.registry import BuildPolicy
from character_performance.storage import RevisionConflict, SQLiteRepository

ROOT = Path(__file__).parents[2]


def test_plan_is_reproducible_and_does_not_commit(pack, request_data):
    engine = PerformanceEngine(pack)
    first, second = engine.plan(request_data), engine.plan(request_data)
    assert first == second
    assert engine.repository.current(first.scene_id, first.subject_id) is None
    assert not engine.repository.history(first.scene_id, first.subject_id)
    with pytest.raises(ValueError, match="RENDER_REQUIRED"):
        engine.commit(first.plan_id, 0)
    engine.render(first)
    state = engine.commit(first.plan_id, 0)
    assert engine.commit(first.plan_id, 0) == state
    assert len(engine.repository.history(first.scene_id, first.subject_id)) == len(first.unit_ids)


def test_concurrent_plans_only_one_commit_succeeds(pack, request_data, tmp_path):
    first = PerformanceEngine(pack, SQLiteRepository(tmp_path / "state.db"))
    second = PerformanceEngine(pack, SQLiteRepository(tmp_path / "state.db"))
    plans = [first.plan(request_data), second.plan(request_data.model_copy(update={"seed": 99}))]
    first.render(plans[0])
    second.render(plans[1])
    def commit(engine, plan):
        try:
            engine.commit(plan.plan_id, 0)
            return "ok"
        except RevisionConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda pair: commit(*pair), [(first, plans[0]), (second, plans[1])]))
    assert sorted(outcomes) == ["conflict", "ok"]
    first.repository.close()
    second.repository.close()


def test_tampered_plan_and_stale_snapshot_are_rejected(pack, request_data):
    engine = PerformanceEngine(pack)
    plan = engine.plan(request_data)
    modified = plan.model_copy(deep=True)
    modified.parameters[modified.primary_signal]["amplitude"] = 1
    assert not engine.validate(modified).valid
    with pytest.raises(ValueError, match="INTEGRITY"):
        engine.render(modified)
    engine.render(plan)
    state = engine.commit(plan.plan_id, 0)
    with pytest.raises(RevisionConflict):
        engine.plan(request_data)
    forged = state.model_copy(update={"position": "pos.teleport"})
    with pytest.raises(RevisionConflict, match="SNAPSHOT"):
        engine.plan(request_data.model_copy(update={"scene_state": forged}))


def test_restart_recovers_history_and_actor_state(pack, request_data, tmp_path):
    repository = SQLiteRepository(tmp_path / "state.db")
    engine = PerformanceEngine(pack, repository)
    plan = engine.plan(request_data)
    engine.render(plan)
    state = engine.commit(plan.plan_id, 0)
    repository.close()
    restored = SQLiteRepository(tmp_path / "state.db")
    assert restored.current(plan.scene_id, plan.subject_id)[0] == state
    assert len(restored.history(plan.scene_id, plan.subject_id)) == len(plan.unit_ids)
    restored.close()


def test_missing_emotion_returns_empty_plan_warning(pack, request_data):
    plan = PerformanceEngine(pack).plan(request_data.model_copy(update={"emotion_state": None}))
    assert not plan.unit_ids
    assert any("STATE_INCOMPLETE" in w for w in plan.warnings)


def test_t8_unknown_and_overreaching_source_fail_build(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(ROOT / "data", root / "data", ignore=shutil.ignore_patterns("compiled"))
    path = root / "data/ontology/units.yaml"
    original = yaml.safe_load(path.read_text(encoding="utf-8"))
    for source, license_class, match in [("src.unknown", "original", "src.unknown"), ("src.facs.concepts.v1", "redistribution_allowed", "usage mismatch")]:
        raw = json.loads(json.dumps(original))
        raw["units"][0].update(source_refs=[source], license_class=license_class)
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        with pytest.raises(PackBuildError, match=match):
            build_pack(root, tmp_path / "out", BuildPolicy(False, False))
        assert not (tmp_path / "out/manifest.json").exists()


def test_compiled_roundtrip_and_tamper_detection(pack, tmp_path):
    build_pack(ROOT, tmp_path, BuildPolicy(False, False))
    restored = PerformancePack.from_compiled(tmp_path)
    assert restored.content_hash == pack.content_hash
    path = tmp_path / "pack.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["units"][0]["narrative_weight"] = 0
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        PerformancePack.from_compiled(tmp_path)


def test_source_and_compiled_plans_are_identical(pack, request_data, tmp_path):
    build_pack(ROOT, tmp_path, BuildPolicy(False, False))
    compiled = PerformancePack.from_compiled(tmp_path)
    assert PerformanceEngine(pack).plan(request_data) == PerformanceEngine(compiled).plan(request_data)


def test_compiled_license_review_cannot_be_bypassed(tmp_path):
    build_pack(ROOT, tmp_path, BuildPolicy(False, False))
    path = tmp_path / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["sources"][0]["review_status"] = "pending"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="review status is pending"):
        PerformancePack.from_compiled(tmp_path)


@pytest.mark.parametrize("seed", range(30))
def test_budget_and_pairwise_conflicts(pack, request_data, seed):
    plan = PerformanceEngine(pack).plan(request_data.model_copy(update={"seed": seed}))
    assert len(plan.unit_ids) <= request_data.director.max_signals
    for unit_id in plan.unit_ids:
        assert not pack.get(unit_id).conflicts & set(plan.unit_ids)
