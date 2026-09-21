# Phase 1 — Canonical Schema

## 1. 当前架构

`character_performance.domain.models` 是无 Web/存储依赖的领域层。数据文件加载后立即进入 Pydantic 严格模型；未知字段被拒绝，模型实例冻结。

## 2. Schema

已实现：

- `VAD`
- `IntensityRange`
- `EmotionState`
- `OntologyEmotion`
- `Cooldown`
- `PerformanceUnit`
- `PerformancePlan`

Pack 构建时导出 `EmotionState`、`PerformanceUnit` 和 `PerformancePlan` 的 JSON Schema。

## 3. 数据来源

Schema 为项目原创；语义设计参考实现文档和已审计公开体系，不复制受限数据。

## 4. License 状态

Schema 使用 `src.original.core.v1` 作为原创来源。具体数据单元仍须各自声明来源。

## 5. 已实现内容

- `[0,1]` 与 `[-1,1]` 数值边界。
- 可验证 ID、非空语义组、语义元数据和来源追踪。
- 强度范围顺序校验。
- 原子单元分类、可见性、冷却、冲突与兼容字段。
- 确定性 JSON 序列化和 SHA-256 内容哈希。
- `plan → render → commit` 所需的最小 Plan 数据结构。

## 6. 示例

参见 `tests/unit/test_domain_models.py` 和构建产物 `data/compiled/schemas/`。

## 7. 测试

领域模型测试与集成构建测试均通过。全量：12 passed。

## 8. 已知问题

- CharacterProfile、RelationshipState、SceneState 将在 Modifier 与 Continuity 阶段加入；本阶段不提前固化未被运行时使用的字段。
- JSON Schema 当前由构建产物生成，不提交到 Git，避免生成文件漂移。

## 9. 下一阶段依赖

Phase 2 使用 `OntologyEmotion` 和 `EmotionState` 建立情绪本体与连续状态。

