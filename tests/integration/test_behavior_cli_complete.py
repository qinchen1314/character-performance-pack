from __future__ import annotations

import json
import sys

import pytest
import yaml

from character_performance.cli.behavior import main
from character_performance.domain.behavior_models import (
    AuditResult,
    BehaviorIdentity,
    GenerationRequest,
    NarrativePosition,
    StyleContext,
)
from character_performance.domain.models import CharacterProfile, SceneState


def _request(run_id: str = "run.cli.complete") -> GenerationRequest:
    position = NarrativePosition(
        book_id="book.cli.complete",
        volume_id="volume.1",
        chapter_id="chapter.1",
        scene_id="scene.1",
        paragraph_index=0,
        beat_index=0,
        global_beat_index=1,
    )
    return GenerationRequest(
        run_id=run_id,
        position=position,
        character=CharacterProfile(id="char.hero"),
        behavior_identity=BehaviorIdentity(
            character_id="char.hero",
            version=1,
            default_strategies={"conflict": "observe"},
            preferred_channels={"gaze": 0.9, "speech_rhythm": 0.8},
            avoided_channels={"hands": 0.9},
            values={"self_control"},
            taboos={"public_pleading"},
            coping_strategies={"observe"},
            social_masks={"public": "courtesy", "private": "quiet"},
        ),
        scene_state=SceneState(scene_id=position.scene_id),
        style_context=StyleContext(
            pov="third_limited", prose_style="restrained", paragraph_function="reaction"
        ),
    )


def _invoke(monkeypatch, capsys, *argv: str) -> dict[str, object]:
    monkeypatch.setattr(sys, "argv", ["cpp-behavior", *argv])
    main()
    return json.loads(capsys.readouterr().out)


def test_cli_audit_commit_and_reports_form_one_durable_workflow(
    tmp_path, monkeypatch, capsys
) -> None:
    database = tmp_path / "story.db"
    run_dir = tmp_path / "run"
    request_path = tmp_path / "request.yaml"
    draft_path = tmp_path / "draft.txt"
    audit_path = run_dir / "audit.json"
    request_path.write_text(
        yaml.safe_dump(_request().model_dump(mode="json"), allow_unicode=True),
        encoding="utf-8",
    )
    draft_path.write_text("他没有回答。", encoding="utf-8")

    prepared = _invoke(
        monkeypatch,
        capsys,
        "prepare",
        str(request_path),
        "--db",
        str(database),
        "--output",
        str(run_dir),
    )
    assert prepared["event"] == "behavior.prepare.completed"

    audited = _invoke(
        monkeypatch,
        capsys,
        "audit",
        str(run_dir / "brief.json"),
        str(draft_path),
        "--db",
        str(database),
        "--output",
        str(audit_path),
    )
    assert audited["accepted"] is True
    assert AuditResult.model_validate_json(audit_path.read_text(encoding="utf-8")).accepted

    committed = _invoke(
        monkeypatch,
        capsys,
        "commit",
        str(audit_path),
        str(draft_path),
        "--db",
        str(database),
    )
    assert committed["event"] == "behavior.commit.completed"
    assert committed["memory_revision"] == 1

    for suffix in ("md", "html"):
        output = tmp_path / f"behavior.{suffix}"
        reported = _invoke(
            monkeypatch,
            capsys,
            "report",
            "--book",
            "book.cli.complete",
            "--db",
            str(database),
            "--output",
            str(output),
        )
        assert reported["event"] == "behavior.report.completed"
        text = output.read_text(encoding="utf-8")
        assert "book.cli.complete" in text
        assert "角色行为分布" in text
        assert "章节重复热点" in text
        assert "句法模板热点" in text


def test_cli_rewrite_is_targeted_and_requires_reaudit(tmp_path, monkeypatch, capsys) -> None:
    database = tmp_path / "story.db"
    run_dir = tmp_path / "run"
    request_path = tmp_path / "request.yaml"
    draft_path = tmp_path / "draft.txt"
    audit_path = run_dir / "audit.json"
    revised_path = run_dir / "revised.txt"
    request_path.write_text(
        yaml.safe_dump(_request("run.cli.rewrite").model_dump(mode="json"), allow_unicode=True),
        encoding="utf-8",
    )
    draft_path.write_text("他握拳。“好。”", encoding="utf-8")
    _invoke(monkeypatch, capsys, "prepare", str(request_path), "--db", str(database), "--output", str(run_dir))
    audited = _invoke(monkeypatch, capsys, "audit", str(run_dir / "brief.json"), str(draft_path), "--db", str(database), "--output", str(audit_path))
    assert audited["accepted"] is False

    rewritten = _invoke(monkeypatch, capsys, "rewrite", str(audit_path), str(draft_path), "--db", str(database), "--output", str(revised_path))
    assert rewritten["event"] == "behavior.rewrite.completed"
    assert "好" in revised_path.read_text(encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _invoke(monkeypatch, capsys, "commit", str(audit_path), str(revised_path), "--db", str(database))
    assert exc.value.code == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error_code"] == "AUDIT_BLOCKED"
