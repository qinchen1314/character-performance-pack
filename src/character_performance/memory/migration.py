"""Transactional SQLite schema migrations for behavior memory."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence

from .repository import RunStatus


CURRENT_SCHEMA_VERSION = 1
Migration = Callable[[sqlite3.Connection], None]


_SCHEMA_V1 = (
    "CREATE TABLE IF NOT EXISTS scenes (id TEXT PRIMARY KEY, revision INTEGER NOT NULL)",
    """CREATE TABLE IF NOT EXISTS actors (
        scene TEXT, subject TEXT, state TEXT NOT NULL, world TEXT NOT NULL,
        PRIMARY KEY(scene, subject)
    )""",
    """CREATE TABLE IF NOT EXISTS plans (
        id TEXT PRIMARY KEY, request TEXT NOT NULL, plan TEXT NOT NULL,
        history TEXT NOT NULL, rendered INTEGER NOT NULL DEFAULT 0,
        committed INTEGER NOT NULL DEFAULT 0, render_result TEXT,
        scene_history TEXT NOT NULL DEFAULT '[]'
    )""",
    """CREATE TABLE IF NOT EXISTS history (
        scene TEXT, subject TEXT, turn INTEGER, entry TEXT NOT NULL
    )""",
    """CREATE TABLE behavior_identities (
        book_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version >= 1),
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (book_id, character_id, version)
    )""",
    """CREATE TABLE generation_runs (
        run_id TEXT PRIMARY KEY,
        book_id TEXT NOT NULL,
        volume_id TEXT,
        chapter_id TEXT NOT NULL,
        scene_id TEXT NOT NULL,
        global_beat_index INTEGER NOT NULL CHECK(global_beat_index >= 0),
        actor_id TEXT NOT NULL,
        request TEXT NOT NULL,
        brief TEXT NOT NULL,
        memory_revision INTEGER NOT NULL CHECK(memory_revision >= 0),
        status TEXT NOT NULL CHECK(status IN (
            'prepared', 'drafted', 'audited_failed', 'rewritten',
            'audited_passed', 'committed', 'abandoned'
        )),
        accepted_revision INTEGER,
        audited_draft TEXT,
        audit_result TEXT,
        extraction_result TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE accepted_drafts (
        run_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        text TEXT NOT NULL,
        audit_result TEXT NOT NULL,
        extraction_result TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        memory_revision INTEGER NOT NULL CHECK(memory_revision >= 1),
        created_at TEXT NOT NULL,
        PRIMARY KEY (run_id, revision),
        FOREIGN KEY (run_id) REFERENCES generation_runs(run_id)
    )""",
    """CREATE TABLE behavior_occurrences (
        occurrence_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        volume_id TEXT,
        chapter_id TEXT NOT NULL,
        scene_id TEXT NOT NULL,
        global_beat_index INTEGER NOT NULL CHECK(global_beat_index >= 0),
        paragraph_index INTEGER NOT NULL CHECK(paragraph_index >= 0),
        beat_index INTEGER NOT NULL CHECK(beat_index >= 0),
        timeline_ms INTEGER,
        actor_id TEXT NOT NULL,
        target_ids TEXT NOT NULL,
        unit_id TEXT,
        semantic_groups TEXT NOT NULL,
        channel TEXT NOT NULL,
        narrative_functions TEXT NOT NULL,
        strategy_id TEXT,
        visibility TEXT NOT NULL,
        amplitude_band TEXT NOT NULL,
        syntax_features TEXT NOT NULL,
        lexical_lemmas TEXT NOT NULL,
        source TEXT NOT NULL,
        confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
        text_start INTEGER NOT NULL CHECK(text_start >= 0),
        text_end INTEGER NOT NULL CHECK(text_end > text_start),
        text TEXT NOT NULL,
        accepted_revision INTEGER NOT NULL CHECK(accepted_revision >= 1),
        memory_revision INTEGER NOT NULL CHECK(memory_revision >= 1),
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE behavior_memory_meta (
        book_id TEXT PRIMARY KEY,
        revision INTEGER NOT NULL CHECK(revision >= 0)
    )""",
    """CREATE TABLE legacy_behavior_imports (
        legacy_history_rowid INTEGER PRIMARY KEY,
        occurrence_id TEXT NOT NULL UNIQUE,
        imported_at TEXT NOT NULL,
        FOREIGN KEY (occurrence_id) REFERENCES behavior_occurrences(occurrence_id)
    )""",
    "CREATE INDEX idx_behavior_actor_position ON behavior_occurrences(book_id, actor_id, global_beat_index DESC)",
    "CREATE INDEX idx_behavior_chapter_actor ON behavior_occurrences(book_id, chapter_id, actor_id)",
    "CREATE INDEX idx_behavior_actor_unit ON behavior_occurrences(book_id, actor_id, unit_id)",
    "CREATE INDEX idx_behavior_actor_channel ON behavior_occurrences(book_id, actor_id, channel)",
    "CREATE INDEX idx_behavior_scene_position ON behavior_occurrences(book_id, scene_id, global_beat_index DESC)",
    f"CREATE UNIQUE INDEX idx_committed_book_position ON generation_runs(book_id, global_beat_index) WHERE status = '{RunStatus.COMMITTED.value}'",
)


def _migration_v1(connection: sqlite3.Connection) -> None:
    for statement in _SCHEMA_V1:
        connection.execute(statement)
    plan_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(plans)").fetchall()
    }
    if "render_result" not in plan_columns:
        connection.execute("ALTER TABLE plans ADD COLUMN render_result TEXT")
    if "scene_history" not in plan_columns:
        connection.execute(
            "ALTER TABLE plans ADD COLUMN scene_history TEXT NOT NULL DEFAULT '[]'"
        )


DEFAULT_MIGRATIONS: tuple[Migration, ...] = (_migration_v1,)


def migrate(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration] = DEFAULT_MIGRATIONS,
) -> int:
    """Apply all pending migrations in one rollback-safe transaction."""
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    target = len(migrations)
    if current > target:
        raise RuntimeError(
            f"database schema version {current} is newer than supported version {target}"
        )
    if current == target:
        return current
    try:
        connection.execute("BEGIN IMMEDIATE")
        for version in range(current + 1, target + 1):
            migrations[version - 1](connection)
            connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return target
