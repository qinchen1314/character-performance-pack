# Phase 4 — Body + Spatial

## 1. 架构与本阶段变更

覆盖 head/neck/shoulders/arms/hands/fingers/torso/legs/feet/whole_body 等身体区域；10 个有状态单元；严伤、持物、座椅/墙接触和目标距离约束。

## 2. Schema

SceneState、PhysicalState、Injury、StateEffects。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。src/character_performance/continuity.py

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

覆盖 head/neck/shoulders/arms/hands/fingers/torso/legs/feet/whole_body 等身体区域；10 个有状态单元；严伤、持物、座椅/墙接触和目标距离约束。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

T5、伤膝承重回归、非法状态规则拒绝。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

单回合最多一项物理状态变换；没有通用导航桥接和持续动作状态机。

## 9. 下一阶段依赖

需要显式场景拓扑才能安全实现 approach → orient → sit。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。

