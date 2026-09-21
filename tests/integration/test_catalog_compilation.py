import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[2]


def load_compiler(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("test_catalog_compiler", ROOT / "tools/compile_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_catalog_file_fails_before_any_output_is_replaced(tmp_path, monkeypatch):
    compiler = load_compiler(monkeypatch)
    monkeypatch.setattr(compiler, "ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        compiler.read_records()
    assert list(tmp_path.iterdir()) == []


def test_quantity_gate_cannot_be_satisfied_with_navigation_units(pack):
    from character_performance.quality import catalog_report, require_catalog_quality
    report = catalog_report(pack)
    report["actual"]["spatial"] = 99
    report["quantity_gates"]["spatial"] = False
    with pytest.raises(ValueError, match="spatial:99<100"):
        require_catalog_quality(report)
