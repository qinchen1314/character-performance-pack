# Phase 13 — Automated Evaluation

## 1. 架构与本阶段变更

固定 T1–T8 对应回归、参数边界/并发/跨进程复现、20 回合中文样本、覆盖统计和规划延迟。

## 2. Schema

docs/evaluation/latest.json 指标与覆盖结构。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。tools/evaluate.py；tests/scenarios；tests/integration；tests/unit

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

固定 T1–T8 对应回归、参数边界/并发/跨进程复现、20 回合中文样本、覆盖统计和规划延迟。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

python tools/evaluate.py --run-tests；实际计数存入 latest.json。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

固定样本全部通过不等于生产全域、文学质量或多供应商网络可靠性通过。

## 9. 下一阶段依赖

扩大对抗数据和盲评之后，再决定 Phase 14 的真实单元缺口。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。

