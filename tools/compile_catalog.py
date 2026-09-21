"""Rebuild the complete original pack from individually authored records."""
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from character_performance.catalog import CatalogRecord, compile_record
from character_performance.ontology.emotion import EmotionOntology, EmotionOntologyDocument
from character_performance.ontology.pack import PerformancePack
from character_performance.quality import catalog_report, require_catalog_quality
from seed_original_units import generate_units

CATALOG_FILES = ("micro.json", "face-gaze.json", "body.json", "spatial.json", "physiology.json", "speech.json", "xianxia.json")


def read_records():
    return tuple(CatalogRecord.model_validate(record) for name in CATALOG_FILES
        for record in json.loads((ROOT / "data/catalog" / name).read_text(encoding="utf-8")))


def main():
    emotion_path = ROOT / "data/ontology/emotion/emotions.yaml"
    emotion_doc = yaml.safe_load(emotion_path.read_text(encoding="utf-8"))
    original_emotions = [row for row in emotion_doc["emotions"] if "src.original.catalog.v1" not in row["source_refs"]]
    added_emotions = json.loads((ROOT / "data/catalog/emotions.json").read_text(encoding="utf-8"))
    emotion_doc["emotions"] = original_emotions + added_emotions
    ontology = EmotionOntology(EmotionOntologyDocument.model_validate(emotion_doc))
    # Original seed VAD uses the original 18 labels; compilation does not require
    # writing partially validated output to make expanded labels available.
    units = generate_units() + [compile_record(record, ontology).model_dump(mode="json", exclude_defaults=True) for record in read_records()]
    modifier_path = ROOT / "data/modifiers/rules.yaml"
    modifier_doc = yaml.safe_load(modifier_path.read_text(encoding="utf-8"))
    modifiers = [row for row in modifier_doc["modifiers"] if "src.original.catalog.v1" not in row.get("source_refs", [])]
    modifiers += json.loads((ROOT / "data/catalog/modifiers.json").read_text(encoding="utf-8"))
    from character_performance.domain.models import PerformanceUnit
    from character_performance.modifiers import Modifier
    # Validate every record and reference before replacing any production file.
    pack = PerformancePack(ontology, tuple(PerformanceUnit.model_validate(row) for row in units),
        tuple(sorted({ref for row in units for ref in row["source_refs"]} | {ref for row in emotion_doc["emotions"] for ref in row["source_refs"]})),
        tuple(Modifier.model_validate(row) for row in modifiers))
    require_catalog_quality(catalog_report(pack))
    for path, payload in ((emotion_path, emotion_doc), (ROOT / "data/ontology/units.yaml", {"schema_version": "1.0.0", "units": units}),
                          (modifier_path, {"schema_version": "1.0.0", "modifiers": modifiers})):
        path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Compiled {len(ontology)} emotions, {len(units)} behaviours, {len(modifiers)} modifiers; {pack.content_hash}")


if __name__ == "__main__":
    main()
