# Character Performance Pack

面向**中文小说角色情绪与动作描写**的本地 Python 工具。输入人物性格、情绪、关系、场景与身体状态，生成可解释的动作计划及中文片段；台词由作者提供。

当前版本 **0.3.0：持续动作与场景衔接**。已有 18 种情绪、48 个通用原子表现、10 个修仙表现、4 个导航控制单元、6 条可配置修正器、SQLite 连续性与中文渲染。核心无需联网或模型 API Key。

## 快速使用

Python 3.12+。在本目录运行：

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m character_performance.cli.build_pack --output data/compiled
python -m character_performance.cli.perform examples/novel-scene.yaml --name 洛寒 --output examples/output
```

输入示例：[examples/novel-scene.yaml](examples/novel-scene.yaml)。输出目录包括 `prose.txt`（片段）、`plan.json`（动作和诊断）、`render.json`（实现覆盖）、`next-request.json`（提交成功后可用的下一回合快照）。

也可使用安装后的 `cpp-perform`、`cpp-build-pack`、`cpp-export-schemas` 命令。

## 连续写作

```powershell
cpp-perform examples/novel-scene.yaml --name 洛寒 --dialogue "此事到此为止。" --db examples/story.db --commit --output examples/output
cpp-perform examples/output/next-request.json --name 洛寒 --db examples/story.db --commit --output examples/output
```

第一行用于新建场景的第一次提交，第二行从已提交快照继续。再次运行旧请求会返回版本冲突。可在下一回合请求中调整情绪、关系、身体状态和 seed；位置、持物及世界资源使用引擎返回的快照。`next-request.json` 仅在前一回合提交成功后有效。

不传 `--commit` 只生成预览，不修改场景或动作历史。正文生成后但尚未采用时不要提交。没有合理新动作时允许空片段，避免每句话都附加表情。

## 从墙边走到桌边坐下

[blocking-scene.yaml](examples/blocking-scene.yaml) 明确声明地标、座椅和有向路径；引擎自动安排离墙、移动、朝向调整和坐下，不自行编造场景拓扑。

```powershell
cpp-perform examples/blocking-scene.yaml --name 洛寒 --db examples/navigation.db --commit --output examples/output/navigation
cpp-perform examples/output/navigation/next-request.json --action-control pause --db examples/navigation.db --commit --output examples/output/navigation
cpp-perform examples/output/navigation/next-request.json --action-control resume --elapsed-ms 1300 --db examples/navigation.db --commit --output examples/output/navigation
```

`elapsed_ms` 是该回合用于推进移动的时间额度（0–60000 毫秒）。一个回合至多经过一条路径边；剩余额度不会瞬移跨越后续地标。每个离墙、移动、转向或坐下步骤都占用一个信号预算，预算不足时保存进度到下一回合。

途中 `position=null`，具体进度由 `active_action.route / edge_index / elapsed_ms` 表示；暂停保留进度，需要显式 resume 才继续。持续移动记录为 continuation，不反复写“走去”，但到达必须描写。新位置没有给出的人物距离会被清空，避免沿用旧距离。CLI 导出的下一回合请求会将一次性控制重置为 continue，并在到达目标姿态后清除目标。

五回合完整示例：[持续动作样本](docs/evaluation/blocking.md)。重生成命令：`python tools/demo_blocking.py`。

## Python 接入写作 Agent

```python
from pathlib import Path
import yaml
from character_performance import PerformanceEngine, PerformancePack
from character_performance.domain import PerformanceRequest, RenderContext
from character_performance.storage import SQLiteRepository

pack = PerformancePack.from_project(Path("."))
store = SQLiteRepository("examples/story.db")
engine = PerformanceEngine(pack, store)
request = PerformanceRequest.model_validate(
    yaml.safe_load(Path("examples/novel-scene.yaml").read_text(encoding="utf-8"))
)
plan = engine.plan(request)
result = engine.render(plan, RenderContext(subject_name="洛寒"))
print(result.text)
# 作者/上游 Agent 采用片段后：
next_scene = engine.commit(plan.plan_id, request.scene_state.revision)
store.close()
```

关系按角色方向保存；`masking` 可指定掩饰强度，缺省采用情绪的 `restraint`。普通现实题材默认禁用修仙表现。修仙需要同时声明 `world_state.genre=xianxia`、境界、角色能力和 `director.allow_world=true`。回收神识/威压类行为还要求相应能力已处于活动状态。

## 数据、质量与边界

- 人格和关系调整语义分数与幅度，不将某类人物绑定为固定动作。
- 候选先检查能力、受伤、持物、前置状态和世界规则，再参与评分；规则取值错误在构建时拒绝。
- `plan → render → commit` 分开；状态、资源和历史使用 SQLite 事务提交，共享场景版本控制并发。
- 语义、通道和表达短语共同参与反重复；固定输入、Pack、规则及 seed 可复现。
- 喜悦、感激也区分主动表达与克制回应；从同一场景最近 12 个已提交信号中提取其他角色的动作，参与轻度反重复。该偏好有上限，旧动作会随场景推进退出窗口，不改写明确的走位指令；计划保存当时的历史快照，重启后仍可验证回放。
- `ConstrainedLLMRenderer` 允许模型选择已审核的表达选项；任意自由文本不能可靠证明没有虚构事实，因此被拒绝并回退。模型端口由调用方配置并负责网络超时；未内置外部供应商依赖。
- 0.3 支持已知路径上的跨回合移动、暂停/恢复与姿态衔接。活动导航期间禁止自主身体/空间动作改写物理状态；可以补充符合预算的视线、面部或语气。图中无路径、缺座椅或伤势不允许时保留原状态并返回原因。
- 当前布局在一个场景会话内固定，导航目的地只支持 standing/seated；任意持续动作、取消后改道、动态障碍同步、开放式文风生成和文学盲评仍待后续实现。
- 62 个单元用于验证场景覆盖，尚未宣称满足完整 200–400 单元扩展目标。现有情绪来源策略继续限制商业和再分发构建；新增动作、语法和世界规则均为原创。

```powershell
python tools/evaluate.py --run-tests
cpp-export-schemas --output schemas
```

评估生成 [指标与20回合样本](docs/evaluation/latest.md) 及机器可读 JSON。本轮实现与优化依据见 [0.3 阶段报告](docs/phase-reports/continuity-0.3.md)、[导航决策](docs/adr/0002-continuous-blocking.md)；完整目标见 [实现文档](docs/implementation-spec.md)。
