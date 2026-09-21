"""Individually designed probabilistic rules, never character-to-action locks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# key | conditions (space-separated AND) | semantic coefficients | parameter coefficients | purpose
PERSONALITY = """
exploratory_attention|openness>.75|initiative:.18||乐于接触陌生信息，增加主动试探
familiar_routine|openness<.25|self_control:.16||偏好熟悉程序，减少行为随意性
deliberate_completion|conscientiousness>.75|self_control:.2||在结果未定时维持有节制的表达
spontaneous_release|conscientiousness<.25|initiative:.16|amplitude:.04|较少预先修整动作，表达更直接流出
social_entry|extraversion>.75|initiative:.22|directness:.04|主动加入互动，不强制某个手势
watchful_reserve|extraversion<.25|withdrawal:.14|directness:-.04|先观察再参与，仍可在安全关系中回应
affiliative_response|agreeableness>.75|warmth:.22||重视关系修复和友善反馈
boundary_assertion|agreeableness<.25|aggression:.13|directness:.04|明确自己的边界，不等同于必然敌意
stress_sensitivity|neuroticism>.75|tension:.18||不确定条件下更容易泄露紧张
emotional_recovery|neuroticism<.25|self_control:.15||倾向恢复表达节律，不假定没有情绪
curious_but_cautious|openness>.7 neuroticism>.7|initiative:.12,withdrawal:.1||希望探究同时保留退路
curious_and_assured|openness>.7 neuroticism<.3|initiative:.2||面对新线索较少提前退缩
imaginative_deliberation|openness>.7 conscientiousness>.7|self_control:.15,initiative:.1||先整理新线索再回应
improvising_curiosity|openness>.7 conscientiousness<.3|initiative:.17|pace:.03|探索过程更易即时变换表达
private_curiosity|openness>.7 extraversion<.3|initiative:.1|volume:-.04|保留探究意愿而降低对外声量
shared_discovery|openness>.7 extraversion>.7|warmth:.12|directness:.03|把新发现引入共同注意
protective_conventionality|openness<.3 agreeableness>.7|deference:.12,warmth:.08||用熟悉的礼节降低他人不适
rigid_boundary|openness<.3 agreeableness<.3|self_control:.12,aggression:.1||不轻易改变已经表达的界限
careful_empathy|conscientiousness>.7 agreeableness>.7|warmth:.13,self_control:.1||善意经过节制后表达，避免压迫对方
disciplined_dissent|conscientiousness>.7 agreeableness<.3|self_control:.17,aggression:.08||反对时保持控制而不自动爆发
anxious_preparation|conscientiousness>.7 neuroticism>.7|self_control:.12,tension:.12||在担忧中试图修整可控细节
steady_followthrough|conscientiousness>.7 neuroticism<.3|self_control:.16|pace:-.02|保持已经选择的表达节奏
impulsive_alarm|conscientiousness<.3 neuroticism>.7|tension:.18|amplitude:.04|受刺激时较难延迟外显反应
easygoing_flexibility|conscientiousness<.3 neuroticism<.3|warmth:.1|pace:.02|低威胁下少做紧绷的自我校正
warm_assertiveness|extraversion>.7 agreeableness>.7|initiative:.12,warmth:.15||积极表达仍顾及互动对象
competitive_presence|extraversion>.7 agreeableness<.3|aggression:.18|volume:.03|争夺表达空间但不绕过冲突约束
quiet_support|extraversion<.3 agreeableness>.7|warmth:.2|amplitude:-.03|以较低幅度维持支持
detached_observation|extraversion<.3 agreeableness<.3|withdrawal:.12,self_control:.08||减少关系性回应而保留观察
uneasy_sociability|extraversion>.7 neuroticism>.7|initiative:.1,tension:.13||想参与互动但紧张仍可泄露
calm_reserve|extraversion<.3 neuroticism<.3|self_control:.2||安静源于稳定而非畏惧
sensitive_concern|agreeableness>.7 neuroticism>.7|warmth:.12,tension:.1||对他人的状态敏感并容易忧心
composed_firmness|agreeableness<.3 neuroticism<.3|aggression:.13,self_control:.1||坚定拒绝而不靠紧张幅度支撑
"""
RELATIONSHIP = """
earned_trust|trust>.75|self_control:.08,warmth:.13|amplitude:.03|信任允许较少防御性的回应
guarded_trust|trust<.25|withdrawal:.18,self_control:.08||信任不足时保留信息和身体边界
familiar_ease|familiarity>.8|warmth:.12|directness:.04|熟悉降低表达中的试探成本
stranger_calibration|familiarity<.2|self_control:.13|amplitude:-.03|不熟悉对象时先校准表现强度
positive_regard|affinity>.8|warmth:.15||好感增加积极回应但不自动亲密接触
cool_regard|affinity<.2|withdrawal:.14||低好感减少关系投入但不自动攻击
dependent_appeal|dependence>.7 dominance<0|deference:.17|directness:-.04|有求于强势对象时更注意保留余地
independent_boundary|dependence<.2 tension>.6|self_control:.1|directness:.06|冲突中不依赖对方时更易表明边界
unresolved_tension|tension>.7 hostility<.5|tension:.18||关系紧绷但尚未进入明确敌意
hostile_vigilance|hostility>.75 trust<.3|aggression:.14,withdrawal:.1||敌意与不信任并存，保留进退选择
trusted_disagreement|trust>.7 tension>.6|self_control:.15|volume:-.03|冲突未抹去信任时偏向控制表达
intimate_safety|intimacy>.75 trust>.7|warmth:.2|amplitude:.04|亲密且可信时允许较充分的温柔
intimate_hurt|intimacy>.7 tension>.65|tension:.12,withdrawal:.1||亲密关系中的受伤既牵挂又防御
formal_deference|dominance<-.6 familiarity<.4|deference:.18|directness:-.05|地位差和陌生感共同增强礼节性收敛
responsible_authority|dominance>.6 affinity>.6|self_control:.1,warmth:.08|pace:-.03|较强地位伴随好感时倾向稳住互动
coercive_distance|dominance>.6 hostility>.7|aggression:.18|directness:.05|强势敌意增加压迫性表达但不自动造成伤害
ambivalent_attachment|affinity>.7 trust<.3|warmth:.1,withdrawal:.13||仍有好感却不敢交付信任，形成接近退避混合
reconciliation_opening|tension>.5 trust>.6 affinity>.6|warmth:.16,self_control:.08||有修复基础的冲突允许试探性缓和
"""


def records(text, kind):
    result = []
    for line in text.strip().splitlines():
        key, conditions, semantics, parameters, purpose = line.split("|")
        when = {}
        for term in conditions.split():
            op = ">" if ">" in term else "<"
            field, number = term.split(op)
            when[f"{kind}.{field}"] = {"gt" if op == ">" else "lt": float(number)}
        def coefficients(value, prefix=""):
            return {prefix + pair.split(":")[0]: float(pair.split(":")[1]) for pair in value.split(",") if pair}
        result.append(dict(id=f"modifier.{key}", kind=kind, when=when,
            effects=dict(score_add=coefficients(semantics, "semantic."), parameter_add=coefficients(parameters)),
            description_zh=purpose, source_refs=["src.original.catalog.v1"]))
    return result


def main():
    result = records(PERSONALITY, "personality") + records(RELATIONSHIP, "relationship")
    (ROOT / "data/catalog/modifiers.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
