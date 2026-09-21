from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from character_performance.cli.export_schemas import export_schemas
from character_performance.ontology.pack import PerformancePack, canonical
from character_performance.sources.registry import (
    BuildPolicy,
    LicenseGateError,
    SourceRegistry,
)


class PackBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class PackBuildResult:
    manifest_path: Path
    schema_paths: tuple[Path, ...]
    manifest: dict[str, Any]


def build_pack(
    project_root: Path,
    output_dir: Path,
    policy: BuildPolicy,
    extra_source_ids: tuple[str, ...] = (),
) -> PackBuildResult:
    registry = SourceRegistry.from_yaml(project_root / "data" / "sources" / "registry.yaml")
    try:
        registry.validate_for_build(extra_source_ids, policy)
        pack = PerformancePack.from_project(project_root, policy)
    except (LicenseGateError, ValueError) as error:
        raise PackBuildError(str(error)) from error
    source_ids = sorted(set(pack.source_ids) | set(extra_source_ids))
    payload = json.loads(canonical(pack.payload()))
    manifest: dict[str, Any] = {
        "pack_version": pack.version,
        "schema_version": "1.0.0",
        "source_registry_version": registry.schema_version,
        "emotion_count": len(pack.ontology),
        "unit_count": len(pack.all()),
        "source_ids": source_ids,
        "content_hash": pack.content_hash,
        "build_policy": {"commercial": policy.commercial, "redistribution": policy.redistribution, "allow_share_alike": policy.allow_share_alike},
        "sources": [registry.get(ref).model_dump(mode="json") for ref in source_ids],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    schema_dir = output_dir / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)

    for filename, value in [("pack.json", payload), ("emotions.json", payload["emotions"]), ("units.json", payload["units"])]:
        (output_dir / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    schema_paths = export_schemas(schema_dir)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return PackBuildResult(manifest_path, tuple(schema_paths), manifest)
