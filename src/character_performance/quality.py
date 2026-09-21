"""Catalog checks and explicit reachability witnesses for offline verification."""
from collections import Counter
from itertools import combinations
import re

from character_performance.domain.models import PerformanceRequest
from character_performance.ontology.pack import PerformancePack

TARGETS = {"emotions": 50, "micro_expression": 100, "facial_gaze": 150, "body": 300,
    "spatial": 100, "physiology": 100, "speech": 100, "personality_modifiers": 30,
    "relationship_modifiers": 15, "world_specific": 100}


def require_catalog_quality(report):
    failures = [f"{name}:{report['actual'].get(name, 0)}<{minimum}" for name, minimum in TARGETS.items() if not report["quantity_gates"][name]]
    if report["exact_duplicate_pairs"]:
        failures.append("duplicate clauses")
    if report["near_duplicate_unit_fraction"] > .05:
        failures.append("near-duplicate units exceed 5 percent")
    failures.extend(f"emotion coverage:{key}" for key, value in report["emotion_coverage"].items() if value["candidates"] < 3 or len(value["channels"]) < 2)
    if failures:
        raise ValueError("CATALOG_QUALITY_GATE: " + "; ".join(failures))


def normalized_phrase(text):
    return re.sub(r"[\s，。！？、；：‘’“”\"'（）]", "", text)


def catalog_report(pack: PerformancePack):
    units = pack.all()
    counts = Counter(unit.category for unit in units if unit.invocation != "blocking")
    kinds = Counter(modifier.kind for modifier in pack.modifiers)
    actual = dict(counts, emotions=len(pack.ontology), facial_gaze=counts["facial"] + counts["gaze"],
        personality_modifiers=kinds["personality"], relationship_modifiers=kinds["relationship"])
    phrases = {unit.id: normalized_phrase("".join(unit.render_hints.get(key, "") for key in ("subject", "verb", "complement"))) for unit in units}
    exact, near = [], []
    grams = {key: set(zip(value, value[1:])) for key, value in phrases.items()}
    for a, b in combinations(units, 2):
        left, right = phrases[a.id], phrases[b.id]
        if left == right:
            exact.append([a.id, b.id])
        elif min(len(left), len(right)) >= 6:
            similarity = 2 * len(grams[a.id] & grams[b.id]) / max(1, len(grams[a.id]) + len(grams[b.id]))
            if similarity >= .82:
                near.append({"a": a.id, "b": b.id, "similarity": round(similarity, 4),
                    "same_family": bool(a.semantic_groups & b.semantic_groups), "texts": [left, right]})
    affected = {row[key] for row in near for key in ("a", "b")}
    families = Counter(group for unit in units for group in unit.semantic_groups)
    emotion_coverage = {emotion.id: {"candidates": sum(emotion.id in unit.emotion_affinity for unit in units),
        "channels": sorted({unit.channel for unit in units if emotion.id in unit.emotion_affinity})} for emotion in pack.ontology.all()}
    return {"pack_hash": pack.content_hash, "targets": TARGETS, "actual": actual,
        "quantity_gates": {key: actual.get(key, 0) >= target for key, target in TARGETS.items()},
        "exact_duplicate_pairs": exact, "near_duplicate_pairs": near,
        "near_duplicate_unit_fraction": round(len(affected) / len(units), 4),
        "semantic_family_count": len(families), "largest_families": families.most_common(15),
        "emotion_coverage": emotion_coverage,
        "method": "Exact normalized clauses and Chinese bigram Dice >= .82; semantic families reviewed separately. This is not a claim of human literary blind review."}


def witness_request(unit, pack):
    """Supply explicit scene facts/abilities for one unit; never used in production."""
    label = next((label for label in unit.emotion_affinity if label != "calm"), "relief")
    emotion = pack.ontology.resolve(label)
    pose = next((pose for pose in ("standing", "seated", "leaning_wall") if pose in unit.preconditions), "standing")
    support = "seat.witness" if "seat_contact" in unit.preconditions or pose == "seated" else "wall.witness" if "wall_contact" in unit.preconditions or pose == "leaning_wall" else None
    held = {f"{side}_hand": f"object.{side}_witness" for side in ("left", "right") if f"{side}_hand_holding" in unit.preconditions}
    tags = {}
    for fact in unit.context_requirements.get("required_facts", []):
        if fact.startswith("held."):
            _, side, tag = fact.split(".", 2)
            for hand in (("left", "right") if side == "both" else (side,)):
                held[f"{hand}_hand"] = "object." + tag
                tags["object." + tag] = [tag]
    intensity = max(unit.intensity_range.min, min(.7, unit.intensity_range.max))
    rules = unit.world_requirements
    intensity = max(intensity, rules.get("min_intensity", 0))
    capabilities = {"vision", "speech", "hearing", "walking", "left_hand_use", "right_hand_use"} | set(unit.physical_requirements.get("capabilities", ()))
    if rules:
        capabilities.add(rules["capability"])
    return PerformanceRequest.model_validate({"request_id": "req.witness", "character": {"id": "char.witness", "capabilities": sorted(capabilities)},
        "relationship": {"subject_id": "char.witness", "target_id": "char.target"},
        "scene_state": {"scene_id": "scene.witness", "pose": pose, "position": "pos.witness", "support_contact": support,
            "held_objects": held, "object_tags": tags, "distances": {"char.target": 3.2}},
        "emotion_state": {"primary": label, "intensity": intensity, "vad": emotion.prototype_vad.model_dump(), "decay_half_life_ms": 90000},
        "context": {"facts": unit.context_requirements.get("required_facts", []), "activity": next(iter(unit.context_requirements.get("any", ())), "conversation")},
        "world_state": {"genre": "xianxia" if rules else "general", "realm": "golden_core", "stage": 9, "target_realm": "mortal", "active_capabilities": rules.get("requires_active", []), "destruction_limit": 1},
        "director": {"allow_world": bool(rules), "beat_importance": .5, "max_signals": 1, "desired_visibility": "obvious"}})
