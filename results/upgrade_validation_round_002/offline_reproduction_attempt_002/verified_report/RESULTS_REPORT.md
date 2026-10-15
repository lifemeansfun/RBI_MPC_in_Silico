# Current study evidence and diagnostic results

Mock procedural diagnostic: 8 meetings, 2 planned replicates and 4 conditions. Complete saved evidence was revalidated before deriving these tables; replay made zero provider calls. A numerical threshold flag does not certify forecasting skill, persuasion, equilibrium or welfare.

## Outcomes

| Condition | Replicate | Exact rate percent | Direction percent | MAE bps | Stance percent | Rate dissent F1 | Stance dissent F1 | Union F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| earlier_rounds | 1 | 100.0 | 100.0 | 0.000 | 100.0 | 0.000 | 0.545 | 0.545 |
| earlier_rounds | 2 | 100.0 | 100.0 | 0.000 | 100.0 | 0.000 | 0.545 | 0.545 |
| full | 1 | 100.0 | 100.0 | 0.000 | 100.0 | 0.000 | 0.545 | 0.545 |
| full | 2 | 100.0 | 100.0 | 0.000 | 100.0 | 0.000 | 0.545 | 0.545 |
| independent | 1 | 100.0 | 100.0 | 0.000 | 100.0 | 0.000 | 0.545 | 0.545 |
| independent | 2 | 100.0 | 100.0 | 0.000 | 100.0 | 0.000 | 0.545 | 0.545 |
| masked | 1 | 100.0 | 100.0 | 0.000 | 100.0 | 0.000 | 0.000 | 0.000 |
| masked | 2 | 100.0 | 100.0 | 0.000 | 100.0 | 0.000 | 0.000 | 0.000 |

## Available-information baselines

| Baseline | Exact rate percent | MAE bps | Union dissent F1 |
|---|---:|---:|---:|
| calibration_constant_dissent | 100.0 | 0.000 | 0.545 |
| hold_previous_stance | 100.0 | 0.000 | 0.000 |
| lag_persistence | 100.0 | 0.000 | 0.800 |

## Paired rate-loss comparisons

Positive advantage means lower model MAE. Intervals use meeting clusters and a circular temporal-block bootstrap. These are exploratory diagnostics on exposed history.

| Condition | Baseline | Mean advantage bps | 95 percent interval | Positive interval lower bound |
|---|---|---:|---|---|
| earlier_rounds | calibration_constant_dissent | 0.000 | [0.0, 0.0] | False |
| earlier_rounds | hold_previous_stance | 0.000 | [0.0, 0.0] | False |
| earlier_rounds | lag_persistence | 0.000 | [0.0, 0.0] | False |
| full | calibration_constant_dissent | 0.000 | [0.0, 0.0] | False |
| full | hold_previous_stance | 0.000 | [0.0, 0.0] | False |
| full | lag_persistence | 0.000 | [0.0, 0.0] | False |
| independent | calibration_constant_dissent | 0.000 | [0.0, 0.0] | False |
| independent | hold_previous_stance | 0.000 | [0.0, 0.0] | False |
| independent | lag_persistence | 0.000 | [0.0, 0.0] | False |
| masked | calibration_constant_dissent | 0.000 | [0.0, 0.0] | False |
| masked | hold_previous_stance | 0.000 | [0.0, 0.0] | False |
| masked | lag_persistence | 0.000 | [0.0, 0.0] | False |

## Dissent with explicitly observed member targets

Observed-case F1 uses only documented targets. Bounds range over all assignments to missing targets with positive truth; they are logical identification bounds, not sampling confidence intervals. An unobserved positive class remains undefined.

| Condition or baseline | Replicate | Channel | Observed / total cells | Observed-case F1 | F1 completion bounds | Complete meetings |
|---|---:|---|---:|---:|---|---:|
| earlier_rounds | 1 | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| earlier_rounds | 1 | formal_stance_dissent | 44 / 48 | 0.667 | [0.5454545454545454, 0.7692307692307693] | 4 |
| earlier_rounds | 2 | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| earlier_rounds | 2 | formal_stance_dissent | 44 / 48 | 0.667 | [0.5454545454545454, 0.7692307692307693] | 4 |
| full | 1 | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| full | 1 | formal_stance_dissent | 44 / 48 | 0.667 | [0.5454545454545454, 0.7692307692307693] | 4 |
| full | 2 | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| full | 2 | formal_stance_dissent | 44 / 48 | 0.667 | [0.5454545454545454, 0.7692307692307693] | 4 |
| independent | 1 | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| independent | 1 | formal_stance_dissent | 44 / 48 | 0.667 | [0.5454545454545454, 0.7692307692307693] | 4 |
| independent | 2 | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| independent | 2 | formal_stance_dissent | 44 / 48 | 0.667 | [0.5454545454545454, 0.7692307692307693] | 4 |
| masked | 1 | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| masked | 1 | formal_stance_dissent | 44 / 48 | 0.000 | [0.0, 0.0] | 4 |
| masked | 2 | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| masked | 2 | formal_stance_dissent | 44 / 48 | 0.000 | [0.0, 0.0] | 4 |
| calibration_constant_dissent | — | exact_rate_disagreement | 48 / 48 | 0.545 | [0.5454545454545454, 0.5454545454545454] | 8 |
| calibration_constant_dissent | — | formal_stance_dissent | 44 / 48 | 0.800 | [0.5714285714285714, 0.8888888888888888] | 4 |
| hold_previous_stance | — | exact_rate_disagreement | 48 / 48 | 0.000 | [0.0, 0.0] | 8 |
| hold_previous_stance | — | formal_stance_dissent | 44 / 48 | 0.000 | [0.0, 0.0] | 4 |
| lag_persistence | — | exact_rate_disagreement | 48 / 48 | 0.800 | [0.8, 0.8] | 8 |
| lag_persistence | — | formal_stance_dissent | 44 / 48 | 0.800 | [0.5714285714285714, 0.8] | 4 |

## Interpretation and remaining evidence

Observed rate class counts are {0: 8}. Generation evidence counts are {'mock': 1344}.
Original saved threshold flags retain their producer contract. Current channel thresholds are recomputed separately in summary.json; neither contract establishes empirical superiority or scientific readiness.
Archival positive-list scores above preserve producer semantics. New formal-vote scoring excludes unobserved member targets and reports complete cases and sharp missing-label bounds in summary.json; these bounds are not confidence intervals.
All null, negative and unchanged effects must remain in the saved records. The comparison tables cannot establish live-model superiority when their generations are mock or replayed.
The complete input missingness is recorded in summary.json. An unavailable output gap leaves the full intended comparator unresolved.
Independent live generation, a frozen broader-regime evaluation, comparable controls, model-contamination assessment and appropriate external-validity evidence require separate scientific work.
Voting majority and casting rules are governed by RBI Act Section 45ZI. Full-roster attendance and declared fragmentation resolution are simulator choices; Section 45ZL concerns minutes publication.
This report does not supply a peer-review verdict.
