"""Rebuild everything under dist/ from source/*.yaml.

    python ontology/nx_v1_1/build/build_all.py

  1 gen_tbox     source -> dist/cncgaide_nx.ttl
  2 gen_rules    source -> dist/rules/*.ru
  3 gen_shapes   source -> dist/shapes.ttl
  4 gen_page     source -> dist/cncgaide_nx_structure.html (when present)
  5 validate     source and dist checks -> docs/validation_report.md

Validation runs last so that it sees everything this build produced: the CJK
check and the byte-for-byte reproducibility check cover the page as well.

The bootstrap (bootstrap_from_nx.py) is not part of the chain: it reads the NX
install and writes the two transcribed YAML files once.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
steps = ["gen_tbox.py", "gen_rules.py", "gen_shapes.py"]
if (HERE / "gen_page.py").is_file():
    steps.append("gen_page.py")
steps.append("validate.py")
env = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"}
for step in steps:
    print(f"\n=== {step}")
    result = subprocess.run([sys.executable, str(HERE / step)], cwd=str(HERE.parents[2]), env=env)
    if result.returncode != 0:
        print(f"!!! {step} failed with exit code {result.returncode}")
        sys.exit(result.returncode)
print("\nall steps passed")
