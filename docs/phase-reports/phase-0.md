# Phase 0 — Source Research & License Audit

## 1. 当前架构

来源治理由 `data/sources/registry.yaml` 和 `SourceRegistry` 组成。Pack 构建只验证实际被本体引用的来源；任何未知、未审批、用途受阻或与构建策略不兼容的来源都会令构建失败。

## 2. Schema

`SourceRecord` 包含：稳定 ID、来源类型、锁定版本、usage mode、审查状态、隔离要求、许可证标识、商业使用、再分发、署名、Share-Alike 与证据 URL。

## 3. 数据来源

完整调研见 [source-license-audit.md](../source-license-audit.md)。当前 Registry 登记了原创来源、GoEmotions、EmoBank、FACS、SAMM 和 EmpatheticDialogues；只在实际使用时触发构建门禁。

## 4. License 状态

- 原创核心：approved，可按项目许可证使用。
- GoEmotions：approved for `derived_metadata`，当前明确禁止商业/再分发构建，等待进一步权利确认。
- EmoBank：approved，但必须启用 Share-Alike 隔离策略。
- FACS：仅 reference-only，禁止打包专有材料。
- SAMM：pending。
- EmpatheticDialogues：pending + blocked，直到 artifact 级许可冲突解决。

## 5. 已实现内容

- YAML Registry 与 Pydantic 严格校验。
- `BuildPolicy` 支持 commercial、redistribution 和 Share-Alike isolation。
- fail-closed 校验与可操作错误原因。
- 未知来源、审批状态和用途兼容性测试。

## 6. 示例

```python
registry.validate_for_build(
    ["src.original.core.v1"],
    BuildPolicy(commercial=True, redistribution=True),
)
```

## 7. 测试

`python -m pytest tests/unit/test_source_registry.py`：4 passed。

## 8. 已知问题

- Registry 尚未录入审计文档的所有未使用来源；来源首次进入 Pack 前必须先登记。
- 许可结论不是法律意见，商业发布前仍需负责人复核 artifact 级许可证。

## 9. 下一阶段依赖

Phase 1 的所有 Canonical 单元必须使用 Registry 中存在且准入的 `source_refs`。

