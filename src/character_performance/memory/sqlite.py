"""SQLite implementation of the cross-chapter behavior memory seam."""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock

from character_performance.domain.behavior_models import (
    AcceptedDraft,
    AuditResult,
    BehaviorFingerprint,
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
from character_performance.domain.models import HistoryEntry, SceneState, WorldState

from .migration import migrate
from .queries import OCCURRENCE_COLUMNS
from .repository import (
    BehaviorMemorySnapshot,
    HistoryWindowLimits,
    LegacyHistoryMapping,
    RevisionImpact,
    RunStatus,
    StoredRun,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteBehaviorMemory:
    """Durable, validated behavior history storage backed by SQLite."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = Path(path) if path != ":memory:" else None
        self._db = sqlite3.connect(
            str(path), check_same_thread=False, timeout=10, isolation_level=None
        )
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 10000")
        if self.path is not None:
            self._db.execute("PRAGMA journal_mode = WAL")
        self._lock = RLock()
        migrate(self._db)
        self._db.row_factory = sqlite3.Row

    @property
    def schema_version(self) -> int:
        with self._lock:
            return int(self._db.execute("PRAGMA user_version").fetchone()[0])

    def save_identity(self, book_id: str, identity: BehaviorIdentity) -> None:
        if not book_id:
            raise ValueError("book_id must not be empty")
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO behavior_identities(
                       book_id, character_id, version, payload, created_at
                   ) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(book_id, character_id, version)
                   DO UPDATE SET payload=excluded.payload""",
                (
                    book_id,
                    identity.character_id,
                    identity.version,
                    identity.model_dump_json(),
                    _utc_now(),
                ),
            )

    def load_identity(
        self, book_id: str, character_id: str, version: int | None = None
    ) -> BehaviorIdentity | None:
        if version is None:
            query = """SELECT payload FROM behavior_identities
                       WHERE book_id=? AND character_id=?
                       ORDER BY version DESC LIMIT 1"""
            parameters = (book_id, character_id)
        else:
            query = """SELECT payload FROM behavior_identities
                       WHERE book_id=? AND character_id=? AND version=?"""
            parameters = (book_id, character_id, version)
        with self._lock:
            row = self._db.execute(query, parameters).fetchone()
        return BehaviorIdentity.model_validate_json(row[0]) if row else None

    def create_run(self, request: GenerationRequest, brief: GenerationBrief) -> None:
        if request.run_id != brief.run_id:
            raise ValueError("RUN_STATE_CONFLICT: request and brief run_id differ")
        if request.position.book_id == "":
            raise ValueError("book_id must not be empty")
        now = _utc_now()
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                current = self._memory_revision(request.position.book_id)
                if brief.memory_revision != current:
                    raise MemoryRevisionConflict(
                        "BEHAVIOR_MEMORY_REVISION_CONFLICT: brief uses a stale revision"
                    )
                existing = self._db.execute(
                    "SELECT request, brief FROM generation_runs WHERE run_id=?",
                    (request.run_id,),
                ).fetchone()
                if existing:
                    if (
                        existing["request"] != request.model_dump_json()
                        or existing["brief"] != brief.model_dump_json()
                    ):
                        raise RunStateConflict(
                            "RUN_STATE_CONFLICT: run_id already has different input"
                        )
                    self._db.rollback()
                    return
                position = request.position
                self._db.execute(
                    """INSERT INTO generation_runs(
                           run_id, book_id, volume_id, chapter_id, scene_id,
                           global_beat_index, actor_id, request, brief,
                           memory_revision, status, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        request.run_id,
                        position.book_id,
                        position.volume_id,
                        position.chapter_id,
                        position.scene_id,
                        position.global_beat_index,
                        request.character.id,
                        request.model_dump_json(),
                        brief.model_dump_json(),
                        current,
                        RunStatus.PREPARED.value,
                        now,
                        now,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def record_draft(self, run_id: str, draft: GeneratedDraft) -> None:
        self._transition_draft(
            run_id, draft, allowed={RunStatus.PREPARED}, target=RunStatus.DRAFTED
        )

    def record_rewrite(self, run_id: str, draft: GeneratedDraft) -> None:
        self._transition_draft(
            run_id,
            draft,
            allowed={RunStatus.AUDITED_FAILED},
            target=RunStatus.REWRITTEN,
        )

    def _transition_draft(
        self,
        run_id: str,
        draft: GeneratedDraft,
        *,
        allowed: set[RunStatus],
        target: RunStatus,
    ) -> None:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute(
                    "SELECT status FROM generation_runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown run: {run_id}")
                status = RunStatus(row["status"])
                if status not in allowed:
                    raise RunStateConflict(
                        f"RUN_STATE_CONFLICT: cannot move {status.value} to {target.value}"
                    )
                self._db.execute(
                    """UPDATE generation_runs
                       SET status=?, audited_draft=?, audit_result=NULL,
                           extraction_result=NULL, updated_at=? WHERE run_id=?""",
                    (target.value, draft.model_dump_json(), _utc_now(), run_id),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def abandon_run(self, run_id: str) -> None:
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT status FROM generation_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
            status = RunStatus(row["status"])
            if status is not RunStatus.AUDITED_FAILED:
                raise RunStateConflict(
                    f"RUN_STATE_CONFLICT: cannot abandon run in {status.value} state"
                )
            self._db.execute(
                "UPDATE generation_runs SET status=?, updated_at=? WHERE run_id=?",
                (RunStatus.ABANDONED.value, _utc_now(), run_id),
            )

    def run_status(self, run_id: str) -> RunStatus:
        with self._lock:
            row = self._db.execute(
                "SELECT status FROM generation_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        return RunStatus(row["status"])

    def load_run(self, run_id: str) -> StoredRun:
        """Load all persisted run material for restart-safe orchestration."""
        with self._lock:
            row = self._db.execute(
                """SELECT status, request, brief, audited_draft,
                          audit_result, extraction_result
                   FROM generation_runs WHERE run_id=?""",
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        return StoredRun(
            run_id=run_id,
            status=RunStatus(row["status"]),
            request=GenerationRequest.model_validate_json(row["request"]),
            brief=GenerationBrief.model_validate_json(row["brief"]),
            draft=GeneratedDraft.model_validate_json(row["audited_draft"]) if row["audited_draft"] else None,
            audit=AuditResult.model_validate_json(row["audit_result"]) if row["audit_result"] else None,
            extraction=ExtractionResult.model_validate_json(row["extraction_result"]) if row["extraction_result"] else None,
        )

    def revision_impact(self, run_id: str) -> RevisionImpact:
        with self._lock:
            run = self._db.execute(
                """SELECT book_id, actor_id, scene_id, memory_revision
                   FROM generation_runs WHERE run_id=?""",
                (run_id,),
            ).fetchone()
            if run is None:
                raise KeyError(f"unknown run: {run_id}")
            current = self._memory_revision(run["book_id"])
            if current == run["memory_revision"]:
                return RevisionImpact.CURRENT
            relevant = self._has_relevant_changes(
                run["book_id"],
                run["memory_revision"],
                run["actor_id"],
                run["scene_id"],
            )
        return RevisionImpact.RELEVANT if relevant else RevisionImpact.UNRELATED

    def record_audit(
        self,
        draft: GeneratedDraft,
        audit: AuditResult,
        extraction: ExtractionResult,
    ) -> None:
        audit.validate_draft(draft)
        if extraction.run_id != audit.run_id:
            raise ValueError("RUN_STATE_CONFLICT: extraction and audit run_id differ")
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                run = self._db.execute(
                    """SELECT status, memory_revision, book_id, audited_draft
                       FROM generation_runs WHERE run_id=?""",
                    (audit.run_id,),
                ).fetchone()
                if run is None:
                    raise KeyError(f"unknown run: {audit.run_id}")
                status = RunStatus(run["status"])
                if status not in {
                    RunStatus.DRAFTED,
                    RunStatus.REWRITTEN,
                    RunStatus.AUDITED_PASSED,
                }:
                    raise RunStateConflict(
                        f"RUN_STATE_CONFLICT: cannot audit run in {status.value} state"
                    )
                saved_draft = GeneratedDraft.model_validate_json(run["audited_draft"])
                if saved_draft != draft:
                    raise DraftHashMismatch(
                        "DRAFT_HASH_MISMATCH: audit draft differs from recorded draft"
                    )
                current_revision = self._memory_revision(run["book_id"])
                if audit.memory_revision != current_revision:
                    raise MemoryRevisionConflict(
                        "BEHAVIOR_MEMORY_REVISION_CONFLICT: audit did not use current history"
                    )
                next_status = (
                    RunStatus.AUDITED_PASSED
                    if audit.accepted
                    else RunStatus.AUDITED_FAILED
                )
                self._db.execute(
                    """UPDATE generation_runs
                       SET status=?, audited_draft=?, audit_result=?,
                           extraction_result=?, memory_revision=?, updated_at=?
                       WHERE run_id=?""",
                    (
                        next_status.value,
                        draft.model_dump_json(),
                        audit.model_dump_json(),
                        extraction.model_dump_json(),
                        current_revision,
                        _utc_now(),
                        audit.run_id,
                    ),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def commit_accepted(
        self,
        run_id: str,
        accepted: AcceptedDraft,
        occurrences: tuple[BehaviorOccurrence, ...],
        *,
        accepted_revision: int,
        scene_state: SceneState | None = None,
        world_state: WorldState | None = None,
    ) -> CommitResult:
        if accepted_revision < 1:
            raise ValueError("accepted_revision must be positive")
        if (scene_state is None) != (world_state is None):
            raise ValueError("scene_state and world_state must be provided together")
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                run = self._db.execute(
                    "SELECT * FROM generation_runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if run is None:
                    raise KeyError(f"unknown run: {run_id}")
                existing = self._db.execute(
                    """SELECT content_hash, memory_revision FROM accepted_drafts
                       WHERE run_id=? AND revision=?""",
                    (run_id, accepted_revision),
                ).fetchone()
                if existing is not None:
                    if existing["content_hash"] != accepted.draft_hash:
                        raise DraftHashMismatch(
                            "DRAFT_HASH_MISMATCH: accepted revision has different content"
                        )
                    ids = tuple(
                        row[0]
                        for row in self._db.execute(
                            """SELECT occurrence_id FROM behavior_occurrences
                               WHERE run_id=? AND accepted_revision=?
                               ORDER BY global_beat_index, text_start, occurrence_id""",
                            (run_id, accepted_revision),
                        )
                    )
                    self._db.rollback()
                    return CommitResult(
                        run_id=run_id,
                        accepted_revision=accepted_revision,
                        content_hash=accepted.draft_hash,
                        memory_revision=existing["memory_revision"],
                        occurrence_ids=ids,
                        idempotent_replay=True,
                    )
                if RunStatus(run["status"]) is not RunStatus.AUDITED_PASSED:
                    raise RunStateConflict(
                        f"RUN_STATE_CONFLICT: cannot commit run in {run['status']} state"
                    )
                audit = AuditResult.model_validate_json(run["audit_result"])
                draft = GeneratedDraft.model_validate_json(run["audited_draft"])
                extraction = ExtractionResult.model_validate_json(run["extraction_result"])
                if not audit.accepted:
                    raise RunStateConflict("RUN_STATE_CONFLICT: audit did not pass")
                audit.validate_draft(draft)
                if (
                    accepted.text != draft.text
                    or accepted.draft_hash != audit.draft_hash
                ):
                    raise DraftHashMismatch(
                        "DRAFT_HASH_MISMATCH: commit text differs from audited text"
                    )
                current_revision = self._memory_revision(run["book_id"])
                audited_revision = audit.memory_revision
                if accepted.memory_revision != audited_revision:
                    raise MemoryRevisionConflict(
                        "BEHAVIOR_MEMORY_REVISION_CONFLICT: accepted draft and audit differ"
                    )
                if audited_revision > current_revision:
                    raise MemoryRevisionConflict(
                        "BEHAVIOR_MEMORY_REVISION_CONFLICT: audit revision is in the future"
                    )
                if audited_revision != current_revision:
                    relevant = self._has_relevant_changes(
                        run["book_id"],
                        audited_revision,
                        run["actor_id"],
                        run["scene_id"],
                    )
                    impact = "relevant" if relevant else "unrelated"
                    raise MemoryRevisionConflict(
                        "BEHAVIOR_MEMORY_REVISION_CONFLICT: "
                        f"{impact} history changed; re-audit the recorded draft"
                    )
                position_owner = self._db.execute(
                    """SELECT run_id FROM generation_runs
                       WHERE book_id=? AND global_beat_index=?
                         AND status=? AND run_id<>?""",
                    (
                        run["book_id"],
                        run["global_beat_index"],
                        RunStatus.COMMITTED.value,
                        run_id,
                    ),
                ).fetchone()
                if position_owner is not None:
                    raise BehaviorCommitConflict(
                        "BEHAVIOR_COMMIT_CONFLICT: global beat already has a formal version"
                    )
                latest_position = self._db.execute(
                    """SELECT MAX(global_beat_index) FROM (
                           SELECT global_beat_index FROM generation_runs
                           WHERE book_id=? AND status=?
                           UNION ALL
                           SELECT global_beat_index FROM behavior_occurrences
                           WHERE book_id=?
                       )""",
                    (
                        run["book_id"],
                        RunStatus.COMMITTED.value,
                        run["book_id"],
                    ),
                ).fetchone()[0]
                if latest_position is not None and run["global_beat_index"] <= latest_position:
                    raise BehaviorCommitConflict(
                        "BEHAVIOR_COMMIT_CONFLICT: global beat must strictly increase"
                    )
                self._validate_occurrences(
                    run, accepted.text, occurrences, accepted_revision
                )
                self._validate_extraction_occurrences(extraction, occurrences)
                new_revision = current_revision + 1
                now = _utc_now()
                self._db.execute(
                    """INSERT INTO accepted_drafts(
                           run_id, revision, text, audit_result, extraction_result,
                           content_hash, memory_revision, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        accepted_revision,
                        accepted.text,
                        audit.model_dump_json(),
                        extraction.model_dump_json(),
                        accepted.draft_hash,
                        new_revision,
                        now,
                    ),
                )
                for occurrence in occurrences:
                    self._insert_occurrence(occurrence, new_revision, now)
                if scene_state is not None and world_state is not None:
                    self._commit_scene_state(run, scene_state, world_state)
                self._db.execute(
                    """INSERT INTO behavior_memory_meta(book_id, revision) VALUES (?, ?)
                       ON CONFLICT(book_id) DO UPDATE SET revision=excluded.revision""",
                    (run["book_id"], new_revision),
                )
                self._db.execute(
                    """UPDATE generation_runs
                       SET status=?, accepted_revision=?, updated_at=?
                       WHERE run_id=?""",
                    (RunStatus.COMMITTED.value, accepted_revision, now, run_id),
                )
                self._db.commit()
                return CommitResult(
                    run_id=run_id,
                    accepted_revision=accepted_revision,
                    content_hash=accepted.draft_hash,
                    memory_revision=new_revision,
                    occurrence_ids=tuple(item.occurrence_id for item in occurrences),
                    idempotent_replay=False,
                )
            except Exception:
                self._db.rollback()
                raise

    def current_scene_state(
        self, scene_id: str, actor_id: str
    ) -> tuple[SceneState, WorldState] | None:
        with self._lock:
            row = self._db.execute(
                """SELECT a.state, a.world, s.revision
                   FROM actors a JOIN scenes s ON s.id=a.scene
                   WHERE a.scene=? AND a.subject=?""",
                (scene_id, actor_id),
            ).fetchone()
        if row is None:
            return None
        state = SceneState.model_validate_json(row["state"]).model_copy(
            update={"revision": row["revision"]}
        )
        return state, WorldState.model_validate_json(row["world"])

    def explain_history_query_plans(
        self, position: NarrativePosition, actor_id: str
    ) -> dict[str, tuple[str, ...]]:
        """Return SQLite's plans for the indexed hot-path history queries."""
        statements = {
            "actor": (
                """SELECT occurrence_id FROM behavior_occurrences
                   WHERE book_id=? AND actor_id=? AND global_beat_index<?
                   ORDER BY global_beat_index DESC LIMIT 5""",
                (position.book_id, actor_id, position.global_beat_index),
            ),
            "chapter": (
                """SELECT occurrence_id FROM behavior_occurrences
                   WHERE book_id=? AND chapter_id=? AND actor_id=?""",
                (position.book_id, position.chapter_id, actor_id),
            ),
            "scene": (
                """SELECT occurrence_id FROM behavior_occurrences
                   WHERE book_id=? AND scene_id=? AND global_beat_index<?
                   ORDER BY global_beat_index DESC LIMIT 20""",
                (position.book_id, position.scene_id, position.global_beat_index),
            ),
            "unit": (
                """SELECT COUNT(*) FROM behavior_occurrences
                   WHERE book_id=? AND actor_id=? AND unit_id=?""",
                (position.book_id, actor_id, "unit.probe"),
            ),
            "channel": (
                """SELECT COUNT(*) FROM behavior_occurrences
                   WHERE book_id=? AND actor_id=? AND channel=?""",
                (position.book_id, actor_id, "channel.probe"),
            ),
        }
        with self._lock:
            return {
                name: tuple(
                    row["detail"]
                    for row in self._db.execute(
                        f"EXPLAIN QUERY PLAN {statement}", parameters
                    ).fetchall()
                )
                for name, (statement, parameters) in statements.items()
            }

    def query_history(
        self,
        position: NarrativePosition,
        actor_id: str,
        limits: HistoryWindowLimits = HistoryWindowLimits(),
    ) -> BehaviorMemorySnapshot:
        base = "book_id=? AND global_beat_index<?"
        values: tuple[object, ...] = (position.book_id, position.global_beat_index)
        with self._lock:
            immediate = self._query_occurrences(
                f"{base} AND actor_id=?", values + (actor_id,), limit=limits.immediate
            )
            scene = self._query_occurrences(
                f"{base} AND scene_id=? AND actor_id=?",
                values + (position.scene_id, actor_id),
            )
            chapter = self._query_occurrences(
                f"{base} AND chapter_id=? AND actor_id=?",
                values + (position.chapter_id, actor_id),
            )
            chapter_rows = self._db.execute(
                """SELECT chapter_id, MAX(global_beat_index) AS latest
                   FROM behavior_occurrences
                   WHERE book_id=? AND actor_id=? AND global_beat_index<?
                   GROUP BY chapter_id ORDER BY latest DESC LIMIT ?""",
                (
                    position.book_id,
                    actor_id,
                    position.global_beat_index,
                    limits.recent_chapters,
                ),
            ).fetchall()
            chapter_ids = tuple(row["chapter_id"] for row in chapter_rows)
            if chapter_ids:
                placeholders = ",".join("?" for _ in chapter_ids)
                recent_chapters = self._query_occurrences(
                    f"{base} AND actor_id=? AND chapter_id IN ({placeholders})",
                    values + (actor_id,) + chapter_ids,
                )
            else:
                recent_chapters = ()
            if position.volume_id is None:
                volume_condition = f"{base} AND volume_id IS NULL AND actor_id=?"
                volume_values = values + (actor_id,)
            else:
                volume_condition = f"{base} AND volume_id=? AND actor_id=?"
                volume_values = values + (position.volume_id, actor_id)
            volume = self._query_occurrences(volume_condition, volume_values)
            book = self._query_occurrences(
                f"{base} AND actor_id=?", values + (actor_id,)
            )
            ensemble = self._query_occurrences(
                f"{base} AND scene_id=?", values + (position.scene_id,), limit=limits.ensemble
            )
            revision = self._memory_revision(position.book_id)
        return BehaviorMemorySnapshot(
            memory_revision=revision,
            immediate=immediate,
            scene=scene,
            chapter=chapter,
            recent_chapters=recent_chapters,
            volume=volume,
            book=book,
            ensemble=ensemble,
        )

    def list_book_occurrences(self, book_id: str) -> tuple[BehaviorOccurrence, ...]:
        """Return validated accepted history in narrative order for reporting."""
        if not book_id:
            raise ValueError("book_id must not be empty")
        with self._lock:
            rows = self._db.execute(
                f"""SELECT {OCCURRENCE_COLUMNS} FROM behavior_occurrences
                    WHERE book_id=?
                    ORDER BY global_beat_index, text_start, occurrence_id""",
                (book_id,),
            ).fetchall()
        return tuple(self._occurrence_from_row(row) for row in rows)

    def import_legacy_history(
        self, mappings: tuple[LegacyHistoryMapping, ...]
    ) -> tuple[BehaviorOccurrence, ...]:
        """Import only explicitly mapped legacy rows as human-confirmed history."""
        rowids = [item.legacy_history_rowid for item in mappings]
        if len(rowids) != len(set(rowids)):
            raise ValueError("legacy_history_rowid values must be unique")
        imported: list[BehaviorOccurrence] = []
        revisions: dict[str, int] = {}
        now = _utc_now()
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                by_book: dict[str, list[tuple[LegacyHistoryMapping, BehaviorOccurrence]]] = defaultdict(list)
                for mapping in mappings:
                    previous = self._db.execute(
                        """SELECT o.* FROM legacy_behavior_imports i
                           JOIN behavior_occurrences o ON o.occurrence_id=i.occurrence_id
                           WHERE i.legacy_history_rowid=?""",
                        (mapping.legacy_history_rowid,),
                    ).fetchone()
                    if previous is not None:
                        imported.append(self._occurrence_from_row(previous))
                        continue
                    row = self._db.execute(
                        "SELECT scene, subject, turn, entry FROM history WHERE rowid=?",
                        (mapping.legacy_history_rowid,),
                    ).fetchone()
                    if row is None:
                        raise KeyError(
                            f"unknown legacy history rowid: {mapping.legacy_history_rowid}"
                        )
                    history = HistoryEntry.model_validate_json(row["entry"])
                    if mapping.position.scene_id != row["scene"]:
                        raise ValueError("legacy mapping scene_id does not match history row")
                    if mapping.position.beat_index != history.turn_index:
                        raise ValueError("legacy mapping beat_index must match history turn_index")
                    fingerprint = BehaviorFingerprint(
                        unit_id=history.unit_id,
                        semantic_groups=history.semantic_groups,
                        channel=history.channel,
                        narrative_functions=mapping.narrative_functions,
                        strategy_id=mapping.strategy_id,
                        actor_id=row["subject"],
                        target_ids=mapping.target_ids,
                        visibility=mapping.visibility,
                        amplitude_band=mapping.amplitude_band,
                        syntax_features=mapping.syntax_features,
                        lexical_lemmas=mapping.lexical_lemmas,
                    )
                    occurrence = BehaviorOccurrence(
                        occurrence_id=f"occurrence.legacy.{mapping.legacy_history_rowid}",
                        book_id=mapping.position.book_id,
                        position=mapping.position,
                        actor_id=row["subject"],
                        target_ids=mapping.target_ids,
                        fingerprint=fingerprint,
                        source="human_confirmed",
                        text_span=mapping.text_span,
                        confidence=mapping.confidence,
                        generation_run_id=f"run.legacy.{mapping.legacy_history_rowid}",
                        accepted_revision=1,
                    )
                    by_book[occurrence.book_id].append((mapping, occurrence))
                for book_id, items in by_book.items():
                    revision = self._memory_revision(book_id) + 1
                    revisions[book_id] = revision
                    for mapping, occurrence in items:
                        self._insert_occurrence(occurrence, revision, now)
                        self._db.execute(
                            """INSERT INTO legacy_behavior_imports(
                                   legacy_history_rowid, occurrence_id, imported_at
                               ) VALUES (?, ?, ?)""",
                            (mapping.legacy_history_rowid, occurrence.occurrence_id, now),
                        )
                        imported.append(occurrence)
                    self._db.execute(
                        """INSERT INTO behavior_memory_meta(book_id, revision) VALUES (?, ?)
                           ON CONFLICT(book_id) DO UPDATE SET revision=excluded.revision""",
                        (book_id, revision),
                    )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return tuple(imported)

    def backup(self, destination: str | Path) -> None:
        destination_path = Path(destination)
        if destination_path.exists():
            raise FileExistsError(destination_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target = sqlite3.connect(destination_path)
            try:
                self._db.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError(f"backup integrity check failed: {result}")
            finally:
                target.close()

    @classmethod
    def restore_backup(
        cls,
        source: str | Path,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> "SQLiteBehaviorMemory":
        source_path = Path(source)
        destination_path = Path(destination)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if destination_path.exists() and not overwrite:
            raise FileExistsError(destination_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination_path.with_name(f".{destination_path.name}.restore-{os.getpid()}")
        try:
            source_db = sqlite3.connect(source_path)
            target = sqlite3.connect(temporary)
            try:
                source_db.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError(
                        f"restored database integrity check failed: {result}"
                    )
            finally:
                target.close()
                source_db.close()
            os.replace(temporary, destination_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return cls(destination_path)

    def _memory_revision(self, book_id: str) -> int:
        row = self._db.execute(
            "SELECT revision FROM behavior_memory_meta WHERE book_id=?", (book_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    def _has_relevant_changes(
        self,
        book_id: str,
        since_revision: int,
        actor_id: str,
        scene_id: str,
    ) -> bool:
        row = self._db.execute(
            """SELECT 1 FROM behavior_occurrences
               WHERE book_id=? AND memory_revision>?
                 AND (actor_id=? OR scene_id=?)
               LIMIT 1""",
            (book_id, since_revision, actor_id, scene_id),
        ).fetchone()
        return row is not None

    def _commit_scene_state(
        self, run: sqlite3.Row, state: SceneState, world: WorldState
    ) -> None:
        request = GenerationRequest.model_validate_json(run["request"])
        before = request.scene_state
        if state.scene_id != run["scene_id"] or state.scene_id != before.scene_id:
            raise SceneRevisionConflict(
                "SCENE_REVISION_CONFLICT: scene state belongs to a different scene"
            )
        current = self._db.execute(
            "SELECT revision FROM scenes WHERE id=?", (state.scene_id,)
        ).fetchone()
        current_revision = int(current[0]) if current else 0
        if current_revision != before.revision or state.revision != before.revision + 1:
            raise SceneRevisionConflict(
                "SCENE_REVISION_CONFLICT: scene state is not the next committed revision"
            )
        self._db.execute(
            """INSERT INTO scenes(id, revision) VALUES (?, ?)
               ON CONFLICT(id) DO UPDATE SET revision=excluded.revision""",
            (state.scene_id, state.revision),
        )
        self._db.execute(
            """INSERT INTO actors(scene, subject, state, world) VALUES (?, ?, ?, ?)
               ON CONFLICT(scene, subject)
               DO UPDATE SET state=excluded.state, world=excluded.world""",
            (
                state.scene_id,
                run["actor_id"],
                state.model_dump_json(),
                world.model_dump_json(),
            ),
        )

    def _validate_occurrences(
        self,
        run: sqlite3.Row,
        source_text: str,
        occurrences: tuple[BehaviorOccurrence, ...],
        accepted_revision: int,
    ) -> None:
        ids = [item.occurrence_id for item in occurrences]
        if len(ids) != len(set(ids)):
            raise ValueError("occurrence_ids must be unique")
        for occurrence in occurrences:
            position = occurrence.position
            if (
                occurrence.generation_run_id != run["run_id"]
                or occurrence.book_id != run["book_id"]
                or occurrence.actor_id != run["actor_id"]
                or position.chapter_id != run["chapter_id"]
                or position.scene_id != run["scene_id"]
                or position.global_beat_index != run["global_beat_index"]
                or occurrence.accepted_revision != accepted_revision
            ):
                raise ValueError("occurrence does not match its generation run")
            span = occurrence.text_span
            if source_text[span.start : span.end] != span.text:
                raise ValueError("occurrence text_span must match accepted draft")
            if occurrence.source not in {"extracted", "human_confirmed"}:
                raise ValueError("only accepted occurrences may enter behavior memory")

    @staticmethod
    def _validate_extraction_occurrences(
        extraction: ExtractionResult,
        occurrences: tuple[BehaviorOccurrence, ...],
    ) -> None:
        extracted_occurrences = [
            occurrence for occurrence in occurrences if occurrence.source == "extracted"
        ]
        if len(extracted_occurrences) != len(extraction.behaviors):
            raise ValueError(
                "extracted occurrences must correspond one-to-one with extraction behaviors"
            )
        unmatched = list(extracted_occurrences)
        for behavior in extraction.behaviors:
            for index, occurrence in enumerate(unmatched):
                fingerprint = occurrence.fingerprint
                if (
                    occurrence.actor_id == behavior.actor_id
                    and occurrence.target_ids == behavior.target_ids
                    and occurrence.text_span == behavior.text_span
                    and fingerprint.unit_id == behavior.matched_unit_id
                    and fingerprint.semantic_groups == behavior.semantic_groups
                    and fingerprint.channel == behavior.channel
                    and fingerprint.narrative_functions == behavior.narrative_functions
                    and fingerprint.strategy_id == behavior.strategy_id
                    and fingerprint.syntax_features == behavior.syntax_features
                    and fingerprint.lexical_lemmas == behavior.lexical_lemmas
                    and occurrence.confidence == behavior.confidence
                ):
                    unmatched.pop(index)
                    break
            else:
                raise ValueError(
                    "extracted occurrence does not match the audited extraction result"
                )

    def _insert_occurrence(
        self, occurrence: BehaviorOccurrence, memory_revision: int, created_at: str
    ) -> None:
        position = occurrence.position
        fingerprint = occurrence.fingerprint
        span = occurrence.text_span
        self._db.execute(
            """INSERT INTO behavior_occurrences(
                   occurrence_id, run_id, book_id, volume_id, chapter_id, scene_id,
                   global_beat_index, paragraph_index, beat_index, timeline_ms,
                   actor_id, target_ids, unit_id, semantic_groups, channel,
                   narrative_functions, strategy_id, visibility, amplitude_band,
                   syntax_features, lexical_lemmas, source, confidence, text_start,
                   text_end, text, accepted_revision, memory_revision, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                         ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                occurrence.occurrence_id,
                occurrence.generation_run_id,
                occurrence.book_id,
                position.volume_id,
                position.chapter_id,
                position.scene_id,
                position.global_beat_index,
                position.paragraph_index,
                position.beat_index,
                position.timeline_ms,
                occurrence.actor_id,
                json.dumps(occurrence.target_ids, ensure_ascii=False),
                fingerprint.unit_id,
                json.dumps(sorted(fingerprint.semantic_groups), ensure_ascii=False),
                fingerprint.channel,
                json.dumps(sorted(fingerprint.narrative_functions), ensure_ascii=False),
                fingerprint.strategy_id,
                fingerprint.visibility,
                fingerprint.amplitude_band,
                fingerprint.syntax_features.model_dump_json(),
                json.dumps(fingerprint.lexical_lemmas, ensure_ascii=False),
                occurrence.source,
                occurrence.confidence,
                span.start,
                span.end,
                span.text,
                occurrence.accepted_revision,
                memory_revision,
                created_at,
            ),
        )

    def _query_occurrences(
        self,
        condition: str,
        parameters: tuple[object, ...],
        *,
        limit: int | None = None,
    ) -> tuple[BehaviorOccurrence, ...]:
        query = f"SELECT {OCCURRENCE_COLUMNS} FROM behavior_occurrences WHERE {condition} ORDER BY global_beat_index DESC, text_start DESC, occurrence_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            parameters += (limit,)
        rows = self._db.execute(query, parameters).fetchall()
        return tuple(self._occurrence_from_row(row) for row in reversed(rows))

    @staticmethod
    def _occurrence_from_row(row: sqlite3.Row) -> BehaviorOccurrence:
        syntax = SyntaxFeatures.model_validate_json(row["syntax_features"])
        target_ids = tuple(json.loads(row["target_ids"]))
        return BehaviorOccurrence(
            occurrence_id=row["occurrence_id"],
            book_id=row["book_id"],
            position=NarrativePosition(
                book_id=row["book_id"],
                volume_id=row["volume_id"],
                chapter_id=row["chapter_id"],
                scene_id=row["scene_id"],
                paragraph_index=row["paragraph_index"],
                beat_index=row["beat_index"],
                global_beat_index=row["global_beat_index"],
                timeline_ms=row["timeline_ms"],
            ),
            actor_id=row["actor_id"],
            target_ids=target_ids,
            fingerprint=BehaviorFingerprint(
                unit_id=row["unit_id"],
                semantic_groups=frozenset(json.loads(row["semantic_groups"])),
                channel=row["channel"],
                narrative_functions=frozenset(json.loads(row["narrative_functions"])),
                strategy_id=row["strategy_id"],
                actor_id=row["actor_id"],
                target_ids=target_ids,
                visibility=row["visibility"],
                amplitude_band=row["amplitude_band"],
                syntax_features=syntax,
                lexical_lemmas=tuple(json.loads(row["lexical_lemmas"])),
            ),
            source=row["source"],
            text_span=TextSpan(
                start=row["text_start"], end=row["text_end"], text=row["text"]
            ),
            confidence=row["confidence"],
            generation_run_id=row["run_id"],
            accepted_revision=row["accepted_revision"],
        )

    def close(self) -> None:
        with self._lock:
            self._db.close()


class BehaviorMemoryError(ValueError):
    """Base error for behavior-memory protocol failures."""


class MemoryRevisionConflict(BehaviorMemoryError):
    pass


class RunStateConflict(BehaviorMemoryError):
    pass


class DraftHashMismatch(BehaviorMemoryError):
    pass


class SceneRevisionConflict(BehaviorMemoryError):
    pass


class BehaviorCommitConflict(BehaviorMemoryError):
    pass
