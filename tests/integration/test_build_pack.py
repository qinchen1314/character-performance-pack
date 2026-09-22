from pathlib import Path

import pytest

from character_performance.build import PackBuildError, build_pack
from character_performance.sources.registry import BuildPolicy


ROOT = Path(__file__).parents[2]


def test_build_pack_emits_manifest_and_json_schemas(tmp_path: Path) -> None:
    result = build_pack(
        project_root=ROOT,
        output_dir=tmp_path,
        policy=BuildPolicy(commercial=False, redistribution=False),
    )

    assert result.manifest_path.exists()
    assert result.schema_paths
    assert result.manifest["schema_version"] == "1.0.0"
    assert result.manifest["emotion_count"] >= 9
    assert len(result.manifest["content_hash"]) == 64
    schema_names = {path.name for path in result.schema_paths}
    assert "PerformanceRequest.schema.json" in schema_names
    assert "SceneState.schema.json" in schema_names


def test_build_pack_rejects_unapproved_source_reference(tmp_path: Path) -> None:
    with pytest.raises(PackBuildError, match="source review status is pending"):
        build_pack(
            project_root=ROOT,
            output_dir=tmp_path,
            policy=BuildPolicy(commercial=False, redistribution=False),
            extra_source_ids=("src.samm.v1",),
        )
