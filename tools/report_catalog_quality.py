"""Write the reproducible catalog coverage and duplicate-candidate reports."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from character_performance.ontology.pack import PerformancePack
from character_performance.quality import catalog_report, require_catalog_quality


def main():
    report = catalog_report(PerformancePack.from_project(ROOT))
    require_catalog_quality(report)
    output = ROOT / "docs/evaluation/catalog-quality.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = ["# 目录质量报告", "", "## 十类覆盖", "", "| 类别 | 目标 | 实际 |", "|---|---:|---:|"]
    markdown.extend(f"| {key} | {minimum} | {report['actual'][key]} |" for key, minimum in report["targets"].items())
    markdown += ["", "## 重复与情绪覆盖", "",
        f"- 完全相同中文实现：{len(report['exact_duplicate_pairs'])} 对",
        f"- 二元组 Dice ≥ 0.82 的近重复候选：{len(report['near_duplicate_pairs'])} 对",
        f"- 近重复涉及单元比例：{report['near_duplicate_unit_fraction']:.2%}",
        f"- 共享语义家族：{report['semantic_family_count']} 个",
        f"- 情绪：{len(report['emotion_coverage'])} 种；每种至少 3 个候选、2 个通道", "",
        "近重复指标用于筛选人工复核候选，不等同于文学盲评或行为科学结论。", ""]
    output.with_suffix(".md").write_text("\n".join(markdown), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
