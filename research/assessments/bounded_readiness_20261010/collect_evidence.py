"""Read retained evidence and write a bounded-goal closeout inventory.

This collector does not execute tests, research generation, or review dispatches.
It hashes existing files and preserves the scope of each original receipt.
"""
from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
VALIDATION = ROOT / "results/upgrade_validation_round_002"
OBJECTIVE = Path("/Users/manishharigovind/.codex/attachments/980abce9-e46e-49aa-9d87-161f166aefac/goal-objective.md")
COMMANDS = []


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def git(*args):
    argv = ["git", *args]
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=True)
    COMMANDS.append({"argv": argv, "cwd": str(ROOT), "exit_code": result.returncode, "stdout": "Configuration contents omitted; budget cap extracted separately." if args and args[0] == "show" else result.stdout})
    return result.stdout.strip()


def compare(mapping, base):
    missing = []
    changed = []
    for name, expected in mapping.items():
        path = base / name
        if not path.is_file():
            missing.append(name)
        elif digest(path) != expected:
            changed.append(name)
    return {"files_checked": len(mapping), "missing": missing, "changed": changed}


started = datetime.now(timezone.utc).isoformat()
branch = git("branch", "--show-current")
refs = {"HEAD": git("rev-parse", "HEAD"), "main": git("rev-parse", "main")}
status = git("status", "--short")
legacy_modifications = git("diff", "--name-status", "--diff-filter=MD", "main", "--", "data", "personas", "runs", "results")
assert branch == "project_upgrade_codex"
assert refs["main"] == "7f2436bc4f32d6021b1e885eb49286c850de9139"
assert not legacy_modifications, "Original tracked evidence changed or deleted relative to main"
objective_bytes = OBJECTIVE.read_bytes()
(OUT / "goal-objective.md").write_bytes(objective_bytes)

scientific_paths = set()
for folder in ["src", "tests", "config", "scripts", "research/verification"]:
    for path in (ROOT / folder).rglob("*"):
        if path.is_file() and path.suffix in {".py", ".yaml", ".yml", ".md", ".json"} and "__pycache__" not in path.parts:
            scientific_paths.add(path)
for name in ["AGENTS.md", "Makefile", "requirements.txt", "requirements-lock.txt",
             "research/source_ledgers/output_gap_round002/protocol_v1.json",
             "research/source_ledgers/output_gap_round002/build_output_gap_evidence.py"]:
    scientific_paths.add(ROOT / name)
scientific_hashes = {str(p.relative_to(ROOT)): digest(p) for p in sorted(scientific_paths)}
save("scientific_files_sha256.json", scientific_hashes)

test_scopes = {}
for stem in ["integrated_suite_attempt_002", "comparator_controls_attempt_004"]:
    folder = VALIDATION / stem
    before = read(folder / "source_manifest_before.json")
    after = read(folder / "source_manifest_after.json")
    code = {k: v for k, v in before.items() if k.startswith(("src/", "tests/", "config/", "scripts/")) or k in {"Makefile", "requirements.txt", "requirements-lock.txt"}}
    test_scopes[stem] = {
        "receipt": read(folder / "result.json"),
        "pytest_summary": (folder / "pytest.log").read_text().splitlines()[-1],
        "before_after_manifests_identical": before == after,
        "current_source_comparison": compare(code, ROOT),
        "captured_src_count": sum(k.startswith("src/") for k in code),
        "src_files_outside_captured_scope": sorted(str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*.py") if str(p.relative_to(ROOT)) not in before),
        "warning": "Captured file hashes are not execution coverage; test scope is the receipt argv. Counts from different suites overlap.",
    }

gap = read(VALIDATION / "output_gap_oct09/attempt_001/receipt.json")
test_scopes["output_gap_oct09/attempt_001"] = {
    "receipt": gap,
    "pytest_summary": (VALIDATION / "output_gap_oct09/attempt_001/pytest.log").read_text().splitlines()[-1],
    "current_source_comparison": compare(gap["inputs_sha256"], ROOT),
}
for name in ["rebuild_tests_attempt_002/pytest.log", "paired_missing_labels_attempt_001/pytest.log", "rolling_panel_contract_tests_attempt_001.log", "snapshot_boundary_attempt_002/pytest.log"]:
    test_scopes[name] = {"retained_log_summary": (VALIDATION / name).read_text().splitlines()[-1], "limitation": "Log result only in this entry; no added claim of independent empirical validation or full current integration."}

rolling_folder = VALIDATION / "rolling_panel_contract_build_attempt_002"
rolling = read(rolling_folder / "receipt.json")
rolling_checks = {
    "original_inputs": compare(rolling["original_inputs"], ROOT),
    "portable_outputs": compare(rolling["output_files"], rolling_folder),
    "facts": {k: rolling[k] for k in ["build_status", "input_immutability_verified", "meetings_count", "member_packets_count", "source_statements_count", "missing_history_member_packets", "model_calls", "predictive_readiness"]},
    "protocol": read(rolling_folder / "protocol.json"),
    "missing_component_documentation": not (ROOT / "research/verification/rolling_panel_contract.md").is_file(),
}

reproduction = VALIDATION / "offline_reproduction_attempt_003"
summary = read(reproduction / "verified_report/summary.json")
study = {
    "receipt": read(reproduction / "result.json"),
    "reconstruction_receipt": str((reproduction / "rebuilt_inputs/reconstruction_receipt.json").relative_to(ROOT)),
    "summary_path": str((reproduction / "verified_report/summary.json").relative_to(ROOT)),
    "facts": {k: summary[k] for k in ["n_meetings", "n_replicates", "generation_evidence_counts", "replay_provider_calls", "observed_rate_class_counts", "evidence_scope", "independent_live_replication", "scientific_readiness", "statistical_scope", "study_anchors"]},
    "condition_metrics": [{k: row[k] for k in ["condition", "replicate", "metrics", "current_channel_threshold_met", "producer_threshold_contract"]} for row in summary["condition_tables"]],
    "baseline_metrics": summary["baseline_metrics"],
    "full_replicate1_observed_formal_stance": summary["observability_aware_dissent"]["full"]["1"]["formal_stance_dissent"],
    "full_replicate1_calibration_constant_formal_stance": summary["baseline_observability_aware_dissent"]["calibration_constant_dissent"]["formal_stance_dissent"],
    "full_replicate1_paired_dissent_bounds": summary["paired_dissent_f1_logical_bounds"]["full"]["1"],
    "paired_rate_mae_comparisons": summary["paired_rate_mae_comparisons"],
    "source_missingness": summary["source_missingness"],
}

review_rows = [
    {"attempt": 1, "directory": "round_001", "outcome": "failed_infrastructure_account_quota", "verdict": None, "evidence": "attempt_status.json"},
    {"attempt": 2, "directory": "round_001_retry", "outcome": "completed_with_recorded_context_and_shared_host_limits", "verdict": read(ROOT / "research/peer_reviews/round_001_retry/verdict.json")["verdict"], "evidence": "verdict.json"},
    {"attempt": 3, "directory": "round_002_oct09", "outcome": "stopped_inherited_memory_contamination", "verdict": None, "evidence": "output/isolation_receipt.json"},
    {"attempt": 4, "directory": "round_002_clean_process_oct09", "outcome": "failed_http400_unsupported_cli_model", "verdict": None, "evidence": "events.jsonl"},
    {"attempt": 5, "directory": "round_002_clean_defaults_oct09", "outcome": "completed_valid_fresh_ai_review_with_recorded_access_limits", "verdict": read(ROOT / "research/peer_reviews/round_002_clean_defaults_oct09/root_acceptance_receipt.json")["terminal_verdict"], "evidence": "root_acceptance_receipt.json"},
]
for row in review_rows:
    row["evidence"] = f"research/peer_reviews/{row['directory']}/{row['evidence']}"
    row["evidence_sha256"] = digest(ROOT / row["evidence"])
save("review_dispatch_ledger.json", {"count": len(review_rows), "active_goal_cap": 4, "counting_rule": "Existing run counted cumulatively without reset; failed and contaminated dispatches included. Prompt-design editing is not a scientific review.", "stop_condition": "reviewer_dispatch_cap_exceeded", "attempts": review_rows})

review_archives = []
review_folder = ROOT / "research/peer_reviews/round_002_clean_defaults_oct09"
for entry in read(review_folder / "archive_receipt.json")["archives"]:
    path = review_folder / entry["file"]
    review_archives.append({"file": str(path.relative_to(ROOT)), "expected_sha256": entry["sha256"], "actual_sha256": digest(path), "bytes": path.stat().st_size})

evidence_names = [
    "research/peer_reviews/round_001/attempt_status.json", "research/peer_reviews/round_001_retry/verdict.json", "research/peer_reviews/round_001_retry/REVIEW.md",
    "research/peer_reviews/round_002_oct09/dispatch_receipt.json", "research/peer_reviews/round_002_oct09/output/isolation_receipt.json",
    "research/peer_reviews/round_002_clean_process_oct09/command.json", "research/peer_reviews/round_002_clean_process_oct09/events.jsonl",
    "research/peer_reviews/round_002_clean_defaults_oct09/output/REVIEW.md", "research/peer_reviews/round_002_clean_defaults_oct09/root_acceptance_receipt.json", "research/peer_reviews/round_002_clean_defaults_oct09/archive_receipt.json",
    "research/source_ledgers/historical_labels_round002/input_manifest.json", "research/source_ledgers/historical_labels_round002/README.md",
    "research/source_ledgers/expanded_panel_oct09_adjudication/verification.json", "research/source_ledgers/expanded_panel_oct09_adjudication/comparison.json", "research/source_ledgers/expanded_panel_oct09_adjudication/METHODS.md",
    "research/source_ledgers/output_gap_round002/protocol_v1.json", "research/verification/comparator_controls.md",
]
for stem in ["integrated_suite_attempt_002", "comparator_controls_attempt_004", "offline_reproduction_attempt_003"]:
    for suffix in ["result.json", "command.json", "source_manifest_before.json", "source_manifest_after.json", "pytest.log"]:
        path = VALIDATION / stem / suffix
        if path.is_file(): evidence_names.append(str(path.relative_to(ROOT)))
for suffix in ["verified_report/RESULTS_REPORT.md", "verified_report/summary.json", "rebuilt_inputs/reconstruction_receipt.json"]:
    evidence_names.append(str((reproduction / suffix).relative_to(ROOT)))
for suffix in ["rolling_panel_contract_build_attempt_002/receipt.json", "rolling_panel_contract_build_attempt_002/protocol.json", "output_gap_oct09/attempt_001/receipt.json", "output_gap_oct09/attempt_001/pytest.log", "rolling_panel_contract_tests_attempt_001.log", "provider_readiness_attempt_001/result.json", "snapshot_boundary_attempt_002/pytest.log", "rebuild_tests_attempt_002/pytest.log", "paired_missing_labels_attempt_001/pytest.log"]:
    evidence_names.append(str((VALIDATION / suffix).relative_to(ROOT)))
for suffix in ["integrated_suite_attempt_001/pytest.log", "comparator_controls_attempt_001/pytest.log", "offline_reproduction_attempt_001/result.json", "rule_defaults_attempt_001/pytest.log", "snapshot_boundary_attempt_001/pytest.log"]:
    path = VALIDATION / suffix
    if path.is_file(): evidence_names.append(str(path.relative_to(ROOT)))
evidence_hashes = {name: digest(ROOT / name) for name in sorted(set(evidence_names))}
save("evidence_files_sha256.json", evidence_hashes)
cap_current = float(re.search(r"budget_usd_cap:\s*([0-9.]+)", (ROOT / "config/config.yaml").read_text()).group(1))
cap_committed = float(re.search(r"budget_usd_cap:\s*([0-9.]+)", git("show", "HEAD:config/config.yaml")).group(1))
inventory = {
    "run_id": "bounded_readiness_20261010", "collected_at_utc": started,
    "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform()},
    "objective_path": str(OBJECTIVE), "objective_sha256": hashlib.sha256(objective_bytes).hexdigest(),
    "authority": "Attached active objective, not the separately saved proposed replacement prompt.",
    "branch": branch, "refs": refs, "working_state": status,
    "original_tracked_evidence_modifications_relative_to_main": legacy_modifications,
    "provider_budget": {"current_cap_usd": cap_current, "committed_cap_usd": cap_committed, "increased": cap_current > cap_committed, "new_closeout_provider_calls": 0, "legacy_actual_billing_authenticated": False},
    "test_scopes": test_scopes, "rolling_inputs": rolling_checks, "saved_study": study,
    "expanded_labels": read(ROOT / "research/source_ledgers/expanded_panel_oct09_adjudication/verification.json"),
    "provider_metadata_check": read(VALIDATION / "provider_readiness_attempt_001/result.json"),
    "review_archives": review_archives,
    "full_current_scientific_readiness": False,
    "collector_scope": "Read-only retained-evidence integrity and packaging; no research experiments, pytest execution, provider generation, or reviewer dispatch.",
}
save("evidence_inventory.json", inventory)
assert all(not item["current_source_comparison"]["missing"] and not item["current_source_comparison"]["changed"] for item in test_scopes.values() if "current_source_comparison" in item)
assert all(not rolling_checks[key]["missing"] and not rolling_checks[key]["changed"] for key in ["original_inputs", "portable_outputs"])
assert all(row["expected_sha256"] == row["actual_sha256"] for row in review_archives)
assert cap_current == cap_committed == 25.0
assert scientific_hashes == {name: digest(ROOT / name) for name in scientific_hashes}
assert refs == {"HEAD": git("rev-parse", "HEAD"), "main": git("rev-parse", "main")}
save("commands.json", {"collector_argv": [sys.executable, str(Path(__file__).resolve())], "collector_sha256": digest(__file__), "started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(), "subprocesses": COMMANDS, "network_or_provider_operations": 0, "failed_exploratory_lookup": {"path": "research/assessments", "reason": "Closeout directory did not exist before creation; no scientific failure inferred."}})
save("integrity_checks.json", {"status": "passed", "scientific_files_unchanged_during_collection": True, "branch_refs_unchanged_during_collection": True, "main_preserved": True, "legacy_inputs_and_portable_rolling_outputs_match_receipt": True, "tested_source_hashes_match_current_files": True, "review_archive_hashes_match": True, "provider_cap_unchanged": True, "publication_readiness_established": False})
print(json.dumps({"status": "inventory_collected", "scientific_files_hashed": len(scientific_hashes), "evidence_files_hashed": len(evidence_hashes), "review_dispatches": len(review_rows), "main": refs["main"], "publication_readiness": False}))
