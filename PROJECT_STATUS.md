# Project status as of 15 October 2026

**Research incomplete.** The first engineering upgrade batch has been implemented and verified within its recorded scope. A corrected live comparative study, validated incremental contribution and publication readiness have not been established.

## Versions and manuscript

| Version | Meaning |
|---|---|
| `main`, preserved commit `7f2436bc4f32d6021b1e885eb49286c850de9139` | Original project, saved results and the 5 October methodology audit. The owner identifies main as the submission baseline; this repository does not authenticate an external submission receipt or submitted file. |
| `project_upgrade_codex` | Experimental engineering and research work. Before this publication update, its GitHub tip was `78de7f75bda03d696205b188af17b9540e02a172`; implementation changes after 5 October were local and uncommitted. This update publishes the curated working files and evidence on this branch without merging to main. |
| `outputs/main_paper/` | Manuscript prepared 6 October from the exact main baseline, with a wording correction on 8 October. It does not use the upgraded experimental results. |

The [original manuscript](outputs/main_paper/RBI_MPC_In_Silico_Research_Manuscript.docx), source, builder, provenance and prior revision are preserved. Its retained QA receipt certifies the pre-correction DOCX, not the current bytes; fresh rendering and page inspection remain required before treating the current document as final. The tracked root overview DOCX is an older proposal, not this manuscript. No upgraded empirical manuscript exists.

## What is established

- The [10 October implementation closeout](research/implementation_runs/elite_impl_20261010_001/IMPLEMENTATION_REPORT.md) records **518 passing tests**, a source-linked mock integration and portable replay, including a clean locked-environment check. These are engineering results.
- The initial 15 October status audit matched all 1,329 files in the retained suite manifest, including every current source, test and configuration file. The integration's 78 code files, 420 inputs and 52 principal delivery artifacts also matched. That initial inspection was integrity verification.
- During this publication checkpoint, a fresh export of the Git index completed **518 tests in 196.24 seconds**, offline source reconstruction/saved mock-study verification, new fixture validation and relocated replay from the preserved bundle. Copied scientific inputs remained unchanged. The existing compatible virtual environment was reused; no new clean installation is claimed. New command/results/log records are under the publication inventory, distinct from the 10 October records.
- The new infrastructure includes shared-prefix experiment branching, dated executable personas, source eligibility auditing, separately implemented consensus analysis, immutable study identities and fail-closed provenance/accounting checks.
- The latest integration used **one historical meeting and 26 mock generations**, with **zero new live scientific calls and zero provider spend**. The earlier corrected diagnostic contains 1,344 mock generations on eight all-hold meetings; it is a separate historical artifact, not live replication.
- A fresh check of the original main artifacts confirms that all eight holdout decisions are holds. A constant-hold baseline matches the saved model's 100% exact-rate accuracy. The headline accuracy establishes no predictive advantage.

## What remains unsupported or defective

The current eligibility audit inventories 38 meetings: 32 complete executable rosters, 23 eligible for a reduced conditional simulator, **zero eligible for premeeting forecasting**, and **zero eligible for the full intended comparator**. Thirteen meetings lack macro snapshots, 14 personal histories are missing across six meetings, and one observed stance is unsupported. These are current-data/current-contract findings, not claims that the missing evidence cannot be obtained.

Novelty and domain importance, independent source/label/persona validation, precision and registration, authenticated accounting/quotas, fresh live comparisons and stronger prospective/domain validation remain open. A provider key alone does not close those gates. See the closeout's remaining requirements and the [next-steps plan](research/planning/github_update_20261015/PLAN.md).

**Known statistics defect:** `src/validation/metrics.py::paired_meeting_uncertainty` can mark superiority with a degenerate two-meeting circular-block interval. For dates `['2024-01-01', '2024-02-01']`, model losses `[0, 0]` and baseline losses `[0, 1]`, default settings return `ci95=[0.5, 0.5]`, `sign_flip_pvalue=1.0` and `superiority_supported=True`. This was reproduced on 15 October. It remains unfixed in this preservation update and must be repaired and regression-tested before scientific use. The 518 passing tests do not certify this edge case or scientific validity generally.

## Published package and local archive

The publication inventory records the exact curated file hashes, verification records and local exclusions. Canonical code, configuration, corrected inputs, source ledgers, manuscript package, saved mock evidence, raw command/test/failure logs, assessments and completed/failed review records are included where selected. Frozen historical bundle code remains unchanged.

Repeated test checkouts, installed environments, caches, duplicate portable copies, bulky review ZIPs, unrelated coursework and newly acquired third-party article fulltexts with unassessed redistribution permissions remain local. Nothing is deleted. Public acquisition metadata, hashes and method matrices are retained. Historical manifests can name these excluded files; they are historical records, not assertions that every archived byte is published. The GitHub package is not a complete backup of the local archive.

See [publication inventory and verification](research/publication/github_update_20261015/README.md). Do not describe mock tests, hashes, replay or this GitHub update as a completed scientific evaluation or journal endorsement.
