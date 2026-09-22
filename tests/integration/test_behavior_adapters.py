from __future__ import annotations

import json
import sys

import yaml

from character_performance.cli.behavior import main
from character_performance.domain.behavior_models import (
    BehaviorIdentity,
    ExtractionRequest,
    GenerationBrief,
    GenerationRequest,
    NarrativePosition,
    StyleContext,
)
from character_performance.domain.models import CharacterProfile, SceneState
from character_performance.memory import RunStatus, SQLiteBehaviorMemory


def _position() -> NarrativePosition:
    return NarrativePosition(
        book_id="book.cli",
        chapter_id="chapter.1",
        scene_id="scene.1",
        paragraph_index=0,
        beat_index=0,
        global_beat_index=1,
    )


def _generation_request() -> GenerationRequest:
    return GenerationRequest(
        run_id="run.cli",
        position=_position(),
        character=CharacterProfile(id="char.a"),
        behavior_identity=BehaviorIdentity(
            character_id="char.a",
            version=1,
            default_strategies={"conflict": "conceal_then_counter"},
            preferred_channels={"gaze": 0.8, "speech_rhythm": 0.7},
            values=frozenset({"self_control"}),
            taboos=frozenset({"public_pleading"}),
            coping_strategies=frozenset({"observe"}),
            social_masks={"public": "controlled", "private": "terse", "intimate": "open"},
        ),
        scene_state=SceneState(scene_id="scene.1"),
        style_context=StyleContext(
            pov="third_limited", prose_style="concise", paragraph_function="reaction"
        ),
    )


def test_prepare_cli_writes_brief_prompt_and_durable_run(tmp_path, monkeypatch, capsys) -> None:
    request_path = tmp_path / "request.yaml"
    database = tmp_path / "story.db"
    output = tmp_path / "run"
    request_path.write_text(
        yaml.safe_dump(_generation_request().model_dump(mode="json"), allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cpp-behavior",
            "prepare",
            str(request_path),
            "--db",
            str(database),
            "--output",
            str(output),
        ],
    )
    main()

    summary = json.loads(capsys.readouterr().out)
    brief = GenerationBrief.model_validate_json((output / "brief.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == "run.cli"
    assert (output / "prompt.txt").read_text(encoding="utf-8").strip() == brief.prompt_fragment
    memory = SQLiteBehaviorMemory(database)
    try:
        assert memory.run_status("run.cli") is RunStatus.PREPARED
    finally:
        memory.close()


def test_extract_cli_writes_validated_rule_result(tmp_path, monkeypatch, capsys) -> None:
    text = "他把指甲掐进掌心，沉默片刻。"
    request = ExtractionRequest(
        run_id="run.extract",
        text=text,
        known_characters=(CharacterProfile(id="char.a"),),
        position=_position(),
    )
    request_path = tmp_path / "extract.yaml"
    output = tmp_path / "extraction.json"
    request_path.write_text(
        yaml.safe_dump(request.model_dump(mode="json"), allow_unicode=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["cpp-behavior", "extract", str(request_path), "--output", str(output)],
    )
    main()

    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert summary["behaviors"] == 2
    assert [item["canonical_action"] for item in payload["behaviors"]] == [
        "hand_clench",
        "delay_response",
    ]
