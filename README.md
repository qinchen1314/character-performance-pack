# Character Performance Pack

Character Performance Pack 是一个面向**中文小说创作**的本地角色表现引擎。它把人物性格、关系、情绪、伤势、持物、场景位置和导演意图组合成可解释、可复现的动作计划，并渲染为可直接嵌入正文的中文片段。

它适合接在写作 Agent、小说工作流或编辑工具之后，专门解决“角色此刻应该怎么表现”这一层问题。项目不代写剧情和台词；台词由作者提供，工具负责为台词补上符合上下文的神态、动作、生理反应和空间行为。

## 能做什么

- 66 种情绪、1024 个原创表现单元和 56 条可配置修正器。
- 综合人物 Big Five、表达基线、关系、主次情绪、强度、克制程度和场景语境选取动作。
- 检查伤势、持物、姿态、前置状态、场景物件和世界规则，避免凭空捏造事实。
- 支持修仙题材能力约束；只有世界、境界、角色能力和导演许可同时满足时，才会使用神识、威压等表现。
- 支持 SQLite 连续性记录、跨回合移动、暂停/恢复、姿态衔接和并发版本检查。
- 相同 Pack、输入和 seed 会得到相同计划，便于复现、测试和审阅。
- 输出动作计划、最终正文、渲染覆盖情况及下一回合请求，选择过程可追踪。
- 核心运行完全本地，不需要联网，也不需要模型 API Key。
- 可生成目录身份隔离的真人盲评包，并按独立评审人数门禁汇总保留、重写或删除决定。
- 提供跨章节行为记忆：按场景、章节、卷、全书和同场角色查询已采用的描写，减少“反复皱眉、握拳、移开视线”一类重复。
- 提供 `准备 → 审查 → 局部改写 → 提交` 流程；正文通过审查后才写入正式记忆，重复提交保持幂等。
- 支持规则抽取器，也预留外部 JSON 模型适配接口；默认功能可完全离线运行。

## 环境要求

- Python 3.12 或更高版本
- Windows、macOS 或 Linux

## 安装

表现目录和示例是仓库内容的一部分，因此建议克隆完整仓库后安装：

```bash
git clone https://github.com/qinchen1314/character-performance-pack.git
cd character-performance-pack
python -m pip install -e .
```

后续命令默认在仓库根目录运行，以便读取 `data/` 下的表现目录。用于应用集成时，也可以通过 `--project-root` 指定仓库位置，或先编译 Pack 后通过 `--pack` 指定编译目录。

安装后提供六个命令：

- `cpp-perform`：根据 YAML/JSON 请求生成角色表现。
- `cpp-build-pack`：校验并编译表现包。
- `cpp-export-schemas`：导出所有公开数据模型的 JSON Schema。
- `cpp-blind-review`：生成匿名真人盲评包，或汇总多名评审的评分。
- `cpp-behavior`：执行 prepare/audit/rewrite/commit 全流程，并生成跨章节行为报告。
- `cpp-behavior-memory`：迁移、备份和恢复跨章节行为记忆数据库。
- `cpp-behavior-verify`：运行自动验收门禁并组织隐去角色名的真人盲评。

## 真人盲评与目录清理

盲评包把动作目录 ID、语义家族和分类元数据留在单独的答案文件中；评审者只看到题材、文风、角色壳与待评片段。内置评审壳覆盖武侠、都市情感、刑侦、校园、古言、科幻和仙侠等题材，并包含冷硬、细腻、白描、明快、清雅和清峻等文风。

```bash
cpp-blind-review prepare --project-root . --output review/run-01 --seed 20260921
```

把 `packet.json` 发给评审者，保留 `answer-key.json` 不公开。每位评审提交一个 JSON 数组；每项填写匿名 `case_id`、稳定且不泄露身份的 `reviewer_id`，以及 `prose_value`、`naturalness`、`character_fit` 三项 1—5 分。可选问题标记为 `mechanical`、`stiff`、`not_worth_prose` 或 `characterless`。

```bash
cpp-blind-review aggregate --key review/run-01/answer-key.json \
  --ratings review/reader-a.json review/reader-b.json \
  --output review/run-01/report.json --minimum-reviewers 2
```

同一评审者评价多个角色壳只计一名独立评审。未达到最少独立评审数时决定保持 `pending`，不会伪装成真人结论。目录记录可用 `editorial_status: rejected` 和 `replacement_id` 保留淘汰依据；它仍以 `deprecated` 进入 Pack 供旧计划兼容，但规划器不会再把它选入新正文。

也可以不安装命令入口，在仓库根目录使用 `python -m character_performance.cli.perform` 等模块命令。

## 五分钟上手

仓库内的 `examples/novel-scene.yaml` 已包含一个完整请求：公开场合中，克制而警觉的角色面对敌对对象，并带有肩伤和持剑状态。

```bash
cpp-perform examples/novel-scene.yaml \
  --name 洛寒 \
  --target-name 对方 \
  --dialogue "此事到此为止。" \
  --output examples/output
```

PowerShell 可以写成一行：

```powershell
cpp-perform examples/novel-scene.yaml --name 洛寒 --target-name 对方 --dialogue "此事到此为止。" --output examples/output
```

使用当前示例和 seed，正文效果为：

> 洛寒放匀呼吸。洛寒说：“此事到此为止。”

这段结果不是不可审计的自由生成。`plan.json` 会记录选中了哪个表现单元、为何入选、状态如何变化；`render.json` 会记录哪些动作成功实现以及是否引入了新事实。

输出目录包含：

| 文件 | 用途 |
| --- | --- |
| `prose.txt` | 可直接使用或继续润色的中文片段 |
| `plan.json` | 候选选择、动作计划、警告和状态迁移 |
| `render.json` | 实际实现的表现单元、遗漏项和新增事实 |
| `next-request.json` | 带有最新场景快照的下一回合输入 |

## 跨章节行为控制

`cpp-perform` 适合从结构化状态生成动作计划；`cpp-behavior` 和 `BehaviorControlSystem` 适合接到已有写作 Agent 上，控制它写出的整段正文。完整离线演示位于 `examples/behavior-workflow.py`：

```bash
python examples/behavior-workflow.py
```

演示会连续执行三次写作回合，输出的关键效果如下：

```text
第一章审查通过： True
正式记忆版本： 1
第二章重复描写通过： False
重复问题： exact_history_repeat
改写前： 他握拳。“好。”
改写后： 他。“好。”
改写后审查通过： True
重复提交保持幂等： True
```

这里的改写只处理审查定位到的问题区间，台词保持原样。遇到阻断级问题时系统要求作者处理，不会自行改写；最多自动改写两次，仍不合格则交回人工审阅。

如果只想给模型准备一份紧凑提示，不创建正式运行记录：

```bash
cpp-behavior prepare examples/behavior-request.yaml \
  --db examples/story.db --output output/brief --preview
```

输出的 `prompt.txt` 会包含本段策略、优先行为通道、动作预算、候选行为、近期重复项和角色禁忌。去掉 `--preview` 后会创建可恢复的运行记录，供后续审查和正式提交使用。

从一段已写正文中抽取行为：

```bash
cpp-behavior extract examples/extraction-request.yaml \
  --output output/extraction.json
```

正式生成链路在每一步都落盘可恢复的 JSON 产物，并输出一行结构化 JSON 日志：

```bash
cpp-behavior prepare examples/behavior-request.yaml --db story.db --output run/
cpp-behavior audit run/brief.json draft.txt --db story.db --output run/audit.json
cpp-behavior rewrite run/audit.json draft.txt --db story.db --output run/revised.txt
# 重写稿必须再次 audit；以下 final-audit.json 必须是 accepted=true
cpp-behavior commit run/final-audit.json run/revised.txt --db story.db
cpp-behavior report --book book.demo --db story.db --output reports/behavior.html
cpp-behavior report --book book.demo --db story.db --output reports/behavior.md
```

命令失败时 stderr 仍为单行 JSON，并包含规格中的稳定 `error_code`，例如
`AUDIT_BLOCKED`、`DRAFT_HASH_MISMATCH`、`RUN_STATE_CONFLICT` 和
`BEHAVIOR_MEMORY_REVISION_CONFLICT`。报告包括角色通道/策略分布、章节语义重复热点、
句法模板热点，以及可直接进入验收报告的自动门禁值。

## 全量验收与角色盲评

`cpp-behavior-verify` 把机器指标与真人门禁分开记录。机器指标必须来自固定对抗集、
故障注入、重启/并发测试和性能基准，不应手工臆造。准备盲评时，公开 packet 只包含
匿名标签与片段，真实角色映射单独保存在 answer key：

```bash
cpp-behavior-verify prepare-human review/character-samples.yaml \
  --output review/character-run --seed 20260922

cpp-behavior-verify evaluate reports/automatic-evidence.json \
  --key review/character-run/answer-key.json \
  --ratings review/reader-a.json review/reader-b.json \
  --output reports/acceptance.md
```

自动报告逐项检查重复率、俗套组占比、通道集中度、抽取召回率/精确率、span 准确率、
重写保持率、幂等/故障注入、确定性和四项 P95 性能目标。没有至少两名独立评审的完整
评分时，总体状态固定为 `pending_human`；只有自动门禁与真人门禁全部通过，报告中的
`completion_claim_allowed` 才会为 `true`。

示例中的“他皱眉。”会被识别为 `facial.brow_contract`，并给出精确文本区间、语义家族、叙事功能和置信度。应用也可以注入自己的 JSON 模型客户端；仓库不绑定供应商 SDK，也不读取 API Key。

正式使用时，每本书使用一个持久化 SQLite 文件。只有作者确认采用的正文才提交；数据库会原子写入正文、审查结果、行为抽取、场景状态和新的记忆版本。数据库备份与恢复命令为：

```bash
cpp-behavior-memory backup --db examples/story.db --output examples/story.backup.db
cpp-behavior-memory restore examples/story.backup.db --db examples/restored.db
```

旧版历史不会被猜测成正式行为记录。需要迁移时，先为每条旧记录明确填写小说位置和原文区间，再运行 `cpp-behavior-memory migrate-legacy`。

## 输入请求怎么写

请求使用 YAML 或 JSON。最常用的字段如下：

| 字段 | 含义 |
| --- | --- |
| `request_id` | 本次请求的唯一标识 |
| `character` | 角色 ID、Big Five 与平时的表达幅度 |
| `relationship` | 角色到目标人物的信任、敌意、支配等关系值 |
| `emotion_state` | 主次情绪、强度、VAD、克制和衰减时间 |
| `context` | 当前活动、公开/私密程度、观众数量、正式程度及显式事实 |
| `physical_state` | 伤势与动作限制 |
| `scene_state` | 姿态、位置、朝向、持物、人物距离、场景布局和版本号 |
| `blocking_goal` | 可选的走位目标与目标姿态 |
| `director` | 节拍重要度、最大动作信号数、可见程度及世界能力许可 |
| `seed` | 控制可复现选择的随机种子 |

建议复制 `examples/novel-scene.yaml` 后逐项修改。情绪既可使用标准 ID，也可以使用 Pack 中登记的中文别名。字段结构的权威定义位于 `schemas/`，需要重新导出时运行：

```bash
cpp-export-schemas --output schemas
```

## 连续写作与状态提交

仅预览时不要传 `--commit`，工具不会修改历史。确认采用正文后，再用 SQLite 数据库提交状态：

```bash
cpp-perform examples/novel-scene.yaml --name 洛寒 --dialogue "此事到此为止。" --db examples/story.db --commit --output examples/output
cpp-perform examples/output/next-request.json --name 洛寒 --db examples/story.db --commit --output examples/output
```

提交后，引擎会保存人物位置、姿态、持物、世界资源、已用动作及场景版本。再次提交旧版本请求会产生版本冲突，避免两个写作进程互相覆盖。

推荐工作流是：

1. 不带 `--commit` 生成预览。
2. 作者或上游 Agent 审阅 `prose.txt` 和 `plan.json`。
3. 决定采用后，使用相同请求与 seed 加 `--commit` 提交。
4. 下一回合从 `next-request.json` 开始，再调整情绪、关系、身体状态和 seed。

正文尚未采用时不要提前提交。没有合适的新动作时，引擎允许输出空片段，避免每句台词都机械附加表情。

## 跨回合移动、暂停与恢复

`examples/blocking-scene.yaml` 展示了从墙边移动到桌边并坐下的完整声明。场景需要明确地标、座位和有向路径，引擎不会自行编造房间拓扑。

```bash
cpp-perform examples/blocking-scene.yaml --name 洛寒 --db examples/navigation.db --commit --output examples/output/navigation
cpp-perform examples/output/navigation/next-request.json --action-control pause --db examples/navigation.db --commit --output examples/output/navigation
cpp-perform examples/output/navigation/next-request.json --action-control resume --elapsed-ms 1300 --db examples/navigation.db --commit --output examples/output/navigation
```

`elapsed_ms` 是该回合用于推进移动的毫秒数，范围为 0–60000。单回合最多经过一条路径边；暂停会保存进度，之后必须显式使用 `resume`。离开支撑物、移动、转向和坐下都会消耗动作信号预算。

## 在 Python 中使用

```python
from pathlib import Path

import yaml

from character_performance import PerformanceEngine, PerformancePack
from character_performance.domain import PerformanceRequest, RenderContext
from character_performance.storage import SQLiteRepository

project_root = Path(".")
raw = yaml.safe_load(
    (project_root / "examples/novel-scene.yaml").read_text(encoding="utf-8")
)

request = PerformanceRequest.model_validate(raw)
pack = PerformancePack.from_project(project_root)

store = SQLiteRepository("examples/story.db")
try:
    engine = PerformanceEngine(pack, store)
    plan = engine.plan(request)
    result = engine.render(
        plan,
        RenderContext(
            subject_name="洛寒",
            target_name="对方",
            dialogue="此事到此为止。",
        ),
    )
    print(result.text)

    # 只有正文被采用后才提交状态。
    next_scene = engine.commit(plan.plan_id, request.scene_state.revision)
finally:
    store.close()
```

## 编译发布 Pack

运行时可以直接读取仓库内的 YAML/JSON，也可以先构建一份经过校验的编译 Pack：

```bash
cpp-build-pack --output data/compiled
```

需要评估商业或再分发条件时，显式打开对应门禁：

```bash
cpp-build-pack --output data/compiled --commercial --redistribute
```

构建器会检查来源许可、规则字段、重复/近重复、情绪覆盖和表现通道覆盖。当前来源登记中仍有不允许商业使用或再分发的参考来源，因此上述严格命令会拒绝构建并指出具体来源；这正是许可门禁的预期效果。完成相应授权或移除相关依赖后，严格构建才会通过。

使用编译结果：

```bash
cpp-perform examples/novel-scene.yaml --pack data/compiled --name 洛寒
```

## 设计边界

- 工具负责“可解释的角色表现”，不负责剧情推进、整段文学创作或自动生成台词。
- 自由文本模型输出无法可靠证明没有虚构事实，因此内置约束渲染器只接受经过审核的表达选项；不合格结果会回退。
- 普通现实题材默认禁用修仙表现。修仙能力必须由世界类型、境界、角色能力和导演许可共同授权。
- `context.facts` 用于显式授权物件、前态、环境和话轮信息；持物事实还必须与场景持物状态一致。
- 当前场景布局在一次会话内固定，导航目标仅支持站立或就座；动态障碍、任意持续动作和开放式文风生成不在当前版本范围内。
- 默认局部改写器采取保守策略：删除最小问题片段，不负责把句子润色成最终文学成稿；需要更自然的替换时可注入外部改写适配器。

## 数据与隐私

运行时不上传小说正文，SQLite 记忆、生成结果、盲评答案和模型凭据都应保存在本地。仓库的 `.gitignore` 已排除 `runtime/`、`output/`、`review/`、数据库、环境变量文件、私钥、凭据文件，以及本地测试和规划资料。提交前仍建议运行 `git status`，确认没有把个人样稿或凭据放进其他自定义路径。

## 项目结构

```text
character-performance-pack/
├─ src/character_performance/   # 引擎、领域模型、渲染器与 CLI
├─ data/                        # 情绪本体、表现目录、修正规则与来源登记
├─ schemas/                     # 对外 JSON Schema
├─ examples/                    # 可直接运行的请求与完整工作流示例
├─ tools/                       # 目录编译、维护和质量检查工具
├─ pyproject.toml               # Python 包与命令入口
└─ README.md                    # 使用说明
```

## 版本

当前版本为 **0.6.0**。
