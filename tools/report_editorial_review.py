"""Report editorial pre-cleaning without claiming uncollected human votes."""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from character_performance.catalog import CatalogRecord


CATALOG_FILES = (
    "micro.json",
    "face-gaze.json",
    "body.json",
    "spatial.json",
    "physiology.json",
    "speech.json",
    "xianxia.json",
)


def main() -> None:
    rejected = []
    for name in CATALOG_FILES:
        rows = json.loads((ROOT / "data" / "catalog" / name).read_text(encoding="utf-8"))
        for raw in rows:
            record = CatalogRecord.model_validate(raw)
            if record.editorial_status == "rejected":
                rejected.append(
                    {
                        "id": record.id,
                        "category": record.category,
                        "clause": record.clause,
                        "reason": record.editorial_note,
                        "replacement_id": record.replacement_id,
                    }
                )
    payload = {
        "review_type": "editorial_preclean",
        "human_blind_review_completed": False,
        "decision_policy": (
            "编辑预清理仅淘汰明显机械、生硬或正文价值过低的条目；"
            "不得计作独立真人盲评票。"
        ),
        "rejected_count": len(rejected),
        "rejected": rejected,
    }
    output = ROOT / "output" / "evaluation" / "editorial-preclean.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 编辑预清理报告",
        "",
        "> 这不是已完成的真人盲评，也不虚构评审者或票数。它是盲评前的编辑预清理。",
        "",
        f"共停用 {len(rejected)} 条。原始记录以 deprecated 保留供旧计划兼容，新规划不会选用。",
        "",
        "| ID | 原句 | 替代项 | 停用理由 |",
        "|---|---|---|---|",
        *(f"| `{row['id']}` | {row['clause']} | `{row['replacement_id']}` | {row['reason']} |" for row in rejected),
        "",
    ]
    output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
