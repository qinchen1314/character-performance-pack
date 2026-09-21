from character_performance.blind_review import (
    BlindRating,
    ReviewCase,
    aggregate_ratings,
    build_blind_packet,
)
from character_performance.catalog import CatalogRecord
from character_performance.catalog import compile_record
from character_performance.ontology.emotion import EmotionOntology
from pathlib import Path
import pytest


def _record(unit_id: str, clause: str) -> CatalogRecord:
    return CatalogRecord(
        id=unit_id,
        category="body",
        channel="head",
        parts=("head",),
        family="acknowledgment",
        meaning="确认自己已经听见对方",
        clause=clause,
        emotions=("approval", "trust"),
        axis="warmth",
    )


def test_blind_packet_hides_catalog_identity_and_covers_review_lenses() -> None:
    records = (
        _record("body.nod_once", "点了一下头"),
        _record("body.nod_twice", "连着点了两下头"),
        _record("body.nod_slow", "慢慢点了点头"),
    )
    cases = (
        ReviewCase(
            id="wuxia.terse.guard",
            genre="武侠",
            style="冷硬短句",
            character="守关刀客",
            subject_name="燕七",
            lead_in="来人报出旧主名号。",
            follow_up="他没有让开山门。",
        ),
        ReviewCase(
            id="romance.delicate.heiress",
            genre="都市情感",
            style="细腻克制",
            character="失势继承人",
            subject_name="程雾",
            lead_in="那份协议推到她面前。",
            follow_up="窗外的车声正好盖过沉默。",
        ),
        ReviewCase(
            id="xianxia.clean.swordmaster",
            genre="仙侠",
            style="清峻古典",
            character="寡言剑修",
            subject_name="谢停云",
            lead_in="传音符在案上化作灰烬。",
            follow_up="殿外松涛未歇。",
        ),
    )

    packet, key = build_blind_packet(records, cases, seed=17)

    assert {item.genre for item in packet.items} == {"武侠", "都市情感", "仙侠"}
    assert {item.style for item in packet.items} == {
        "冷硬短句",
        "细腻克制",
        "清峻古典",
    }
    public_dump = packet.model_dump_json()
    assert "body.nod_" not in public_dump
    assert {item.case_id for item in packet.items} == set(key.unit_ids)
    assert len(packet.items) == 9
    assert all(list(key.unit_ids.values()).count(record.id) == 3 for record in records)


def test_review_decision_requires_two_independent_humans() -> None:
    unit_ids = {"case-a": "body.nod_once"}
    first = BlindRating(
        case_id="case-a",
        reviewer_id="reader-1",
        prose_value=1,
        naturalness=2,
        character_fit=2,
        flags=("mechanical",),
    )

    pending = aggregate_ratings(unit_ids, (first,), minimum_reviewers=2)
    assert pending.units[0].decision == "pending"

    second = BlindRating(
        case_id="case-a",
        reviewer_id="reader-2",
        prose_value=2,
        naturalness=1,
        character_fit=2,
        flags=("stiff", "not_worth_prose"),
    )
    complete = aggregate_ratings(unit_ids, (first, second), minimum_reviewers=2)

    assert complete.units[0].decision == "remove"
    assert complete.units[0].reviewer_count == 2


def test_repeated_reviewer_does_not_satisfy_independence_gate() -> None:
    ratings = (
        BlindRating(
            case_id="case-a",
            reviewer_id="reader-1",
            prose_value=2,
            naturalness=2,
            character_fit=2,
        ),
        BlindRating(
            case_id="case-b",
            reviewer_id="reader-1",
            prose_value=2,
            naturalness=2,
            character_fit=2,
        ),
    )

    result = aggregate_ratings(
        {"case-a": "body.nod_once", "case-b": "body.nod_once"},
        ratings,
        minimum_reviewers=2,
    )

    assert result.units[0].decision == "pending"
    assert result.units[0].reviewer_count == 1


def test_each_human_has_equal_weight_across_multiple_character_lenses() -> None:
    ratings = tuple(
        BlindRating(
            case_id=case_id,
            reviewer_id="reader-1",
            prose_value=1,
            naturalness=1,
            character_fit=1,
        )
        for case_id in ("case-a", "case-b", "case-c")
    ) + (
        BlindRating(
            case_id="case-a",
            reviewer_id="reader-2",
            prose_value=5,
            naturalness=5,
            character_fit=5,
        ),
    )

    result = aggregate_ratings(
        {
            "case-a": "body.nod_once",
            "case-b": "body.nod_once",
            "case-c": "body.nod_once",
        },
        ratings,
        minimum_reviewers=2,
    )

    assert result.units[0].naturalness == 3
    assert result.units[0].decision == "keep"


def test_editorially_rejected_record_compiles_as_deprecated_with_replacement() -> None:
    record = _record("body.nod_once", "点了一下头").model_copy(
        update={
            "editorial_status": "rejected",
            "editorial_note": "跨题材试读均显得机械，不值得进入正文",
            "replacement_id": "body.nod_slow",
        }
    )
    ontology = EmotionOntology.from_yaml(
        Path(__file__).parents[2] / "data" / "ontology" / "emotion" / "emotions.yaml"
    )

    unit = compile_record(record, ontology)

    assert unit.status == "deprecated"
    assert unit.replacement_id == "body.nod_slow"
