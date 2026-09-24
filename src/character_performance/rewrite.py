"""Targeted, contract checked rewriting for audit findings."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
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


@dataclass(frozen=True, slots=True)
class _ParsedSceneState:
    positions: frozenset[str]
    departed_positions: frozenset[str]
    poses: frozenset[str]
    held_objects: frozenset[tuple[str, str]]
    released_objects: frozenset[tuple[str, str]]
    injuries: frozenset[str]
    healed_injuries: frozenset[str]
    actor_claims: frozenset[tuple[str, str, str, str]]


_POSE_PATTERNS = {
    "standing": re.compile(r"(?:站着|站立|站在|起身|站起|伫立|立在)"),
    "seated": re.compile(r"(?:坐着|坐下|落座|坐在)"),
    "leaning_wall": re.compile(r"(?:倚着?墙|靠着?墙|背靠着?墙)"),
    "lying": re.compile(r"(?:躺着|躺下|躺在|卧在)"),
}
_POSITION_PATTERN = re.compile(
    r"(?:身处|位于|来到|走到|退到|挪到|站在|坐在|靠在|躺在)"
    r"(?P<value>[a-zA-Z0-9_.\-\u3400-\u9fff]{1,24}?)(?=[，。！？；、]|$)"
)
_DEPARTED_POSITION_PATTERN = re.compile(
    r"(?:离开|走出|退出|远离)"
    r"(?P<value>[a-zA-Z0-9_.\-\u3400-\u9fff]{1,24}?)(?=[，。！？；、]|$)"
)
_HELD_PATTERN = re.compile(
    r"(?P<hand>右手|左手|双手|两手)?\s*(?:正|仍|还)?"
    r"(?:握着|握住|握紧|手持|持着|拿着|提着|捧着|托着|攥着|抱着)"
    r"(?P<object>[a-zA-Z0-9_.\-\u3400-\u9fff]{1,20}?)(?=[，。！？；、]|$)"
)
_RELEASED_OBJECT_PATTERN = re.compile(
    r"(?P<hand>右手|左手|双手|两手)?\s*(?:已经|随即|终于)?"
    r"(?:放下|丢下|松开|扔下|交出)"
    r"(?P<object>[a-zA-Z0-9_.\-\u3400-\u9fff]{1,20}?)(?=[，。！？；、]|$)"
)
_INJURY_PATTERN = re.compile(
    r"(?P<body>左肩|右肩|左膝|右膝|左臂|右臂|左手|右手|左腿|右腿|肩膀|膝盖|手臂|腿|胸口|腹部|后背|背部|头部|额头)"
    r"[^，。！？；]{0,8}?(?P<condition>受伤|伤口|伤势|疼|痛|流血|渗血|骨折|断了)"
)
_HEALED_INJURY_PATTERN = re.compile(
    r"(?P<body>左肩|右肩|左膝|右膝|左臂|右臂|左手|右手|左腿|右腿|肩膀|膝盖|手臂|腿|胸口|腹部|后背|背部|头部|额头)"
    r"[^，。！？；]{0,8}?(?:痊愈|愈合|无伤|不再疼|已经好了)"
)

_TOKEN_ALIASES = {
    "sword": frozenset({"sword", "剑", "佩剑", "长剑"}),
    "cup": frozenset({"cup", "杯", "酒杯", "茶杯"}),
    "book": frozenset({"book", "书", "册", "书册"}),
    "tray": frozenset({"tray", "托盘"}),
    "door": frozenset({"door", "门", "门边", "门口"}),
    "wall": frozenset({"wall", "墙", "墙边"}),
    "hall": frozenset({"hall", "大厅", "堂内"}),
    "left_shoulder": frozenset({"left_shoulder", "左肩"}),
    "right_shoulder": frozenset({"right_shoulder", "右肩"}),
    "left_knee": frozenset({"left_knee", "左膝", "左膝盖"}),
    "right_knee": frozenset({"right_knee", "右膝", "右膝盖"}),
}


def _normalise_token(value: str) -> str:
    return value.strip(" 的着了正仍还一把一柄一个").lower()


def _token_key(value: str) -> str:
    normalized = _normalise_token(value)
    segments = normalized.split(".")
    suffix = segments[-1]
    for key, aliases in _TOKEN_ALIASES.items():
        if normalized in aliases or suffix in aliases or any(alias in normalized for alias in aliases):
            return key
    return suffix


def _actor_before(text: str, start: int) -> str:
    boundary = max(text.rfind(mark, 0, start) for mark in "。！？；\n")
    prefix = text[boundary + 1 : start].strip(" ，、：")
    prefix = re.sub(r"(?:缓缓|慢慢|仍然|依旧|正|还|独自)$", "", prefix)
    pronoun = re.match(r"(他们|她们|它们|自己|他|她|它)", prefix)
    if pronoun:
        return pronoun.group(1)
    prefix = re.split(
        r"(?:咬牙|忍痛|缓缓|慢慢|仍然|依旧|独自|随即|忽然|终于)",
        prefix,
        maxsplit=1,
    )[0].rstrip("的")
    chinese = re.fullmatch(r"([\u3400-\u9fff]{1,8})", prefix)
    if chinese:
        return chinese.group(1)
    identifier = re.match(r"([a-zA-Z][a-zA-Z0-9_.-]*)", prefix)
    return identifier.group(1) if identifier else "<implicit>"


def _parse_scene_state(text: str) -> _ParsedSceneState:
    claims: set[tuple[str, str, str, str]] = set()
    poses: set[str] = set()
    for pose, pattern in _POSE_PATTERNS.items():
        for match in pattern.finditer(text):
            poses.add(pose)
            claims.add((_actor_before(text, match.start()), "pose", "", pose))
    positions: set[str] = set()
    for match in _POSITION_PATTERN.finditer(text):
        value = _token_key(match.group("value"))
        positions.add(value)
        claims.add((_actor_before(text, match.start()), "position", "", value))
    departed: set[str] = set()
    for match in _DEPARTED_POSITION_PATTERN.finditer(text):
        value = _token_key(match.group("value"))
        departed.add(value)
        claims.add(
            (
                _actor_before(text, match.start()),
                "position_departed",
                "",
                value,
            )
        )
    held: set[tuple[str, str]] = set()
    for match in _HELD_PATTERN.finditer(text):
        hand = {"右手": "right_hand", "左手": "left_hand", "双手": "both", "两手": "both"}.get(
            match.group("hand") or "", "unspecified"
        )
        value = _token_key(match.group("object"))
        held.add((hand, value))
        claims.add((_actor_before(text, match.start()), "held", hand, value))
    released: set[tuple[str, str]] = set()
    for match in _RELEASED_OBJECT_PATTERN.finditer(text):
        hand = {"右手": "right_hand", "左手": "left_hand", "双手": "both", "两手": "both"}.get(
            match.group("hand") or "", "unspecified"
        )
        value = _token_key(match.group("object"))
        released.add((hand, value))
        claims.add((_actor_before(text, match.start()), "released", hand, value))
    injuries: set[str] = set()
    for match in _INJURY_PATTERN.finditer(text):
        value = _token_key(match.group("body"))
        injuries.add(value)
        claims.add(
            (
                _actor_before(text, match.start()),
                "injury",
                match.group("condition"),
                value,
            )
        )
    healed_values: set[str] = set()
    for match in _HEALED_INJURY_PATTERN.finditer(text):
        value = _token_key(match.group("body"))
        healed_values.add(value)
        claims.add(
            (
                _actor_before(text, match.start()),
                "injury_healed",
                "",
                value,
            )
        )
    return _ParsedSceneState(
        frozenset(positions),
        frozenset(departed),
        frozenset(poses),
        frozenset(held),
        frozenset(released),
        frozenset(injuries),
        frozenset(healed_values),
        frozenset(claims),
    )


def _hand_matches(claimed: str, expected: str) -> bool:
    return claimed in {expected, "unspecified", "both"} or (
        expected == "both" and claimed in {"left_hand", "right_hand"}
    )


def _fact_preserved(fact: str, text: str, parsed: _ParsedSceneState) -> bool:
    normalized = fact.lower()
    parts = normalized.split(".")
    if parts[0] == "held" and len(parts) >= 3:
        hand = {"right": "right_hand", "left": "left_hand", "both": "both"}.get(parts[1], parts[1])
        expected_object = _token_key(parts[-1])
        return any(_hand_matches(claimed_hand, hand) and value == expected_object for claimed_hand, value in parsed.held_objects)
    pose = parts[-1]
    if pose in _POSE_PATTERNS:
        return pose in parsed.poses
    if parts[0] in {"position", "location"} and len(parts) >= 2:
        return _token_key(parts[-1]) in parsed.positions
    if "injur" in normalized:
        body = normalized.removeprefix("fact.").removesuffix("_injured").removesuffix(".injured")
        return _token_key(body) in parsed.injuries
    if normalized in {"fact.back_against_wall", "body.back_against_wall"}:
        return "leaning_wall" in parsed.poses
    if normalized.endswith(".reachable"):
        object_key = _token_key(parts[-2]) if len(parts) >= 2 else ""
        return object_key in _token_key(text) and re.search(r"(?:触手可及|伸手可及|够得到|可触及)", text) is not None
    # Opaque application-specific facts have no shared grammar.  Preserve
    # their exact marker as a final fallback, never ahead of known structures.
    return fact in text


def detect_required_facts(text: str, facts: frozenset[str]) -> frozenset[str]:
    """Find required facts actually expressed by prose, including symbolic IDs."""

    parsed = _parse_scene_state(text)
    return frozenset(fact for fact in facts if _fact_preserved(fact, text, parsed))


def _scene_state_preserved(context: RewriteContext, before_text: str, after_text: str) -> bool:
    before = _parse_scene_state(before_text)
    after = _parse_scene_state(after_text)
    scene = context.request.scene_state
    expected_position = _token_key(scene.position) if scene.position is not None else None

    # Requiring each actor-bound positive claim to survive prevents both
    # deleting the evidence and swapping otherwise identical state sets
    # between characters.
    if before.actor_claims != after.actor_claims:
        return False

    if before.positions and after.positions and before.positions.isdisjoint(after.positions):
        return False
    if before.positions & after.departed_positions:
        return False
    if after.positions and expected_position is not None and expected_position not in after.positions:
        return False
    if expected_position is not None and expected_position in after.departed_positions:
        return False
    if before.poses and after.poses and before.poses != after.poses:
        return False
    if after.poses and scene.pose != "unknown" and scene.pose not in after.poses:
        return False

    expected_held = {
        hand: {_token_key(value), *(_token_key(tag) for tag in scene.object_tags.get(value, frozenset()))}
        for hand, value in scene.held_objects.items()
    }
    for hand, value in after.held_objects:
        if hand in expected_held and value not in expected_held[hand]:
            return False
        if hand == "both" and expected_held and not any(value in values for values in expected_held.values()):
            return False
    for hand, value in after.released_objects:
        if hand in expected_held and value in expected_held[hand]:
            return False
        if hand in {"both", "unspecified"} and any(value in values for values in expected_held.values()):
            return False
    for before_hand, before_value in before.held_objects:
        if any(
            _hand_matches(hand, before_hand) and value == before_value
            for hand, value in after.released_objects
        ):
            return False
        conflicting = {
            value for hand, value in after.held_objects if _hand_matches(hand, before_hand)
        }
        if conflicting and before_value not in conflicting:
            return False

    expected_injuries = {_token_key(injury.body_part) for injury in context.request.physical_state.injuries}
    if expected_injuries & after.healed_injuries:
        return False
    if before.injuries & after.healed_injuries:
        return False
    return True


@dataclass(frozen=True, slots=True)
class _DialogueNode:
    opener: str
    closer: str
    parts: tuple[str | "_DialogueNode", ...]


_QUOTE_PAIRS = {"“": "”", "‘": "’", "「": "」", "『": "』", '"': '"'}


def _dialogue_document(text: str) -> tuple[str | _DialogueNode, ...]:
    """Parse quotation nesting while retaining top-level narrative slots."""

    def parse_sequence(index: int, closer: str | None) -> tuple[tuple[str | _DialogueNode, ...], int]:
        parts: list[str | _DialogueNode] = []
        literal: list[str] = []

        def flush() -> None:
            if literal:
                parts.append("".join(literal))
                literal.clear()

        while index < len(text):
            character = text[index]
            if closer is not None and character == closer:
                flush()
                return tuple(parts), index + 1
            if character in _QUOTE_PAIRS:
                flush()
                nested_closer = _QUOTE_PAIRS[character]
                nested, index = parse_sequence(index + 1, nested_closer)
                parts.append(_DialogueNode(character, nested_closer, nested))
                continue
            literal.append(character)
            index += 1
        flush()
        if closer is not None:
            raise ValueError("unclosed quotation")
        return tuple(parts), index

    document, _ = parse_sequence(0, None)
    return document


def _dialogue_signature(text: str) -> tuple[object, ...]:
    """Return ordered dialogue trees, retaining splits and nested quotes."""

    def node_signature(node: _DialogueNode) -> tuple[object, ...]:
        return (
            "quote",
            node.opener,
            node.closer,
            tuple(
                ("text", part) if isinstance(part, str) else node_signature(part)
                for part in node.parts
            ),
        )

    return tuple(
        node_signature(part)
        for part in _dialogue_document(text)
        if isinstance(part, _DialogueNode)
    )


def _dialogue_parts(text: str) -> tuple[str, ...]:
    """Flatten dialogue trees for the backwards-compatible dialogue hash."""

    values: list[str] = []

    def visit(node: _DialogueNode) -> None:
        values.append("".join(part for part in node.parts if isinstance(part, str)))
        for part in node.parts:
            if isinstance(part, _DialogueNode):
                visit(part)

    for part in _dialogue_document(text):
        if isinstance(part, _DialogueNode):
            visit(part)
    return tuple(values)


def _top_level_quote_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    for index, character in enumerate(text):
        if stack and character == stack[-1][0]:
            _, start = stack.pop()
            if not stack:
                spans.append((start, index + 1))
        elif character in _QUOTE_PAIRS:
            stack.append((_QUOTE_PAIRS[character], index))
    if stack:
        raise ValueError("unclosed quotation")
    return tuple(spans)


def _narrative_slots(text: str) -> tuple[str, ...]:
    spans = _top_level_quote_spans(text)
    cursor = 0
    slots: list[str] = []
    for start, end in spans:
        slots.append(re.sub(r"[\W_]+", "", text[cursor:start]))
        cursor = end
    slots.append(re.sub(r"[\W_]+", "", text[cursor:]))
    return tuple(slots)


_PRONOUN_SUBJECT_SOURCE = r"(?:他们|她们|它们|自己|他|她|它)"
_QUOTE_OPENERS = "“‘「『\""
_PRONOUN_PATTERN = re.compile(_PRONOUN_SUBJECT_SOURCE)


@dataclass(frozen=True, slots=True)
class _TextIntegrity:
    grammar_complete: bool
    punctuation_balanced: bool
    reference_continuity: bool

    @property
    def safe(self) -> bool:
        return all(
            (
                self.grammar_complete,
                self.punctuation_balanced,
                self.reference_continuity,
            )
        )

    def preservation_checks(
        self,
        original_text: str,
        *,
        required_facts: bool = True,
        scene_state: bool = True,
    ) -> PreservationChecks:
        return PreservationChecks(
            dialogue_hash=content_hash("\u0000".join(_dialogue_parts(original_text))),
            required_facts=required_facts,
            scene_state=scene_state,
            grammar_complete=self.grammar_complete,
            punctuation_balanced=self.punctuation_balanced,
            reference_continuity=self.reference_continuity,
        )


def _provisional_preservation_checks(original_text: str) -> PreservationChecks:
    """Build schema-valid placeholders that are replaced before returning."""

    return PreservationChecks(
        dialogue_hash=content_hash("\u0000".join(_dialogue_parts(original_text))),
        required_facts=True,
        scene_state=True,
        grammar_complete=True,
        punctuation_balanced=True,
        reference_continuity=True,
    )


def _quotes_balanced(text: str) -> bool:
    pairs = {"“": "”", "‘": "’", "「": "」", "『": "』"}
    closing = {right: left for left, right in pairs.items()}
    stack: list[str] = []
    for character in text:
        if character == '"':
            if stack and stack[-1] == character:
                stack.pop()
            else:
                stack.append(character)
        elif character in pairs:
            stack.append(character)
        elif character in closing:
            if not stack or stack[-1] != closing[character]:
                return False
            stack.pop()
    return not stack


def _grammar_complete(text: str) -> bool:
    orphan = re.compile(rf"(?:^|[。！？；\n])\s*{_PRONOUN_SUBJECT_SOURCE}\s*[。！？；]")
    broken_clause = re.compile(rf"(?:^|[。！？；\n])\s*{_PRONOUN_SUBJECT_SOURCE}\s*[，、]")
    dangling_function_word = re.compile(
        r"(?:^|[。！？；\n])\s*[\u3400-\u9fff]*[的地得把被向在与和及]\s*[。！？；]"
    )
    return (
        orphan.search(text) is None
        and broken_clause.search(text) is None
        and dangling_function_word.search(text) is None
        and text[-1] in "。！？!?….”’」』\""
    )


def _pronoun_contexts(text: str) -> tuple[tuple[str, str], ...]:
    contexts: list[tuple[str, str]] = []
    boundaries = "。！？；\n"
    for match in _PRONOUN_PATTERN.finditer(text):
        sentence_start = max(text.rfind(mark, 0, match.start()) for mark in boundaries)
        context = text[sentence_start + 1 : match.start()].strip()
        if not context and sentence_start >= 0:
            previous_start = max(
                text.rfind(mark, 0, sentence_start) for mark in boundaries
            )
            context = text[previous_start + 1 : sentence_start].strip()
        contexts.append((match.group(), re.sub(r"\s+", "", context)))
    return tuple(contexts)


def _reference_continuity(text: str, *, original_text: str | None = None) -> bool:
    before_quote = re.compile(
        rf"(?:^|[。！？；\n])\s*{_PRONOUN_SUBJECT_SOURCE}\s*(?=[{_QUOTE_OPENERS}])"
    )
    # A short name/noun phrase stranded as a complete sentence immediately
    # before dialogue is just as unsafe as an orphan pronoun (for example,
    # ``洛寒。‘好。’``).  Do not guess that the fragment is a speaker tag.
    named_fragment_before_quote = re.compile(
        rf"(?:^|[。！？；\n])\s*(?!{_PRONOUN_SUBJECT_SOURCE})[\u3400-\u9fff]{{1,4}}[。！？]\s*(?=[{_QUOTE_OPENERS}])"
    )
    if before_quote.search(text) is not None or named_fragment_before_quote.search(text) is not None:
        return False
    if original_text is not None:
        # A targeted action rewrite must not silently change who a pronoun
        # refers to.  Names/coreference need semantic resolution, so adapters
        # that alter this deterministic signature are handed back to a human.
        before_pronouns = _pronoun_contexts(original_text)
        after_pronouns = _pronoun_contexts(text)
        # Removing an entire action span may also remove its subject, which is
        # safe when no pronoun remains.  A surviving but changed pronoun is a
        # real continuity break (``他`` -> ``她``), so reject that case.
        if before_pronouns and after_pronouns and before_pronouns != after_pronouns:
            return False
    return True


def _integrity_checks(
    text: str,
    *,
    original_text: str | None = None,
) -> _TextIntegrity:
    punctuation_balanced = _quotes_balanced(text) and not re.search(
        r"(?:^|[。！？!?；])\s*[，、：；]", text
    )
    return _TextIntegrity(
        grammar_complete=_grammar_complete(text),
        punctuation_balanced=punctuation_balanced,
        reference_continuity=_reference_continuity(
            text,
            original_text=original_text,
        ),
    )


def _subject_before_span(text: str, start: int) -> bool:
    boundary = max(text.rfind(mark, 0, start) for mark in "。！？；\n")
    return re.fullmatch(
        _PRONOUN_SUBJECT_SOURCE,
        text[boundary + 1 : start].strip(),
    ) is not None


def _require_safe_integrity(request: RewriteRequest, text: str) -> _TextIntegrity:
    integrity = _integrity_checks(text, original_text=request.text)
    if not integrity.safe:
        raise HumanReviewRequired(
            request.audit,
            "REWRITE_UNSAFE: grammar, punctuation, or reference continuity failed",
        )
    return integrity


def _actual_changes_within_issue_spans(request: RewriteRequest, text: str) -> bool:
    """Return whether every source-side edit is contained by one rewrite span.

    Adapter supplied ``changed_spans`` are evidence, not authority.  The
    opcodes are therefore always recomputed from the two complete texts.
    Insertions use the source cursor as their coordinate and may occur at
    either edge of an allowed span.
    """

    allowed = tuple(
        span
        for issue in request.audit.issues
        if issue.severity == "rewrite"
        for span in issue.spans
    )
    for operation, before_start, before_end, _, _ in SequenceMatcher(
        None, request.text, text, autojunk=False
    ).get_opcodes():
        if operation == "equal":
            continue
        if before_start == before_end:
            if not any(span.start <= before_start <= span.end for span in allowed):
                return False
        elif not any(
            span.start <= before_start and before_end <= span.end for span in allowed
        ):
            return False
    return True


def _dialogue_preserved(before: str, after: str) -> bool:
    try:
        if _dialogue_signature(before) != _dialogue_signature(after):
            return False
        before_slots = _narrative_slots(before)
        after_slots = _narrative_slots(after)
        removed_slots = {
            index
            for index, (before_slot, after_slot) in enumerate(zip(before_slots, after_slots))
            if before_slot and not after_slot
        }
        introduced_slots = {
            index
            for index, (before_slot, after_slot) in enumerate(zip(before_slots, after_slots))
            if not before_slot and after_slot
        }
        if introduced_slots:
            return False
        if removed_slots and any(
            before_slots[index] != after_slots[index]
            for index in range(len(before_slots))
            if index not in removed_slots
        ):
            return False
        for before_index, before_slot in enumerate(before_slots):
            if not before_slot:
                continue
            if any(
                after_index != before_index
                and len(before_slot) >= 2
                and before_slot in after_slot
                for after_index, after_slot in enumerate(after_slots)
            ):
                return False
        equal_ranges = tuple(
            (before_start, before_end)
            for operation, before_start, before_end, _, _ in SequenceMatcher(
                None, before, after, autojunk=False
            ).get_opcodes()
            if operation == "equal"
        )
        return all(
            any(equal_start <= start and end <= equal_end for equal_start, equal_end in equal_ranges)
            for start, end in _top_level_quote_spans(before)
        )
    except ValueError:
        return False


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
            # Adapter-owned preservation booleans are deliberately discarded;
            # this boundary recomputes every check from the resulting prose.
            payload = dict(result)
            payload["preserved_checks"] = _provisional_preservation_checks(request.text)
            checked = RewriteResult.model_validate(payload)
        else:
            raise TypeError("rewrite adapter must return RewriteResult, text, or mapping")
        try:
            if checked.run_id != request.run_id or checked.original_text != request.text:
                raise ValueError("RUN_STATE_CONFLICT: rewrite result is bound to another draft")
            if checked.rewrite_attempt != request.attempt:
                raise ValueError("RUN_STATE_CONFLICT: invalid rewrite attempt")
            if not _integrity_checks(
                checked.text, original_text=request.text
            ).reference_continuity:
                raise HumanReviewRequired(
                    audit,
                    "REWRITE_UNSAFE: grammar, punctuation, or reference continuity failed",
                )
            if not _dialogue_preserved(request.text, checked.text):
                raise ValueError("DIALOGUE_PRESERVATION_FAILED: rewrite changed dialogue structure")
            if not _actual_changes_within_issue_spans(request, checked.text):
                raise ValueError("REWRITE_CONTRACT_FAILED: actual diff falls outside allowed spans")
            integrity = _require_safe_integrity(request, checked.text)
            if context is None and self.adapter is not None:
                raise ValueError(
                    "REWRITE_CONTRACT_FAILED: RewriteContext is required to verify Adapter output"
                )
            if context is not None:
                self._verify(context, request, checked)
        except ValueError as exc:
            if str(exc).startswith(
                (
                    "DIALOGUE_PRESERVATION_FAILED",
                    "REQUIRED_FACT_PRESERVATION_FAILED",
                    "SCENE_STATE_PRESERVATION_FAILED",
                    "REWRITE_CONTRACT_FAILED",
                )
            ):
                raise HumanReviewRequired(audit, f"REWRITE_UNSAFE: {exc}") from exc
            raise
        # Preservation flags supplied by an Adapter are never authoritative.
        # Return checks derived by this boundary from the actual output text.
        return checked.model_copy(
            update={"preserved_checks": integrity.preservation_checks(request.text)}
        )

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
            replacement = issue.replacement_text or ""
            end = span.end
            subject_before = _subject_before_span(request.text, span.start)
            if (
                issue.replacement_text is None
                and subject_before
                and request.text[span.start:end].endswith("。")
                and end < len(request.text)
                and request.text[end] in _QUOTE_OPENERS
            ):
                replacement = "说："
            elif (
                issue.replacement_text is None
                and subject_before
                and end < len(request.text) - 1
                and request.text[end] == "。"
                and request.text[end + 1] in _QUOTE_OPENERS
            ):
                replacement = "开口"
            selected.append((span.start, end, replacement, (issue.issue_id,)))
        if not selected:
            raise HumanReviewRequired(request.audit, "REWRITE_EXHAUSTED: no rewrite issue span")
        selected.sort()
        merged: list[tuple[int, int, str, set[str]]] = []
        for start, end, text, ids in selected:
            if merged and start < merged[-1][1]:
                previous = merged[-1]
                same_replacement = (
                    start == previous[0]
                    and end == previous[1]
                    and text == previous[2]
                )
                if (text or previous[2]) and not same_replacement:
                    raise HumanReviewRequired(
                        request.audit,
                        "REWRITE_UNSAFE: conflicting overlapping replacements require human review",
                    )
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
            # Provisional only: ``rewrite`` recomputes these checks after it
            # validates the actual diff against the audit spans.
            preserved_checks=_provisional_preservation_checks(request.text),
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
            preserved_checks=_provisional_preservation_checks(request.text),
            rewrite_attempt=request.attempt,
        )

    def _verify(self, context: RewriteContext, request: RewriteRequest, result: RewriteResult) -> None:
        parsed_after = _parse_scene_state(result.text)
        if any(not _fact_preserved(fact, result.text, parsed_after) for fact in context.required_facts):
            raise ValueError("REQUIRED_FACT_PRESERVATION_FAILED: rewrite removed a required fact")
        if not _scene_state_preserved(context, request.text, result.text):
            raise ValueError("SCENE_STATE_PRESERVATION_FAILED: parsed scene state changed")


LocalRewriter = TargetedRewriter

__all__ = [
    "HumanReviewRequired",
    "RewriteAdapter",
    "RewriteContext",
    "TargetedRewriter",
    "LocalRewriter",
    "detect_required_facts",
]
