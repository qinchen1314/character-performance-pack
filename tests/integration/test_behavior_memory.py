from __future__ import annotations

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
import yaml

from character_performance.domain.behavior_models import (
    AcceptedDraft,
    AuditMetrics,
    AuditResult,
    BehaviorFingerprint,
    BehaviorIdentity,
    BehaviorOccurrence,
    ExtractedBehavior,
    ExtractionResult,
    GeneratedDraft,
    GenerationBrief,
    GenerationRequest,
    NarrativePosition,
    ReactionStrategyPlan,
    StyleContext,
    SyntaxFeatures,
    TextSpan,
    content_hash,
)
from character_performance.domain.models import CharacterProfile, HistoryEntry, SceneState
from character_performance.memory import (
    BehaviorCommitConflict,
    HistoryWindowLimits,
    LegacyHistoryMapping,
    MemoryRevisionConflict,
    SceneRevisionConflict,
    SQLiteBehaviorMemory,
)
from character_performance.memory.migration import migrate


def _identity(character_id: str = "char.luo_han") -> BehaviorIdentity:
    return BehaviorIdentity(
        character_id=character_id,
        version=1,
        default_strategies={"conflict": "conceal_then_counter"},
        preferred_channels={"gaze": 0.8, "speech_rhythm": 0.72},
        avoided_channels={"hands": 0.9},
        values={"self_control", "status"},
        taboos={"public_pleading"},
        coping_strategies={"observe", "conceal"},
        social_masks={"public": "controlled_courtesy"},
    )


def _position(
    *, chapter: str = "chapter.0017", scene: str = "scene.0017.02", beat: int = 1284
) -> NarrativePosition:
    return NarrativePosition(
        book_id="book.hehuan",
        volume_id="volume.01",
        chapter_id=chapter,
        scene_id=scene,
        paragraph_index=18,
        beat_index=43,
        global_beat_index=beat,
    )


def _strategy() -> ReactionStrategyPlan:
    return ReactionStrategyPlan(
        strategy_id="conceal_then_counter",
        intent="protect_status_without_escalation",
        surface_goal="maintain_courtesy",
        private_goal="retain_initiative",
        applicability_conditions={"public_scene"},
        contraindications={"unconscious"},
        preferred_channels=("speech_rhythm", "gaze"),
        suppressed_channels={"hands"},
        allowed_visibility="subtle",
        action_budget=2,
        omit_action_allowed=True,
        relationship_meaning="courtesy_without_submission",
        reasons=("public_scene",),
    )


def _request(
    run_id: str = "run.01j",
    position: NarrativePosition | None = None,
    actor_id: str = "char.luo_han",
) -> GenerationRequest:
    position = position or _position()
    return GenerationRequest(
        run_id=run_id,
        position=position,
        character=CharacterProfile(id=actor_id),
        behavior_identity=_identity(actor_id),
        scene_state=SceneState(scene_id=position.scene_id),
        style_context=StyleContext(
            pov="third_limited", prose_style="restrained", paragraph_function="reaction"
        ),
    )


def _brief(run_id: str = "run.01j", memory_revision: int = 0) -> GenerationBrief:
    return GenerationBrief(
        run_id=run_id,
        strategy=_strategy(),
        preferred_channels=("speech_rhythm", "gaze"),
        omit_action_allowed=True,
        maximum_visible_signals=2,
        prompt_fragment="保持克制，可省略动作。",
        memory_revision=memory_revision,
    )


def _accepted_bundle(
    run_id: str = "run.01j",
    memory_revision: int = 0,
    position: NarrativePosition | None = None,
    actor_id: str = "char.luo_han",
):
    position = position or _position()
    text = "他看向窗外。"
    span = TextSpan(start=0, end=len(text), text=text)
    syntax = SyntaxFeatures(subject_opening="actor", temporal_shape="sustained")
    extracted = ExtractedBehavior(
        actor_id=actor_id,
        text_span=span,
        canonical_action="gaze_outside",
        matched_unit_id="gaze.look_away",
        semantic_groups={"gaze_withdrawal"},
        channel="gaze",
        narrative_functions={"delay_response"},
        strategy_id="conceal_then_counter",
        syntax_features=syntax,
        lexical_lemmas=("看向", "窗外"),
        confidence=0.96,
        evidence_sources={"rule"},
    )
    extraction = ExtractionResult(run_id=run_id, behaviors=(extracted,))
    audit = AuditResult(
        run_id=run_id,
        draft_hash=content_hash(text),
        accepted=True,
        metrics=AuditMetrics(),
        memory_revision=memory_revision,
    )
    occurrence = BehaviorOccurrence(
        occurrence_id=f"occurrence.{run_id}",
        book_id="book.hehuan",
        position=position,
        actor_id=actor_id,
        fingerprint=BehaviorFingerprint(
            unit_id="gaze.look_away",
            semantic_groups={"gaze_withdrawal"},
            channel="gaze",
            narrative_functions={"delay_response"},
            strategy_id="conceal_then_counter",
            actor_id=actor_id,
            visibility="subtle",
            amplitude_band="low",
            syntax_features=syntax,
            lexical_lemmas=("看向", "窗外"),
        ),
        source="extracted",
        text_span=span,
        confidence=0.96,
        generation_run_id=run_id,
        accepted_revision=1,
    )
    return (
        GeneratedDraft(text=text),
        audit,
        extraction,
        AcceptedDraft(text=text, draft_hash=content_hash(text), memory_revision=memory_revision),
        occurrence,
    )


def test_legacy_database_upgrades_without_losing_old_tables_and_restarts(tmp_path) -> None:
    path = tmp_path / "story.db"
    with sqlite3.connect(path) as legacy:
        legacy.execute(
            "CREATE TABLE history (scene TEXT, subject TEXT, turn INTEGER, entry TEXT NOT NULL)"
        )
        legacy.execute(
            "INSERT INTO history VALUES (?, ?, ?, ?)",
            ("scene.old", "char.old", 1, "{}"),
        )

    memory = SQLiteBehaviorMemory(path)
    memory.save_identity("book.hehuan", _identity())
    assert memory.schema_version == 1
    memory.close()

    restored = SQLiteBehaviorMemory(path)
    try:
        assert restored.load_identity("book.hehuan", "char.luo_han") == _identity()
        with sqlite3.connect(path) as raw:
            assert raw.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 1
    finally:
        restored.close()


def test_atomic_commit_is_queryable_and_idempotent(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    try:
        request, brief = _request(), _brief()
        draft, audit, extraction, accepted, occurrence = _accepted_bundle()
        memory.create_run(request, brief)
        memory.record_audit(draft, audit, extraction)

        committed = memory.commit_accepted(
            request.run_id, accepted, (occurrence,), accepted_revision=1
        )
        replayed = memory.commit_accepted(
            request.run_id, accepted, (occurrence,), accepted_revision=1
        )
        snapshot = memory.query_history(
            _position(beat=1285), "char.luo_han", HistoryWindowLimits()
        )

        assert committed.memory_revision == 1
        assert not committed.idempotent_replay
        assert replayed.model_copy(update={"idempotent_replay": False}) == committed
        assert replayed.idempotent_replay
        assert snapshot.memory_revision == 1
        assert snapshot.immediate == (occurrence,)
        assert snapshot.book == (occurrence,)
    finally:
        memory.close()


def test_concurrent_stale_audit_is_rejected_without_partial_commit(tmp_path) -> None:
    path = tmp_path / "story.db"
    first = SQLiteBehaviorMemory(path)
    second = SQLiteBehaviorMemory(path)
    requests = (
        _request("run.first", _position(beat=1284)),
        _request("run.second", _position(beat=1285)),
    )
    bundles = (
        _accepted_bundle("run.first", position=_position(beat=1284)),
        _accepted_bundle("run.second", position=_position(beat=1285)),
    )
    for memory, request, bundle in zip((first, second), requests, bundles):
        memory.create_run(request, _brief(request.run_id))
        memory.record_audit(bundle[0], bundle[1], bundle[2])

    def commit(memory, request, bundle):
        try:
            return memory.commit_accepted(
                request.run_id, bundle[3], (bundle[4],), accepted_revision=1
            )
        except MemoryRevisionConflict:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(
                pool.map(
                    lambda args: commit(*args),
                    ((first, requests[0], bundles[0]), (second, requests[1], bundles[1])),
                )
            )
        assert sum(outcome == "conflict" for outcome in outcomes) == 1
        snapshot = first.query_history(
            _position(beat=1286), "char.luo_han", HistoryWindowLimits()
        )
        assert snapshot.memory_revision == 1
        assert len(snapshot.book) == 1
    finally:
        first.close()
        second.close()


def _commit_behavior(
    memory: SQLiteBehaviorMemory,
    *,
    run_id: str,
    revision: int,
    position: NarrativePosition,
    actor_id: str,
) -> BehaviorOccurrence:
    request = _request(run_id, position, actor_id)
    bundle = _accepted_bundle(run_id, revision, position, actor_id)
    memory.create_run(request, _brief(run_id, revision))
    memory.record_audit(bundle[0], bundle[1], bundle[2])
    memory.commit_accepted(run_id, bundle[3], (bundle[4],), accepted_revision=1)
    return bundle[4]


def test_all_history_windows_have_cross_chapter_and_ensemble_scope(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    try:
        first = _commit_behavior(
            memory,
            run_id="run.chapter1",
            revision=0,
            position=_position(chapter="chapter.0001", scene="scene.0001.01", beat=1),
            actor_id="char.luo_han",
        )
        second = _commit_behavior(
            memory,
            run_id="run.chapter2",
            revision=1,
            position=_position(chapter="chapter.0002", scene="scene.0002.01", beat=2),
            actor_id="char.luo_han",
        )
        other = _commit_behavior(
            memory,
            run_id="run.other",
            revision=2,
            position=_position(chapter="chapter.0002", scene="scene.0002.01", beat=3),
            actor_id="char.other",
        )

        snapshot = memory.query_history(
            _position(chapter="chapter.0002", scene="scene.0002.01", beat=4),
            "char.luo_han",
            HistoryWindowLimits(),
        )

        assert snapshot.immediate == (first, second)
        assert snapshot.scene == (second,)
        assert snapshot.chapter == (second,)
        assert snapshot.recent_chapters == (first, second)
        assert snapshot.volume == (first, second)
        assert snapshot.book == (first, second)
        assert snapshot.ensemble == (first, second, other)[1:]
    finally:
        memory.close()


def test_legacy_rows_require_explicit_mapping_and_import_idempotently(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    entry = HistoryEntry(
        turn_index=7,
        unit_id="body.hand_clench",
        semantic_groups={"hand_tension"},
        channel="hands",
        intensity=0.6,
    )
    with sqlite3.connect(path) as legacy:
        legacy.execute(
            "CREATE TABLE history (scene TEXT, subject TEXT, turn INTEGER, entry TEXT NOT NULL)"
        )
        legacy.execute(
            "INSERT INTO history VALUES (?, ?, ?, ?)",
            ("scene.legacy", "char.luo_han", 7, entry.model_dump_json()),
        )
        legacy.execute(
            "INSERT INTO history VALUES (?, ?, ?, ?)",
            ("scene.unmapped", "char.other", 1, entry.model_dump_json()),
        )
    position = _position(
        chapter="chapter.legacy", scene="scene.legacy", beat=700
    ).model_copy(update={"beat_index": 7})
    text = "他攥紧手指。"
    mapping = LegacyHistoryMapping(
        legacy_history_rowid=1,
        position=position,
        text_span=TextSpan(start=0, end=len(text), text=text),
        narrative_functions=frozenset({"anger_leak"}),
        lexical_lemmas=("攥紧", "手指"),
    )

    memory = SQLiteBehaviorMemory(path)
    try:
        imported = memory.import_legacy_history((mapping,))
        replayed = memory.import_legacy_history((mapping,))
        snapshot = memory.query_history(
            position.model_copy(update={"global_beat_index": 701}),
            "char.luo_han",
        )
        assert imported == replayed
        assert imported[0].source == "human_confirmed"
        assert snapshot.book == imported
        assert snapshot.memory_revision == 1
        with sqlite3.connect(path) as raw:
            assert raw.execute("SELECT COUNT(*) FROM history").fetchone()[0] == 2
            assert raw.execute("SELECT COUNT(*) FROM legacy_behavior_imports").fetchone()[0] == 1
    finally:
        memory.close()


def test_backup_restore_recovers_committed_history_after_restart(tmp_path) -> None:
    original = tmp_path / "story.db"
    backup = tmp_path / "story.backup.db"
    restored_path = tmp_path / "restored.db"
    memory = SQLiteBehaviorMemory(original)
    occurrence = _commit_behavior(
        memory,
        run_id="run.backup",
        revision=0,
        position=_position(beat=10),
        actor_id="char.luo_han",
    )
    memory.backup(backup)
    memory.close()

    restored = SQLiteBehaviorMemory.restore_backup(backup, restored_path)
    try:
        snapshot = restored.query_history(_position(beat=11), "char.luo_han")
        assert snapshot.book == (occurrence,)
        assert snapshot.memory_revision == 1
    finally:
        restored.close()


def test_scene_state_failure_rolls_back_draft_occurrence_and_revision(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    request = _request("run.atomic", _position(beat=20))
    bundle = _accepted_bundle("run.atomic", position=_position(beat=20))
    memory.create_run(request, _brief("run.atomic"))
    memory.record_audit(bundle[0], bundle[1], bundle[2])
    invalid_state = request.scene_state.model_copy(update={"revision": 2})
    try:
        try:
            memory.commit_accepted(
                request.run_id,
                bundle[3],
                (bundle[4],),
                accepted_revision=1,
                scene_state=invalid_state,
                world_state=request.world_state,
            )
        except SceneRevisionConflict:
            pass
        else:
            raise AssertionError("invalid scene revision was accepted")
        assert memory.query_history(_position(beat=21), "char.luo_han").book == ()

        valid_state = request.scene_state.model_copy(update={"revision": 1, "pose": "standing"})
        result = memory.commit_accepted(
            request.run_id,
            bundle[3],
            (bundle[4],),
            accepted_revision=1,
            scene_state=valid_state,
            world_state=request.world_state,
        )
        assert result.memory_revision == 1
        assert memory.current_scene_state(request.position.scene_id, "char.luo_han") == (
            valid_state,
            request.world_state,
        )
    finally:
        memory.close()


def test_committed_global_position_cannot_be_overwritten(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    try:
        _commit_behavior(
            memory,
            run_id="run.owner",
            revision=0,
            position=_position(beat=30),
            actor_id="char.luo_han",
        )
        request = _request("run.competing", _position(beat=30), "char.other")
        bundle = _accepted_bundle(
            "run.competing", 1, _position(beat=30), "char.other"
        )
        memory.create_run(request, _brief("run.competing", 1))
        memory.record_audit(bundle[0], bundle[1], bundle[2])
        with pytest.raises(BehaviorCommitConflict, match="BEHAVIOR_COMMIT_CONFLICT"):
            memory.commit_accepted(
                request.run_id, bundle[3], (bundle[4],), accepted_revision=1
            )
        assert memory.query_history(_position(beat=31), "char.other").book == ()
        assert memory.query_history(_position(beat=31), "char.luo_han").memory_revision == 1
    finally:
        memory.close()


def test_history_query_plans_use_all_required_indexes(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    try:
        plans = memory.explain_history_query_plans(_position(), "char.luo_han")
        assert "idx_behavior_actor_position" in " ".join(plans["actor"])
        assert "idx_behavior_chapter_actor" in " ".join(plans["chapter"])
        assert "idx_behavior_scene_position" in " ".join(plans["scene"])
        assert "idx_behavior_actor_unit" in " ".join(plans["unit"])
        assert "idx_behavior_actor_channel" in " ".join(plans["channel"])
    finally:
        memory.close()


def test_failed_schema_migration_leaves_previous_version_readable(tmp_path) -> None:
    path = tmp_path / "migration.db"
    connection = sqlite3.connect(path, isolation_level=None)

    def broken_migration(db: sqlite3.Connection) -> None:
        db.execute("CREATE TABLE should_rollback (id INTEGER)")
        db.execute("THIS IS NOT SQL")

    try:
        with pytest.raises(sqlite3.OperationalError):
            migrate(connection, (broken_migration,))
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='should_rollback'"
        ).fetchone() is None
    finally:
        connection.close()


def test_idempotent_replay_returns_original_commit_revision(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    try:
        first = _accepted_bundle("run.original", position=_position(beat=40))
        memory.create_run(_request("run.original", _position(beat=40)), _brief("run.original"))
        memory.record_audit(first[0], first[1], first[2])
        original = memory.commit_accepted(
            "run.original", first[3], (first[4],), accepted_revision=1
        )
        _commit_behavior(
            memory,
            run_id="run.later",
            revision=1,
            position=_position(beat=41),
            actor_id="char.other",
        )

        replay = memory.commit_accepted(
            "run.original", first[3], (first[4],), accepted_revision=1
        )

        assert original.memory_revision == 1
        assert replay.memory_revision == 1
        assert replay.idempotent_replay
        assert memory.query_history(_position(beat=42), "char.luo_han").memory_revision == 2
    finally:
        memory.close()


def test_legacy_migration_cli_imports_validated_mapping(tmp_path) -> None:
    database = tmp_path / "legacy.db"
    mapping_path = tmp_path / "mapping.yaml"
    entry = HistoryEntry(
        turn_index=7,
        unit_id="body.hand_clench",
        semantic_groups={"hand_tension"},
        channel="hands",
        intensity=0.6,
    )
    with sqlite3.connect(database) as legacy:
        legacy.execute(
            "CREATE TABLE history (scene TEXT, subject TEXT, turn INTEGER, entry TEXT NOT NULL)"
        )
        legacy.execute(
            "INSERT INTO history VALUES (?, ?, ?, ?)",
            ("scene.legacy", "char.luo_han", 7, entry.model_dump_json()),
        )
    position = _position(
        chapter="chapter.legacy", scene="scene.legacy", beat=70
    ).model_copy(update={"beat_index": 7})
    mapping = LegacyHistoryMapping(
        legacy_history_rowid=1,
        position=position,
        text_span=TextSpan(start=0, end=6, text="他攥紧手指。"),
        narrative_functions=frozenset({"anger_leak"}),
    )
    mapping_path.write_text(
        yaml.safe_dump(
            {"mappings": [mapping.model_dump(mode="json")]},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "character_performance.cli.behavior_memory",
            "migrate-legacy",
            str(mapping_path),
            "--db",
            str(database),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    memory = SQLiteBehaviorMemory(database)
    try:
        assert len(memory.query_history(position.model_copy(update={"global_beat_index": 71}), "char.luo_han").book) == 1
    finally:
        memory.close()
