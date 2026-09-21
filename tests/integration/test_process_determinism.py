import os
from pathlib import Path
import subprocess
import sys


def test_plan_is_stable_across_python_hash_seeds():
    root = Path(__file__).parents[2]
    code = """
from pathlib import Path
import yaml
from character_performance import PerformanceEngine, PerformancePack
from character_performance.domain import PerformanceRequest
from character_performance.ontology.pack import canonical
root = Path.cwd()
pack = PerformancePack.from_project(root)
request = PerformanceRequest.model_validate(yaml.safe_load((root / 'examples/novel-scene.yaml').read_text(encoding='utf-8')))
print(canonical(PerformanceEngine(pack).plan(request).model_dump(mode='python')).hex())
"""
    outputs = []
    for seed in ("1", "973"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root / "src")}
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=root, env=env, timeout=20))
    assert outputs[0] == outputs[1]
