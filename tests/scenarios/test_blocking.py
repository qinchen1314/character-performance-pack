from pathlib import Path

import pytest
from pydantic import ValidationError

from character_performance.blocking import shortest_route
from character_performance.domain.models import BlockingGoal, Director, PhysicalState, RenderContext, SceneLayout, SceneState
from character_performance.engine import PerformanceEngine
from character_performance.storage import SQLiteRepository
from character_performance.ontology.pack import PerformancePack


@pytest.fixture
def navigation_request(pack, request_data):
    layout = SceneLayout(landmarks=[
        {"id": "pos.wall", "label_zh": "墙边"},
        {"id": "pos.table", "label_zh": "桌边", "seat_id": "seat.table", "seat_label": "椅子"},
    ], edges=[{"origin": "pos.wall", "destination": "pos.table", "duration_ms": 2000}])
    enabled = {"spatial.leave_wall", "spatial.stand_up", "spatial.sit_down", "navigation.move", "navigation.orient", "navigation.pause", "navigation.resume"}
    return request_data.model_copy(update={
        "scene_state": SceneState(scene_id="scene.navigation", pose="leaning_wall", position="pos.wall",
            support_contact="wall.north", held_objects={"right_hand": "object.sword"}, layout=layout,
            distances={"char.target": 3.2}),
        "physical_state": PhysicalState(injuries=[{"body_part": "left_shoulder", "severity": .45}]),
        "blocking_goal": BlockingGoal(destination="pos.table", pose="seated"),
        "elapsed_ms": 700,
        "director": Director(beat_importance=.8, max_signals=4,
            disabled_units=frozenset(unit.id for unit in pack.all() if unit.id not in enabled)),
    })


def run_turn(engine, request):
    plan = engine.plan(request)
    rendered = engine.render(plan, RenderContext(subject_name="洛寒"))
    scene = engine.commit(plan.plan_id, request.scene_state.revision)
    next_request = request.model_copy(update={"scene_state": scene, "world_state": plan.state_transition.world_after, "action_control": "continue"})
    return plan, rendered, next_request


def test_wall_to_seat_has_bridges_and_no_teleport(pack, navigation_request):
    engine = PerformanceEngine(pack)
    first, prose, request = run_turn(engine, navigation_request)
    assert [step.unit_id for step in first.sequence] == ["spatial.leave_wall", "navigation.move"]
    assert "离开墙面" in prose.text and "桌边走去" in prose.text
    assert request.scene_state.position is None
    assert request.scene_state.active_action.elapsed_ms == 700
    assert request.scene_state.pose == "standing"
    second, prose, request = run_turn(engine, request)
    assert second.continuation_signals == ("navigation.move",)
    assert prose.text == "" and prose.omitted_units == ("navigation.move",)
    assert request.scene_state.position is None
    third, prose, request = run_turn(engine, request)
    assert [step.unit_id for step in third.sequence] == ["navigation.move", "navigation.orient", "spatial.sit_down"]
    assert "走到桌边，转向椅子，坐下" in prose.text
    assert request.scene_state.position == "pos.table"
    assert request.scene_state.pose == "seated"
    assert request.scene_state.support_contact == "seat.table"
    assert request.scene_state.active_action is None
    assert request.scene_state.held_objects == {"right_hand": "object.sword"}
    assert request.scene_state.distances == {}  # Old distances cannot survive a move.
    assert request.scene_state.time_ms == 2000
    assert [entry.turn_index for entry in engine.repository.history(first.scene_id, first.subject_id) if entry.unit_id == "navigation.move"] == [0, 2]


def test_pause_keeps_progress_and_explicit_resume_finishes(pack, navigation_request):
    engine = PerformanceEngine(pack)
    _, _, request = run_turn(engine, navigation_request)
    _, text, request = run_turn(engine, request.model_copy(update={"action_control": "pause"}))
    assert "停住脚步" in text.text
    assert request.scene_state.active_action.status == "paused"
    assert request.scene_state.active_action.elapsed_ms == 700
    assert request.scene_state.position is None
    paused_time = request.scene_state.time_ms
    plan, text, request = run_turn(engine, request)
    assert "ACTION_PAUSED" in " ".join(plan.warnings)
    assert text.text == ""
    assert request.scene_state.time_ms == paused_time
    _, text, request = run_turn(engine, request.model_copy(update={"action_control": "resume", "elapsed_ms": 1300}))
    assert "重新迈步" in text.text and "走到桌边" in text.text
    assert request.scene_state.pose == "seated"


def test_uninterruptible_action_rejects_pause(pack, navigation_request):
    request = navigation_request.model_copy(update={"blocking_goal": BlockingGoal(destination="pos.table", interruption_policy="forbid")})
    engine = PerformanceEngine(pack)
    _, _, request = run_turn(engine, request)
    plan, _, next_request = run_turn(engine, request.model_copy(update={"action_control": "pause"}))
    assert "ACTION_NOT_INTERRUPTIBLE" in plan.warnings
    assert next_request.scene_state.active_action == request.scene_state.active_action


@pytest.mark.parametrize("kind", ["unknown_destination", "blocked", "no_seat", "no_layout", "injury", "disabled", "visibility", "zero_budget"])
def test_invalid_route_or_constraints_keep_physical_state(pack, navigation_request, kind):
    request = navigation_request
    values = request.model_dump(mode="python")
    if kind == "unknown_destination":
        values["blocking_goal"]["destination"] = "pos.invented"
    elif kind == "blocked":
        values["scene_state"]["layout"]["edges"][0]["blocked"] = True
    elif kind == "no_seat":
        values["scene_state"]["layout"]["landmarks"][1].update(seat_id=None, seat_label=None)
    elif kind == "no_layout":
        values["scene_state"]["layout"] = None
    elif kind == "injury":
        values["physical_state"]["injuries"] = [{"body_part": "left_knee", "severity": 1}]
    elif kind == "disabled":
        values["director"]["disabled_units"] |= {"navigation.move"}
    elif kind == "visibility":
        values["director"]["desired_visibility"] = "very_subtle"
    elif kind == "zero_budget":
        values["director"]["max_signals"] = 0
    request = type(request).model_validate(values)
    plan = PerformanceEngine(pack).plan(request)
    after = plan.state_transition.after
    assert not plan.sequence and plan.warnings
    assert after.pose == request.scene_state.pose
    assert after.position == request.scene_state.position
    assert after.held_objects == request.scene_state.held_objects
    assert after.active_action is None


@pytest.mark.parametrize("budget", [1, 2, 3, 4])
def test_every_bridge_counts_towards_budget(pack, navigation_request, budget):
    request = navigation_request.model_copy(update={"director": navigation_request.director.model_copy(update={"max_signals": budget}), "elapsed_ms": 2000})
    engine = PerformanceEngine(pack)
    for _ in range(8):
        plan, _, request = run_turn(engine, request)
        assert len(plan.unit_ids) <= budget
        if request.scene_state.pose == "seated":
            break
    assert request.scene_state.pose == "seated"


def test_injury_mid_movement_cannot_advance(pack, navigation_request):
    engine = PerformanceEngine(pack)
    _, _, request = run_turn(engine, navigation_request)
    injured = request.model_copy(update={"physical_state": PhysicalState(injuries=[{"body_part": "right_knee", "severity": 1}])})
    plan, _, next_request = run_turn(engine, injured)
    assert any("injury" in warning for warning in plan.warnings)
    assert next_request.scene_state.active_action.elapsed_ms == 700
    assert next_request.scene_state.position is None


def test_restart_preserves_navigation_and_render_coverage(pack, navigation_request, tmp_path):
    store = SQLiteRepository(tmp_path / "story.db")
    engine = PerformanceEngine(pack, store)
    _, _, request = run_turn(engine, navigation_request)
    store.close()
    restored = SQLiteRepository(tmp_path / "story.db")
    scene, world = restored.current(request.scene_state.scene_id, request.character.id)
    assert scene == request.scene_state
    engine = PerformanceEngine(pack, restored)
    _, _, request = run_turn(engine, request.model_copy(update={"scene_state": scene, "world_state": world, "elapsed_ms": 1300}))
    assert request.scene_state.pose == "seated"
    restored.close()


def test_route_is_directed_and_deterministic():
    layout = SceneLayout(landmarks=[{"id": f"pos.{name}", "label_zh": name} for name in "abcd"], edges=[
        {"origin": "pos.a", "destination": "pos.c", "duration_ms": 10},
        {"origin": "pos.c", "destination": "pos.d", "duration_ms": 10},
        {"origin": "pos.a", "destination": "pos.b", "duration_ms": 10},
        {"origin": "pos.b", "destination": "pos.d", "duration_ms": 10},
    ])
    assert shortest_route(layout, "pos.a", "pos.d") == ("pos.a", "pos.b", "pos.d")
    with pytest.raises(ValueError, match="no known"):
        shortest_route(layout, "pos.d", "pos.a")


def test_invalid_progress_cannot_claim_known_position(pack, navigation_request):
    engine = PerformanceEngine(pack)
    _, _, request = run_turn(engine, navigation_request)
    raw = request.scene_state.model_dump(mode="python")
    raw["position"] = "pos.table"
    with pytest.raises(ValidationError, match="inconsistent"):
        SceneState.model_validate(raw)


def test_arrived_controls_do_not_invent_walking(pack, navigation_request):
    request = navigation_request.model_copy(update={"director": navigation_request.director.model_copy(update={"max_signals": 1}), "elapsed_ms": 2000})
    engine = PerformanceEngine(pack)
    _, _, request = run_turn(engine, request)  # Leave wall.
    _, _, request = run_turn(engine, request)  # Arrive; orientation needs a later beat.
    assert request.scene_state.position == "pos.table"
    _, text, request = run_turn(engine, request.model_copy(update={"action_control": "pause"}))
    assert "脚步" not in text.text and "暂缓落座" in text.text
    director = request.director.model_copy(update={"disabled_units": request.director.disabled_units | {"navigation.move"}})
    plan, text, request = run_turn(engine, request.model_copy(update={"action_control": "resume", "director": director}))
    assert not plan.warnings
    assert "迈步" not in text.text and "准备落座" in text.text
    assert request.scene_state.time_ms == 2000
    _, _, request = run_turn(engine, request)
    _, _, request = run_turn(engine, request)
    assert request.scene_state.pose == "seated"


def test_injury_does_not_prevent_pausing_progress(pack, navigation_request):
    engine = PerformanceEngine(pack)
    _, _, request = run_turn(engine, navigation_request)
    request = request.model_copy(update={"physical_state": PhysicalState(injuries=[{"body_part": "left_knee", "severity": 1}]), "action_control": "pause"})
    _, _, request = run_turn(engine, request)
    assert request.scene_state.active_action.status == "paused"
    assert request.scene_state.active_action.elapsed_ms == 700


def test_explicit_existing_seat_contact_can_sit(pack, navigation_request):
    values = navigation_request.scene_state.model_dump(mode="python")
    values.update(position="pos.table", pose="standing", support_contact="seat.table")
    request = navigation_request.model_copy(update={"scene_state": SceneState.model_validate(values)})
    engine = PerformanceEngine(pack)
    plan, _, request = run_turn(engine, request)
    assert [step.unit_id for step in plan.sequence] == ["navigation.orient", "spatial.sit_down"]
    assert request.scene_state.pose == "seated"


def test_multi_edge_route_visits_known_landmarks_before_sitting(pack, navigation_request):
    raw = navigation_request.model_dump(mode="json")
    raw["scene_state"]["layout"]["landmarks"].append({"id": "pos.aisle", "label_zh": "过道"})
    raw["scene_state"]["layout"]["edges"] = [
        {"origin": "pos.wall", "destination": "pos.aisle", "duration_ms": 1000},
        {"origin": "pos.aisle", "destination": "pos.table", "duration_ms": 1000},
    ]
    raw["elapsed_ms"] = 5000
    request = type(navigation_request).model_validate(raw)
    engine = PerformanceEngine(pack)
    first, text, request = run_turn(engine, request)
    assert request.scene_state.position == "pos.aisle"
    assert "坐下" not in text.text
    assert request.scene_state.time_ms == 1000
    second, text, request = run_turn(engine, request)
    assert request.scene_state.position == "pos.table"
    assert request.scene_state.time_ms == 2000
    assert request.scene_state.pose == "seated"


def test_continuation_omission_cannot_hide_arrival(pack, navigation_request):
    engine = PerformanceEngine(pack)
    request = navigation_request.model_copy(update={"elapsed_ms": 2000})
    plan = engine.plan(request)
    tampered = plan.model_copy(update={"continuation_signals": ("navigation.move",)})
    assert not engine.validate(tampered).valid
    with pytest.raises(ValueError, match="INTEGRITY"):
        engine.render(tampered)


def test_explicit_navigation_still_honors_context_requirements(pack, navigation_request):
    units = tuple(u.model_copy(update={"context_requirements": {"private_only": True}}) if u.id == "navigation.move" else u for u in pack.all())
    restricted = PerformancePack(pack.ontology, units, pack.source_ids, pack.modifiers)
    request = navigation_request.model_copy(update={"context": navigation_request.context.model_copy(update={"privacy": "public"})})
    plan = PerformanceEngine(restricted).plan(request)
    assert not plan.sequence
    assert "navigation.move:privacy" in plan.warnings


def test_navigation_units_cannot_bypass_route_lifecycle(pack):
    units = tuple(u.model_copy(update={"invocation": "automatic"}) if u.id == "navigation.move" else u for u in pack.all())
    with pytest.raises(ValueError, match="navigation unit contract"):
        PerformancePack(pack.ontology, units, pack.source_ids, pack.modifiers)
