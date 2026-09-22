"""Adapter for an external JSON-capable language model.

No provider SDK is imported here.  Applications pass a callable or a small
client object, which keeps the extraction seam testable and lets the pack run
without network access.
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from character_performance.domain.behavior_models import ExtractionRequest, ExtractionResult

from .models import (
    ExtractionFormatError,
    ExtractionUnavailable,
    TextBehaviorExtractor,
    parse_adapter_payload,
)


class JsonLLMClient(Protocol):
    def generate_json(self, prompt: str) -> Any: ...


def _json_text(value: Any) -> Any:
    if isinstance(value, (Mapping, ExtractionResult)):
        return value
    if hasattr(value, "text") and isinstance(value.text, str):
        value = value.text
    elif hasattr(value, "content") and isinstance(value.content, str):
        value = value.content
    if not isinstance(value, str):
        return value
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Some gateways prepend a short explanation.  Restrict recovery to a
        # single outer JSON object and still validate it strictly afterwards.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ExtractionFormatError("LLM response is not valid JSON")
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ExtractionFormatError(f"LLM response is not valid JSON: {exc}") from exc


class LLMBehaviorExtractor:
    """Call an injected JSON model and validate every returned span."""

    def __init__(
        self,
        client: JsonLLMClient | Callable[..., Any] | None,
        *,
        system_prompt: str | None = None,
    ) -> None:
        self.client = client
        self.system_prompt = system_prompt or (
            "你是小说正文行为抽取器。只返回 JSON，不要解释。识别正文中实际出现的动作，"
            "包含隐含的停顿/回避/未回答；不能凭空补写正文没有的动作。每个 text_span 必须"
            "使用 Python Unicode code point 偏移，并逐字复制原文。"
        )

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        if self.client is None:
            raise ExtractionUnavailable("LLM behavior extractor is not configured")
        prompt = self._prompt(request)
        payload = self._invoke(request, prompt)
        result = parse_adapter_payload(_json_text(payload), request=request)
        # The adapter is the source of this evidence even when a gateway
        # omitted the optional evidence_sources field.
        return result.model_copy(update={
            "behaviors": tuple(item.model_copy(update={
                "evidence_sources": frozenset(set(item.evidence_sources) | {"llm"}),
            }) for item in result.behaviors)
        })

    def _invoke(self, request: ExtractionRequest, prompt: str) -> Any:
        client = self.client
        try:
            if hasattr(client, "generate_json"):
                return client.generate_json(prompt)  # type: ignore[attr-defined]
            if hasattr(client, "complete"):
                return client.complete(prompt)  # type: ignore[attr-defined]
            if hasattr(client, "invoke"):
                return client.invoke(prompt)  # type: ignore[attr-defined]
            if hasattr(client, "extract"):
                return client.extract(request)  # type: ignore[attr-defined]
            if callable(client):
                try:
                    signature = inspect.signature(client)
                    names = [item.name.lower() for item in signature.parameters.values()]
                except (TypeError, ValueError):
                    names = []
                if names and any("request" in name for name in names):
                    return client(request)
                return client(prompt)
        except ExtractionUnavailable:
            raise
        except Exception as exc:
            raise ExtractionUnavailable(f"LLM behavior extractor failed: {exc}") from exc
        raise ExtractionUnavailable("configured LLM client has no supported JSON method")

    def _prompt(self, request: ExtractionRequest) -> str:
        characters = [item.id for item in request.known_characters]
        candidates = [item.model_dump(mode="json") for item in request.candidate_behaviors]
        schema = {
            "run_id": request.run_id,
            "behaviors": [
                {
                    "actor_id": "known character id",
                    "target_ids": [],
                    "text_span": {"start": 0, "end": 1, "text": "原文片段"},
                    "canonical_action": "snake_case_action",
                    "matched_unit_id": None,
                    "semantic_groups": ["semantic_group"],
                    "channel": "gaze|hands|facial|breath|speech_rhythm|spatial|other",
                    "narrative_functions": ["narrative_function"],
                    "strategy_id": None,
                    "syntax_features": {
                        "subject_opening": "actor|body_part|object|environment|dialogue|other|unknown",
                        "temporal_shape": "instant",
                        "reset_pattern": False,
                        "dialogue_position": "before_dialogue|during_dialogue|after_dialogue|no_dialogue|unknown",
                    },
                    "lexical_lemmas": [],
                    "confidence": 0.0,
                    "evidence_sources": ["llm"],
                }
            ],
            "unresolved_spans": [],
        }
        return (
            f"{self.system_prompt}\n"
            f"已知角色：{json.dumps(characters, ensure_ascii=False)}\n"
            f"候选行为摘要：{json.dumps(candidates, ensure_ascii=False)}\n"
            f"输出结构：{json.dumps(schema, ensure_ascii=False)}\n"
            "正文（不要改动字符，span 使用 code point）：\n"
            f"{request.text}"
        )


LLMExtractor = LLMBehaviorExtractor

__all__ = ["JsonLLMClient", "LLMBehaviorExtractor", "LLMExtractor"]
