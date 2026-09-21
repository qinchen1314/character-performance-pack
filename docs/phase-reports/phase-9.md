# Phase 9 — Composition Engine

## 1. 架构与本阶段变更

硬约束先于评分；VAD、情绪、人格、关系、身体、签名、反重复、通道预算和稳定随机；空候选允许不描写。

## 2. Schema

PerformanceRequest / PerformancePlan、ScoringRules。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。src/character_performance/engine.py；scoring.py

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

硬约束先于评分；VAD、情绪、人格、关系、身体、签名、反重复、通道预算和稳定随机；空候选允许不描写。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

固定输入复现、跨 Python hash seed、预算/两两冲突回归。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

参考实现遍历小型只读 Pack；尚未建立大规模倒排和向量召回。

## 9. 下一阶段依赖

数据规模扩大后才引入更复杂检索；当前保留分项诊断。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。

