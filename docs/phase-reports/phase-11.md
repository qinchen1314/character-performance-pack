# Phase 11 — Chinese Narrative Renderer

## 1. 架构与本阶段变更

中文语法槽位、受约束模型选择端口、独立输出核验、异常回退；普通作者名与台词输入。

## 2. Schema

RenderContext、RenderResult、RealizationModel Protocol。导出命令：`cpp-export-schemas --output schemas`。

## 3. 数据来源与版本

Pack 0.2.0 / rule 1.0.0。新增单元使用 `src.original.performance.v1`；已有情绪来源见 Phase 2 与来源注册表。src/character_performance/renderer.py

## 4. License 状态

新增动作/规则/语法为项目原创；保留已有情绪数据的非商业、非再分发构建策略。来源不明、reference_only 和用途越权在编译与加载时拒绝。本阶段未新增外部下载。

## 5. 已实现清单

中文语法槽位、受约束模型选择端口、独立输出核验、异常回退；普通作者名与台词输入。

## 6. 最小可运行示例

```powershell
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

## 7. 测试、结果和失败记录

T7、自报事实绕过被拒、合法措辞可改变但计划不变。 最新全量结果见 [评估 JSON](../evaluation/latest.json)，失败及修复见 [failure-history.md](failure-history.md)。本文报告本地垂直切片，不冒充完整生产阶段退出。

## 8. 已知问题与风险

未配置真实模型供应商；HTTP 超时归模型适配器；自由模型正文不在允许输出集合内。

## 9. 下一阶段依赖

真实模型回归与文学表达盲评，不以关键词过滤冒充自由文本事实证明。 总体边界见 [runtime-mvp.md](runtime-mvp.md)。

