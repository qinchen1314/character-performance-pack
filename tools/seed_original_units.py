"""Rebuild the project's original, hand-authored atomic behaviours (no scraped text)."""
from pathlib import Path
import yaml

# id, category, channel, body region, semantic group, affinities, semantic axis,
# grammar subject / verb / complement, visibility. Grammar is not a sentence bank.
ROWS = [
    ("brow_contract", "facial", "facial", "brow", "brow_tension", "anger curiosity", "tension", "眉间", "蹙", "起", "subtle"),
    ("lip_press", "facial", "facial", "lips", "lip_restraint", "anger fear remorse", "self_control", "嘴唇", "抿", "紧", "subtle"),
    ("jaw_set", "facial", "facial", "jaw", "jaw_tension", "anger resentment", "aggression", "下颌", "绷", "紧", "noticeable"),
    ("smile_open", "facial", "facial", "mouth", "mouth_change", "joy love gratitude", "warmth", "唇角", "扬", "起", "noticeable"),
    ("eyelid_lower", "facial", "facial", "eyelids", "eyelid_cover", "sadness disappointment shame", "withdrawal", "眼睑", "垂", "下", "subtle"),
    ("brow_release", "facial", "facial", "brow", "brow_release", "relief love calm", "self_control", "眉间", "舒展", "开", "subtle"),
    ("lip_pause", "micro_expression", "facial", "lips", "speech_inhibition", "fear anger embarrassment", "self_control", "嘴唇", "动", "了一下，又停住", "very_subtle"),
    ("blink_delay", "micro_expression", "facial", "eyelids", "blink_delay", "fear surprise jealousy", "tension", "眼睑", "停", "了一瞬才落下", "very_subtle"),
    ("target_lock", "gaze", "gaze", "eyes", "target_attention", "anger curiosity resentment", "aggression", "目光", "停", "在对方身上", "noticeable"),
    ("gaze_avoid", "gaze", "gaze", "eyes", "gaze_avoidance", "fear embarrassment remorse", "withdrawal", "目光", "避", "开对方", "subtle"),
    ("gaze_lower", "gaze", "gaze", "eyes", "gaze_lowering", "sadness disappointment admiration", "deference", "目光", "垂", "下", "subtle"),
    ("gaze_return", "gaze", "gaze", "eyes", "attention_return", "love hope gratitude", "warmth", "目光", "转", "回对方身上", "subtle"),
    ("gaze_steady", "gaze", "gaze", "eyes", "surface_calm", "calm", "self_control", "目光", "保持", "平稳", "subtle"),
    ("chin_raise", "body", "head", "head", "head_assertion", "anger pride", "aggression", "下巴", "抬", "起", "noticeable"),
    ("head_incline", "body", "head", "head", "head_inquiry", "curiosity surprise", "initiative", "头", "偏", "了偏", "subtle"),
    ("neck_stiffen", "body", "neck", "neck", "neck_guard", "fear anger", "tension", "颈侧", "绷", "紧", "subtle"),
    ("shoulder_release", "body", "shoulders", "shoulders", "shoulder_release", "relief calm", "self_control", "肩膀", "松", "下来", "subtle"),
    ("shoulder_draw", "body", "shoulders", "shoulders", "shoulder_guard", "fear embarrassment", "withdrawal", "肩膀", "缩", "起", "noticeable"),
    ("arms_fold", "body", "arms", "arms", "arm_barrier", "anger disgust resentment", "withdrawal", "双臂", "交叠", "在身前", "noticeable"),
    ("hand_clench", "body", "hands", "right_hand", "hand_tension", "anger jealousy fear", "aggression", "右手", "握", "紧", "subtle"),
    ("palm_open", "body", "hands", "left_hand", "palm_openness", "gratitude love hope", "warmth", "左手", "摊", "开", "subtle"),
    ("finger_still", "body", "fingers", "right_hand", "motor_inhibition", "fear anger embarrassment", "self_control", "右手指尖", "停", "住不动", "very_subtle"),
    ("torso_forward", "body", "torso", "torso", "engagement", "curiosity anger hope", "initiative", "上身", "倾", "向前", "noticeable"),
    ("torso_recoil", "body", "torso", "torso", "torso_recoil", "disgust surprise fear", "withdrawal", "上身", "向后", "避了避", "noticeable"),
    ("knees_brace", "body", "legs", "legs", "leg_brace", "fear anger", "tension", "双膝", "绷", "紧", "subtle"),
    ("weight_shift", "body", "feet", "feet", "balance_shift", "fear curiosity", "withdrawal", "重心", "移", "向另一只脚", "subtle"),
    ("turn_toward", "spatial", "spatial", "whole_body", "orientation_engage", "anger curiosity love", "initiative", "身体", "转", "向对方", "noticeable"),
    ("turn_away", "spatial", "spatial", "whole_body", "orientation_disengage", "disgust sadness resentment", "withdrawal", "身体", "转", "开", "noticeable"),
    ("step_back", "spatial", "spatial", "whole_body", "distance_retreat", "fear disgust", "withdrawal", "脚步", "退", "开半步", "noticeable"),
    ("step_closer", "spatial", "spatial", "whole_body", "distance_approach", "anger love hope", "initiative", "脚步", "向对方", "挪近半步", "noticeable"),
    ("stand_up", "spatial", "spatial", "whole_body", "posture_rise", "anger surprise", "initiative", "身体", "站", "起", "noticeable"),
    ("sit_down", "spatial", "spatial", "whole_body", "posture_sit", "sadness relief", "withdrawal", "身体", "坐", "下", "noticeable"),
    ("leave_wall", "spatial", "spatial", "whole_body", "support_release", "anger curiosity", "initiative", "后背", "离", "开墙面", "subtle"),
    ("lean_wall", "spatial", "spatial", "whole_body", "support_seek", "sadness disappointment", "withdrawal", "后背", "靠", "向墙面", "subtle"),
    ("transfer_left", "body", "hands", "hands", "object_transfer_left", "fear curiosity", "self_control", "手中东西", "交", "到左手", "subtle"),
    ("transfer_right", "body", "hands", "hands", "object_transfer_right", "anger hope", "initiative", "手中东西", "交", "到右手", "subtle"),
    ("breath_pause", "physiology", "breath", "lungs", "breath_pause", "fear surprise", "tension", "呼吸", "停", "了一拍", "very_subtle"),
    ("breath_even", "physiology", "breath", "lungs", "breath_regulation", "calm relief", "self_control", "呼吸", "放", "匀", "subtle"),
    ("swallow", "physiology", "throat", "throat", "swallow_response", "fear embarrassment", "tension", "喉间", "动", "了一下", "subtle"),
    ("exhale", "physiology", "breath", "lungs", "exhale_release", "sadness relief disappointment", "withdrawal", "气息", "缓缓", "吐出", "subtle"),
    ("voice_low", "speech", "speech", "voice", "volume_reduction", "fear love resentment", "withdrawal", "声音", "压", "低", "subtle"),
    ("pace_slow", "speech", "speech", "voice", "pace_deliberate", "anger calm", "self_control", "语速", "放", "慢", "subtle"),
    ("pace_quick", "speech", "speech", "voice", "pace_urgent", "joy anger surprise", "initiative", "语速", "加", "快", "noticeable"),
    ("pause_before", "speech", "speech", "voice", "speech_delay", "fear remorse disappointment", "withdrawal", "话音", "迟", "了一拍", "subtle"),
    ("enunciate", "speech", "speech", "voice", "articulation_precise", "anger pride", "aggression", "字音", "咬", "得分明", "noticeable"),
    ("voice_soft", "speech", "speech", "voice", "vocal_warmth", "love gratitude admiration", "warmth", "语气", "放", "柔", "subtle"),
    ("phrase_short", "speech", "speech", "voice", "phrase_compression", "anger disgust", "aggression", "话语", "收", "得短促", "noticeable"),
    ("voice_level", "speech", "speech", "voice", "surface_composure", "calm", "self_control", "语调", "保持", "平稳", "subtle"),
]

STATE_RULES = {
    "turn_toward": (["standing", "target_known"], {"orientation": "target"}),
    "turn_away": (["standing", "target_known"], {"orientation": "away"}),
    "step_back": (["standing", "distance_known"], {"distance_delta": 0.4}),
    "step_closer": (["standing", "can_approach"], {"distance_delta": -0.4}),
    "stand_up": (["seated"], {"pose": "standing", "clear_support": True}),
    "sit_down": (["standing", "seat_contact"], {"pose": "seated"}),
    "leave_wall": (["leaning_wall", "wall_contact"], {"pose": "standing", "clear_support": True}),
    "lean_wall": (["standing", "wall_contact"], {"pose": "leaning_wall"}),
    "transfer_left": (["right_hand_holding", "left_hand_free"], {"transfer": "right_to_left"}),
    "transfer_right": (["left_hand_holding", "right_hand_free"], {"transfer": "left_to_right"}),
}

WORLD_ROWS = [
    ("qi_settle", "qi_refining", "qi_control", "calm", "self_control", "体内气息", "收", "稳", .02),
    ("qi_stir", "qi_refining", "qi_control", "anger", "tension", "体内灵气", "微微", "一动", .03),
    ("qi_restrain", "qi_refining", "qi_control", "fear", "self_control", "体内灵气", "缓缓", "收拢", .03),
    ("aura_withdraw", "foundation", "aura_control", "fear", "withdrawal", "外放气息", "收", "回体内", .06),
    ("aura_soften", "foundation", "aura_control", "love", "warmth", "周身气息", "缓", "和下来", .06),
    ("sense_focus", "foundation", "spiritual_sense", "curiosity", "initiative", "神识", "凝", "向对方", .08),
    ("sense_retract", "foundation", "spiritual_sense", "fear", "withdrawal", "神识", "收", "回", .08),
    ("intent_gather", "golden_core", "intent_control", "anger", "aggression", "剑意", "凝", "而未发", .12),
    ("pressure_release", "golden_core", "pressure_control", "anger", "aggression", "威压", "向对方", "逼去", .15),
    ("intent_quiet", "golden_core", "intent_control", "calm", "self_control", "剑意", "敛", "入体内", .10),
]


def main() -> None:
    units = []
    root = Path(__file__).resolve().parents[1]
    emotions_doc = yaml.safe_load((root / "data/ontology/emotion/emotions.yaml").read_text(encoding="utf-8"))
    prototypes = {e["id"]: e["prototype_vad"] for e in emotions_doc["emotions"]}
    prototypes["calm"] = {"valence": .2, "arousal": -.5, "dominance": .3}
    for action, category, channel, part, group, emotions, axis, subject, verb, complement, visibility in ROWS:
        # Shame maps to the existing embarrassment taxonomy; no new label invented.
        emotions = emotions.replace("shame", "embarrassment")
        preconditions, effects = STATE_RULES.get(action, ([], {}))
        capabilities = []
        if part in {"right_hand", "left_hand"}:
            preconditions = [*preconditions, f"{part}_free"]
            capabilities.append(f"{part}_use")
        if category == "gaze":
            capabilities.append("vision")
            if action in {"target_lock", "gaze_avoid", "gaze_return"}:
                preconditions = ["target_known"]
        if category == "speech":
            capabilities.append("speech")
        if action in {"arms_fold", "transfer_left", "transfer_right"}:
            capabilities += ["left_hand_use", "right_hand_use"]
        if action == "arms_fold":
            preconditions = ["left_hand_free", "right_hand_free"]
        if action in {"knees_brace", "weight_shift"}:
            preconditions = ["standing"]
        if category == "spatial":
            capabilities.append("walking")
        requirements = {"capabilities": capabilities}
        if category == "spatial":
            requirements["min_mobility"] = .5
        if category == "physiology":
            requirements["min_breath"] = .3
        units.append(dict(id=f"{category}.{action}", category=category, channel=channel,
            atomic_action=action, body_parts=[part], semantic_groups=[group], semantics={axis: .9},
            emotion_affinity={label: .85 if i == 0 else .65 for i, label in enumerate(emotions.split())},
            intensity_range={"min": .05, "max": 1}, preconditions=preconditions, effects=effects,
            physical_requirements=requirements, conflicts=[], visibility=visibility,
            narrative_weight=.6, cooldown={"turns": 4, "scene_scope": True}, repeat_group=group,
            render_hints={"subject": subject, "verb": verb, "complement": complement},
            source_refs=["src.original.performance.v1"], license_class="original", status="active",
            **({"timing_ms": [180, 500]} if category == "micro_expression" else {})))
    for action, realm, capability, emotion, axis, subject, verb, complement, cost in WORLD_ROWS:
        units.append(dict(id=f"world.{action}", category="world_specific", channel="world",
            atomic_action=action, body_parts=["whole_body"], semantic_groups=[action],
            semantics={axis: .9}, emotion_affinity={emotion: .9},
            intensity_range={"min": .25, "max": 1}, conflicts=[], visibility="subtle",
            narrative_weight=.5, cooldown={"turns": 6}, repeat_group=action,
            preconditions=["target_known"] if action in {"sense_focus", "pressure_release"} else [],
            world_requirements={"min_realm": realm, "capability": capability, "cost": cost,
                "control": .6, "destruction": 0, "min_intensity": .7 if action == "pressure_release" else .25,
                "target_dominance": action == "pressure_release"},
            render_hints={"subject": subject, "verb": verb, "complement": complement},
            source_refs=["src.original.performance.v1"], license_class="original", status="active"))
    for action, verb, complement in [("move", "走", "向已知位置"), ("orient", "转", "向座椅"), ("pause", "停", "住脚步"), ("resume", "重新", "迈步")]:
        units.append(dict(id=f"navigation.{action}", category="spatial", channel="spatial",
            atomic_action=f"navigation_{action}", invocation="blocking", body_parts=[] if action in {"pause", "resume"} else ["whole_body"],
            semantic_groups=[f"navigation_{action}"], semantics={"initiative": .5},
            emotion_affinity={}, intensity_range={"min": 0, "max": 1}, conflicts=[],
            visibility="noticeable" if action == "move" else "subtle", narrative_weight=.6,
            cooldown={"turns": 0}, repeat_group=f"navigation_{action}",
            physical_requirements={"capabilities": ["walking"], "min_mobility": .5} if action in {"move", "orient"} else {},
            render_hints={"subject": "", "verb": verb, "complement": complement},
            source_refs=["src.original.navigation.v1"], license_class="original", status="active"))
    by_action = {u["atomic_action"]: u for u in units}
    for first, second in [("hand_clench", "finger_still"), ("arms_fold", "palm_open"),
                          ("torso_forward", "torso_recoil"), ("transfer_left", "hand_clench")]:
        by_action[first]["conflicts"].append(by_action[second]["id"])
        by_action[second]["conflicts"].append(by_action[first]["id"])
    for unit in units:
        # Positive affect can be expansive, receptive or restrained; warmth alone
        # cannot distinguish persona choices across channels.
        if unit["atomic_action"] in {"palm_open", "smile_open"}:
            unit["semantics"]["initiative"] = .7
        if unit["atomic_action"] == "gaze_return":
            unit["semantics"]["self_control"] = .65
        if unit["atomic_action"] == "voice_soft":
            unit["semantics"]["self_control"] = .35
        if unit["atomic_action"] == "brow_release":
            unit["emotion_affinity"]["joy"] = .7
        grammar = {
            "stand_up": ("", "站", "起身来"),
            "sit_down": ("", "坐", "下"),
            "turn_toward": ("", "转", "向对方"),
            "turn_away": ("", "转", "开身"),
            "step_back": ("", "后退", "半步"),
            "step_closer": ("", "向对方", "挪近半步"),
            "breath_even": ("", "放匀", "呼吸"),
            "exhale": ("", "缓缓吐", "出一口气"),
            "head_incline": ("", "偏", "了偏头"),
            "transfer_left": ("", "将右手的东西交", "到左手"),
            "transfer_right": ("", "将左手的东西交", "到右手"),
        }.get(unit["atomic_action"])
        if grammar:
            unit["render_hints"] = dict(zip(("subject", "verb", "complement"), grammar))
        if unit["category"] in {"facial", "micro_expression"}:
            unit["facial_units"] = [{"region": unit["body_parts"][0], "action": unit["atomic_action"], "intensity": .3 if unit["category"] == "micro_expression" else .5}]
        if unit["category"] == "micro_expression":
            unit["timing"] = {"onset_ms": [40, 100], "apex_ms": [60, 140], "offset_ms": [80, 260], "total_duration_ms": [180, 500]}
        if unit["category"] == "world_specific":
            rules = unit["world_requirements"]
            capability = rules["capability"]
            if unit["atomic_action"] in {"aura_withdraw", "sense_retract", "intent_quiet"}:
                rules.update(requires_active=[capability], deactivate=[capability])
            elif unit["atomic_action"] in {"aura_soften", "sense_focus", "intent_gather", "pressure_release"}:
                rules["activate"] = [capability]
        affinity = unit["emotion_affinity"]
        if affinity:
            unit["vad_affinity"] = {axis: round(sum(prototypes[label][axis] * weight for label, weight in affinity.items()) / sum(affinity.values()), 4) for axis in ("valence", "arousal", "dominance")}
        # Original engineering priors distinguish regulated from activating responses.
        if "self_control" in unit["semantics"]:
            unit["vad_affinity"]["arousal"] = -.25
        elif affinity and ("aggression" in unit["semantics"] or "initiative" in unit["semantics"]):
            unit["vad_affinity"]["arousal"] = .8
        verb = unit["render_hints"]["verb"]
        alternate = {"保持": "维持", "垂": "低垂", "收拢": "聚拢"}.get(verb)
        if alternate:
            unit["render_hints"]["alternate_verb"] = alternate
    path = root / "data/ontology/units.yaml"
    path.write_text(yaml.safe_dump({"schema_version": "1.0.0", "units": units}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"{len(units)} original units -> {path}")


if __name__ == "__main__":
    main()
