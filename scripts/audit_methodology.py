"""Independent, offline methodology probes; preserves existing research artifacts.

Run with the project interpreter:
    .venv/bin/python scripts/audit_methodology.py --output results/methodology_audit_2026-10-05

Repository checks run in a separate snapshot because existing tests write to runs/
and the default cache. This script never calls a live LLM or changes production
code, original tables, transcripts, or the original cache. Audit failures are
recorded as evidence, rather than repaired or hidden.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import itertools
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.rational.monte_carlo import MonteCarloEngine
from src.rational.rational_panel_runner import MEMBER_TAYLOR_PARAMS
from src.rational.taylor_rule import SmoothedTaylorRule
from src.rule_engine.engine import InstitutionalRuleEngine
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.validation.metrics import MetricsEvaluator


def dump(path: Path, value):
    path.write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + "\n")


def inventory():
    """Hash research inputs and preexisting outputs, excluding our audit directory."""
    found = {}
    for directory in ("src", "tests", "scripts", "config", "personas", "data", "runs", "results"):
        for path in sorted((ROOT / directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if any(p.startswith("methodology_audit") for p in path.parts):
                continue
            if path.name == "audit_methodology.py":
                continue
            found[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def run_repository_checks(output: Path):
    scratch = Path(tempfile.mkdtemp(prefix="rbi_methodology_audit_"))
    for directory in ("src", "tests", "scripts", "config", "personas", "data", "runs", "results"):
        shutil.copytree(ROOT / directory, scratch / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "methodology_audit*"))
    for name in ("pytest.ini", "Makefile", "requirements.txt"):
        shutil.copy2(ROOT / name, scratch / name)
    # No .env or original cache is copied. The interpreter is reused, not reinstalled.
    (scratch / ".venv").symlink_to(ROOT / ".venv", target_is_directory=True)
    interpreter = str(ROOT / ".venv/bin/python")
    commands = {
        "pytest": [interpreter, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider",
                   "--cov=src", "--cov-branch", "--cov-report=term-missing",
                   f"--cov-report=json:{output / 'coverage.json'}"],
        "deep_battery": [interpreter, "scripts/deep_verification_battery.py"],
        "intensive_battery": [interpreter, "scripts/intensive_academic_verification.py"],
        "integrity_guard": [interpreter, "scripts/academic_integrity_guard.py"],
    }
    env = dict(os.environ)
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FRED_API_KEY"):
        env.pop(key, None)
    env["COVERAGE_FILE"] = str(output / ".coverage")
    env["PYTHONPATH"] = str(scratch)

    def run(item):
        name, command = item
        start = time.monotonic()
        try:
            result = subprocess.run(command, cwd=scratch, env=env, capture_output=True,
                                    text=True, timeout=180)
            log = result.stdout + "\n" + result.stderr
            record = {"command": command, "cwd": str(scratch), "exit_code": result.returncode,
                      "elapsed_seconds": round(time.monotonic() - start, 3)}
        except subprocess.TimeoutExpired as exc:
            log = str(exc)
            record = {"command": command, "cwd": str(scratch), "exit_code": None,
                      "timed_out": True, "elapsed_seconds": round(time.monotonic() - start, 3)}
        (output / f"{name}.log").write_text(log)
        return name, record

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = dict(pool.map(run, commands.items()))
    # Recompute the rational panel into the snapshot's result directory, retaining all rows.
    rational_command = [interpreter, "-m", "src.rational.rational_panel_runner"]
    records["rational_recompute"] = run(("rational_recompute", rational_command))[1]
    rational_path = scratch / "results/tables/rational_taylor_panel_results.csv"
    if records["rational_recompute"]["exit_code"] == 0 and rational_path.exists():
        shutil.copy2(rational_path, output / "rational_recomputed.csv")
        old = pd.read_csv(ROOT / "results/tables/rational_taylor_panel_results.csv")
        new = pd.read_csv(rational_path)
        records["rational_comparison"] = {
            "old_rows": len(old), "new_rows": len(new),
            "rate_decisions_identical": old.taylor_modal_rate_bps.tolist() == new.taylor_modal_rate_bps.tolist(),
            "stance_decisions_identical": old.taylor_modal_stance.tolist() == new.taylor_modal_stance.tolist(),
            "new_exact_accuracy_pct": float(new.taylor_exact_match.mean() * 100),
            "new_directional_accuracy_pct": float(new.taylor_directional_match.mean() * 100),
        }
    return {"scratch_snapshot": str(scratch), "checks": records}


def exhaust_voting():
    """Tests implemented arithmetic; does not certify statutory or social choice claims."""
    actions = (-50, -25, 0, 25, 50)
    ids = ("g", "a", "b", "c", "d", "e")
    counts = {"profiles": 0, "invalid_outputs": 0, "majority_errors": 0,
              "binary_tie_errors": 0, "permutation_errors": 0,
              "weak_rate_monotonicity_comparisons": 0, "weak_rate_monotonicity_violations": 0}
    examples = []
    for profile in itertools.product(actions, repeat=6):
        counts["profiles"] += 1
        votes = dict(zip(ids, profile))
        result = InstitutionalRuleEngine.aggregate_rate_votes(votes, "g")
        counts["invalid_outputs"] += int(result.winning_action not in actions)
        tally = {a: profile.count(a) for a in set(profile)}
        for action, number in tally.items():
            counts["majority_errors"] += int(number >= 4 and result.winning_action != action)
        if sorted(tally.values()) == [3, 3]:
            counts["binary_tie_errors"] += int(result.winning_action != profile[0])
        reverse = (profile[0],) + tuple(reversed(profile[1:]))
        swapped = InstitutionalRuleEngine.aggregate_rate_votes(dict(zip(ids, reverse)), "g")
        counts["permutation_errors"] += int(result.winning_action != swapped.winning_action)
        for index in range(6):
            action_index = actions.index(profile[index])
            if action_index == len(actions) - 1:
                continue
            raised = list(profile)
            raised[index] = actions[action_index + 1]
            result2 = InstitutionalRuleEngine.aggregate_rate_votes(dict(zip(ids, raised)), "g")
            counts["weak_rate_monotonicity_comparisons"] += 1
            if result2.winning_action < result.winning_action:
                counts["weak_rate_monotonicity_violations"] += 1
                if len(examples) < 5:
                    examples.append({"before": profile, "after": raised,
                                     "outcomes": [result.winning_action, result2.winning_action]})
    stances = ("accommodative", "neutral", "withdrawal_of_accommodation")
    stance_counts = {"profiles": 0, "invalid_outputs": 0, "majority_errors": 0,
                     "binary_tie_errors": 0, "permutation_errors": 0}
    for profile in itertools.product(stances, repeat=6):
        stance_counts["profiles"] += 1
        result = InstitutionalRuleEngine.aggregate_stance_votes(dict(zip(ids, profile)), "g")
        stance_counts["invalid_outputs"] += int(result.winning_action not in stances)
        tally = {a: profile.count(a) for a in set(profile)}
        for action, number in tally.items():
            stance_counts["majority_errors"] += int(number >= 4 and result.winning_action != action)
        if sorted(tally.values()) == [3, 3]:
            stance_counts["binary_tie_errors"] += int(result.winning_action != profile[0])
        reverse = (profile[0],) + tuple(reversed(profile[1:]))
        swapped = InstitutionalRuleEngine.aggregate_stance_votes(dict(zip(ids, reverse)), "g")
        stance_counts["permutation_errors"] += int(result.winning_action != swapped.winning_action)
    return {"rate": counts, "stance": stance_counts, "monotonicity_counterexamples": examples,
            "scope": "Only implemented output, majority, binary tie, selected permutation and ordinal arithmetic properties."}


def probe_metrics_and_schema():
    bad_stances = MetricsEvaluator.evaluate_panel(
        [0] * 8, [0] * 8, ["neutral"] * 8, ["withdrawal_of_accommodation"] * 8,
        [["jayanth_varma"]] * 8, [["jayanth_varma"]] * 8)
    short = MetricsEvaluator.evaluate_panel(
        [0] * 8, [0], ["neutral"], ["neutral"], [[]], [[]])
    directional = MetricsEvaluator.evaluate_panel([25], [50], ["neutral"], ["neutral"], [[]], [[]])
    base = {"meeting_date": "2023-08-10", "current_repo_rate_pct": 6.5,
            "cpi_headline_yoy_pct": 5.0, "cpi_core_yoy_pct": 4.0}
    nan_results = {}
    for field in ("cpi_headline_yoy_pct", "cpi_core_yoy_pct", "output_gap_pct"):
        try:
            snap = MacroMeetingSnapshot(**{**base, field: float("nan")})
            action, _ = SmoothedTaylorRule().compute_discrete_action(snap, MEMBER_TAYLOR_PARAMS["shaktikanta_das"])
            nan_results[field] = {"accepted": True, "taylor_discrete_action": action,
                                  "prompt_contains_nan": "nan" in snap.to_prompt_text().lower()}
        except Exception as exc:
            nan_results[field] = {"accepted": False, "error_type": type(exc).__name__}
    return {"zero_stance_accuracy_gate": bad_stances.model_dump(),
            "mismatched_lengths_not_rejected": short.model_dump(),
            "same_sign_different_magnitude_labelled_directional": directional.model_dump(),
            "nan_inputs": nan_results}


def numerical_stress(output):
    panel = pd.read_parquet(ROOT / "data/processed/macro_panel.parquet")
    snapshots = [MacroMeetingSnapshot(**row) for row in panel.to_dict("records")]
    active_ids = lambda date: ["shaktikanta_das", "michael_patra",
        "mridul_saggar" if date < "2022-05-01" else "rajiv_ranjan",
        "shashanka_bhide", "ashima_goyal", "jayanth_varma"]
    rule = SmoothedTaylorRule()
    rng = np.random.default_rng(20261005)
    max_gradient_error = 0.0
    for _ in range(1000):
        snap = snapshots[int(rng.integers(len(snapshots)))].model_copy(update={
            "cpi_headline_yoy_pct": float(rng.uniform(0, 15)),
            "output_gap_pct": float(rng.uniform(-5, 5)),
            "us_fed_funds_rate_pct": float(rng.uniform(0, 10))})
        parameter = list(MEMBER_TAYLOR_PARAMS.values())[int(rng.integers(7))]
        for field, coefficient in (("cpi_headline_yoy_pct", 1 + parameter.alpha),
                ("output_gap_pct", parameter.beta), ("us_fed_funds_rate_pct", parameter.gamma)):
            high = snap.model_copy(update={field: getattr(snap, field) + 1e-5})
            low = snap.model_copy(update={field: getattr(snap, field) - 1e-5})
            observed = (rule.compute_continuous_rate(high, parameter) - rule.compute_continuous_rate(low, parameter)) / 2e-5
            max_gradient_error = max(max_gradient_error, abs(observed - (1 - rule.rho) * coefficient))
    # Independent normal-theory standard error for the *continuous committee mean*.
    snap = snapshots[0]
    pars = [MEMBER_TAYLOR_PARAMS[m] for m in active_ids(snap.meeting_date)]
    sd, n = .2, 1000
    mean_alpha, mean_beta, mean_gamma = [float(np.mean([getattr(p, k) for p in pars]))
                                        for k in ("alpha", "beta", "gamma")]
    analytic_sd = (1 - rule.rho) * sd * np.sqrt((1 + mean_alpha) ** 2 + (1.5 * mean_beta) ** 2 + (.5 * mean_gamma) ** 2)
    analytic_mean = float(np.mean([rule.compute_continuous_rate(snap, p) for p in pars]))
    mc = MonteCarloEngine(rule, n_draws=n, noise_std_pct=sd, seed=42).simulate(snap, pars)
    continuous_probe = {"analytic_mean_pct": analytic_mean, "mc_mean_pct": mc.mean_implied_rate,
        "analytic_standard_error_pct": float(analytic_sd / np.sqrt(n)),
        "z_deviation": float((mc.mean_implied_rate - analytic_mean) / (analytic_sd / np.sqrt(n))),
        "scope": "Checks MC arithmetic under configured independent Gaussian noise; does not validate noise assumptions or policy optimality."}
    rows = []
    for sigma in (0.0, 0.05, 0.2, 0.5):
        for seed in (42, 20261005):
            for snapshot in snapshots:
                parameters = [MEMBER_TAYLOR_PARAMS[m] for m in active_ids(snapshot.meeting_date)]
                result = MonteCarloEngine(rule, n_draws=300, noise_std_pct=sigma, seed=seed).simulate(snapshot, parameters)
                truth = snapshot.real_rate_decision_bps
                rows.append({"meeting_date": snapshot.meeting_date, "noise_std_pct": sigma,
                    "seed": seed, "n_draws": 300, "actual_bps": truth,
                    "modal_bps": result.modal_rate_decision_bps,
                    "exact_match": result.modal_rate_decision_bps == truth,
                    "direction_match": bool(np.sign(result.modal_rate_decision_bps) == np.sign(truth)),
                    "mean_rate_pct": result.mean_implied_rate})
    df = pd.DataFrame(rows)
    df.to_csv(output / "numeric_sensitivity.csv", index=False)
    summaries = df.groupby(["noise_std_pct", "seed"]).agg(
        exact_accuracy=("exact_match", "mean"), direction_accuracy=("direction_match", "mean")).reset_index().to_dict("records")
    return {"finite_difference_points": 1000, "finite_difference_comparisons": 3000,
            "max_gradient_error": max_gradient_error, "continuous_mc_normal_theory": continuous_probe,
            "sensitivity_simulations": len(rows), "sensitivity_mc_draws": len(rows) * 300,
            "sensitivity_summaries": summaries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "audit_results.json").exists():
        raise SystemExit("Use a new output directory to preserve the previous audit evidence.")
    before = inventory()
    dump(output / "input_hashes.json", before)
    git = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    (output / "git_status_before.txt").write_text(git.stdout)
    packages = {name: importlib.metadata.version(name) for name in
                ("numpy", "pandas", "scipy", "statsmodels", "pydantic", "pytest", "pyarrow", "google-genai")}
    result = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "machine": platform.machine(), "packages": packages},
        "offline_only": True, "source_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    result["repository_checks"] = run_repository_checks(output)
    print("Repository checks recorded", flush=True)
    result["voting_exhaustion"] = exhaust_voting()
    result["metric_and_input_negative_controls"] = probe_metrics_and_schema()
    print("Exhaustive voting and negative controls recorded", flush=True)
    result["numeric_stress"] = numerical_stress(output)
    after = inventory()
    result["existing_artifact_changes"] = {key: {"before": before.get(key), "after": after.get(key)}
        for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)}
    result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    dump(output / "audit_results.json", result)
    print(json.dumps({"checks": result["repository_checks"]["checks"],
        "existing_artifact_changes": result["existing_artifact_changes"],
        "voting": result["voting_exhaustion"], "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
