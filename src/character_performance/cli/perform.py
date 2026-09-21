from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from character_performance.domain.models import PerformanceRequest, RenderContext
from character_performance.engine import PerformanceEngine
from character_performance.ontology.pack import PerformancePack
from character_performance.storage import SQLiteRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="为小说角色生成情绪动作与中文描写")
    parser.add_argument("request", type=Path, help="YAML/JSON PerformanceRequest")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--pack", type=Path, help="已编译 Pack 目录")
    parser.add_argument("--name", default="他")
    parser.add_argument("--target-name", default="对方")
    parser.add_argument("--dialogue", help="作者提供的台词，原样保留")
    parser.add_argument("--output", type=Path, help="保存正文、计划及下一回合请求")
    parser.add_argument("--db", type=Path, help="SQLite 连续性历史库")
    parser.add_argument("--commit", action="store_true", help="渲染成功后提交本回合状态")
    parser.add_argument("--elapsed-ms", type=int, help="本回合允许推进动作的毫秒数")
    parser.add_argument("--action-control", choices=("continue", "pause", "resume"), help="持续动作控制")
    args = parser.parse_args()
    if args.commit and not args.db:
        parser.error("--commit requires --db for persistent history")
    repository = None
    try:
        raw_request = yaml.safe_load(args.request.read_text(encoding="utf-8"))
        if args.elapsed_ms is not None:
            raw_request["elapsed_ms"] = args.elapsed_ms
        if args.action_control is not None:
            raw_request["action_control"] = args.action_control
        request = PerformanceRequest.model_validate(raw_request)
        pack = PerformancePack.from_compiled(args.pack) if args.pack else PerformancePack.from_project(args.project_root)
        repository = SQLiteRepository(args.db or ":memory:")
        engine = PerformanceEngine(pack, repository)
        plan = engine.plan(request)
        result = engine.render(plan, RenderContext(subject_name=args.name, target_name=args.target_name, dialogue=args.dialogue))
        next_values = request.model_dump(mode="json")
        next_values.update(request_id=request.request_id + ".next", scene_state=plan.state_transition.after.model_dump(mode="json"), world_state=plan.state_transition.world_after.model_dump(mode="json"))
        next_values["action_control"] = "continue"
        goal = request.blocking_goal
        after = plan.state_transition.after
        if goal and after.active_action is None and after.position == goal.destination and after.pose == goal.pose:
            next_values["blocking_goal"] = None
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            (args.output / "render.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
            (args.output / "prose.txt").write_text(result.text + "\n", encoding="utf-8")
            (args.output / "next-request.json").write_text(json.dumps(next_values, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.commit:
            engine.commit(plan.plan_id, request.scene_state.revision)
        print(result.text or "（本回合无需补写动作）")
        for warning in plan.warnings + result.warnings:
            print(f"[提示] {warning}")
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f"无法生成角色表现：{error}\n")
    finally:
        if repository is not None:
            repository.close()


if __name__ == "__main__":
    main()
