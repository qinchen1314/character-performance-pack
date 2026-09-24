"""Single source of truth for machine acceptance gate thresholds."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Literal


Comparator = Literal["<=", ">=", "=="]


@dataclass(frozen=True, slots=True)
class GateSpec:
    code: str
    evidence_field: str
    threshold: float
    comparator: Comparator


def gate_passes(value: float, spec: GateSpec) -> bool:
    if spec.comparator == "<=":
        return value <= spec.threshold
    if spec.comparator == ">=":
        return value >= spec.threshold
    return value == spec.threshold


@dataclass(frozen=True, slots=True)
class GatePolicy:
    status: Literal["provisional", "ready"]
    source_report_sha256: str
    overrides: tuple[GateSpec, ...]

    def apply(self, specs: tuple[GateSpec, ...]) -> tuple[GateSpec, ...]:
        by_code = {spec.code: spec for spec in self.overrides}
        return tuple(by_code.get(spec.code, spec) for spec in specs)

    def apply_ready(self, specs: tuple[GateSpec, ...]) -> tuple[GateSpec, ...]:
        if self.status != "ready":
            raise ValueError("only ready gate policies can drive acceptance")
        return self.apply(specs)


def load_gate_policy(path: Path, *, require_ready: bool = True) -> GatePolicy:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0.0":
        raise ValueError("unsupported threshold policy schema_version")
    status = payload.get("status")
    if status not in {"provisional", "ready"}:
        raise ValueError("threshold policy status must be provisional or ready")
    if require_ready and status != "ready":
        raise ValueError("provisional threshold policy cannot replace acceptance gates")
    source_hash = payload.get("source_report_sha256", "")
    if not isinstance(source_hash, str) or re.fullmatch(
        r"sha256:[0-9a-f]{64}", source_hash
    ) is None:
        raise ValueError("threshold policy requires source_report_sha256")
    known = {spec.code: spec for spec in AUTOMATIC_GATE_SPECS}
    overrides: list[GateSpec] = []
    gates = payload.get("gates")
    if not isinstance(gates, dict) or not gates:
        raise ValueError("threshold policy requires non-empty gates")
    for code, item in gates.items():
        if code not in known or not isinstance(item, dict):
            raise ValueError(f"unknown threshold gate: {code}")
        comparator = item.get("comparator")
        threshold = item.get("threshold")
        if comparator != known[code].comparator:
            raise ValueError(f"threshold comparator cannot change for {code}")
        if (
            not isinstance(threshold, (int, float))
            or isinstance(threshold, bool)
            or not math.isfinite(threshold)
            or threshold < 0
        ):
            raise ValueError(f"invalid threshold for {code}")
        if code in {
            "IMMEDIATE_EXACT_REPEAT_RATE",
            "CLICHE_GROUP_SHARE",
            "MAX_CHARACTER_CHANNEL_SHARE",
            "CROSS_CHAPTER_FUNCTION_CHANNEL_REPEAT_RATE",
            "SEMANTIC_REPEAT_RECALL",
            "SEMANTIC_REPEAT_PRECISION",
            "SPAN_ACCURACY",
            "REWRITE_GRAMMAR_INTEGRITY",
            "REWRITE_DIALOGUE_PRESERVATION",
            "REWRITE_FACT_PRESERVATION",
        } and threshold > 1:
            raise ValueError(f"rate threshold must be between 0 and 1 for {code}")
        overrides.append(
            GateSpec(code, known[code].evidence_field, float(threshold), comparator)
        )
    return GatePolicy(status, source_hash, tuple(overrides))


MEMORY_GATE_SPECS = (
    GateSpec("IMMEDIATE_EXACT_REPEAT_RATE", "immediate_exact_repeat_rate", 0.0, "<="),
    GateSpec("CHAPTER_SEMANTIC_OVER_LIMIT", "chapter_semantic_over_limit", 0.0, "<="),
    GateSpec("CLICHE_GROUP_SHARE", "cliche_group_share", 0.20, "<="),
    GateSpec("MAX_CHARACTER_CHANNEL_SHARE", "maximum_character_channel_share", 0.45, "<="),
    GateSpec("CROSS_CHAPTER_FUNCTION_CHANNEL_REPEAT_RATE", "cross_chapter_function_channel_repeat_rate", 0.10, "<="),
)


AUTOMATIC_GATE_SPECS = MEMORY_GATE_SPECS + (
    GateSpec("SEMANTIC_REPEAT_RECALL", "semantic_repeat_recall", 0.90, ">="),
    GateSpec("SEMANTIC_REPEAT_PRECISION", "semantic_repeat_precision", 0.85, ">="),
    GateSpec("SPAN_ACCURACY", "span_accuracy", 0.98, ">="),
    GateSpec("REWRITE_GRAMMAR_INTEGRITY", "rewrite_grammar_integrity_rate", 1.0, ">="),
    GateSpec(
        "REWRITE_DIALOGUE_PRESERVATION",
        "rewrite_dialogue_preservation_rate",
        1.0,
        ">=",
    ),
    GateSpec("REWRITE_FACT_PRESERVATION", "rewrite_fact_preservation_rate", 1.0, ">="),
    GateSpec("DUPLICATE_HISTORY_COUNT", "duplicate_history_count", 0.0, "=="),
    GateSpec("FAULT_INJECTION", "fault_injection_passed", 1.0, "=="),
    GateSpec("PREPARE_P95_MS", "prepare_p95_ms", 100.0, "<="),
    GateSpec("RULE_EXTRACTION_P95_MS", "rule_extraction_p95_ms", 80.0, "<="),
    GateSpec("HISTORY_QUERY_P95_MS", "history_query_p95_ms", 30.0, "<="),
    GateSpec("COMMIT_P95_MS", "commit_p95_ms", 50.0, "<="),
    GateSpec("DETERMINISTIC_REPLAY", "deterministic_replay_passed", 1.0, "=="),
)


__all__ = ["AUTOMATIC_GATE_SPECS", "MEMORY_GATE_SPECS", "Comparator", "GatePolicy", "GateSpec", "gate_passes", "load_gate_policy"]
