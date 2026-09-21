# Character Performance Pack V2 实现文档

> 实施进度（2026-09-21）：已推进至 0.3.0，新增已知路径导航、持续移动与暂停恢复，详见 [本轮阶段报告](phase-reports/continuity-0.3.md)、[动作样本](evaluation/blocking.md) 与 [离线评估](evaluation/latest.md)。本文仍是完整 v1.0 目标规范；未以局部测试通过替代全量退出条件。

> 文档状态：Draft v0.1  
> 文档类型：架构设计 + 数据契约 + 实施计划  
> 适用对象：小说 Agent、Character/NPC Agent、Narrator/Director Agent、世界模拟与 RPG/TRPG 系统  
> 原始需求：Character Performance Pack V2 提示词  
> 目标版本：MVP → v1.0 生产可用版

## 1. 文档目的

本文将原始概念提示词转换为可开发、可测试、可审计的实现规范。系统的交付物不是动作句库，而是一套与具体大模型解耦的角色表演基础设施：

1. Character Performance Ontology：统一描述情绪、面部、视线、身体、空间、生理、言语和世界观行为。
2. Character State Model：保存角色内在状态、外在姿态、关系、位置、持有物与历史残留。
3. Composition Engine：从状态检索、约束、修正、排序并组合原子行为。
4. Continuity Engine：验证表演计划的物理与时序连续性。
5. Anti-Repetition Engine：在语义层而非字符串层抑制重复。
6. Narrative Renderer：把结构化表演计划渲染为中文小说表达。
7. Genre Adapter：把通用行为映射到修仙等具体世界规则。

本文中的“必须 / 禁止”属于规范性要求；“建议默认值”可在实现时通过 ADR（Architecture Decision Record）替换。

## 2. 成功标准

系统成功不以词条数量衡量，而以行为区分度、连续性和可控性衡量。v1.0 必须满足：

- 同一事件输入给不同人格角色时，表演计划具有稳定且可解释的差异。
- 同一角色面对不同关系对象时，通道选择、幅度、距离与言语表现不同。
- 相同情绪在不同强度、唤醒度和控制力下产生不同表现。
- 内在状态与外显状态可分离，并可通过微弱泄露信号暗示冲突。
- 动作、位置、朝向、持有物和伤势不会无过渡跳变。
- 长对话中不会只靠改写句子重复同一语义动作。
- 超自然行为符合境界、能力、消耗和世界规则。
- Renderer 不直接暴露内部标签、分数、选择理由或 YAML 字段。
- 核心推理可在不依赖 LLM 的情况下运行；更换 LLM 不改变核心行为逻辑。
- 相同输入、规则版本和随机种子可复现相同 Performance Plan。

## 3. 范围

### 3.1 v1.0 范围内

- 事件与认知结果的标准输入契约。
- 分层情绪本体、VAD 连续空间和复合情绪状态。
- 面部、微表情、视线、身体、空间、生理、言语表现的原子单元。
- 人格、关系、上下文、身体状态修正器。
- 掩饰与泄露规划。
- 表演预算、连续性、冲突检测、反重复和排序。
- 中文小说 Renderer 接口与一个参考实现。
- 修仙 World Adapter 与规则校验接口。
- 来源、许可、版本与派生链追踪。
- 离线评估、回归测试与可观察性。

### 3.2 v1.0 范围外

- 自动决定完整剧情走向。
- 替代 Dialogue Agent 决定台词语义内容。
- 端到端训练新的情绪识别或生成模型。
- 复制并再分发许可不明确的数据集原文。
- 穷举所有动作、表情或文学句式。
- 用 LLM 自由生成未经 Schema 验证的生产数据。

## 4. 设计原则与工程约束

| 原则 | 工程落点 |
|---|---|
| Source First | 所有非原创单元必须有 `source_ref`，导入前通过许可门禁。 |
| Ontology First | Adapter 只能写入 Canonical Schema，不允许运行时直接消费源数据结构。 |
| Atomic Behaviour First | 单元描述最小可组合行为及其语义，不存整句小说描写。 |
| Composition Over Enumeration | 差异来自状态、修正器、规则和组合，不来自近义条目膨胀。 |
| State Before Rendering | Renderer 只消费已验证的 Performance Plan，不重新决定人物状态。 |
| Hard Constraints Before Scores | 物理、世界观、许可和连续性硬约束不得被高分候选覆盖。 |
| Explainable Planning | 每次筛选和选中均保留机器可读原因，但不进入正文。 |
| Deterministic Core | 规则版本 + 输入 + seed 决定结果，便于回归。 |
| Graceful Degradation | 缺少可用候选时允许少写或不写，不用错误动作填满预算。 |

## 5. 推荐参考技术栈

本规范本身与语言无关。若没有既有平台约束，建议默认采用：

- Python 3.12+：核心引擎、离线数据管线和测试。
- Pydantic v2：运行时数据验证与 JSON Schema 导出。
- YAML：人工维护的小规模本体和规则；构建时编译为 JSON/SQLite。
- SQLite：MVP 的索引、来源注册表和本地历史存储。
- PostgreSQL：多租户或并发服务化部署时替换 SQLite。
- NumPy：向量评分；候选规模扩大后可选 FAISS/pgvector 做近邻检索。
- pytest + Hypothesis：示例测试、性质测试和状态机测试。
- FastAPI（可选）：服务化 API；核心包不得依赖 Web 框架。

选择这些技术只是建议默认值。核心领域包必须通过端口接口隔离存储、嵌入模型和 LLM。

## 6. 总体架构

```text
离线构建链
Source Registry → Source Adapter → Normalizer → Deduplicator
                → Conflict/Lint → License Gate → Compiled Performance Pack

运行时链
Event + Cognition + Character/Relationship/World State
  → Emotion State Builder
  → Candidate Retriever
  → Hard Constraint Filter
  → Modifier Pipeline
  → Masking & Leak Planner
  → Continuity Validator
  → Anti-Repetition Penalty
  → Narrative Value Ranker
  → Budgeted Composer
  → Genre Adapter + World Rule Validator
  → Performance Plan
  → Narrative Renderer
  → State Transition Commit
```

### 6.1 组件边界

| 组件 | 职责 | 不得负责 |
|---|---|---|
| Source Registry | 来源、版本、许可和校验记录 | 运行时选动作 |
| Ontology Pack | 存储标准化本体和原子单元 | 生成小说句子 |
| Emotion State Builder | 生成离散标签 + VAD + 强度等状态 | 选择具体动作 |
| Candidate Retriever | 召回可能的原子单元 | 绕过硬约束 |
| Modifier Pipeline | 调整候选概率、幅度和参数 | 直接锁死具体动作 |
| Masking Planner | 分离 surface 与 leak | 解释台词内容 |
| Continuity Engine | 校验并产出状态变更 | 猜测未知位置 |
| Repetition Engine | 惩罚语义、通道和修辞重复 | 仅做字符串匹配 |
| Composer | 在预算内选兼容组合 | 写正文 |
| Genre Adapter | 通用语义到世界表现映射 | 绕过世界规则 |
| Renderer | 实现“怎么写 / 怎么说” | 改写已确定的内在状态 |

## 7. 核心领域模型

### 7.1 数值约定

- 归一化强度、概率、亲密度等默认范围为 `[0.0, 1.0]`。
- VAD 范围为 `[-1.0, 1.0]`。
- 双向关系属性（如 dominance）以当前角色为观察主体；`1.0` 表示主体强势，`-1.0` 表示主体弱势。
- 时间统一使用毫秒；场景内可额外使用单调递增 `turn_index`。
- 所有枚举必须有 `unknown`，但生产数据不得用 `unknown` 掩盖可修复缺失。

### 7.2 EmotionState

```yaml
emotion_state:
  primary: anger
  secondary: disappointment
  families: [conflict, relational]
  intensity: 0.68
  vad: {valence: -0.74, arousal: 0.61, dominance: 0.72}
  restraint: 0.87
  awareness: 0.76
  duration_ms: 48000
  decay_half_life_ms: 90000
  trigger_refs: [event.public_humiliation]
  appraisal:
    goal_congruence: -0.9
    controllability: 0.7
    responsibility: target
    certainty: 0.85
```

`primary` 是当前选择权重最高的离散情绪；`secondary` 可为空。标签不得替代 VAD，VAD 也不得替代语义标签。

### 7.3 CharacterProfile

```yaml
character:
  id: char.luo_han
  personality:
    big_five:
      openness: 0.42
      conscientiousness: 0.88
      extraversion: 0.18
      agreeableness: 0.31
      neuroticism: 0.24
    learned_modifiers: [modifier.disciplined_swordsman]
  expression_baseline:
    amplitude: 0.28
    initiative: 0.34
    speech_volume: 0.40
    gaze_duration: 0.55
  capabilities: [vision, speech, right_hand_use, qi_control]
  signature_behaviours:
    - unit_id: body.thumb_touch_sword_guard
      affinity: 0.65
      cooldown_turns: 9
```

Big Five 只是一个输入维度。角色特质、习得习惯和签名行为均通过 Modifier 影响概率或参数，不直接跳过候选流程。

### 7.4 RelationshipState

```yaml
relationship:
  subject_id: char.luo_han
  target_id: char.master
  type_tags: [master_disciple]
  affinity: 0.72
  trust: 0.81
  familiarity: 0.90
  dominance: -0.66
  dependence: 0.58
  tension: 0.21
  hostility: 0.03
  intimacy: 0.44
  public_role_constraints: [sect_etiquette]
```

关系状态按方向保存；A 对 B 的依赖不等于 B 对 A 的依赖。

### 7.5 PhysicalState 与 SceneState

```yaml
physical_state:
  fatigue: 0.36
  pain: 0.12
  injuries:
    - body_part: left_shoulder
      severity: 0.45
      constraints: [no_overhead_reach]
  mobility: 0.92
  breath_capacity: 0.84
  motor_control: 0.95
  sensory_constraints: []

scene_state:
  scene_id: scene.0042
  turn_index: 17
  pose: standing
  position: pos.north_window
  orientation_target: char.enemy
  held_objects:
    right_hand: object.sword
  distances:
    char.enemy: 3.2
    door.east: 5.7
  support_contact: null
  unfinished_actions: []
  emotional_residue:
    - emotion: shame
      intensity: 0.22
      expires_after_turn: 25
```

### 7.6 PerformanceUnit

```yaml
id: body.hand_clench
schema_version: 1.0.0
category: body
channel: hands
atomic_action: hand_clench
body_parts: [hand, fingers]
semantic_groups: [hand_tension, restraint_leak]
semantics:
  tension: 0.80
  aggression: 0.42
  withdrawal: 0.00
  self_control: 0.48
emotion_affinity:
  anger: 0.70
  anxiety: 0.46
vad_affinity:
  center: {valence: -0.45, arousal: 0.64, dominance: 0.35}
  tolerance: {valence: 0.45, arousal: 0.35, dominance: 0.55}
intensity_range: {min: 0.25, max: 0.85}
personality_bias: []
relationship_bias: []
context_requirements:
  any: [conversation, confrontation, waiting]
physical_requirements:
  capabilities: [hand_use]
  forbidden_injuries: [severe_hand_injury]
preconditions:
  - right_hand_free_or_clenchable
effects:
  pose_patch: {}
  held_object_patch: {}
conflicts: [body.relaxed_hand, body.open_palm_display]
compatible_with: [gaze.target_lock, speech.slow_pace]
visibility: subtle
narrative_weight: 0.62
cooldown:
  turns: 4
  scene_scope: true
repeat_group: hand_tension
render_hints:
  verbs: [收紧, 扣紧]
  avoid_explicit_emotion_name: true
source_refs: [src.original.hand_clench.v1]
license_class: original
status: active
```

强制字段：`id`、`category`、`channel`、`atomic_action`、`semantic_groups`、`semantics`、`intensity_range`、`conflicts`、`visibility`、`narrative_weight`、`cooldown`、`repeat_group`、`source_refs`、`license_class`、`status`。

### 7.7 MicroExpressionUnit

微表情是 `PerformanceUnit` 的特化，不把面部动作永久绑定为单一情绪。

```yaml
id: facial.brow_lower_lip_press_micro
category: micro_expression
channel: facial
facial_units:
  - {region: brow, action: lower, au_ref: AU4, intensity: 0.35}
  - {region: lips, action: press, au_ref: AU24, intensity: 0.28}
timing:
  onset_ms: [40, 120]
  apex_ms: [60, 180]
  offset_ms: [80, 260]
  total_duration_ms: [180, 500]
visibility: very_subtle
leak_probability: 0.48
possible_internal_states: [anger, concentration, anxiety]
masking_relation: contradicts_surface_calm
narrative_priority: 0.58
```

`au_ref` 仅是来源概念引用；若所用 FACS 材料存在许可限制，项目不得打包受限原始材料或照片。

### 7.8 Modifier

```yaml
id: modifier.high_introversion
kind: personality
when:
  personality.extraversion: {lt: 0.25}
effects:
  score_add:
    channel.speech: -0.10
    semantic.initiative: -0.20
  parameter_add:
    expression_amplitude: -0.25
    speech_volume: -0.15
    gaze_duration: -0.10
  budget_add:
    speech: -1
priority: 40
stacking: additive_clamped
```

Modifier 的结果必须被截断到字段合法范围。多修正器的默认执行顺序为：人格 → 关系 → 场景 → 身体 → 叙事导演 → 世界规则。硬约束不属于 Modifier。

### 7.9 PerformancePlan

```yaml
performance_plan:
  plan_id: plan.01J...
  schema_version: 1.0.0
  subject_id: char.luo_han
  target_ids: [char.enemy]
  scene_id: scene.0042
  turn_index: 17
  seed: 938102
  primary_signal: body.hand_clench
  secondary_signals: [gaze.target_lock]
  surface_signals: [speech.slow_pace]
  leak_signals: [body.finger_pause]
  selected:
    facial: []
    gaze: [gaze.target_lock]
    body: [body.hand_clench]
    spatial: []
    physiology: []
    speech: [speech.slow_pace]
    world_specific: []
  parameters:
    body.hand_clench: {side: left, amplitude: 0.31}
    speech.slow_pace: {pace: 0.35, pause_ms: 420}
  state_transition:
    preconditions: [left_hand_free]
    effects: []
  suppressed_candidates:
    - unit_id: physiology.tremble
      reasons: [mask_strength_high, over_budget]
  diagnostics_ref: diag.01J...
```

## 8. 来源与许可管线

### 8.1 SourceRecord

```yaml
id: src.goemotions.taxonomy.v1
name: GoEmotions
source_type: academic_dataset
official_url: https://...
version: pinned-version-or-commit
retrieved_at: 2026-09-21
concepts_used: [emotion_labels, label_relations]
usage_mode: derived_metadata
license:
  identifier: pending_verification
  commercial_use: unknown
  redistribution: unknown
  attribution_required: unknown
  evidence_urls: []
review:
  status: pending
  reviewer: null
  reviewed_at: null
content_hash: null
```

### 8.2 许可分类

每个来源必须归入且只归入以下运行类别：

- `reference_only`：只引用研究概念，禁止导入或分发原始数据。
- `derived_metadata`：允许人工抽象后的分类、关系或统计元数据；不得保留可还原原文。
- `transform_allowed`：可按许可转换，但必须记录转换脚本与归属。
- `redistribution_allowed`：可随 Pack 分发，仍需遵守署名和同许可要求。
- `original`：项目原创；记录作者和创建版本。
- `blocked`：许可不明、冲突或明令禁止，不进入构建产物。

### 8.3 构建门禁

`pack build` 必须失败于以下任一情况：

- `source_refs` 不存在。
- 来源审计状态不是 `approved`。
- 使用方式超出许可分类。
- 缺失版本、证据 URL 或必要署名。
- 派生条目仍包含源数据可识别的长文本、媒体或个人数据。
- 构建目标为商业分发，但来源未确认商业使用权。

完整的初步来源审计独立保存于 [source-license-audit.md](./source-license-audit.md)；其状态不得被本文概述替代。

## 9. 离线数据构建流程

### 9.1 Adapter 接口

```python
class SourceAdapter(Protocol):
    source_id: str

    def extract(self, source_path: Path) -> Iterable[RawConcept]: ...
    def normalize(self, item: RawConcept) -> Iterable[CanonicalDraft]: ...
    def provenance(self, item: RawConcept) -> ProvenanceRecord: ...
```

Adapter 只负责可追踪转换；不得在其中偷偷做最终渲染或人物化决策。

### 9.2 标准构建步骤

1. 锁定来源版本与内容哈希。
2. 验证许可证和允许的 `usage_mode`。
3. 提取源概念，保留 source-local ID。
4. 映射到 Canonical Draft。
5. Schema 校验与数值归一化。
6. 计算语义指纹：category、channel、body part、semantic groups、preconditions、effects。
7. 执行精确重复和近义重复检测。
8. 执行冲突图、兼容图和不可达规则检测。
9. 人工审阅低置信度映射。
10. 编译只读 Pack，生成版本、哈希、来源清单和测试报告。

### 9.3 去重策略

重复检测分三层：

- Identity：ID 或规范化字段完全相同，自动拒绝。
- Semantic group：如“握拳 / 五指收紧 / 指节泛白”共同落入 `hand_tension`，默认合并为一个行为及不同参数/渲染提示。
- Embedding candidate：语义向量相似度超过建议阈值 `0.88` 时进入人工复核，不自动删除。

不得只因动词不同而保留新单元。只有当 precondition、effect、叙事功能或可组合性显著不同，才允许同组多单元共存。

## 10. 运行时输入契约

```yaml
performance_request:
  request_id: req.01J...
  event:
    id: event.public_humiliation
    participants: [char.luo_han, char.enemy]
    salience: 0.78
    publicness: 0.94
    threat: {physical: 0.15, social: 0.86}
  cognition:
    subject_id: char.luo_han
    interpretation: deliberate_status_attack
    goal_impact: -0.76
    controllability: 0.71
    certainty: 0.88
    target_responsibility: 0.92
  emotion_state: {}
  character_ref: char.luo_han
  relationship_ref: rel.luo_han.enemy
  context:
    activity: conversation
    audience_size: 24
    privacy: public
    formality: 0.73
    danger_level: 0.31
  physical_state: {}
  scene_state: {}
  world_state_ref: world.xianxia.default
  history_ref: hist.scene.0042.char.luo_han
  director:
    beat_importance: 0.62
    desired_visibility: subtle
    max_signals: 3
  seed: 938102
```

如果调用方已提供 `emotion_state`，引擎验证后直接使用；否则由 Emotion State Builder 基于 event + cognition + residue 构建。缺失关键事实时返回显式 warning，不得用 Renderer 补造事实。

## 11. 候选召回与硬约束

### 11.1 召回

候选召回使用可解释的倒排索引作为第一层：

- emotion label / family
- VAD 区域
- channel / body part
- context tag
- semantic group
- world adapter capability

可选的向量召回只能扩大候选集，不能绕过后续硬约束。

### 11.2 硬约束顺序

1. Schema 与版本兼容。
2. 来源许可允许当前运行/分发模式。
3. 角色能力与身体条件满足。
4. 场景物理条件满足。
5. 与当前姿态、持有物和未完成动作不冲突。
6. 与已选候选的 `conflicts` 不冲突。
7. 世界规则和力量等级允许。
8. 未被显式禁用，且状态为 `active`。

硬约束失败的候选进入 `suppressed_candidates` 诊断，绝不通过降低分数“软处理”。

## 12. 修正、评分与选择

### 12.1 建议默认评分公式

```text
score(u) =
    1.20 * emotion_affinity(u, E)
  + 0.80 * vad_similarity(u, E.vad)
  + 0.65 * context_fit(u, C)
  + 0.55 * narrative_value(u, D)
  + personality_modifier(u, P)
  + relationship_modifier(u, R)
  + physical_modifier(u, H)
  + signature_bonus(u, S)
  + controlled_jitter(seed, u, ±0.05)
  - repetition_penalty(u, History)
  - continuity_cost(u, Scene)
  - channel_saturation(u, PartialPlan)
```

权重必须配置化、版本化，并由离线评估校准。任何硬约束不得表现为一个有限负分。

### 12.2 选择策略

- 先按通道生成 shortlist，再做跨通道组合，避免身体候选数量压倒微表情等小类。
- 在 shortlist 内使用 temperature-controlled softmax 或 top-k sampling；生产默认 `temperature=0.35`。
- 关键剧情可降低 temperature 以增强稳定性；日常段落可略增以获得变化。
- 随机性只用于同等合理候选间选择，不能制造与状态无关的动作。
- 组合完成后必须二次执行冲突、预算和连续性验证。

## 13. Emotion Masking 与 Leak

### 13.1 状态表示

```yaml
masking:
  internal_emotion: fear
  displayed_emotion: calm
  mask_strength: 0.88
  motive: protect_status
  control_capacity: 0.91
  leak_pressure: 0.63
```

### 13.2 规划规则

1. 计算 `effective_mask = clamp(mask_strength × control_capacity × (1 - impairment))`。
2. Surface 候选优先匹配 displayed emotion、社会角色和当前活动。
3. Leak 候选匹配 internal emotion，但限制在 subtle/very_subtle 通道。
4. 建议默认泄露概率：`sigmoid(3 × (arousal + intensity + leak_pressure - effective_mask - 1.2))`。
5. 高掩饰时禁止选择明显颤抖、逃跑、尖叫等强外显动作，除非生理或世界规则判定控制失败。
6. Surface 与 Leak 应形成可读张力，但不能互相物理冲突。
7. Renderer 不得写“表面平静，其实害怕”；只渲染信号。

## 14. Performance Budget

### 14.1 默认预算

| 场景等级 | 总信号数 | 推荐通道 |
|---|---:|---|
| filler / 过渡 | 0–1 | speech 或 body |
| 普通对话 | 1–2 | speech + facial/body 二选一 |
| 重要情绪 | 2–4 | 至少两个不同通道 |
| 高潮 | 3–6 | 由 Director 指定，仍需防堆砌 |

示例：

```yaml
budget:
  total: 3
  facial: 0
  gaze: 1
  body: 1
  spatial: 0
  physiology: 0
  speech: 1
  world_specific: 0
```

预算是上限，不是必须填满的配额。若一个信号已足够，Composer 应提前停止。

### 14.2 边际叙事价值停止条件

新增候选只有在满足以下条件时才进入计划：

```text
marginal_value = new_information + contrast + characterization
                 - redundancy - prose_load - continuity_cost
```

建议默认 `marginal_value < 0.15` 时停止追加。

## 15. 反重复引擎

### 15.1 历史记录

```yaml
history_entry:
  turn_index: 17
  unit_id: body.hand_clench
  semantic_groups: [hand_tension, restraint_leak]
  channel: hands
  render_features:
    verbs: [收紧]
    metaphor_group: none
  intensity: 0.31
```

分别维护：动作、表情、视线、生理、空间、言语模式、修辞组和通道的近期窗口。

### 15.2 惩罚

```text
repeat_penalty =
    exact_unit_penalty(decayed turns)
  + semantic_group_penalty(decayed turns)
  + channel_saturation_penalty(window)
  + render_phrase_penalty(n-gram / lemma)
  + metaphor_group_penalty(window)
```

建议默认：同一单元 4 回合内强惩罚；同一语义组 6 回合内中等惩罚；同一通道连续 3 回合逐级惩罚。若动作由连续性强制保持，不视为新动作重复，而标记为 `continuation` 并尽量不重复渲染。

## 16. 连续性引擎

### 16.1 行为作为状态变换

每个会改变物理状态的单元必须声明：

- preconditions：执行前必须成立。
- effects：执行后的 state patch。
- duration / completion：瞬时、持续或未完成。
- interruption policy：可否被打断以及被打断后的状态。
- transition cost：需要过渡的幅度。

例如“走到桌边坐下”不应作为一个不可拆原子单元，而应分解为 approach → orient → sit；Composer 可把连续单元打包为一个 sequence。

### 16.2 提交协议

1. Planner 基于 SceneState 快照生成计划。
2. Continuity Engine 模拟执行 state patch。
3. Renderer 成功后，由调用方提交 transition。
4. 若渲染或下游生成失败，不提交状态。
5. 多角色并发时使用 `scene_revision` 乐观锁；版本冲突需重算。

### 16.3 不可恢复冲突

找不到合法过渡时返回结构化错误：

```yaml
error:
  code: CONTINUITY_NO_VALID_TRANSITION
  subject_id: char.luo_han
  conflicting_facts: [pose.leaning_wall, requested.sit_at_table]
  required_bridge: [leave_wall, approach_table, sit]
```

不得由 Renderer 用含糊文字掩盖状态冲突。

## 17. 言语表现与潜台词

Speech Performance 只描述“怎么说”，不决定“说什么”。

```yaml
speech_performance:
  tone: restrained
  pace: 0.35
  rhythm: measured
  volume: 0.42
  pause_ms: [180, 520]
  hesitation: 0.08
  repetition: 0.02
  interruption_tendency: 0.15
  sentence_length_bias: short
  directness: 0.72
  emotional_leak: 0.18
  dialogue_act_constraints: [answer, warning]
  subtext_intent: conceal_fear_preserve_status
```

Dialogue Agent 提供语义草稿和 dialogue act；Performance Engine 返回表现约束；Renderer 或 Dialogue Realizer 将二者合成。若语义与表演冲突，应返回诊断给上游，不擅自更改事实或承诺。

## 18. 修仙 Genre Adapter

### 18.1 接口

```python
class GenreAdapter(Protocol):
    genre_id: str

    def expand_candidates(
        self, generic_units, character, world_state
    ) -> list[PerformanceUnit]: ...

    def map_unit(
        self, unit, character, target, world_state
    ) -> list[WorldSpecificCandidate]: ...

    def validate(
        self, candidate, character, world_state
    ) -> ValidationResult: ...
```

### 18.2 通用语义映射

| 通用语义 | 可映射修仙通道 | 条件示例 |
|---|---|---|
| attention | gaze / spiritual_sense / qi_perception | 具备感知能力且范围足够 |
| threatening_presence | posture / aura / pressure / killing_intent | 控制力、敌意和场景允许 |
| physical_tension | meridian_tension / qi_circulation / weapon_intent | 已修炼对应体系 |
| avoidance | withdraw_sense / suppress_aura / escape_art_preparation | 技能、消耗、空间允许 |

### 18.3 WorldRule

```yaml
world_rule:
  id: xianxia.spiritual_sense.range
  applies_to: spiritual_sense_scan
  requirements:
    capabilities: [spiritual_sense]
    min_realm: foundation_establishment
  formula: min(base_range_by_realm * control_factor, world_cap)
  costs:
    qi: 0.04
    concentration: 0.12
  forbidden_contexts: [sealed_domain]
```

校验必须考虑 realm、stage、相对实力、控制力、资源消耗、伤势、阵法/领域限制和场景破坏上限。低强度情绪不能单独驱动大范围破坏性表现。

## 19. Narrative Renderer

### 19.1 输入输出

Renderer 输入：

- 已验证 Performance Plan。
- 当前段落视角、时态、叙述距离和风格约束。
- Dialogue Agent 产出的可选语义台词。
- 允许引用的场景实体与可见事实。

Renderer 输出：

```yaml
render_result:
  text: "他的目光在对方身上停了片刻……"
  realized_units:
    body.hand_clench: "手指缓缓收紧"
    gaze.target_lock: "目光在对方身上停了片刻"
    speech.slow_pace: "再开口时，语速慢了几分"
  omitted_units: []
  introduced_facts: []
  warnings: []
```

### 19.2 两级实现

1. Deterministic Renderer：模板不是成品句库，而是语法槽位与约束；用于测试、降级和可复现输出。
2. LLM Renderer：把 Plan 实现为自然中文；必须经输出检查器验证，不得新增位置、道具、伤势、能力或情绪事实。

### 19.3 输出检查

- 禁止显式输出内部字段名、数值和选择理由。
- 禁止使用计划外的高强度动作。
- 禁止新增未提供实体或世界事实。
- 检查 realized unit 覆盖率；允许省略，但必须记录。
- 检查近期短语、意象和句法重复。
- 若无法可靠实现，回退到 deterministic renderer 或返回错误，不重新规划。

## 20. 服务与包接口

### 20.1 核心 Python API

```python
class PerformanceEngine:
    def plan(self, request: PerformanceRequest) -> PerformancePlan: ...
    def validate(self, plan: PerformancePlan) -> ValidationReport: ...
    def commit(self, plan_id: str, expected_scene_revision: int) -> CommitResult: ...

class NarrativeRenderer:
    def render(
        self, plan: PerformancePlan, context: RenderContext
    ) -> RenderResult: ...
```

### 20.2 可选 REST API

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v1/performance/plan` | 生成未提交计划 |
| POST | `/v1/performance/plans/{id}/render` | 渲染计划 |
| POST | `/v1/performance/plans/{id}/commit` | 原子提交状态变更与历史 |
| POST | `/v1/performance/plans/{id}/validate` | 重新验证计划 |
| GET | `/v1/ontology/units/{id}` | 查询单元与来源 |
| GET | `/v1/diagnostics/{id}` | 查询内部选择诊断（受控权限） |
| GET | `/v1/packs/{version}/manifest` | 查询 Pack 版本、哈希和来源 |

`plan → render → commit` 拆分是为了避免生成失败时污染连续性状态。

## 21. 可观察性与解释

每次规划记录：

- request/plan/pack/rule/renderer 版本。
- seed 和输入摘要哈希。
- 各阶段候选数、过滤原因和耗时。
- 入选分数明细及 Modifier 贡献。
- 预算使用率、重复惩罚和连续性成本。
- Genre Adapter 映射与世界规则判定。
- Renderer 实现、遗漏和新增事实检查。

诊断日志可能包含剧情和角色隐私，生产环境须支持脱敏、访问控制和保留期限。内部 reasoning 只保存结构化判定依据，不保存模型私有思维链。

建议指标：

- `planner_latency_ms`
- `candidate_count_before/after_constraints`
- `no_valid_candidate_rate`
- `continuity_rejection_rate`
- `semantic_repeat_rate_20_turns`
- `renderer_fact_invention_rate`
- `plan_reproducibility_rate`
- `persona_distinguishability_score`

### 21.1 非功能目标（建议默认值）

以下指标用于 MVP 压测和容量设计，正式 SLO 应在确定部署形态后通过 ADR 固化：

| 指标 | 本地规则引擎目标 | 含远程 LLM Renderer 目标 |
|---|---:|---:|
| 单角色规划 P50 | ≤ 30 ms | 不适用 |
| 单角色规划 P95 | ≤ 100 ms | 不适用 |
| 计划 + 渲染 P95 | ≤ 150 ms | ≤ 5 s |
| 单场景活跃历史窗口 | 100 turns | 100 turns |
| 单 Pack 原子单元 | 400 内无需向量数据库 | 超过 5,000 再评估 ANN |
| 固定输入复现率 | 100% | Plan 100%，文本不要求逐字一致 |
| Schema 无效数据拒绝率 | 100% | 100% |

核心 Planner 应支持批量规划，但同一场景的状态提交必须按 `scene_revision` 串行化。Pack 加载后只读并可在进程间共享；热更新采用“加载新版本 → 完整校验 → 原子切换”，不得原地修改活动 Pack。

## 22. 目录结构

```text
character-performance-pack/
├── pyproject.toml
├── README.md
├── src/character_performance/
│   ├── domain/                 # 纯领域模型，无框架依赖
│   ├── ontology/               # Pack 加载、索引与查询
│   ├── emotion/                # 情绪状态构建
│   ├── planner/                # 召回、过滤、评分、组合
│   ├── masking/
│   ├── continuity/
│   ├── repetition/
│   ├── budget/
│   ├── genres/xianxia/
│   ├── renderer/chinese_novel/
│   ├── ports/                  # Repository / Embedder / LLM 等接口
│   └── adapters/               # SQLite、API、模型等基础设施
├── data/
│   ├── sources/                # 默认不提交受限原始数据
│   ├── ontology/
│   │   ├── emotion/
│   │   ├── facial/
│   │   ├── body/
│   │   ├── spatial/
│   │   ├── physiology/
│   │   └── speech/
│   ├── modifiers/
│   ├── genres/xianxia/
│   └── compiled/
├── schemas/
│   ├── performance-unit.schema.json
│   ├── performance-request.schema.json
│   └── performance-plan.schema.json
├── tools/
│   ├── source_adapters/
│   ├── build_pack.py
│   ├── lint_ontology.py
│   └── evaluate.py
├── tests/
│   ├── unit/
│   ├── property/
│   ├── scenarios/
│   ├── renderer/
│   └── fixtures/
├── docs/
│   ├── implementation-spec.md
│   ├── source-license-audit.md
│   ├── adr/
│   └── phase-reports/
└── examples/
```

## 23. 配置、版本与兼容性

- Ontology Pack 使用 SemVer；改变字段语义或删除单元为 major 变更。
- 评分权重、Modifier 和世界规则拥有独立 `rule_version`。
- Schema 迁移必须提供向前转换工具，不在加载时静默修复。
- Performance Plan 固定记录 `pack_version` 和 `rule_version`。
- 生产环境启动时校验 Pack manifest 哈希和签名（若启用）。
- 已废弃单元先标记 `deprecated` 并提供 replacement ID，不立即删除。

## 24. 错误处理与降级

| 情况 | 行为 |
|---|---|
| 没有合法候选 | 返回空/低密度计划和 warning，允许正文不描写动作 |
| 只有重复候选 | 若剧情必要可选最低重复项并标记原因，否则保持空 |
| 连续性缺事实 | 返回 `STATE_INCOMPLETE`，要求上游补充，不猜测 |
| Genre Adapter 不可用 | 使用通用行为；不得虚构世界行为 |
| LLM Renderer 超时/违规 | 回退 deterministic renderer |
| Pack/Schema 不兼容 | fail closed，不加载半兼容数据 |
| 许可状态改变 | 阻止新 Pack 构建；已发布产物按合规流程处置 |

## 25. 测试策略

### 25.1 单元测试

- Schema 边界、数值截断和非法枚举。
- Modifier 顺序、叠加与上限。
- 每种硬约束过滤原因。
- 冷却衰减与语义组重复惩罚。
- 连续性 precondition/effect 应用。
- 相同 seed 的确定性。
- 世界规则的境界、范围和资源消耗。

### 25.2 性质测试

- 任意合法输入产生的 Plan 均不超预算。
- 入选候选两两不冲突。
- 所有 state patch 应保持 Schema 合法。
- 加重伤势不会增加依赖受伤部位动作的可选性。
- 提高 mask_strength 在其他变量不变时，不应增加明显泄露的期望值。
- 冷却窗口内重复同一语义组不会获得更高分，除非显式 narrative override。

### 25.3 必需场景测试与通过阈值

#### T1：同事件 / 不同人格

事件：公开羞辱。角色：冷静剑修、暴躁体修、城府宗主、胆怯弟子。

通过条件：

- 四个计划的通道 + 语义组集合平均 Jaccard 相似度 ≤ 0.55。
- 每个计划至少有一个差异能由 personality modifier 解释。
- 不得只替换渲染词，结构化计划必须不同。

#### T2：同人物 / 不同关系

对象：师尊、弟子、道侣、仇敌、陌生人；`anger=0.7`。

通过条件：

- 至少四种关系产生不同的幅度、距离、直率度或礼仪约束。
- 对师尊与仇敌的 dominance、directness 或 spatial 行为至少两个维度不同。

#### T3：掩饰

输入：`fear=0.85, restraint=0.95, control_capacity≥0.85`。

通过条件：

- 无 `visibility=obvious` 的恐惧信号。
- 至少 80% 的固定种子样本选择 surface calm；泄露若出现应为 subtle 或 very_subtle。
- Renderer 不出现“害怕 / 恐惧 / 强装镇定”等直陈词（除非视角设定允许读心且 Director 明确要求）。

#### T4：反重复

同一角色连续运行 20 轮普通对话，使用固定种子集合。

通过条件：

- 任一高频语义组不超过 4 次。
- 相邻 3 轮不得重复同一非连续性动作单元。
- `皱眉 / hand_tension / 嘴角变化 / gaze_flash / 深吸气` 五组总占用不超过所有信号的 30%。

#### T5：连续性

从“靠墙站立、右手持剑、左肩受伤”开始运行多步场景。

通过条件：

- 无未声明的位置、姿态、持有物跳变。
- 使用左肩的高幅动作被过滤。
- 走到桌边坐下必须出现合法桥接 sequence 或保持原位。

#### T6：修仙力量约束

同事件分别由炼气、筑基、金丹角色执行。

通过条件：

- 能力范围单调符合世界规则但受控制力/伤势上限约束。
- 炼气角色不能使用未解锁神识能力。
- 任一破坏性世界行为均记录规则 ID、资源成本和校验结果。

#### T7：模型替换稳定性

同一批 Performance Plan 交给两个 Renderer 或两个模型。

通过条件：

- 结构化行为、状态变更和世界事实一致率 100%。
- 文本可不同，但不得改变动作强度等级或添加计划外能力。

#### T8：许可门禁

注入一个来源未知和一个用途越权的单元。

通过条件：构建失败，错误准确指出来源 ID 与违规用途。

## 26. 质量门禁

每个 Performance Unit 合并前必须回答：

| 门禁 | 机器检查 | 人工检查 |
|---|---|---|
| Semantic Uniqueness | 指纹 + 相似度候选 | 是否有真实语义差异 |
| Composability | 冲突/兼容图可达 | 是否能与多通道组合 |
| Character Sensitivity | Modifier 覆盖测试 | 人格影响是否合理 |
| Relationship Sensitivity | 关系场景测试 | 是否避免刻板映射 |
| Context Sensitivity | requirements 测试 | 场景限制是否完整 |
| Continuity | precondition/effect lint | 动作是否可物理执行 |
| Narrative Value | 权重与预算测试 | 是否值得进入正文 |
| Source Validity | Registry + License Gate | 证据是否可信 |
| Genre Compatibility | World Rule 测试 | 是否符合世界设定 |

任一必需门禁失败即禁止进入 compiled Pack。

## 27. 实施阶段、交付物与退出条件

### Phase 0 — Source Research & License Audit

交付物：来源注册表、许可矩阵、获取脚本边界、引用规范。  
退出条件：计划使用的每个来源都有官方证据、用途分类和审批状态；不明许可均被阻止。

### Phase 1 — Canonical Schema

交付物：领域模型、JSON Schema、ID/版本规范、lint 工具。  
退出条件：示例单元、请求、计划均通过 round-trip；非法数据能稳定失败。

### Phase 2 — Emotion Ontology + VAD

交付物：分层情绪本体、标签映射、VAD 表示、复合情绪与衰减。  
退出条件：标签与连续状态可并存；至少覆盖 basic/social/relational/cognitive/moral/defensive/attachment/conflict/complex。

### Phase 3 — Facial / FACS Adapter

交付物：面部区域、动作、AU 引用、微表情时序与泄露模型。  
退出条件：任何面部动作都不永久绑定单一情绪；许可门禁通过。

### Phase 4 — Body + Spatial Ontology

交付物：身体部位、原子动作、proxemics、blocking、precondition/effect。  
退出条件：覆盖 head/neck/shoulders/arms/hands/fingers/torso/legs/feet/whole_body；基本空间行为可连续模拟。

### Phase 5 — Physiology

交付物：生理通道、概率条件、身体约束。  
退出条件：不存在“情绪标签必然触发生理反应”的硬编码。

### Phase 6 — Speech Performance

交付物：语气、节奏、音量、停顿、犹豫、打断、句长、直率度与 dialogue act 接口。  
退出条件：表现参数与台词语义内容解耦。

### Phase 7 — Personality + Relationship Modifiers

交付物：Modifier DSL、叠加顺序、人格/关系基线规则。  
退出条件：T1、T2 通过；无“角色类型 → 固定动作”规则。

### Phase 8 — Masking + Subtext

交付物：surface/leak 规划、控制失败、潜台词意图。  
退出条件：T3 通过。

### Phase 9 — Composition Engine

交付物：检索、过滤、评分、组合、预算和解释日志。  
退出条件：Plan 可复现、不超预算、无冲突；空候选可优雅降级。

### Phase 10 — Continuity + Anti-Repetition

交付物：SceneState、状态变换、语义历史和冷却。  
退出条件：T4、T5 通过。

### Phase 11 — Chinese Narrative Renderer

交付物：确定性 Renderer、LLM Renderer、输出检查器。  
退出条件：正文不泄露内部状态；事实新增率达到门禁目标；可回退。

### Phase 12 — Xianxia Adapter

交付物：qi/aura/spiritual_sense/pressure/intent/cultivation 等映射与世界规则。  
退出条件：T6 通过。

### Phase 13 — Automated Evaluation

交付物：固定基准集、指标面板、回归报告、模型替换测试。  
退出条件：T1–T8 全部通过且结果可复现。

### Phase 14 — Dataset Expansion

交付物：200–400 个高质量 Atomic Units、扩展 Modifier 与 Adapter。  
退出条件：覆盖报告显示真实缺口收敛；新增单元全部通过质量门禁，禁止为数量凑条目。

## 28. 每阶段统一报告模板

每个 `docs/phase-reports/phase-N.md` 必须包含：

1. 当前架构与本阶段变更。
2. 新增/变更 Schema。
3. 使用的数据来源、版本和链接。
4. License 状态与限制。
5. 已实现内容清单。
6. 最小可运行示例。
7. 测试命令、结果和失败记录。
8. 已知问题与风险。
9. 下一阶段依赖。

测试失败必须保留失败证据、修复说明和重跑结果，不得降低断言或删除失败样本来制造通过。

## 29. MVP 切片

建议用一个垂直切片验证架构，而不是先批量建库：

### MVP-1：可规划

- 12 个情绪标签 + VAD。
- 40–60 个高质量原子单元，覆盖 facial/gaze/body/spatial/physiology/speech。
- 4 个角色画像、5 类关系、3 类场景。
- 规则式候选召回、硬约束、评分和预算。
- 结构化 Plan 与解释日志。

### MVP-2：可持续

- SceneState 与 10 个有状态动作。
- 语义组反重复与 20 轮历史。
- masking surface/leak。
- T1–T5 自动化。

### MVP-3：可表达

- 确定性中文 Renderer。
- 可选 LLM Renderer + 事实检查。
- 10 个修仙映射和 6 条世界规则。
- T6–T8 自动化。

只有垂直切片通过后，才进入 200–400 单元扩展。

## 30. 风险与应对

| 风险 | 后果 | 应对 |
|---|---|---|
| 本体过度细化 | 维护成本高、召回稀疏 | 原子语义 + 参数化，不为每个表面变体建单元 |
| 来源许可误判 | 无法分发或商用 | 独立 Registry、证据链接、fail-closed 构建 |
| 规则爆炸 | 难调试、角色僵硬 | Modifier DSL、版本化权重、结构化诊断 |
| LLM 越权改写 | 事实和连续性被破坏 | Renderer 与 Planner 分离、输出检查、回退 |
| 反重复压过合理性 | 为求变化产生怪动作 | 重复是软惩罚；合理性和硬约束优先 |
| 掩饰模式模板化 | 总是“平静 + 指尖” | 多通道 leak 候选、通道轮换、角色特征与情境约束 |
| 修仙表现通胀 | 小情绪造成大异象 | 能力、境界、消耗、控制力和 Director 联合门禁 |
| 指标被游戏化 | 数字好看、文本失真 | 结构指标 + 盲评 + 对抗样本共同验收 |

## 31. 尚待产品确认的决策

以下问题不阻塞 Schema 与 MVP-1，但应在对应阶段前形成 ADR：

1. 首个运行形态是本地 Python 包、CLI，还是常驻服务。
2. 是否允许商业分发；这会改变 Phase 0 的许可门禁。
3. Character State 的权威来源是本引擎还是上游 World Simulator。
4. Renderer 使用的目标模型、最大延迟与失败预算。
5. 是否需要多语言 Renderer；v1.0 默认只支持中文小说。
6. 关系是逐角色有向图，还是由外部知识图谱提供。
7. 修仙境界与能力表是否采用项目自定义世界观，而非通用预设。

## 32. 需求追踪矩阵

| 原始需求主题 | 本文落点 | 主要验收 |
|---|---|---|
| Source First / License | §8、§9、Phase 0 | T8、Pack 构建门禁 |
| Emotion + VAD | §7.2、Phase 2 | Schema、强度差异场景 |
| Facial / Micro Expression | §7.7、Phase 3 | 非单一情绪绑定、masking 测试 |
| Body / Spatial / Physiology | §7.6、§16、Phase 4–5 | T5、性质测试 |
| Speech Performance | §17、Phase 6 | 内容与表现解耦测试 |
| Personality / Relationship | §7.3、§7.4、§7.8 | T1、T2 |
| Emotion Masking / Subtext | §13、§17 | T3 |
| Composition / Budget | §11、§12、§14 | 不超预算、无冲突性质测试 |
| Anti-Repetition | §15 | T4 |
| Continuity | §16 | T5、revision 冲突测试 |
| Planner / Renderer 分离 | §7.9、§19、§20 | T7 |
| Xianxia Adapter / Power | §18 | T6 |
| Provenance / Quality Gate | §8、§26 | lint、构建失败测试 |
| 分阶段实施与报告 | §27、§28 | 每阶段退出条件与报告完整性 |
| Coverage Target | §29、Definition of Done | 覆盖报告，不以近义条目凑数 |

## 33. Definition of Done

v1.0 只有同时满足以下条件才视为完成：

- Phase 0–13 的报告、Schema、代码、数据和测试齐全。
- 200–400 单元是覆盖目标；若少于 200，必须用覆盖报告证明已满足目标场景，而非伪造数量。
- 所有编译入 Pack 的单元来源可追踪、许可状态明确。
- T1–T8 在干净环境可重复通过。
- 核心 Planner 不调用 LLM 也能工作。
- 替换 Renderer 后，结构化行为与状态结果不变。
- 连续 20 轮基准场景无物理跳变，无高频语义动作滥用。
- 修仙能力均可追溯到 WorldRule 判定。
- 文档、示例和错误信息足以让新开发者独立运行垂直切片。

最终验收问题保持不变：把同一个事件交给十个不同人物，读者是否能仅通过他们持续、克制且符合处境的反应，逐渐分辨出这是十个不同的人。
