"""Offline regression runner and coverage/latency report; no network or LLM required."""
from __future__ import annotations

import argparse
from collections import Counter
from itertools import combinations
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
from time import perf_counter
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from character_performance.domain.models import CharacterProfile, EmotionState, PerformanceRequest, Personality, RelationshipState, SceneState, VAD
from character_performance.engine import PerformanceEngine
from character_performance.ontology.pack import PerformancePack


def evaluate() -> dict:
    pack = PerformancePack.from_project(ROOT)
    request = PerformanceRequest(request_id="req.benchmark", character=CharacterProfile(id="char.hero"),
        relationship=RelationshipState(subject_id="char.hero", target_id="char.target"),
        emotion_state=EmotionState(primary="anger", intensity=.7, vad=VAD(valence=-.65, arousal=.7, dominance=.55), decay_half_life_ms=90000),
        scene_state=SceneState(scene_id="scene.benchmark", pose="standing", position="pos.hall", distances={"char.target": 3.2}), seed=10)
    groups, rounds, timings = Counter(), [], []
    engine = PerformanceEngine(pack)
    scene = request.scene_state
    for turn in range(20):
        current = request.model_copy(update={"request_id": f"req.benchmark.{turn}", "scene_state": scene, "seed": turn})
        start = perf_counter()
        plan = engine.plan(current)
        timings.append((perf_counter() - start) * 1000)
        rendered = engine.render(plan)
        scene = engine.commit(plan.plan_id, scene.revision)
        groups.update(group for key in plan.unit_ids for group in pack.get(key).semantic_groups)
        rounds.append({"turn": turn, "units": plan.unit_ids, "text": rendered.text, "revision": scene.revision})
    engine.repository.close()
    signatures = []
    profiles = [(.95, .1, .5, .1), (.1, .95, .05, .2), (.95, .7, .65, .05), (.2, .05, .7, .95)]
    for conscientiousness, extraversion, agreeableness, neuroticism in profiles:
        profile = CharacterProfile(id="char.hero", personality=Personality(big_five=dict(conscientiousness=conscientiousness, extraversion=extraversion, agreeableness=agreeableness, neuroticism=neuroticism)))
        engine = PerformanceEngine(pack)
        plan = engine.plan(request.model_copy(update={"character": profile}))
        signatures.append({(pack.get(key).channel, group) for key in plan.unit_ids for group in pack.get(key).semantic_groups})
        engine.repository.close()
    jaccard = sum(len(a & b) / len(a | b) for a, b in combinations(signatures, 2)) / 6
    total = sum(len(row["units"]) for row in rounds)
    trope = sum(groups[key] for key in ("brow_tension", "hand_tension", "mouth_change", "gaze_flash", "deep_breath"))
    recent_repeat = any(set(row["units"]) & {key for previous in rounds[max(0, i-3):i] for key in previous["units"]} for i, row in enumerate(rounds))
    units = pack.all()
    return {
        "pack_version": pack.version, "pack_hash": pack.content_hash, "rule_version": "1.0.0",
        "coverage": {"emotions": len(pack.ontology), "units": len(units),
            "categories": dict(sorted(Counter(u.category for u in units).items())),
            "body_parts": sorted({part for u in units for part in u.body_parts}),
            "emotion_candidates": {e.id: sum(e.id in u.emotion_affinity for u in units) for e in pack.ontology.all()},
            "stateful_units": sum(bool(u.effects) for u in units), "modifiers": len(pack.modifiers)},
        "metrics": {"persona_mean_jaccard": round(jaccard, 4), "signals_20_turns": total,
            "max_semantic_group_count": max(groups.values(), default=0), "trope_fraction": round(trope / total, 4) if total else 0,
            "adjacent_3_repeat": recent_repeat, "no_valid_candidate_rate": sum(not row["units"] for row in rounds) / 20,
            "planner_p50_ms": round(median(timings), 3), "planner_p95_ms": round(sorted(timings)[18], 3)},
        "gates": {"T1": jaccard <= .55, "T4": max(groups.values(), default=0) <= 4 and not recent_repeat and trope / max(1, total) <= .3},
        "semantic_counts": dict(sorted(groups.items())), "rounds": rounds,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evaluation/latest.json")
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = evaluate()
    status = 0
    if args.run_tests:
        junit = args.output.with_suffix(".junit.xml")
        completed = subprocess.run([sys.executable, "-m", "pytest", f"--junitxml={junit}"], cwd=ROOT)
        status = completed.returncode
        if junit.exists():
            suites = ET.parse(junit).getroot()
            report["tests"] = {key: sum(int(suite.attrib.get(key, 0)) for suite in suites.iter("testsuite")) for key in ("tests", "failures", "errors", "skipped")}
        report["gates"]["regression_suite"] = status == 0
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = args.output.with_suffix(".md")
    rows = ["# 离线评估报告", "", f"Pack {report['pack_version']} / SHA-256 `{report['pack_hash']}`", "", "## 指标", "", "| 指标 | 实测 |", "|---|---:|"]
    rows += [f"| {key} | {value} |" for key, value in report["metrics"].items()]
    rows += ["", "## 20 回合描写样本", "", "| 回合 | 片段 |", "|---:|---|"]
    rows += [f"| {row['turn'] + 1} | {row['text'] or '（省略动作）'} |" for row in report["rounds"]]
    if "tests" in report:
        rows += ["", "测试结果：`" + json.dumps(report["tests"]) + "`。"]
    rows += ["", "固定基准用于工程回归，不代表盲评、开放题材覆盖或正式生产 SLO。", ""]
    markdown.write_text("\n".join(rows), encoding="utf-8")
    print(json.dumps({"report": str(args.output), "metrics": report["metrics"], "gates": report["gates"]}, ensure_ascii=False, indent=2))
    raise SystemExit(status or (0 if all(report["gates"].values()) else 1))


if __name__ == "__main__":
    main()
