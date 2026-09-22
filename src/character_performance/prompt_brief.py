"""Build the small, model-facing behaviour brief used by a writer.

The performance engine owns physical planning and the memory repository owns
durability.  This module is the seam between those two systems and a prose
model: it turns a request plus a *bounded* history snapshot into a validated
``GenerationBrief`` and a compact prompt fragment.  It intentionally never
serialises the complete pack, scores, SQLite identifiers, or the full book
history into the prompt.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, Sequence

from character_performance.domain.behavior_models import (
    BehaviorOccurrence,
    CandidateBehavior,
    GenerationBrief,
    GenerationRequest,
    OverusedBehavior,
    ReactionStrategyPlan,
)
from character_performance.domain.models import PerformanceUnit
from character_performance.continuity import context_errors, physical_errors, precondition_errors
from character_performance.memory.repository import BehaviorMemorySnapshot
from character_performance.ontology.pack import PerformancePack
from character_performance.identity import ReactionStrategyPlanner
from character_performance.repetition import RepetitionPolicy
from character_performance.world import validate_world


class BriefStrategyPlanner(Protocol):
    """A small strategy seam so T3 or an application planner can be injected."""

    def plan(
        self,
        request: GenerationRequest,
        *,
        history: BehaviorMemorySnapshot | None = None,
    ) -> ReactionStrategyPlan: ...


@dataclass(frozen=True, slots=True)
class BriefBuildConfig:
    """Presentation limits, kept separate from selection policy."""

    token_budget: int = 512
    max_candidates: int = 3
    max_overused: int = 8
    max_avoid_syntax: int = 6
    max_required_facts: int = 12
    max_context_items: int = 12
    maximum_visible_signals: int | None = None

    def __post_init__(self) -> None:
        if self.token_budget < 1:
            raise ValueError("token_budget must be positive")
        if not 1 <= self.max_candidates <= 3:
            raise ValueError("max_candidates must be between 1 and 3")
        if self.max_overused < 0 or self.max_avoid_syntax < 0:
            raise ValueError("brief limits must not be negative")
        if self.max_required_facts < 0 or self.max_context_items < 0:
            raise ValueError("context limits must not be negative")


def estimate_prompt_tokens(text: str) -> int:
    """Estimate mixed Chinese/Latin prompt tokens deterministically.

    This is deliberately conservative for Chinese (one token per two code
    points) and accounts for whitespace separated Latin words.  It is a
    budget guard, not a claim about a particular provider tokenizer.
    """

    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk = len(re.findall(r"[^\u3400-\u9fff\s]+", text))
    whitespace = len(re.findall(r"\s+", text))
    return max(1, math.ceil(cjk / 2) + non_cjk + whitespace // 2)


def _all_history(snapshot: BehaviorMemorySnapshot | None) -> tuple[BehaviorOccurrence, ...]:
    if snapshot is None:
        return ()
    # Preserve the snapshot's order while de-duplicating occurrences that are
    # present in more than one window.
    seen: set[str] = set()
    result: list[BehaviorOccurrence] = []
    for window in (
        snapshot.immediate,
        snapshot.scene,
        snapshot.chapter,
        snapshot.recent_chapters,
        snapshot.volume,
        snapshot.book,
        snapshot.ensemble,
    ):
        for occurrence in window:
            if occurrence.occurrence_id not in seen:
                seen.add(occurrence.occurrence_id)
                result.append(occurrence)
    return tuple(result)
def _window(snapshot: BehaviorMemorySnapshot | None, name: str) -> tuple[BehaviorOccurrence, ...]:
    return tuple(getattr(snapshot, name, ())) if snapshot is not None else ()


class PromptBriefBuilder:
    """Create a deterministic, compressed ``GenerationBrief``."""

    def __init__(
        self,
        pack: PerformancePack | None = None,
        *,
        config: BriefBuildConfig | None = None,
        strategy_planner: BriefStrategyPlanner | None = None,
        repetition_policy: RepetitionPolicy | None = None,
    ) -> None:
        self.pack = pack
        self.config = config or BriefBuildConfig()
        self.strategy_planner = strategy_planner or ReactionStrategyPlanner()
        self.repetition_policy = repetition_policy or RepetitionPolicy()

    def build(
        self,
        request: GenerationRequest,
        history: BehaviorMemorySnapshot | None = None,
        *,
        strategy: ReactionStrategyPlan | None = None,
    ) -> GenerationBrief:
        if strategy is None:
            strategy = self.strategy_planner.plan(request, history=history)
        if strategy.strategy_id in request.behavior_identity.taboos:
            raise ValueError("strategy is forbidden by the behavior identity")

        overused = self._overused(history)
        blocked_groups = {item.semantic_group for item in overused if item.severity == "block"}
        avoid_syntax = self._avoid_syntax(history)
        preferred_channels = self._preferred_channels(request, strategy, history)
        candidates = self._candidates(
            request,
            strategy,
            preferred_channels,
            blocked_groups,
            history,
        )
        required_facts = frozenset(
            sorted(request.context.facts)[: self.config.max_required_facts]
        )
        forbidden_facts = frozenset()
        maximum = min(
            strategy.action_budget,
            request.director.max_signals,
            self.config.maximum_visible_signals
            if self.config.maximum_visible_signals is not None
            else strategy.action_budget,
        )
        context = self._compress_context(request, required_facts, preferred_channels)
        prompt = self._prompt_fragment(
            request,
            strategy,
            required_facts,
            forbidden_facts,
            overused,
            avoid_syntax,
            preferred_channels,
            candidates,
            maximum,
        )
        return GenerationBrief(
            run_id=request.run_id,
            strategy=strategy,
            required_facts=required_facts,
            forbidden_facts=forbidden_facts,
            recently_overused=tuple(overused),
            avoid_syntax=frozenset(avoid_syntax),
            preferred_channels=tuple(preferred_channels),
            candidate_behaviors=tuple(candidates),
            omit_action_allowed=strategy.omit_action_allowed,
            maximum_visible_signals=maximum,
            prompt_fragment=prompt,
            memory_revision=history.memory_revision if history is not None else 0,
            token_budget=self.config.token_budget,
            compressed_context=context,
        )

    def _preferred_channels(
        self,
        request: GenerationRequest,
        strategy: ReactionStrategyPlan,
        history: BehaviorMemorySnapshot | None,
    ) -> tuple[str, ...]:
        identity = request.behavior_identity
        saturation: dict[str, int] = {}
        for occurrence in _window(history, "chapter"):
            saturation[occurrence.fingerprint.channel] = saturation.get(occurrence.fingerprint.channel, 0) + 1
        channels = [
            item for item in strategy.preferred_channels
            if item not in strategy.suppressed_channels
            and item not in identity.avoided_channels
        ]
        channels.sort(key=lambda item: (saturation.get(item, 0), -identity.preferred_channels.get(item, 0.0), item))
        return tuple(channels or strategy.preferred_channels or ("speech_rhythm",))

    def _overused(
        self,
        snapshot: BehaviorMemorySnapshot | None,
    ) -> list[OverusedBehavior]:
        result: list[OverusedBehavior] = []
        immediate = _window(snapshot, "immediate")
        chapter = _window(snapshot, "chapter")
        recent = _window(snapshot, "recent_chapters")
        groups: dict[str, int] = {}
        for occurrence in chapter:
            for group in occurrence.fingerprint.semantic_groups:
                groups[group] = groups.get(group, 0) + 1
        for group, count in sorted(groups.items(), key=lambda item: (-item[1], item[0])):
            if count >= 3:
                result.append(OverusedBehavior(
                    semantic_group=group,
                    severity="block",
                    reason="current chapter already uses this semantic family three times",
                ))
            elif count >= 2:
                result.append(OverusedBehavior(
                    semantic_group=group,
                    severity="rewrite",
                    reason="current chapter already uses this semantic family twice",
                ))
        immediate_groups = {
            group for occurrence in immediate for group in occurrence.fingerprint.semantic_groups
        }
        for group in sorted(immediate_groups):
            if not any(item.semantic_group == group for item in result):
                result.append(OverusedBehavior(
                    semantic_group=group,
                    severity="block",
                    reason="semantic family was used in the immediate history window",
                ))
        recent_pairs: dict[tuple[str, str], int] = {}
        for occurrence in recent:
            for function in occurrence.fingerprint.narrative_functions:
                key = (function, occurrence.fingerprint.channel)
                recent_pairs[key] = recent_pairs.get(key, 0) + 1
        for (function, channel), count in sorted(recent_pairs.items()):
            if count >= 2:
                group = f"{function}.{channel}"
                result.append(OverusedBehavior(
                    semantic_group=group,
                    severity="warning" if count == 2 else "rewrite",
                    reason="the same narrative function and channel recur across recent chapters",
                ))
        # A deterministic set-like sort also keeps prompt output stable when
        # the seven windows contain the same occurrence.
        unique: dict[tuple[str, str], OverusedBehavior] = {}
        for item in result:
            unique.setdefault((item.semantic_group, item.severity), item)
        return sorted(unique.values(), key=lambda item: (item.severity, item.semantic_group))[: self.config.max_overused]

    def _avoid_syntax(self, snapshot: BehaviorMemorySnapshot | None) -> list[str]:
        chapter = _window(snapshot, "chapter")
        counts: dict[str, int] = {}
        for occurrence in chapter:
            syntax = occurrence.fingerprint.syntax_features
            values = {
                f"subject_opening.{syntax.subject_opening}",
                f"temporal_shape.{syntax.temporal_shape}",
                "reset_pattern" if syntax.reset_pattern else "no_reset_pattern",
            }
            for value in values:
                counts[value] = counts.get(value, 0) + 1
        return [
            value for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            if count >= 3
        ][: self.config.max_avoid_syntax]

    def _candidates(
        self,
        request: GenerationRequest,
        strategy: ReactionStrategyPlan,
        preferred_channels: Sequence[str],
        blocked_groups: set[str],
        history: BehaviorMemorySnapshot | None,
    ) -> list[CandidateBehavior]:
        if self.pack is None:
            return []
        all_history = _all_history(history)
        recent_units = {
            occurrence.fingerprint.unit_id
            for occurrence in _window(history, "immediate")[-5:]
            if occurrence.fingerprint.unit_id
        }
        group_counts: dict[str, int] = {}
        for occurrence in all_history:
            for group in occurrence.fingerprint.semantic_groups:
                group_counts[group] = group_counts.get(group, 0) + 1
        weights = request.behavior_identity.preferred_channels
        options: list[tuple[float, PerformanceUnit]] = []
        for unit in self.pack.all():
            if unit.status != "active" or unit.id in request.director.disabled_units:
                continue
            if unit.invocation == "blocking":
                continue
            if unit.category == "world_specific":
                if request.emotion_state is None:
                    continue
                world_errors, _ = validate_world(
                    unit,
                    request,
                    request.emotion_state,
                    request.world_state,
                )
                if world_errors:
                    continue
            if unit.channel not in preferred_channels:
                continue
            target_id = request.relationship.target_id if request.relationship else None
            if (
                context_errors(unit, request)
                or physical_errors(unit, request)
                or precondition_errors(unit, request.scene_state, target_id)
            ):
                continue
            groups = set(unit.semantic_groups)
            if groups & blocked_groups or unit.id in recent_units:
                continue
            required = set(unit.context_requirements.get("required_facts", ()))
            if not required <= set(request.context.facts):
                continue
            if self.repetition_policy is not None:
                repetition = self.repetition_policy.score(
                    unit,
                    history or (),
                    position=request.position,
                    identity=request.behavior_identity,
                    actor_id=request.character.id,
                )
                if repetition.hard_block:
                    continue
                repetition_penalty = repetition.total_penalty
            else:
                repetition_penalty = 0.0
            if unit.channel in strategy.suppressed_channels:
                continue
            channel_weight = weights.get(unit.channel, 0.0)
            channel_rank = len(preferred_channels) - preferred_channels.index(unit.channel) if unit.channel in preferred_channels else 0
            score = (
                channel_weight * 3.0
                + channel_rank * 0.25
                + unit.narrative_weight
                - sum(group_counts.get(group, 0) for group in groups) * 0.35
                - repetition_penalty
            )
            options.append((score, unit))
        options.sort(key=lambda item: (-item[0], item[1].id))
        result: list[CandidateBehavior] = []
        used_channels: set[str] = set()
        for _, unit in options:
            if unit.channel in used_channels and len(result) < len(preferred_channels):
                continue
            guidance = unit.description_zh.strip()
            if not guidance:
                rendered = "".join(str(unit.render_hints.get(key, "")) for key in ("subject", "verb", "complement"))
                guidance = rendered.strip() or unit.atomic_action.replace("_", " ")
            result.append(CandidateBehavior(
                unit_id=unit.id,
                purpose=strategy.private_goal,
                realization_guidance=guidance,
                channel=unit.channel,
                semantic_groups=frozenset(unit.semantic_groups),
            ))
            used_channels.add(unit.channel)
            if len(result) >= self.config.max_candidates:
                break
        return result

    def _compress_context(
        self,
        request: GenerationRequest,
        required_facts: Iterable[str],
        preferred_channels: Sequence[str],
    ) -> dict[str, Any]:
        scene = request.scene_state
        return {
            "position": {
                "chapter_id": request.position.chapter_id,
                "scene_id": request.position.scene_id,
                "paragraph_index": request.position.paragraph_index,
                "beat_index": request.position.beat_index,
            },
            "style": {
                "pov": request.style_context.pov,
                "prose_style": request.style_context.prose_style,
                "paragraph_function": request.style_context.paragraph_function,
            },
            "activity": request.context.activity,
            "privacy": request.context.privacy,
            "facts": list(required_facts),
            "constraints": list(request.dialogue_or_plot_constraints[: self.config.max_context_items]),
            "held_objects": dict(scene.held_objects),
            "pose": scene.pose,
            "position_id": scene.position,
            "preferred_channels": list(preferred_channels),
        }

    def _prompt_fragment(
        self,
        request: GenerationRequest,
        strategy: ReactionStrategyPlan,
        required_facts: Iterable[str],
        forbidden_facts: Iterable[str],
        overused: Sequence[OverusedBehavior],
        avoid_syntax: Sequence[str],
        preferred_channels: Sequence[str],
        candidates: Sequence[CandidateBehavior],
        maximum: int,
    ) -> str:
        lines = [
            "角色行为控制：",
            f"- 本段策略：{strategy.strategy_id}；行为目的：{strategy.intent}。",
            f"- 优先使用通道：{', '.join(preferred_channels)}。",
            f"- 最多写 {maximum} 个可见信号；{'可以完全不写动作' if strategy.omit_action_allowed else '必须保留动作信号'}。",
        ]
        facts = list(required_facts)
        if facts:
            lines.append(f"- 必须保持的事实：{', '.join(facts)}。")
        if request.dialogue_or_plot_constraints:
            constraints = request.dialogue_or_plot_constraints[: self.config.max_context_items]
            lines.append(f"- 台词与剧情不可改变项：{'、'.join(constraints)}。")
        forbidden = list(forbidden_facts)
        if forbidden:
            lines.append(f"- 禁止改变的事实：{', '.join(forbidden)}。")
        if overused:
            blocked = "、".join(item.semantic_group for item in overused)
            lines.append(f"- 近期过度使用：{blocked}；本段避免同义表达。")
        if avoid_syntax:
            lines.append(f"- 避免句式模板：{'、'.join(avoid_syntax)}。")
        if candidates:
            lines.append("- 可选行为（按优先级排列）：")
            for item in candidates:
                lines.append(f"  · {item.unit_id}：{item.realization_guidance}")
        if request.behavior_identity.taboos:
            lines.append(f"- 角色禁忌：{'、'.join(sorted(request.behavior_identity.taboos))}。")
        return self._fit_prompt(lines)

    def _fit_prompt(self, lines: Sequence[str]) -> str:
        budget = self.config.token_budget
        result: list[str] = []
        for index, line in enumerate(lines):
            candidate = "\n".join(result + [line])
            if estimate_prompt_tokens(candidate) <= budget:
                result.append(line)
                continue
            if index == 0:
                # The first line is short and required by the model contract;
                # this branch only protects a custom future localisation.
                result.append(line[: max(1, budget * 2)])
            break
        prompt = "\n".join(result).strip()
        if estimate_prompt_tokens(prompt) > budget:
            # Deterministic character-level guard for very small custom
            # budgets.  The normal minimum budget never takes this path.
            prompt = prompt[: max(1, budget * 2)].rstrip("，。；：") + "。"
        while len(prompt) > 1 and estimate_prompt_tokens(prompt) > budget:
            prompt = prompt[:-1].rstrip()
        return prompt


class PythonGenerationBriefAdapter:
    """Application-facing adapter; it accepts validated Python models."""

    def __init__(self, builder: PromptBriefBuilder) -> None:
        self.builder = builder

    def prepare(
        self,
        request: GenerationRequest,
        history: BehaviorMemorySnapshot | None = None,
        *,
        strategy: ReactionStrategyPlan | None = None,
    ) -> GenerationBrief:
        return self.builder.build(request, history, strategy=strategy)


# Short aliases make the seam convenient for integrations while retaining a
# descriptive canonical class name in documentation.
GenerationBriefAdapter = PythonGenerationBriefAdapter
PromptBriefAdapter = PythonGenerationBriefAdapter


__all__ = [
    "BriefBuildConfig",
    "BriefStrategyPlanner",
    "GenerationBriefAdapter",
    "PromptBriefAdapter",
    "PromptBriefBuilder",
    "PythonGenerationBriefAdapter",
    "estimate_prompt_tokens",
]
