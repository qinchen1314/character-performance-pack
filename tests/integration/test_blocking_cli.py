import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).parents[2]


def test_cli_exports_one_shot_controls_and_clears_completed_goal(tmp_path):
    request = ROOT / "examples/blocking-scene.yaml"
    database = tmp_path / "story.db"
    output = tmp_path / "output"
    for control, elapsed in [("continue", "700"), ("pause", "0"), ("resume", "1300")]:
        command = [sys.executable, "-m", "character_performance.cli.perform", str(request),
            "--project-root", str(ROOT), "--db", str(database), "--commit", "--output", str(output),
            "--action-control", control, "--elapsed-ms", elapsed]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        request = output / "next-request.json"
        state = json.loads(request.read_text(encoding="utf-8"))
        assert state["action_control"] == "continue"
    assert state["blocking_goal"] is None
    assert state["scene_state"]["active_action"] is None
    assert state["scene_state"]["pose"] == "seated"
    assert state["scene_state"]["revision"] == 3


def test_cli_rejects_invalid_elapsed_before_creating_state(tmp_path):
    result = subprocess.run([sys.executable, "-m", "character_performance.cli.perform",
        str(ROOT / "examples/blocking-scene.yaml"), "--elapsed-ms", "-1", "--db", str(tmp_path / "state.db")],
        cwd=ROOT, capture_output=True, timeout=20)
    assert result.returncode == 2
    assert not (tmp_path / "state.db").exists()
