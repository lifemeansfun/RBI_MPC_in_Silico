# Project workings and exploration map

The project simulates a six-person RBI monetary policy committee. A meeting's macroeconomic briefing and member persona prompts feed independent initial preferences, two deliberation rounds, and final ballots. A discrete voting rule combines the ballots. Historical outcomes and member dissent labels support retrospective evaluation; Taylor-rule and Monte Carlo modules supply numerical comparators. Scenario runners manipulate simulated inputs or peer information.

This map describes where to inspect the implementation. It does not prescribe a quality verdict. Verify what the executed path does rather than inferring behavior from module names or comments.

| Question | Files |
|---|---|
| Scientific questions, claims and claimed evidence | `RBI_MPC_In_Silico_Project_Plan_version_2.md`, `results/RESULTS_REPORT.md`, `research/protocols/` and `research/study/` if present |
| Inputs and data extraction | `src/data_pipeline/`, `data/raw/minutes_html/`, `data/raw/manifest.csv`, `data/processed/` |
| Persona construction and prompts | `src/persona_engine/extractor.py`, `src/schemas/persona_schema.py`, `personas/` |
| Information flow, four rounds and voting | `src/behavioral/debate_orchestrator.py`, `src/schemas/debate_schema.py`, `src/rule_engine/engine.py` |
| Model calls, caching, costs and logs | `src/infra/`, `config/config.yaml`, `runs/` |
| Numerical comparators | `src/rational/` |
| Evaluation, splits, resume and metric definitions | `src/backtest/`, `src/validation/metrics.py`, `src/run_stage2_pipeline.py`, `data/checkpoints/`, `results/tables/` |
| Perturbations and attribution | `src/scenarios/`, `src/attribution/`, `src/validation/data_perturbation.py` |
| Verification and reports | `tests/`, `scripts/`, `Makefile`, `src/reporting/` |
| External source records | `research/source_ledgers/` if present, bundled `Kazinnik_paper.pdf` and `kazinnik_extracted.txt` |

Reviewers receive a copied snapshot with a source manifest. Prior reviews, implementation plans, Git history, credentials, local caches and the README synthesis are excluded. The Python runtime may be shared. Subagents share a host and may share the same model; this process provides fresh supplied context and is not independent human peer review or operating-system isolation. Reviewers should use only their assigned input copy and make any probes there, preserving commands, raw outputs, unsuccessful checks and limitations.
