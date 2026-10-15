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

## Interpretation and remaining evidence

Observed rate class counts are {0: 8}. Generation evidence counts are {'mock': 1344}.
All null, negative and unchanged effects must remain in the saved records. The comparison tables cannot establish live-model superiority when their generations are mock or replayed.
The complete input missingness is recorded in summary.json. An unavailable output gap leaves the full intended comparator unresolved.
Independent live generation, a frozen broader-regime evaluation, comparable controls, model-contamination assessment and appropriate external-validity evidence require separate scientific work.
Voting majority and casting rules are governed by RBI Act Section 45ZI. Full-roster attendance and declared fragmentation resolution are simulator choices; Section 45ZL concerns minutes publication.
This report does not supply a peer-review verdict.
