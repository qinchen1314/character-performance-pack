"""SQLite unit of work: plans are provisional; state and history commit together."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from character_performance.domain.models import HistoryEntry, PerformancePlan, PerformanceRequest, RenderResult, SceneState, WorldState


class RevisionConflict(ValueError):
    pass


class SQLiteRepository:
    def __init__(self, path: str | Path = ":memory:"):
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._lock = RLock()
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS scenes (id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS actors (scene TEXT, subject TEXT, state TEXT NOT NULL,
                world TEXT NOT NULL, PRIMARY KEY(scene, subject));
            CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, request TEXT NOT NULL,
                plan TEXT NOT NULL, history TEXT NOT NULL, rendered INTEGER NOT NULL DEFAULT 0,
                committed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS history (scene TEXT, subject TEXT, turn INTEGER, entry TEXT NOT NULL);
        """)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(plans)")}
            if "render_result" not in columns:
                self._db.execute("ALTER TABLE plans ADD COLUMN render_result TEXT")
            if "scene_history" not in columns:
                self._db.execute("ALTER TABLE plans ADD COLUMN scene_history TEXT NOT NULL DEFAULT '[]'")
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    def close(self) -> None:
        self._db.close()

    def current(self, scene_id: str, subject_id: str) -> tuple[SceneState, WorldState] | None:
        with self._lock:
            row = self._db.execute("SELECT a.state, a.world, s.revision FROM actors a JOIN scenes s ON s.id=a.scene WHERE a.scene=? AND a.subject=?", (scene_id, subject_id)).fetchone()
        if not row:
            return None
        state = SceneState.model_validate_json(row[0]).model_copy(update={"revision": row[2]})
        return state, WorldState.model_validate_json(row[1])

    def check_snapshot(self, request: PerformanceRequest) -> None:
        scene = request.scene_state
        with self._lock:
            row = self._db.execute("SELECT revision FROM scenes WHERE id=?", (scene.scene_id,)).fetchone()
            revision = row[0] if row else 0
            if scene.revision != revision:
                raise RevisionConflict(f"SCENE_REVISION_CONFLICT: expected {scene.revision}, current {revision}")
            current = self.current(scene.scene_id, request.character.id)
            if current and (current[0] != scene or current[1] != request.world_state):
                raise RevisionConflict("STATE_SNAPSHOT_CONFLICT: use the committed scene/world snapshot")

    def history(self, scene_id: str, subject_id: str) -> tuple[HistoryEntry, ...]:
        with self._lock:
            rows = self._db.execute("SELECT entry FROM history WHERE scene=? AND subject=? ORDER BY turn, rowid", (scene_id, subject_id)).fetchall()
        return tuple(HistoryEntry.model_validate_json(row[0]) for row in rows)

    def scene_history(self, scene_id: str, exclude_subject: str) -> tuple[HistoryEntry, ...]:
        # Actor turn indices are local. Commit insertion order defines the shared
        # recent-scene window, independent of each actor's turn counter.
        with self._lock:
            rows = self._db.execute("SELECT subject, entry FROM history WHERE scene=? ORDER BY rowid DESC LIMIT 12", (scene_id,)).fetchall()
        # Apply the shared window before excluding this actor, so their later
        # gestures can age other actors' old gestures out of the window.
        return tuple(HistoryEntry.model_validate_json(entry) for subject, entry in reversed(rows) if subject != exclude_subject)

    def saved_scene_history(self, plan_id: str) -> tuple[HistoryEntry, ...]:
        with self._lock:
            row = self._db.execute("SELECT scene_history FROM plans WHERE id=?", (plan_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown plan: {plan_id}")
        return tuple(HistoryEntry.model_validate(item) for item in json.loads(row[0]))

    def save_plan(self, request: PerformanceRequest, plan: PerformancePlan, history: tuple[HistoryEntry, ...], scene_history: tuple[HistoryEntry, ...] = ()) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO plans(id, request, plan, history, scene_history) VALUES(?,?,?,?,?)", (plan.plan_id, request.model_dump_json(), plan.model_dump_json(), json.dumps([h.model_dump(mode="json") for h in history]), json.dumps([h.model_dump(mode="json") for h in scene_history])))

    def load_plan(self, plan_id: str) -> tuple[PerformanceRequest, PerformancePlan, tuple[HistoryEntry, ...]]:
        with self._lock:
            row = self._db.execute("SELECT request, plan, history FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise KeyError(f"unknown plan: {plan_id}")
        return PerformanceRequest.model_validate_json(row[0]), PerformancePlan.model_validate_json(row[1]), tuple(HistoryEntry.model_validate(h) for h in json.loads(row[2]))

    def mark_rendered(self, plan_id: str, result: RenderResult) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE plans SET rendered=1, render_result=? WHERE id=? AND committed=0", (result.model_dump_json(), plan_id))

    def render_result(self, plan_id: str) -> RenderResult | None:
        with self._lock:
            row = self._db.execute("SELECT render_result FROM plans WHERE id=?", (plan_id,)).fetchone()
        return RenderResult.model_validate_json(row[0]) if row and row[0] else None

    def commit(self, plan: PerformancePlan, expected_revision: int, entries: tuple[HistoryEntry, ...]) -> SceneState:
        transition = plan.state_transition
        if transition is None:
            raise ValueError("plan has no state transition")
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                row = self._db.execute("SELECT committed, rendered FROM plans WHERE id=?", (plan.plan_id,)).fetchone()
                if row is None or not row[1]:
                    raise ValueError("RENDER_REQUIRED: render successfully before commit")
                if expected_revision != transition.before.revision:
                    raise RevisionConflict("SCENE_REVISION_CONFLICT: plan revision differs")
                if row[0]:
                    self._db.rollback()
                    return transition.after
                current = self._db.execute("SELECT revision FROM scenes WHERE id=?", (plan.scene_id,)).fetchone()
                revision = current[0] if current else 0
                if revision != expected_revision:
                    raise RevisionConflict(f"SCENE_REVISION_CONFLICT: expected {expected_revision}, current {revision}")
                self._db.execute("INSERT INTO scenes(id, revision) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision", (plan.scene_id, revision + 1))
                self._db.execute("INSERT INTO actors(scene,subject,state,world) VALUES(?,?,?,?) ON CONFLICT(scene,subject) DO UPDATE SET state=excluded.state,world=excluded.world", (plan.scene_id, plan.subject_id, transition.after.model_dump_json(), transition.world_after.model_dump_json()))
                for entry in entries:
                    self._db.execute("INSERT INTO history(scene,subject,turn,entry) VALUES(?,?,?,?)", (plan.scene_id, plan.subject_id, entry.turn_index, entry.model_dump_json()))
                self._db.execute("DELETE FROM history WHERE scene=? AND subject=? AND turn < ?", (plan.scene_id, plan.subject_id, plan.turn_index - 100))
                self._db.execute("UPDATE plans SET committed=1 WHERE id=?", (plan.plan_id,))
                self._db.commit()
                return transition.after
            except Exception:
                self._db.rollback()
                raise
