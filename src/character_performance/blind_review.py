"""Deterministic, identity-blind literary review packets and aggregation."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import random
from statistics import fmean
from typing import Literal, Mapping, Sequence

from pydantic import Field, model_validator

from character_performance.catalog import CatalogRecord
from character_performance.domain.models import DomainModel, NonEmptyId


class ReviewCase(DomainModel):
    id: NonEmptyId
    genre: str = Field(min_length=1)
    style: str = Field(min_length=1)
    character: str = Field(min_length=1)
    subject_name: str = Field(min_length=1)
    lead_in: str = Field(min_length=1)
    follow_up: str = Field(min_length=1)
    categories: tuple[NonEmptyId, ...] = ()


class BlindItem(DomainModel):
    case_id: NonEmptyId
    genre: str
    style: str
    character: str
    excerpt: str


class BlindPacket(DomainModel):
    packet_id: NonEmptyId
    instructions: str
    items: tuple[BlindItem, ...] = Field(min_length=1)


class BlindKey(DomainModel):
    packet_id: NonEmptyId
    unit_ids: dict[NonEmptyId, NonEmptyId]


ReviewFlag = Literal["mechanical", "stiff", "not_worth_prose", "characterless"]


class BlindRating(DomainModel):
    case_id: NonEmptyId
    reviewer_id: NonEmptyId
    prose_value: int = Field(ge=1, le=5)
    naturalness: int = Field(ge=1, le=5)
    character_fit: int = Field(ge=1, le=5)
    flags: tuple[ReviewFlag, ...] = ()
    note: str = ""

    @model_validator(mode="after")
    def unique_flags(self) -> "BlindRating":
        if len(set(self.flags)) != len(self.flags):
            raise ValueError("rating flags must be unique")
        return self


class UnitReviewDecision(DomainModel):
    unit_id: NonEmptyId
    reviewer_count: int = Field(ge=0)
    rating_count: int = Field(ge=0)
    prose_value: float | None = None
    naturalness: float | None = None
    character_fit: float | None = None
    flags: dict[str, int] = Field(default_factory=dict)
    decision: Literal["pending", "keep", "rewrite", "remove"]


class BlindReviewReport(DomainModel):
    minimum_reviewers: int = Field(ge=2)
    units: tuple[UnitReviewDecision, ...]


def build_blind_packet(
    records: Sequence[CatalogRecord],
    cases: Sequence[ReviewCase],
    *,
    seed: int,
    lenses_per_record: int = 3,
) -> tuple[BlindPacket, BlindKey]:
    """Pair records with shuffled review lenses without exposing catalog metadata."""
    if not records:
        raise ValueError("at least one catalog record is required")
    if not cases:
        raise ValueError("at least one review case is required")
    if lenses_per_record < 1:
        raise ValueError("lenses_per_record must be positive")
    shuffled_records = list(records)
    shuffled_cases = list(cases)
    random.Random(seed).shuffle(shuffled_records)
    random.Random(seed ^ 0xC0DEC).shuffle(shuffled_cases)
    items: list[BlindItem] = []
    unit_ids: dict[str, str] = {}
    for index, record in enumerate(shuffled_records):
        eligible = [
            lens
            for lens in shuffled_cases
            if not lens.categories or record.category in lens.categories
        ]
        if not eligible:
            raise ValueError(f"no review case accepts category: {record.category}")
        start = index % len(eligible)
        selected_lenses = [
            eligible[(start + offset) % len(eligible)]
            for offset in range(min(lenses_per_record, len(eligible)))
        ]
        for lens_index, lens in enumerate(selected_lenses):
            token = sha256(
                f"{seed}:{index}:{lens_index}:{record.id}:{lens.id}".encode()
            ).hexdigest()[:12]
            case_id = f"blind.{token}"
            excerpt = f"{lens.lead_in}{lens.subject_name}{record.clause}。{lens.follow_up}"
            items.append(
                BlindItem(
                    case_id=case_id,
                    genre=lens.genre,
                    style=lens.style,
                    character=lens.character,
                    excerpt=excerpt,
                )
            )
            unit_ids[case_id] = record.id
    random.Random(seed ^ 0xB11D).shuffle(items)
    packet_hash = sha256("|".join(item.case_id for item in items).encode()).hexdigest()[:12]
    packet_id = f"packet.{packet_hash}"
    instructions = (
        "请只按匿名片段评分：正文价值、自然度、角色贴合度各 1—5 分；"
        "可标记 mechanical、stiff、not_worth_prose 或 characterless。"
    )
    return (
        BlindPacket(packet_id=packet_id, instructions=instructions, items=tuple(items)),
        BlindKey(packet_id=packet_id, unit_ids=unit_ids),
    )


def aggregate_ratings(
    unit_ids: Mapping[str, str],
    ratings: Sequence[BlindRating],
    *,
    minimum_reviewers: int = 2,
) -> BlindReviewReport:
    if minimum_reviewers < 2:
        raise ValueError("blind review requires at least two independent reviewers")
    grouped: dict[str, list[BlindRating]] = defaultdict(list)
    for rating in ratings:
        try:
            unit_id = unit_ids[rating.case_id]
        except KeyError as exc:
            raise ValueError(f"unknown blind case: {rating.case_id}") from exc
        grouped[unit_id].append(rating)
    decisions: list[UnitReviewDecision] = []
    for unit_id in sorted(set(unit_ids.values())):
        rows = grouped[unit_id]
        by_reviewer: dict[str, list[BlindRating]] = defaultdict(list)
        for row in rows:
            by_reviewer[row.reviewer_id].append(row)
        reviewer_count = len(by_reviewer)
        flag_counts: dict[str, int] = defaultdict(int)
        for reviewer_rows in by_reviewer.values():
            for flag in {flag for row in reviewer_rows for flag in row.flags}:
                flag_counts[flag] += 1
        scores = {
            name: round(
                fmean(
                    fmean(getattr(row, name) for row in reviewer_rows)
                    for reviewer_rows in by_reviewer.values()
                ),
                2,
            )
            if rows
            else None
            for name in ("prose_value", "naturalness", "character_fit")
        }
        if reviewer_count < minimum_reviewers:
            decision = "pending"
        elif scores["prose_value"] <= 2 and scores["naturalness"] <= 2:
            decision = "remove"
        elif min(scores.values()) < 3 or any(
            count * 2 >= reviewer_count for count in flag_counts.values()
        ):
            decision = "rewrite"
        else:
            decision = "keep"
        decisions.append(
            UnitReviewDecision(
                unit_id=unit_id,
                reviewer_count=reviewer_count,
                rating_count=len(rows),
                flags=dict(sorted(flag_counts.items())),
                decision=decision,
                **scores,
            )
        )
    return BlindReviewReport(minimum_reviewers=minimum_reviewers, units=tuple(decisions))
