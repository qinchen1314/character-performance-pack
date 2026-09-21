"""Shared gesture history must be scoped, bounded and reproducible after restart."""
import sqlite3

from character_performance.domain.models import RelationshipState
from character_performance.engine import PerformanceEngine
from character_performance.storage import SQLiteRepository


def actor_request(request, subject, revision, scene_id=None):
    return request.model_copy(update={
        "request_id": f"req.{subject}.{revision}",
        "character": request.character.model_copy(update={"id": subject}),
        "relationship": RelationshipState(subject_id=subject, target_id="char.target"),
        "scene_state": request.scene_state.model_copy(update={
            "scene_id": scene_id or request.scene_state.scene_id, "revision": revision}),
    })


def perform(engine, request):
    plan = engine.plan(request)
    engine.render(plan)
    engine.commit(plan.plan_id, request.scene_state.revision)
    return plan


def test_plan_keeps_ensemble_snapshot_after_later_commits_and_restart(pack, request_data, tmp_path):
    path = tmp_path / "ensemble.db"
    engine = PerformanceEngine(pack, SQLiteRepository(path))
    first = perform(engine, actor_request(request_data, "char.first", 0))
    second = perform(engine, actor_request(request_data, "char.second", 1))
    snapshot = engine.repository.saved_scene_history(second.plan_id)
    assert tuple(entry.unit_id for entry in snapshot) == first.unit_ids
    assert any(score.get("scene_repetition", 0) < 0 for score in second.scores.values())
    perform(engine, actor_request(request_data, "char.third", 2))
    engine.repository.close()

    restored = PerformanceEngine(pack, SQLiteRepository(path))
    try:
        assert restored.repository.saved_scene_history(second.plan_id) == snapshot
        assert restored.repository.scene_history(second.scene_id, second.subject_id) != snapshot
        assert restored.validate(second).valid
        # Idempotent commit replays the saved state, never the newer scene history.
        assert restored.commit(second.plan_id, 1) == second.state_transition.after
        assert restored.repository.current(second.scene_id, second.subject_id)[0].revision == 3
    finally:
        restored.repository.close()


def test_ensemble_window_uses_commit_order_excludes_self_and_other_scenes(pack, request_data):
    engine = PerformanceEngine(pack)
    try:
        expected = []
        for index in range(8):
            subject = f"char.member{index}"
            plan = perform(engine, actor_request(request_data, subject, index))
            expected.extend(engine.repository.history(plan.scene_id, subject))
        assert len(expected) > 12
        assert engine.repository.scene_history(plan.scene_id, "char.observer") == tuple(expected[-12:])
        without_last = expected[-12:][:-len(plan.unit_ids)]
        assert engine.repository.scene_history(plan.scene_id, plan.subject_id) == tuple(without_last)
        assert not engine.repository.scene_history("scene.other", "char.observer")
        # A previously unseen scene gets exactly the same plan as a clean store.
        unrelated = actor_request(request_data, "char.observer", 0, "scene.other")
        clean = PerformanceEngine(pack)
        try:
            assert engine.plan(unrelated) == clean.plan(unrelated)
        finally:
            clean.repository.close()
    finally:
        engine.repository.close()


def test_other_actor_gestures_expire_as_current_actor_continues(pack, request_data):
    engine = PerformanceEngine(pack)
    try:
        first = perform(engine, actor_request(request_data, "char.first", 0))
        assert engine.repository.scene_history(first.scene_id, "char.solo")
        request = actor_request(request_data, "char.solo", 1)
        emitted = 0
        for index in range(30):
            plan = perform(engine, request.model_copy(update={"seed": index}))
            emitted += len(plan.unit_ids)
            request = request.model_copy(update={"scene_state": plan.state_transition.after,
                                                 "world_state": plan.state_transition.world_after})
        assert emitted >= 12
        assert engine.repository.scene_history(first.scene_id, "char.solo") == ()
        next_plan = engine.plan(request)
        assert all(score.get("scene_repetition", 0) == 0 for score in next_plan.scores.values())
    finally:
        engine.repository.close()


def test_database_without_ensemble_column_migrates_and_can_commit(pack, request_data, tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as old:
        old.execute("CREATE TABLE plans (id TEXT PRIMARY KEY, request TEXT NOT NULL, "
                    "plan TEXT NOT NULL, history TEXT NOT NULL, rendered INTEGER NOT NULL DEFAULT 0, "
                    "committed INTEGER NOT NULL DEFAULT 0, render_result TEXT)")
    engine = PerformanceEngine(pack, SQLiteRepository(path))
    try:
        plan = perform(engine, request_data)
        assert engine.repository.saved_scene_history(plan.plan_id) == ()
        assert engine.repository.current(plan.scene_id, plan.subject_id)[0] == plan.state_transition.after
    finally:
        engine.repository.close()
