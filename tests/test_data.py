# SPDX-License-Identifier: Apache-2.0
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dataset_validates_against_schema_and_integrity_checks():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "validate.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_build_is_reproducible_from_workbook_export(tmp_path):
    """data/*.json must be exactly what tools/build_data.py produces."""
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location("build_data", ROOT / "tools" / "build_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.OUT = tmp_path
    assert mod.build() == 0
    for name in ("controls", "frameworks", "domains"):
        fresh = json.loads((tmp_path / f"{name}.json").read_text(encoding="utf-8"))
        committed = json.loads((ROOT / "data" / f"{name}.json").read_text(encoding="utf-8"))
        assert fresh == committed, f"data/{name}.json is stale: run python tools/build_data.py"
