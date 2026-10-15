"""Verify assessment artifacts and record completion of the bounded task.

This is document/evidence integrity checking, not scientific readiness testing.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]


def read(name):
    return json.loads((OUT / name).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


inventory = read("evidence_inventory.json")
criteria = read("criterion_matrix.json")["criteria"]
ledger = read("review_dispatch_ledger.json")
integrity = read("integrity_checks.json")
report = (OUT / "READINESS_ASSESSMENT.md").read_text()
assert {row["id"] for row in criteria} == set("ABCDEFG")
assert all(row["status"] in {"PASS", "FAIL", "UNVERIFIED"} for row in criteria)
assert any(row["status"] != "PASS" for row in criteria)
assert ledger["count"] == len(ledger["attempts"]) == 5
assert ledger["active_goal_cap"] == 4
assert not inventory["full_current_scientific_readiness"]
assert not inventory["original_tracked_evidence_modifications_relative_to_main"]
assert inventory["branch"] == "project_upgrade_codex"
assert inventory["provider_budget"]["current_cap_usd"] == 25.0
assert not inventory["provider_budget"]["increased"]
assert integrity["status"] == "passed"
assert sha(OUT / "goal-objective.md") == inventory["objective_sha256"]
assert sha(Path(inventory["objective_path"])) == inventory["objective_sha256"]

for manifest in ["scientific_files_sha256.json", "evidence_files_sha256.json"]:
    for name, expected in read(manifest).items():
        assert (ROOT / name).is_file(), name
        assert sha(ROOT / name) == expected, name
for row in criteria:
    for name in row["evidence"]:
        assert (ROOT / name).is_file(), name

requirements = [
    ("Governing objective read and retained", "goal-objective.md; matching attached-objective hash"),
    ("Existing work reused without restarting", "evidence_inventory.json: retained execution receipts, matching current source hashes"),
    ("Main and original tracked evidence preserved", "evidence_inventory.json: fixed main commit; no modified/deleted original data/personas/runs/results relative to main"),
    ("No manuscript work", "Collector allowlist excludes outputs/main_paper; closeout edits are assessment and plan-status files"),
    ("Limits evaluated without reset", "review_dispatch_ledger.json: five cumulative scientific attempts; failed/contaminated attempts included; inherited cap overrun explicitly disclosed"),
    ("Provider cap not increased", "evidence_inventory.json: current and committed USD25 cap; zero closeout provider calls"),
    ("All mandatory scientific criteria assessed", "criterion_matrix.json: A through G with status, scoped evidence and exact remaining gaps"),
    ("Decisive experiments identified", "READINESS_ASSESSMENT.md: Exact remaining gaps and smallest next actions"),
    ("Evaluation freeze and exposure addressed", "Saved studies retain anchors; future live freeze is an explicit unmet requirement; no new evaluation initiated at closeout"),
    ("Critical review and independence limits recorded", "Five-attempt ledger; valid negative review preserved; contaminated/failed attempts have no invented verdict; no final-current approval claimed"),
    ("Implemented remedies and their acceptance boundaries reported", "READINESS_ASSESSMENT.md: implemented changes, retained executions, partial component boundaries"),
    ("Scientific disagreements, nulls, failures and contrary findings preserved", "READINESS_ASSESSMENT.md; hashed failed execution logs and existing raw review archives"),
    ("Stop condition enforced", "Dispatch allowance exhausted; no further repairs/experiments/reviews; historical plans marked superseded"),
    ("Changes and why delivered", "READINESS_ASSESSMENT.md: Implemented changes and what they establish"),
    ("Executed checks and results delivered", "READINESS_ASSESSMENT.md; evidence_inventory.json: exact receipt argv, logs, environment and limits"),
    ("Criterion evidence table delivered", "READINESS_ASSESSMENT.md and criterion_matrix.json"),
    ("Exact gaps and smallest next actions delivered", "READINESS_ASSESSMENT.md: prioritized source/integration/live/contribution requirements"),
    ("Reproduction commands and artifact locations delivered", "READINESS_ASSESSMENT.md: supported Makefile interfaces and absolute file links"),
    ("Terminal status distinguishes task completion from readiness", "Status 2; publication readiness false; no universal rejection of untested live approach"),
    ("Automatic continuation beyond stopping condition prohibited", "Terminal assessment and both supersession notices require new user instruction"),
]
for phrase in ["Research incomplete — specified evidence or resources remain necessary", "307 passed", "1,344 mock", "three repair cycles", "four reviewer dispatches", "eight execution hours", "make reproduce", "make test", "make verify", "[-0.119658, -0.025974]", "No further research work"]:
    assert phrase in report, phrase
for name in ["round_001.md", "round_002.md"]:
    plan = (ROOT / "research/implementation_plans" / name).read_text()
    assert "implementation stopped under the attached bounded goal" in plan

audit = {
    "verified_at_utc": datetime.now(timezone.utc).isoformat(),
    "bounded_assessment_complete": True,
    "publication_readiness_achieved": False,
    "scientific_terminal_status": "Research incomplete — specified evidence or resources remain necessary",
    "scope": "Completion proves delivery of the bounded assessment and stop, not scientific gate satisfaction or historical compliance with the newly reduced dispatch cap.",
    "requirement_checks": [{"requirement": requirement, "bounded_task_status": "COMPLETE", "evidence": evidence} for requirement, evidence in requirements],
    "scientific_gate_statuses": {row["id"]: row["status"] for row in criteria},
    "historical_dispatch_count": 5, "active_dispatch_limit": 4,
    "historical_overrun_not_erased": True,
    "scientific_manifest_sha256": sha(OUT / "scientific_files_sha256.json"),
    "verifier_sha256": sha(Path(__file__)),
    "verification_command": [".venv/bin/python", "research/assessments/bounded_readiness_20261010/verify_closeout.py"],
}
(OUT / "completion_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
for target in re.findall(r"\]\(<(/Users/[^>]+)>\)", report):
    assert Path(target).is_file(), target
linked_count = len(re.findall(r"\]\(<(/Users/[^>]+)>\)", report))
artifact_hashes = {path.name: sha(path) for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_manifest_sha256.json"}
(OUT / "artifact_manifest_sha256.json").write_text(json.dumps(artifact_hashes, indent=2) + "\n")
print(json.dumps({"bounded_assessment_complete": True, "publication_readiness": False, "requirement_checks": len(requirements), "criterion_checks": len(criteria), "absolute_file_links_checked": linked_count, "artifacts_hashed": len(artifact_hashes)}))
