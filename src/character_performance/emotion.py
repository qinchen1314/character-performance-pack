from character_performance.domain.models import Appraisal, EmotionState, PerformanceRequest
from character_performance.ontology.emotion import EmotionOntology


def build_emotion(request: PerformanceRequest, ontology: EmotionOntology) -> tuple[EmotionState | None, tuple[str, ...]]:
    if request.emotion_state:
        ontology.validate_state(request.emotion_state)
        return request.emotion_state, ()
    if request.event is None or request.cognition is None:
        return None, ("STATE_INCOMPLETE: provide emotion_state or event + cognition",)
    event, cognition = request.event, request.cognition
    if cognition.goal_impact >= 0.2:
        label = "joy"
    elif event.threat.get("physical", 0) > 0.5 and cognition.controllability < 0.5:
        label = "fear"
    elif cognition.goal_impact < -0.2 and cognition.target_responsibility > 0.5:
        label = "anger"
    elif cognition.goal_impact < -0.2:
        label = "disappointment"
    else:
        label = "curiosity"
    emotion = ontology.resolve(label)
    residue = sorted((r for r in request.scene_state.emotional_residue if r.expires_after_turn >= request.scene_state.turn_index and r.emotion != label), key=lambda r: (-r.intensity, r.emotion))
    secondary = ontology.resolve(residue[0].emotion) if residue else None
    state = EmotionState(primary=label, secondary=secondary.id if secondary else None,
        families=emotion.families | (secondary.families if secondary else frozenset()),
        intensity=min(1, event.salience * 0.5 + abs(cognition.goal_impact) * 0.5),
        vad=emotion.prototype_vad,
        restraint=request.character.personality.big_five.conscientiousness,
        decay_half_life_ms=90000, trigger_refs=(event.id,),
        appraisal=Appraisal(goal_congruence=cognition.goal_impact,
            controllability=cognition.controllability, certainty=cognition.certainty,
            responsibility="target" if cognition.target_responsibility > 0.5 else "unknown"))
    return state, ("EMOTION_INFERRED: rule-based appraisal; caller may supply emotion_state",)
