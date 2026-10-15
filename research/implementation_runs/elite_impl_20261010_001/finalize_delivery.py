"""Evidence-driven closeout of the authorized zero-provider implementation batch."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent


def read(name):
    return json.loads((RUN / name).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, document):
    path = RUN / name
    if path.exists():
        raise FileExistsError("Do not replace a delivered record: " + name)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


full = read("full_suite_attempt_001/result.json")
full_log = (RUN / "full_suite_attempt_001/pytest.log").read_text()
assert full["exit_code"] == 0 and full["frozen_files_unchanged"] is True
assert re.search(r"\b518 passed\b", full_log)
clean = read("clean_install_attempt_001/run_control.json")
assert clean["clean_install_passed"] and clean["fresh_portable_checks_passed"]
assert clean["lock_unchanged"] and clean["portable_code_and_inputs_unchanged"]
assert clean["elapsed_seconds"] < clean["max_total_installation_and_checks_seconds"]
assert clean["maximum_observed_new_directory_bytes"] <= clean["max_new_directory_bytes"]
assert all(row["exit_code"] == 0 for row in clean["commands"])
assert read("clean_install_attempt_001/fresh_environment.json")["lock_mismatches"] == []
for row in clean["commands"]:
    assert digest(RUN / "clean_install_attempt_001" / row["log"]) == row["log_sha256"]

integration = read("source_integration_attempt_001/run_control.json")
assert integration["status"] == "passed"
assert all(row["exit_code"] == row["expected_exit"] for row in integration["commands"])
completion = read("source_integration_attempt_001/mock/completion.json")
assert completion["actual_generation_calls"] == 26 and completion["evidence_type"] == "engineering_mock"
assert completion["provider_spend_usd"] == 0
assert read("source_integration_attempt_001/live_refused/failure.json")["client_generation_attempts"] == 0
analysis = read("source_integration_attempt_001/mock/analysis.json")
assert analysis == read("source_integration_attempt_001/portable_replay/analysis.json")
assert analysis == read("clean_install_attempt_001/fresh_portable_replay/analysis.json")
assert analysis["B_minus_H"]["reconstructed_generation_tracks"] == {"mock": 26}

protocol = read("source_integration_attempt_001/bundle/protocol.json")
for ref in protocol["code_files"]:
    assert digest(ROOT / ref["path"]) == ref["sha256"]
full_snapshot = read("full_suite_attempt_001/source_manifest_before.json")
for name, expected in full_snapshot.items():
    if name.startswith(("src/", "tests/", "config/")) or name in ("requirements.txt", "requirements-lock.txt"):
        assert digest(ROOT / name) == expected

source = read("source_persona/reconstruction_attempt_003/eligibility_audit.json")
assert not any(source[key] for key in ("input_failures", "rolling_source_failures", "executable_failures"))
assert source["summary"]["artificial_conditional_simulator_eligible"] == 23
baseline = read("baseline_code_manifest.json")
changed = [name for name, old in baseline.items() if digest(ROOT / name) != old]
assert set(changed) == {"AGENTS.md", "Makefile", "src/behavioral/debate_orchestrator.py", "src/persona_engine/provenance.py"}

write("preservation_and_verification.json", {
    "verified_at": datetime.now(timezone.utc).isoformat(), "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
    "baseline_files_missing": [], "baseline_files_changed": changed,
    "current_executable_code_matches_integrated_freeze": True,
    "current_source_tests_and_configuration_match_full_suite_snapshot": True,
    "full_suite_passed": 518, "source_linked_mock_generations": 26,
    "independent_replays_equal": True, "clean_install_passed": True,
    "new_research_provider_calls": 0, "new_provider_spend_usd": 0,
    "scope": "Preserved earlier work and verified current engineering paths; scientific readiness remains separate"})

criteria = [
    {"criterion": "A", "name": "Reference fidelity and justified departures", "status": "UNVERIFIED",
     "acceptance": "Version-specific full-method mapping and decisive verification of required adapted mechanisms, with comparator departures explicit",
     "verified": "Exact August 2025 fulltext and three related primary fulltexts retained with method/page/hash records; Taylor remains a distinct comparator",
     "remaining": "July 2026 revised full methods unavailable; complete scientific adaptation and relevant reference-mechanism reproduction remain unestablished",
     "evidence": ["reference_fidelity/METHOD_AND_CONTRIBUTION_MATRIX.md", "reference_fidelity/reference_methods.json"]},
    {"criterion": "B", "name": "Important incremental contribution", "status": "UNVERIFIED",
     "acceptance": "Substantiated distinction from closest prior work and domain/methods assessment of meaningful scientific importance",
     "verified": "Actual late-Governor H/B/N contrast is explicit; overlaps with peer influence and final-solution withholding documented",
     "remaining": "Exact novelty, domain importance and meaningful effect not assessed; no favorable verdict sought",
     "evidence": ["reference_fidelity/METHOD_AND_CONTRIBUTION_MATRIX.md"]},
    {"criterion": "C", "name": "Source, timing, persona and label validity", "status": "UNVERIFIED",
     "acceptance": "Source/availability/roster/ontology evidence appropriate to each claim, with independent coding and persona-construct validation where claimed",
     "verified": "38 meetings audited; raw bytes/headings/declared cutoffs and deterministic v3 fields reconstructed; 23 reduced conditional-simulator eligible",
     "remaining": "Oracle attendance, unauthenticated historical first availability, absent human coding/construct validation; 13 missing macro meetings, 14 missing histories, unsupported stance; no premeeting forecasting eligibility",
     "evidence": ["source_persona/reconstruction_attempt_003/eligibility_audit.json", "source_persona/reconstruction_attempt_003/executable_personas/receipt.json"]},
    {"criterion": "D", "name": "Identification, baselines and empirical execution", "status": "FAIL",
     "acceptance": "Frozen scientifically justified cohort/controls with actual fresh live-model evidence and matched comparisons",
     "verified": "Actual common 23-output prefix, field-only H/B/N branches and retained raw ballots exercised with mock outputs; all-planned schedule is immutable",
     "remaining": "Zero live study calls; no reconciled allowance/quota, externally assessed scientific freeze, pilot or main-study execution; semantic disclosure audit missing",
     "evidence": ["source_integration_attempt_001/mock/completion.json", "source_integration_attempt_001/live_refused/failure.json", "post_verification_accounting_presence.json"]},
    {"criterion": "E", "name": "Measurement, uncertainty and no pseudoreplication", "status": "UNVERIFIED",
     "acceptance": "Independently recomputed endpoints, planned missingness accounting and adequate meeting/temporal uncertainty under stated assumptions",
     "verified": "Independent arithmetic, fixed-peer attainable ranges, raw request/transcript joins, hierarchical planned-denominator bounds; absent uncertainty stays null",
     "remaining": "No live variance/precision design, empirical intervals or temporal generalization; fixture null is not evidence of equivalence",
     "evidence": ["source_integration_attempt_001/mock/analysis.json", "full_suite_attempt_001/result.json"]},
    {"criterion": "F", "name": "Integrated reproducibility, provenance and failures", "status": "UNVERIFIED",
     "acceptance": "Complete source reconstruction, independent saved-output analysis and fresh live replication with valid accounting and retained failures",
     "verified": "518 isolated tests, portable source-linked mock execution, two identical independent replays including a clean-installed environment; corrupt/unresolved paths fail closed",
     "remaining": "Fresh live replication/provider authentication/billing unverified; new runner blocks existing outputs and does not yet implement controlled continuation of a stopped study; final independent scientific critique not performed",
     "evidence": ["full_suite_attempt_001/result.json", "source_integration_attempt_001/run_control.json", "clean_install_attempt_001/run_control.json"]},
    {"criterion": "G", "name": "Conclusions proportional to evidence", "status": "PASS",
     "acceptance": "Current conclusions explicitly limited to verified evidence, with nulls/failures/contrary and missing evidence retained",
     "verified": "Mock/replay/source checks separately labeled; no forecasting, human cognition, welfare, equilibrium or journal-readiness claim made",
     "remaining": "Conclusions must be reassessed against any later empirical evidence",
     "evidence": ["IMPLEMENTATION_REPORT.md", "criterion_evidence_table.json"]},
]
write("criterion_evidence_table.json", {"version": "implementation-closeout-v1", "status": "RESEARCH INCOMPLETE — SPECIFIED EVIDENCE OR RESOURCES REMAIN NECESSARY", "criteria": criteria,
    "adaptation_established": False, "contribution_established": False, "publication_readiness_established": False,
    "new_scientific_reviewer_dispatches": 0, "scope": "Current engineering batch, preserving the terminal prior assessment and its accounting"})

ledger_path = RUN / "run_ledger.json"
ledger = read("run_ledger.json")
write("run_ledger_before_closeout.json", ledger)
ledger.update(phase="engineering_batch_delivered_research_incomplete", verification_python=full["python"],
    completed_at=datetime.now(timezone.utc).isoformat(), new_live_calls=0, new_provider_spend_usd=0,
    full_suite_passed=518, source_linked_mock_generations=26, clean_install_passed=True,
    new_scientific_reviewer_dispatches=0,
    external_dependency_status="Not resolved by implementation; no renewed provider allowance or scientific approval inferred",
    subagent_limit_event="Source owner final message failed at account usage limit after its independent clean-install driver had completed successfully; root verified saved records",
    remaining_work=[row["remaining"] for row in criteria if row["status"] != "PASS"])
ledger_path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")

report = '''# Implementation closeout — engineering complete, research incomplete

The authorized first implementation batch is integrated on `project_upgrade_codex`. **518 current tests passed** in a copied checkout. A source-linked engineering study completed and replayed identically from relocated code/data, including a fresh environment installed from the unchanged dependency lock. New research-provider calls and spending were **zero**.

**Status 2: RESEARCH INCOMPLETE — SPECIFIED EVIDENCE OR RESOURCES REMAIN NECESSARY.** A scientifically defensible full adaptation, important contribution and publication readiness have not been established. This closeout preserves the earlier terminal bounded assessment; its counters and allowance were not reopened or reset. Later scientific phases are incomplete rather than represented by fixtures.

## What changed and why

| Implementation | Resulting behavior |
|---|---|
| `src/behavioral/paired_prefix.py` | Retains actual six-member R1–R3 and five non-Governor R4 outputs: 23 common generations. Fresh Governor H/B/N draws reuse that prefix. B/N expose identical member/rate/stance tuples, varying binding status; H withholds final information. Final rationales are excluded. Six raw ballots survive unresolved aggregation. |
| `src/persona_engine/executable_rolling.py` and additive `provenance.py` | Creates executable v3 personas from expanding personal histories. Reconstructs raw signed-statement boundaries, identities, roles, dates, lexical counts, quotations and all fitted fields. Missing history causes exclusion. Older v2 behavior remains available. |
| `src/backtest/eligibility_audit.py` | Uses the actual observation schema, inventories every meeting and separates reduced conditional-simulator eligibility from forecasting and full-comparator eligibility. Missing sources, unsupported stances, dates and history stay explicit. |
| `src/validation/paired_consensus.py` | Separately written central arithmetic and raw transcript reconstruction, without producer scoring imports. Checks immutable joins and computes rate/stance/joint agreement, dispersion, fixed-peer attainable ranges, meeting-weighted contrasts and sharp planned-denominator missingness bounds. |
| `src/schemas/frozen_study_schema.py` and `src/backtest/run_frozen_study.py` | Portable file/code/settings freeze and ex ante branch schedule. Default validation makes no client. Mock substitution for research is refused. Live preflight requires recipe-bound scientific/accounting receipts, an existing reconciled ledger, quota/token/call/time limits and dependency agreement before constructing the client. |
| `scripts/prepare_paired_engineering_study.py`, Makefile and active plan | Provides explicitly mock source-linked integration and validation/replay commands with unused destinations. Existing scientific outputs are protected from overwrite. |

Only four preexisting baseline files changed in this batch: AGENTS.md, Makefile, the debate orchestrator's optional source-root validation, and additive persona provenance. All baseline files remain present; configuration, dependency pins, existing mixed tests and other baseline implementation files retain their starting bytes. The large preexisting working tree remains uncommitted. Scientific data and earlier runs/reviews were preserved.

The v3 lexical orientation is a disclosed descriptive extraction, neutral stance is a fixed procedural setting, and attendance is a retrospective oracle. None validates latent human preferences or premeeting membership. The intervention identifies incremental final information/status conditional on retained earlier arguments; those earlier arguments may already reveal intended choices. Semantic disclosure remains a manual scientific audit requirement.

## Checks actually run

- Full isolated current suite: **518 passed**, exit 0, 206.93 seconds of pytest (208.08 seconds driver), copied inputs unchanged. See `full_suite_attempt_001/result.json` and `pytest.log`.
- Current source reconstruction: rolling inputs, executable personas and eligibility audit each exited 0. Actual commands/raw logs/code and input hashes are in `source_persona/reconstruction_attempt_003/run_control.json`.
- Source-to-result path: all six bounded integration commands met their declared exits, including expected live refusal. One historical meeting (2020-12-04, earliest source-eligible) was selected solely for integration, **not** confirmatory evaluation. There were 26 explicit mock generations (23 prefix plus three branches); the live refusal recorded zero generation attempts. See `source_integration_attempt_001/run_control.json`.
- Independent relocated replay: copied code/source/evidence reconstructed the same analysis without an original-workspace code dependency or generation. The source and result bundles exclude credentials, Git, chat, memory, plans and earlier reviews; this is an engineering portability check, not an OS-isolated scientific review.
- Clean environment: one fresh-venv lock installation, version reconciliation, `pip check`, portable validation and independent replay all exited 0. Total 225.69 seconds, peak observed new-directory size 719,790,230 bytes, within 1,200 seconds and 2 GiB. Lock and portable bundle unchanged. See `clean_install_attempt_001/run_control.json` and raw logs. The subagent's final message hit an account usage limit after its driver completed; root verified the completed records.
- Dedicated owner/runner attempts and failures remain retained. Earlier failures exposed a branch identity alias mismatch and floating-point permutation sensitivity; subsequent checks passed after focused fixes. The current full suite contains the final source boundary, rehashed-corruption, metadata/hash, cache, malformed/refusal/cancellation, unresolved aggregation, budget, ledger and replay controls.
- A separate engineering audit found missing ex ante replay anchoring and alternate-code-root bypass; both were corrected and covered by the current suite. This was not an independent scientific submission review. Makefile's new validation routing was dry-run inspected; the corresponding CLI modes were actually executed.

No paid generation, provider quota benchmark, new scientific reviewer dispatch, prospective forecast or human validation experiment ran. Passing arithmetic and provenance checks does not establish empirical superiority or scientific adequacy.

## Evidence and null findings

The audit enumerates **38 meetings**, with **32 complete executable rosters**, **23 reduced artificial conditional-simulator eligible meetings**, **zero premeeting-forecasting eligible meetings**, and **zero full open-economy-comparator eligible meetings**. Thirteen meetings lack macro snapshots; six meetings have 14 missing member histories; one source stance (`calibrated_tightening`) is unsupported by the current simulator ontology. Input/rolling/executable byte-check failures are empty in the final audit. The source release/value transcriptions remain repository-reported evidence; first historical availability and human label/construct validity remain unverified.

For the source-linked **mock fixture**, B−H and B−N joint agreement differences are both **0**, with logical complete-output bounds [0, 0]. All branches had six agreeing mock ballots. The fixture is designed engineering behavior; this is not an empirical null, an equivalence finding or evidence of policy benefit. Monte Carlo standard errors and temporal intervals remain null because one prefix/draw/meeting cannot support them. All planned failure denominators and unattempted branches are retained on failure.

The literature package retains exact full versions of the August 2025 reference and three related papers, with raw acquisition responses, page evidence and hashes. Current GWU bytes equal the retained August 2025 PDF. Bounded revised-SSRN requests returned 403/403/404; July 2026 abstract statements remain distinct from unavailable full methods. Peer influence, reuse of initial outputs and final-solution withholding already appear in inspected work, so exact novelty and scientific importance remain open. See `reference_fidelity/METHOD_AND_CONTRIBUTION_MATRIX.md` and `reference_methods.json`.

## Remaining gates

The fixed A–G assessment is in `criterion_evidence_table.json`: A/B/C/E/F remain UNVERIFIED; D fails the required live empirical execution; G passes proportionality of the current conclusions. Engineering subchecks do not pass those scientific criteria.

1. Establish domain importance and exact differentiation from verified prior work, including revised reference methods where needed. Freeze a meaningful effect and target population before new outcomes.
2. Independently validate label/source semantics and any claimed persona constructs; acquire pre-cutoff appointment evidence for forecasting, authentic missing vintages, and a versioned expanded stance ontology where those claims require them. Conditional oracle simulation cannot close forecasting validity.
3. Reconcile remaining existing allowance, historical charges and actual project quotas. Existing corrected ledgers and markers remain absent; no blank ledger was created. Receipt structure/hashes do not independently authenticate account statements or human judgments.
4. Determine achievable precision using a bounded development pilot under funded limits, finalize the cohort/controls/models/prompt/semantic disclosure policy, and obtain an external registration timestamp. The engineering fixture is not a registered scientific study.
5. Execute and independently replicate fresh live-model evidence with retained raw calls/usage/failures. Controlled continuation of stopped studies is not yet integrated into the new runner; existing outputs are refused and failed attempts cannot be silently retried.
6. Obtain prospective outcomes and qualified human/domain validation for stronger claims. Write the manuscript and assess journal fit after its substantive evidence exists. A final fresh scientific critique must enforce the prescribed exclusions and access controls; this batch dispatched none.

The smallest immediate dependency is authenticated accounting plus substantive domain/methods input. No increase to spending caps, substitution of models or renewed old allowance follows from “continue.”

## Reproduction

From the project root, choose a new destination for every output. These commands produce engineering evidence only:

```sh
.venv/bin/python -m src.persona_engine.rolling_inputs --source-root . --output-root /tmp/elite_new/rolling
.venv/bin/python -m src.persona_engine.executable_rolling --rolling-root /tmp/elite_new/rolling --output-root /tmp/elite_new/personas
.venv/bin/python -m src.backtest.eligibility_audit --rolling-root /tmp/elite_new/rolling --executable-root /tmp/elite_new/personas --source-root . --output-file /tmp/elite_new/audit.json
.venv/bin/python scripts/prepare_paired_engineering_study.py --executable-root /tmp/elite_new/personas --audit /tmp/elite_new/audit.json --output-root /tmp/elite_new/bundle
make study-validate PROTOCOL=/tmp/elite_new/bundle/protocol.json OUT=/tmp/elite_new/validate
make study-mock PROTOCOL=/tmp/elite_new/bundle/protocol.json OUT=/tmp/elite_new/mock
make study-replay PROTOCOL=/tmp/elite_new/bundle/protocol.json SAVED=/tmp/elite_new/mock OUT=/tmp/elite_new/replay
make test OUT=/tmp/elite_new/tests
```

For a relocated or fresh environment, launch `python -m src.backtest.run_frozen_study` from the portable bundle's `code/` directory, pointing to its protocol and retained evidence. `clean_install_attempt_001/driver.py` and `run_source_integration.py` retain the actual completed commands. The complete current code/input manifest is embedded in `source_integration_attempt_001/bundle/protocol.json`; the delivery manifest indexes the principal records and raw logs. Public reference PDFs are retained for internal checking, with redistribution rights still to be assessed.
'''
report_path = RUN / "IMPLEMENTATION_REPORT.md"
if report_path.exists():
    raise FileExistsError("Report already delivered")
report_path.write_text(report)

principals = ["IMPLEMENTATION_REPORT.md", "criterion_evidence_table.json", "run_ledger.json", "run_ledger_before_closeout.json",
    "baseline_code_manifest.json", "baseline_git_status.txt", "post_verification_accounting_presence.json", "preservation_and_verification.json",
    "finalize_delivery.py", "run_source_integration.py", "diagnostic_read_failure_001.json",
    "full_suite_attempt_001_control.json", "full_suite_attempt_001/result.json", "full_suite_attempt_001/pytest.log",
    "full_suite_attempt_001/command.json", "full_suite_attempt_001/source_manifest_before.json", "full_suite_attempt_001/source_manifest_after.json",
    "runner_attempt_001/result.json", "runner_attempt_001/pytest.log", "runner_attempt_002/result.json", "runner_attempt_002/pytest.log",
    "source_integration_attempt_001/run_control.json", "source_integration_attempt_001/bundle/protocol.json",
    "source_integration_attempt_001/mock/analysis.json", "source_integration_attempt_001/mock/completion.json",
    "source_integration_attempt_001/live_refused/failure.json", "source_integration_attempt_001/portable_replay/replay_receipt.json",
    "source_persona/reconstruction_attempt_003/run_control.json", "source_persona/reconstruction_attempt_003/eligibility_audit.json",
    "source_persona/reconstruction_attempt_003/executable_personas/receipt.json", "reference_fidelity/METHOD_AND_CONTRIBUTION_MATRIX.md",
    "reference_fidelity/reference_methods.json", "reference_fidelity/file_manifest.json",
    "clean_install_attempt_001/run_control.json", "clean_install_attempt_001/fresh_environment.json", "clean_install_attempt_001/driver.py",
    "clean_install_attempt_001/predeclared_limits.json", "clean_install_attempt_001/portable_manifest_before.json", "clean_install_attempt_001/portable_manifest_after.json",
    "clean_install_attempt_001/fresh_portable_replay/replay_receipt.json"]
principals += ["clean_install_attempt_001/" + row["log"] for row in clean["commands"]]
principals += ["source_integration_attempt_001/" + row["log"] for row in integration["commands"]]
write("DELIVERY_MANIFEST.json", {"version": "implementation-delivery-v1", "files": {name: {"sha256": digest(RUN / name), "bytes": (RUN / name).stat().st_size} for name in principals},
    "nested_evidence": "Frozen protocol, source/persona receipts and reference manifests index complete source/raw evidence; failed isolated attempts remain in their original directories"})
print(json.dumps({"status": "delivery_created", "full_suite_passed": 518, "manifest_files": len(principals), "new_research_provider_calls": 0, "provider_spend_usd": 0}, indent=2))
