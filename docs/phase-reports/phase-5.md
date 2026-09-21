# Phase 5 — Physiology

## 1. 架构与本阶段变更

呼吸暂停、调匀呼吸、吞咽、呼气作为概率候选；呼吸能力不足时拒绝相关表现。

## 2. Schema

PhysicalRequirements.min_breath、PhysicalState.breath_capacity。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。data/ontology/units.yaml 中 physiology 类。

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

呼吸暂停、调匀呼吸、吞咽、呼气作为概率候选；呼吸能力不足时拒绝相关表现。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

T3、T4、预算和伤势边界回归。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

原子反应是叙事工程先验，未用作现实心理或生理推断。

## 9. 下一阶段依赖

扩展身体状态场景与低控制力样本。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。

