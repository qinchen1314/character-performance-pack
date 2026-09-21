"""Fail-closed predicates and small, explicit physical state transitions."""
from character_performance.domain.models import PerformanceRequest, PerformanceUnit, SceneState


BODY_REGIONS = {
    "left_arm": {"left_shoulder", "left_elbow", "left_hand"},
    "right_arm": {"right_shoulder", "right_elbow", "right_hand"},
    "left_leg": {"left_hip", "left_knee", "left_ankle", "left_foot"},
    "right_leg": {"right_hip", "right_knee", "right_ankle", "right_foot"},
    "arms": {"left_shoulder", "right_shoulder", "left_arm", "right_arm", "left_hand", "right_hand"},
    "shoulders": {"left_shoulder", "right_shoulder"},
    "hands": {"left_hand", "right_hand", "left_shoulder", "right_shoulder"},
    "legs": {"left_leg", "right_leg", "left_knee", "right_knee"},
    "feet": {"left_foot", "right_foot", "left_leg", "right_leg", "left_knee", "right_knee", "left_ankle", "right_ankle"},
    "whole_body": {"left_leg", "right_leg", "left_foot", "right_foot", "left_knee", "right_knee", "left_ankle", "right_ankle", "torso"},
}


def context_errors(unit: PerformanceUnit, request: PerformanceRequest) -> list[str]:
    requirements = unit.context_requirements
    errors = []
    if requirements.get("any") and request.context.activity not in requirements["any"]:
        errors.append("context")
    if requirements.get("private_only") and request.context.privacy != "private":
        errors.append("privacy")
    errors.extend(f"fact:{fact}" for fact in sorted(set(requirements.get("required_facts", ())) - request.context.facts))
    for fact in requirements.get("required_facts", ()):
        if fact.startswith("held."):
            _, side, tag = fact.split(".", 2)
            sides = ("left", "right") if side == "both" else (side,)
            objects = [request.scene_state.held_objects.get(f"{hand}_hand") for hand in sides]
            if any(obj is None or (tag not in request.scene_state.object_tags.get(obj, ()) and obj != "object." + tag) for obj in objects):
                errors.append(f"held_fact:{fact}")
            elif side == "both" and len(set(objects)) != 1:
                errors.append(f"held_fact:{fact}")
    return errors


def precondition_errors(unit: PerformanceUnit, scene: SceneState, target: str | None) -> list[str]:
    predicates = {
        "right_hand_free": "right_hand" not in scene.held_objects,
        "left_hand_free": "left_hand" not in scene.held_objects,
        "right_hand_holding": "right_hand" in scene.held_objects,
        "left_hand_holding": "left_hand" in scene.held_objects,
        "standing": scene.pose == "standing", "seated": scene.pose == "seated",
        "leaning_wall": scene.pose == "leaning_wall", "target_known": target is not None,
        "distance_known": target in scene.distances,
        "can_approach": target in scene.distances and scene.distances[target] >= .9,
        "seat_contact": bool(scene.support_contact and scene.support_contact.startswith("seat.")),
        "wall_contact": bool(scene.support_contact and scene.support_contact.startswith("wall.")),
    }
    errors = [f"precondition:{key}" for key in unit.preconditions if not predicates.get(key, False)]
    if (scene.unfinished_actions or scene.active_action) and (unit.effects or unit.category in {"body", "spatial"}):
        errors.append("unfinished_action")
    return errors


def physical_errors(unit: PerformanceUnit, request: PerformanceRequest) -> list[str]:
    errors = []
    requirements, physical = unit.physical_requirements, request.physical_state
    for capability in requirements.get("capabilities", []):
        if capability not in request.character.capabilities or capability in physical.sensory_constraints:
            errors.append(f"capability:{capability}")
    if physical.mobility < requirements.get("min_mobility", 0):
        errors.append("mobility")
    if physical.breath_capacity < requirements.get("min_breath", 0):
        errors.append("breath_capacity")
    parts = set(unit.body_parts)
    for part in unit.body_parts:
        parts.update(BODY_REGIONS.get(part, set()))
    if "right_hand" in parts:
        parts.update({"right_arm", "right_shoulder", "hand", "fingers"})
    if "left_hand" in parts:
        parts.update({"left_arm", "left_shoulder", "hand", "fingers"})
    for injury in physical.injuries:
        if (injury.body_part in parts and (injury.severity >= .4 or injury.constraints)) or injury.constraints & set(requirements.get("forbidden_injuries", [])):
            errors.append(f"injury:{injury.body_part}")
    return errors


def apply_effects(unit: PerformanceUnit, scene: SceneState, target: str | None) -> SceneState:
    errors = precondition_errors(unit, scene, target)
    if errors:
        raise ValueError("CONTINUITY_NO_VALID_TRANSITION: " + ", ".join(errors))
    values = scene.model_dump(mode="python")
    effects = unit.effects
    if "pose" in effects:
        values["pose"] = effects["pose"]
    if "orientation" in effects:
        values["orientation_target"] = target if effects["orientation"] == "target" else None
    if effects.get("clear_support"):
        values["support_contact"] = None
    if "distance_delta" in effects:
        if target not in scene.distances:
            raise ValueError("STATE_INCOMPLETE: distance")
        values["distances"][target] = round(scene.distances[target] + effects["distance_delta"], 6)
    if "transfer" in effects:
        source, destination = ("right_hand", "left_hand") if effects["transfer"] == "right_to_left" else ("left_hand", "right_hand")
        if destination in values["held_objects"] or source not in values["held_objects"]:
            raise ValueError("STATE_INCOMPLETE: transfer hands")
        values["held_objects"][destination] = values["held_objects"].pop(source)
    return SceneState.model_validate(values)
