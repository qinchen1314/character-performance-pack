"""Validated, detached pack snapshots; no source-format data reaches the planner."""
from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from character_performance.domain.models import PerformanceUnit
from character_performance.domain.rules import ContextRequirements, PhysicalRequirements, RenderHints, StateEffects, WorldRequirements
from character_performance.ontology.emotion import EmotionOntology, EmotionOntologyDocument
from character_performance.sources.registry import BuildPolicy, LicenseGateError, SourceRegistry
from character_performance.modifiers import Modifier


def canonical(value: Any) -> bytes:
    if isinstance(value, dict):
        value = {key: json.loads(canonical(item)) for key, item in value.items()}
    elif isinstance(value, (set, frozenset)):
        value = sorted(value)
    elif isinstance(value, (tuple, list)):
        value = [json.loads(canonical(item)) for item in value]
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return sha256(canonical(value)).hexdigest()


PRECONDITIONS = {
    "right_hand_free", "left_hand_free", "standing", "seated", "leaning_wall",
    "target_known", "distance_known", "can_approach", "seat_contact", "wall_contact",
    "right_hand_holding", "left_hand_holding",
}
EFFECTS = {"pose", "orientation", "distance_delta", "transfer", "clear_support"}


class PerformancePack:
    version = "0.5.0"
    schema_version = "1.0.0"

    def __init__(self, ontology: EmotionOntology, units: tuple[PerformanceUnit, ...], source_ids: tuple[str, ...], modifiers: tuple[Modifier, ...] = ()):
        self.ontology = ontology
        self._units = {u.id: u.model_copy(deep=True) for u in units}
        if len(self._units) != len(units):
            raise ValueError("duplicate unit ids")
        self.source_ids = tuple(sorted(source_ids))
        self._modifiers = tuple(m.model_copy(deep=True) for m in modifiers)
        if len({m.id for m in modifiers}) != len(modifiers):
            raise ValueError("duplicate modifier ids")
        self._lint()
        self.content_hash = digest(self.payload())

    def get(self, unit_id: str) -> PerformanceUnit:
        return self._units[unit_id].model_copy(deep=True)

    def all(self) -> tuple[PerformanceUnit, ...]:
        return tuple(self.get(key) for key in sorted(self._units))

    @property
    def modifiers(self) -> tuple[Modifier, ...]:
        return tuple(m.model_copy(deep=True) for m in self._modifiers)

    def payload(self) -> dict[str, Any]:
        return {
            "emotions": [e.model_dump(mode="python") for e in self.ontology.all()],
            "units": [u.model_dump(mode="python") for u in self.all()],
            "modifiers": [m.model_dump(mode="python") for m in sorted(self.modifiers, key=lambda m: m.id)],
        }

    def _lint(self) -> None:
        fingerprints: dict[str, str] = {}
        phrases: dict[str, str] = {}
        selectors = {f"channel.{u.channel}" for u in self.all()} | {f"category.{u.category}" for u in self.all()} | {f"semantic.{s}" for u in self.all() for s in u.semantics}
        for modifier in self.modifiers:
            if set(modifier.effects.score_add) - selectors:
                raise ValueError(f"unreachable modifier selector: {modifier.id}")
        for unit in self.all():
            if unit.status == "deprecated":
                if unit.replacement_id is None or unit.replacement_id == unit.id:
                    raise ValueError(f"deprecated unit requires a replacement: {unit.id}")
                replacement = self._units.get(unit.replacement_id)
                if replacement is None or replacement.status != "active":
                    raise ValueError(f"invalid replacement for deprecated unit: {unit.id}")
            elif unit.replacement_id is not None:
                raise ValueError(f"active unit cannot declare a replacement: {unit.id}")
            if unit.invocation == "blocking" and unit.id not in {"navigation.move", "navigation.orient", "navigation.pause", "navigation.resume"}:
                raise ValueError(f"unsupported blocking unit: {unit.id}")
            if unit.id.startswith("navigation."):
                if unit.invocation != "blocking" or unit.category != "spatial" or unit.channel != "spatial" or unit.atomic_action != "navigation_" + unit.id.split(".", 1)[1]:
                    raise ValueError(f"invalid navigation unit contract: {unit.id}")
                if unit.effects or unit.preconditions or unit.world_requirements:
                    raise ValueError(f"navigation state effects are controlled by the route lifecycle: {unit.id}")
            if unit.schema_version != self.schema_version:
                raise ValueError(f"unsupported unit schema: {unit.id}")
            if unit.category == "unknown" or unit.visibility == "unknown" or unit.status == "unknown":
                raise ValueError(f"unresolved production enum: {unit.id}")
            if unit.category == "micro_expression" and (not unit.facial_units or unit.timing is None):
                raise ValueError(f"micro expression requires facial actions and phase timing: {unit.id}")
            for label in unit.emotion_affinity:
                if label != "calm":
                    self.ontology.resolve(label)
            if unit.id in unit.conflicts:
                raise ValueError(f"self conflict: {unit.id}")
            for ref in unit.conflicts | unit.compatible_with:
                if ref not in self._units:
                    raise ValueError(f"unknown conflict/compatibility reference: {unit.id} -> {ref}")
            if set(unit.preconditions) - PRECONDITIONS or set(unit.effects) - EFFECTS:
                raise ValueError(f"unsupported state rule: {unit.id}")
            try:
                PhysicalRequirements.model_validate(unit.physical_requirements)
                ContextRequirements.model_validate(unit.context_requirements)
                StateEffects.model_validate(unit.effects)
                RenderHints.model_validate(unit.render_hints)
                if unit.world_requirements:
                    WorldRequirements.model_validate(unit.world_requirements)
                    rules = unit.world_requirements
                    active = set(rules.get("activate", []))
                    inactive = set(rules.get("deactivate", []))
                    required_active = set(rules.get("requires_active", []))
                    if (active | inactive | required_active) - {rules["capability"]} or active & inactive:
                        raise ValueError("world state changes must match the declared capability")
                    if not inactive <= required_active:
                        raise ValueError("world retraction requires prior activation")
                    if rules["destruction"] > 0 and (rules["min_intensity"] < .7 or rules["cost"] <= 0):
                        raise ValueError("destructive world action needs high intensity and positive resource cost")
                if any(value is None for value in unit.effects.values()):
                    raise ValueError("null state effect")
                predicates = set(unit.preconditions)
                if len(predicates & {"standing", "seated", "leaning_wall"}) > 1:
                    raise ValueError("unreachable pose preconditions")
                for side in ("right", "left"):
                    if {f"{side}_hand_free", f"{side}_hand_holding"} <= predicates:
                        raise ValueError("unreachable hand preconditions")
                required = set()
                if "orientation" in unit.effects:
                    required.add("target_known")
                if "distance_delta" in unit.effects:
                    required.update({"standing", "can_approach" if unit.effects["distance_delta"] < 0 else "distance_known"})
                if unit.effects.get("transfer") == "right_to_left":
                    required.update({"right_hand_holding", "left_hand_free"})
                if unit.effects.get("transfer") == "left_to_right":
                    required.update({"left_hand_holding", "right_hand_free"})
                if unit.effects.get("pose") == "seated":
                    required.update({"standing", "seat_contact"})
                if unit.effects.get("pose") == "leaning_wall":
                    required.update({"standing", "wall_contact"})
                if unit.effects.get("pose") == "standing" and not set(unit.preconditions) & {"seated", "leaning_wall"}:
                    raise ValueError("standing effect needs a declared initial pose")
                if unit.effects.get("pose") == "lying":
                    raise ValueError("lying transition is not implemented")
                if not required <= set(unit.preconditions):
                    raise ValueError(f"effect lacks preconditions: {sorted(required - set(unit.preconditions))}")
            except ValueError as error:
                raise ValueError(f"invalid rule values for {unit.id}: {error}") from error
            if set(unit.physical_requirements) - {"capabilities", "min_mobility", "min_breath", "forbidden_injuries"}:
                raise ValueError(f"unsupported physical requirement: {unit.id}")
            if set(unit.context_requirements) - {"any", "private_only", "required_facts"}:
                raise ValueError(f"unsupported context requirement: {unit.id}")
            if unit.category == "world_specific" and not unit.world_requirements:
                raise ValueError(f"world unit missing rules: {unit.id}")
            if set(unit.world_requirements) - {"min_realm", "min_stage", "capability", "cost", "control", "destruction", "min_intensity", "target_dominance", "requires_active", "activate", "deactivate"}:
                raise ValueError(f"unsupported world rule: {unit.id}")
            if not {"subject", "verb"} <= unit.render_hints.keys():
                raise ValueError(f"missing rendering grammar: {unit.id}")
            if any(token in str(value) for value in unit.render_hints.values() for token in ("{", "}")):
                raise ValueError(f"render hints cannot interpolate facts: {unit.id}")
            phrase = re.sub(r"[\s，。！？、；：‘’“”\"'（）]", "", "".join(unit.render_hints.get(key, "") for key in ("subject", "verb", "complement")))
            if phrase in phrases:
                raise ValueError(f"duplicate realization: {unit.id}, {phrases[phrase]}")
            phrases[phrase] = unit.id
            fingerprint = digest({"category": unit.category, "channel": unit.channel,
                "groups": unit.semantic_groups, "parts": unit.body_parts,
                "preconditions": unit.preconditions, "effects": unit.effects,
                "action": unit.atomic_action})
            if fingerprint in fingerprints:
                raise ValueError(f"semantic duplicate: {unit.id}, {fingerprints[fingerprint]}")
            fingerprints[fingerprint] = unit.id

    @classmethod
    def from_project(cls, root: Path, policy: BuildPolicy | None = None) -> "PerformancePack":
        policy = policy or BuildPolicy(commercial=False, redistribution=False)
        registry = SourceRegistry.from_yaml(root / "data/sources/registry.yaml")
        ontology = EmotionOntology.from_yaml(root / "data/ontology/emotion/emotions.yaml")
        raw = yaml.load((root / "data/ontology/units.yaml").read_text(encoding="utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
        if raw["schema_version"] != "1.0.0":
            raise ValueError("unsupported pack schema")
        units = tuple(PerformanceUnit.model_validate(item) for item in raw["units"])
        sources = {ref for e in ontology.all() for ref in e.source_refs}
        modifier_doc = yaml.load((root / "data/modifiers/rules.yaml").read_text(encoding="utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
        if modifier_doc["schema_version"] != "1.0.0":
            raise ValueError("unsupported modifier schema")
        modifiers = tuple(Modifier.model_validate(m) for m in modifier_doc["modifiers"])
        sources.update(ref for m in modifiers for ref in m.source_refs)
        for unit in units:
            sources.update(unit.source_refs)
            for ref in unit.source_refs:
                if registry.get(ref).usage_mode != unit.license_class:
                    raise LicenseGateError(f"source usage mismatch: {ref} in {unit.id}: {unit.license_class}")
        decision = registry.validate_for_build(tuple(sorted(sources)), policy)
        return cls(ontology, units, decision.approved_source_ids, modifiers)

    @classmethod
    def from_compiled(cls, directory: Path) -> "PerformancePack":
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["schema_version"] != cls.schema_version or manifest["pack_version"] != cls.version:
            raise ValueError("unsupported compiled pack version")
        payload = json.loads((directory / "pack.json").read_text(encoding="utf-8"))
        if digest(payload) != manifest["content_hash"]:
            raise ValueError("pack hash mismatch")
        ontology = EmotionOntology(EmotionOntologyDocument(schema_version=cls.schema_version, emotions=payload["emotions"]))
        from character_performance.sources.registry import SourceRegistryDocument
        registry = SourceRegistry(SourceRegistryDocument(schema_version=manifest["source_registry_version"], sources=manifest["sources"]))
        policy = BuildPolicy(**manifest["build_policy"])
        units = tuple(PerformanceUnit.model_validate(u) for u in payload["units"])
        modifiers = tuple(Modifier.model_validate(m) for m in payload["modifiers"])
        refs = {ref for e in ontology.all() for ref in e.source_refs} | {ref for u in units for ref in u.source_refs} | {ref for m in modifiers for ref in m.source_refs}
        if not refs <= set(manifest["source_ids"]):
            raise ValueError("compiled source manifest is incomplete")
        registry.validate_for_build(tuple(sorted(set(manifest["source_ids"]))), policy)
        for unit in units:
            for ref in unit.source_refs:
                if registry.get(ref).usage_mode != unit.license_class:
                    raise ValueError(f"compiled source usage mismatch: {ref}")
        return cls(ontology, units, tuple(manifest["source_ids"]), modifiers)
