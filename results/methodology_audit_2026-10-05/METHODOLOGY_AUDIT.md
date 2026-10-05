# Independent methodology audit: RBI MPC In Silico

Audit date: **5 October 2026, Asia/Kolkata**. This is an audit of the current working tree, including its existing staged and unstaged changes. It is not a new live-model experiment, a replication of a different paper, or an accusation about the authors' intentions.

## Verdict

**The project is a functioning simulation prototype, but its current evidence does not validate out-of-sample forecasting, the added predictive value of deliberation, or causal conclusions about real RBI policymaking.** Several foundational failures are directly demonstrated: future-release macro inputs, holdout statements used in persona construction, incorrect dissent labels, a homogeneous holdout that persistence predicts perfectly, and a Round 3 that is disconnected from final voting.

This verdict does not mean LLM committee simulations cannot work. It means the present experiments cannot distinguish that hypothesis from substantially simpler explanations. The appropriate response is to narrow the current claims and run a fresh, frozen evaluation after repairing the data and experimental contracts.

Three independent reviews examined data, statistics, and architecture. The primary audit independently executed existing checks, recomputed the rational track, exhausted the configured voting space, and tested numerical sensitivity and negative controls. Findings are classified below as **verified**, **repository-reported**, or **unresolved**. An implementation property is not treated as empirical validation merely because its test passes.

## What actually ran

Existing tests and generators ran in a separate filesystem snapshot. Some existing tests write to a fixed run directory and the default cache; executing them in the original checkout would risk altering the supplied evidence. No original `.env` or cache was copied into that snapshot. No live LLM calls were made by this audit.

| Check executed | Result | What that result establishes |
|---|---|---|
| Existing pytest suite, with branch coverage | **28 passed** | The existing offline tests pass in the current environment. |
| Deep verification battery | **16/16 passed** | Its selected numerical and implementation assertions pass. |
| Intensive verification battery | **17/17 passed** | Its selected assertions pass; their scientific interpretations require separate assessment. |
| Existing integrity guard | Exit **0** | The current guard accepts the repository; adversarial probes show important false negatives. |
| Existing reproduction harness | Exit **0**, approximately **8.08 seconds** | Its tests, guards, and figure regeneration execute against supplied artifacts. It does not recreate the empirical research from raw inputs. |
| Rational panel rerun | **25 meetings × 1,000 draws** | Saved modal rate and stance decisions reproduce exactly; rate exact accuracy **16%**, direction accuracy **28%**. |
| Exhaustive configured rate voting | **15,625 profiles** | No invalid outputs, majority errors, binary casting-vote errors, or tested permutation errors. |
| Exhaustive configured stance voting | **729 profiles** | No invalid outputs, majority errors, binary casting-vote errors, or tested permutation errors. |
| Rate aggregation adjacent monotonicity | **75,000 comparisons**, zero violations | Weak ordinal monotonicity for this finite action space, rather than a theorem about unrestricted preferences. |
| Taylor finite differences | **3,000 comparisons**, maximum error **1.46 × 10⁻¹⁰** | The implemented linear derivatives agree with the formula. |
| Rational sensitivity | **200 meeting simulations, 60,000 draws** | Exact/directional accuracies remain **16%/28%** over four noise scales and two seeds on the supplied panel. |
| Raw-source and extraction audit | **25 hashes and 150 full statements agree** | Local corpus fidelity and extraction correctness; not the validity of the macro panel or labels. |
| Negative controls and experimental mutations | Failures found | Validation, prompt-flow, cache, provenance, and reproduction claims have specific counterexamples. |

Pytest statement coverage is **64.10%** and branch coverage **56.44%** across `src`; rule-engine branch coverage in that suite is **77.78%**. These figures describe the existing suite only. Independent exhaustive probes add evidence beyond that coverage measurement, but do not retroactively make the suite's claimed coverage 100%.

The audit hash inventory found **zero changes to existing research inputs or outputs** during the main checks. New scripts and audit artifacts are additive. Environment, commands, durations, hashes, logs, and all numerical observations are retained in [audit_results.json](audit_results.json), [input_hashes.json](input_hashes.json), and the linked reviewer evidence below.

## Blocking findings

### B1. The historical information set contains future-release observations — verified

`src/data_pipeline/macro_builder.py` supplies a hardcoded panel; `MacroMeetingSnapshot` declares that its fields are contemporaneously observable, but neither the schema nor prompt wording checks release timestamps.

Two cases are independently anchored to public release dates:

| Simulated meeting | Input in the project | Public release date | Consequence |
|---|---|---|---|
| 10 August 2023 | Headline CPI **7.44%**, food CPI **11.51%** | **14 August 2023, 17:30 IST** | The briefing includes the subsequently released July print. |
| 8 August 2024 | Headline CPI **3.54%** | **12 August 2024, 17:30 IST** | The briefing includes the subsequently released July print. |

The official [MoSPI July 2023 release](https://www.mospi.gov.in/sites/default/files/press_release/CPI_PR_14aug23.pdf) provides the first values and release date. The official [July 2024 release](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2044604&lang=2&reg=48) provides the second value and date. The [RBI's own retrospective description](https://www.rbi.org.in/scripts/BS_ViewBulletin.aspx?Id=22120) says the June 2023 inflation reading was available in the run-up to the August meeting.

Across the supplied raw minutes, **21/25 headline inputs differ materially from the latest rounded inflation observation described in the associated resolution**. That is a broader provenance warning, rather than proof that all 21 observations were future releases: rounding, revisions, and different definitions require individual adjudication. The two dated release examples above suffice to disprove the blanket contemporaneous-information claim.

No HP-filter implementation was found for the supplied output gaps; they are hardcoded. Consequently, this audit did **not** demonstrate two-sided HP-filter leakage in an executed filter. It demonstrated that the claimed HP-filter provenance is absent. A prompt instruction saying the agent has no future knowledge cannot repair future observations already present in its briefing.

### B2. The persona calibration uses the nominal holdout — verified

`src/persona_engine/extractor.py:115` loads all available dated statements, and its score at line 172 combines those corpus frequencies with a manually assigned prior. The persisted personas agree with the all-corpus scores. All six active holdout personas include the eight holdout meetings in their corpus; restricting calibration to the pre-holdout period changes all six scores. For example, Rajiv Ranjan changes from **0.43** to **0.46**, and Jayanth Varma from **−0.31** to **−0.28**.

The actual split is **17 calibration meetings plus 8 holdout meetings**, rather than the plan's 16+8. The existing live runner loads the static personas without enforcing corpus cutoffs. The promised `HOLDOUT_LOCKED` vault is not enforced by this construction path.

This is leakage from evaluation-period statements into the fitted representation. The size of the resulting accuracy inflation cannot be inferred from the score changes alone. However, the current results cannot be called an untouched holdout. Correcting the pipeline now would still require a fresh evaluation; it would not retrospectively make these eight repeatedly examined meetings unseen.

### B3. The primary holdout cannot establish forecasting advantage — verified

All eight holdout committee rate decisions are **0 bps**, and all eight committee stances are **withdrawal of accommodation**. Aggregating the saved independent Round 1 proposals already gives both committee outcomes correctly. Holding the current rate and carrying forward the previous stance achieves **100%/100%**, exactly as the final committee does.

The following results are **recomputed against the repository's existing labels**, which have separate validity problems under B4. They are diagnostics, not corrected final performance estimates:

| Predictor | Panel | Direction accuracy | Stance accuracy | Dissent union F1 |
|---|---|---:|---:|---:|
| Saved mock/heuristic panel | All 25 | 76% | 76% | 0.6769 |
| Carry forward previous observed decision/stance/dissent | All 25 | 92% | 96% | 0.8571 |
| Saved live final committee | Holdout 8 | 100% | 100% | 0.8333 |
| Hold rate, previous stance, fixed Varma dissent chosen from calibration frequency | Holdout 8 | 100% | 100% | 0.8889 |
| Carry forward previous observed decision/stance/dissent | Holdout 8 | 100% | 100% | 0.9474 |
| Aggregate saved independent Round 1 positions | Holdout 8 | 100% | 100% | 0.8000 |

Lagged public ballots are admissible historical information between these meetings. These baseline results are descriptive: the sample and repeated comparisons do not establish that a lagged predictor will outperform a repaired LLM on new data. They establish that superiority to a weak Taylor specification is insufficient evidence of useful forecasting.

The paired rate comparison between the live committee and persistence has **zero discordant successes** and exact McNemar **p = 1**. There is no measured committee rate advantage to explain. Dissent union F1 improves from Round 1's 0.8000 to 0.8333, but that small change does not establish the usefulness of the full deliberation procedure.

### B4. Ground truth conflates reservations, formal stance dissent, and rate dissent — verified

The panel contains only a single `real_dissenters` list. Official member statements and resolution sections distinguish these constructs. Six of the 25 strict rate/stance dissent sets disagree with the supplied labels. Examples include April 2022, where both resolutions are unanimous but the panel lists Varma, and April/June/August/October/December 2023, where expressed reservations are treated as formal dissent.

This distinction is explicit in the June 2023 statement: Varma describes deciding against dissent. Under strict formal rate/stance ballots, the first four holdout meetings have no dissenters. October 2020 additionally illustrates a separate forward-guidance timeline vote that should be represented separately if the target includes it. Combining every disagreement into one binary label is not a neutral choice of ground truth.

On the supplied eight saved simulations, the independently adjudicated **strict formal-ballot sensitivity** is:

| Target | True positives | False positives | False negatives | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Union of rate/stance formal dissenter identities | 6 | 8 | 0 | 0.4286 | 1.0000 | **0.6000** |
| Rate dissent separately | 2 | 0 | 4 | 1.0000 | 0.3333 | **0.5000** |
| Stance dissent separately | 6 | 8 | 0 | 0.4286 | 1.0000 | **0.6000** |

The simulations miss Varma's rate dissent in February and April 2024 and Goyal's in June and August 2024. A correct stance-dissenter identity can conceal an incorrect rate ballot when union scoring is used. This is why the reported 1.00 union recall does not imply that all actual ballots were recovered.

These adjudicated values are an audit sensitivity under an explicit label definition, not a replacement for a signed, independently annotated benchmark. The raw resolution/statement evidence and separate labels are retained in [data_adjudicated_truth.json](data_adjudicated_truth.json) and the statistical review. The original tables have been preserved.

### B5. The purported four-round causal chain drops Round 3 — verified

`src/behavioral/debate_orchestrator.py:169` constructs the final digest solely from Round 1 and Round 2. Round 3 is generated and logged, but neither its preferences nor its compromise rationales enter the final-vote prompts.

An offline controlled client changed all Round 3 rate recommendations between **−50 and +50 bps**. All six final-vote prompts remained identical. This directly falsifies the implementation claim that final votes use the Round 3 compromise synthesis. It does not prove that Round 2 peer information has no effect; that narrower channel needs its own experiment.

The saved stance-dispersion means are **0.4894, 0.4894, 0.4353, 0.4894** across Rounds 1–4. The Round 3 dip fully reverses in Round 4 and occurs in only four meetings. The exploratory paired sign test gives **p = 0.125**. If the word “significantly” in the report means statistical significance, that interpretation is unsupported; the descriptive dip itself reproduces.

## Important experimental and engineering failures

### E1. The full-panel result is mislabeled in prominent research claims

`src/run_stage2_pipeline.py:66` initializes the full historical panel with `provider="mock"`. Its saved 25-meeting rate predictions are a constant pause heuristic. The main report's Table 1A eventually identifies the baseline, which is a useful disclosure, but the abstract at `results/RESULTS_REPORT.md:18` attributes its 76%/76%/0.68 metrics to the multi-agent behavioral simulation.

Moreover, `src/run_stage2_pipeline.py:141` hardcodes dissent exact-match accuracy at **76%**. Recomputing sets gives **40% (10/25)**. Saved live holdout set accuracy is **50% (4/8)** against the supplied labels. This is a direct table-generation/concordance error; it is not an interpretive disagreement.

The Taylor dissent scores printed in Table 1A also lack a traceable corresponding evaluation in the inspected runner. Its saved dissent probabilities count rate dissent only, whereas behavioral scoring combines rate and stance. Without a declared probability threshold and matched target definition, those comparative dissent statistics remain unverified.

### E2. “Replicates” replay the same cache entry

`replicate_id` changes transcript paths, but is not passed as an independent seed into LLM generation. The cached generation key therefore stays unchanged when identical prompts are rerun. An offline probe made **24 generator calls for replicate 1 and zero new calls for replicate 2**.

The current holdout runner explicitly executes only `replicate_id=1` and temperature **0.1**, despite global configuration specifying three replicates and temperature 0.6. These explicit overrides are reproducible choices, but they must be reported as the actual experimental protocol. The eight saved holdout chains contain one replicate per meeting; they do not supply empirical model-sampling uncertainty.

### E3. Ablations do not isolate the claimed channels

Withholding a member from the Round 1/2 matrices does not remove that member's final ballot and rationale from the Governor's context at `debate_orchestrator.py:197`. It is a partial information-withholding intervention, not removal of the member from the committee, and it does not isolate all peer-persuasion channels.

The governor casting-vote experiment must be interpreted as changing a modeled aggregation rule while holding ballots fixed. It cannot establish the real-world effect of changing the institution because members' strategic responses are absent. Fragmented-vote behavior also relies on an assumed compromise procedure, not a statutory identification strategy.

Scenario construction does not preserve all nonspecified inputs: at the actual **5 August 2022** scenario anchor, the Fed-shock builder drops the baseline's GVA value, **11.2%**, to `None`. Baseline and shock runs can also write into the same date/replicate transcript paths: an observed 25-file baseline directory remains 25 files after the shock, with overwritten contents. Thus some stored effects have incomplete paired provenance.

### E4. Synthetic forecasts are presented as independently observed staff/market information

`debate_orchestrator.py:261` calculates forecast proxies mechanically from the same snapshot, but presents them to agents as professional forecaster, market-implied, and confidential staff data. The inflation proxy is simply **0.75 × current CPI + 1**; the GDP proxy uses GVA growth plus an output-gap adjustment. There is no independently observed latent information in that calculation.

Such synthetic features can be part of a clearly labeled simulation. They cannot be cited as solving missing information about actual RBI staff forecasts. The extra feature injection also confounds independent Round 1 versus later-round comparisons: later rounds receive both peers and new synthetic briefing content.

### E5. Five-action and seven-action contracts disagree

The configured action set, persona system prompts, and default voting engine use **−50, −25, 0, +25, +50**. `src/schemas/debate_schema.py:11` and the Round 1 user template additionally accept **+35 and +40**, which are genuine historical actions. A parsed +35/+40 vote is then rejected by default aggregation at `debate_orchestrator.py:226`. This is demonstrated by direct schema-to-aggregation probes.

A five-action benchmark also has an exact-match ceiling of **23/25 = 92%** on this panel because its truth contains a +35 and a +40 action. Adding those actions in one schema alone does not solve the problem. The historical +40 episode is also mislabeled **18 May 2022**, the minutes-publication date, instead of **4 May 2022**, the decision date. The [official RBI decision](https://www.rbi.org.in/commonman/Upload/English/PressRelease/PDFs/PR154MPC04052022.pdf) confirms the latter. This affects temporal joins and information cutoffs.

### E6. Validation can accept broken inputs and broken performance

Independent negative controls establish the following:

- The generic `MetricsEvaluator` passes a panel with **0% stance accuracy**, because its gate omits stance. The separate live-runner gate does include stance; the defect is inconsistent evaluators rather than a claim that every gate omits it.
- The generic “directional” metric uses exact equality: +25 predicted against +50 actual becomes **0% direction accuracy** despite matching direction.
- Unequal sequence lengths are silently zipped/truncated, enabling partial inputs to be scored without an alignment error.
- No true/predicted dissent positives are reported as F1 **1.0** by the generic evaluator. That must be declared as a convention, and cannot be used as evidence of dissent-detection skill.
- NaN headline CPI and output gaps pass schema validation, enter prompts as `nan`, and can silently discretize to **−50 bps**. This is a numerical validity failure rather than sensible missing-data handling.

### E7. Run provenance and fallback handling cannot substantiate “100% live” claims by themselves

Existing cache records provide some affirmative evidence of Gemini-labeled outputs: the architecture review found **192 such records at temperature 0.1 and seed 42**, consistent in count with eight meetings and 24 calls per meeting. That inventory did not establish an entry-to-outcome linkage. Saved outcomes match the saved CSVs, and all eight report zero fallback counts. However, outcome files do not persist effective provider/model, seed, temperature, input hashes, or prompt hashes. Self-reported zero fallback flags are not complete end-to-end provider provenance.

A simulated rate-limit fallback shows that the effective fallback model's response can be cached and costed under the originally requested model. A separate simulated outage makes the cross-model stress script report “PASSED” when both outputs are identical deterministic fallback heuristics, without successful calls to either model. The previously saved cross-model result is correctly described as inconclusive, but the script does not enforce that interpretation.

The claimed hard spending stop also fails an offline mock-client probe: with a tiny cap, the orchestrator catches `BudgetExceededError` as a generic generation failure, proceeds through **24 calls**, and substitutes fallback outputs. No real provider expenditure occurred in this audit. The result shows the stop condition is not propagated reliably through the meeting loop.

### E8. The Taylor comparison is highly sensitive to an unestimated parameter

The member coefficients described as fitted are literals without an accompanying estimation objective or fitting evidence. The independent statistics review varied only smoothing rho over six values, retaining the other parameters and 1,000 common seeded noise draws per meeting. Selecting **rho = 0.975** by minimum **calibration-only rate MAE** gives **87.5% holdout directional accuracy** and **3.125 bps holdout MAE**, versus **12.5%** and **34.375 bps** under the original rho = 0.75. Rho = 0.99 predicts all eight holds, although its calibration MAE is worse.

This grid was chosen after inspecting the project and uses the same flawed macro panel, so it is an exploratory comparator sensitivity rather than new confirmatory performance. Its implication is narrower and important: a large gap against one arbitrarily fixed reaction function cannot establish structural superiority over reasonable conventional comparators. The relevant results are preserved in [stat_taylor_rho_metrics.csv](stat_taylor_rho_metrics.csv).

## Statistical and theoretical interpretations that exceed their tests

1. **The permutation test uses the wrong null.** `(1/5)^8 = 0.00000256` is the probability of eight holds from independent uniform five-action draws. It is not a permutation of observed labels and does not test advantage over persistence. Permuting eight identical hold labels produces the same sequence every time: a constant hold classifier succeeds with probability **1** under that label permutation.
2. **Eight perfect observations do not establish a 75% population accuracy floor.** Even under the optimistic independent Bernoulli assumption, the exact two-sided 95% interval for 8/8 is **[0.6306, 1]**. Regime persistence and temporal dependence make broad generalization harder. Model-call repetitions cannot substitute for more independent meetings.
3. **Dissent uncertainty is large.** A meeting-cluster bootstrap against supplied labels gives a descriptive live union F1 interval of approximately **[0.72, 0.9565]**. The difference from the fixed-Varma baseline spans **[−0.2727, +0.1600]**. Eight clusters are too few for a strong asymptotic argument; these intervals illustrate uncertainty rather than rescue the benchmark.
4. **Persona rank correlation is not independently observed validation.** The perfect tau/rho compare scores to a hardcoded “empirical” ranking with distinctions among officials who have equal dissent counts. Against the repository's actual dissent frequencies, tau is approximately **0.7746** and rho **0.8452**, with ties; an exact two-sided Spearman permutation over all **720 pairings** gives **p = 0.06667**. Those frequencies themselves need corrected labels. Prior blending and hand-selected lexical rules further limit the independence of this check.
5. **Taylor arithmetic does not prove rational expectations, equilibrium determinacy, or welfare optimality.** A positive inflation coefficient, a stable smoothing parameter, and matching finite differences establish properties of the chosen reaction function. The code contains no equilibrium model or identified welfare loss from which the larger claims follow. A smaller sum of squared policy changes is descriptive policy smoothness, not proof of optimal inflation/output stabilization.
6. **Monte Carlo convergence validates integration under chosen noise assumptions.** The independent analytic continuous-mean check agrees within approximately **1.41 standard errors**. It supports the arithmetic. Gaussian scales, independence, clipping, member coefficients, and noise covariance are not empirically calibrated merely because the simulation converges. Continuous member-averaged rates must also be kept distinct from the distribution of discrete committee decisions.
7. **A few unchanged discrete responses do not prove Lipschitz continuity.** The saved Governor-only ten-draw perturbation test is local, single-meeting, and away from known threshold behavior. Step-valued decisions can change discontinuously near action boundaries. Stability can be useful, but a constant predictor is also stable and insensitive.
8. **Stylized counterfactual differences are simulator responses.** They do not identify causal effects in the real economy or prove that an LLM's chosen response is better policy. A single shock anchor, partial ablations, missing replicates, and uncontrolled features weaken even within-simulator mechanism attribution.

## Institutional and literature scope

The official [Reserve Bank of India Act](https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/The-Reserve-Bank-of-India-Act--1934.pdf), pages 88–89, places quorum, majority voting and the Governor's casting vote in **§45ZI**, especially subsections (5), (7), and (8). **§45ZL concerns publication of minutes**, including their publication fourteen days later. The report and code repeatedly cite §45ZL as the source of voting powers.

Requiring all six members is a valid simplifying simulation assumption, but the Act permits a quorum of four with its specified presiding-member conditions. The weighted-median fragmented rate fallback, stance plurality procedure, and treatment of stance as an independently aggregated categorical vote require explicit modeling assumptions and documentary support. The Act does not by itself provide the implemented fragmented median rule. Passing all profiles tests that custom rule's execution, rather than certifying every part as statutory procedure. Likewise, tests on scalar ballots are not proofs of Arrow or Maskin axioms for unrestricted ranked preferences.

The local cited FOMC paper is an August 2025 draft. The [authors' 2025 working paper](https://www2.gwu.edu/~forcpgm/2025-005.pdf) and the [currently revised author paper record](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5424097) differ in scope. The comparison in this repository should explicitly name the version being compared. Its claim of longitudinal generalizability is not established by replacing the original draft's one-meeting scenario experiment with a homogeneous, contaminated eight-meeting test.

## Evidence that remains useful

- The local minute archives and complete extracted statements are faithful to one another. We found no fabricated replacement text in that extraction path.
- Ground-truth fields are not directly rendered by `MacroMeetingSnapshot.to_prompt_text()`. The identified leakage routes are corpus calibration and observation timing, rather than proof that the code literally prints the true decision in its briefing.
- The saved eight outcomes are consistent with their CSV decision and union-dissent rows. Reported 100%/100%/0.8333 can be reproduced **against the supplied labels**.
- The numerical Taylor implementation and the configured finite voting arithmetic are reproducible. Varying perturbation noise with the Taylor parameters fixed does not explain away its poor accuracy on the supplied panel; changing the smoothing parameter does materially change the comparison.
- Member-specific behavior, the explicit dual outputs, transcript retention, separate rational calculations, and existing tests form a useful foundation for a better experiment.
- The saved cross-model test admits its API unavailability. That negative/inconclusive observation should remain in the record.

These strengths justify continuing the project with narrower claims. They do not cancel the blockers above.

## What remains unverified

No new live LLM run, independent provider/model family comparison, genuine prospective forecast, or frozen post-calibration external test was executed. No claim is made that the exact numerical benefit of removing leakage is known. Pretraining memorization is **plausible but not demonstrated**; named historical personas and meeting dates do not eliminate it, and extreme-input or masked-date probes cannot establish its absence. Complete release-vintage metadata for every macro field, independently agreed ballot annotations, human persona/parameter sign-off, and actual policy-welfare validation remain outstanding.

## Minimum credible repair and fresh-test protocol

The detailed protocol is in [FRESH_EVALUATION_PROTOCOL.md](FRESH_EVALUATION_PROTOCOL.md). The order matters:

1. **Repair and freeze truth and information sets first.** Distinguish decision date from publication date; attach observation-period, release-time, source and vintage metadata to every input; adjudicate rate, stance and reservations separately; preserve forward-guidance disagreements separately. Publish the corrected-label diff and reasons.
2. **Refit personas only on admissible pre-cutoff statements.** Freeze priors, lexical rules, prompts, feature transformations, coefficients and tuning decisions. The current holdout becomes development/audit data. Reserve a fresh chronological test spanning actual transitions and, where available, roster changes.
3. **Repair experimental identity and execution.** Propagate Round 3 or redefine the protocol; unify action contracts; reject nonfinite data; enforce keyed alignment; separate all ablation channels; preserve nonspecified shock variables; persist distinct immutable scenario/replicate artifacts; propagate cost-stop exceptions.
4. **Predeclare strong comparisons and statistical units.** Evaluate persistence, lagged policy/ballots, calibrated conventional baselines, independent-agent aggregation, generic-persona and no-peer variants. Measure exact rate, direction, basis-point error, stance, member ballots and separate dissent dimensions. Meetings are the principal independent units; seeds are nested repeats.
5. **Run once on the frozen new test, including failures.** Cache distinct seeds as distinct calls, preserve actual effective model metadata and prompts, report fallback coverage and missing outputs, use paired meeting-level estimates and uncertainty, and report null results. Do not tune until a threshold passes.
6. **Bound the conclusions.** Forecasting advantage requires improvement over admissible strong baselines with adequate regime coverage and uncertainty. Deliberation advantage requires a controlled improvement over independent agents. Counterfactuals initially support only identified within-simulator interventions. Real-world causal or welfare claims require additional identification beyond this simulator.

## Evidence map and reproduction

| Artifact | Purpose |
|---|---|
| [data_review.md](data_review.md), [data_probe.json](data_probe.json), [data_adjudicated_truth.json](data_adjudicated_truth.json) | Corpus fidelity, observation timing, split/calibration leakage, formal ballot evidence. |
| [statistical_review.md](statistical_review.md), [stat_results.json](stat_results.json), [stat_baseline_metrics.csv](stat_baseline_metrics.csv) | Independently recomputed metrics, baselines, uncertainty, and label sensitivities. |
| [stat_adjudicated_results.json](stat_adjudicated_results.json), [stat_sensitivity.json](stat_sensitivity.json), [stat_taylor_rho_metrics.csv](stat_taylor_rho_metrics.csv) | Strict formal-ballot scores and alternative-smoothing comparator sensitivity. |
| [architecture_review.md](architecture_review.md), [arch_probe_results.json](arch_probe_results.json) | Controlled prompt, cache, ablation, fallback, integrity-guard and harness counterexamples. |
| [audit_results.json](audit_results.json), [numeric_sensitivity.csv](numeric_sensitivity.csv), [rational_recomputed.csv](rational_recomputed.csv) | Root execution results, exhaustive checks, numerical negative controls and full rational recomputation. |
| [pytest.log](pytest.log), [deep_battery.log](deep_battery.log), [intensive_battery.log](intensive_battery.log), [integrity_guard.log](integrity_guard.log), [reproduce_harness.log](reproduce_harness.log) | Unabridged stdout/stderr for checks actually run. |
| [input_hashes.json](input_hashes.json), [git_status_before.txt](git_status_before.txt), [coverage.json](coverage.json) | Working-tree evidence inventory and measured existing-suite coverage. |

The primary offline audit can be repeated from the project root into a **new** output directory:

```sh
.venv/bin/python scripts/audit_methodology.py --output results/methodology_audit_new
```

The additive [audit runner](../../scripts/audit_methodology.py) refuses to replace a previous `audit_results.json`. Reviewer probe sources are also retained beside their outputs. This command reproduces the root checks, not every reviewer experiment or a new live study. It intentionally records failures instead of modifying production code to make checks green.
