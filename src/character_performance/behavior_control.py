"""Cross-chapter behavior control orchestration and commit protocol."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .audit import AuditContext, AuditPolicy, GeneratedTextAuditor
from .domain.behavior_models import (
    AcceptedDraft,
    BehaviorFingerprint,
    BehaviorOccurrence,
    CandidateBehavior,
    CommitResult,
    ExtractionRequest,
    ExtractionResult,
    GeneratedDraft,
    GenerationBrief,
    GenerationRequest,
    ReactionStrategyPlan,
)
from .domain.models import SceneState, WorldState
from .memory.repository import BehaviorMemory, BehaviorMemorySnapshot, RunStatus
from .memory.sqlite import SQLiteBehaviorMemory
from .rewrite import HumanReviewRequired, RewriteContext, RewriteResult, TargetedRewriter
from .prompt_brief import PromptBriefBuilder


class ExtractorProtocol(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


class PlannerProtocol(Protocol):
    def plan(self, request: GenerationRequest, history: BehaviorMemorySnapshot) -> GenerationBrief: ...


@dataclass(frozen=True, slots=True)
class RunRecovery:
    run_id: str
    status: RunStatus
    request: GenerationRequest
    brief: GenerationBrief
    draft: GeneratedDraft | None
    audit: Any | None
    extraction: ExtractionResult | None


class _EmptyExtractor:
    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        return ExtractionResult(run_id=request.run_id)


class DefaultBriefPlanner:
    """Small deterministic planner used when a richer strategy module is absent."""

    def __init__(self, pack: Any | None = None) -> None:
        self.pack = pack

    def plan(self, request: GenerationRequest, history: BehaviorMemorySnapshot) -> GenerationBrief:
        activity = request.context.activity
        strategy_id = request.behavior_identity.default_strategies.get(activity)
        if strategy_id is None:
            strategy_id = request.behavior_identity.default_strategies.get("conflict") or next(iter(request.behavior_identity.default_strategies.values()))
        preferred = tuple(sorted(request.behavior_identity.preferred_channels, key=lambda key: (-request.behavior_identity.preferred_channels[key], key)))
        preferred = preferred[: max(1, min(6, request.director.max_signals or 1))]
        if not preferred:
            preferred = ("speech_rhythm",)
        # The domain model requires a non-empty condition and reason.  These
        # labels are explanations, not hidden scoring inputs.
        strategy = ReactionStrategyPlan(
            strategy_id=strategy_id,
            intent=f"{strategy_id}.intent",
            surface_goal="maintain_position",
            private_goal="retain_agency",
            applicability_conditions=frozenset({activity}),
            contraindications=frozenset(request.behavior_identity.taboos),
            preferred_channels=preferred,
            suppressed_channels=frozenset(request.behavior_identity.avoided_channels),
            allowed_visibility=request.director.desired_visibility if request.director.desired_visibility != "unknown" else "subtle",
            action_budget=request.director.max_signals,
            omit_action_allowed=True,
            relationship_meaning="preserve_relationship_boundary",
            reasons=(activity, "history_aware" if history.book else "no_recent_history"),
        )
        overused: list[Any] = []
        recent_groups: dict[str, int] = {}
        for occurrence in history.chapter + history.recent_chapters:
            for group in occurrence.fingerprint.semantic_groups:
                recent_groups[group] = recent_groups.get(group, 0) + 1
        from .domain.behavior_models import OverusedBehavior
        for group, count in sorted(recent_groups.items()):
            if count >= 2:
                overused.append(OverusedBehavior(semantic_group=group, severity="block", reason="recent semantic family overused"))
        candidates: list[CandidateBehavior] = []
        if self.pack is not None:
            for unit in self.pack.all():
                if unit.channel not in preferred or unit.id in request.director.disabled_units:
                    continue
                if unit.semantic_groups & {item.semantic_group for item in overused}:
                    continue
                candidates.append(CandidateBehavior(unit_id=unit.id, purpose=strategy.private_goal, realization_guidance=unit.description_zh or f"用{unit.channel}承担态度", channel=unit.channel, semantic_groups=unit.semantic_groups))
                if len(candidates) == 3:
                    break
        avoid_syntax = frozenset({"brief_then_release", "body_part_opening"})
        prompt = (
            f"角色行为控制：本段采用“{strategy_id}”策略。优先使用：{ '、'.join(preferred) }。"
            f"最多写 {strategy.action_budget} 个可见信号；若台词已传达态度，可以不补动作。"
        )
        if overused:
            prompt += "近期语义家族已过度使用，避免同义表达。"
        return GenerationBrief(
            run_id=request.run_id, strategy=strategy,
            required_facts=frozenset(request.context.facts),
            recently_overused=tuple(overused), avoid_syntax=avoid_syntax,
            preferred_channels=preferred, candidate_behaviors=tuple(candidates[:3]),
            omit_action_allowed=True,
            maximum_visible_signals=min(request.director.max_signals, strategy.action_budget),
            prompt_fragment=prompt,
            memory_revision=history.memory_revision,
        )


class BehaviorControlSystem:
    """Facade implementing prepare → audit → rewrite → commit."""

    def __init__(
        self,
        pack: Any | None = None,
        repository: BehaviorMemory | None = None,
        extractor: ExtractorProtocol | None = None,
        rewriter: TargetedRewriter | Any | None = None,
        policy: AuditPolicy | None = None,
        planner: PlannerProtocol | None = None,
        brief_builder: PromptBriefBuilder | None = None,
    ) -> None:
        self.pack = pack
        self.repository = repository or SQLiteBehaviorMemory(":memory:")
        self.policy = policy or AuditPolicy()
        if extractor is None:
            from .extraction.rules import RuleBasedBehaviorExtractor
            self.extractor = RuleBasedBehaviorExtractor(pack)
        else:
            self.extractor = extractor
        self.planner = planner
        self.brief_builder = brief_builder or PromptBriefBuilder(pack)
        self.auditor = GeneratedTextAuditor(self.extractor, policy=self.policy, memory=self.repository, pack=pack)
        self.rewriter = rewriter or TargetedRewriter(max_attempts=self.policy.max_rewrite_attempts)
        self._contexts: dict[str, tuple[GenerationRequest, GenerationBrief]] = {}

    def prepare(self, request: GenerationRequest, *, preview: bool = False) -> GenerationBrief:
        request = GenerationRequest.model_validate_json(request.model_dump_json())
        identity = self.repository.load_identity(request.position.book_id, request.character.id)
        if identity is None and not preview:
            # Request identity is explicit input, so persisting it is safe and
            # avoids silently inventing a default personality.
            self.repository.save_identity(request.position.book_id, request.behavior_identity)
        elif identity is not None and identity.character_id != request.behavior_identity.character_id:
            raise ValueError("BEHAVIOR_IDENTITY_MISSING: identity belongs to another character")
        history = self.repository.query_history(request.position, request.character.id)
        if self.planner is None:
            brief = self.brief_builder.build(request, history)
        else:
            planned = self.planner.plan(request, history)
            if isinstance(planned, GenerationBrief):
                brief = planned
            else:
                brief = self.brief_builder.build(request, history, strategy=planned)
        if brief.run_id != request.run_id:
            raise ValueError("RUN_STATE_CONFLICT: planner returned another run")
        self._contexts[request.run_id] = (request, brief)
        if not preview:
            self.repository.create_run(request, brief)
        return brief

    def preview(self, request: GenerationRequest) -> GenerationBrief:
        return self.prepare(request, preview=True)

    def recover(self, run_id: str) -> RunRecovery:
        loader = getattr(self.repository, "load_run", None)
        if loader is None:
            context = self._contexts.get(run_id)
            if context is None:
                raise KeyError(f"unknown run: {run_id}")
            request, brief = context
            return RunRecovery(run_id, self.repository.run_status(run_id), request, brief, None, None, None)
        record = loader(run_id)
        self._contexts[run_id] = (record.request, record.brief)
        return RunRecovery(run_id, record.status, record.request, record.brief, record.draft, record.audit, record.extraction)

    resume = recover

    def _context(self, run_id: str) -> tuple[GenerationRequest, GenerationBrief]:
        if run_id not in self._contexts:
            self.recover(run_id)
        return self._contexts[run_id]

    def audit(self, run_id: str, draft: GeneratedDraft | str):
        request, brief = self._context(run_id)
        if isinstance(draft, str):
            draft = GeneratedDraft(text=draft)
        status = self.repository.run_status(run_id)
        if status is RunStatus.PREPARED:
            self.repository.record_draft(run_id, draft)
        elif status is RunStatus.AUDITED_FAILED:
            raise ValueError("RUN_STATE_CONFLICT: rewrite must precede the next audit")
        elif status is RunStatus.REWRITTEN:
            recorded = self.recover(run_id).draft
            if recorded is None or recorded.text != draft.text:
                raise ValueError("DRAFT_HASH_MISMATCH: audit draft differs from recorded rewrite")
            # Revision is durable coordinator metadata; callers may continue
            # to use the documented GeneratedDraft(text=...) shape.
            draft = recorded
        snapshot = self.repository.query_history(request.position, request.character.id)
        context = AuditContext(
            request=request,
            brief=brief,
            history=snapshot,
            required_facts=frozenset(fact for fact in brief.required_facts if fact in draft.text),
        )
        audit, extraction = self.auditor.audit_with_extraction(context, draft, rewrite_attempts=(draft.revision - 1 if status is RunStatus.REWRITTEN else 0))
        self.repository.record_audit(draft, audit, extraction)
        return audit

    def rewrite(self, run_id: str, draft: GeneratedDraft | str, audit: Any) -> str:
        request, brief = self._context(run_id)
        if isinstance(draft, str):
            draft = GeneratedDraft(text=draft)
        if audit.run_id != run_id:
            raise ValueError("RUN_STATE_CONFLICT: audit belongs to another run")
        result: RewriteResult
        if isinstance(self.rewriter, TargetedRewriter):
            preserved_facts = frozenset(fact for fact in brief.required_facts if fact in draft.text)
            result = self.rewriter.rewrite(RewriteContext(request=request, brief=brief, required_facts=preserved_facts), draft, audit)
        else:
            preserved_facts = frozenset(fact for fact in brief.required_facts if fact in draft.text)
            result = TargetedRewriter(self.rewriter, max_attempts=self.policy.max_rewrite_attempts).rewrite(RewriteContext(request=request, brief=brief, required_facts=preserved_facts), draft, audit)
        self.repository.record_rewrite(run_id, GeneratedDraft(text=result.text, revision=result.rewrite_attempt + 1))
        return result.text

    def commit(
        self,
        run_id: str,
        accepted: AcceptedDraft,
        *,
        scene_state: SceneState | None = None,
        world_state: WorldState | None = None,
        accepted_revision: int = 1,
    ) -> CommitResult:
        request, brief = self._context(run_id)
        recovery = self.recover(run_id)
        if recovery.audit is None or not recovery.audit.accepted:
            raise ValueError("AUDIT_BLOCKED: only an audited-passed draft can be committed")
        extraction = recovery.extraction
        if extraction is None:
            raise ValueError("EXTRACTION_INCOMPLETE: no audited extraction is available")
        occurrences = tuple(
            BehaviorOccurrence(
                occurrence_id=f"occurrence.{run_id}.{index}",
                book_id=request.position.book_id,
                position=request.position,
                actor_id=behavior.actor_id,
                target_ids=behavior.target_ids,
                fingerprint=BehaviorFingerprint(
                    unit_id=behavior.matched_unit_id,
                    semantic_groups=behavior.semantic_groups,
                    channel=behavior.channel,
                    narrative_functions=behavior.narrative_functions,
                    # Preserve the extractor evidence exactly.  Filling an
                    # absent strategy here would make the occurrence differ
                    # from the audited extraction and break atomic commit.
                    strategy_id=behavior.strategy_id,
                    actor_id=behavior.actor_id,
                    target_ids=behavior.target_ids,
                    visibility=brief.strategy.allowed_visibility,
                    amplitude_band="low",
                    syntax_features=behavior.syntax_features,
                    lexical_lemmas=behavior.lexical_lemmas,
                ),
                source="extracted",
                text_span=behavior.text_span,
                confidence=behavior.confidence,
                generation_run_id=run_id,
                accepted_revision=accepted_revision,
            )
            for index, behavior in enumerate(extraction.behaviors)
        )
        return self.repository.commit_accepted(
            run_id, accepted, occurrences, accepted_revision=accepted_revision,
            scene_state=scene_state, world_state=world_state,
        )

    def commit_text(self, run_id: str, text: str, *, scene_state: SceneState | None = None, world_state: WorldState | None = None) -> CommitResult:
        from .domain.behavior_models import content_hash
        recovery = self.recover(run_id)
        if recovery.audit is None:
            raise ValueError("AUDIT_BLOCKED: audit is required before commit")
        accepted = AcceptedDraft(text=text, draft_hash=content_hash(text), memory_revision=recovery.audit.memory_revision)
        return self.commit(run_id, accepted, scene_state=scene_state, world_state=world_state)

    def abandon(self, run_id: str) -> None:
        self.repository.abandon_run(run_id)

    def close(self) -> None:
        close = getattr(self.repository, "close", None)
        if close is not None:
            close()


__all__ = ["BehaviorControlSystem", "DefaultBriefPlanner", "RunRecovery", "HumanReviewRequired"]
