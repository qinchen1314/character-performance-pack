from __future__ import annotations

from math import exp, log

from character_performance.continuity import apply_effects, physical_errors, precondition_errors
from character_performance.domain.models import (
    HistoryEntry, Masking, PerformancePlan, PerformanceRequest, RenderContext,
    RenderResult, StateTransition, ValidationReport,
)
from character_performance.emotion import build_emotion
from character_performance.ontology.pack import PerformancePack, digest
from character_performance.scoring import ScoringRules, noise, parameters, score_unit
from character_performance.modifiers import active_modifiers, parameter_modifiers, score_modifiers
from character_performance.storage import SQLiteRepository
from character_performance.world import apply_world, validate_world

VISIBILITY = {"hidden": 0, "very_subtle": 1, "subtle": 2, "noticeable": 3, "obvious": 4, "unknown": -1}


class PerformanceEngine:
    def __init__(self, pack: PerformancePack, repository: SQLiteRepository | None = None, rules: ScoringRules | None = None):
        self.pack = pack
        self.repository = repository or SQLiteRepository()
        self.rules = rules or ScoringRules()

    def plan(self, request: PerformanceRequest) -> PerformancePlan:
        # Revalidation detaches nested containers from caller-owned mutable objects.
        request = PerformanceRequest.model_validate_json(request.model_dump_json())
        self.repository.check_snapshot(request)
        history = self.repository.history(request.scene_state.scene_id, request.character.id)
        plan = self._compose(request, history)
        self.repository.save_plan(request, plan, history)
        return plan

    def _compose(self, request: PerformanceRequest, history: tuple[HistoryEntry, ...]) -> PerformancePlan:
        emotion, warnings = build_emotion(request, self.pack.ontology)
        input_hash = digest(request.model_dump(mode="python"))
        plan_id = "plan." + digest({"input": input_hash, "history": [h.model_dump(mode="python") for h in history], "pack": self.pack.content_hash, "rules": vars(self.rules)})[:32]
        scene, world = request.scene_state, request.world_state
        target = request.relationship.target_id if request.relationship else None
        selected: dict[str, list[str]] = {}
        values, scores, suppressed, decisions = {}, {}, {}, {}
        chosen, surfaces, leaks = [], [], []
        modifiers = active_modifiers(self.pack.modifiers, request)
        if emotion is not None:
            mask = request.masking or Masking(mask_strength=emotion.restraint,
                control_capacity=request.physical_state.motor_control)
            if mask.displayed_emotion != "calm":
                raise ValueError("unsupported displayed emotion; MVP supports calm")
            effective = mask.mask_strength * mask.control_capacity * (1 - request.physical_state.pain)
            masking = effective >= .65
            leak_probability = 1 / (1 + exp(-3 * (emotion.vad.arousal + emotion.intensity + mask.leak_pressure - effective - 1.2)))
            allow_leak = noise(request.seed, "mask.leak") < leak_probability
            candidates = []
            for unit in self.pack.all():
                surface = masking and unit.emotion_affinity.get("calm", 0) > 0
                affinity = max(unit.emotion_affinity.get(emotion.primary, 0), unit.emotion_affinity.get(emotion.secondary, 0) * .65)
                reasons = []
                if unit.status != "active" or unit.id in request.director.disabled_units:
                    reasons.append("disabled")
                if not surface and affinity <= 0:
                    reasons.append("emotion_mismatch")
                if not surface and not unit.intensity_range.min <= emotion.intensity <= unit.intensity_range.max:
                    reasons.append("intensity_range")
                if unit.visibility == "hidden" or VISIBILITY[unit.visibility] > VISIBILITY[request.director.desired_visibility]:
                    reasons.append("visibility_budget")
                if masking and not surface and (VISIBILITY[unit.visibility] > 2 or not allow_leak):
                    reasons.append("mask_strength_high")
                requirements = unit.context_requirements
                if requirements.get("any") and request.context.activity not in requirements["any"]:
                    reasons.append("context")
                if requirements.get("private_only") and request.context.privacy != "private":
                    reasons.append("privacy")
                if request.relationship and request.relationship.public_role_constraints and request.context.privacy == "public" and request.relationship.dominance < 0 and unit.semantics.get("aggression", 0) > .5:
                    reasons.append("public_role_constraint")
                reasons.extend(physical_errors(unit, request))
                reasons.extend(precondition_errors(unit, scene, target))
                world_errors, decision = validate_world(unit, request, emotion, world)
                reasons.extend(world_errors)
                if decision:
                    decisions[unit.id] = decision
                if reasons:
                    suppressed[unit.id] = tuple(reasons)
                    continue
                breakdown = score_unit(unit, request, emotion, history, self.rules, surface)
                breakdown.update(score_modifiers(modifiers, unit))
                scores[unit.id] = breakdown
                total = sum(breakdown.values())
                if total < self.rules.minimum_score:
                    suppressed[unit.id] = ("low_marginal_value_or_repetition",)
                    continue
                # Gumbel sampling is stable per unit and seed, independent of iteration order.
                gumbel = -log(-log(max(1e-12, min(1 - 1e-12, noise(request.seed, "select." + unit.id)))))
                candidates.append((total + self.rules.temperature * gumbel, unit, surface))
            # A surface signal precedes leaks; shortlist one best candidate per channel.
            candidates.sort(key=lambda item: (-int(item[2]), -item[0], item[1].id))
            budget = min(request.director.max_signals, 1 if request.director.beat_importance < .25 else 2 if request.director.beat_importance < .65 else 4 if request.director.beat_importance < .9 else 6)
            budget = max(0, min(request.director.max_signals, budget + sum(m.effects.budget_add.get("total", 0) for m in modifiers)))
            used_channels, used_groups = set(), set()
            for _, unit, surface in candidates:
                reasons = []
                if len(chosen) >= budget:
                    reasons.append("over_budget")
                if unit.channel in used_channels or (unit.category == "world_specific" and selected.get("world_specific")):
                    reasons.append("channel_saturation")
                category_limit = max(0, min(budget, 1 + sum(m.effects.budget_add.get(unit.category, 0) for m in modifiers)))
                if len(selected.get(unit.category, ())) >= category_limit:
                    reasons.append("category_budget")
                if unit.semantic_groups & used_groups:
                    reasons.append("semantic_redundancy")
                if any((unit.render_hints["verb"], unit.render_hints.get("complement", "")) == (previous.render_hints["verb"], previous.render_hints.get("complement", "")) for previous in chosen):
                    reasons.append("phrase_redundancy")
                if any(unit.id in previous.conflicts or previous.id in unit.conflicts for previous in chosen):
                    reasons.append("conflict")
                # A surface and at most one leak keep masked beats restrained.
                if masking and ((surface and surfaces) or (not surface and leaks)):
                    reasons.append("mask_budget")
                if unit.effects and any(previous.effects for previous in chosen):
                    reasons.append("one_state_transition_per_beat")
                reasons.extend(precondition_errors(unit, scene, target))
                world_errors, decision = validate_world(unit, request, emotion, world)
                reasons.extend(world_errors)
                if reasons:
                    suppressed[unit.id] = tuple(reasons)
                    continue
                scene = apply_effects(unit, scene, target)
                world = apply_world(unit, world)
                chosen.append(unit)
                selected.setdefault(unit.category, []).append(unit.id)
                used_channels.add(unit.channel)
                used_groups.update(unit.semantic_groups)
                values[unit.id] = parameter_modifiers(modifiers, parameters(request, emotion, unit, masking and not surface))
                if masking and not surface:
                    values[unit.id]["amplitude"] = min(.2, values[unit.id]["amplitude"])
                if surface:
                    surfaces.append(unit.id)
                elif masking:
                    leaks.append(unit.id)
                if decision:
                    decisions[unit.id] = decision
        if not chosen:
            warnings += ("NO_VALID_CANDIDATE: prose may omit character action",)
        scene = scene.model_copy(update={"revision": scene.revision + 1, "turn_index": scene.turn_index + 1})
        return PerformancePlan(plan_id=plan_id, subject_id=request.character.id,
            target_ids=(target,) if target else (), scene_id=scene.scene_id,
            turn_index=request.scene_state.turn_index, seed=request.seed,
            pack_hash=self.pack.content_hash, pack_version=self.pack.version,
            rule_version=self.rules.version, input_hash=input_hash, emotion_state=emotion,
            primary_signal=chosen[0].id if chosen else None,
            secondary_signals=tuple(u.id for u in chosen[1:]),
            surface_signals=tuple(surfaces), leak_signals=tuple(leaks),
            selected={k: tuple(v) for k, v in selected.items()}, parameters=values,
            state_transition=StateTransition(before=request.scene_state, after=scene,
                world_before=request.world_state, world_after=world),
            suppressed_candidates=suppressed, scores=scores, world_decisions=decisions, warnings=warnings)

    def validate(self, plan: PerformancePlan) -> ValidationReport:
        try:
            request, saved, history = self.repository.load_plan(plan.plan_id)
            recomposed = self._compose(request, history)
            if plan != saved or plan != recomposed:
                return ValidationReport(valid=False, errors=("PLAN_INTEGRITY_OR_VERSION_MISMATCH",))
        except (KeyError, ValueError) as error:
            return ValidationReport(valid=False, errors=(str(error),))
        return ValidationReport(valid=True)

    def render(self, plan: PerformancePlan, context: RenderContext | None = None, renderer=None) -> RenderResult:
        from character_performance.renderer import ChineseNovelRenderer
        report = self.validate(plan)
        if not report.valid:
            raise ValueError(", ".join(report.errors))
        context = context or RenderContext()
        verifier = ChineseNovelRenderer(self.pack)
        result = (renderer or verifier).render(plan, context)
        if not verifier.validate_result(plan, context, result):
            raise ValueError("RENDER_COVERAGE_OR_FACT_VIOLATION")
        self.repository.mark_rendered(plan.plan_id, result)
        return result

    def commit(self, plan_id: str, expected_scene_revision: int):
        _, plan, _ = self.repository.load_plan(plan_id)
        report = self.validate(plan)
        if not report.valid:
            raise ValueError(", ".join(report.errors))
        rendered = self.repository.render_result(plan_id)
        entries = tuple(HistoryEntry(turn_index=plan.turn_index, unit_id=u,
            semantic_groups=self.pack.get(u).semantic_groups, channel=self.pack.get(u).channel,
            intensity=plan.parameters[u]["amplitude"], render_features={
                "grammar": (self.pack.get(u).render_hints["verb"] + self.pack.get(u).render_hints.get("complement", ""),),
                "realized": (rendered.realized_units[u],) if rendered else (),
            }) for u in plan.unit_ids)
        return self.repository.commit(plan, expected_scene_revision, entries)
