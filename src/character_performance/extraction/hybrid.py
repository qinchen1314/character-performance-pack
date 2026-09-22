"""Rule-first, LLM-supplementing extraction with explicit conflict evidence."""

from __future__ import annotations

from typing import Iterable

from character_performance.domain.behavior_models import (
    ExtractedBehavior,
    ExtractionRequest,
    ExtractionResult,
    TextSpan,
)

from .models import (
    ExtractionConflict,
    ExtractionError,
    ExtractionUnavailable,
    TextBehaviorExtractor,
)
from .rules import RuleBasedBehaviorExtractor


def _same_semantics(left: ExtractedBehavior, right: ExtractedBehavior) -> bool:
    return bool(
        left.actor_id == right.actor_id
        and _span_overlap(left.text_span, right.text_span) >= 0.8
        and left.channel == right.channel
        and left.semantic_groups & right.semantic_groups
    )


def _span_overlap(left: TextSpan, right: TextSpan) -> float:
    intersection = max(0, min(left.end, right.end) - max(left.start, right.start))
    return intersection / max(1, min(left.end - left.start, right.end - right.start))


class HybridBehaviorExtractor:
    """Merge local high-precision evidence with optional LLM recall."""

    def __init__(
        self,
        rule_extractor: RuleBasedBehaviorExtractor | TextBehaviorExtractor | None = None,
        llm_extractor: TextBehaviorExtractor | None = None,
    ) -> None:
        self.rule_extractor = rule_extractor or RuleBasedBehaviorExtractor()
        self.llm_extractor = llm_extractor
        self.conflicts: tuple[ExtractionConflict, ...] = ()
        self.last_error: ExtractionError | None = None

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        rule_result = self.rule_extractor.extract(request)
        llm_result: ExtractionResult | None = None
        self.last_error = None
        if self.llm_extractor is not None:
            try:
                llm_result = self.llm_extractor.extract(request)
            except ExtractionUnavailable as exc:
                # Local rules remain a valid degraded path.  Keep the error
                # observable so a caller can decide whether to escalate.
                self.last_error = exc
            except ExtractionError:
                raise
        if llm_result is None:
            self.conflicts = ()
            return rule_result

        merged: list[ExtractedBehavior] = list(rule_result.behaviors)
        conflicts: list[ExtractionConflict] = []
        for llm_behavior in llm_result.behaviors:
            exact = next(
                (
                    item
                    for item in merged
                    if item.actor_id == llm_behavior.actor_id
                    and _span_overlap(item.text_span, llm_behavior.text_span) >= 0.8
                ),
                None,
            )
            if exact is None:
                merged.append(llm_behavior.model_copy(update={
                    "evidence_sources": frozenset(set(llm_behavior.evidence_sources) | {"llm"}),
                }))
                continue
            if _same_semantics(exact, llm_behavior):
                index = merged.index(exact)
                merged[index] = exact.model_copy(update={
                    "matched_unit_id": exact.matched_unit_id or llm_behavior.matched_unit_id,
                    "strategy_id": exact.strategy_id or llm_behavior.strategy_id,
                    "narrative_functions": frozenset(exact.narrative_functions | llm_behavior.narrative_functions),
                    "semantic_groups": frozenset(exact.semantic_groups | llm_behavior.semantic_groups),
                    "lexical_lemmas": tuple(dict.fromkeys(exact.lexical_lemmas + llm_behavior.lexical_lemmas)),
                    "confidence": max(exact.confidence, llm_behavior.confidence),
                    "evidence_sources": frozenset(set(exact.evidence_sources) | set(llm_behavior.evidence_sources) | {"rule", "llm"}),
                })
                continue
            # A conflict is retained as two lowered-confidence observations;
            # selecting one here would silently erase evidence from an adapter.
            lowered_rule = exact.model_copy(update={
                "confidence": min(exact.confidence, 0.49),
                "evidence_sources": frozenset(set(exact.evidence_sources) | {"rule", "llm"}),
            })
            lowered_llm = llm_behavior.model_copy(update={
                "confidence": min(llm_behavior.confidence, 0.49),
                "evidence_sources": frozenset(set(llm_behavior.evidence_sources) | {"rule", "llm"}),
            })
            index = merged.index(exact)
            merged[index] = lowered_rule
            merged.append(lowered_llm)
            conflicts.append(ExtractionConflict(
                span=exact.text_span,
                actor_id=exact.actor_id,
                rule=exact,
                llm=llm_behavior,
            ))
        self.conflicts = tuple(conflicts)
        unresolved = self._merge_spans(
            span
            for span in (*rule_result.unresolved_spans, *llm_result.unresolved_spans)
            if not any(_span_overlap(span, item.text_span) >= 0.8 for item in merged)
        )
        return ExtractionResult(
            run_id=request.run_id,
            behaviors=tuple(sorted(merged, key=lambda item: (
                item.text_span.start, item.text_span.end, item.actor_id, item.canonical_action
            ))),
            unresolved_spans=unresolved,
        )

    @staticmethod
    def _merge_spans(spans: Iterable[TextSpan]) -> tuple[TextSpan, ...]:
        unique = {(item.start, item.end, item.text): item for item in spans}
        return tuple(unique[key] for key in sorted(unique))


HybridExtractor = HybridBehaviorExtractor

__all__ = ["HybridBehaviorExtractor", "HybridExtractor"]
