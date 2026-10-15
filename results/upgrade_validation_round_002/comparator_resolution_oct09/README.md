# Comparator resolution validation, 9 October 2026

Scope: engineering and assumed-noise sensitivity controls. These are not authentic policy forecasts, fitted forecast-error uncertainty, live-model evidence, comparative superiority or research-grade closure.

## Implemented contract

`MonteCarloEngine` has a keyword-only `fragmentation_policy`, defaulting to `reject`, and passes it explicitly to both institutional aggregators. Majority and Governor-resolvable binary equality remain accepted. Only the rule engine's specific rejected-fragmentation exception becomes an explicit unresolved channel; invalid ballots, required missing macro inputs, nonfinite arithmetic and unexpected aggregation errors propagate.

Every draw is retained in `draw_records`, including its continuous targets, raw changes, member ballots, unresolved null outcomes, resolution method, synthetic flags and nullable dissent sets. The rate and stance distributions/dissent probabilities use their channel's accepted-draw denominator. Union dissent uses jointly accepted draws. Zero-denominator distributions are empty, modes and dissent probabilities are null, and resolution status is explicit. Unresolved/synthetic probabilities use all draws and expose their denominator. Continuous means use all member-draw targets, including unresolved draws.

Saturation means a continuous change strictly outside the declared menu endpoints. Exact endpoint votes are separately counted and do not establish saturation. The result retains input observables, their full-snapshot hash, seed, noise scale, rule settings and supplied member coefficients. Noise is explicitly assumed Gaussian sensitivity; fitting provenance is not inferred.

## Verification

Final command is in `attempt_004/command.json`, environment in `attempt_004/environment.json`, raw log in `attempt_004/pytest.log`, and before/after copied-input hash manifests plus outcome in `attempt_004/result.json`. The exact project virtual-environment interpreter ran from an isolated source copy; no provider calls. Result: **29 tests passed in 0.66 seconds**, all copied inputs unchanged. This includes 26 dedicated parameterized tests and the three pre-existing Taylor/Monte Carlo tests.

The independent test oracles cover every rate tally with a distinguished Governor (3,234 classes) under reject and legacy synthetic policies, and all stance tally/Governor classes (63) under all three declared policies. They check decisions, methods, accepted/unresolved accounting, synthetic counts and dissent. Other tests check mixed channel denominators, all-unresolved and one-channel-only results, actual Taylor saturation/boundary cases, deterministic seeded noise, missing required inputs, invalid ballots, unexpected aggregation failures and extreme finite/overflow arithmetic. Draw classes are controls, not independent empirical observations.

Four validation attempts are preserved. Each passed; later attempts added explicit probabilities/provenance, finite-mean guards, or broader oracles. Earlier hashes prove the versions actually tested. There were no failed attempts in this owner task.

Seven small saved complete result artifacts are in `controls_001/`, with command, raw log, result, loaded implementation hash, control-script hash and artifact hashes. The fragmented reject case retains three unresolved draws in each channel; legacy and status-quo alternatives label all three draws synthetic. The mixed case records rate denominator 2, stance denominator 2 and union denominator 1 across four draws. Upper/lower targets beyond the menu have saturation fraction 1; an exact upper-endpoint target has fraction 0.

## Reproduction and integration

Run the project `.venv/bin/python` with `run_validation.py NEW_ATTEMPT_NAME` from the active project. The script refuses to overwrite an existing attempt. For control artifacts, use the captured controls command with a fresh destination and `PYTHONPATH` pointing to the validated copied checkout. Scripts never call a model provider or change legacy artifacts.

Existing result field names remain. Callers must handle nullable modes/probabilities or reject incomplete results explicitly. `RationalPanelRunner` and archival demos still assume integer modes and need root-owned fail-closed routing/nullable handling; this owner did not edit them. The behavioral single-run path may raise on rejected fragmentation, whereas this numerical sensitivity returns explicit incomplete outcome evidence for each draw. Cross-track comparisons must apply a declared common failure policy and cannot conceal unresolved coverage by citing conditional percentages.

Missing source-linked output-gap observations still block the full intended comparator. This task neither fits committee/member coefficients nor validates the assumed macro-noise distribution, and it does not establish empirical superiority, external validity or a publication-readiness verdict.
