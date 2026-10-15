"""Isolated owner tests; preserve every attempted run and raw exit status."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
destination = ROOT / "results/upgrade_validation_round_002/output_gap_oct09" / sys.argv[1]
destination.mkdir(parents=True, exist_ok=False)
snapshot = destination / "snapshot"
snapshot.mkdir()
shutil.copytree(ROOT / "src", snapshot / "src", ignore=shutil.ignore_patterns("__pycache__"))
(snapshot / "tests").mkdir()
shutil.copy2(ROOT / "tests/test_output_gap_estimation.py", snapshot / "tests/test_output_gap_estimation.py")
files = [ROOT / "src/data_pipeline/output_gap_estimation.py", ROOT / "tests/test_output_gap_estimation.py",
         ROOT / "research/source_ledgers/output_gap_round002/protocol_v1.json"]
hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
command = [str(ROOT / ".venv/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_output_gap_estimation.py"]
env = dict(os.environ, PYTHONPATH=str(snapshot), PYTHONDONTWRITEBYTECODE="1")
receipt = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "command": command,
    "working_directory": str(snapshot.relative_to(ROOT)), "inputs_sha256": hashes,
    "python_executable": str(ROOT / ".venv/bin/python"), "python_version": sys.version,
    "platform": platform.platform(), "network_or_provider_calls": 0,
    "evidence_scope": "Synthetic engineering controls and corruption/failure checks only"}
(destination / "command.json").write_text(json.dumps(receipt, indent=2) + "\n")
with (destination / "pytest.log").open("w") as log:
    result = subprocess.run(command, cwd=snapshot, env=env, stdout=log, stderr=subprocess.STDOUT)
receipt.update(exit_code=result.returncode, finished_at_utc=datetime.now(timezone.utc).isoformat(),
               inputs_unchanged={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() == hashes[str(p.relative_to(ROOT))] for p in files})
(destination / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print((destination / "pytest.log").read_text())
print(json.dumps(receipt, indent=2))
raise SystemExit(result.returncode)
