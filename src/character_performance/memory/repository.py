"""Public storage seam for cross-chapter behavior memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from character_performance.domain.behavior_models import (
    AcceptedDraft,
    AuditResult,
    BehaviorIdentity,
    BehaviorOccurrence,
    CommitResult,
    ExtractionResult,
    GeneratedDraft,
    GenerationBrief,
    GenerationRequest,
    NarrativePosition,
    SyntaxFeatures,
    TextSpan,
)
from character_performance.domain.models import SceneState, WorldState


@dataclass(frozen=True, slots=True)
class HistoryWindowLimits:
    immediate: int = 5
    recent_chapters: int = 3
    ensemble: int = 20

    def __post_init__(self) -> None:
        if self.immediate < 1 or self.recent_chapters < 1 or self.ensemble < 1:
            raise ValueError("history window limits must be positive")


class RunStatus(StrEnum):
    PREPARED = "prepared"
    DRAFTED = "drafted"
    AUDITED_FAILED = "audited_failed"
    REWRITTEN = "rewritten"
    AUDITED_PASSED = "audited_passed"
    COMMITTED = "committed"
    ABANDONED = "abandoned"


class RevisionImpact(StrEnum):
    CURRENT = "current"
    UNRELATED = "unrelated"
    RELEVANT = "relevant"


@dataclass(frozen=True, slots=True)
class BehaviorMemorySnapshot:
    memory_revision: int
    immediate: tuple[BehaviorOccurrence, ...]
    scene: tuple[BehaviorOccurrence, ...]
    chapter: tuple[BehaviorOccurrence, ...]
    recent_chapters: tuple[BehaviorOccurrence, ...]
    volume: tuple[BehaviorOccurrence, ...]
    book: tuple[BehaviorOccurrence, ...]
    ensemble: tuple[BehaviorOccurrence, ...]


@dataclass(frozen=True, slots=True)
class StoredRun:
    """Durable run payload used by coordinators after a process restart."""

    run_id: str
    status: RunStatus
    request: GenerationRequest
    brief: GenerationBrief
    draft: GeneratedDraft | None = None
    audit: AuditResult | None = None
    extraction: ExtractionResult | None = None


class LegacyHistoryMapping(BaseModel):
    """Caller-supplied information missing from one legacy ``history`` row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    legacy_history_rowid: int = Field(ge=1)
    position: NarrativePosition
    text_span: TextSpan
    narrative_functions: frozenset[str] = Field(min_length=1)
    target_ids: tuple[str, ...] = ()
    strategy_id: str | None = None
    visibility: Literal[
        "hidden", "very_subtle", "subtle", "noticeable", "obvious", "unknown"
    ] = "unknown"
    amplitude_band: Literal["none", "low", "medium", "high", "unknown"] = "unknown"
    syntax_features: SyntaxFeatures = SyntaxFeatures()
    lexical_lemmas: tuple[str, ...] = ()
    confidence: float = Field(default=1.0, ge=0, le=1)


class BehaviorMemory(Protocol):
    @property
    def schema_version(self) -> int: ...

    def save_identity(self, book_id: str, identity: BehaviorIdentity) -> None: ...

    def load_identity(
        self, book_id: str, character_id: str, version: int | None = None
    ) -> BehaviorIdentity | None: ...

    def create_run(self, request: GenerationRequest, brief: GenerationBrief) -> None: ...

    def record_draft(self, run_id: str, draft: GeneratedDraft) -> None: ...

    def record_rewrite(self, run_id: str, draft: GeneratedDraft) -> None: ...

    def abandon_run(self, run_id: str) -> None: ...

    def run_status(self, run_id: str) -> RunStatus: ...

    def load_run(self, run_id: str) -> StoredRun: ...

    def revision_impact(self, run_id: str) -> RevisionImpact: ...

    def record_audit(
        self,
        draft: GeneratedDraft,
        audit: AuditResult,
        extraction: ExtractionResult,
    ) -> None: ...

    def commit_accepted(
        self,
        run_id: str,
        accepted: AcceptedDraft,
        occurrences: tuple[BehaviorOccurrence, ...],
        *,
        accepted_revision: int,
        scene_state: SceneState | None = None,
        world_state: WorldState | None = None,
    ) -> CommitResult: ...

    def query_history(
        self,
        position: NarrativePosition,
        actor_id: str,
        limits: HistoryWindowLimits = HistoryWindowLimits(),
    ) -> BehaviorMemorySnapshot: ...

    def import_legacy_history(
        self, mappings: tuple[LegacyHistoryMapping, ...]
    ) -> tuple[BehaviorOccurrence, ...]: ...

    def backup(self, destination: str) -> None: ...

    def current_scene_state(
        self, scene_id: str, actor_id: str
    ) -> tuple[SceneState, WorldState] | None: ...

    def explain_history_query_plans(
        self, position: NarrativePosition, actor_id: str
    ) -> dict[str, tuple[str, ...]]: ...

    def close(self) -> None: ...
