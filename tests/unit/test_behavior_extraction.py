from __future__ import annotations

import pytest

from character_performance.domain.behavior_models import (
    ExtractedBehavior,
    ExtractionRequest,
    ExtractionResult,
    NarrativePosition,
    TextSpan,
)
from character_performance.domain.models import CharacterProfile
from character_performance.extraction import (
    ExtractionUnavailable,
    HybridBehaviorExtractor,
    LLMBehaviorExtractor,
    RuleBasedBehaviorExtractor,
    SpanValidationError,
)


def _position() -> NarrativePosition:
    return NarrativePosition(
        book_id="book.demo",
        chapter_id="chapter.1",
        scene_id="scene.1",
        paragraph_index=0,
        beat_index=0,
        global_beat_index=1,
    )


def _request(text: str, *, two_characters: bool = False) -> ExtractionRequest:
    characters = (CharacterProfile(id="char.a"),)
    aliases = {"甲": "char.a"}
    if two_characters:
        characters += (CharacterProfile(id="char.b"),)
        aliases["乙"] = "char.b"
    return ExtractionRequest(
        run_id="run.extract",
        text=text,
        known_characters=characters,
        position=_position(),
        pack_summary={"character_aliases": aliases},
    )


def test_rule_extractor_recognizes_free_paraphrase_and_implicit_pause() -> None:
    text = "他把指甲掐进掌心，却没有回答。"
    result = RuleBasedBehaviorExtractor().extract(_request(text))

    assert [item.canonical_action for item in result.behaviors] == [
        "hand_clench",
        "delay_response",
    ]
    hand = result.behaviors[0]
    assert hand.matched_unit_id == "body.hand_clench"
    assert "hand_tension" in hand.semantic_groups
    assert hand.text_span.text == text[hand.text_span.start : hand.text_span.end]
    assert all("rule" in item.evidence_sources for item in result.behaviors)


def test_rule_extractor_attributes_multiple_people_from_aliases() -> None:
    text = "甲拳头缓缓握紧。乙移开目光，沉默片刻。"
    result = RuleBasedBehaviorExtractor().extract(_request(text, two_characters=True))

    assert [(item.actor_id, item.canonical_action) for item in result.behaviors] == [
        ("char.a", "hand_clench"),
        ("char.b", "gaze_withdrawal"),
        ("char.b", "delay_response"),
    ]


def test_llm_adapter_rejects_span_that_does_not_match_source() -> None:
    request = _request("他移开目光。")
    payload = {
        "run_id": request.run_id,
        "behaviors": [
            {
                "actor_id": "char.a",
                "text_span": {"start": 0, "end": 4, "text": "错误文本"},
                "canonical_action": "gaze_withdrawal",
                "semantic_groups": ["gaze_withdrawal"],
                "channel": "gaze",
                "narrative_functions": ["withdraw"],
                "confidence": 0.9,
            }
        ],
    }
    with pytest.raises(SpanValidationError, match="exact source text"):
        LLMBehaviorExtractor(lambda _: payload).extract(request)


def test_hybrid_merges_agreement_and_marks_evidence_sources() -> None:
    text = "他移开目光。"
    request = _request(text)
    rule = RuleBasedBehaviorExtractor()
    start = text.index("移开目光")
    payload = {
        "run_id": request.run_id,
        "behaviors": [
            {
                "actor_id": "char.a",
                "text_span": {"start": start, "end": start + 4, "text": "移开目光"},
                "canonical_action": "gaze_withdrawal",
                "matched_unit_id": "gaze.look_away",
                "semantic_groups": ["gaze_withdrawal"],
                "channel": "gaze",
                "narrative_functions": ["withdraw"],
                "confidence": 0.88,
            }
        ],
    }
    hybrid = HybridBehaviorExtractor(rule, LLMBehaviorExtractor(lambda _: payload))
    result = hybrid.extract(request)

    assert len(result.behaviors) == 1
    assert result.behaviors[0].evidence_sources == frozenset({"rule", "llm"})
    assert not hybrid.conflicts


def test_hybrid_merges_overlapping_agreement_and_resolves_rule_gap() -> None:
    text = "他忽然移开目光。"
    request = _request(text)
    phrase_start = text.index("移开目光")
    payload = {
        "run_id": request.run_id,
        "behaviors": [
            {
                "actor_id": "char.a",
                "text_span": {
                    "start": phrase_start - 2,
                    "end": phrase_start + 4,
                    "text": "忽然移开目光",
                },
                "canonical_action": "gaze_withdrawal",
                "semantic_groups": ["gaze_withdrawal"],
                "channel": "gaze",
                "narrative_functions": ["withdraw"],
                "confidence": 0.88,
            }
        ],
    }
    hybrid = HybridBehaviorExtractor(
        RuleBasedBehaviorExtractor(), LLMBehaviorExtractor(lambda _: payload)
    )

    result = hybrid.extract(request)

    assert len(result.behaviors) == 1
    assert result.behaviors[0].evidence_sources == frozenset({"rule", "llm"})
    assert not result.unresolved_spans
    assert not hybrid.conflicts


def test_hybrid_retains_both_conflicting_interpretations_at_lower_confidence() -> None:
    text = "他移开目光。"
    request = _request(text)
    start = text.index("移开目光")
    payload = {
        "run_id": request.run_id,
        "behaviors": [
            {
                "actor_id": "char.a",
                "text_span": {"start": start, "end": start + 4, "text": "移开目光"},
                "canonical_action": "social_reading",
                "semantic_groups": ["social_reading"],
                "channel": "gaze",
                "narrative_functions": ["observe"],
                "confidence": 0.9,
            }
        ],
    }
    hybrid = HybridBehaviorExtractor(
        RuleBasedBehaviorExtractor(), LLMBehaviorExtractor(lambda _: payload)
    )
    result = hybrid.extract(request)

    assert len(result.behaviors) == 2
    assert len(hybrid.conflicts) == 1
    assert all(item.confidence <= 0.49 for item in result.behaviors)
    assert all(item.evidence_sources == frozenset({"rule", "llm"}) for item in result.behaviors)


def test_hybrid_degrades_to_rules_when_llm_is_unavailable() -> None:
    request = _request("他移开目光。")
    hybrid = HybridBehaviorExtractor(
        RuleBasedBehaviorExtractor(), LLMBehaviorExtractor(None)
    )
    result = hybrid.extract(request)

    assert [item.canonical_action for item in result.behaviors] == ["gaze_withdrawal"]
    assert isinstance(hybrid.last_error, ExtractionUnavailable)


def test_rule_extractor_reports_unresolved_action_like_sentence() -> None:
    text = "他忽然回头，做了一个谁也看不懂的手势。"
    result = RuleBasedBehaviorExtractor().extract(_request(text))

    assert not result.behaviors
    assert result.unresolved_spans
    assert result.unresolved_spans[0].text == text
