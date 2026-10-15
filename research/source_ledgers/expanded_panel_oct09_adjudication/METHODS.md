# Source-label reconciliation

The two retained source passes were written separately. This directory compares them and records parent adjudication; it does not call the result independent consensus or a universal gold standard. Neither model predictions nor prior forecasting scores entered these decisions.

Both passes agree on all 78 exact rate choices and rate-choice disagreements. Literal ballot agreement includes six unknown cells; only 72 literal ballots are observed. Three literal No ballots differ from four exact-magnitude disagreements because June 2025 Bhattacharya votes Yes for a 25-bps cut while the committee chooses 50 bps.

For formal stance, 76 of 78 entries agree including unknowns. Two personal statements explicitly link a status-quo vote to both rate and stance. The primary definition accepts these contextual personal votes as neutral, with the preceding neutral stance as referent. A strict-narrative sensitivity preserves the second coder's nulls. Both original annotations, excerpts and reasons remain in comparison.json. Resolution-reported October 2026 preferences are not substituted for unavailable personal statements.

The primary definition observes 20 formal stance cells; the strict sensitivity observes 18. Only three meetings have all six stance votes observed. Unknown votes, unassessed reservations and unassessed guidance are never coded as negatives. These labels cover an already exposed retrospective panel of 13 decisions, including eight holds, four cuts and one increase. `calibrated_tightening` is outside the current simulator's three-stance ontology and requires explicit versioned integration.

`build_adjudication.py` verifies 25 shared primary-source hashes and 386 exact annotation raw fragments, then writes new outputs exclusively. The independent pass's broader annotations-plus-statements check covers 1,048 fragments separately; these counts refer to different inputs. Hashes check retained consistency, not authenticated historical first availability.

`evaluate_missing_labels.py` produces one offline no-dissent baseline diagnostic for each distinct channel, including the strict stance sensitivity. The new evaluator reports observed and complete cases plus sharp logical bounds over every possible assignment to missing labels. Bounds are not confidence intervals and do not assume random missingness. This deterministic baseline uses no model generation and cannot establish model performance. Run into a new output directory:

```sh
PYTHONPATH=. .venv/bin/python research/source_ledgers/expanded_panel_oct09_adjudication/evaluate_missing_labels.py --output-dir results/source_label_diagnostics_new
```
