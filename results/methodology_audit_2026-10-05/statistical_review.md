# Independent statistical methodology review — 5 October 2026

The saved results support a functioning simulation prototype and narrow descriptive replication of one sustained policy regime. They do **not** establish general predictive superiority, independent holdout validity, or a causal benefit of deliberation. Several numerical claims reproduce exactly; the dissent exact-match claim does not, and formal ballot adjudication materially lowers dissent performance. The distinction matters: an implementation can be internally consistent while its evaluation cannot discriminate the research hypothesis from simpler explanations.

This review used the existing `.venv`, read production files without editing them, made no LLM/API calls, and wrote only `stat_*` audit evidence and this report. Independently adjudicated raw-minute labels came from the concurrent data review in `data_adjudicated_truth.json`; production labels remain intact. No live run was authenticated or rerun here.

## Reproducible evidence

Run from the project root:

```bash
.venv/bin/python results/methodology_audit_2026-10-05/stat_recompute.py > results/methodology_audit_2026-10-05/stat_recompute_stdout.json
.venv/bin/python results/methodology_audit_2026-10-05/stat_sensitivity.py > results/methodology_audit_2026-10-05/stat_sensitivity_stdout.json
.venv/bin/python results/methodology_audit_2026-10-05/stat_adjudicated_recompute.py > results/methodology_audit_2026-10-05/stat_adjudicated_stdout.txt
```

All three commands ran successfully. Python 3.11.16, NumPy 2.4.6, pandas 3.0.5, and SciPy 1.17.1 were used. `stat_results.json` stores input hashes, environment, metrics, paired contingency counts, edge probes, uncertainty diagnostics, and statement endings. Other machine-readable evidence includes `stat_baseline_metrics.csv`, `stat_holdout_transcript_checks.csv`, `stat_round_preferences.csv`, `stat_taylor_rho_metrics.csv`, and `stat_adjudicated_results.json`. The bootstrap used 100,000 meeting-level resamples, seed 20261005. Taylor sensitivity used 1,000 common seeded perturbation draws per meeting per rho, seed 42; these are simulated perturbations, not additional historical observations.

## 1. Which reported numbers reproduce?

| Track and label definition | Rate direction | Rate exact | Stance | Dissent precision | Dissent recall | Dissent F1 | Dissent set exact match |
|---|---:|---:|---:|---:|---:|---:|---:|
| Saved 25-meeting mock baseline, published labels | 76% | 76% | 76% | 0.5116 | 1.0000 | 0.6769 | **40%, 10/25** |
| Saved 8-meeting live-labelled holdout, published labels | 100% | 100% | 100% | 0.7143 | 1.0000 | 0.8333 | **50%, 4/8** |
| Saved Taylor panel | 28% | 16% | 48% | See qualification below | — | — | — |

The rate, stance, and micro-averaged dissent F1 calculations agree with saved CSV rows. The holdout has TP=10, FP=4, FN=0 under its published labels. Its comparison CSV agrees with all eight stored outcomes and all eight unions of rate/stance dissenters derived independently from member ballots; each meeting has 25 transcript JSONs.

The full-panel dissent exact-match claim in `results/RESULTS_REPORT.md:147` and `results/tables/table1_validation_accuracy.csv` is **wrong for the saved rows**: it states 76% (19/25); recomputation yields 40% (10/25). `src/run_stage2_pipeline.py:141` hardcodes 76.0 rather than deriving the metric. This would fail the report's additional ≥60% exact-dissent target. Whether the declared primary gate fails depends on which inconsistent gate definition is used; see Section 6.

The original Taylor experiment was independently rerun offline: all 25 modal rate predictions, all 25 modal stance predictions, and all 25 means rounded to two decimals match the saved CSV. This is positive reproducibility evidence for that computation.

Taylor dissent statistics in Table 1A (precision 0.18, recall 0.40, F1 0.25, exact match 12%) have no traceable corresponding evaluation in the inspected runner. The saved `taylor_dissent_probs` concern **rate dissent only** (`src/rational/monte_carlo.py:119-120`), while behavioral scores union rate and stance. For illustration, thresholding saved Taylor probabilities at ≥0.5 gives published-label union F1=0.4444 and exact match 36%; this is not a fair two-channel comparison and is **not** asserted to be the authors' intended threshold. A prespecified threshold and matched target definition are required before the reported Taylor dissent comparison can be validated.

The 25-meeting comparison is explicitly generated with `LLMClient(provider="mock")` at `src/run_stage2_pipeline.py:66`; the mock returns a zero rate vote (`src/infra/llm_client.py:288,297`). The report discloses this baseline in Table 1A and its integrity statement, but its abstract (`results/RESULTS_REPORT.md:18`) and structural-superiority conclusion (`:267`) attribute these numbers to behavioral LLM capabilities. That attribution is not supported by this experiment.

## 2. Does the model beat admissible simple baselines?

The implemented date cutoff gives **17 calibration and 8 holdout** meetings, not the repeatedly documented 16+8. Calibration has 11 pauses and 6 hikes; the holdout has **8 pauses, 0 hikes, 0 cuts**, and one stance class throughout. Thus the holdout does not test a rate or stance transition. Balanced accuracy computed over observed holdout classes would still be 100%, but does not evaluate either absent rate class.

The following are deterministic baseline computations. Previous observed decisions are used only from earlier meetings; the first panel row is initialized at pause, its pre-existing accommodative stance, and no dissent. The lag baseline is an online baseline, because earlier holdout outcomes would be known before the next meeting. A simultaneous multi-period forecasting study should additionally report a fixed-origin baseline that never updates within the horizon. This project uses observed pre-meeting states at every meeting, making the online comparison appropriate.

| Prediction method | Panel | Rate direction | Rate exact | Stance | Published-label dissent F1 | Dissent exact |
|---|---|---:|---:|---:|---:|---:|
| Saved mock baseline | All 25 | 76% | 76% | 76% | 0.6769 | 40% |
| Always pause, retain previous stance, always Varma dissent | All 25 | 76% | 76% | **96%** | **0.7234** | 48% |
| Repeat previous observed rate/stance/dissent set | All 25 | **92%** | **80%** | **96%** | **0.8571** | **80%** |
| Saved live-labelled model | Holdout 8 | 100% | 100% | 100% | 0.8333 | 50% |
| Always pause, retain previous stance, always Varma dissent | Holdout 8 | 100% | 100% | 100% | **0.8889** | **75%** |
| Repeat previous observed rate/stance/dissent set | Holdout 8 | 100% | 100% | 100% | **0.9474** | **87.5%** |

These dissent baselines use the published labels, whose errors qualify their interpretation; the corrected comparison follows below. Varma is the only member with published calibration dissent frequency ≥50% (9/17). This justifies the simple member-prior baseline without selecting a member from the holdout. A completely frozen calibration-majority stance is accommodative and fails on the holdout (0%); that is a useful negative finding, but previous-stance persistence remains the stronger and relevant baseline.

With all25 published labels, the pause-only classifier has 100% pause recall and 0% hike recall, so its two-observed-class directional balanced accuracy is **50%** despite 76% ordinary accuracy. Its reported ordinary rate performance is exactly the majority-class frequency.

Exact paired McNemar diagnostics compare correctness on the same meetings:

* Live holdout vs pause/previous stance: **zero discordant pairs** on rate and stance, difference 0, p=1; there is no observed predictive gain to explain.
* Live holdout vs lag dissent exact match: one live-only success, four lag-only successes; two-sided p=0.375. This small panel neither demonstrates superiority nor gives decisive inferiority evidence.
* Mock full panel vs saved Taylor directional accuracy: 18 mock-only successes and 6 Taylor-only successes, p=0.02266. This tests that particular **mock baseline** against that particular Taylor configuration; it does not test LLM reasoning or general structural advantage. Stance p=0.03906; these are unadjusted exploratory comparisons and do not survive a three-comparison Bonferroni correction.
* Live holdout vs Taylor rate direction: 7 live-only successes, none Taylor-only, p=0.015625; stance p=0.5. Even that favorable comparison does not distinguish the LLM from constant pause.

The exact McNemar calculation uses a binomial distribution over discordant pairs, as described in the [statsmodels documentation](https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.mcnemar.html). Serial dependence among meetings limits a conventional independent-pair interpretation; the saved contingency counts remain descriptive facts.

## 3. Formal ballot labels change the result and expose missing rate dissent

The independent source review separated formal rate/stance votes, forward-guidance disagreement, and expressed reservations. Its mapping is preserved with raw evidence in `data_adjudicated_truth.json`. Six of 25 published union labels differ from strict two-channel formal-ballot labels: April 2022, April 2023, and June/August/October/December 2023. October 2020 has a separate formal forward-guidance disagreement that the coarse two-channel labels cannot represent.

The first four holdout dates record Varma's **reservations**, not a formal vote for a neutral stance. June 2023 explicitly says why he is **not dissenting**. A source reservation must not silently be converted to a neutral ballot. Rate and stance dissent should also be scored separately: in February/April 2024 Varma votes for a 25bps cut; in June/August 2024 both Varma and Goyal vote for a cut and neutrality. The model's rate dissent consists only of Varma in June/August 2024. It misses four actual rate-dissent member-meetings.

| Scoring under adjudicated formal ballot labels | TP | FP | FN | Precision | Recall | F1 | Exact set match |
|---|---:|---:|---:|---:|---:|---:|---:|
| Live holdout union of dimensions | 6 | 8 | 0 | 0.4286 | 1.0000 | **0.6000** | **25%** |
| Live holdout rate dissent | 2 | 0 | 4 | 1.0000 | **0.3333** | **0.5000** | 50% |
| Live holdout stance dissent | 6 | 8 | 0 | 0.4286 | 1.0000 | **0.6000** | 25% |
| Holdout previous formal dissent set | 4 | 0 | 2 | 1.0000 | 0.6667 | **0.8000** | **75%** |
| Full mock union | 16 | 27 | 0 | 0.3721 | 1.0000 | **0.5424** | **36%** |

The corrected target definition is a reviewer adjudication with an explicit convention, not an alteration of the published dataset. If the research intentionally targets broader disagreement including reservations, it must state that target and label it consistently across dates; that would be a different task from forecasting statutory ballots. The report's claim of exact joint dissent in June/August 2024 matches **identities in the union**, but fails to reproduce Goyal's actual rate ballot. High union recall therefore overstates two-dimensional voting fidelity.

## 4. Uncertainty, sample size, and the erroneous permutation inference

Even under an optimistic iid Bernoulli model, 8/8 correct produces a two-sided exact 95% confidence interval **[63.06%, 100%]**. It does not establish underlying accuracy ≥75%; the one-sided probability of 8/8 at p=0.75 is 0.75⁸=0.1001. At least 13 all-success iid observations are needed for the two-sided exact lower bound to exceed 75%, and that is only a best-case bound, **not** a sample-size recommendation or a remedy for absent classes and dependence. The calculation uses SciPy's [exact binomial confidence interval](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html).

The meeting-cluster bootstrap under published labels gives live dissent F1's descriptive percentile interval **[0.7200, 0.9565]** and the difference versus always-Varma F1 **[-0.2727, +0.1600]**. These resample each meeting's six ballots together. Eight highly related meetings are too few to treat these intervals as reliable long-run coverage, and they do not correct contamination, target errors, or dependence across dates.

`scripts/stress_test_permutation.py:15-32` samples new independent actions uniformly from five options; it does **not** permute the observed labels. The probability 5⁻⁸=0.00000256 is arithmetically correct under that artificial null. The report's inference that it falsifies a predictive fluke (`results/stress_test_results.md:30`) is not warranted. All eight observed rate labels are identical; every permutation of them is the same all-pause vector, and a constant-pause model remains 100% correct under label permutation. The model comparison requires an explicit hypothesis about added performance over a credible baseline and a corresponding statistic. [SciPy's permutation-test documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html) describes null-specific reassignment of observations or paired samples, unlike drawing new equally likely policy actions.

The configured three replicates (`config/config.yaml:13`) were not used by the panel runners: both `src/backtest/backtest_runner.py:94` and `src/backtest/run_holdout_live.py:119` fix replicate_id=1. The eight holdout folders contain only rep_1. There is no distribution of independently sampled committees, no estimate of LLM run variability, and no basis for treating the 192 round/member outputs or 150 historical statements as 192/150 independent forecast cases. Repeated Monte Carlo draws reduce simulation approximation error, not uncertainty from eight historical observations.

## 5. Do dynamics and stress tests demonstrate mechanisms?

Independent aggregation of Round1 member proposals already yields **100% holdout rate and stance accuracy**. Dissent union F1 is 0.8000 in R1 versus 0.8333 in R4, and exact set match 37.5% versus 50%. This modest descriptive change may be useful, but it does not isolate a causal benefit of peer debate: there is no matched intervention with peer messages withheld and identical macro/persona prompts, and no repeated randomized runs.

Figure5's dispersion is correctly reproduced: round means **0.48936, 0.48936, 0.43529, 0.48936**. The R3 dip occurs in four meetings and reverses completely in R4. The exact two-sided sign diagnostic on four nonzero R1−R3 differences is **p=0.125**. “Compresses significantly” at `results/RESULTS_REPORT.md:180` is not supported if statistical significance is intended. An ordinal three-category stance encoded −1/0/+1 also makes numerical dispersion dependent on that encoding; categorical disagreement rates should accompany it. A dip in a prompted compromise round is not evidence that deliberation improves predictive performance.

The Monte Carlo perturbation stress test (`scripts/stress_test_mc_perturbation.py:18-65`) observes the governor's R1 rate at one anchor under small noise, not an entire committee or global policy function. Ten identical outputs provide evidence of local stability for that setup. They do **not** prove Lipschitz continuity, rule out threshold jumps, or rule out an unresponsive constant predictor. With zero changes in 10 independent trials, a one-sided exact 95% upper bound on change probability is still about 25.9%; independence here is itself unverified. The script uses unseeded Python `random`, does not retain perturbed inputs, and actually injects output-gap noise SD=0.10 while its reported prose says 0.05 for both. The variance threshold's comment also confuses 25 with the squared 25bps tick (625).

The report appropriately labels the second-model stress result **inconclusive** after an API 404 and heuristic fallback; it must remain inconclusive. A model's response to one extreme counterfactual shows input sensitivity, but cannot demonstrate that historical contamination is absent. Synthetic placebo success requires a prespecified property and positive/negative controls; “degraded correctly” from one astrologer output is not an independently defined research criterion.

## 6. Validation code and gates are inconsistent

Executed read-only edge probes in `stat_results.json` demonstrate:

* `MetricsEvaluator.evaluate_panel` calls exact rate equality “directional” (`src/validation/metrics.py:77-80`): simulated +25 vs true +50 returns 0% directional accuracy, although the runners return a directional match. The difference is hidden on this all-pause holdout.
* Its gate omits stance (`:93-96`): a panel with 0% stance accuracy, matching rate, and matching dissent is declared passed.
* Unequal sequence lengths are silently truncated by `zip`: an extra true +50 meeting is ignored and the one simulated observation can score 100%. Dissent list lengths are likewise not checked (`:39-41`).
* Its no-positive/no-prediction dissent precision and recall default to 1.0 (`:52-54`), while runner aggregates default to 0 through denominator guards. This changes gate behavior for an unanimous panel; the metric should explicitly disclose undefined/no-positive cases and prevent treating them as evidence of dissent prediction skill.

The shared config sets dissent threshold 0.50 (`config/config.yaml:48`); the full backtest hardcodes 0.60 (`src/backtest/backtest_runner.py:235`); the holdout hardcodes 0.50 (`src/backtest/run_holdout_live.py:187`); and the report adds exact-rate, exact-dissent, precision, and recall targets that these gate functions do not all enforce. All 25 rows can receive a `holdout_gate_status` although calibration rows are included. Thus “ALL CRITERIA MET” is not a single auditable decision rule. Existing metric tests exercise a perfect, equal-length, equal-rate-size panel (`tests/test_attribution_and_scenarios.py:39-60`), which does not expose these failures.

The action set omits the historical +40 and +35 changes. Its theoretical maximum exact-rate accuracy on all25 is therefore at most 23/25=92%, even if every representable decision is perfect. A study should either represent historical actions, state a rounded target explicitly, or make direction the primary metric and transparently score magnitude separately.

## 7. Persona and Taylor comparisons need independent calibration

The “perfect correlation with historical dissent frequencies” in `results/RESULTS_REPORT.md:115` is based on six **hand-entered ordered scores** in `scripts/deep_verification_battery.py:282-288`, not measured dissent frequencies. Four of the six members have identical zero published dissent frequencies, so those frequencies cannot yield a strict perfect ordering among them. Against actual published frequencies, the magnitude correlations are Kendall tau=0.7746 and Spearman rho=0.8452; the small-sample asymptotic Spearman p=0.0341 is merely a diagnostic. Enumerating all 720 pairings gives **exact two-sided Spearman p=0.06667**, which is not below 0.05. [SciPy recommends permutation-based inference for small Spearman samples](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html). The perfectly ordered handcrafted comparison's Kendall and exact Spearman p=0.002778 are numerically real, but they validate agreement with those chosen ranks, not independent empirical calibration.

`PersonaExtractor.load_member_corpus` loads every date without a split (`src/persona_engine/extractor.py:115-128`), and its calibration combines an expert-assigned prior with lexical counts from all loaded statements (`:165-172`). The saved scores reproduce the **full-corpus** calculation, not calibration-only scores. Removing holdout statements changes scores, for example Varma −0.31→−0.28, Das +0.23→+0.21, and Ranjan +0.43→+0.46. These shifts are small, but confirm that later statements enter predictor construction. This is direct evidence of a breached frozen split, not a hypothetical concern; the audit cannot infer how much that breach changes live performance without a new run.

The Taylor coefficients are described as “fitted” at `src/rational/rational_panel_runner.py:25`, but are literals with no fitting code, objective, estimates, or training uncertainty. Its stance is an additional heuristic (`src/rational/taylor_rule.py:85-91`), not a directly estimated Taylor-rule consequence. Its noisy dissent probability tracks rate only. A fair comparison should match information, target definitions, training privileges, and computational budget, and include naive persistence and a simple calibration-fitted reaction rule before claiming a structural advantage.

An offline six-value rho sensitivity, holding all other parameters and Monte Carlo noise fixed, illustrates comparator dependence. Choosing rho=0.975 by minimum **calibration-only** rate MAE yields 70.59% calibration and **87.5% holdout directional accuracy**, with holdout MAE 3.125bps. Original rho=0.75 yields 12.5% holdout directional accuracy and MAE 34.375bps. Rho=0.99 yields 100% holdout rate accuracy, although its calibration MAE is slightly worse than rho=0.975. The audit grid was chosen after inspecting the repository, so these are exploratory sensitivity results, not a new untouched validation result. They are enough to show that the claimed performance gap depends heavily on one unestimated smoothing coefficient.

## Repair priorities and defensible research claims

1. Define the estimand before further evaluation: committee rate direction, magnitude, stance, formal member rate/stance ballots, and reservations should have separate targets. Adjudicate raw ballots with a second blinded reviewer and preserve disagreements.
2. Remove the hardcoded dissent exact-match statistic and derive every report/table/gate from one tested evaluator with strict alignment, equal-length checks, no-positive conventions, and a single frozen configuration.
3. Reconstruct calibration features and personas using only information available before their cutoff, including macro release dates and vintages; freeze prompts, hashes, model/version, all baselines, and selection rules before touching a new test panel. Already-inspected dates cannot become a fresh confirmatory holdout.
4. Compare matched pause, previous-stance, online lag, independent R1, single-agent, and calibration-fitted reaction-rule baselines. Keep a fixed-origin baseline for any multi-period forecasting claim. Run paired, repeated message-withholding ablations if the hypothesis concerns deliberation.
5. Extend the new test across rate hikes, cuts, and stance transitions, include a prespecified power/design simulation over realistic serial dependence and discordant classifier outcomes, report uncertainty by meeting, and distinguish model randomness from historical sampling uncertainty. Three replicates improve random-run description but do not create additional independent meetings.
6. Prespecify primary outcomes, multiple-comparison handling, failure/fallback treatment, meaningful perturbation ranges and controls; retain all calls, inputs, outputs, costs, seeds, and negative results. Repeated calls should bypass result cache when independence is intended.

A defensible current statement is: **the stored live-labelled simulation reproduces the majority rate and stance in eight pause-regime meetings, and its transcript ballots are internally consistent with saved result rows; corrected formal-ballot dissent union F1 is 0.60 and rate-dissent F1 is 0.50. Simple persistence matches majority decisions and scores better on dissent.** The wider claims of independent generalizability, causal persuasion, absence of contamination, and structural superiority remain unverified.
