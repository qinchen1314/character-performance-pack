"""Acceptance benchmarks and identity-blind human gates for behavior control."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from hashlib import sha256
from math import ceil, comb
import random
from statistics import fmean
from typing import Literal, Protocol, Sequence

from pydantic import Field, model_validator

from .domain.behavior_models import ExtractionRequest, ExtractionResult
from .domain.models import DomainModel
from .gate_policy import AUTOMATIC_GATE_SPECS, GatePolicy, gate_passes


class ExtractionAdapter(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


class ExtractionTruth(DomainModel):
    actor_id: str = Field(min_length=1)
    semantic_group: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> "ExtractionTruth":
        if self.end <= self.start:
            raise ValueError("truth span end must be greater than start")
        return self


class ExtractionBenchmarkCase(DomainModel):
    request: ExtractionRequest
    truths: tuple[ExtractionTruth, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def truths_fit_source(self) -> "ExtractionBenchmarkCase":
        known = {character.id for character in self.request.known_characters}
        for truth in self.truths:
            if truth.actor_id not in known:
                raise ValueError("truth actor must be a known character")
            if truth.end > len(self.request.text):
                raise ValueError("truth span exceeds source text")
        return self


class ExtractionBenchmarkResult(DomainModel):
    case_count: int = Field(ge=1)
    truth_count: int = Field(ge=1)
    prediction_count: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    span_accuracy: float = Field(ge=0, le=1)


def benchmark_extractor(
    extractor: ExtractionAdapter, cases: Sequence[ExtractionBenchmarkCase]
) -> ExtractionBenchmarkResult:
    if not cases:
        raise ValueError("at least one extraction benchmark case is required")
    truth_count = prediction_count = true_positives = exact_spans = 0
    for case in cases:
        result = extractor.extract(case.request)
        case.request.validate_result(result)
        predictions = list(result.behaviors)
        prediction_count += len(predictions)
        truth_count += len(case.truths)
        unmatched = set(range(len(predictions)))
        for truth in case.truths:
            compatible = [
                index
                for index in unmatched
                if predictions[index].actor_id == truth.actor_id
                and truth.semantic_group in predictions[index].semantic_groups
            ]
            if not compatible:
                continue
            exact = [
                index
                for index in compatible
                if predictions[index].text_span.start == truth.start
                and predictions[index].text_span.end == truth.end
            ]
            chosen = exact[0] if exact else compatible[0]
            unmatched.remove(chosen)
            true_positives += 1
            exact_spans += int(chosen in exact)
    false_positives = prediction_count - true_positives
    false_negatives = truth_count - true_positives
    return ExtractionBenchmarkResult(
        case_count=len(cases),
        truth_count=truth_count,
        prediction_count=prediction_count,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=true_positives / prediction_count if prediction_count else 0.0,
        recall=true_positives / truth_count,
        span_accuracy=exact_spans / true_positives if true_positives else 0.0,
    )


def percentile(samples: Sequence[float], percentile_value: float) -> float:
    """Return a deterministic nearest-rank percentile for benchmark timings."""
    if not samples:
        raise ValueError("percentile needs at least one sample")
    if not 0 < percentile_value <= 100:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(float(sample) for sample in samples)
    return ordered[ceil(percentile_value / 100 * len(ordered)) - 1]


class CharacterBlindSample(DomainModel):
    sample_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    character_name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def redactions_are_unique(self) -> "CharacterBlindSample":
        values = (self.character_name, *self.aliases)
        if len(values) != len(set(values)):
            raise ValueError("character name and aliases must be unique")
        return self


class CharacterBlindItem(DomainModel):
    sample_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class CharacterBlindPacket(DomainModel):
    packet_id: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    candidate_labels: tuple[str, ...] = Field(min_length=2)
    items: tuple[CharacterBlindItem, ...] = Field(min_length=2)


class CharacterBlindKey(DomainModel):
    packet_id: str = Field(min_length=1)
    sample_characters: dict[str, str]
    label_to_character: dict[str, str]

    @property
    def character_to_label(self) -> dict[str, str]:
        return {character: label for label, character in self.label_to_character.items()}


HumanFlag = Literal[
    "mechanical", "formulaic", "indistinguishable", "contrived_variation"
]


class CharacterBlindRating(DomainModel):
    sample_id: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    guessed_label: str = Field(min_length=1)
    naturalness: int = Field(ge=1, le=5)
    character_fit: int = Field(ge=1, le=5)
    prose_value: int = Field(ge=1, le=5)
    flags: tuple[HumanFlag, ...] = ()
    note: str = ""

    @model_validator(mode="after")
    def flags_are_unique(self) -> "CharacterBlindRating":
        if len(self.flags) != len(set(self.flags)):
            raise ValueError("rating flags must be unique")
        return self


class HumanBlindSummary(DomainModel):
    packet_id: str
    reviewer_count: int = Field(ge=0)
    rating_count: int = Field(ge=0)
    recognition_rate: float = Field(ge=0, le=1)
    random_baseline: float = Field(gt=0, le=1)
    recognition_p_value: float = Field(ge=0, le=1)
    naturalness: float = Field(ge=1, le=5)
    character_fit: float = Field(ge=1, le=5)
    prose_value: float = Field(ge=1, le=5)
    flag_rates: dict[HumanFlag, float]
    status: Literal["pending", "passed", "failed"]


def build_character_blind_packet(
    samples: Sequence[CharacterBlindSample], *, seed: int
) -> tuple[CharacterBlindPacket, CharacterBlindKey]:
    if len(samples) < 2:
        raise ValueError("blind recognition requires at least two samples")
    sample_ids = [sample.sample_id for sample in samples]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("sample ids must be unique")
    characters = sorted({sample.character_id for sample in samples})
    if len(characters) < 2:
        raise ValueError("blind recognition requires at least two characters")
    shuffled_characters = list(characters)
    random.Random(seed).shuffle(shuffled_characters)
    labels = tuple(f"角色-{index + 1:02d}" for index in range(len(characters)))
    label_to_character = dict(zip(labels, shuffled_characters, strict=True))
    items: list[CharacterBlindItem] = []
    for sample in samples:
        redacted = sample.text
        for name in sorted((sample.character_name, *sample.aliases), key=len, reverse=True):
            redacted = redacted.replace(name, "某人")
        if sample.character_id in redacted:
            raise ValueError("sample text leaks character_id")
        if any(name in redacted for name in (sample.character_name, *sample.aliases)):
            raise ValueError("sample text still contains a character name or alias")
        items.append(CharacterBlindItem(sample_id=sample.sample_id, text=redacted))
    random.Random(seed ^ 0xC0DE).shuffle(items)
    digest = sha256(
        f"{seed}|".encode() + "|".join(sorted(sample_ids)).encode("utf-8")
    ).hexdigest()[:12]
    packet_id = f"character-blind.{digest}"
    return (
        CharacterBlindPacket(
            packet_id=packet_id,
            instructions="隐去角色名后判断片段属于哪个匿名角色，并评分自然度、角色符合度与正文价值。",
            candidate_labels=labels,
            items=tuple(items),
        ),
        CharacterBlindKey(
            packet_id=packet_id,
            sample_characters={sample.sample_id: sample.character_id for sample in samples},
            label_to_character=label_to_character,
        ),
    )


def aggregate_character_blind_ratings(
    key: CharacterBlindKey,
    ratings: Sequence[CharacterBlindRating],
    *,
    minimum_reviewers: int = 2,
) -> HumanBlindSummary:
    if minimum_reviewers < 2:
        raise ValueError("blind review requires at least two independent reviewers")
    if not ratings:
        raise ValueError("at least one rating is required")
    sample_ids = set(key.sample_characters)
    labels = set(key.label_to_character)
    pairs: set[tuple[str, str]] = set()
    by_reviewer: dict[str, set[str]] = defaultdict(set)
    for rating in ratings:
        if rating.sample_id not in sample_ids:
            raise ValueError(f"unknown blind sample: {rating.sample_id}")
        if rating.guessed_label not in labels:
            raise ValueError(f"unknown character label: {rating.guessed_label}")
        pair = (rating.reviewer_id, rating.sample_id)
        if pair in pairs:
            raise ValueError("each reviewer may rate a sample only once")
        pairs.add(pair)
        by_reviewer[rating.reviewer_id].add(rating.sample_id)
    incomplete = [reviewer for reviewer, seen in by_reviewer.items() if seen != sample_ids]
    if incomplete:
        raise ValueError(f"reviewers must rate every sample: {sorted(incomplete)}")
    correct = sum(
        key.label_to_character[rating.guessed_label]
        == key.sample_characters[rating.sample_id]
        for rating in ratings
    )
    flag_counts = Counter(flag for rating in ratings for flag in rating.flags)
    flag_rates = {
        flag: flag_counts[flag] / len(ratings)
        for flag in (
            "mechanical",
            "formulaic",
            "indistinguishable",
            "contrived_variation",
        )
    }
    reviewer_count = len(by_reviewer)
    recognition = correct / len(ratings)
    random_baseline = 1 / len(labels)
    recognition_p_value = sum(
        comb(len(ratings), successes)
        * random_baseline**successes
        * (1 - random_baseline) ** (len(ratings) - successes)
        for successes in range(correct, len(ratings) + 1)
    )
    scores = {
        name: fmean(getattr(rating, name) for rating in ratings)
        for name in ("naturalness", "character_fit", "prose_value")
    }
    if reviewer_count < minimum_reviewers:
        status = "pending"
    elif (
        recognition >= 0.70
        and recognition_p_value <= 0.05
        and all(score >= 4.0 for score in scores.values())
        and all(rate <= 0.10 for rate in flag_rates.values())
    ):
        status = "passed"
    else:
        status = "failed"
    return HumanBlindSummary(
        packet_id=key.packet_id,
        reviewer_count=reviewer_count,
        rating_count=len(ratings),
        recognition_rate=recognition,
        random_baseline=random_baseline,
        recognition_p_value=recognition_p_value,
        flag_rates=flag_rates,
        status=status,
        **scores,
    )


class EvidenceProvenance(DomainModel):
    producer: Literal["cpp-behavior-verification-suite"]
    commit_sha: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    generated_at: datetime
    history_row_count: int = Field(ge=1_000_000)
    book_occurrence_count: int = Field(ge=200_000)
    test_counts: dict[
        Literal[
            "unit",
            "property",
            "integration",
            "scenario",
            "chapter_benchmark",
            "fault_injection",
            "performance",
        ],
        int,
    ]

    @model_validator(mode="after")
    def every_suite_ran(self) -> "EvidenceProvenance":
        required = {
            "unit",
            "property",
            "integration",
            "scenario",
            "chapter_benchmark",
            "fault_injection",
            "performance",
        }
        if set(self.test_counts) != required or any(count < 1 for count in self.test_counts.values()):
            raise ValueError("all required verification suites must report a positive test count")
        return self


class AutomaticEvidence(DomainModel):
    provenance: EvidenceProvenance
    immediate_exact_repeat_rate: float = Field(ge=0, le=1)
    chapter_semantic_over_limit: int = Field(ge=0)
    cliche_group_share: float = Field(ge=0, le=1)
    maximum_character_channel_share: float = Field(ge=0, le=1)
    cross_chapter_function_channel_repeat_rate: float = Field(ge=0, le=1)
    semantic_repeat_recall: float = Field(ge=0, le=1)
    semantic_repeat_precision: float = Field(ge=0, le=1)
    span_accuracy: float = Field(ge=0, le=1)
    rewrite_preservation_rate: float = Field(ge=0, le=1)
    duplicate_history_count: int = Field(ge=0)
    fault_injection_passed: bool
    prepare_p95_ms: float = Field(ge=0)
    rule_extraction_p95_ms: float = Field(ge=0)
    history_query_p95_ms: float = Field(ge=0)
    commit_p95_ms: float = Field(ge=0)
    deterministic_replay_passed: bool


class AcceptanceGate(DomainModel):
    code: str
    value: float
    threshold: float
    comparator: Literal["<=", ">=", "=="]
    passed: bool


class AcceptanceReport(DomainModel):
    automatic_status: Literal["passed", "failed"]
    human_status: Literal["pending", "passed", "failed"]
    overall_status: Literal["pending_human", "passed", "failed"]
    completion_claim_allowed: bool
    automatic_gates: tuple[AcceptanceGate, ...]
    human_summary: HumanBlindSummary | None = None


class AcceptanceEvaluator:
    def __init__(self, *, gate_policy: GatePolicy | None = None) -> None:
        self.gate_specs = (
            gate_policy.apply_ready(AUTOMATIC_GATE_SPECS)
            if gate_policy is not None
            else AUTOMATIC_GATE_SPECS
        )

    def evaluate(
        self,
        automatic: AutomaticEvidence,
        human: HumanBlindSummary | None = None,
    ) -> AcceptanceReport:
        gates = tuple(
            AcceptanceGate(
                code=spec.code,
                value=value,
                threshold=spec.threshold,
                comparator=spec.comparator,
                passed=gate_passes(value, spec),
            )
            for spec in self.gate_specs
            for value in (float(getattr(automatic, spec.evidence_field)),)
        )
        automatic_status = "passed" if all(gate.passed for gate in gates) else "failed"
        human_status = human.status if human is not None else "pending"
        if automatic_status == "failed" or human_status == "failed":
            overall = "failed"
        elif human_status == "pending":
            overall = "pending_human"
        else:
            overall = "passed"
        return AcceptanceReport(
            automatic_status=automatic_status,
            human_status=human_status,
            overall_status=overall,
            completion_claim_allowed=overall == "passed",
            automatic_gates=gates,
            human_summary=human,
        )


def render_acceptance_markdown(report: AcceptanceReport) -> str:
    lines = [
        "# 跨章节角色行为控制验收报告",
        "",
        f"- 自动门禁：{report.automatic_status}",
        f"- 真人门禁：{report.human_status}",
        f"- 总体状态：{report.overall_status}",
        f"- 允许宣告完成：{'是' if report.completion_claim_allowed else '否'}",
        "",
        "## 自动门禁",
        "",
        "| 指标 | 当前值 | 阈值 | 结果 |",
        "|---|---:|---:|---|",
    ]
    for gate in report.automatic_gates:
        lines.append(
            f"| {gate.code} | {gate.value:.4f} | {gate.comparator} {gate.threshold:.4f} | {'通过' if gate.passed else '失败'} |"
        )
    lines.extend(["", "## 真人盲评", ""])
    if report.human_summary is None:
        lines.append("尚未提供真人盲评结果；总体状态保持 pending_human。")
    else:
        human = report.human_summary
        lines.extend(
            [
                f"- 独立评审人数：{human.reviewer_count}",
                f"- 角色识别率：{human.recognition_rate:.2%}（随机基线 {human.random_baseline:.2%}）",
                f"- 识别显著性 p 值：{human.recognition_p_value:.4f}",
                f"- 自然度：{human.naturalness:.2f}/5",
                f"- 角色符合度：{human.character_fit:.2f}/5",
                f"- 正文价值：{human.prose_value:.2f}/5",
            ]
        )
        lines.extend(f"- {flag} 标记率：{rate:.2%}" for flag, rate in human.flag_rates.items())
    return "\n".join(lines) + "\n"


__all__ = [
    "AcceptanceEvaluator", "AcceptanceGate", "AcceptanceReport", "AutomaticEvidence", "EvidenceProvenance",
    "CharacterBlindItem", "CharacterBlindKey", "CharacterBlindPacket", "CharacterBlindRating",
    "CharacterBlindSample", "ExtractionBenchmarkCase", "ExtractionBenchmarkResult", "ExtractionTruth",
    "HumanBlindSummary", "aggregate_character_blind_ratings", "benchmark_extractor",
    "build_character_blind_packet", "percentile", "render_acceptance_markdown",
]
