from __future__ import annotations

import json
from hashlib import sha256

import yaml

from character_performance.cli.acceptance import main


def test_calibrate_command_writes_json_markdown_and_policy(tmp_path, monkeypatch) -> None:
    novel = tmp_path / "novel.txt"
    novel.write_text("第1章 开始\n他看向门外。\n第2章 后续\n他沉默片刻。", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "minimum_occurrences_per_chapter": 1,
                "samples": [
                    {"id": "accepted", "role": "quality", "path": novel.name, "human_accepted": True}
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    markdown = tmp_path / "report.md"
    policy = tmp_path / "thresholds.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "cpp-behavior-verify",
            "calibrate",
            str(manifest),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--policy-output",
            str(policy),
        ],
    )

    main()

    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "provisional"
    assert "优质正文分布" in markdown.read_text(encoding="utf-8")
    policy_payload = json.loads(policy.read_text(encoding="utf-8"))
    assert policy_payload["status"] == "provisional"
    assert policy_payload["source_report_sha256"] == (
        "sha256:" + sha256(output.read_bytes()).hexdigest()
    )
