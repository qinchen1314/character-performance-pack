# 0.3.0 — 持续动作与导航衔接优化

## 1. 架构与优化依据

本轮完成文档 §16、Phase 4/10、T5 的下一垂直切片：显式走位目标、合法桥接、持续移动、暂停恢复与不重复描写。沿用原规划器、渲染验证和 SQLite 原子提交，新增 `blocking.py` 负责导航，不把路径搜索混入情绪评分。

## 2. Schema 变更

新增 Landmark、PathEdge、SceneLayout、BlockingGoal、ActiveAction、BlockingStep。SceneState 新增 layout/active_action/time_ms，Request 新增 blocking_goal/elapsed_ms/action_control，Plan 新增 sequence/continuation_signals，PerformanceUnit 新增 invocation。

路由控制单元只有明确走位请求才能执行；当前途中的地标位置必须为 null，完整路线、边索引和进度必须一致。Schema 导出包含 ActiveAction、BlockingGoal、SceneLayout。

## 3. 来源与版本

Pack 0.3.0 / rule 1.1.0。新增 4 个原创单元 `navigation.move/orient/pause/resume`，引用 `src.original.navigation.v1`；总数 62。原有情绪和动作来源保持不变，没有新增外部数据或网络依赖。

## 4. License 状态

新增规则、语法和测试是项目原创；原有第三方情绪来源的商业/分发门禁继续生效。Pack 加载继续校验源审计与内容哈希。

## 5. 已完成清单

- 按明确有向图选择可复现的最短时长路径；禁止未知位置、隐含反向边及被阻断边。
- 自动衔接离墙/起身→逐边移动→朝向座椅→坐下，每一步纳入预算。
- 跨回合保存进度，中途暂停/恢复，暂停不消耗移动额度；禁止打断策略得到执行。
- 持剑、伤势、能力、可见度、禁用单元与座椅事实约束不能被显式目标绕过。
- 持续移动省略重复动作描写；到达与姿态变化仍必须实现到正文。
- 目标完成后自动清除 CLI 的 blocking_goal，pause/resume 自动重置为 continue。
- 旧距离随离开地标清空，到达后只恢复已明确的新距离。
- 普通情绪描写的原有基准保持，不修改用户原有未提交测试。
- 补足积极情绪动作的主动性、自控语义，使喜悦、感激保留连续性格差异；全场最近 12 个信号中的其他角色动作参与有上限的软反重复，显式走位不受影响。
- SQLite 为计划保存跨角色历史快照；按提交先后而非各自回合号选取历史，重启或后续角色提交不会改变旧计划的验证结果。

## 6. 最小运行

```powershell
python -m pip install -e ".[dev]"
cpp-perform examples/blocking-scene.yaml --name 洛寒 --db examples/navigation.db --commit --output examples/output/navigation
cpp-perform examples/output/navigation/next-request.json --action-control pause --db examples/navigation.db --commit --output examples/output/navigation
cpp-perform examples/output/navigation/next-request.json --action-control resume --elapsed-ms 1300 --db examples/navigation.db --commit --output examples/output/navigation
python tools/demo_blocking.py
```

生成的五回合样本见 [blocking.md](../evaluation/blocking.md)。末态为桌边坐姿，右手仍持剑，累计移动 2000 ms。

## 7. 测试与失败记录

新增 `tests/scenarios/test_blocking.py` 和 `tests/integration/test_blocking_cli.py`，覆盖完整桥接、四档预算、暂停恢复、禁止打断、途中受伤、现有座椅接触、多段路径、图方向、SQLite 重启、连续性省略防篡改与 CLI 请求续接。

两轴代码审查识别并修复：到达后误写脚步/不必要检查移动权限；膝伤导致不能暂停；已知 standing+seat_contact 被拒。CLI 单次控制重置在审查期间完成。新增多段路径测试首次因对 tuple 调用 append 失败，调整测试构造为 JSON 可变列表后通过，未改变验收条件。

首次全量检查为 117 通过、3 失败，失败来自工作区新增的积极情绪与同场人物回归测试：四类性格在 joy/gratitude 下选择一致，同场角色反复使用相同手势。通过补足动作语义与跨角色软反重复修复，未修改这些验收测试。另增集成测试覆盖跨场景隔离、排除自身、最近窗口、数据库升级及重启后的历史回放。

补充审查发现先排除当前角色再截取窗口会使其他角色的旧动作长期不退出。已改为先截取全场窗口，再筛选其他角色，并加入其他角色离场后当前角色连续 30 回合使旧手势过期的回归。

最终全量命令：`python tools/evaluate.py --run-tests`。实际测试计数、延迟和常规二十回合指标记录在 [latest.json](../evaluation/latest.json)，没有以当前切片通过冒充完整 v1.0 验收。

最终结果：**124 项测试通过**；T1 人格平均 Jaccard 0.1111，T4 二十回合常见套话动作占比 13.79%，相邻三回合无同动作重复。`compileall`、13 份 Schema 导出、Pack 构建和 0.3.0 本地安装完成。安装后的 CLI 使用编译 Pack 实际执行开始→暂停→恢复三次提交，末态确认桌边坐姿、持剑保留、2000 ms，并清空已完成目标。

审查结果：Standards 轴发现的跨角色历史窗口过期问题已修复并复查通过；Spec 轴发现的导航边界问题已修复并通过 26 项导航场景测试。两轴均无剩余阻塞项。

## 8. 已知问题与风险

当前只支持场景初始化时声明的固定路径图、步行导航和 standing/seated 目标。任意持续动作、动态障碍同步、取消与改道、坐标级运动和文学盲评仍不在此阶段。Pack 变化时活动动作需保留原 Pack 完成；不静默重写正在执行的动作。

## 9. 下一阶段

导航与持续移动的这一切片已完成。下一项应针对中文表达做固定样本盲评和受约束文风改进，再据覆盖缺口扩充动作；通用持续动作扩展应复用本轮生命周期和渲染覆盖协议。工程取舍见 [ADR 0002](../adr/0002-continuous-blocking.md)。
