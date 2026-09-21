"""Explicit blocking goals, known paths and resumable movement.

elapsed_ms is a time allowance for this beat, not an external clock update. A beat
traverses at most one edge, and every visible bridge consumes one signal slot.
"""
from heapq import heappop, heappush

from character_performance.continuity import apply_effects, context_errors, physical_errors, precondition_errors
from character_performance.domain.models import ActiveAction, BlockingStep, PerformanceRequest, SceneLayout, SceneState
from character_performance.ontology.pack import PerformancePack, digest

VISIBILITY = {"hidden": 0, "very_subtle": 1, "subtle": 2, "noticeable": 3, "obvious": 4, "unknown": -1}


def shortest_route(layout: SceneLayout, origin: str, destination: str) -> tuple[str, ...]:
    """Directed least-duration path, lexical path tie-break; blocked edges excluded."""
    frontier = [(0, (origin,))]
    visited = set()
    while frontier:
        cost, route = heappop(frontier)
        node = route[-1]
        if node in visited:
            continue
        visited.add(node)
        if node == destination:
            return route
        for edge in sorted(layout.edges, key=lambda edge: (edge.origin, edge.destination)):
            if edge.origin == node and not edge.blocked and edge.destination not in visited:
                heappush(frontier, (cost + edge.duration_ms, (*route, edge.destination)))
    raise ValueError("CONTINUITY_NO_VALID_TRANSITION: no known unblocked route")


def _state(scene: SceneState, **changes) -> SceneState:
    return SceneState.model_validate({**scene.model_dump(mode="python"), **changes})


def _allowed(pack: PerformancePack, request: PerformanceRequest, unit_id: str) -> list[str]:
    unit = pack.get(unit_id)
    errors = physical_errors(unit, request)
    if unit.status != "active" or unit.id in request.director.disabled_units:
        errors.append("disabled")
    if VISIBILITY[unit.visibility] > VISIBILITY[request.director.desired_visibility]:
        errors.append("visibility_budget")
    errors.extend(context_errors(unit, request))
    return [f"{unit_id}:{reason}" for reason in errors]


def advance_blocking(pack: PerformancePack, request: PerformanceRequest, budget: int) -> tuple[SceneState, tuple[BlockingStep, ...], tuple[str, ...]]:
    scene = request.scene_state
    action = scene.active_action
    goal = request.blocking_goal or (action.goal if action else None)
    steps: list[BlockingStep] = []
    if goal is None:
        warnings = ("NO_ACTIVE_ACTION: cannot pause or resume",) if request.action_control != "continue" else ()
        return scene, (), warnings
    if budget <= 0:
        return scene, (), ("BLOCKING_BUDGET_EXHAUSTED",)
    if action and (action.pack_hash != pack.content_hash or goal != action.goal):
        return scene, (), ("ACTIVE_ACTION_CONFLICT: finish existing goal with its original pack",)
    if scene.unfinished_actions:
        return scene, (), ("CONTINUITY_NO_VALID_TRANSITION: legacy unfinished action",)
    if scene.layout is None:
        return scene, (), ("STATE_INCOMPLETE: blocking requires scene layout",)
    nodes = {node.id: node for node in scene.layout.landmarks}
    destination = nodes.get(goal.destination)
    if destination is None or (goal.pose == "seated" and destination.seat_id is None):
        return scene, (), ("STATE_INCOMPLETE: destination or seat is unknown",)
    if request.action_control in {"pause", "resume"}:
        if action is None:
            return scene, (), ("NO_ACTIVE_ACTION: cannot pause or resume",)
        if request.action_control == "pause":
            if action.status == "paused":
                return scene, (), ()
            if action.goal.interruption_policy == "forbid":
                return scene, (), ("ACTION_NOT_INTERRUPTIBLE",)
            errors = _allowed(pack, request, "navigation.pause")
            if errors:
                return scene, (), tuple(errors)
            action = action.model_copy(update={"status": "paused"})
            return _state(scene, active_action=action), (BlockingStep(unit_id="navigation.pause", phase="pause"),), ()
        if action.status == "paused":
            errors = _allowed(pack, request, "navigation.resume")
            if action.edge_index < len(action.route) - 1:
                errors += _allowed(pack, request, "navigation.move")
            if errors:
                return scene, (), tuple(errors)
            action = action.model_copy(update={"status": "running"})
            scene = _state(scene, active_action=action)
            steps.append(BlockingStep(unit_id="navigation.resume", phase="resume"))
    if action and action.status == "paused":
        return scene, tuple(steps), ("ACTION_PAUSED: explicit resume required",)
    if action is None:
        if scene.position not in nodes:
            return scene, (), ("STATE_INCOMPLETE: current landmark is unknown",)
        if scene.position == goal.destination and scene.pose == goal.pose:
            if goal.pose != "seated" or scene.support_contact == destination.seat_id:
                return scene, (), ()
        try:
            route = shortest_route(scene.layout, scene.position, goal.destination)
        except ValueError as error:
            return scene, (), (str(error),)
        # Preflight the full recipe before even leaving support.
        required = ["navigation.move"] if len(route) > 1 else []
        if goal.pose == "seated":
            required += ["navigation.orient", "spatial.sit_down"]
        bridge = {"leaning_wall": "spatial.leave_wall", "seated": "spatial.stand_up"}.get(scene.pose)
        if bridge:
            required.append(bridge)
        if scene.pose not in {"standing", "seated", "leaning_wall"}:
            return scene, (), ("STATE_INCOMPLETE: unsupported initial pose",)
        errors = [reason for key in required for reason in _allowed(pack, request, key)]
        if errors:
            return scene, (), tuple(errors)
        if bridge:
            errors = precondition_errors(pack.get(bridge), scene, None)
            if errors:
                return scene, (), tuple(errors)
            scene = apply_effects(pack.get(bridge), scene, None)
            steps.append(BlockingStep(unit_id=bridge, phase="instant"))
        known_seat_contact = scene.position == goal.destination and goal.pose == "seated" and scene.support_contact == destination.seat_id
        if scene.support_contact is not None and not known_seat_contact:
            return scene, tuple(steps), ("STATE_INCOMPLETE: unsupported standing contact",)
        action = ActiveAction(id="action." + digest({"scene": scene.model_dump(mode="python"), "goal": goal.model_dump(mode="python"), "pack": pack.content_hash})[:24], goal=goal, route=route, pack_hash=pack.content_hash)
        scene = _state(scene, active_action=action)
    if action.edge_index == len(action.route) - 1 and goal.pose == "standing":
        return _state(scene, active_action=None), tuple(steps), ()
    if len(steps) >= budget:
        return scene, tuple(steps), ()
    # Follow the persisted route; do not silently re-route an action in flight.
    if action.edge_index < len(action.route) - 1:
        origin, target = action.route[action.edge_index:action.edge_index + 2]
        edge = next(e for e in scene.layout.edges if (e.origin, e.destination) == (origin, target))
        errors = _allowed(pack, request, "navigation.move")
        if edge.blocked:
            errors.append("CONTINUITY_NO_VALID_TRANSITION: active edge blocked")
        if errors:
            return scene, tuple(steps), tuple(errors)
        if request.elapsed_ms == 0:
            return scene, tuple(steps), ("STATE_INCOMPLETE: elapsed_ms required to advance movement",)
        elapsed = min(request.elapsed_ms, edge.duration_ms - action.elapsed_ms)
        progress = action.elapsed_ms + elapsed
        complete = progress == edge.duration_ms
        phase = "complete" if complete else "start" if action.elapsed_ms == 0 else "continue"
        steps.append(BlockingStep(unit_id="navigation.move", phase=phase, destination=target,
            elapsed_ms=progress, duration_ms=edge.duration_ms, render=phase != "continue"))
        action = action.model_copy(update={"edge_index": action.edge_index + int(complete), "elapsed_ms": 0 if complete else progress})
        scene = _state(scene, active_action=action, position=target if complete else None,
            orientation_target=target, support_contact=None, time_ms=scene.time_ms + elapsed,
            distances=nodes[target].distances if complete else {})
        if action.edge_index < len(action.route) - 1:
            return scene, tuple(steps), ()
    if goal.pose == "standing":
        return _state(scene, active_action=None), tuple(steps), ()
    # Final orientation and sit are distinct instantaneous atoms, each budgeted.
    if scene.orientation_target != destination.seat_id and len(steps) < budget:
        errors = _allowed(pack, request, "navigation.orient")
        if errors:
            return scene, tuple(steps), tuple(errors)
        scene = _state(scene, orientation_target=destination.seat_id)
        steps.append(BlockingStep(unit_id="navigation.orient", phase="instant", destination=destination.id))
    if scene.orientation_target == destination.seat_id and len(steps) < budget:
        errors = _allowed(pack, request, "spatial.sit_down")
        if errors:
            return scene, tuple(steps), tuple(errors)
        sitting = _state(scene, active_action=None, support_contact=destination.seat_id)
        scene = apply_effects(pack.get("spatial.sit_down"), sitting, None)
        steps.append(BlockingStep(unit_id="spatial.sit_down", phase="instant", destination=destination.id))
    return scene, tuple(steps), ()
