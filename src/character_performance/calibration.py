"""Corpus-backed calibration for prose repetition acceptance gates.

The calibrator deliberately separates descriptive evidence from activation.
A respected novel can establish the accepted-prose distribution, but a policy
is only ``ready`` when human-labelled formulaic prose, paired system outputs,
and human naturalness ratings across a strength sweep are also present.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from statistics import fmean, pstdev
from typing import Literal

from pydantic import Field, model_validator
import yaml

from .domain.behavior_models import (
    BehaviorFingerprint,
    BehaviorOccurrence,
    ExtractionRequest,
    NarrativePosition,
)
from .domain.models import CharacterProfile, DomainModel
from .extraction import RuleBasedBehaviorExtractor
from .reporting import calculate_memory_gate_values


MetricName = Literal["repeat_rate", "cliche_share", "channel_concentration"]
Role = Literal[
    "quality",
    "formulaic",
    "synthetic_formulaic",
    "system_off",
    "system_on",
    "sweep",
]
_METRICS: tuple[MetricName, ...] = (
    "repeat_rate",
    "cliche_share",
    "channel_concentration",
)
_GATE_BY_METRIC = {
    "repeat_rate": "IMMEDIATE_EXACT_REPEAT_RATE",
    "cliche_share": "CLICHE_GROUP_SHARE",
    "channel_concentration": "MAX_CHARACTER_CHANNEL_SHARE",
}
_CHAPTER_RE = re.compile(
    r"(?m)^[\t \u3000]*(第[0-9０-９一二三四五六七八九十百千万两〇零]+章[^\r\n]*)[\t \u3000]*\r?$"
)


class ReadinessRequirements(DomainModel):
    minimum_quality_chapters: int = Field(default=30, ge=1)
    minimum_formulaic_chapters: int = Field(default=30, ge=1)
    minimum_pairs: int = Field(default=10, ge=1)
    minimum_sweep_strengths: int = Field(default=3, ge=3)
    minimum_ratings_per_strength: int = Field(default=2, ge=1)
    minimum_actor_attribution_coverage: float = Field(default=0.80, ge=0, le=1)


class SyntheticFormulaicConfig(DomainModel):
    """Detector sensitivity control; never counts as human-labelled evidence."""

    enabled: bool = True
    stock_repetitions_per_chapter: int = Field(default=8, ge=1, le=100)


class CalibrationCharacter(DomainModel):
    id: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    signature_groups: frozenset[str] = frozenset()


class CalibrationSample(DomainModel):
    id: str = Field(min_length=1)
    role: Role
    path: str = Field(min_length=1)
    human_accepted: bool = False
    pair_id: str | None = None
    sweep_id: str | None = None
    control_fingerprint: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    strength: float | None = Field(default=None, ge=0, le=1)
    naturalness_ratings: tuple[float, ...] = ()
    characters: tuple[CalibrationCharacter, ...] = ()
    actor_attribution_reviewed: bool = False
    single_actor_text: bool = False

    @model_validator(mode="after")
    def role_fields_are_coherent(self) -> "CalibrationSample":
        if self.role in {"quality", "formulaic"} and not self.human_accepted:
            raise ValueError("quality and formulaic samples must be human_accepted")
        if self.role in {"system_off", "system_on"} and (
            not self.pair_id or not self.control_fingerprint
        ):
            raise ValueError(
                "system_on/system_off samples require pair_id and control_fingerprint"
            )
        if self.role == "sweep":
            if self.strength is None or not self.sweep_id or not self.control_fingerprint:
                raise ValueError(
                    "sweep samples require sweep_id, control_fingerprint and strength"
                )
            if any(value < 1 or value > 5 for value in self.naturalness_ratings):
                raise ValueError("naturalness ratings must be between 1 and 5")
        elif self.strength is not None or self.naturalness_ratings:
            raise ValueError("strength and naturalness_ratings are only valid for sweep samples")
        character_ids = [character.id for character in self.characters]
        if len(character_ids) != len(set(character_ids)):
            raise ValueError("sample characters must have unique ids")
        return self


class CalibrationManifest(DomainModel):
    version: Literal[1] = 1
    minimum_occurrences_per_chapter: int = Field(default=3, ge=1)
    readiness: ReadinessRequirements = ReadinessRequirements()
    synthetic_formulaic: SyntheticFormulaicConfig | None = None
    samples: tuple[CalibrationSample, ...]

    @model_validator(mode="after")
    def samples_are_unique(self) -> "CalibrationManifest":
        ids = [sample.id for sample in self.samples]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("calibration samples must have unique non-empty ids")
        pairs: dict[str, set[str]] = defaultdict(set)
        sweeps: dict[str, set[str]] = defaultdict(set)
        for sample in self.samples:
            if sample.pair_id and sample.control_fingerprint:
                pairs[sample.pair_id].add(sample.control_fingerprint)
            if sample.sweep_id and sample.control_fingerprint:
                sweeps[sample.sweep_id].add(sample.control_fingerprint)
        if any(len(values) > 1 for values in pairs.values()):
            raise ValueError("paired system samples must share one control_fingerprint")
        if any(len(values) > 1 for values in sweeps.values()):
            raise ValueError("each strength sweep must share one control_fingerprint")
        return self


class ChapterMetrics(DomainModel):
    sample_id: str
    chapter_id: str
    chapter_title: str
    character_count: int = Field(ge=0)
    occurrence_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    repeat_rate: float = Field(ge=0, le=1)
    cliche_share: float = Field(ge=0, le=1)
    channel_concentration: float = Field(ge=0, le=1)


class MetricDistribution(DomainModel):
    count: int = Field(ge=0)
    minimum: float = 0
    p25: float = 0
    median: float = 0
    p75: float = 0
    p90: float = 0
    p95: float = 0
    maximum: float = 0
    mean: float = 0
    standard_deviation: float = 0


class CorpusDistribution(DomainModel):
    chapter_count: int = Field(ge=0)
    excluded_chapter_count: int = Field(ge=0)
    sample_ids: tuple[str, ...]
    repeat_rate: MetricDistribution
    cliche_share: MetricDistribution
    channel_concentration: MetricDistribution


class ThresholdRecommendation(DomainModel):
    threshold: float = Field(ge=0, le=1)
    method: Literal["separation", "quality_p95"]
    quality_false_positive_rate: float = Field(ge=0, le=1)
    formulaic_true_positive_rate: float | None = Field(default=None, ge=0, le=1)


class PairedComparison(DomainModel):
    pair_id: str
    repeat_rate_off: float
    repeat_rate_on: float
    repeat_rate_delta: float
    cliche_share_off: float
    cliche_share_on: float
    cliche_share_delta: float
    channel_concentration_off: float
    channel_concentration_on: float
    channel_concentration_delta: float


class TradeoffPoint(DomainModel):
    strength: float = Field(ge=0, le=1)
    sample_count: int = Field(ge=1)
    rating_count: int = Field(ge=0)
    naturalness: float | None = Field(default=None, ge=1, le=5)
    repeat_rate: float = Field(ge=0, le=1)
    cliche_share: float = Field(ge=0, le=1)
    channel_concentration: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=1)
    utility_score: float | None = None
    pareto_optimal: bool = False


class CalibrationSource(DomainModel):
    sample_id: str
    role: Role
    path: str
    sha256: str
    human_accepted: bool
    chapter_count: int
    declared_character_count: int = Field(ge=0)
    actor_attribution_reviewed: bool
    actor_attribution_coverage: float = Field(ge=0, le=1)


class CalibrationReport(DomainModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["provisional", "ready"]
    sources: tuple[CalibrationSource, ...]
    chapter_metrics: tuple[ChapterMetrics, ...]
    distributions: dict[str, CorpusDistribution]
    recommended_thresholds: dict[str, ThresholdRecommendation]
    paired_comparisons: tuple[PairedComparison, ...]
    tradeoff_curve: tuple[TradeoffPoint, ...]
    recommended_strength: float | None = None
    missing_evidence: tuple[str, ...] = ()

    def policy_payload(self) -> dict[str, object]:
        digest = sha256(self.canonical_bytes()).hexdigest()
        return {
            "schema_version": "1.0.0",
            "status": self.status,
            "source_report_sha256": f"sha256:{digest}",
            "gates": {
                code: {"threshold": item.threshold, "comparator": "<="}
                for code, item in sorted(self.recommended_thresholds.items())
            },
        }

    def policy_json(self) -> str:
        return json.dumps(self.policy_payload(), ensure_ascii=False, indent=2) + "\n"

    def canonical_json(self) -> str:
        return self.model_dump_json(indent=2) + "\n"

    def canonical_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _distribution(values: list[float]) -> MetricDistribution:
    if not values:
        return MetricDistribution(count=0)
    return MetricDistribution(
        count=len(values),
        minimum=min(values),
        p25=_quantile(values, 0.25),
        median=_quantile(values, 0.5),
        p75=_quantile(values, 0.75),
        p90=_quantile(values, 0.9),
        p95=_quantile(values, 0.95),
        maximum=max(values),
        mean=fmean(values),
        standard_deviation=pstdev(values),
    )


def _split_chapters(text: str) -> list[tuple[str, str]]:
    matches = list(_CHAPTER_RE.finditer(text))
    if not matches:
        return [("全文", text.strip())] if text.strip() else []
    chapters: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Some scraped books repeat the chapter header on the following line.
        if not body and index + 1 < len(matches) and matches[index + 1].group(1).strip() == title:
            continue
        if chapters and chapters[-1][0] == title and not chapters[-1][1]:
            chapters[-1] = (title, body)
        else:
            chapters.append((title, body))
    return [(title, body) for title, body in chapters if body]


def _analyze_chapters(
    sample: CalibrationSample, chapters: list[tuple[str, str]]
) -> list[ChapterMetrics]:
    extractor = RuleBasedBehaviorExtractor()
    rows: list[ChapterMetrics] = []
    character_specs = sample.characters or (
        CalibrationCharacter(id="char.calibration_subject"),
    )
    characters = tuple(CharacterProfile(id=item.id) for item in character_specs)
    aliases = {
        alias: item.id
        for item in character_specs
        for alias in item.aliases
    }
    signatures = {
        item.id: item.signature_groups
        for item in character_specs
        if item.signature_groups
    }
    for index, (title, body) in enumerate(chapters, start=1):
        request = ExtractionRequest(
            run_id=f"calibration.{sample.id}.{index}",
            text=body,
            known_characters=characters,
            position=NarrativePosition(
                book_id=f"book.{sample.id}",
                chapter_id=f"chapter.{index}",
                scene_id=f"scene.{index}",
                paragraph_index=0,
                beat_index=0,
                global_beat_index=index,
            ),
            pack_summary={"character_aliases": aliases},
        )
        result = extractor.extract(request)
        behaviors = result.behaviors
        total = len(behaviors)
        occurrences = tuple(
            BehaviorOccurrence(
                occurrence_id=f"calibration.{sample.id}.{index}.{behavior_index}",
                book_id=request.position.book_id,
                position=request.position.model_copy(
                    update={"beat_index": behavior_index, "global_beat_index": behavior_index}
                ),
                actor_id=behavior.actor_id,
                target_ids=behavior.target_ids,
                fingerprint=BehaviorFingerprint(
                    unit_id=behavior.matched_unit_id,
                    semantic_groups=behavior.semantic_groups,
                    channel=behavior.channel,
                    narrative_functions=behavior.narrative_functions,
                    strategy_id=behavior.strategy_id,
                    actor_id=behavior.actor_id,
                    target_ids=behavior.target_ids,
                    syntax_features=behavior.syntax_features,
                    lexical_lemmas=behavior.lexical_lemmas,
                ),
                source="extracted",
                text_span=behavior.text_span,
                confidence=behavior.confidence,
                generation_run_id=request.run_id,
                accepted_revision=1,
            )
            for behavior_index, behavior in enumerate(behaviors)
        )
        gate_values = calculate_memory_gate_values(
            occurrences, signature_groups_by_actor=signatures
        )
        rows.append(
            ChapterMetrics(
                sample_id=sample.id,
                chapter_id=f"chapter.{index}",
                chapter_title=title,
                character_count=len(body),
                occurrence_count=total,
                unresolved_count=len(result.unresolved_spans),
                repeat_rate=gate_values["IMMEDIATE_EXACT_REPEAT_RATE"][0],
                cliche_share=gate_values["CLICHE_GROUP_SHARE"][0],
                channel_concentration=gate_values["MAX_CHARACTER_CHANNEL_SHARE"][0],
            )
        )
    return rows


def _analyze_sample(sample: CalibrationSample, path: Path) -> tuple[list[ChapterMetrics], CalibrationSource]:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    chapters = _split_chapters(text)
    rows = _analyze_chapters(sample, chapters)
    resolved = sum(row.occurrence_count for row in rows)
    unresolved = sum(row.unresolved_count for row in rows)
    source = CalibrationSource(
        sample_id=sample.id,
        role=sample.role,
        path=sample.path,
        sha256=f"sha256:{sha256(raw).hexdigest()}",
        human_accepted=sample.human_accepted,
        chapter_count=len(rows),
        declared_character_count=len(sample.characters),
        actor_attribution_reviewed=sample.actor_attribution_reviewed,
        actor_attribution_coverage=resolved / max(1, resolved + unresolved),
    )
    return rows, source


def _synthetic_formulaic_sample(
    source_sample: CalibrationSample,
    source_path: Path,
    config: SyntheticFormulaicConfig,
) -> tuple[CalibrationSample, list[ChapterMetrics], CalibrationSource]:
    raw = source_path.read_bytes()
    chapters = _split_chapters(raw.decode("utf-8-sig"))
    stock = "".join(
        "他皱眉。他皱眉。他深吸一口气。他嘴角一扯。"
        for _ in range(config.stock_repetitions_per_chapter)
    )
    derived = CalibrationSample(
        id=f"synthetic.formulaic.{source_sample.id}",
        role="synthetic_formulaic",
        path=f"derived://{source_sample.id}",
        human_accepted=False,
        characters=source_sample.characters,
        actor_attribution_reviewed=source_sample.actor_attribution_reviewed,
        single_actor_text=source_sample.single_actor_text,
    )
    rows = _analyze_chapters(
        derived,
        [(title, f"{body}\n{stock}") for title, body in chapters],
    )
    digest_material = raw + f"\0stock={config.stock_repetitions_per_chapter}".encode()
    source = CalibrationSource(
        sample_id=derived.id,
        role="formulaic",
        path=derived.path,
        sha256=f"sha256:{sha256(digest_material).hexdigest()}",
        human_accepted=False,
        chapter_count=len(rows),
        declared_character_count=len(derived.characters),
        actor_attribution_reviewed=derived.actor_attribution_reviewed,
        actor_attribution_coverage=(
            sum(row.occurrence_count for row in rows)
            / max(
                1,
                sum(row.occurrence_count + row.unresolved_count for row in rows),
            )
        ),
    )
    return derived, rows, source


def _corpus_distribution(rows: list[ChapterMetrics], excluded: int) -> CorpusDistribution:
    return CorpusDistribution(
        chapter_count=len(rows),
        excluded_chapter_count=excluded,
        sample_ids=tuple(sorted({row.sample_id for row in rows})),
        repeat_rate=_distribution([row.repeat_rate for row in rows]),
        cliche_share=_distribution([row.cliche_share for row in rows]),
        channel_concentration=_distribution([row.channel_concentration for row in rows]),
    )


def _recommend(quality: list[float], formulaic: list[float]) -> ThresholdRecommendation:
    if not quality:
        return ThresholdRecommendation(
            threshold=0.0,
            method="quality_p95",
            quality_false_positive_rate=0.0,
        )
    if not formulaic:
        threshold = min(1.0, _quantile(quality, 0.95))
        false_positive = sum(value > threshold for value in quality) / len(quality)
        return ThresholdRecommendation(
            threshold=threshold,
            method="quality_p95",
            quality_false_positive_rate=false_positive,
        )
    values = sorted(set([0.0, 1.0, *quality, *formulaic]))
    candidates = sorted(set(values + [(a + b) / 2 for a, b in zip(values, values[1:])]))
    scored: list[tuple[float, float, float, float]] = []
    for threshold in candidates:
        false_positive = sum(value > threshold for value in quality) / len(quality)
        true_positive = sum(value > threshold for value in formulaic) / len(formulaic)
        balanced = ((1 - false_positive) + true_positive) / 2
        scored.append((balanced, -false_positive, true_positive, threshold))
    _, negative_fp, true_positive, threshold = max(scored)
    return ThresholdRecommendation(
        threshold=threshold,
        method="separation",
        quality_false_positive_rate=-negative_fp,
        formulaic_true_positive_rate=true_positive,
    )


def _mean_metrics(rows: list[ChapterMetrics]) -> dict[MetricName, float]:
    return {
        metric: fmean(getattr(row, metric) for row in rows) if rows else 0.0
        for metric in _METRICS
    }


def _paired(samples: tuple[CalibrationSample, ...], rows_by_sample: dict[str, list[ChapterMetrics]]) -> tuple[PairedComparison, ...]:
    grouped: dict[str, dict[str, CalibrationSample]] = defaultdict(dict)
    for sample in samples:
        if sample.pair_id:
            grouped[sample.pair_id][sample.role] = sample
    result: list[PairedComparison] = []
    for pair_id, roles in sorted(grouped.items()):
        if set(roles) != {"system_off", "system_on"}:
            continue
        if not rows_by_sample[roles["system_off"].id] or not rows_by_sample[roles["system_on"].id]:
            continue
        off = _mean_metrics(rows_by_sample[roles["system_off"].id])
        on = _mean_metrics(rows_by_sample[roles["system_on"].id])
        result.append(
            PairedComparison(
                pair_id=pair_id,
                repeat_rate_off=off["repeat_rate"],
                repeat_rate_on=on["repeat_rate"],
                repeat_rate_delta=off["repeat_rate"] - on["repeat_rate"],
                cliche_share_off=off["cliche_share"],
                cliche_share_on=on["cliche_share"],
                cliche_share_delta=off["cliche_share"] - on["cliche_share"],
                channel_concentration_off=off["channel_concentration"],
                channel_concentration_on=on["channel_concentration"],
                channel_concentration_delta=off["channel_concentration"] - on["channel_concentration"],
            )
        )
    return tuple(result)


def _tradeoff(samples: tuple[CalibrationSample, ...], rows_by_sample: dict[str, list[ChapterMetrics]]) -> tuple[tuple[TradeoffPoint, ...], float | None]:
    grouped: dict[float, list[CalibrationSample]] = defaultdict(list)
    for sample in samples:
        if sample.role == "sweep" and sample.strength is not None:
            grouped[sample.strength].append(sample)
    draft: list[TradeoffPoint] = []
    for strength, group in sorted(grouped.items()):
        rows = [row for sample in group for row in rows_by_sample[sample.id]]
        if not rows:
            continue
        metrics = _mean_metrics(rows)
        ratings = [rating for sample in group for rating in sample.naturalness_ratings]
        naturalness = fmean(ratings) if ratings else None
        risk = fmean(metrics.values())
        utility = None if naturalness is None else (naturalness / 5.0) - 0.35 * risk
        draft.append(
            TradeoffPoint(
                strength=strength,
                sample_count=len(group),
                rating_count=len(ratings),
                naturalness=naturalness,
                repeat_rate=metrics["repeat_rate"],
                cliche_share=metrics["cliche_share"],
                channel_concentration=metrics["channel_concentration"],
                risk_score=risk,
                utility_score=utility,
            )
        )
    points: list[TradeoffPoint] = []
    for point in draft:
        dominated = any(
            other.strength != point.strength
            and other.risk_score <= point.risk_score
            and (other.naturalness or 0) >= (point.naturalness or 0)
            and (other.risk_score < point.risk_score or (other.naturalness or 0) > (point.naturalness or 0))
            for other in draft
        )
        points.append(point.model_copy(update={"pareto_optimal": not dominated}))
    rated = [point for point in points if point.utility_score is not None]
    recommended = max(rated, key=lambda point: (point.utility_score, -point.strength)).strength if rated else None
    return tuple(points), recommended


def calibrate_manifest(path: Path) -> CalibrationReport:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest = CalibrationManifest.model_validate(payload)
    base = path.parent
    rows_by_sample: dict[str, list[ChapterMetrics]] = {}
    all_samples = list(manifest.samples)
    sources: list[CalibrationSource] = []
    all_rows: list[ChapterMetrics] = []
    for sample in manifest.samples:
        sample_path = (base / sample.path).resolve()
        if not sample_path.is_file():
            raise ValueError(f"calibration sample does not exist: {sample.path}")
        rows, source = _analyze_sample(sample, sample_path)
        rows_by_sample[sample.id] = rows
        sources.append(source)
        all_rows.extend(rows)
    if manifest.synthetic_formulaic is not None and manifest.synthetic_formulaic.enabled:
        for sample in manifest.samples:
            if sample.role != "quality":
                continue
            derived, rows, source = _synthetic_formulaic_sample(
                sample, (base / sample.path).resolve(), manifest.synthetic_formulaic
            )
            all_samples.append(derived)
            rows_by_sample[derived.id] = rows
            sources.append(source)
            all_rows.extend(rows)

    by_role: dict[str, list[ChapterMetrics]] = defaultdict(list)
    excluded_by_role: Counter[str] = Counter()
    for sample in all_samples:
        for row in rows_by_sample[sample.id]:
            if row.occurrence_count >= manifest.minimum_occurrences_per_chapter:
                by_role[sample.role].append(row)
            else:
                excluded_by_role[sample.role] += 1
    distributions = {
        role: _corpus_distribution(rows, excluded_by_role[role])
        for role, rows in sorted(by_role.items())
    }
    qualified_by_sample: dict[str, list[ChapterMetrics]] = {
        sample.id: [
            row for row in rows_by_sample[sample.id]
            if row.occurrence_count >= manifest.minimum_occurrences_per_chapter
        ]
        for sample in manifest.samples
    }
    quality = by_role.get("quality", [])
    human_formulaic_ids = {
        sample.id for sample in all_samples
        if sample.role == "formulaic" and sample.human_accepted
    }
    formulaic = [row for row in by_role.get("formulaic", []) if row.sample_id in human_formulaic_ids]
    recommendations = {
        _GATE_BY_METRIC[metric]: _recommend(
            [getattr(row, metric) for row in quality],
            [getattr(row, metric) for row in formulaic],
        )
        for metric in _METRICS
    }
    paired = _paired(manifest.samples, qualified_by_sample)
    curve, strength = _tradeoff(manifest.samples, qualified_by_sample)
    req = manifest.readiness
    missing: list[str] = []
    human_quality_ids = {
        sample.id for sample in all_samples
        if sample.role == "quality" and sample.human_accepted
    }
    quality_count = sum(row.sample_id in human_quality_ids for row in quality)
    if quality_count < req.minimum_quality_chapters:
        missing.append("quality_distribution")
    if len(formulaic) < req.minimum_formulaic_chapters:
        missing.append("formulaic_distribution")
    if len(paired) < req.minimum_pairs:
        missing.append("system_on_off_pairs")
    source_by_id = {source.sample_id: source for source in sources}
    if any(
        not sample.characters
        or not sample.actor_attribution_reviewed
        or any(not character.aliases for character in sample.characters)
        or (len(sample.characters) == 1 and not sample.single_actor_text)
        or source_by_id[sample.id].actor_attribution_coverage
        < req.minimum_actor_attribution_coverage
        for sample in manifest.samples
    ):
        missing.append("actor_attribution")
    sweep_strengths: dict[str, set[float]] = defaultdict(set)
    for sample in manifest.samples:
        if (
            sample.role == "sweep"
            and sample.sweep_id is not None
            and sample.strength is not None
            and qualified_by_sample[sample.id]
            and len(sample.naturalness_ratings) >= req.minimum_ratings_per_strength
        ):
            sweep_strengths[sample.sweep_id].add(sample.strength)
    if not any(
        len(strengths) >= req.minimum_sweep_strengths
        for strengths in sweep_strengths.values()
    ):
        missing.append("naturalness_tradeoff_curve")
    return CalibrationReport(
        status="ready" if not missing else "provisional",
        sources=tuple(sources),
        chapter_metrics=tuple(all_rows),
        distributions=distributions,
        recommended_thresholds=recommendations,
        paired_comparisons=paired,
        tradeoff_curve=curve,
        recommended_strength=strength,
        missing_evidence=tuple(missing),
    )


def render_calibration_markdown(report: CalibrationReport) -> str:
    lines = [
        "# 阈值校准报告",
        "",
        f"- 状态：{report.status}",
        f"- 来源文件：{len(report.sources)}",
        f"- 缺失证据：{'、'.join(report.missing_evidence) or '无'}",
        "- 合成公式化样本：仅用于检测器敏感性检查，不计入真人标注负样本或 ready 判定。",
        "- provisional 策略：只能审阅，验收与行为报告拒绝加载。",
        "",
        "## 优质正文分布",
        "",
    ]
    quality = report.distributions.get("quality")
    if quality is None:
        lines.append("暂无合格样本。")
    else:
        lines.extend(_distribution_lines(quality))
    lines.extend(["", "## 公式化正文分布", ""])
    formulaic = report.distributions.get("formulaic")
    lines.extend(_distribution_lines(formulaic) if formulaic else ["暂无合格样本。"]) 
    lines.extend(["", "## 合成公式化敏感性诊断", ""])
    synthetic = report.distributions.get("synthetic_formulaic")
    lines.extend(_distribution_lines(synthetic) if synthetic else ["未启用合成诊断。"])
    lines.extend(["", "## 系统开启/关闭配对对照", ""])
    if report.paired_comparisons:
        lines.append("| 配对 | 重复率改善 | 俗套占比改善 | 通道集中度改善 |")
        lines.append("|---|---:|---:|---:|")
        lines.extend(
            f"| {row.pair_id} | {row.repeat_rate_delta:.4f} | {row.cliche_share_delta:.4f} | {row.channel_concentration_delta:.4f} |"
            for row in report.paired_comparisons
        )
    else:
        lines.append("暂无完整配对。")
    lines.extend(["", "## 排重强度与自然度权衡曲线", ""])
    if report.tradeoff_curve:
        lines.append("| 强度 | 重复率 | 俗套占比 | 通道集中度 | 自然度 | Pareto |")
        lines.append("|---:|---:|---:|---:|---:|---|")
        lines.extend(
            f"| {point.strength:.2f} | {point.repeat_rate:.4f} | {point.cliche_share:.4f} | {point.channel_concentration:.4f} | {point.naturalness if point.naturalness is not None else '无'} | {'是' if point.pareto_optimal else '否'} |"
            for point in report.tradeoff_curve
        )
        lines.append(f"\n建议强度：{report.recommended_strength if report.recommended_strength is not None else '无'}")
    else:
        lines.append("暂无带真人自然度评分的强度扫描。")
    lines.extend(["", "## 建议阈值", "", "| 门禁 | 阈值 | 方法 | 优质误杀率 | 公式化召回率 |", "|---|---:|---|---:|---:|"])
    for code, item in sorted(report.recommended_thresholds.items()):
        recall = "无" if item.formulaic_true_positive_rate is None else f"{item.formulaic_true_positive_rate:.2%}"
        lines.append(f"| {code} | {item.threshold:.4f} | {item.method} | {item.quality_false_positive_rate:.2%} | {recall} |")
    return "\n".join(lines) + "\n"


def _distribution_lines(distribution: CorpusDistribution) -> list[str]:
    return [
        f"- 纳入章节：{distribution.chapter_count}；排除章节：{distribution.excluded_chapter_count}",
        "",
        "| 指标 | 均值 | 中位数 | P90 | P95 | 最大值 |",
        "|---|---:|---:|---:|---:|---:|",
        f"| 重复率 | {distribution.repeat_rate.mean:.4f} | {distribution.repeat_rate.median:.4f} | {distribution.repeat_rate.p90:.4f} | {distribution.repeat_rate.p95:.4f} | {distribution.repeat_rate.maximum:.4f} |",
        f"| 俗套占比 | {distribution.cliche_share.mean:.4f} | {distribution.cliche_share.median:.4f} | {distribution.cliche_share.p90:.4f} | {distribution.cliche_share.p95:.4f} | {distribution.cliche_share.maximum:.4f} |",
        f"| 通道集中度 | {distribution.channel_concentration.mean:.4f} | {distribution.channel_concentration.median:.4f} | {distribution.channel_concentration.p90:.4f} | {distribution.channel_concentration.p95:.4f} | {distribution.channel_concentration.maximum:.4f} |",
    ]


__all__ = [
    "CalibrationManifest",
    "CalibrationReport",
    "CalibrationSample",
    "CalibrationCharacter",
    "ChapterMetrics",
    "SyntheticFormulaicConfig",
    "calibrate_manifest",
    "render_calibration_markdown",
]
