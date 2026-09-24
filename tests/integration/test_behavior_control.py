from __future__ import annotations

import pytest

from character_performance.behavior_control import BehaviorControlSystem
from character_performance.domain.behavior_models import (
    BehaviorIdentity,
    GenerationRequest,
    NarrativePosition,
    StyleContext,
)
from character_performance.domain.models import CharacterProfile, SceneState
from character_performance.memory import RunStateConflict, RunStatus, SQLiteBehaviorMemory


def _request(run_id: str = "run.control", beat: int = 1) -> GenerationRequest:
    position = NarrativePosition(
        book_id="book.control",
        volume_id="volume.1",
        chapter_id=f"chapter.{beat}",
        scene_id=f"scene.{beat}",
        paragraph_index=0,
        beat_index=0,
        global_beat_index=beat,
    )
    identity = BehaviorIdentity(
        character_id="char.hero",
        version=1,
        default_strategies={"conflict": "observe"},
        preferred_channels={"gaze": 0.9, "speech_rhythm": 0.7},
        avoided_channels={"hands": 0.8},
        values={"self_control"},
        taboos={"public_pleading"},
        coping_strategies={"observe"},
        social_masks={"public": "courtesy", "private": "quiet"},
    )
    return GenerationRequest(
        run_id=run_id,
        position=position,
        character=CharacterProfile(id="char.hero"),
        behavior_identity=identity,
        scene_state=SceneState(scene_id=position.scene_id),
        style_context=StyleContext(
            pov="third_limited", prose_style="restrained", paragraph_function="reaction"
        ),
    )


def test_preview_is_isolated_and_formal_run_commits_idempotently(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    system = BehaviorControlSystem(repository=memory)
    request = _request()

    preview = system.preview(request)
    with pytest.raises(KeyError):
        memory.run_status(request.run_id)

    brief = system.prepare(request)
    audit = system.audit(request.run_id, "他没有回答。")
    assert preview == brief
    assert audit.accepted

    first = system.commit_text(request.run_id, "他没有回答。")
    replay = system.commit_text(request.run_id, "他没有回答。")
    assert first.memory_revision == 1
    assert replay.idempotent_replay
    assert replay.occurrence_ids == first.occurrence_ids
    assert memory.run_status(request.run_id) is RunStatus.COMMITTED
    memory.close()


def test_restart_recovers_passed_audit_and_commits(tmp_path) -> None:
    path = tmp_path / "story.db"
    first = SQLiteBehaviorMemory(path)
    system = BehaviorControlSystem(repository=first)
    request = _request("run.restart")
    system.prepare(request)
    assert system.audit(request.run_id, "他没有回答。").accepted
    first.close()

    restored = SQLiteBehaviorMemory(path)
    resumed = BehaviorControlSystem(repository=restored)
    recovery = resumed.recover(request.run_id)
    assert recovery.status is RunStatus.AUDITED_PASSED
    assert recovery.draft is not None
    assert recovery.audit is not None and recovery.audit.accepted
    result = resumed.commit_text(request.run_id, recovery.draft.text)
    assert result.memory_revision == 1
    restored.close()


def test_failed_audit_cannot_commit_or_skip_rewrite(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    system = BehaviorControlSystem(repository=memory)

    first = _request("run.first", 1)
    system.prepare(first)
    assert system.audit(first.run_id, "他皱眉。").accepted
    system.commit_text(first.run_id, "他皱眉。")

    second = _request("run.second", 2)
    system.prepare(second)
    failed = system.audit(second.run_id, "他皱眉。")
    assert not failed.accepted
    assert memory.run_status(second.run_id) is RunStatus.AUDITED_FAILED
    with pytest.raises(ValueError, match="AUDIT_BLOCKED"):
        system.commit_text(second.run_id, "他皱眉。")
    with pytest.raises(ValueError, match="rewrite must precede"):
        system.audit(second.run_id, "他皱眉。")
    memory.close()


def test_rewrite_can_be_reaudited_with_documented_text_only_draft_shape(tmp_path) -> None:
    memory = SQLiteBehaviorMemory(tmp_path / "story.db")
    system = BehaviorControlSystem(repository=memory)
    request = _request("run.rewrite")
    original = "他握拳。“好。”"
    system.prepare(request)

    failed = system.audit(request.run_id, original)
    assert not failed.accepted and failed.auto_rewrite_allowed
    revised = system.rewrite(request.run_id, original, failed)
    recovery = system.recover(request.run_id)

    assert recovery.status is RunStatus.AUDITED_PASSED
    assert recovery.audit is not None and recovery.audit.accepted
    assert recovery.extraction is not None

    passed = system.audit(request.run_id, revised)

    assert passed.accepted
    assert "好" in revised
    assert system.commit_text(request.run_id, revised).memory_revision == 1
    memory.close()
