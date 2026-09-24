# T10 验收证据格式

`cpp-behavior-verify evaluate` 接受一个 JSON/YAML 对象。每个值都必须来自同一待发布
版本的自动测试或基准运行：

使用校准阈值策略时，证据必须声明 `prose_gate_scope: chapter_p95`，且重复率、俗套占比、
通道集中度均为章节级指标的 P95。未加载校准策略时保留的旧证据可使用
`legacy_aggregate`；两种口径不得混用。

证据必须包含 `provenance`：生产者固定为 `cpp-behavior-verification-suite`，记录 Git
提交、生成时间、总历史行数（至少 100 万）、单书 occurrence 数（至少 20 万），以及
unit/property/integration/scenario/chapter_benchmark/fault_injection/performance 七类测试的
实际通过数量。缺任一来源或数据规模不足时，模型验证直接失败，不生成“通过”报告。

| 字段 | 来源 | 门禁 |
|---|---|---:|
| `immediate_exact_repeat_rate` | 最近 3 个行为的 unit 重复统计 | `0` |
| `chapter_semantic_over_limit` | 章内非连续性语义家族超限次数 | `0` |
| `cliche_group_share` | 高频俗套语义组占比 | `≤ 0.20` |
| `maximum_character_channel_share` | 任一角色最高频非签名通道占比 | `≤ 0.45` |
| `cross_chapter_function_channel_repeat_rate` | 三章内同功能同通道重复率 | `≤ 0.10` |
| `semantic_repeat_recall` / `semantic_repeat_precision` | 固定对抗集 | `≥ 0.90 / ≥ 0.85` |
| `span_accuracy` | 独立人工标注 span | `≥ 0.98` |
| `rewrite_grammar_integrity_rate` | 重写后主谓结构、句末标点及引号完整性校验 | `1.0` |
| `rewrite_dialogue_preservation_rate` | 重写前后台词内容与顺序保持率 | `1.0` |
| `rewrite_fact_preservation_rate` | 重写前后必需事实保持率 | `1.0` |
| `duplicate_history_count` | 并发、重启、重试后的重复 occurrence 数 | `0` |
| `fault_injection_passed` | 原子回滚、外部 Adapter 失败和恢复测试 | `true` |
| `prepare_p95_ms` | 不含外部 LLM | `≤ 100` |
| `rule_extraction_p95_ms` | 3000 中文字 | `≤ 80` |
| `history_query_p95_ms` | 规定数据规模下七窗口查询 | `≤ 30` |
| `commit_p95_ms` | 原子提交 | `≤ 50` |
| `deterministic_replay_passed` | 相同输入、Pack、Identity、revision、seed | `true` |

旧的聚合字段 `rewrite_preservation_rate` 已拆为三个独立硬门禁，不能再用一项综合比例掩盖
残句、台词变化或事实丢失。三项都必须来自同一版本的固定重写对抗集，且分别达到 100%。

抽取对抗集通过 `benchmark_extractor` 使用独立的 `ExtractionTruth` 计算，不从抽取器输出
反推期望值。每条 truth 必须独立标注 actor、targets、canonical action、semantic group 和
半开区间 `[start, end)`。预测只有同时满足 actor、无序 targets 集合、action、semantic
group 且区间 IoU 达到门槛（默认 0.5）才算命中；匹配使用全局一对一最优分配，先最大化
命中数，再最大化总 IoU，避免 truth 顺序或多动作预测影响分数。

`ExtractionBenchmarkResult` 同时保留兼容字段 `precision`、`recall`、`span_accuracy`，并输出：

- `mean_span_iou`：已匹配项的平均 IoU；`span_accuracy` 仍表示已匹配项中的完全区间一致率；
- `micro`：汇总全部 truth/prediction 后的 precision、recall、F1；
- `macro`：逐 case 计算后等权平均的 precision、recall、F1；
- `error_counts`：actor、target、action、semantic group、span、漏检、孤立误报七类诊断计数；
- `error_type_confusion_matrix`：actor/target/action/semantic/span 五个维度的
  correct/incorrect 矩阵，以及 detection 的 TP/FP/FN 行；同一诊断对可贡献多个字段错误；
- `identity_confusion_matrix`：联合身份标签的 truth→prediction 矩阵，含 `__missing__` 和
  `__spurious__`；
- `calibration`：非空等宽置信度分箱、每箱平均置信度/实际准确率，以及 ECE 和 Brier score。

混淆诊断只在剩余 truth 与 prediction 的区间有交集时配对；无交集项分别记作漏检和孤立
误报，避免把相距很远的动作强行解释为分类混淆。置信度正确性采用上述完整联合命中定义。

真人评分文件是 JSON/YAML 数组，每项包含 `sample_id`、`reviewer_id`、
`guessed_label`、三项 1—5 分评分，以及可选的 `mechanical`、`formulaic`、
`indistinguishable`、`contrived_variation` 标记。每名评审必须恰好覆盖 packet 中全部
样本。样本必须提供真实 `character_name` 和可选 `aliases`；公开 packet 会统一替换为
“某人”，并拒绝仍泄漏角色 ID 的正文。角色识别除达到 70% 外，还须以单侧二项检验
显著高于匿名候选的随机基线（`p ≤ 0.05`）。

缺少真人评分不是通过，也不是失败，而是 `pending_human`。这条状态规则防止机器指标
替代规格要求的真人门禁。
