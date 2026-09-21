# 原创目录格式

每个 JSON 文件为记录列表；每条记录单独编写，禁止组合循环或同义词扩写凑数。

必填：`id`（完整英文命名空间 ID），`category`，`channel`，`parts`（身体部位列表），`family`（共享语义家族，用于反重复，不要为每条造独立家族），`meaning`（该行为独特意义及与邻近动作的差别），`clause`（可直接接在人物姓名后面的原创中文短句，不含终止句号），`emotions`（2–4 个已有或新增情绪 ID），`axis`（initiative/withdrawal/self_control/aggression/warmth/tension/deference）。

可选：`facts`（必须由 Context.facts 明确给出的事实标签），`preconditions`（standing/seated/target_known/right_hand_free/left_hand_free/right_hand_holding/left_hand_holding 等现有合法谓词），`effects`（现有物理状态效果），`capabilities`，`visibility`，`world`（完整 world_requirements），`facial_actions`（微表情的不同解剖动作列表，region/action/intensity），`intensity`（默认 [.15,.95]）。

编辑清理使用 `editorial_status: rejected`、不少于 6 字的 `editorial_note` 和有效 `replacement_id` 保留淘汰依据。被拒条目仍留在作者目录并编译为 `deprecated` 供旧计划兼容，但规划器和盲评包生成器必须排除，不能进入新的正文候选。未写状态时默认为 `active`。

微表情必须 facial_actions，不把微表情当情绪测谎证据；时序是虚构叙事参数。所有对象/环境/对方动作/前态都需 facts 或正式状态前提；不让普通输入凭空出现杯子、伤口、哭泣、笑容、衣饰、门窗。空间条目以合法距离/朝向变化或已明确地标的静态关系为主，不绕过导航瞬移。修仙每条明确能力、境界、成本、控制、激活/回收前提；不凭空破坏、强控对方或恢复资源。

新增情绪可用：amusement, annoyance, approval, caring, confusion, desire, disapproval, excitement, grief, nervousness, optimism, realization, shame, guilt, loneliness, longing, nostalgia, homesickness, awe, reverence, compassion, tenderness, trust, suspicion, contempt, frustration, impatience, helplessness, despair, anxiety, dread, unease, contentment, serenity, satisfaction, confidence, determination, resolve, boredom, interest, anticipation, vulnerability, hurt, humiliation, defiance, resignation, schadenfreude, ambivalence。

已有情绪：anger fear joy sadness disgust surprise admiration embarrassment gratitude disappointment curiosity remorse pride love jealousy relief resentment hope；calm 为现有掩饰态，也允许引用。情绪与身体行为多对多，不永久绑定。
