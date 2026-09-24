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

from .domain.behavior_models import ExtractedBehavior, ExtractionRequest, ExtractionResult
from .domain.models import DomainModel, NonEmptyId
from .gate_policy import AUTOMATIC_GATE_SPECS, GatePolicy, gate_passes


class ExtractionAdapter(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


class ExtractionTruth(DomainModel):
    actor_id: NonEmptyId
    target_ids: tuple[NonEmptyId, ...] = ()
    canonical_action: NonEmptyId
    semantic_group: NonEmptyId
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> "ExtractionTruth":
        if self.end <= self.start:
            raise ValueError("truth span end must be greater than start")
        if self.actor_id in self.target_ids:
            raise ValueError("truth actor cannot also be a target")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("truth target ids must be unique")
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
            unknown_targets = set(truth.target_ids) - known
            if unknown_targets:
                raise ValueError("truth targets must be known characters")
            if truth.end > len(self.request.text):
                raise ValueError("truth span exceeds source text")
        return self


class ExtractionMetrics(DomainModel):
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)


class ConfidenceCalibrationBin(DomainModel):
    lower_bound: float = Field(ge=0, le=1)
    upper_bound: float = Field(ge=0, le=1)
    count: int = Field(ge=1)
    mean_confidence: float = Field(ge=0, le=1)
    empirical_accuracy: float = Field(ge=0, le=1)
    absolute_gap: float = Field(ge=0, le=1)


class ConfidenceCalibration(DomainModel):
    bins: tuple[ConfidenceCalibrationBin, ...]
    expected_calibration_error: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0, le=1)


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
    mean_span_iou: float = Field(ge=0, le=1)
    micro: ExtractionMetrics
    macro: ExtractionMetrics
    error_counts: dict[str, int]
    error_type_confusion_matrix: dict[str, dict[str, int]]
    identity_confusion_matrix: dict[str, dict[str, int]]
    calibration: ConfidenceCalibration


def _span_iou(truth: ExtractionTruth, prediction: ExtractedBehavior) -> float:
    span = prediction.text_span
    intersection = max(0, min(truth.end, span.end) - max(truth.start, span.start))
    union = max(truth.end, span.end) - min(truth.start, span.start)
    return intersection / union if union else 0.0


def _identity_mismatches(
    truth: ExtractionTruth, prediction: ExtractedBehavior, *, minimum_iou: float
) -> frozenset[str]:
    mismatches: set[str] = set()
    if prediction.actor_id != truth.actor_id:
        mismatches.add("actor")
    if sorted(prediction.target_ids) != sorted(truth.target_ids):
        mismatches.add("target")
    if prediction.canonical_action != truth.canonical_action:
        mismatches.add("action")
    if truth.semantic_group not in prediction.semantic_groups:
        mismatches.add("semantic_group")
    if _span_iou(truth, prediction) < minimum_iou:
        mismatches.add("span")
    return frozenset(mismatches)


def _maximum_weight_assignment(weights: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    """Return a deterministic maximum-weight one-to-one assignment.

    The implementation is the O(n^3) Hungarian algorithm. Zero-weight edges are
    padding/incompatible pairs and are omitted from the returned assignment.
    """
    row_count = len(weights)
    column_count = len(weights[0]) if row_count else 0
    size = max(row_count, column_count)
    if size == 0:
        return []
    costs = [
        [-(weights[row][column] if row < row_count and column < column_count else 0.0)
         for column in range(size)]
        for row in range(size)
    ]
    row_potential = [0.0] * (size + 1)
    column_potential = [0.0] * (size + 1)
    matched_row = [0] * (size + 1)
    predecessor = [0] * (size + 1)
    for row in range(1, size + 1):
        matched_row[0] = row
        column = 0
        minimum = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[column] = True
            active_row = matched_row[column]
            delta = float("inf")
            next_column = 0
            for candidate in range(1, size + 1):
                if used[candidate]:
                    continue
                reduced = (
                    costs[active_row - 1][candidate - 1]
                    - row_potential[active_row]
                    - column_potential[candidate]
                )
                if reduced < minimum[candidate]:
                    minimum[candidate] = reduced
                    predecessor[candidate] = column
                if minimum[candidate] < delta:
                    delta = minimum[candidate]
                    next_column = candidate
            for candidate in range(size + 1):
                if used[candidate]:
                    row_potential[matched_row[candidate]] += delta
                    column_potential[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            previous = predecessor[column]
            matched_row[column] = matched_row[previous]
            column = previous
            if column == 0:
                break
    assignment = [(matched_row[column] - 1, column - 1) for column in range(1, size + 1)]
    return [
        (row, column)
        for row, column in assignment
        if row < row_count and column < column_count and weights[row][column] > 0
    ]


def _optimal_matches(
    truths: Sequence[ExtractionTruth],
    predictions: Sequence[ExtractedBehavior],
    *,
    minimum_iou: float,
) -> list[tuple[int, int]]:
    cardinality_weight = max(len(truths), len(predictions)) + 1
    weights = [
        [
            cardinality_weight + _span_iou(truth, prediction)
            if not _identity_mismatches(
                truth, prediction, minimum_iou=minimum_iou
            )
            else 0.0
            for prediction in predictions
        ]
        for truth in truths
    ]
    return _maximum_weight_assignment(weights)


def _identity_label(
    actor_id: str,
    target_ids: Sequence[str],
    canonical_action: str,
    semantic_groups: Sequence[str],
) -> str:
    targets = ",".join(sorted(target_ids)) or "-"
    groups = ",".join(sorted(semantic_groups))
    return f"actor={actor_id}|targets={targets}|action={canonical_action}|groups={groups}"


def _truth_label(truth: ExtractionTruth) -> str:
    return _identity_label(
        truth.actor_id,
        truth.target_ids,
        truth.canonical_action,
        (truth.semantic_group,),
    )


def _prediction_label(
    prediction: ExtractedBehavior, *, compared_semantic_group: str | None = None
) -> str:
    groups = (
        (compared_semantic_group,)
        if compared_semantic_group in prediction.semantic_groups
        else tuple(prediction.semantic_groups)
    )
    return _identity_label(
        prediction.actor_id,
        prediction.target_ids,
        prediction.canonical_action,
        groups,
    )


def _diagnostic_matches(
    truths: Sequence[ExtractionTruth],
    predictions: Sequence[ExtractedBehavior],
) -> list[tuple[int, int]]:
    size = max(len(truths), len(predictions))
    cardinality_weight = size * 5 + 1
    weights = [
        [
            cardinality_weight
            + _span_iou(truth, prediction)
            + 4
            - len(
                _identity_mismatches(
                    truth, prediction, minimum_iou=0.0
                )
            )
            if _span_iou(truth, prediction) > 0
            else 0.0
            for prediction in predictions
        ]
        for truth in truths
    ]
    return _maximum_weight_assignment(weights)


def _record_confusion(
    matrix: dict[str, dict[str, int]], truth_label: str, prediction_label: str
) -> None:
    row = matrix.setdefault(truth_label, {})
    row[prediction_label] = row.get(prediction_label, 0) + 1


def _confidence_calibration(
    observations: Sequence[tuple[float, bool]], *, bin_count: int
) -> ConfidenceCalibration:
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bin_count)]
    for confidence, correct in observations:
        buckets[min(int(confidence * bin_count), bin_count - 1)].append(
            (confidence, correct)
        )
    points: list[ConfidenceCalibrationBin] = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        mean_confidence = fmean(confidence for confidence, _ in bucket)
        empirical_accuracy = fmean(int(correct) for _, correct in bucket)
        points.append(
            ConfidenceCalibrationBin(
                lower_bound=index / bin_count,
                upper_bound=(index + 1) / bin_count,
                count=len(bucket),
                mean_confidence=mean_confidence,
                empirical_accuracy=empirical_accuracy,
                absolute_gap=abs(mean_confidence - empirical_accuracy),
            )
        )
    total = len(observations)
    return ConfidenceCalibration(
        bins=tuple(points),
        expected_calibration_error=(
            sum(point.count * point.absolute_gap for point in points) / total
            if total
            else 0.0
        ),
        brier_score=(
            fmean((confidence - int(correct)) ** 2 for confidence, correct in observations)
            if observations
            else 0.0
        ),
    )


def _metrics(true_positives: int, prediction_count: int, truth_count: int) -> ExtractionMetrics:
    precision = true_positives / prediction_count if prediction_count else 0.0
    recall = true_positives / truth_count if truth_count else 0.0
    return ExtractionMetrics(
        precision=precision,
        recall=recall,
        f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    )


def benchmark_extractor(
    extractor: ExtractionAdapter,
    cases: Sequence[ExtractionBenchmarkCase],
    *,
    minimum_iou: float = 0.5,
    calibration_bins: int = 10,
) -> ExtractionBenchmarkResult:
    if not cases:
        raise ValueError("at least one extraction benchmark case is required")
    if not 0 < minimum_iou <= 1:
        raise ValueError("minimum_iou must be in (0, 1]")
    if calibration_bins < 1:
        raise ValueError("calibration_bins must be at least 1")
    truth_count = prediction_count = true_positives = exact_spans = 0
    matched_ious: list[float] = []
    case_metrics: list[ExtractionMetrics] = []
    error_counts = {
        "actor_mismatch": 0,
        "target_mismatch": 0,
        "action_mismatch": 0,
        "semantic_group_mismatch": 0,
        "span_mismatch": 0,
        "missed_truth": 0,
        "spurious_prediction": 0,
    }
    error_type_confusion = {
        dimension: {"correct": 0, "incorrect": 0}
        for dimension in ("actor", "target", "action", "semantic_group", "span")
    }
    confusion: dict[str, dict[str, int]] = {}
    calibration_observations: list[tuple[float, bool]] = []
    for case in cases:
        result = extractor.extract(case.request)
        case.request.validate_result(result)
        predictions = list(result.behaviors)
        prediction_count += len(predictions)
        truth_count += len(case.truths)
        matches = _optimal_matches(case.truths, predictions, minimum_iou=minimum_iou)
        matched_truths = {truth_index for truth_index, _ in matches}
        matched_predictions = {prediction_index for _, prediction_index in matches}
        true_positives += len(matches)
        case_metrics.append(_metrics(len(matches), len(predictions), len(case.truths)))
        for truth_index, prediction_index in matches:
            truth = case.truths[truth_index]
            prediction = predictions[prediction_index]
            exact_spans += int(
                prediction.text_span.start == truth.start
                and prediction.text_span.end == truth.end
            )
            matched_ious.append(_span_iou(truth, prediction))
            _record_confusion(
                confusion,
                _truth_label(truth),
                _prediction_label(
                    prediction, compared_semantic_group=truth.semantic_group
                ),
            )
            for row in error_type_confusion.values():
                row["correct"] += 1

        remaining_truth_indices = [
            index for index in range(len(case.truths)) if index not in matched_truths
        ]
        remaining_prediction_indices = [
            index for index in range(len(predictions)) if index not in matched_predictions
        ]
        remaining_truths = [case.truths[index] for index in remaining_truth_indices]
        remaining_predictions = [predictions[index] for index in remaining_prediction_indices]
        diagnostic_matches = _diagnostic_matches(remaining_truths, remaining_predictions)
        diagnosed_truths = {truth_index for truth_index, _ in diagnostic_matches}
        diagnosed_predictions = {
            prediction_index for _, prediction_index in diagnostic_matches
        }
        for truth_index, prediction_index in diagnostic_matches:
            truth = remaining_truths[truth_index]
            prediction = remaining_predictions[prediction_index]
            _record_confusion(
                confusion,
                _truth_label(truth),
                _prediction_label(
                    prediction, compared_semantic_group=truth.semantic_group
                ),
            )
            mismatches = _identity_mismatches(
                truth, prediction, minimum_iou=minimum_iou
            )
            for dimension, row in error_type_confusion.items():
                outcome = "incorrect" if dimension in mismatches else "correct"
                row[outcome] += 1
            for mismatch in mismatches:
                error_counts[f"{mismatch}_mismatch"] += 1
        for index, truth in enumerate(remaining_truths):
            if index in diagnosed_truths:
                continue
            error_counts["missed_truth"] += 1
            _record_confusion(confusion, _truth_label(truth), "__missing__")
        for index, prediction in enumerate(remaining_predictions):
            if index in diagnosed_predictions:
                continue
            error_counts["spurious_prediction"] += 1
            _record_confusion(confusion, "__spurious__", _prediction_label(prediction))
        calibration_observations.extend(
            (prediction.confidence, index in matched_predictions)
            for index, prediction in enumerate(predictions)
        )
    false_positives = prediction_count - true_positives
    false_negatives = truth_count - true_positives
    error_type_confusion["detection"] = {
        "true_positive": true_positives,
        "false_positive": false_positives,
        "false_negative": false_negatives,
    }
    micro = _metrics(true_positives, prediction_count, truth_count)
    macro = ExtractionMetrics(
        precision=fmean(item.precision for item in case_metrics),
        recall=fmean(item.recall for item in case_metrics),
        f1=fmean(item.f1 for item in case_metrics),
    )
    return ExtractionBenchmarkResult(
        case_count=len(cases),
        truth_count=truth_count,
        prediction_count=prediction_count,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=micro.precision,
        recall=micro.recall,
        span_accuracy=exact_spans / true_positives if true_positives else 0.0,
        mean_span_iou=fmean(matched_ious) if matched_ious else 0.0,
        micro=micro,
        macro=macro,
        error_counts=error_counts,
        error_type_confusion_matrix=error_type_confusion,
        identity_confusion_matrix=confusion,
        calibration=_confidence_calibration(
            calibration_observations, bin_count=calibration_bins
        ),
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
    prose_gate_scope: Literal["legacy_aggregate", "chapter_p95"] = "legacy_aggregate"
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
        self.uses_calibrated_policy = gate_policy is not None
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
        if self.uses_calibrated_policy and automatic.prose_gate_scope != "chapter_p95":
            raise ValueError(
                "calibrated threshold policies require prose_gate_scope=chapter_p95"
            )
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
    "ConfidenceCalibration", "ConfidenceCalibrationBin", "ExtractionMetrics",
    "CharacterBlindItem", "CharacterBlindKey", "CharacterBlindPacket", "CharacterBlindRating",
    "CharacterBlindSample", "ExtractionBenchmarkCase", "ExtractionBenchmarkResult", "ExtractionTruth",
    "HumanBlindSummary", "aggregate_character_blind_ratings", "benchmark_extractor",
    "build_character_blind_packet", "percentile", "render_acceptance_markdown",
]
