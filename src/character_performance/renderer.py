"""Constrained Chinese realization; unrestricted model prose is never trusted."""
from __future__ import annotations

import json
from typing import Protocol

from character_performance.domain.models import PerformancePlan, RenderContext, RenderResult
from character_performance.ontology.pack import PerformancePack


class RealizationModel(Protocol):
    def choose(self, payload: dict) -> str:
        """Return JSON {choices: {unit_id: option_index}}; adapter owns I/O timeout."""


class ChineseNovelRenderer:
    def __init__(self, pack: PerformancePack):
        self.pack = pack

    def options(self, plan: PerformancePlan, context: RenderContext) -> dict[str, tuple[str, ...]]:
        if plan.pack_hash != self.pack.content_hash or plan.pack_version != self.pack.version:
            raise ValueError("RENDER_PACK_MISMATCH")
        result = {}
        for unit_id in plan.unit_ids:
            unit = self.pack.get(unit_id)
            hints = unit.render_hints
            subject, verb, complement = hints["subject"], hints["verb"], hints.get("complement", "")
            subject, verb, complement = (fragment.replace("对方", context.target_name) for fragment in (subject, verb, complement))
            amplitude = plan.parameters[unit_id]["amplitude"]
            modifier = "轻轻" if amplitude < .3 and unit.atomic_action in {"hand_clench", "palm_open", "chin_raise", "head_incline", "lip_press"} else ""
            clause = f"{subject}{modifier}{verb}{complement}"
            alternative = hints.get("alternate_verb")
            result[unit_id] = (clause, f"{subject}{modifier}{alternative}{complement}") if alternative else (clause,)
        return result

    def _assemble(self, plan: PerformancePlan, context: RenderContext, choices: dict[str, str], warnings: tuple[str, ...] = ()) -> RenderResult:
        clauses = list(choices.values())
        text = context.subject_name + "，".join(clauses) + "。" if clauses else ""
        if context.dialogue is not None:
            text += f"{context.subject_name}说：“{context.dialogue}”"
        return RenderResult(text=text, realized_units=choices, warnings=warnings)

    def validate_result(self, plan: PerformancePlan, context: RenderContext, result: RenderResult) -> bool:
        options = self.options(plan, context)
        if result.introduced_facts or result.omitted_units or set(result.realized_units) != set(options):
            return False
        if any(value not in options[key] for key, value in result.realized_units.items()):
            return False
        ordered = {key: result.realized_units[key] for key in options}
        return result.text == self._assemble(plan, context, ordered).text

    def render(self, plan: PerformancePlan, context: RenderContext) -> RenderResult:
        options = self.options(plan, context)
        return self._assemble(plan, context, {key: value[0] for key, value in options.items()})


class ConstrainedLLMRenderer(ChineseNovelRenderer):
    def __init__(self, pack: PerformancePack, model: RealizationModel):
        super().__init__(pack)
        self.model = model

    def render(self, plan: PerformancePlan, context: RenderContext) -> RenderResult:
        options = self.options(plan, context)
        try:
            raw = json.loads(self.model.choose({"allowed_realizations": options, "format": {"choices": "unit_id -> integer option index"}}))
            if set(raw) != {"choices"} or set(raw["choices"]) != set(options):
                raise ValueError("unexpected facts or incomplete units")
            choices = {}
            for key, index in raw["choices"].items():
                if type(index) is not int or not 0 <= index < len(options[key]):
                    raise ValueError("invalid realization choice")
                choices[key] = options[key][index]
            return self._assemble(plan, context, {key: choices[key] for key in options})
        except Exception as error:
            fallback = super().render(plan, context)
            return fallback.model_copy(update={"warnings": (f"LLM_FALLBACK:{type(error).__name__}",)})
