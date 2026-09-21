# 0.2.0 — 小说角色情绪与动作运行链

## 1. 架构与变更

原有来源注册表、情绪本体和 Pydantic 模型之上，补齐 `PerformanceRequest → Emotion Builder → 硬约束 → Modifier/评分 → 掩饰与预算组合 → 中文 Renderer → SQLite Commit`。模块独立于 Web、LLM SDK 和外部服务。

## 2. Schema

补齐角色、关系、伤势、场景、事件认知、导演、掩饰、世界状态、语义历史、渲染上下文/结果和状态变更。规则值通过严格嵌套模型校验；微表情包含面部区域和 onset/apex/offset；Modifier 使用受限路径和数值操作，无 eval。

`cpp-export-schemas --output schemas` 导出全部正式输入输出 Schema。

## 3. 来源与版本

Pack 0.2.0 / schema 1.0.0 / rule 1.0.0。18 情绪沿用 Phase 2 来源；58 单元和六条规则记录 `src.original.performance.v1`，创作定义位于 `tools/seed_original_units.py`、`data/modifiers/rules.yaml`。没有抓取或导入新外部语料。

## 4. 许可

沿用 `data/sources/registry.yaml` 策略。默认非商业、非再分发；旧情绪来源会阻止未经许可的商业构建。原子单元的 license_class 必须与来源 usage_mode 一致。compiled Pack 载入时校验哈希、来源引用、审阅状态和构建用途。

## 5. 已完成与阶段状态

| 阶段 | 本轮实现 | 退出状态 |
|---|---|---|
| 0–2 | 修复原有测试暴露的模型、来源字段、情绪验证、Schema 导出缺口 | 基础回归通过 |
| 3 | 原创面部动作、两种微表情、分阶段时序 | 本地子集；没有导入 FACS 材料 |
| 4 | 11 类身体区域、10 个状态动作、显式前置/效果、持物和伤势依赖 | 单步连续性通过；导航序列未实现 |
| 5 | 呼吸、吞咽等生理候选，受情境/强度/身体约束 | 无情绪必然反应映射 |
| 6 | 音量、语速、停顿、发音、句长表现 | 台词原样输入；完整 dialogue act 接口待扩展 |
| 7 | 人格/关系参数、六类修正顺序、DSL 与参数截断 | T1、T2 固定场景通过 |
| 8 | surface calm、概率泄露与泄露幅度上限 | T3 固定种子通过 |
| 9 | VAD、情绪语义、分项评分、稳定随机、通道/类别预算与诊断 | 复现、约束、预算回归通过 |
| 10 | SQLite 场景版本锁、事务提交、重启恢复、语义与语法反重复 | T4、T5；不含通用持续动作/打断状态机 |
| 11 | 中文槽位语法、受约束模型端口、独立正文检查、失败回退 | T7；自由小说改写及文学盲评未完成 |
| 12 | 10 修仙单元、境界/阶段/资源/控制/相对力量/活动能力等检查 | T6；原创简化世界观 |
| 13 | T1–T8 对应场景、边界与并发回归、指标/样本报告 | 固定离线集通过；非全面生产验收 |
| 14 | 58 单元、覆盖统计，无近义词凑数 | 200–400 扩展未完成 |

## 6. 最小运行

```powershell
python -m pip install -e ".[dev]"
cpp-perform examples/novel-scene.yaml --name 洛寒 --output examples/output
python tools/evaluate.py --run-tests
```

连写须传 `--db ... --commit`，从输出的 `next-request.json` 继续，详见 README。没有提供真实 LLM 服务配置；规则核心和确定性渲染无需 API Key。

## 7. 测试与证据

实际指标、测试数量和 20 回合样本以 [latest.json](../evaluation/latest.json) / [latest.md](../evaluation/latest.md) 为准。失败样本、根因与修复记录见 [failure-history.md](failure-history.md)。没有删除用户已有测试、修改失败阈值或替换固定种子来制造通过。

本轮最终执行：**89 passed**；本地可编辑安装、compileall、Schema 导出、compiled Pack 加载以及 CLI 两回合持久化均通过。规划 P95 在本机该固定样本运行约 5 ms（不含模型网络调用与 Pack 初始化）。独立双轴审查见 [code-review.md](code-review.md)。

T1–T7 在 `tests/scenarios/test_acceptance.py`，T8 在 `tests/integration/test_runtime.py`。额外覆盖模型非法值、严重膝伤、持剑、虚构渲染、compiled 来源异常、Modifier 覆盖评分攻击、字典顺序复现、SQLite 多连接竞争与重启恢复。

## 8. 已知限制

- 固定基准普通对话出现空动作回合，是反重复与低价值停止的结果；不应拿信号数量作为文笔质量。
- 评分权重、VAD 和关系规则是工程先验，尚无盲评标定；不能推断现实人的心理。
- 场景位置导航、动作持续/完成/打断、身体各部位的长期姿态需要进一步扩展状态模型。当前只保证所声明状态字段不发生未计划变更。
- 中文输出为参考片段，表达种类有限。模型只能选择审核片段，无法无约束润色整段文章。
- 阶段耗时细分、生产权限/脱敏/保留期、批量规划、签名和原子 Pack 热切换尚未实现。
- 完整 v1.0 的 Definition of Done 尚未满足，不能把当前基准通过称为生产版完成。

## 9. 后续依赖

先建立小说样本盲评和真实场景缺口，再扩充单元。完整状态机需要明确上游世界模拟的同步协议；自由 LLM 渲染需要新的事实核验能力与实际供应商回归集。具体工程取舍见 [ADR 0001](../adr/0001-local-novel-runtime.md)。
