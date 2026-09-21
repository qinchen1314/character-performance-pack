"""Versioned scoring terms. Personality and relationships modify semantics, never IDs."""
from dataclasses import dataclass
from hashlib import sha256

from character_performance.domain.models import EmotionState, HistoryEntry, PerformanceRequest, PerformanceUnit


def clamp(value: float) -> float:
    return min(1., max(0., value))


def noise(seed: int, unit_id: str) -> float:
    return int.from_bytes(sha256(f"{seed}:{unit_id}".encode()).digest()[:8], "big") / (2**64 - 1)


@dataclass(frozen=True)
class ScoringRules:
    version: str = "1.0.0"
    emotion: float = 1.2
    vad: float = .8
    narrative: float = .55
    temperature: float = .35
    minimum_score: float = .35


def score_unit(unit: PerformanceUnit, request: PerformanceRequest, emotion: EmotionState, history: tuple[HistoryEntry, ...], rules: ScoringRules, surface: bool) -> dict[str, float]:
    traits = request.character.personality.big_five
    sem = unit.semantics
    personality = (
        (traits.extraversion - .5) * 2.5 * sem.get("initiative", 0)
        + (traits.neuroticism - .5) * 2.5 * sem.get("withdrawal", 0)
        + (traits.conscientiousness - .5) * 2.5 * sem.get("self_control", 0)
        + (.5 - traits.agreeableness) * 2.5 * sem.get("aggression", 0)
        + (traits.agreeableness - .5) * 1.8 * sem.get("warmth", 0)
        + (traits.neuroticism - .5) * sem.get("tension", 0)
    )
    relation = request.relationship
    relationship = 0.
    if relation:
        relationship = (
            relation.dominance * .8 * sem.get("aggression", 0)
            - relation.dominance * .8 * sem.get("deference", 0)
            + relation.intimacy * sem.get("warmth", 0)
            + relation.hostility * .7 * sem.get("aggression", 0)
            + (1 - relation.trust) * .5 * sem.get("withdrawal", 0)
        )
    repetition = 0.
    phrase_penalty = 0.
    phrase = unit.render_hints["verb"] + unit.render_hints.get("complement", "")
    for entry in history:
        age = request.scene_state.turn_index - entry.turn_index
        if 0 < age <= 20:
            if entry.unit_id == unit.id:
                repetition += 8 if age <= max(3, unit.cooldown.turns) else 1.5 * (1 - age / 21)
            if entry.semantic_groups & unit.semantic_groups:
                repetition += 2.5 * (1 - age / 21)
            if age <= 3 and entry.channel == unit.channel:
                repetition += .2 * (4 - age)
            if age <= 6 and phrase in entry.render_features.get("grammar", ()):
                phrase_penalty += .25 * (1 - age / 7)
    affinity = unit.emotion_affinity.get("calm" if surface else emotion.primary, 0)
    if not surface and emotion.secondary:
        affinity = max(affinity, .65 * unit.emotion_affinity.get(emotion.secondary, 0))
    similarity = 0.
    if unit.vad_affinity:
        similarity = 1 - sum(abs(getattr(unit.vad_affinity, field) - getattr(emotion.vad, field)) for field in ("valence", "arousal", "dominance")) / 6
    signature = sum(s.affinity * .5 for s in request.character.signature_behaviours if s.unit_id == unit.id and not any(h.unit_id == unit.id and 0 < request.scene_state.turn_index - h.turn_index <= s.cooldown_turns for h in history))
    return {"emotion": rules.emotion * affinity, "vad": rules.vad * similarity,
        "narrative": rules.narrative * unit.narrative_weight,
        "personality_modifier": personality, "relationship_modifier": relationship,
        "physical_modifier": -.5 * request.physical_state.fatigue * sem.get("initiative", 0),
        "signature": signature, "surface": 1.5 if surface else 0.,
        "jitter": (noise(request.seed, unit.id) - .5) * .1, "repetition": -repetition,
        "render_phrase_penalty": -phrase_penalty}


def parameters(request: PerformanceRequest, emotion: EmotionState, unit: PerformanceUnit, leak: bool) -> dict[str, float]:
    traits = request.character.personality.big_five
    relation = request.relationship
    dominance = relation.dominance if relation else 0
    intimacy = relation.intimacy if relation else 0
    amplitude = clamp(request.character.expression_baseline.amplitude * (.4 + .6 * emotion.intensity)
        + .2 * traits.extraversion - .25 * emotion.restraint + .12 * dominance
        - .2 * request.physical_state.fatigue)
    if leak:
        amplitude = min(.2, amplitude)
    result = {"amplitude": round(amplitude, 4),
        "directness": round(clamp(.5 + .3 * dominance + .2 * traits.extraversion - .2 * request.context.formality), 4),
        "preferred_distance": round(1.5 - .5 * intimacy - .2 * dominance, 4)}
    if unit.category == "speech":
        result.update(volume=round(clamp(request.character.expression_baseline.speech_volume + .15 * dominance - .2 * request.context.formality), 4),
            pace=.35 if unit.atomic_action == "pace_slow" else .8 if unit.atomic_action == "pace_quick" else .5)
    return result
