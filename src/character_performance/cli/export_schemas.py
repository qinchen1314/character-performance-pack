from __future__ import annotations

import argparse
import json
from pathlib import Path

from character_performance.domain.models import (
    CharacterProfile, EmotionState, PerformancePlan, PerformanceRequest,
    PerformanceUnit, RenderContext, RenderResult, SceneState, WorldState,
)
from character_performance.modifiers import Modifier

SCHEMA_MODELS = (
    EmotionState, PerformanceUnit, PerformanceRequest, PerformancePlan,
    CharacterProfile, SceneState, WorldState, RenderContext, RenderResult, Modifier,
)


def export_schemas(output_dir: Path) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for model in SCHEMA_MODELS:
        path = output_dir / f"{model.__name__}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export canonical JSON schemas")
    parser.add_argument("--output", type=Path, default=Path("schemas"))
    args = parser.parse_args()
    for path in export_schemas(args.output):
        print(path)


if __name__ == "__main__":
    main()
