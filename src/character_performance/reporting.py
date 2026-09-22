"""Validated behavior analytics and dependency-free Markdown/HTML rendering."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from html import escape
from typing import Iterable, Literal

from pydantic import Field

from .domain.behavior_models import BehaviorOccurrence
from .domain.models import DomainModel
from .gate_policy import MEMORY_GATE_SPECS, gate_passes
from .memory.repository import BehaviorMemory


CLICHE_GROUPS = frozenset(
    {"brow_tension", "hand_tension", "deep_breath", "mouth_change", "gaze_flash"}
)


class DistributionRow(DomainModel):
    actor_id: str = Field(min_length=1)
    occurrence_count: int = Field(ge=0)
    channel_counts: dict[str, int]
    strategy_counts: dict[str, int]
    semantic_group_counts: dict[str, int]
    highest_non_signature_channel_share: float = Field(ge=0, le=1)


class HotspotRow(DomainModel):
    scope_id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    count: int = Field(ge=1)
    actor_ids: tuple[str, ...] = ()


class MetricGate(DomainModel):
    code: str = Field(min_length=1)
    value: float = Field(ge=0)
    threshold: float = Field(ge=0)
    comparator: Literal["<=", ">="]
    passed: bool
    sample_size: int = Field(ge=0)


class BehaviorReport(DomainModel):
    book_id: str = Field(min_length=1)
    occurrence_count: int = Field(ge=0)
    chapter_count: int = Field(ge=0)
    character_distributions: tuple[DistributionRow, ...]
    chapter_repeat_hotspots: tuple[HotspotRow, ...]
    syntax_hotspots: tuple[HotspotRow, ...]
    gates: tuple[MetricGate, ...]

    @property
    def automatic_gates_passed(self) -> bool:
        return all(gate.passed for gate in self.gates)


def _syntax_keys(item: BehaviorOccurrence) -> tuple[str, ...]:
    features = item.fingerprint.syntax_features
    keys: list[str] = []
    if features.subject_opening != "unknown":
        keys.append(f"subject_opening:{features.subject_opening}")
    if features.temporal_shape != "unknown":
        keys.append(f"temporal_shape:{features.temporal_shape}")
    if features.reset_pattern:
        keys.append("reset_pattern:true")
    if features.dialogue_position != "unknown":
        keys.append(f"dialogue_position:{features.dialogue_position}")
    return tuple(keys)


def build_behavior_report(
    book_id: str,
    occurrences: Iterable[BehaviorOccurrence],
    *,
    signature_groups_by_actor: dict[str, frozenset[str]] | None = None,
) -> BehaviorReport:
    rows = tuple(sorted(occurrences, key=lambda item: (item.position.global_beat_index, item.text_span.start, item.occurrence_id)))
    if any(item.book_id != book_id for item in rows):
        raise ValueError("all occurrences must belong to the requested book")

    by_actor: dict[str, list[BehaviorOccurrence]] = defaultdict(list)
    chapter_groups: Counter[tuple[str, str]] = Counter()
    syntax_counts: Counter[tuple[str, str]] = Counter()
    cliche_count = 0
    for item in rows:
        by_actor[item.actor_id].append(item)
        for group in item.fingerprint.semantic_groups:
            chapter_groups[(item.position.chapter_id, group)] += 1
        for key in _syntax_keys(item):
            syntax_counts[(item.position.chapter_id, key)] += 1
        if item.fingerprint.semantic_groups & CLICHE_GROUPS:
            cliche_count += 1

    distributions: list[DistributionRow] = []
    max_channel_share = 0.0
    signature_groups_by_actor = signature_groups_by_actor or {}
    for actor_id, actor_rows in sorted(by_actor.items()):
        channels = Counter(item.fingerprint.channel for item in actor_rows)
        strategies = Counter(item.fingerprint.strategy_id or "unclassified" for item in actor_rows)
        groups = Counter(group for item in actor_rows for group in item.fingerprint.semantic_groups)
        signature_groups = signature_groups_by_actor.get(actor_id, frozenset())
        non_signature_rows = [
            item
            for item in actor_rows
            if not (item.fingerprint.semantic_groups & signature_groups)
        ]
        non_signature_channels = Counter(
            item.fingerprint.channel for item in non_signature_rows
        )
        share = max(non_signature_channels.values(), default=0) / max(
            1, len(non_signature_rows)
        )
        max_channel_share = max(max_channel_share, share)
        distributions.append(
            DistributionRow(
                actor_id=actor_id,
                occurrence_count=len(actor_rows),
                channel_counts=dict(sorted(channels.items())),
                strategy_counts=dict(sorted(strategies.items())),
                semantic_group_counts=dict(sorted(groups.items())),
                highest_non_signature_channel_share=share,
            )
        )

    chapter_hotspots = tuple(
        HotspotRow(scope_id=chapter, key=group, count=count)
        for (chapter, group), count in sorted(chapter_groups.items(), key=lambda pair: (-pair[1], pair[0]))
        if count > 1
    )
    syntax_hotspots = tuple(
        HotspotRow(scope_id=chapter, key=key, count=count)
        for (chapter, key), count in sorted(syntax_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        if count > 1
    )

    exact_repeat_count = 0
    cross_chapter_repeat_count = 0
    comparable_cross_chapter = 0
    for actor_rows in by_actor.values():
        recent: deque[BehaviorOccurrence] = deque(maxlen=3)
        prior_by_chapter: dict[str, list[BehaviorOccurrence]] = defaultdict(list)
        chapter_order: list[str] = []
        for item in actor_rows:
            if item.fingerprint.unit_id and any(
                previous.fingerprint.unit_id == item.fingerprint.unit_id for previous in recent
            ):
                exact_repeat_count += 1
            recent.append(item)
            chapter = item.position.chapter_id
            previous_chapters = [
                previous for previous in chapter_order if previous != chapter
            ][-3:]
            candidates = [old for old_chapter in previous_chapters for old in prior_by_chapter[old_chapter]]
            if candidates:
                comparable_cross_chapter += 1
                if any(
                    old.fingerprint.channel == item.fingerprint.channel
                    and bool(old.fingerprint.narrative_functions & item.fingerprint.narrative_functions)
                    for old in candidates
                ):
                    cross_chapter_repeat_count += 1
            if chapter not in prior_by_chapter:
                chapter_order.append(chapter)
            prior_by_chapter[chapter].append(item)

    semantic_over_limit = sum(max(0, count - 2) for count in chapter_groups.values())
    total = len(rows)
    gate_values = {
        "IMMEDIATE_EXACT_REPEAT_RATE": (exact_repeat_count / max(1, total), total),
        "CHAPTER_SEMANTIC_OVER_LIMIT": (float(semantic_over_limit), sum(chapter_groups.values())),
        "CLICHE_GROUP_SHARE": (cliche_count / max(1, total), total),
        "MAX_CHARACTER_CHANNEL_SHARE": (max_channel_share, total),
        "CROSS_CHAPTER_FUNCTION_CHANNEL_REPEAT_RATE": (
            cross_chapter_repeat_count / max(1, comparable_cross_chapter),
            comparable_cross_chapter,
        ),
    }
    gates = tuple(
        MetricGate(
            code=spec.code,
            value=gate_values[spec.code][0],
            threshold=spec.threshold,
            comparator=spec.comparator,
            passed=(gate_passes(gate_values[spec.code][0], spec) or total == 0),
            sample_size=gate_values[spec.code][1],
        )
        for spec in MEMORY_GATE_SPECS
    )
    return BehaviorReport(
        book_id=book_id,
        occurrence_count=total,
        chapter_count=len({item.position.chapter_id for item in rows}),
        character_distributions=tuple(distributions),
        chapter_repeat_hotspots=chapter_hotspots,
        syntax_hotspots=syntax_hotspots,
        gates=gates,
    )


class BehaviorReportBuilder:
    def __init__(self, memory: BehaviorMemory) -> None:
        self.memory = memory

    def build(self, book_id: str) -> BehaviorReport:
        occurrences = self.memory.list_book_occurrences(book_id)
        signature_groups: dict[str, frozenset[str]] = {}
        for actor_id in {item.actor_id for item in occurrences}:
            identity = self.memory.load_identity(book_id, actor_id)
            if identity is not None:
                signature_groups[actor_id] = frozenset(
                    family.semantic_group for family in identity.signature_families
                )
        return build_behavior_report(
            book_id,
            occurrences,
            signature_groups_by_actor=signature_groups,
        )


def render_markdown(report: BehaviorReport) -> str:
    lines = [f"# 行为控制报告：{report.book_id}", "", f"- 行为记录：{report.occurrence_count}", f"- 章节数：{report.chapter_count}", f"- 自动门禁：{'通过' if report.automatic_gates_passed else '未通过'}", "", "## 角色行为分布", ""]
    if not report.character_distributions:
        lines.append("暂无已提交行为。")
    for row in report.character_distributions:
        channels = "、".join(f"{key}={value}" for key, value in row.channel_counts.items()) or "无"
        lines.append(f"- {row.actor_id}：{row.occurrence_count} 次；通道 {channels}")
    lines.extend(["", "## 章节重复热点", ""])
    lines.extend(f"- {row.scope_id} / {row.key}：{row.count}" for row in report.chapter_repeat_hotspots)
    if not report.chapter_repeat_hotspots:
        lines.append("暂无重复热点。")
    lines.extend(["", "## 句法模板热点", ""])
    lines.extend(f"- {row.scope_id} / {row.key}：{row.count}" for row in report.syntax_hotspots)
    if not report.syntax_hotspots:
        lines.append("暂无句法模板热点。")
    lines.extend(["", "## 自动验收门禁", "", "| 指标 | 当前值 | 阈值 | 结果 |", "|---|---:|---:|---|"])
    for gate in report.gates:
        lines.append(f"| {gate.code} | {gate.value:.4f} | {gate.comparator} {gate.threshold:.4f} | {'通过' if gate.passed else '失败'} |")
    return "\n".join(lines) + "\n"


def render_html(report: BehaviorReport) -> str:
    markdown = render_markdown(report)
    sections = []
    in_list = False
    for line in markdown.splitlines():
        if line.startswith("# "):
            sections.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                sections.append("</ul>")
                in_list = False
            sections.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("- "):
            if not in_list:
                sections.append("<ul>")
                in_list = True
            sections.append(f"<li>{escape(line[2:])}</li>")
        elif line and not line.startswith("|"):
            if in_list:
                sections.append("</ul>")
                in_list = False
            sections.append(f"<p>{escape(line)}</p>")
    if in_list:
        sections.append("</ul>")
    gate_rows = "".join(
        f"<tr><td>{escape(g.code)}</td><td>{g.value:.4f}</td><td>{escape(g.comparator)} {g.threshold:.4f}</td><td>{'通过' if g.passed else '失败'}</td></tr>"
        for g in report.gates
    )
    sections.append(f"<table><thead><tr><th>指标</th><th>当前值</th><th>阈值</th><th>结果</th></tr></thead><tbody>{gate_rows}</tbody></table>")
    body = "\n".join(sections)
    return f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>{escape(report.book_id)} 行为控制报告</title><style>body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;line-height:1.6}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #bbb;padding:.4rem;text-align:left}}</style></head><body>{body}</body></html>\n"


__all__ = ["BehaviorReport", "BehaviorReportBuilder", "DistributionRow", "HotspotRow", "MetricGate", "build_behavior_report", "render_html", "render_markdown"]
