# Phase 12 — Xianxia Adapter

## 1. 架构与本阶段变更

10 个原创 qi/aura/sense/intent/pressure 表现；境界、阶段、能力、控制、资源、破坏、强度、相对力量、活动状态校验。

## 2. Schema

WorldState、WorldRequirements；显式激活/回收能力。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。src/character_performance/world.py；world 类原子。

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

10 个原创 qi/aura/sense/intent/pressure 表现；境界、阶段、能力、控制、资源、破坏、强度、相对力量、活动状态校验。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

T6；神识回收要求已激活；世界成本在提交时生效。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

使用四级原创简化世界观，不代表所有修仙作品；按作品设定修改数据。

## 9. 下一阶段依赖

更完整世界规则及跨角色目标效果需明确定义。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。

