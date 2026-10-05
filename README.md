# RBI MPC In Silico

A research prototype for simulating the Reserve Bank of India's Monetary Policy Committee with member personas, LLM deliberation, rate and stance ballots, and a smoothed Taylor-rule comparator. Developed for Artificial Intelligence and Expert Systems at VIT Vellore.

## Research status

The project includes historical data, saved simulations, counterfactual experiments, reports, and an independent methodology audit dated **5 October 2026**. Its current evidence **does not establish independent out-of-sample forecasting superiority or causal effects in real RBI policymaking**.

The audit demonstrates future-release macro inputs, holdout statements entering persona calibration, inconsistent formal-dissent labels, a homogeneous holdout matched by persistence, disconnected Round 3 information flow, and experimental provenance failures. Existing numerical and implementation checks pass, but do not resolve those methodological issues.

- [Full methodology audit](results/methodology_audit_2026-10-05/METHODOLOGY_AUDIT.md)
- [Data review](results/methodology_audit_2026-10-05/data_review.md)
- [Statistical review](results/methodology_audit_2026-10-05/statistical_review.md)
- [Architecture review](results/methodology_audit_2026-10-05/architecture_review.md)
- [Protocol for a fresh evaluation](results/methodology_audit_2026-10-05/FRESH_EVALUATION_PROTOCOL.md)

The earlier [results report](results/RESULTS_REPORT.md) and [project plan](RBI_MPC_In_Silico_Project_Plan_version_2.md) are retained as part of the research record. Read their claims together with the audit rather than treating them as currently validated conclusions.

## Contents

| Directory | Contents |
|---|---|
| `src/` | Data extraction, personas, LLM infrastructure, deliberation, voting, numerical comparators, scenarios, and reporting |
| `config/` | Simulation settings and persona defaults |
| `data/` | Local RBI minute archives, extracted statements, macro panel, and saved checkpoints |
| `personas/` | Persisted historical member profiles and calibration review |
| `runs/` | Saved mock and live-labeled simulation transcripts; provenance limitations are documented in the audit |
| `results/` | Existing research tables, figures, reports, and independent audit evidence |
| `scripts/` | Existing verification/stress scripts, reproduction harness, and additive offline audit runner |
| `tests/` | Offline unit/integration tests and fixtures |

## Environment

Python 3.11 or later is required. To create an environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Dependency ranges are not locked. The actual versions used for the October 2026 audit are recorded in [audit_results.json](results/methodology_audit_2026-10-05/audit_results.json).

Local credentials belong in `.env`, following [.env.example](.env.example). The virtual environment, credentials, local LLM cache, and coverage caches are excluded from Git.

## Repeat the offline audit

From the repository root, use a new output directory:

```sh
.venv/bin/python scripts/audit_methodology.py --output results/methodology_audit_local
```

The runner copies project inputs into a separate temporary snapshot because existing tests write to fixed run paths and caches. It executes the existing tests and batteries, recomputes the rational panel, exhausts the configured voting space, and runs numerical sensitivity and negative controls. It records source hashes, environment details, raw logs and results, refuses to replace a previous audit result, and makes no live LLM calls. It does not repeat every independent reviewer probe or constitute a fresh forecasting study.

The saved audit found **28 passing pytest tests**, **33 passing existing battery checks**, **16,354 valid voting profiles**, and reproducible rational calculations. It also demonstrated that several passing guards accept invalid research evidence. A successful process exit is therefore distinct from a successful research hypothesis.

## Existing commands

The [Makefile](Makefile) retains the project's original commands. `make reproduce` runs tests, verification, figure generation, and integrity checks against existing artifacts; it does not reconstruct all live experiments from raw data. Existing scenario and live-run commands can call the configured external model and overwrite fixed experiment paths. The audit documents these execution limitations and the changes needed for a credible frozen evaluation.

## Related research

The original proposal adapts the August 2025 draft of [FOMC In Silico by Sophia Kazinnik and Tara Sinclair](https://www2.gwu.edu/~forcpgm/2025-005.pdf). The bundled paper and original plans are preserved; the audit distinguishes that draft from subsequent revisions and evaluates this implementation on its own evidence.
