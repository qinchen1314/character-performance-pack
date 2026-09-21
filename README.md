# Character Performance Pack

面向小说与世界模拟 Agent 的人物动态表演本体与组合引擎。

当前实现里程碑为 Phase 0–2：来源许可门禁、Canonical Schema、Emotion Ontology 与 VAD。

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m character_performance.cli.build_pack --output data/compiled
```

设计与阶段验收要求见 [实现文档](docs/implementation-spec.md)。

