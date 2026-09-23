from __future__ import annotations

import json

import yaml
import pytest

from character_performance.calibration import CalibrationManifest, calibrate_manifest
from character_performance.gate_policy import load_gate_policy


def _write_book(path, chapters: list[str]) -> None:
    path.write_text(
        "\n".join(
            f"第{index}章 样本{index}\n{text}"
            for index, text in enumerate(chapters, start=1)
        ),
        encoding="utf-8",
    )


def test_calibration_builds_all_four_evidence_views_and_publishable_policy(tmp_path) -> None:
    control = "sha256:" + "1" * 64
    characters = [{"id": "char.a", "aliases": ["他", "她"]}]
    quality = tmp_path / "quality.txt"
    formulaic = tmp_path / "formulaic.txt"
    off = tmp_path / "off.txt"
    on = tmp_path / "on.txt"
    sweep_low = tmp_path / "sweep-low.txt"
    sweep_mid = tmp_path / "sweep-mid.txt"
    sweep_high = tmp_path / "sweep-high.txt"
    _write_book(quality, ["他看向窗外。她后退一步。", "他沉默片刻，随后走近。"])
    _write_book(formulaic, ["他皱眉。他皱眉。他皱眉。", "他深吸一口气，又深吸一口气。"])
    _write_book(off, ["他皱眉。他皱眉。他皱眉。"])
    _write_book(on, ["他看向窗外，随后退后半步。"])
    _write_book(sweep_low, ["他皱眉。他皱眉。"])
    _write_book(sweep_mid, ["他皱眉，随后看向窗外。"])
    _write_book(sweep_high, ["他后退一步，又沉默片刻。"])
    manifest = tmp_path / "calibration.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "minimum_occurrences_per_chapter": 1,
                "readiness": {
                    "minimum_quality_chapters": 2,
                    "minimum_formulaic_chapters": 2,
                    "minimum_pairs": 1,
                    "minimum_sweep_strengths": 3,
                    "minimum_ratings_per_strength": 2,
                },
                "samples": [
                    {"id": "quality", "role": "quality", "path": quality.name, "human_accepted": True, "characters": characters},
                    {"id": "formulaic", "role": "formulaic", "path": formulaic.name, "human_accepted": True, "characters": characters},
                    {"id": "pair.off", "role": "system_off", "path": off.name, "pair_id": "pair.1", "control_fingerprint": control, "characters": characters},
                    {"id": "pair.on", "role": "system_on", "path": on.name, "pair_id": "pair.1", "control_fingerprint": control, "characters": characters},
                    {"id": "sweep.0", "role": "sweep", "path": sweep_low.name, "sweep_id": "sweep.1", "control_fingerprint": control, "strength": 0.0, "naturalness_ratings": [2, 3], "characters": characters},
                    {"id": "sweep.5", "role": "sweep", "path": sweep_mid.name, "sweep_id": "sweep.1", "control_fingerprint": control, "strength": 0.5, "naturalness_ratings": [4, 4], "characters": characters},
                    {"id": "sweep.1", "role": "sweep", "path": sweep_high.name, "sweep_id": "sweep.1", "control_fingerprint": control, "strength": 1.0, "naturalness_ratings": [3, 4], "characters": characters},
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    report = calibrate_manifest(manifest)

    assert report.status == "ready"
    assert report.distributions["quality"].chapter_count == 2
    assert report.distributions["formulaic"].chapter_count == 2
    assert report.paired_comparisons[0].pair_id == "pair.1"
    assert report.paired_comparisons[0].repeat_rate_delta > 0
    assert [point.strength for point in report.tradeoff_curve] == [0.0, 0.5, 1.0]
    assert report.recommended_strength == 0.5
    assert set(report.recommended_thresholds) == {
        "IMMEDIATE_EXACT_REPEAT_RATE",
        "CLICHE_GROUP_SHARE",
        "MAX_CHARACTER_CHANNEL_SHARE",
    }
    policy_path = tmp_path / "thresholds.json"
    policy_path.write_text(report.policy_json(), encoding="utf-8")
    policy = load_gate_policy(policy_path, require_ready=True)
    assert policy.status == "ready"


def test_quality_only_baseline_is_provisional_and_cannot_be_published(tmp_path) -> None:
    quality = tmp_path / "quality.txt"
    _write_book(quality, ["他看向窗外。", "他退后半步。"])
    manifest = tmp_path / "calibration.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "minimum_occurrences_per_chapter": 1,
                "synthetic_formulaic": {"stock_repetitions_per_chapter": 2},
                "samples": [
                    {"id": "quality", "role": "quality", "path": quality.name, "human_accepted": True}
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    report = calibrate_manifest(manifest)

    assert report.status == "provisional"
    assert "formulaic_distribution" in report.missing_evidence
    assert "formulaic" not in report.distributions
    assert report.distributions["synthetic_formulaic"].chapter_count == 2
    assert any(source.path.startswith("derived://") for source in report.sources)
    policy = json.loads(report.policy_json())
    assert policy["status"] == "provisional"


def test_pair_controls_must_share_the_same_input_fingerprint() -> None:
    with pytest.raises(ValueError, match="share one control_fingerprint"):
        CalibrationManifest.model_validate(
            {
                "version": 1,
                "samples": [
                    {
                        "id": "off",
                        "role": "system_off",
                        "path": "off.txt",
                        "pair_id": "pair.1",
                        "control_fingerprint": "sha256:" + "1" * 64,
                    },
                    {
                        "id": "on",
                        "role": "system_on",
                        "path": "on.txt",
                        "pair_id": "pair.1",
                        "control_fingerprint": "sha256:" + "2" * 64,
                    },
                ],
            }
        )


def test_gate_policy_rejects_non_finite_rate_threshold(tmp_path) -> None:
    policy = tmp_path / "thresholds.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "status": "ready",
                "source_report_sha256": "sha256:" + "a" * 64,
                "gates": {
                    "CLICHE_GROUP_SHARE": {
                        "threshold": float("inf"),
                        "comparator": "<=",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid threshold"):
        load_gate_policy(policy)
