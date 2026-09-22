"""Deterministic Chinese prose behaviour extraction.

The rules intentionally describe semantic families rather than one renderer
phrase.  They therefore recognise a free rewrite such as ``指甲陷入掌心``
as hand tension even when the pack's canonical phrase says ``握紧``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from character_performance.domain.behavior_models import (
    BehaviorFingerprint,
    CandidateBehavior,
    ExtractedBehavior,
    ExtractionRequest,
    ExtractionResult,
    SyntaxFeatures,
    TextSpan,
)
from character_performance.ontology.pack import PerformancePack


@dataclass(frozen=True, slots=True)
class _Rule:
    pattern: re.Pattern[str]
    canonical_action: str
    semantic_groups: frozenset[str]
    channel: str
    narrative_functions: frozenset[str]
    unit_hints: tuple[str, ...] = ()
    confidence: float = 0.92
    implicit: bool = False
    priority: int = 50


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_RULES: tuple[_Rule, ...] = (
    _Rule(
        _compile(r"(?:握拳|攥拳|捏拳|拳头一紧)"),
        "hand_clench",
        frozenset({"hand_tension", "restraint_leak"}),
        "hands",
        frozenset({"anger_leak", "self_control_failure"}),
        ("body.hand_clench",),
        confidence=0.9,
        priority=4,
    ),
    _Rule(
        _compile(r"(?:五指|手指|指节|右手|左手|拳头|手掌)[^。！？；\n]{0,12}(?:收拢|收紧|攥紧|握紧|捏紧|攥成拳|扣进|陷入掌心|掐入掌心)"),
        "hand_clench",
        frozenset({"hand_tension", "restraint_leak"}),
        "hands",
        frozenset({"anger_leak", "self_control_failure"}),
        ("body.hand_clench",),
        priority=5,
    ),
    _Rule(
        _compile(r"(?:指甲)[^。！？；\n]{0,10}(?:陷入|掐进|刺入)(?:掌心|肉里|皮肉)"),
        "hand_clench",
        frozenset({"hand_tension", "restraint_leak"}),
        "hands",
        frozenset({"anger_leak", "pain_displacement"}),
        ("body.hand_clench",),
        confidence=0.96,
        priority=4,
    ),
    _Rule(
        _compile(r"(?:眉头|眉心|眉间|眉骨)[^。！？；\n]{0,5}(?:一皱|皱起|紧蹙|拧紧|蹙起|压低)"),
        "brow_contract",
        frozenset({"brow_tension"}),
        "facial",
        frozenset({"anger_leak", "suspicion"}),
        ("facial.brow_contract",),
        priority=6,
    ),
    _Rule(
        _compile(r"(?:皱眉|蹙眉|拧眉)"),
        "brow_contract",
        frozenset({"brow_tension"}),
        "facial",
        frozenset({"anger_leak", "suspicion"}),
        ("facial.brow_contract",),
        confidence=0.9,
        priority=5,
    ),
    _Rule(
        _compile(r"(?:眉头|眉心|眉间)[^。！？；\n]{0,10}(?:松开|舒展开|散开|恢复平静)"),
        "brow_release",
        frozenset({"brow_release", "composure"}),
        "facial",
        frozenset({"self_control_restored"}),
        ("facial.brow_release",),
        priority=7,
    ),
    _Rule(
        _compile(r"(?:移开目光|移开视线|别开目光|别开视线|避开他的目光|垂下眼|垂眸|侧过脸|转开脸)"),
        "gaze_withdrawal",
        frozenset({"gaze_withdrawal", "status_avoidance"}),
        "gaze",
        frozenset({"withdraw", "delay_response", "conceal"}),
        ("gaze.look_away", "gaze.avert"),
        priority=3,
    ),
    _Rule(
        _compile(r"(?:盯着|凝视|直视|看向|望向|抬眼看|抬眸看)[^。！？；\n]{0,12}"),
        "gaze_hold",
        frozenset({"gaze_engagement"}),
        "gaze",
        frozenset({"confrontation", "observe", "connection"}),
        ("gaze.target_answer_seek", "gaze.target_response_hold"),
        priority=20,
    ),
    _Rule(
        _compile(r"(?:深吸一口气|深吸了口气|吸了口气|呼吸停了一拍|呼吸一滞|屏住呼吸|屏息)"),
        "breath_pause",
        frozenset({"breath_pause", "physiological_control"}),
        "breath",
        frozenset({"alarm", "delay_response", "self_control_failure"}),
        ("physiology.breath_pause", "physiology.breath_hold_after_inhale"),
        priority=4,
    ),
    _Rule(
        _compile(r"(?:深呼吸|长长地吸了口气)"),
        "breath_pause",
        frozenset({"breath_pause", "physiological_control"}),
        "breath",
        frozenset({"alarm", "delay_response", "self_control_failure"}),
        ("physiology.breath_pause",),
        confidence=0.88,
        priority=4,
    ),
    _Rule(
        _compile(r"(?:放匀呼吸|缓缓吐气|吐出一口气|呼吸渐渐平稳|平复呼吸)"),
        "breath_regulation",
        frozenset({"breath_regulation"}),
        "breath",
        frozenset({"self_control_restored", "composure"}),
        ("physiology.breath_even", "physiology.breath_release_hold"),
        priority=8,
    ),
    _Rule(
        _compile(r"(?:沉默|默不作声|没有回答|并未回答|不置可否|迟疑(?:了)?(?:片刻|一瞬)|停顿(?:了一下|片刻))"),
        "delay_response",
        frozenset({"response_delay", "deliberate_pause"}),
        "speech_rhythm",
        frozenset({"delay_response", "conceal", "observe"}),
        ("speech.deliberate_pause", "physiology.breath_pause"),
        confidence=0.82,
        implicit=True,
        priority=2,
    ),
    _Rule(
        _compile(r"(?:后退一步|退后半步|向后退|拉开距离|与对方拉开距离|往后撤)"),
        "create_distance",
        frozenset({"spatial_withdrawal", "boundary"}),
        "spatial",
        frozenset({"withdraw", "seek_protection", "boundary_assertion"}),
        ("spatial.step_back", "spatial.distance_increase"),
        priority=9,
    ),
    _Rule(
        _compile(r"(?:走近|逼近|靠近|向前一步|压近)"),
        "close_distance",
        frozenset({"spatial_pressure"}),
        "spatial",
        frozenset({"pressure", "confrontation", "repair_attempt"}),
        ("spatial.step_forward",),
        priority=10,
    ),
)


def _clean_phrase(value: str) -> str:
    return re.sub(r"[\s，。！？、；：‘’“”\"'（）()【】\[\]]", "", value)


class RuleBasedBehaviorExtractor:
    """High precision local extractor with semantic-family fallbacks."""

    def __init__(
        self,
        pack: PerformancePack | None = None,
        *,
        rules: Sequence[_Rule] | None = None,
        aliases: Mapping[str, str | Sequence[str]] | None = None,
    ) -> None:
        self.pack = pack
        self._rules = tuple(rules or _RULES)
        self._unit_ids = {unit.id for unit in pack.all()} if pack is not None else set()
        self._catalog_rules = self._build_catalog_rules(pack)
        self._aliases = dict(aliases or {})

    def _build_catalog_rules(self, pack: PerformancePack | None) -> tuple[_Rule, ...]:
        if pack is None:
            return ()
        result: list[_Rule] = []
        for unit in pack.all():
            phrases: set[str] = set()
            for value in unit.render_hints.values():
                if isinstance(value, str):
                    phrase = _clean_phrase(value)
                    # Very short phrases such as ``看`` are too ambiguous to
                    # be a rule; semantic rules above cover them where safe.
                    if len(phrase) >= 3 and len(phrase) <= 18 and any("\u4e00" <= ch <= "\u9fff" for ch in phrase):
                        phrases.add(phrase)
            if len(unit.description_zh) >= 3 and len(unit.description_zh) <= 18:
                phrases.add(_clean_phrase(unit.description_zh))
            if not phrases:
                continue
            for phrase in phrases:
                groups = frozenset(unit.semantic_groups)
                functions = frozenset({unit.atomic_action})
                canonical = re.sub(r"[^a-z0-9_]+", "_", unit.atomic_action.lower()).strip("_") or "observed_action"
                result.append(_Rule(
                    _compile(re.escape(phrase)),
                    canonical,
                    groups,
                    unit.channel,
                    functions,
                    (unit.id,),
                    confidence=0.94,
                    priority=30,
                ))
        return tuple(result)

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        text = request.text
        aliases = self._character_aliases(request)
        matches: list[tuple[int, int, int, _Rule, re.Match[str]]] = []
        for rule in (*self._rules, *self._catalog_rules):
            for match in rule.pattern.finditer(text):
                matches.append((match.start(), -(match.end() - match.start()), rule.priority, rule, match))
        matches.sort(key=lambda item: (item[0], item[1], item[2], item[3].canonical_action))
        selected: list[tuple[int, int, _Rule, re.Match[str], str | None]] = []
        occupied: list[tuple[int, int]] = []
        ambiguous_spans: list[TextSpan] = []
        last_actor: str | None = None
        for start, _, _, rule, match in matches:
            end = match.end()
            if any(start < right and end > left for left, right in occupied):
                continue
            actor = self._resolve_actor(text, start, request, aliases, last_actor)
            if actor is None:
                ambiguous_spans.append(TextSpan(start=start, end=end, text=text[start:end]))
                continue
            selected.append((start, end, rule, match, actor))
            occupied.append((start, end))
            last_actor = actor
        behaviours: list[ExtractedBehavior] = []
        for start, end, rule, match, actor in selected:
            span = TextSpan(start=start, end=end, text=text[start:end])
            unit_id = self._match_unit(rule.unit_hints)
            target_ids = self._resolve_targets(text, start, end, actor, request, aliases)
            syntax = self._syntax(text, span, request, aliases)
            behaviours.append(ExtractedBehavior(
                actor_id=actor,
                target_ids=target_ids,
                text_span=span,
                canonical_action=rule.canonical_action,
                matched_unit_id=unit_id,
                semantic_groups=rule.semantic_groups,
                channel=rule.channel,
                narrative_functions=rule.narrative_functions,
                syntax_features=syntax,
                lexical_lemmas=self._lemmas(span.text),
                confidence=rule.confidence,
                evidence_sources=frozenset({"rule"}),
            ))
        unresolved = self._unresolved_spans(text, behaviours, ambiguous_spans)
        return ExtractionResult(
            run_id=request.run_id,
            behaviors=tuple(sorted(behaviours, key=lambda item: (item.text_span.start, item.text_span.end, item.actor_id))),
            unresolved_spans=tuple(unresolved),
        )

    def _match_unit(self, hints: Iterable[str]) -> str | None:
        for hint in hints:
            if hint in self._unit_ids or (not self._unit_ids and hint in {
                "body.hand_clench", "facial.brow_contract", "facial.brow_release",
                "gaze.look_away", "gaze.avert", "gaze.target_answer_seek",
                "gaze.target_response_hold", "physiology.breath_pause",
                "physiology.breath_hold_after_inhale", "physiology.breath_even",
                "physiology.breath_release_hold", "speech.deliberate_pause",
                "spatial.step_back", "spatial.distance_increase", "spatial.step_forward",
            }):
                return hint
        return None

    def _character_aliases(self, request: ExtractionRequest) -> dict[str, str]:
        aliases: dict[str, str] = {}
        configured = request.pack_summary.get("character_aliases", {})
        if isinstance(configured, Mapping):
            for key, value in configured.items():
                if isinstance(value, str) and any(item.id == value for item in request.known_characters):
                    aliases[str(key)] = value
                elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    for alias in value:
                        aliases[str(alias)] = str(key)
        for character in request.known_characters:
            cid = character.id
            aliases.setdefault(cid, cid)
            bits = [bit for bit in re.split(r"[._-]", cid) if bit and bit not in {"char", "character"}]
            if bits:
                aliases.setdefault(bits[-1], cid)
                aliases.setdefault("".join(bits), cid)
        return aliases

    def _resolve_actor(
        self,
        text: str,
        start: int,
        request: ExtractionRequest,
        aliases: Mapping[str, str],
        last_actor: str | None,
    ) -> str | None:
        sentence_start = max(text.rfind(mark, 0, start) for mark in "。！？；\n") + 1
        prefix = text[sentence_start:start]
        candidates: list[tuple[int, str]] = []
        for alias, actor in aliases.items():
            index = prefix.rfind(alias)
            if index >= 0:
                candidates.append((index, actor))
        if candidates:
            return max(candidates, key=lambda item: (item[0], len(item[1])))[1]
        if len(request.known_characters) == 1:
            return request.known_characters[0].id
        if last_actor is not None and re.search(r"(?:他|她|其|对方|那人)$", prefix):
            return last_actor
        # A prose sentence beginning with a pronoun is still attributable to
        # the prior actor; otherwise it would be unsafe to guess in a cast.
        if last_actor is not None and not prefix.strip():
            return last_actor
        return None

    def _resolve_targets(
        self,
        text: str,
        start: int,
        end: int,
        actor: str,
        request: ExtractionRequest,
        aliases: Mapping[str, str],
    ) -> tuple[str, ...]:
        context = text[max(0, start - 12) : min(len(text), end + 20)]
        if not re.search(r"(?:向|对|朝|盯着|看向|冲着)", context):
            return ()
        result: list[str] = []
        for alias, candidate in aliases.items():
            if candidate == actor or alias == actor:
                continue
            if alias in context:
                result.append(candidate)
        return tuple(dict.fromkeys(result))

    def _syntax(
        self,
        text: str,
        span: TextSpan,
        request: ExtractionRequest,
        aliases: Mapping[str, str],
    ) -> SyntaxFeatures:
        value = span.text
        if value[:1] in {"他", "她", "其"} or any(value.startswith(alias) for alias in aliases):
            opening = "actor"
        elif value[:1] in "五手指拳眉目眼脸眸呼吸嘴唇下巴肩头":
            opening = "body_part"
        elif value[:1] in "‘“\"『《":
            opening = "dialogue"
        else:
            opening = "other"
        if re.search(r"旋即|随即|转眼|很快|松开|放平|恢复|散开|归位", value):
            temporal = "brief_then_release"
        elif re.search(r"一瞬|一下|片刻|微微|短暂", value):
            temporal = "brief"
        elif re.search(r"一直|始终|仍然|持续", value):
            temporal = "sustained"
        else:
            temporal = "instant"
        sentence_end = min(
            item for item in (text.find(mark, span.end) for mark in "。！？；\n") if item >= 0
        ) if any(text.find(mark, span.end) >= 0 for mark in "。！？；\n") else len(text)
        sentence = text[max(0, max(text.rfind(mark, 0, span.start) for mark in "。！？；\n") + 1) : sentence_end]
        quote_positions = [index for index, char in enumerate(sentence) if char in "‘’“”\"『』"]
        if not quote_positions:
            dialogue_position = "no_dialogue"
        elif span.start - (sentence_end - len(sentence)) < min(quote_positions):
            dialogue_position = "before_dialogue"
        else:
            dialogue_position = "after_dialogue"
        return SyntaxFeatures(
            subject_opening=opening,
            temporal_shape=temporal,
            reset_pattern=bool(re.search(r"松开|放平|恢复|散开|归位|回到原位", value)),
            dialogue_position=dialogue_position,
        )

    @staticmethod
    def _lemmas(text: str) -> tuple[str, ...]:
        chunks = re.findall(r"[\u3400-\u9fff]{1,6}|[A-Za-z_]{2,}", text)
        return tuple(dict.fromkeys(chunk for chunk in chunks if chunk not in {"微微", "一瞬", "一下"}))

    def _unresolved_spans(
        self,
        text: str,
        behaviours: Sequence[ExtractedBehavior],
        ambiguous: Sequence[TextSpan],
    ) -> list[TextSpan]:
        result = list(ambiguous)
        occupied = [(item.text_span.start, item.text_span.end) for item in behaviours]
        offset = 0
        for match in re.finditer(r"[^。！？；\n]+[。！？；\n]?", text):
            value = match.group(0).strip()
            start = match.start() + len(match.group(0)) - len(match.group(0).lstrip())
            end = start + len(value)
            if not value or any(start < right and end > left for left, right in occupied):
                continue
            if re.search(r"握|抬|移|停|沉默|呼吸|笑|皱|咬|退|靠|转身|回头|凝视|盯|望", value):
                result.append(TextSpan(start=start, end=end, text=text[start:end]))
            offset = match.end()
        unique = {(item.start, item.end): item for item in result}
        return [unique[key] for key in sorted(unique)]


# The rule object is intentionally private, but aliases are useful to small
# integrations that used the earlier experimental names.
RuleExtractor = RuleBasedBehaviorExtractor


__all__ = ["RuleBasedBehaviorExtractor", "RuleExtractor"]
