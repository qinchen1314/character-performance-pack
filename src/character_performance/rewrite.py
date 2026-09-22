"""Targeted, contract checked rewriting for audit findings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .domain.behavior_models import (
    AuditResult,
    ChangedSpan,
    GeneratedDraft,
    GenerationBrief,
    GenerationRequest,
    PreservationChecks,
    RewriteRequest,
    RewriteResult,
    TextReplacement,
    TextSpan,
    content_hash,
)


class HumanReviewRequired(RuntimeError):
    """Raised when a block issue or exhausted rewrite cannot be automated."""

    def __init__(self, audit: AuditResult, message: str | None = None) -> None:
        self.audit = audit
        super().__init__(message or "REWRITE_EXHAUSTED: human review required")


class RewriteAdapter(Protocol):
    def rewrite(self, request: RewriteRequest) -> RewriteResult | str | dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class RewriteContext:
    request: GenerationRequest
    brief: GenerationBrief | None = None
    required_facts: frozenset[str] = frozenset()
    scene_state_valid: bool = True


def _dialogue_parts(text: str) -> tuple[str, ...]:
    # Support common Chinese and ASCII quote pairs.  Returning the content
    # rather than offsets makes the check robust when a preceding action moves.
    pairs = (("“", "”"), ("‘", "’"), ('"', '"'), ("「", "」"), ("『", "』"))
    found: list[str] = []
    for left, right in pairs:
        start = 0
        while True:
            begin = text.find(left, start)
            if begin < 0:
                break
            end = text.find(right, begin + len(left))
            if end < 0:
                break
            found.append(text[begin + len(left) : end])
            start = end + len(right)
    return tuple(sorted(found))


class TargetedRewriter:
    """Rewrite only issue spans and verify the resulting contract."""

    def __init__(self, adapter: RewriteAdapter | None = None, *, max_attempts: int = 2) -> None:
        if max_attempts < 1 or max_attempts > 2:
            raise ValueError("max_attempts must be between one and two")
        self.adapter = adapter
        self.max_attempts = max_attempts

    def rewrite(
        self,
        context: RewriteContext | RewriteRequest,
        draft: GeneratedDraft | str | None = None,
        audit: AuditResult | None = None,
    ) -> RewriteResult:
        direct_request = isinstance(context, RewriteRequest)
        if direct_request:
            request = context
            context = None
        else:
            if draft is None or audit is None:
                raise TypeError("rewrite requires a draft and audit")
            if isinstance(draft, str):
                draft = GeneratedDraft(text=draft)
            audit.validate_draft(draft)
        if direct_request:
            audit = request.audit
            draft = GeneratedDraft(text=request.text)
        assert audit is not None and draft is not None
        if audit.accepted:
            raise ValueError("RUN_STATE_CONFLICT: accepted draft cannot be rewritten")
        if any(issue.severity == "block" for issue in audit.issues):
            raise HumanReviewRequired(audit, "AUDIT_BLOCKED: blocking issue requires human review")
        attempt = audit.rewrite_attempts + 1
        if attempt > self.max_attempts or attempt > 2:
            raise HumanReviewRequired(audit)
        if not direct_request:
            request = RewriteRequest(run_id=audit.run_id, text=draft.text, audit=audit, attempt=attempt)

        result: RewriteResult | str | dict[str, Any]
        if self.adapter is None:
            result = self._default(request)
        else:
            method = getattr(self.adapter, "rewrite", None)
            if method is None and callable(self.adapter):
                method = self.adapter
            if method is None:
                raise TypeError("rewrite adapter must expose rewrite(request)")
            try:
                result = method(request)
            except TypeError:
                # Small adapters in integrations often accept text and issues.
                result = method(draft.text, audit.issues)
        if isinstance(result, RewriteResult):
            checked = result
        elif isinstance(result, str):
            checked = self._from_text(request, result)
        elif isinstance(result, dict):
            checked = RewriteResult.model_validate(result)
        else:
            raise TypeError("rewrite adapter must return RewriteResult, text, or mapping")
        if context is not None:
            self._verify(context, request, checked)
        else:
            if _dialogue_parts(request.text) != _dialogue_parts(checked.text):
                raise ValueError("DIALOGUE_PRESERVATION_FAILED: rewrite changed dialogue")
        return checked

    def rewrite_text(
        self,
        context: RewriteContext,
        text: str,
        audit: AuditResult,
    ) -> str:
        return self.rewrite(context, GeneratedDraft(text=text), audit).text

    def _default(self, request: RewriteRequest) -> RewriteResult:
        # Deleting the smallest offending span is the safest fallback: it does
        # not invent an action, fact, or emotional interpretation.
        selected: list[tuple[int, int, str, tuple[str, ...]]] = []
        for issue in request.audit.issues:
            if issue.severity != "rewrite":
                continue
            span = min(issue.spans, key=lambda item: (item.end - item.start, item.start))
            replacement = ""
            selected.append((span.start, span.end, replacement, (issue.issue_id,)))
        if not selected:
            raise HumanReviewRequired(request.audit, "REWRITE_EXHAUSTED: no rewrite issue span")
        selected.sort()
        merged: list[tuple[int, int, str, set[str]]] = []
        for start, end, text, ids in selected:
            if merged and start < merged[-1][1]:
                previous = merged[-1]
                merged[-1] = (previous[0], max(previous[1], end), previous[2], previous[3] | set(ids))
            else:
                merged.append((start, end, text, set(ids)))
        changed: list[ChangedSpan] = []
        cursor = 0
        parts: list[str] = []
        for start, end, replacement, ids in merged:
            original = request.text[start:end]
            parts.extend((request.text[cursor:start], replacement))
            cursor = end
            changed.append(
                ChangedSpan(
                    original=TextSpan(start=start, end=end, text=original),
                    replacement=TextReplacement(text=replacement),
                    resolved_issue_ids=tuple(sorted(ids)),
                )
            )
        parts.append(request.text[cursor:])
        text = "".join(parts)
        if not text.strip():
            raise HumanReviewRequired(request.audit, "REWRITE_EXHAUSTED: rewrite removed the complete draft")
        return RewriteResult(
            run_id=request.run_id,
            original_text=request.text,
            text=text,
            changed_spans=tuple(changed),
            requested_issue_ids=tuple(issue.issue_id for issue in request.audit.issues if issue.severity == "rewrite"),
            preserved_checks=PreservationChecks(
                dialogue_hash=content_hash("\u0000".join(_dialogue_parts(request.text))),
                required_facts=True,
                scene_state=True,
            ),
            rewrite_attempt=request.attempt,
        )

    def _from_text(self, request: RewriteRequest, text: str) -> RewriteResult:
        if not text or text == request.text:
            raise ValueError("rewrite adapter must change the text")
        # A plain-text adapter is accepted only when its changed region can be
        # located by a deterministic prefix/suffix diff.
        prefix = 0
        while prefix < len(request.text) and prefix < len(text) and request.text[prefix] == text[prefix]:
            prefix += 1
        suffix = 0
        while suffix < len(request.text) - prefix and suffix < len(text) - prefix and request.text[-1 - suffix] == text[-1 - suffix]:
            suffix += 1
        end = len(request.text) - suffix
        replacement = text[prefix : len(text) - suffix if suffix else len(text)]
        if end <= prefix:
            # Pure insertion has no non-empty source span.  Expand the diff
            # by one code point so it can still satisfy TextSpan's invariant.
            if prefix >= len(request.text):
                prefix = max(0, len(request.text) - 1)
                end = len(request.text)
                replacement = request.text[prefix:] + text[len(request.text):]
            else:
                end = min(len(request.text), prefix + 1)
                replacement = text[: len(text) - suffix if suffix else len(text)] + request.text[prefix:end]
        issue_ids = tuple(issue.issue_id for issue in request.audit.issues if any(s.start <= prefix < s.end or s.start == prefix for s in issue.spans))
        if not issue_ids:
            issue_ids = tuple(issue.issue_id for issue in request.audit.issues if issue.severity == "rewrite")
        return RewriteResult(
            run_id=request.run_id,
            original_text=request.text,
            text=text,
            changed_spans=(ChangedSpan(original=TextSpan(start=prefix, end=end, text=request.text[prefix:end]), replacement=TextReplacement(text=replacement), resolved_issue_ids=issue_ids),),
            requested_issue_ids=tuple(issue.issue_id for issue in request.audit.issues if issue.severity == "rewrite"),
            preserved_checks=PreservationChecks(dialogue_hash=content_hash("\u0000".join(_dialogue_parts(request.text))), required_facts=True, scene_state=True),
            rewrite_attempt=request.attempt,
        )

    def _verify(self, context: RewriteContext, request: RewriteRequest, result: RewriteResult) -> None:
        if result.run_id != request.run_id or result.original_text != request.text:
            raise ValueError("RUN_STATE_CONFLICT: rewrite result is bound to another draft")
        if result.rewrite_attempt != request.attempt:
            raise ValueError("RUN_STATE_CONFLICT: invalid rewrite attempt")
        before_dialogue = _dialogue_parts(request.text)
        after_dialogue = _dialogue_parts(result.text)
        if before_dialogue != after_dialogue:
            raise ValueError("DIALOGUE_PRESERVATION_FAILED: rewrite changed dialogue")
        if any(fact not in result.text for fact in context.required_facts):
            raise ValueError("REQUIRED_FACT_PRESERVATION_FAILED: rewrite removed a required fact")
        if not context.scene_state_valid:
            raise ValueError("SCENE_STATE_PRESERVATION_FAILED: scene state is already invalid")
        if result.preserved_checks.dialogue_hash != content_hash("\u0000".join(before_dialogue)):
            raise ValueError("DIALOGUE_PRESERVATION_FAILED: dialogue hash mismatch")
        if not result.preserved_checks.required_facts or not result.preserved_checks.scene_state:
            raise ValueError("REWRITE_CONTRACT_FAILED: preservation checks are false")


LocalRewriter = TargetedRewriter

__all__ = ["HumanReviewRequired", "RewriteAdapter", "RewriteContext", "TargetedRewriter", "LocalRewriter"]
