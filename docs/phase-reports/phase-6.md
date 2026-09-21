# Phase 6 — Speech Performance

## 1. 架构与本阶段变更

音量、语速、停顿、咬字、语气和句长表现；台词由上游原样提供。

## 2. Schema

RenderContext.dialogue、Plan.parameters.volume / pace / directness。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。src/character_performance/renderer.py；speech 原子。

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

音量、语速、停顿、咬字、语气和句长表现；台词由上游原样提供。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

T2、T7；模型更换保留台词。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

不决定台词语义，不会改写作者提供内容；完整 dialogue act 模型未实现。

## 9. 下一阶段依赖

以更多真实对话场景校准参数到语法的映射。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。

