from __future__ import annotations

import pytest

from character_performance.audit import AuditContext, GeneratedTextAuditor
from character_performance.domain.behavior_models import (
    AuditIssue,
    AuditMetrics,
    AuditResult,
    BehaviorFingerprint,
    BehaviorIdentity,
    BehaviorOccurrence,
    ExtractedBehavior,
    ExtractionResult,
    GeneratedDraft,
    GenerationRequest,
    NarrativePosition,
    RewriteRequest,
    SourceSpan,
    StyleContext,
    SyntaxFeatures,
    TextSpan,
    content_hash,
)
from character_performance.domain.models import CharacterProfile, SceneState
from character_performance.memory.repository import BehaviorMemorySnapshot
from character_performance.rewrite import HumanReviewRequired, RewriteContext, TargetedRewriter


def _position(beat: int = 2, chapter: str = "chapter.2") -> NarrativePosition:
    return NarrativePosition(
        book_id="book.test",
        volume_id="volume.1",
        chapter_id=chapter,
        scene_id=f"scene.{beat}",
        paragraph_index=0,
        beat_index=0,
        global_beat_index=beat,
    )


def _request(*, taboos: frozenset[str] = frozenset()) -> GenerationRequest:
    identity = BehaviorIdentity(
        character_id="char.hero",
        version=1,
        default_strategies={"conflict": "observe"},
        preferred_channels={"gaze": 0.9, "speech_rhythm": 0.7},
        avoided_channels={"hands": 0.8},
        values={"self_control"},
        taboos=taboos,
        coping_strategies={"observe"},
        social_masks={"public": "courtesy"},
    )
    return GenerationRequest(
        run_id="run.current",
        position=_position(),
        character=CharacterProfile(id="char.hero"),
        behavior_identity=identity,
        scene_state=SceneState(scene_id="scene.2"),
        style_context=StyleContext(
            pov="third_limited", prose_style="restrained", paragraph_function="reaction"
        ),
    )


def _behavior(
    text: str,
    *,
    action: str = "brow_contract",
    unit_id: str = "facial.brow_contract",
) -> ExtractedBehavior:
    return ExtractedBehavior(
        actor_id="char.hero",
        text_span=TextSpan(start=0, end=len(text), text=text),
        canonical_action=action,
        matched_unit_id=unit_id,
        semantic_groups={"brow_tension"},
        channel="facial",
        narrative_functions={"suspicion"},
        syntax_features=SyntaxFeatures(subject_opening="actor", temporal_shape="instant"),
        lexical_lemmas=("皱眉",),
        confidence=0.95,
        evidence_sources={"rule"},
    )


class _Extractor:
    def extract(self, request):
        return ExtractionResult(
            run_id=request.run_id,
            behaviors=(_behavior(request.text, unit_id="facial.brow_tighten"),),
        )


class _ExactExtractor:
    def extract(self, request):
        return ExtractionResult(run_id=request.run_id, behaviors=(_behavior(request.text),))


def _occurrence() -> BehaviorOccurrence:
    text = "他皱眉。"
    behavior = _behavior(text)
    return BehaviorOccurrence(
        occurrence_id="occurrence.previous",
        book_id="book.test",
        position=_position(1, "chapter.1"),
        actor_id="char.hero",
        fingerprint=BehaviorFingerprint(
            unit_id=behavior.matched_unit_id,
            semantic_groups=behavior.semantic_groups,
            channel=behavior.channel,
            narrative_functions=behavior.narrative_functions,
            actor_id=behavior.actor_id,
            syntax_features=behavior.syntax_features,
            lexical_lemmas=behavior.lexical_lemmas,
        ),
        source="extracted",
        text_span=behavior.text_span,
        confidence=behavior.confidence,
        generation_run_id="run.previous",
        accepted_revision=1,
    )


def _snapshot(*, immediate=(), recent=()) -> BehaviorMemorySnapshot:
    return BehaviorMemorySnapshot(
        memory_revision=7,
        immediate=tuple(immediate),
        scene=(),
        chapter=(),
        recent_chapters=tuple(recent),
        volume=tuple(recent),
        book=tuple(recent),
        ensemble=(),
    )


def test_cross_chapter_semantic_repeat_is_located_and_rewriteable() -> None:
    text = "他皱眉。"
    result = GeneratedTextAuditor(_Extractor()).audit(
        AuditContext(request=_request(), history=_snapshot(recent=(_occurrence(),))),
        GeneratedDraft(text=text),
    )

    assert not result.accepted
    assert result.auto_rewrite_allowed
    issue = result.issues[0]
    assert issue.code == "cross_chapter_semantic_repeat"
    assert text[issue.spans[0].start : issue.spans[0].end] == text
    assert issue.evidence["previous_occurrence"] == "occurrence.previous"


def test_immediate_exact_repeat_and_character_taboo_block_automation() -> None:
    text = "他皱眉。"
    result = GeneratedTextAuditor(_ExactExtractor()).audit(
        AuditContext(
            request=_request(taboos=frozenset({"brow_contract"})),
            history=_snapshot(immediate=(_occurrence(),)),
        ),
        text,
    )

    assert not result.accepted
    assert not result.auto_rewrite_allowed
    assert {issue.code for issue in result.issues} >= {
        "character_taboo",
        "exact_history_repeat",
    }
    assert all(issue.severity == "block" for issue in result.issues)


def test_targeted_rewriter_deletes_only_issue_span_and_preserves_dialogue() -> None:
    text = "他皱眉。“我会去。”"
    audit = AuditResult(
        run_id="run.current",
        draft_hash=content_hash(text),
        accepted=False,
        issues=(
            AuditIssue(
                issue_id="issue.repeat",
                severity="rewrite",
                code="cross_chapter_semantic_repeat",
                spans=(SourceSpan(start=0, end=4),),
                preserve={"dialogue", "required_facts", "scene_state"},
            ),
        ),
        metrics=AuditMetrics(semantic_repeat_score=1.0),
        memory_revision=7,
        auto_rewrite_allowed=True,
    )

    result = TargetedRewriter().rewrite(
        RewriteRequest(run_id="run.current", text=text, audit=audit, attempt=1)
    )

    assert result.text == "“我会去。”"
    assert result.changed_spans[0].original.text == "他皱眉。"
    assert "我会去" in result.text
    assert result.rewrite_attempt == 1


def test_default_rewriter_repairs_orphan_subject_before_preserved_dialogue() -> None:
    text = "他握拳。‘好。’"
    audit = AuditResult(
        run_id="run.current",
        draft_hash=content_hash(text),
        accepted=False,
        issues=(
            AuditIssue(
                issue_id="issue.repeat",
                severity="rewrite",
                code="cross_chapter_semantic_repeat",
                spans=(SourceSpan(start=1, end=3),),
                preserve={"dialogue", "required_facts", "scene_state"},
            ),
        ),
        metrics=AuditMetrics(semantic_repeat_score=1.0),
        memory_revision=7,
        auto_rewrite_allowed=True,
    )

    result = TargetedRewriter().rewrite(
        RewriteRequest(run_id="run.current", text=text, audit=audit, attempt=1)
    )

    assert result.text == "他说：‘好。’"
    assert result.preserved_checks.grammar_complete
    assert result.preserved_checks.punctuation_balanced
    assert result.preserved_checks.reference_continuity


def test_default_rewriter_uses_an_explicit_safe_span_replacement() -> None:
    text = "他握拳。"
    audit = AuditResult(
        run_id="run.current",
        draft_hash=content_hash(text),
        accepted=False,
        issues=(
            AuditIssue(
                issue_id="issue.repeat",
                severity="rewrite",
                code="cross_chapter_semantic_repeat",
                spans=(SourceSpan(start=1, end=3),),
                replacement_text="松开手",
            ),
        ),
        metrics=AuditMetrics(semantic_repeat_score=1.0),
        memory_revision=7,
        auto_rewrite_allowed=True,
    )

    result = TargetedRewriter().rewrite(
        RewriteRequest(run_id="run.current", text=text, audit=audit, attempt=1)
    )

    assert result.text == "他松开手。"
    assert result.changed_spans[0].replacement.text == "松开手"


def test_default_rewriter_repairs_clause_punctuation_after_span_deletion() -> None:
    text = "他握拳，又抬头。"
    audit = AuditResult(
        run_id="run.current",
        draft_hash=content_hash(text),
        accepted=False,
        issues=(
            AuditIssue(
                issue_id="issue.repeat",
                severity="rewrite",
                code="cross_chapter_semantic_repeat",
                spans=(SourceSpan(start=1, end=3),),
            ),
        ),
        metrics=AuditMetrics(semantic_repeat_score=1.0),
        memory_revision=7,
        auto_rewrite_allowed=True,
    )

    result = TargetedRewriter().rewrite(
        RewriteRequest(run_id="run.current", text=text, audit=audit, attempt=1)
    )

    assert result.text == "他又抬头。"


def test_default_rewriter_hands_off_when_deletion_leaves_no_safe_predicate() -> None:
    text = "他握拳。"
    audit = AuditResult(
        run_id="run.current",
        draft_hash=content_hash(text),
        accepted=False,
        issues=(
            AuditIssue(
                issue_id="issue.repeat",
                severity="rewrite",
                code="cross_chapter_semantic_repeat",
                spans=(SourceSpan(start=1, end=3),),
            ),
        ),
        metrics=AuditMetrics(semantic_repeat_score=1.0),
        memory_revision=7,
        auto_rewrite_allowed=True,
    )

    with pytest.raises(HumanReviewRequired, match="REWRITE_UNSAFE"):
        TargetedRewriter().rewrite(
            RewriteRequest(run_id="run.current", text=text, audit=audit, attempt=1)
        )


def test_rewriter_hands_off_when_adapter_changes_facts_or_dialogue_order() -> None:
    text = "他握住佩剑。“留下。”“别走。”"
    audit = AuditResult(
        run_id="run.current",
        draft_hash=content_hash(text),
        accepted=False,
        issues=(
            AuditIssue(
                issue_id="issue.repeat",
                severity="rewrite",
                code="cross_chapter_semantic_repeat",
                spans=(SourceSpan(start=1, end=5),),
            ),
        ),
        metrics=AuditMetrics(semantic_repeat_score=1.0),
        memory_revision=7,
        auto_rewrite_allowed=True,
    )

    with pytest.raises(HumanReviewRequired, match="REQUIRED_FACT_PRESERVATION_FAILED"):
        TargetedRewriter(lambda _: "他离开。“留下。”“别走。”").rewrite(
            RewriteContext(request=_request(), required_facts=frozenset({"佩剑"})),
            GeneratedDraft(text=text),
            audit,
        )

    with pytest.raises(HumanReviewRequired, match="DIALOGUE_PRESERVATION_FAILED"):
        TargetedRewriter(lambda _: "他握住佩剑。“别走。”“留下。”").rewrite(
            RewriteRequest(run_id="run.current", text=text, audit=audit, attempt=1)
        )


def test_targeted_rewriter_returns_human_handoff_for_block_or_exhaustion() -> None:
    text = "他皱眉。"
    block = AuditResult(
        run_id="run.current",
        draft_hash=content_hash(text),
        accepted=False,
        issues=(
            AuditIssue(
                issue_id="issue.block",
                severity="block",
                code="character_taboo",
                spans=(SourceSpan(start=0, end=len(text)),),
            ),
        ),
        metrics=AuditMetrics(),
        memory_revision=7,
    )
    with pytest.raises(HumanReviewRequired, match="AUDIT_BLOCKED"):
        TargetedRewriter().rewrite(
            RewriteRequest(run_id="run.current", text=text, audit=block, attempt=1)
        )

    exhausted = block.model_copy(
        update={
            "issues": (
                block.issues[0].model_copy(update={"severity": "rewrite"}),
            ),
            "rewrite_attempts": 2,
        }
    )
    with pytest.raises(HumanReviewRequired, match="REWRITE_EXHAUSTED"):
        TargetedRewriter().rewrite(
            RewriteContext(request=_request()), GeneratedDraft(text=text), exhausted
        )
