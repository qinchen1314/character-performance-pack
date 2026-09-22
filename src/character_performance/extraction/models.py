"""Protocols and errors shared by text behaviour extractors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from character_performance.domain.behavior_models import (
    ExtractedBehavior,
    ExtractionRequest,
    ExtractionResult,
    TextSpan,
)


class TextBehaviorExtractor(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


class ExtractionError(ValueError):
    """Base class for actionable extraction failures."""

    code = "EXTRACTION_INCOMPLETE"


class ExtractionUnavailable(ExtractionError):
    code = "EXTRACTION_UNAVAILABLE"


class ExtractionFormatError(ExtractionError):
    code = "EXTRACTION_FORMAT_INVALID"


class SpanValidationError(ExtractionFormatError):
    code = "EXTRACTION_SPAN_INVALID"


@dataclass(frozen=True, slots=True)
class ExtractionConflict:
    """Evidence retained when adapters disagree about one text span."""

    span: TextSpan
    actor_id: str
    rule: ExtractedBehavior
    llm: ExtractedBehavior


def parse_adapter_payload(payload: Any, *, request: ExtractionRequest) -> ExtractionResult:
    """Validate an adapter payload without allowing silent field loss."""

    if isinstance(payload, ExtractionResult):
        result = payload
    elif isinstance(payload, Mapping):
        try:
            result = ExtractionResult.model_validate(payload)
        except Exception as exc:  # pydantic's detail is useful to callers
            raise ExtractionFormatError(f"invalid extraction payload: {exc}") from exc
    else:
        raise ExtractionFormatError("extraction adapter must return a mapping or ExtractionResult")
    try:
        request.validate_result(result)
    except ValueError as exc:
        raise SpanValidationError(str(exc)) from exc
    return result


__all__ = [
    "ExtractionConflict",
    "ExtractionError",
    "ExtractionFormatError",
    "ExtractionUnavailable",
    "SpanValidationError",
    "TextBehaviorExtractor",
    "parse_adapter_payload",
]
