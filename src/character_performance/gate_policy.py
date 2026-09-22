"""Single source of truth for machine acceptance gate thresholds."""

from __future__ import annotations

from dataclasses import dataclass
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
    GateSpec("REWRITE_PRESERVATION", "rewrite_preservation_rate", 1.0, ">="),
    GateSpec("DUPLICATE_HISTORY_COUNT", "duplicate_history_count", 0.0, "=="),
    GateSpec("FAULT_INJECTION", "fault_injection_passed", 1.0, "=="),
    GateSpec("PREPARE_P95_MS", "prepare_p95_ms", 100.0, "<="),
    GateSpec("RULE_EXTRACTION_P95_MS", "rule_extraction_p95_ms", 80.0, "<="),
    GateSpec("HISTORY_QUERY_P95_MS", "history_query_p95_ms", 30.0, "<="),
    GateSpec("COMMIT_P95_MS", "commit_p95_ms", 50.0, "<="),
    GateSpec("DETERMINISTIC_REPLAY", "deterministic_replay_passed", 1.0, "=="),
)


__all__ = ["AUTOMATIC_GATE_SPECS", "MEMORY_GATE_SPECS", "Comparator", "GateSpec", "gate_passes"]
