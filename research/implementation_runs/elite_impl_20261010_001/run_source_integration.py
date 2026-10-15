"""Bounded, zero-provider integration of real sources with explicit mock output."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv/bin/python"
OUT = RUN / "source_integration_attempt_001"
OUT.mkdir(exist_ok=False)
env = {key: value for key, value in os.environ.items() if not any(tag in key for tag in ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN"))}
env["PYTHON_DOTENV_DISABLED"] = "1"
env.pop("PYTHONPATH", None)
control = {"max_commands": 6, "timeout_seconds_per_command": 1200,
           "live_research_call_limit": 0, "provider_spend_limit_usd": 0,
           "credential_environment_removed": True, "dotenv_disabled": True,
           "started_at_unix": time.time(), "commands": []}


def command(args, *, cwd=ROOT, expected=0):
    index = len(control["commands"]) + 1
    start = time.time()
    log = OUT / f"command_{index:03d}.log"
    with log.open("x") as handle:
        result = subprocess.run([str(PYTHON), *map(str, args)], cwd=cwd, env=env,
                                stdout=handle, stderr=subprocess.STDOUT, timeout=1200)
    control["commands"].append({"argv": [str(PYTHON), *map(str, args)], "cwd": str(cwd),
                               "exit_code": result.returncode, "expected_exit": expected,
                               "elapsed_seconds": time.time() - start, "log": log.name})
    (OUT / "run_control.json").write_text(json.dumps(control, indent=2) + "\n")
    if result.returncode != expected:
        raise RuntimeError(f"Integration command {index} exited {result.returncode}; expected {expected}")


source = RUN / "source_persona/reconstruction_attempt_003"
bundle = OUT / "bundle"
command(["scripts/prepare_paired_engineering_study.py", "--executable-root", source / "executable_personas",
         "--audit", source / "eligibility_audit.json", "--output-root", bundle])
protocol = bundle / "protocol.json"
command(["-m", "src.backtest.run_frozen_study", "--protocol", protocol, "--output-root", OUT / "validation"])
command(["-m", "src.backtest.run_frozen_study", "--protocol", protocol, "--execution", "mock", "--output-root", OUT / "mock"])
command(["-m", "src.backtest.run_frozen_study", "--protocol", protocol, "--execution", "live", "--output-root", OUT / "live_refused"], expected=1)
portable = OUT / "portable_bundle"
portable_evidence = OUT / "portable_evidence"
shutil.copytree(bundle, portable)
shutil.copytree(OUT / "mock", portable_evidence)
command(["-m", "src.backtest.run_frozen_study", "--protocol", portable / "protocol.json", "--output-root", OUT / "portable_validation"], cwd=portable / "code")
command(["-m", "src.backtest.run_frozen_study", "--protocol", portable / "protocol.json", "--execution", "replay",
         "--retained-root", portable_evidence, "--output-root", OUT / "portable_replay"], cwd=portable / "code")
assert json.loads((OUT / "mock/analysis.json").read_text()) == json.loads((OUT / "portable_replay/analysis.json").read_text())
control.update(status="passed", actual_research_provider_calls=0, provider_spend_usd=0,
               elapsed_seconds=time.time() - control["started_at_unix"])
(OUT / "run_control.json").write_text(json.dumps(control, indent=2) + "\n")
print(json.dumps({key: control[key] for key in ("status", "actual_research_provider_calls", "provider_spend_usd", "elapsed_seconds")}, indent=2))
