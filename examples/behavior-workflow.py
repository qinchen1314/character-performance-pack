"""Run a self-contained, offline prepare/audit/rewrite/commit demonstration.

Each invocation uses a fresh in-memory database. For a real book, replace
":memory:" with a persistent SQLite path and use distinct run IDs/positions.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from character_performance import BehaviorControlSystem, PerformancePack
from character_performance.domain.behavior_models import GenerationRequest
from character_performance.memory import SQLiteBehaviorMemory


ROOT = Path(__file__).resolve().parents[1]


def request_for(chapter: int) -> GenerationRequest:
    raw = yaml.safe_load((ROOT / "examples/behavior-request.yaml").read_text(encoding="utf-8"))
    raw["run_id"] = f"run.demo.chapter-{chapter:02d}"
    raw["position"].update(
        chapter_id=f"chapter.{chapter:02d}",
        scene_id=f"scene.demo.{chapter:02d}",
        global_beat_index=chapter,
    )
    raw["scene_state"]["scene_id"] = raw["position"]["scene_id"]
    return GenerationRequest.model_validate(raw)


def main() -> None:
    memory = SQLiteBehaviorMemory(":memory:")
    system = BehaviorControlSystem(
        pack=PerformancePack.from_project(ROOT), repository=memory
    )
    try:
        first = request_for(1)
        brief = system.prepare(first)
        print("写作提示：", brief.prompt_fragment)
        first_text = "他皱眉。"
        first_audit = system.audit(first.run_id, first_text)
        print("第一章审查通过：", first_audit.accepted)
        if not first_audit.accepted:
            raise RuntimeError(first_audit.model_dump_json(indent=2))
        committed = system.commit_text(first.run_id, first_text)
        print("正式记忆版本：", committed.memory_revision)

        second = request_for(2)
        system.prepare(second)
        repeat_audit = system.audit(second.run_id, first_text)
        print("第二章重复描写通过：", repeat_audit.accepted)
        print("重复问题：", ", ".join(issue.code for issue in repeat_audit.issues))
        # A blocking issue requires author review; abandon this demonstration run.
        system.abandon(second.run_id)

        third = request_for(3)
        system.prepare(third)
        draft = "他握拳。“好。”"
        audit = system.audit(third.run_id, draft)
        print("改写前：", draft)
        for _ in range(2):
            if audit.accepted or not audit.auto_rewrite_allowed:
                break
            draft = system.rewrite(third.run_id, draft, audit)
            audit = system.audit(third.run_id, draft)
        print("改写后：", draft)
        print("改写后审查通过：", audit.accepted)
        if not audit.accepted:
            raise RuntimeError("This draft requires author review: " + audit.model_dump_json())
        final = system.commit_text(third.run_id, draft)
        print("正式记忆版本：", final.memory_revision)
        replay = system.commit_text(third.run_id, draft)
        print("重复提交保持幂等：", replay.idempotent_replay)
    finally:
        memory.close()


if __name__ == "__main__":
    main()
