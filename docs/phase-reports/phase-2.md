# Phase 2 — Emotion Ontology + VAD

## 1. 当前架构

`EmotionOntology` 从 YAML 加载并建立 canonical ID、中文标签和别名的唯一索引。离散标签与 VAD 原型同时存在，运行态由 `EmotionState` 保存强度、克制、觉察、持续时间和衰减半衰期。

## 2. Schema

```yaml
emotion:
  id: anger
  label_zh: 愤怒
  families: [basic, conflict]
  aliases: [恼怒, angry]
  prototype_vad: {valence: -0.65, arousal: 0.70, dominance: 0.55}
  source_refs: [src.goemotions.taxonomy.v1]
```

## 3. 数据来源

- GoEmotions：标签概念和分类启发，仅保存派生本体元数据。
- 项目原创：jealousy、resentment、hope 等面向叙事组合的重组条目。

## 4. License 状态

当前 Pack 以非商业、非再分发策略构建。GoEmotions 的原始评论文本未下载、未复制、未进入仓库。

## 5. 已实现内容

- 18 个 canonical emotions。
- 覆盖 basic、social、relational、cognitive、moral、defensive、attachment、conflict、complex 九个家族。
- 中文/英文别名解析和冲突检测。
- VAD 原型严格范围校验。
- 复合情绪所需 primary + secondary 表示。
- 基于 half-life 的不可变衰减操作。
- Pack manifest、内容哈希和标准化 JSON 输出。

## 6. 示例

```python
ontology = EmotionOntology.from_yaml(path)
emotion = ontology.resolve("恼怒")
assert emotion.id == "anger"
```

## 7. 测试

- canonical label 与别名解析。
- 未知情绪显式失败。
- VAD 越界失败。
- 标签与连续 VAD 共存。
- 实际 Pack 构建生成 18 个情绪与 64 位 SHA-256 哈希。

全量结果：12 passed；`compileall` 通过；CLI 构建通过。

## 8. 已知问题

- VAD 当前是工程原型值，不冒充来源数据集的逐条标注；后续需建立校准集。
- 尚未实现 event + cognition → EmotionState 的 appraisal builder；按文档应在运行时垂直切片中加入。
- 情绪间关系图（近邻、对立、可混合）尚未实现。

## 9. 下一阶段依赖

Phase 3 需要新增面部动作与微表情 Schema，并使用已审计的 FACS 概念引用方式，禁止打包专有训练材料。

