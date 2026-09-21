"""Original narrative distinctions and engineering VAD priors, not measured norms."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMOTIONS = """
amusement|觉得好笑|.65,.35,.2|positive social|被具体趣事逗乐，区别于不依赖笑料的喜悦
annoyance|烦扰|-.35,.35,.3|conflict|小阻碍持续打断当前任务，区别于强烈追责的愤怒
approval|赞许|.55,.1,.35|social moral|认可具体选择或表现，区别于仰视整个人的钦佩
caring|关切|.35,.2,.15|attachment relational|关注他人的需要并准备照顾，区别于欣赏或占有
confusion|困惑|-.15,.25,-.25|cognitive|线索互相冲突尚不能理解，区别于主动寻求新知的好奇
desire|渴求|.35,.55,.1|motivational|想获得尚未拥有的对象，区别于已有事物带来的满足
disapproval|不赞同|-.3,.15,.35|social moral|否定具体行为或判断，区别于对整个人的轻蔑
excitement|兴奋|.7,.85,.4|positive motivational|积极事件引起明显动员，区别于安定满足
grief|哀恸|-.9,.2,-.7|loss attachment|重大且不可逆丧失引发的悲痛，区别于暂时挫折
nervousness|紧张|-.35,.55,-.3|defensive social|临近具体表现任务时的不稳，区别于无明确期限的焦虑
optimism|乐观|.65,.15,.4|cognitive positive|倾向预期有利结果，区别于针对一个愿望的希望
realization|恍然|.2,.45,.35|cognitive|信息刚刚接通形成理解，区别于持续探究
shame|羞耻|-.65,.35,-.65|moral social|觉得自身形象或价值暴露缺陷，区别于仅对行为负责的内疚
guilt|内疚|-.6,.2,-.3|moral relational|意识到自己使他人受损并承担责任，区别于社交失态
loneliness|孤独|-.55,-.3,-.35|attachment loss|缺乏所需连接而感到隔绝，区别于主动独处
longing|思念|-.15,.2,-.2|attachment|渴望与特定离开者重逢，区别于泛泛缺少陪伴
nostalgia|怀旧|.2,-.1,.05|memory complex|过去片段带来温暖和失落并存，区别于当下目标受阻
homesickness|思乡|-.3,.05,-.25|attachment memory|思念熟悉的归属环境，区别于仅思念某个人
awe|震撼|.3,.6,-.55|cognitive complex|面对超出原有理解的宏大事物，区别于一次突发惊讶
reverence|敬畏|.35,.05,-.4|social moral|面对承认其权威或价值的对象主动收敛，区别于危险恐惧
compassion|悲悯|-.05,.2,.2|relational moral|被他人困境触动并愿意减轻痛苦，区别于自身悲伤
tenderness|怜爱|.65,-.2,.05|attachment|对脆弱或珍视对象温柔保护，区别于热烈占有
trust|信任|.55,-.3,.2|relational|愿意把一部分不确定性交给对方，区别于熟悉或盲从
suspicion|猜疑|-.35,.35,.05|relational cognitive|怀疑表面信息隐含不利动机，区别于尚未理解
contempt|轻蔑|-.45,.05,.7|relational conflict|贬低对象的价值或资格，区别于只反对一次行为
frustration|挫败|-.55,.55,.05|motivational conflict|努力反复被阻断但仍想达成目标，区别于放弃后的绝望
impatience|不耐烦|-.3,.45,.4|motivational|等待成本高于容忍而催促推进，区别于对动机的怨恨
helplessness|无助|-.7,-.15,-.85|defensive|觉得缺乏改变局面的手段，区别于尚能行动的害怕
despair|绝望|-.9,-.45,-.8|loss motivational|认为重要目标已无实现可能，区别于仍保留办法的失望
anxiety|焦虑|-.55,.65,-.35|defensive cognitive|围绕多种未定风险持续担忧，区别于眼前明确威胁
dread|惶惧|-.8,.35,-.6|defensive anticipation|确信不利事件正在逼近而不愿面对，区别于一般不确定
unease|不安|-.3,.2,-.15|defensive|感觉有异样但尚无明确解释，区别于已锁定动机的猜疑
contentment|知足|.65,-.45,.2|positive|接受已有处境并无需更多，区别于刚完成任务的满足
serenity|安宁|.5,-.65,.3|positive regulated|威胁和内在冲突退去后的安稳，区别于对外掩饰的平静
satisfaction|满足|.7,-.1,.5|positive motivational|具体需要或任务已得到充分满足，区别于泛化乐观
confidence|自信|.55,.2,.75|motivational|相信自己具备应对能力，区别于已经取得结果的自豪
determination|奋意|.25,.65,.7|motivational|为了困难目标主动投入努力，区别于单次下定决定
resolve|决意|.1,.15,.8|motivational regulated|在冲突选项间已完成取舍，区别于仍在审慎权衡
boredom|无聊|-.2,-.65,.05|cognitive|缺少足够刺激而注意游离，区别于体力疲惫
interest|兴味|.4,.2,.2|cognitive|愿意持续接触一个对象，区别于只想解开疑问
anticipation|期待|.4,.45,.1|motivational|等待一件具体事件到来，区别于长期总体乐观
vulnerability|脆弱感|-.45,.15,-.6|relational defensive|意识到自己可能被伤害却缺少保护，区别于已经被羞辱
hurt|受伤感|-.65,.3,-.35|relational|重要关系中的言行刺痛自己，区别于身体伤势
humiliation|屈辱|-.8,.5,-.6|social conflict|尊严遭到外部贬损且无法立即挽回，区别于自我羞耻
defiance|抗拒|-.15,.65,.7|conflict motivational|面对强加要求仍拒绝服从，区别于主动侵犯
resignation|认命|-.35,-.5,-.55|loss regulated|停止抵抗已接受不利结果，区别于仍在寻找援助的无助
schadenfreude|幸灾乐祸|.45,.35,.4|social complex|他人受挫让自己产生快意，区别于普通幽默愉悦
ambivalence|矛盾|-.05,.25,-.2|complex cognitive|同一对象同时激起接近和退避，区别于没有理解信息
"""


def main():
    records = []
    for line in EMOTIONS.strip().splitlines():
        key, label, vad, families, meaning = line.split("|")
        records.append(dict(id=key, label_zh=label, families=families.split(), aliases=[],
            prototype_vad=dict(zip(("valence", "arousal", "dominance"), map(float, vad.split(",")))),
            description_zh=meaning, source_refs=["src.original.catalog.v1"]))
    (ROOT / "data/catalog/emotions.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
