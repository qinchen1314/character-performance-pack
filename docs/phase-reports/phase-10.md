# Phase 10 — Continuity + Anti-Repetition

## 1. 架构与本阶段变更

显式 SceneState 变换、SQLite 原子提交、共享 scene revision、幂等 commit、重启恢复；动作/语义/通道/语法短语惩罚。

## 2. Schema

StateTransition、HistoryEntry.render_features、world active_capabilities。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。src/character_performance/storage.py；continuity.py；scoring.py

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

显式 SceneState 变换、SQLite 原子提交、共享 scene revision、幂等 commit、重启恢复；动作/语义/通道/语法短语惩罚。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

T4、T5、多连接竞争、未渲染禁止提交、过期快照拒绝。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

只保证已声明字段的状态连续性；未完成动作保守阻止新身体动作，尚无通用打断/恢复。

## 9. 下一阶段依赖

上游世界同步协议、空间拓扑与动作生命周期。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。
