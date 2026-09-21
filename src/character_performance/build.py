from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from character_performance.domain.models import (
    EmotionState,
    PerformancePlan,
    PerformanceUnit,
)
from character_performance.ontology.emotion import EmotionOntology
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


SCHEMA_MODELS: tuple[type[BaseModel], ...] = (
    EmotionState,
    PerformanceUnit,
    PerformancePlan,
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def build_pack(
    project_root: Path,
    output_dir: Path,
    policy: BuildPolicy,
    extra_source_ids: tuple[str, ...] = (),
) -> PackBuildResult:
    registry = SourceRegistry.from_yaml(project_root / "data" / "sources" / "registry.yaml")
    ontology = EmotionOntology.from_yaml(
        project_root / "data" / "ontology" / "emotion" / "emotions.yaml"
    )

    source_ids = sorted(
        {
            source_id
            for emotion in ontology.all()
            for source_id in emotion.source_refs
        }
        | set(extra_source_ids)
    )
    try:
        decision = registry.validate_for_build(source_ids, policy)
    except LicenseGateError as error:
        raise PackBuildError(str(error)) from error

    emotions = [emotion.model_dump(mode="json") for emotion in ontology.all()]
    content_hash = sha256(_canonical_json(emotions)).hexdigest()
    manifest: dict[str, Any] = {
        "pack_version": "0.1.0",
        "schema_version": "1.0.0",
        "source_registry_version": registry.schema_version,
        "emotion_count": len(emotions),
        "source_ids": list(decision.approved_source_ids),
        "content_hash": content_hash,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    schema_dir = output_dir / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)

    emotion_path = output_dir / "emotions.json"
    emotion_path.write_text(
        json.dumps(emotions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    schema_paths: list[Path] = []
    for model in SCHEMA_MODELS:
        path = schema_dir / f"{model.__name__}.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        schema_paths.append(path)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return PackBuildResult(manifest_path, tuple(schema_paths), manifest)

