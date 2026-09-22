"""Auditing of generated prose against behavior history and character identity.

The auditor is deliberately independent from the prose writer.  It consumes a
structured extraction result and turns every violation into a located,
machine-readable :class:`AuditIssue`; it never mutates memory or rewrites text.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from .domain.behavior_models import (
    AuditIssue,
    AuditMetrics,
    AuditResult,
    BehaviorOccurrence,
    ExtractedBehavior,
    ExtractionRequest,
    ExtractionResult,
    GeneratedDraft,
    GenerationBrief,
    GenerationRequest,
    SourceSpan,
    SyntaxFeatures,
    content_hash,
)
from .memory.repository import BehaviorMemorySnapshot


class BehaviorExtractor(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


class AuditPolicyProtocol(Protocol):
    max_rewrite_attempts: int
    max_visible_signals: int
    max_semantic_group_per_chapter: int
    max_syntax_pattern_per_chapter: int


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    """Thresholds for prose review.

    The defaults are intentionally conservative: continuity and identity
    violations block, while repeat and style findings can be repaired locally.
    """

    max_rewrite_attempts: int = 2
    max_visible_signals: int = 6
    max_semantic_group_per_chapter: int = 2
    max_syntax_pattern_per_chapter: int = 3
    exact_repeat_severity: str = "block"
    unresolved_severity: str = "block"
    cross_chapter_severity: str = "rewrite"
    local_repeat_severity: str = "rewrite"
    character_fit_threshold: float = 0.35


@dataclass(frozen=True, slots=True)
class AuditContext:
    request: GenerationRequest
    brief: GenerationBrief | None = None
    history: BehaviorMemorySnapshot | None = None
    extraction: ExtractionResult | None = None
    required_facts: frozenset[str] = frozenset()
    forbidden_facts: frozenset[str] = frozenset()
    dialogue_hash: str | None = None
    scene_state_valid: bool = True


def _span(item: ExtractedBehavior) -> SourceSpan:
    return SourceSpan(start=item.text_span.start, end=item.text_span.end)


def _source_span(start: int, end: int) -> SourceSpan:
    return SourceSpan(start=start, end=end)


def _group_overlap(left: ExtractedBehavior, right: BehaviorOccurrence) -> float:
    groups = set(left.semantic_groups)
    other = set(right.fingerprint.semantic_groups)
    return len(groups & other) / max(1, len(groups | other))


def _syntax_key(features: SyntaxFeatures) -> tuple[str, str, bool, str]:
    return (
        features.subject_opening,
        features.temporal_shape,
        features.reset_pattern,
        features.dialogue_position,
    )


class GeneratedTextAuditor:
    """Review extracted behavior without changing the draft or memory."""

    def __init__(
        self,
        extractor: BehaviorExtractor,
        *,
        policy: AuditPolicy | None = None,
        memory: Any | None = None,
        pack: Any | None = None,
    ) -> None:
        self.extractor = extractor
        self.policy = policy or AuditPolicy()
        self.memory = memory
        self.pack = pack

    def extract(self, context: AuditContext, draft: GeneratedDraft) -> ExtractionResult:
        request = ExtractionRequest(
            run_id=context.request.run_id,
            text=draft.text,
            known_characters=(context.request.character,),
            position=context.request.position,
            scene_facts=frozenset(context.request.context.facts),
            candidate_behaviors=context.brief.candidate_behaviors if context.brief else (),
        )
        result = self.extractor.extract(request)
        request.validate_result(result)
        return result

    def audit(
        self,
        context: AuditContext | GenerationRequest,
        draft: GeneratedDraft | str,
        *,
        rewrite_attempts: int = 0,
        history: BehaviorMemorySnapshot | None = None,
        brief: GenerationBrief | None = None,
        extraction: ExtractionResult | None = None,
        return_extraction: bool = False,
    ) -> AuditResult | tuple[AuditResult, ExtractionResult]:
        if isinstance(draft, str):
            draft = GeneratedDraft(text=draft)
        if history is None and isinstance(self.memory, BehaviorMemorySnapshot):
            history = self.memory
        if isinstance(context, GenerationRequest):
            if history is None and self.memory is not None and hasattr(self.memory, "query_history"):
                history = self.memory.query_history(context.position, context.character.id)
            context = AuditContext(request=context, brief=brief, history=history, extraction=extraction)
        extraction = context.extraction or self.extract(context, draft)
        issues: list[AuditIssue] = []
        snapshot = context.history
        identity = context.request.behavior_identity

        def add(
            code: str,
            severity: str,
            spans: tuple[SourceSpan, ...],
            *,
            actor_id: str | None = None,
            evidence: dict[str, Any] | None = None,
            preserve: frozenset[str] = frozenset(),
            alternatives: tuple[str, ...] = (),
        ) -> None:
            if not spans:
                return
            digest = sha256(
                f"{context.request.run_id}:{code}:{[(s.start, s.end) for s in spans]}".encode()
            ).hexdigest()[:16]
            issues.append(
                AuditIssue(
                    issue_id=f"issue.{digest}",
                    severity=severity, code=code, spans=spans,
                    actor_id=actor_id, evidence=evidence or {},
                    preserve=preserve, alternatives=alternatives,
                )
            )

        # Extraction failures are unsafe to silently commit.  A completely
        # unresolved result is still allowed for an empty action paragraph only
        # when omission was explicitly permitted by the brief.
        if extraction.unresolved_spans and not (
            context.brief and context.brief.omit_action_allowed and not extraction.behaviors
        ):
            add(
                "extraction_incomplete", self.policy.unresolved_severity,
                tuple(_source_span(s.start, s.end) for s in extraction.unresolved_spans),
                actor_id=context.request.character.id,
                evidence={"unresolved_count": len(extraction.unresolved_spans)},
                preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
            )

        groups: Counter[str] = Counter()
        syntax: Counter[tuple[str, str, bool, str]] = Counter()
        if snapshot:
            for previous in snapshot.chapter:
                groups.update(previous.fingerprint.semantic_groups)
                syntax[_syntax_key(previous.fingerprint.syntax_features)] += 1
        units: defaultdict[str, list[ExtractedBehavior]] = defaultdict(list)
        channels: Counter[str] = Counter()
        for behavior in extraction.behaviors:
            groups.update(behavior.semantic_groups)
            syntax[_syntax_key(behavior.syntax_features)] += 1
            channels[behavior.channel] += 1
            if behavior.matched_unit_id:
                units[behavior.matched_unit_id].append(behavior)

            # Identity taboos are hard constraints; avoided channels and a
            # mismatching strategy are repairable unless explicitly tabooed.
            if behavior.canonical_action in identity.taboos or (
                behavior.matched_unit_id and behavior.matched_unit_id in identity.taboos
            ):
                add(
                    "character_taboo", "block", (_span(behavior),),
                    actor_id=behavior.actor_id,
                    evidence={"action": behavior.canonical_action},
                    preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                )
            avoid_weight = identity.avoided_channels.get(behavior.channel, 0.0)
            if avoid_weight >= self.policy.character_fit_threshold:
                add(
                    "character_channel_deviation", "rewrite", (_span(behavior),),
                    actor_id=behavior.actor_id,
                    evidence={"channel": behavior.channel, "avoidance": avoid_weight},
                    alternatives=tuple(identity.preferred_channels),
                    preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                )
            if context.brief and context.brief.strategy.strategy_id != behavior.strategy_id and behavior.strategy_id:
                add(
                    "strategy_deviation", "rewrite", (_span(behavior),),
                    actor_id=behavior.actor_id,
                    evidence={"expected": context.brief.strategy.strategy_id, "actual": behavior.strategy_id},
                    alternatives=tuple(context.brief.preferred_channels),
                    preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                )
            relationship = context.request.relationship
            override = identity.relationship_overrides.get(relationship.target_id) if relationship else None
            if override and behavior.strategy_id in override.forbidden_strategies:
                add(
                    "relationship_forbidden_strategy", "block", (_span(behavior),),
                    actor_id=behavior.actor_id,
                    evidence={"strategy": behavior.strategy_id, "target_id": relationship.target_id},
                    alternatives=override.preferred_strategies,
                    preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                )
            if override and behavior.channel in override.avoided_channels:
                add(
                    "relationship_channel_deviation", "rewrite", (_span(behavior),),
                    actor_id=behavior.actor_id,
                    evidence={"channel": behavior.channel, "target_id": relationship.target_id},
                    alternatives=override.preferred_channels,
                    preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                )
            if self.pack is not None and behavior.matched_unit_id:
                try:
                    unit = self.pack.get(behavior.matched_unit_id)
                except KeyError:
                    unit = None
                if unit is not None:
                    from .continuity import context_errors, physical_errors, precondition_errors

                    target = relationship.target_id if relationship else None
                    errors = (
                        physical_errors(unit, context.request)
                        + context_errors(unit, context.request)
                        + precondition_errors(unit, context.request.scene_state, target)
                    )
                    if errors:
                        add(
                            "physical_or_continuity_conflict", "block", (_span(behavior),),
                            actor_id=behavior.actor_id,
                            evidence={"unit_id": unit.id, "errors": tuple(errors)},
                            preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                        )

        for unit_id, matches in units.items():
            if len(matches) > 1:
                add(
                    "exact_repeat", self.policy.exact_repeat_severity,
                    tuple(_span(item) for item in matches),
                    actor_id=matches[0].actor_id,
                    evidence={"unit_id": unit_id, "count": len(matches)},
                    alternatives=tuple(c.unit_id for c in (context.brief.candidate_behaviors if context.brief else ())),
                    preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                )

        for group, count in groups.items():
            if count > self.policy.max_semantic_group_per_chapter:
                matching = tuple(_span(item) for item in extraction.behaviors if group in item.semantic_groups)
                add(
                    "chapter_semantic_overuse", self.policy.local_repeat_severity,
                    matching,
                    actor_id=context.request.character.id,
                    evidence={"semantic_group": group, "count": count},
                    alternatives=tuple(c.unit_id for c in (context.brief.candidate_behaviors if context.brief else ())),
                    preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                )
        for key, count in syntax.items():
            if count > self.policy.max_syntax_pattern_per_chapter:
                matching = tuple(_span(item) for item in extraction.behaviors if _syntax_key(item.syntax_features) == key)
                add(
                    "syntax_pattern_overuse", self.policy.local_repeat_severity,
                    matching, actor_id=context.request.character.id,
                    evidence={"syntax": key, "count": count},
                    alternatives=tuple(context.brief.avoid_syntax if context.brief else ()),
                    preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                )

        configured_budget = context.brief.maximum_visible_signals if context.brief else context.request.director.max_signals
        action_budget = min(self.policy.max_visible_signals, configured_budget)
        if len(extraction.behaviors) > action_budget:
            add(
                "action_budget_exceeded", "rewrite",
                tuple(_span(item) for item in extraction.behaviors[action_budget:]),
                actor_id=context.request.character.id,
                evidence={"count": len(extraction.behaviors), "budget": action_budget},
                preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
            )

        # Compare all fingerprint layers with the durable windows.  Exact unit
        # repetition is blocked only in the immediate window; semantic/function
        # repetition across chapters is repairable.
        previous: tuple[BehaviorOccurrence, ...] = ()
        if snapshot:
            previous = snapshot.immediate + snapshot.recent_chapters + snapshot.volume + snapshot.ensemble
        seen_previous: set[str] = set()
        for behavior in extraction.behaviors:
            for old in previous:
                if old.occurrence_id in seen_previous and old not in snapshot.immediate:
                    continue
                if old.occurrence_id in seen_previous:
                    continue
                overlap = _group_overlap(behavior, old)
                same_function = bool(set(behavior.narrative_functions) & set(old.fingerprint.narrative_functions))
                if behavior.matched_unit_id and behavior.matched_unit_id == old.fingerprint.unit_id:
                    severity = "block" if old in (snapshot.immediate if snapshot else ()) else self.policy.cross_chapter_severity
                    add(
                        "exact_history_repeat", severity, (_span(behavior),), actor_id=behavior.actor_id,
                        evidence={"unit_id": behavior.matched_unit_id, "previous_occurrence": old.occurrence_id},
                        alternatives=tuple(c.unit_id for c in (context.brief.candidate_behaviors if context.brief else ())),
                        preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                    )
                    seen_previous.add(old.occurrence_id)
                    break
                if overlap >= 0.5 and same_function and behavior.channel == old.fingerprint.channel:
                    add(
                        "cross_chapter_semantic_repeat", self.policy.cross_chapter_severity, (_span(behavior),),
                        actor_id=behavior.actor_id,
                        evidence={"current_groups": sorted(behavior.semantic_groups), "previous_occurrence": old.occurrence_id, "similarity": round(overlap, 3)},
                        alternatives=tuple(c.unit_id for c in (context.brief.candidate_behaviors if context.brief else ())),
                        preserve=frozenset({"dialogue", "required_facts", "scene_state"}),
                    )
                    break

        # Explicit facts are checked as literal anchors when a caller supplies
        # them.  This is deterministic and lets richer extractors add semantics
        # later without weakening the base gate.
        for fact in context.required_facts:
            if fact not in draft.text and fact not in context.request.context.facts:
                add("required_fact_missing", "block", (_source_span(0, len(draft.text)),), actor_id=context.request.character.id, evidence={"fact": fact}, preserve=frozenset({"dialogue", "scene_state"}))
        for fact in context.forbidden_facts:
            if fact in draft.text:
                start = draft.text.find(fact)
                add("forbidden_fact_introduced", "block", (_source_span(start, start + len(fact)),), actor_id=context.request.character.id, evidence={"fact": fact}, preserve=frozenset({"dialogue", "required_facts", "scene_state"}))
        if not context.scene_state_valid:
            add("scene_state_conflict", "block", (_source_span(0, len(draft.text)),), actor_id=context.request.character.id, preserve=frozenset({"dialogue", "required_facts"}))

        exact = sum(issue.code in {"exact_repeat", "exact_history_repeat"} for issue in issues)
        semantic_values = [float(issue.evidence.get("similarity", 0.0)) for issue in issues if issue.code == "cross_chapter_semantic_repeat"]
        syntax_score = min(1.0, sum(1 for issue in issues if "syntax" in issue.code) / max(1, len(extraction.behaviors)))
        fit_score = max(0.0, 1.0 - sum(1 for issue in issues if "character" in issue.code or "strategy" in issue.code) / max(1, len(extraction.behaviors)))
        actionable = any(item.severity in {"block", "rewrite"} for item in issues)
        has_block = any(item.severity == "block" for item in issues)
        accepted = not actionable
        auto = bool(actionable and not has_block and rewrite_attempts < self.policy.max_rewrite_attempts)
        result = AuditResult(
            run_id=context.request.run_id,
            draft_hash=content_hash(draft.text),
            accepted=accepted,
            issues=tuple(issues),
            metrics=AuditMetrics(
                exact_repeat_count=exact,
                semantic_repeat_score=max(semantic_values, default=0.0),
                character_fit_score=fit_score,
                syntax_pattern_score=syntax_score,
            ),
            memory_revision=snapshot.memory_revision if snapshot else 0,
            auto_rewrite_allowed=auto,
            rewrite_attempts=rewrite_attempts,
        )
        result.validate_draft(draft)
        return (result, extraction) if return_extraction else result

    def audit_with_extraction(
        self,
        context: AuditContext | GenerationRequest,
        draft: GeneratedDraft | str,
        **kwargs: Any,
    ) -> tuple[AuditResult, ExtractionResult]:
        kwargs["return_extraction"] = True
        result = self.audit(context, draft, **kwargs)
        assert isinstance(result, tuple)
        return result


TextAuditor = GeneratedTextAuditor

__all__ = ["AuditContext", "AuditPolicy", "BehaviorExtractor", "GeneratedTextAuditor", "TextAuditor"]
