"""Run isolated offline dose contracts; never overwrite an existing attempt."""

from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", required=True)
    arguments = parser.parse_args()
    if not arguments.attempt.startswith("scenario_") or Path(arguments.attempt).name != arguments.attempt:
        raise ValueError("Attempt must be a scenario_ prefixed single directory name")
    root = Path(__file__).absolute().parents[2]
    evidence = root / "results/upgrade_validation_round_002" / arguments.attempt
    evidence.mkdir(parents=True, exist_ok=False)
    checkout = evidence / "checkout"
    checkout.mkdir()
    for directory in ("src", "config", "tests"):
        shutil.copytree(root / directory, checkout / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for file in ("pytest.ini", "requirements.txt", "requirements-lock.txt"):
        if (root / file).is_file():
            shutil.copy2(root / file, checkout / file)
    manifest = {str(path.relative_to(checkout)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in checkout.rglob("*") if path.is_file()}
    (evidence / "input_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    selectors = [
        "tests/test_scenario_doses.py",
        "tests/test_attribution_and_scenarios.py::test_scenario_runner",
        "tests/test_attribution_and_scenarios.py::test_scenario_snapshot_builders",
        "tests/test_deliberation_upgrade.py::test_shocks_preserve_all_unrelated_fields_and_label_synthetic_values",
        "tests/test_deliberation_upgrade.py::test_shocks_and_muting_preserve_missing_values_and_zero_food",
        "tests/test_deliberation_upgrade.py::test_nonfinite_scenario_parameters_and_corrupt_input_fail",
        "tests/test_deliberation_upgrade.py::test_scenario_fragmentation_is_rejected_or_explicitly_labeled",
    ]
    command = [str(root / ".venv/bin/python"), "-m", "pytest", "-q", *selectors,
               "--basetemp", str(checkout / "isolated_test_outputs")]
    environment = dict(os.environ, PYTHONPATH=str(checkout), PYTHONDONTWRITEBYTECODE="1")
    (evidence / "command.json").write_text(json.dumps({
        "command": command, "cwd": str(checkout),
        "environment_overrides": {"PYTHONPATH": str(checkout), "PYTHONDONTWRITEBYTECODE": "1"},
        "python": sys.version, "platform": platform.platform(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }, indent=2) + "\n")
    started = time.monotonic()
    with (evidence / "pytest.log").open("w") as log:
        completed = subprocess.run(command, cwd=checkout, env=environment,
                                   stdout=log, stderr=subprocess.STDOUT)
    unchanged = all((checkout / relative).is_file()
                    and hashlib.sha256((checkout / relative).read_bytes()).hexdigest() == digest
                    for relative, digest in manifest.items())
    result = {
        "exit_code": completed.returncode, "elapsed_seconds": time.monotonic() - started,
        "input_hashes_unchanged": unchanged, "provider_calls": 0,
        "verification_scope": "offline compound-dose, missingness, legacy scenario and menu-saturation contracts",
        "scientific_boundary": "assumed simulator-local bundles; no empirical transmission or welfare evidence",
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    print((evidence / "pytest.log").read_text())
    return completed.returncode if unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
