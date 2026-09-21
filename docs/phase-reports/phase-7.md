# Phase 7 — Personality + Relationship Modifiers

## 1. 架构与本阶段变更

连续人格/关系修正 + 六条可配置 DSL；固定六层执行顺序；参数截断、预算上限、贡献命名空间。

## 2. Schema

Modifier、Condition、ModifierEffects。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。data/modifiers/rules.yaml；src/character_performance/modifiers.py

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

连续人格/关系修正 + 六条可配置 DSL；固定六层执行顺序；参数截断、预算上限、贡献命名空间。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

T1、T2、test_modifiers、source/compiled 等价。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

Big Five 与关系权重为原创工程先验，未进行文学盲评标定。

## 9. 下一阶段依赖

按盲评扩充受限 DSL 路径与人格习得习惯。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。

