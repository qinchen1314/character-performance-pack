# Character Performance Pack

面向**中文小说角色情绪与动作描写**的本地 Python 工具。输入人物性格、情绪、关系、场景与身体状态，生成可解释的动作计划及中文片段；台词由作者提供。

当前版本 **0.2.0：可运行的小说写作垂直切片**。已有 18 种情绪、48 个通用原子表现、10 个修仙表现、6 条可配置修正器、SQLite 连续性与中文渲染。核心无需联网或模型 API Key。

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
- `ConstrainedLLMRenderer` 允许模型选择已审核的表达选项；任意自由文本不能可靠证明没有虚构事实，因此被拒绝并回退。模型端口由调用方配置并负责网络超时；未内置外部供应商依赖。
- 当前状态动作是瞬时单步；靠墙直接到桌边坐下不会凭空发生。未完成动作存在时保守限制新身体动作。持续动作/打断、导航桥接序列、开放式文风生成和文学盲评仍属于 v1.0 后续工作。
- 58 个单元用于验证场景覆盖，尚未宣称满足完整 200–400 单元扩展目标。现有情绪来源策略继续限制商业和再分发构建；新增动作、语法和世界规则均为原创。

```powershell
python tools/evaluate.py --run-tests
cpp-export-schemas --output schemas
```

评估生成 [指标与20回合样本](docs/evaluation/latest.md) 及机器可读 JSON。完整实施范围与剩余差距见 [阶段总览](docs/phase-reports/runtime-mvp.md)、[决策记录](docs/adr/0001-local-novel-runtime.md) 和 [实现文档](docs/implementation-spec.md)。
