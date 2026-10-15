# Compound scenario dose verification

Implementation owner scope: `src/scenarios/scenario_runner.py`, new `tests/test_scenario_doses.py`, and new `scenario_*` evidence in this directory. Other owners' code, configuration, mixed tests and existing scientific results were not edited.

## Interface and assumptions

Both Fed and monsoon snapshot builders and their corresponding run methods add keyword-only `dose=1.0` and named coefficients for every ancillary component. `dose=0` preserves all observable values, including missing values and signed zero. A counterfactual record still records the parent and declared intervention; zero observable dose does not erase provenance.

Fed ancillary headline/core/liquidity changes scale with `fed_hike_bps / 75`. Default `inr_depreciation=None` derives the INR component from that fraction. The reference 75-bps dose retains +0.30 percentage points of headline CPI, +0.20 points of core CPI, -30,000 crore of liquidity and +1.50 rupees per USD. Explicit `inr_depreciation` is an independent signed rupee-per-USD change, multiplied by `dose`. Therefore `fed_hike_bps=0` with unspecified or explicitly zero INR change is identity, while an explicitly nonzero INR component is a declared compound intervention.

Monsoon IIP/output-gap drags scale with `food_cpi_shock_pct / 4`; headline change uses the declared food weight. Default `monsoon_departure_pct=None` interpolates from observed rainfall toward the -20% reference endpoint by that same fraction and `dose`. The reference four-point food dose retains the old rainfall endpoint and -0.5/-0.2-point drags. Explicit `monsoon_departure_pct` remains an absolute hypothetical endpoint interpolated by `dose`, independent of the food component. A zero food component with an explicit different rainfall endpoint is deliberately a rainfall intervention. Missing rainfall remains missing even when an endpoint is requested.

Positive/negative signed doses apply/reverse the declared linear bundle. Coefficients are assumptions, not fitted transmission estimates. Numeric bounds and finite parameter checks still apply. The component basis, units, reference sizes, applied doses, rainfall/INR modes and missing-input policy are recorded in `intervention.assumptions` under `dose_contract_version=2`.

`ScenarioOutcome` adds `fragmentation_policy`, `intervention_assumptions`, `continuous_diagnostics_available`, `continuous_targets_pct`, `continuous_rate_changes_bps`, `menu_saturation` and `action_menu_bps`. Numeric dictionaries use `baseline`/`shocked` then member identity. Menu labels are `below_menu`, `within_menu`, or `above_menu`, with strict outside-bound comparisons. A boundary vote alone does not imply saturation. A discrete-only custom comparator retains explicit unavailable diagnostics. Default rejected fragmentation still propagates before an outcome/wedge is constructed.

## Verification and raw evidence

- `scenario_doses_attempt_001`: 39 passed, 83 deselected, 1.77 seconds, all copied input hashes unchanged; broader filename-filtered scenario checks. Preserved unchanged.
- `scenario_doses_attempt_002`: final dedicated and explicitly named compatibility checks, 37 passed in 0.98 seconds, all copied input hashes unchanged. Covers global and component zero doses, independent compound components, signed/half doses, default compatibility, missing inputs, custom assumptions, nonfinite/overflow rejection, exact menu boundaries, saturation, discrete-only interfaces, and corrupt continuous outputs.
- `scenario_dose_probe_001`: ten retained synthetic dose records, two zero-dose identity checks, and a readable table. All probes use the copied source from final attempt 002 and explicit assumed Taylor parameters. Positive Fed and monsoon doses leave the discrete rate at the menu maximum while continuous targets increase, preserving the null discrete wedge and exposing saturation.
- All checks and probes made zero provider calls. No failed executed check occurred in these two attempts. Source/test/driver/probe hashes are in `scenario_final_hashes.json`; copied inputs, commands, environment details, raw logs and result records remain in the attempt directories.

Reproduce into fresh destinations:

```sh
.venv/bin/python results/upgrade_validation_round_002/scenario_validation.py --attempt scenario_doses_attempt_003
.venv/bin/python results/upgrade_validation_round_002/scenario_probe.py --source-root results/upgrade_validation_round_002/scenario_doses_attempt_003/checkout --output results/upgrade_validation_round_002/scenario_dose_probe_002
```

These checks establish the implemented synthetic arithmetic and metadata contracts. They do not establish actual Fed/monsoon transmission, real-MPC intervention effects, empirical comparator superiority or welfare effects. Full integrated-suite verification belongs to the root after other owners' changes are complete.

## Additional failure control and final corrected version

After attempt 002, a stress counterexample showed that finite but extremely large parameters could overflow in a component whose parent observation was missing. The unknown liquidity value stayed null, but nonfinite liquidity and applied-Fed assumptions were retained. The exact copied-source counterexample, command, stdout and hash are preserved in `scenario_hidden_overflow_counterexample_001`; it is a failed failure-control check, not an empirical result.

The corrected helper validates every derived additive delta before checking parent missingness, and the intervention function rejects nested nonfinite or non-JSON assumptions. Missing observations still remain missing for valid doses. New dedicated tests cover the concealed-overflow and nested-assumption cases.

Final corrected isolated verification: `scenario_doses_attempt_003`, **39 passed in 2.71 seconds**, copied input hashes unchanged, zero provider calls. The identical counterexample program against this corrected copied source rejects the operation with `derived intervention delta must be finite`; retained in `scenario_hidden_overflow_repaired_002`.

`scenario_dose_probe_002` contains the same ten synthetic signed-dose probes against corrected attempt 003. `scenario_final_hashes_v2.json` identifies the current source/tests/drivers and corrected probe outputs. The earlier `scenario_final_hashes.json` and probe 001 remain as records of the initial attempt-002 version and are superseded for integration.

Reproduction after these existing attempts must use a new attempt name, for example `scenario_doses_attempt_004` and `scenario_dose_probe_003`. The drivers refuse existing output destinations.
