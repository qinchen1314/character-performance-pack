from __future__ import annotations

from hashlib import sha256

import pytest
from pydantic import ValidationError

from character_performance.domain.behavior_models import (
    AcceptedDraft,
    AuditIssue,
    AuditMetrics,
    AuditResult,
    BehaviorFingerprint,
    BehaviorIdentity,
    BehaviorOccurrence,
    CandidateBehavior,
    ChangedSpan,
    CommitRequest,
    CommitResult,
    ExtractedBehavior,
    ExtractionRequest,
    ExtractionResult,
    GenerationBrief,
    GenerationRequest,
    NarrativePosition,
    OverusedBehavior,
    PreservationChecks,
    ReactionStrategyPlan,
    RewriteRequest,
    RewriteResult,
    SignatureFamily,
    SourceSpan,
    StyleContext,
    SyntaxFeatures,
    TextReplacement,
    TextSpan,
)
from character_performance.domain.models import CharacterProfile, SceneState


def _position() -> NarrativePosition:
    return NarrativePosition(
        book_id="book.hehuan",
        volume_id="volume.01",
        chapter_id="chapter.0017",
        scene_id="scene.0017.02",
        paragraph_index=18,
        beat_index=43,
        global_beat_index=1284,
        timeline_ms=972000,
    )


def _identity() -> BehaviorIdentity:
    return BehaviorIdentity(
        character_id="char.luo_han",
        version=1,
        default_strategies={"conflict": "conceal_then_counter"},
        preferred_channels={"gaze": 0.8, "speech_rhythm": 0.72},
        avoided_channels={"hands": 0.9},
        values={"self_control", "status"},
        taboos={"public_pleading"},
        coping_strategies={"observe", "conceal"},
        social_masks={"public": "controlled_courtesy"},
        signature_families=(
            SignatureFamily(
                semantic_group="deliberate_pause",
                affinity=0.75,
                cooldown_chapters=3,
                maximum_per_volume=8,
            ),
        ),
    )


def _strategy() -> ReactionStrategyPlan:
    return ReactionStrategyPlan(
        strategy_id="conceal_then_counter",
        intent="protect_status_without_escalation",
        surface_goal="maintain_courtesy",
        private_goal="retain_initiative",
        applicability_conditions={"public_scene", "target_hostile"},
        contraindications={"unconscious"},
        preferred_channels=("speech_rhythm", "gaze"),
        suppressed_channels={"hands"},
        allowed_visibility="subtle",
        action_budget=2,
        omit_action_allowed=True,
        relationship_meaning="courtesy_without_submission",
        reasons=("public_scene", "character_high_self_control"),
    )


def _fingerprint() -> BehaviorFingerprint:
    return BehaviorFingerprint(
        unit_id="body.hand_clench",
        semantic_groups={"hand_tension", "restraint_leak"},
        channel="hands",
        narrative_functions={"anger_leak"},
        strategy_id="conceal_then_counter",
        actor_id="char.luo_han",
        target_ids=("char.enemy",),
        visibility="subtle",
        amplitude_band="low",
        syntax_features=SyntaxFeatures(
            subject_opening="body_part",
            temporal_shape="brief_then_release",
            reset_pattern=True,
            dialogue_position="before_dialogue",
        ),
        lexical_lemmas=("手指", "收紧", "松开"),
    )


def _hash(text: str) -> str:
    return f"sha256:{sha256(text.encode('utf-8')).hexdigest()}"


def test_behavior_identity_round_trips_and_emits_versioned_schema() -> None:
    identity = _identity()

    restored = BehaviorIdentity.model_validate_json(identity.model_dump_json())
    schema = BehaviorIdentity.model_json_schema()

    assert restored == identity
    assert schema["properties"]["schema_version"]["default"] == "1.0.0"


def test_identity_rejects_channel_preferred_and_avoided_at_once() -> None:
    with pytest.raises(ValidationError, match="preferred and avoided"):
        BehaviorIdentity.model_validate(
            {**_identity().model_dump(), "avoided_channels": {"gaze": 0.9}}
        )


def test_strategy_rejects_preferred_channel_that_is_suppressed() -> None:
    with pytest.raises(ValidationError, match="preferred and suppressed"):
        ReactionStrategyPlan.model_validate(
            {**_strategy().model_dump(), "suppressed_channels": ["gaze"]}
        )


def test_occurrence_requires_fingerprint_identity_and_exact_span_length() -> None:
    text = "他五指微微收拢，旋即松开。"
    with pytest.raises(ValidationError, match="fingerprint.actor_id"):
        BehaviorOccurrence(
            occurrence_id="occurrence.01j",
            book_id="book.hehuan",
            position=_position(),
            actor_id="char.other",
            target_ids=("char.enemy",),
            fingerprint=_fingerprint(),
            source="extracted",
            text_span=TextSpan(start=0, end=len(text), text=text),
            confidence=0.94,
            generation_run_id="run.01j",
            accepted_revision=3,
        )


def test_planned_occurrence_cannot_claim_an_accepted_revision() -> None:
    text = "他五指微微收拢，旋即松开。"
    with pytest.raises(ValidationError, match="planned or rendered"):
        BehaviorOccurrence(
            occurrence_id="occurrence.01j",
            book_id="book.hehuan",
            position=_position(),
            actor_id="char.luo_han",
            target_ids=("char.enemy",),
            fingerprint=_fingerprint(),
            source="planned",
            text_span=TextSpan(start=0, end=len(text), text=text),
            confidence=0.94,
            generation_run_id="run.01j",
            accepted_revision=3,
        )


def test_generation_request_cross_validates_character_identity_and_scene() -> None:
    with pytest.raises(ValidationError, match="scene_id"):
        GenerationRequest(
            run_id="run.01j",
            position=_position(),
            character=CharacterProfile(id="char.luo_han"),
            behavior_identity=_identity(),
            scene_state=SceneState(scene_id="scene.other"),
            style_context=StyleContext(
                pov="third_limited",
                prose_style="concise",
                paragraph_function="confrontation",
            ),
        )


def test_generation_brief_budget_and_channels_are_consistent_with_strategy() -> None:
    with pytest.raises(ValidationError, match="maximum_visible_signals"):
        GenerationBrief(
            run_id="run.01j",
            strategy=_strategy(),
            recently_overused=(
                OverusedBehavior(
                    semantic_group="hand_tension", severity="block", reason="recent"
                ),
            ),
            preferred_channels=("gaze",),
            candidate_behaviors=(
                CandidateBehavior(
                    unit_id="gaze.pass_without_hold",
                    purpose="deny_status_acknowledgement",
                    realization_guidance="一掠而过",
                    channel="gaze",
                ),
            ),
            omit_action_allowed=True,
            maximum_visible_signals=3,
            prompt_fragment="避免重复动作。",
            memory_revision=47,
        )


def test_extraction_models_validate_actor_membership_spans_and_round_trip() -> None:
    text = "他五指微微收拢，旋即松开。"
    request = ExtractionRequest(
        run_id="run.01j",
        text=text,
        known_characters=(CharacterProfile(id="char.luo_han"),),
        position=_position(),
        scene_facts={"fact.holding_sword"},
    )
    behavior = ExtractedBehavior(
        actor_id="char.luo_han",
        target_ids=(),
        text_span=TextSpan(start=0, end=len(text), text=text),
        canonical_action="hand_clench_release",
        matched_unit_id="body.hand_clench",
        semantic_groups={"hand_tension"},
        channel="hands",
        narrative_functions={"anger_leak"},
        syntax_features=SyntaxFeatures(
            temporal_shape="brief_then_release", reset_pattern=True
        ),
        confidence=0.94,
    )
    result = ExtractionResult(
        run_id="run.01j", behaviors=(behavior,)
    )

    request.validate_result(result)
    assert ExtractionResult.model_validate_json(result.model_dump_json()) == result


def test_extraction_request_rejects_result_whose_span_does_not_match_source() -> None:
    text = "甲抬眼。"
    request = ExtractionRequest(
        run_id="run.01j",
        text=text,
        known_characters=(CharacterProfile(id="char.luo_han"),),
        position=_position(),
    )
    result = ExtractionResult(
        run_id="run.01j",
        behaviors=(
            ExtractedBehavior(
                actor_id="char.luo_han",
                text_span=TextSpan(start=0, end=4, text="乙抬眼。"),
                canonical_action="raise_gaze",
                semantic_groups={"gaze_engage"},
                channel="gaze",
                narrative_functions={"attention"},
                confidence=0.9,
            ),
        ),
    )

    with pytest.raises(ValueError, match="exact source text"):
        request.validate_result(result)


def test_audit_acceptance_must_agree_with_issue_severity_and_hash() -> None:
    text = "正文"
    issue = AuditIssue(
        issue_id="issue.01",
        severity="rewrite",
        code="cross_chapter_semantic_repeat",
        spans=(SourceSpan(start=0, end=2),),
        actor_id="char.luo_han",
        preserve={"dialogue"},
    )
    with pytest.raises(ValidationError, match="accepted"):
        AuditResult(
            run_id="run.01j",
            draft_hash=_hash(text),
            accepted=True,
            issues=(issue,),
            metrics=AuditMetrics(),
            memory_revision=47,
        )


def test_rewrite_result_resolves_only_known_issues_and_preserves_hashes() -> None:
    original = "旧句。"
    revised = "新句。"
    with pytest.raises(ValidationError, match="resolved_issue_ids"):
        RewriteResult(
            run_id="run.01j",
            original_text=original,
            text=revised,
            changed_spans=(
                ChangedSpan(
                    original=TextSpan(start=0, end=len(original), text=original),
                    replacement=TextReplacement(text=revised),
                    resolved_issue_ids=("issue.unknown",),
                ),
            ),
            requested_issue_ids=("issue.01",),
            preserved_checks=PreservationChecks(
                dialogue_hash="sha256:" + "0" * 64,
                required_facts=True,
                scene_state=True,
                grammar_complete=True,
                punctuation_balanced=True,
                reference_continuity=True,
            ),
            rewrite_attempt=1,
        )


def test_rewrite_result_must_reproduce_text_and_preserve_required_state() -> None:
    original = "旧句。"
    common = {
        "run_id": "run.01j",
        "original_text": original,
        "changed_spans": (
            ChangedSpan(
                original=TextSpan(start=0, end=len(original), text=original),
                replacement=TextReplacement(text="新句。"),
                resolved_issue_ids=("issue.01",),
            ),
        ),
        "requested_issue_ids": ("issue.01",),
        "rewrite_attempt": 1,
    }

    with pytest.raises(ValidationError, match="reproduce"):
        RewriteResult(
            **common,
            text="无关正文。",
            preserved_checks=PreservationChecks(
                dialogue_hash="sha256:" + "0" * 64,
                required_facts=True,
                scene_state=True,
                grammar_complete=True,
                punctuation_balanced=True,
                reference_continuity=True,
            ),
        )

    with pytest.raises(ValidationError, match="preserve"):
        RewriteResult(
            **common,
            text="新句。",
            preserved_checks=PreservationChecks(
                dialogue_hash="sha256:" + "0" * 64,
                required_facts=False,
                scene_state=True,
                grammar_complete=True,
                punctuation_balanced=True,
                reference_continuity=True,
            ),
        )


def test_commit_models_verify_content_hash_and_round_trip() -> None:
    text = "通过审查的正文"
    accepted = AcceptedDraft(
        text=text,
        draft_hash=_hash(text),
        memory_revision=47,
    )
    request = CommitRequest(run_id="run.01j", accepted=accepted)
    result = CommitResult(
        run_id="run.01j",
        accepted_revision=3,
        content_hash=_hash(text),
        memory_revision=48,
        occurrence_ids=("occurrence.01j",),
        idempotent_replay=False,
    )

    assert CommitRequest.model_validate_json(request.model_dump_json()) == request
    assert CommitResult.model_validate_json(result.model_dump_json()) == result


def test_accepted_draft_rejects_hash_for_different_text() -> None:
    with pytest.raises(ValidationError, match="draft_hash"):
        AcceptedDraft(
            text="正文甲",
            draft_hash=_hash("正文乙"),
            memory_revision=47,
        )


def test_accepted_draft_accepts_documented_three_field_api_shape() -> None:
    text = "正文"

    accepted = AcceptedDraft(
        text=text,
        draft_hash=_hash(text),
        memory_revision=47,
    )

    assert accepted.text == text


def test_rewrite_request_rejects_audit_span_outside_the_draft() -> None:
    text = "正文"
    audit = AuditResult(
        run_id="run.01j",
        draft_hash=_hash(text),
        accepted=False,
        issues=(
            AuditIssue(
                issue_id="issue.01",
                severity="rewrite",
                code="syntax_repeat",
                spans=(SourceSpan(start=99, end=100),),
            ),
        ),
        metrics=AuditMetrics(),
        memory_revision=47,
    )

    with pytest.raises(ValidationError, match="exceeds draft length"):
        RewriteRequest(run_id="run.01j", text=text, audit=audit, attempt=1)


def test_every_top_level_behavior_contract_round_trips_through_json() -> None:
    text = "他抬眼。"
    span = TextSpan(start=0, end=len(text), text=text)
    fingerprint = BehaviorFingerprint(
        unit_id="gaze.raise",
        semantic_groups={"gaze_engage"},
        channel="gaze",
        narrative_functions={"attention"},
        strategy_id="observe",
        actor_id="char.luo_han",
    )
    occurrence = BehaviorOccurrence(
        occurrence_id="occurrence.01j",
        book_id="book.hehuan",
        position=_position(),
        actor_id="char.luo_han",
        fingerprint=fingerprint,
        source="extracted",
        text_span=span,
        confidence=0.9,
        generation_run_id="run.01j",
        accepted_revision=1,
    )
    generation_request = GenerationRequest(
        run_id="run.01j",
        position=_position(),
        character=CharacterProfile(id="char.luo_han"),
        behavior_identity=_identity(),
        scene_state=SceneState(scene_id="scene.0017.02"),
        style_context=StyleContext(
            pov="third_limited",
            prose_style="concise",
            paragraph_function="confrontation",
        ),
    )
    brief = GenerationBrief(
        run_id="run.01j",
        strategy=_strategy(),
        preferred_channels=("gaze",),
        candidate_behaviors=(
            CandidateBehavior(
                unit_id="gaze.raise",
                purpose="retain_initiative",
                realization_guidance="让视线承担态度。",
                channel="gaze",
                semantic_groups={"gaze_engage"},
            ),
        ),
        omit_action_allowed=True,
        maximum_visible_signals=1,
        prompt_fragment="保持克制。",
        memory_revision=47,
    )
    extraction_request = ExtractionRequest(
        run_id="run.01j",
        text=text,
        known_characters=(CharacterProfile(id="char.luo_han"),),
        position=_position(),
    )
    extracted = ExtractedBehavior(
        actor_id="char.luo_han",
        text_span=span,
        canonical_action="raise_gaze",
        matched_unit_id="gaze.raise",
        semantic_groups={"gaze_engage"},
        channel="gaze",
        narrative_functions={"attention"},
        confidence=0.9,
    )
    extraction_result = ExtractionResult(
        run_id="run.01j", behaviors=(extracted,)
    )
    issue = AuditIssue(
        issue_id="issue.01",
        severity="rewrite",
        code="syntax_repeat",
        spans=(SourceSpan(start=span.start, end=span.end),),
    )
    audit = AuditResult(
        run_id="run.01j",
        draft_hash=_hash(text),
        accepted=False,
        issues=(issue,),
        metrics=AuditMetrics(syntax_pattern_score=0.8),
        memory_revision=47,
        auto_rewrite_allowed=True,
    )
    rewrite_request = RewriteRequest(run_id="run.01j", text=text, audit=audit, attempt=1)
    rewrite_result = RewriteResult(
        run_id="run.01j",
        original_text=text,
        text="他没有接话。",
        changed_spans=(
            ChangedSpan(
                original=span,
                replacement=TextReplacement(text="他没有接话。"),
                resolved_issue_ids=("issue.01",),
            ),
        ),
        requested_issue_ids=("issue.01",),
        preserved_checks=PreservationChecks(
            dialogue_hash="sha256:" + "0" * 64,
            required_facts=True,
            scene_state=True,
            grammar_complete=True,
            punctuation_balanced=True,
            reference_continuity=True,
        ),
        rewrite_attempt=1,
    )
    accepted = AcceptedDraft(
        text=text,
        draft_hash=_hash(text),
        memory_revision=47,
    )
    instances = (
        _position(),
        _identity(),
        _strategy(),
        fingerprint,
        occurrence,
        generation_request,
        brief,
        extraction_request,
        extraction_result,
        audit,
        rewrite_request,
        rewrite_result,
        accepted,
        CommitRequest(run_id="run.01j", accepted=accepted),
        CommitResult(
            run_id="run.01j",
            accepted_revision=1,
            content_hash=_hash(text),
            memory_revision=48,
            occurrence_ids=("occurrence.01j",),
            idempotent_replay=False,
        ),
    )

    for instance in instances:
        assert type(instance).model_validate_json(instance.model_dump_json()) == instance
