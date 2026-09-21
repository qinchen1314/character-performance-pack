from character_performance.domain.models import EmotionState, PerformanceRequest, PerformanceUnit, WorldState

REALMS = {"mortal": 0, "qi_refining": 1, "foundation": 2, "golden_core": 3}


def validate_world(unit: PerformanceUnit, request: PerformanceRequest, emotion: EmotionState, world: WorldState) -> tuple[list[str], dict]:
    if unit.category != "world_specific":
        return [], {}
    errors = []
    rules = unit.world_requirements
    if world.genre != "xianxia" or not request.director.allow_world:
        errors.append("world.disabled")
    if REALMS.get(world.realm, -1) < REALMS.get(rules.get("min_realm"), 99) or world.stage < rules.get("min_stage", 1):
        errors.append("world.realm")
    capability = rules.get("capability")
    if capability not in request.character.capabilities or capability in world.suppressed_capabilities:
        errors.append("world.capability")
    if not set(rules.get("requires_active", [])) <= world.active_capabilities:
        errors.append("world.active_state")
    if world.control * request.physical_state.motor_control * (1 - request.physical_state.pain) < rules.get("control", 0):
        errors.append("world.control")
    if world.qi < rules.get("cost", 0):
        errors.append("world.resource")
    if rules.get("destruction", 0) > world.destruction_limit:
        errors.append("world.destruction")
    if emotion.intensity < rules.get("min_intensity", 0):
        errors.append("world.intensity")
    if rules.get("target_dominance") and (world.target_realm == "unknown" or REALMS.get(world.target_realm, 99) > REALMS.get(world.realm, -1)):
        errors.append("world.relative_power")
    return errors, {"rules": ["world.realm", "world.capability", "world.active_state", "world.control", "world.resource", "world.destruction", "world.intensity", "world.relative_power"], "cost": rules.get("cost", 0), "valid": not errors}


def apply_world(unit: PerformanceUnit, world: WorldState) -> WorldState:
    if not unit.world_requirements:
        return world
    values = world.model_dump(mode="python")
    values["qi"] = max(0, round(world.qi - unit.world_requirements.get("cost", 0), 8))
    values["active_capabilities"] = (world.active_capabilities | set(unit.world_requirements.get("activate", []))) - set(unit.world_requirements.get("deactivate", []))
    return WorldState.model_validate(values)
