# 本轮失败与修复记录

基线：`baa5875`，2026-09-21。保留用户原有验收测试，未降低其断言。

| 阶段 | 原始失败/证据 | 修复 | 回归覆盖 |
|---|---|---|---|
| 开始 | 3 errors during collection；缺 `Appraisal`、`PerformanceRequest`、`cli.export_schemas` | 补模型、来源元数据、标签验证与导出模块 | 原有 18 项测试 |
| 构建接入 | `PerformanceRequest.schema.json` 不在导出列表；17 passed / 1 failed | 构建器复用完整 Schema 导出函数 | test_build_pack |
| 新 Pack lint | `render hints cannot interpolate facts: body.arms_fold`；误将整个 dict 字符串的括号视为插值 | 检查语法字段值而非容器文本 | 全库构建与 roundtrip |
| 审查 | `effects.pose=flying`、`min_mobility=broken` 可进入 Pack | 严格规则模型 + 必要前置条件校验 | test_runtime_boundaries 参数化样本 |
| 审查 | Renderer 自报空 introduced_facts 仍可输出“飞到屋顶”并提交 | 独立语法选项和正文一致性检查，违规不标记成功 | test_custom_renderer_cannot_self_certify_invented_text |
| 审查 | 重度左膝伤仍可 step_closer/weight_shift | whole_body/feet 承重依赖补齐膝踝 | test_severe_knee_injury_prevents_weight_bearing_actions |
| 审查 | 所有种子缺 vad_affinity，VAD 评分恒为零 | 每单元增加原创 VAD 先验 | test_vad_changes_scoring_with_fixed_discrete_emotion |
| 审查 | 目标名字只替换补语，向对方仍留在动词中 | 语法槽位统一替换目标引用 | test_target_substitution_covers_verb_and_complement |
| 复核 | world.sense_retract 可在未外放神识时执行 | 显式 active_capabilities 与世界激活/回收效果 | test_world_retraction_requires_prior_activation |
| 复核 | Modifier id=repetition 覆盖反重复项；字典顺序导致浮点结果差异 | 独立 modifier: 前缀、排序及 fsum | test_modifiers 与 source/compiled 等价测试 |

最新全量结果由 `python tools/evaluate.py --run-tests` 保存到 `docs/evaluation/latest.json`，其中 tests 字段和 JUnit XML 为实际运行结果。文学质量、数据规模、真实 LLM 服务集成没有用这些通过结果冒充验收。
