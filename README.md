# RBI MPC In Silico

A research prototype for simulating the Reserve Bank of India's Monetary Policy Committee with member personas, LLM deliberation, rate/stance ballots and mechanical comparators, developed for Artificial Intelligence and Expert Systems at VIT Vellore.

**Status on 15 October 2026: research incomplete.** The experimental branch contains substantial engineering repairs and reproducibility evidence. It has not established forecasting superiority, validated policymaker preferences, a benefit from deliberation or a publication-ready incremental contribution.

## Start here

- [Current project status](PROJECT_STATUS.md): what exists, what is verified, the known statistics defect and scientific limitations.
- [Next-steps plan](research/planning/github_update_20261015/PLAN.md): preservation, verification repair, scientific design, accounted live readiness and manuscript completion.
- [GitHub publication inventory](research/publication/github_update_20261015/README.md): included files, verification and local exclusions.
- [Latest implementation closeout](research/implementation_runs/elite_impl_20261010_001/IMPLEMENTATION_REPORT.md): the completed first engineering batch and outstanding research gates.

## Branches and manuscript

`main` remains the original baseline at `7f2436bc4f32d6021b1e885eb49286c850de9139`, including the [5 October methodology audit](results/methodology_audit_2026-10-05/METHODOLOGY_AUDIT.md). The owner identifies it as the submission baseline; an external submitted file or receipt is not authenticated here. `project_upgrade_codex` contains the experimental upgrade and this preservation checkpoint. Publishing this branch does not merge it into main.

The [original-main manuscript](outputs/main_paper/RBI_MPC_In_Silico_Research_Manuscript.docx) and its [authoring record](outputs/main_paper/README.md) are preserved separately. It was prepared from main, not from upgraded experimental results. Its saved QA receipt covers a prior revision; current final-layout QA remains pending. The root overview DOCX is an older proposal. No upgraded empirical manuscript exists.

The original eight-meeting holdout contains only holds; a constant-hold rule matches its 100% rate accuracy. The audit also documents temporal leakage, persona contamination, label/provenance problems and disconnected final-round information. Read the [historical results report](results/RESULTS_REPORT.md) together with that audit rather than treating its old claims as validated conclusions.

## Engineering evidence and limits

The retained 10 October suite and a fresh exported-package run on **15 October** each record **518 passing tests**. The new run also passed offline source reconstruction, saved mock-study verification, fixture validation and relocated replay of the preserved source-linked bundle. It reused the compatible project virtual environment; it was not a new clean installation. Raw records are in the publication inventory. The latest source-linked integration used **26 mock generations on one historical meeting**, with zero new live study calls. Tests, integrity hashes and portable replay establish behavior within their engineering scope; they do not establish empirical superiority.

The current source audit inventories 38 meetings, with 23 eligible for a reduced conditional simulation, zero eligible for premeeting forecasting and zero eligible for the full intended comparator. Missing sources, roster timing, labels, constructs, novelty, precision and accounting remain open gates. A known two-meeting uncertainty defect remains disclosed in the status page and is scheduled for repair before scientific use.

## Environment and offline verification

Use Python 3.11 or later; the recorded research environment is Python 3.11.16. Install the dependency lock for the captured environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip check
make test OUT=/tmp/rbi-tests-new
make reproduce OUT=/tmp/rbi-reproduce-new
```

Every output path must be unused. Tests run in a copied scientific checkout; reproduction rebuilds historical inputs and verifies the included saved mock study. Neither command performs a new live-model scientific evaluation. Drivers use the repository's `.venv/bin/python`. The broad `requirements.txt` records dependency constraints; the lock records exact captured versions.

For an explicitly artificial new frozen engineering fixture:

```sh
make study-fixture OUT=/tmp/rbi-fixture-new
make study-validate PROTOCOL=/tmp/rbi-fixture-new/protocol.json OUT=/tmp/rbi-validate-new
```

Use `make help` for mock/replay commands. Existing historical protocols seal exact executable files/settings; run a preserved bundle from its own `bundle/code/` directory if active code has changed. Never rewrite historical protocol hashes to force compatibility.

Live execution requires a separately frozen scientific protocol, source eligibility, authenticated accounting and declared resource limits. This checkpoint authorizes no provider spending. Local credentials belong in ignored `.env` files; they are not required for offline tests or replay. Legacy direct scripts can retain fixed-output behavior; use declared current entry points and unused destinations.

## Repository map

| Path | Contents |
|---|---|
| `src/`, `tests/`, `config/` | Implementation, failure controls, tests and simulation settings |
| `data/`, `personas/`, `research/source_ledgers/` | Preserved original inputs, corrected versions, provenance and source metadata |
| `research/implementation_runs/`, `research/assessments/`, `research/peer_reviews/` | Scoped implementation evidence, scientific assessments, completed and failed reviews |
| `results/`, `runs/` | Historical outputs, corrected mock diagnostics and raw verification records |
| `outputs/main_paper/` | Original-main manuscript, sources, provenance and earlier revision |
| `research/verification/`, `scripts/` | Reconstruction, isolated testing, freeze and replay entry points |

Large duplicate checkouts, local runtime installations, review archives, unrelated coursework and new third-party fulltexts with unassessed redistribution permissions are excluded from this GitHub package and retained locally. Acquisition records and hashes remain available. Historical manifests may refer to those local-only files; the publication inventory documents the boundary. No original data or evidence was deleted for this update.
