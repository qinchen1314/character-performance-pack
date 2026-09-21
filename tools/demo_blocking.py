"""Write a reproducible multi-turn movement/pause/resume example."""
import argparse
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from character_performance import PerformanceEngine, PerformancePack
from character_performance.domain import PerformanceRequest, RenderContext


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evaluation/blocking.json")
    args = parser.parse_args()
    pack = PerformancePack.from_project(ROOT)
    engine = PerformanceEngine(pack)
    request = PerformanceRequest.model_validate(yaml.safe_load((ROOT / "examples/blocking-scene.yaml").read_text(encoding="utf-8")))
    rows = []
    for control, elapsed in [("continue", 700), ("pause", 700), ("continue", 700), ("resume", 700), ("continue", 700)]:
        current = request.model_copy(update={"action_control": control, "elapsed_ms": elapsed})
        plan = engine.plan(current)
        rendered = engine.render(plan, RenderContext(subject_name="洛寒"))
        scene = engine.commit(plan.plan_id, current.scene_state.revision)
        rows.append({"turn": scene.turn_index, "control": control, "text": rendered.text,
            "sequence": [step.model_dump(mode="json") for step in plan.sequence],
            "position": scene.position, "pose": scene.pose, "time_ms": scene.time_ms,
            "held_objects": scene.held_objects,
            "active_action": scene.active_action.model_dump(mode="json") if scene.active_action else None,
            "warnings": plan.warnings})
        request = request.model_copy(update={"scene_state": scene, "world_state": plan.state_transition.world_after})
    assert scene.pose == "seated" and scene.position == "pos.table" and scene.active_action is None
    assert scene.held_objects == {"right_hand": "object.sword"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"pack_version": pack.version, "pack_hash": pack.content_hash, "turns": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 持续动作与暂停恢复样本", "", "右手持剑、左肩受伤的洛寒，从墙边前往桌边坐下。中途暂停一回合后恢复。", "", "| 回合 | 控制 | 正文片段 | 已知位置 | 姿态 | 动作累计时间 |", "|---:|---|---|---|---|---:|"]
    lines += [f"| {row['turn']} | {row['control']} | {row['text'] or '（延续状态，省略重复动作）'} | {row['position'] or '途中'} | {row['pose']} | {row['time_ms']} ms |" for row in rows]
    lines += ["", "暂停不推进时间；途中不伪造地标位置；到达后才转向已知座椅并坐下。持剑状态在所有回合保留。", ""]
    args.output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    engine.repository.close()
    print(args.output)


if __name__ == "__main__":
    main()
