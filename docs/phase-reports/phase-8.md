# Phase 8 — Masking + Subtext

## 1. 架构与本阶段变更

自动或显式掩饰、surface calm、按强度/唤醒/控制/疼痛计算泄露概率；泄露限 subtle 和 very_subtle。

## 2. Schema

Masking；Plan.surface_signals / leak_signals。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。src/character_performance/engine.py

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

自动或显式掩饰、surface calm、按强度/唤醒/控制/疼痛计算泄露概率；泄露限 subtle 和 very_subtle。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

T3 的 30 固定种子，禁直陈恐惧。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

displayed_emotion 暂只支持 calm；其他展示情绪显式报错，不悄悄忽略。

## 9. 下一阶段依赖

扩展 displayed 情绪前须增加对应行为与冲突验收。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。
