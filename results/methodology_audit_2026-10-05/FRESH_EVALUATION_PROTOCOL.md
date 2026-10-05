# Protocol for a fresh evaluation

This is a proposed repair protocol, not a preregistration that predates the existing results. The current eight-meeting holdout has been inspected and used in calibration; treat it as development/audit data. Do not retrospectively relabel repaired results as an untouched test.

## Define the questions before changing prompts

**Forecasting:** Given only information available before a policy meeting, does the LLM committee improve predictive performance over credible policy and member-vote baselines?

**Deliberation:** With identical agents, admissible inputs, effective model, token budget and replicated sampling, does sharing peer arguments improve predictions relative to independently aggregated votes?

**Simulator mechanisms:** What changes when a precisely defined information, voting-rule or macro-input intervention is applied to the frozen simulator? This estimand concerns simulator behavior. It is not a causal effect of an institution or policy in the real economy.

Keep these hypotheses separate. Strong descriptions of personalities or plausible rationales do not substitute for any of their evaluations.

## Data contract and truth adjudication

Each field must have `meeting_decision_timestamp`, `observation_period`, `release_timestamp`, `vintage_timestamp`, `source_url`, `source_hash`, `units`, and a transformation identifier. Enforce release time at or before the forecast cutoff, including timezone. Archive the actual vintage rather than retrieving a revised series without a revision flag. Preserve legitimate contemporaneous forecasts as forecasts, separately from realized observations.

Use official resolution roll calls as the primary label source. Have two annotators independently classify individual rate ballots, stance ballots, reservations, abstentions and forward-guidance votes under a written codebook. Reconcile discrepancies without viewing model outputs. Publish unresolved cases and sensitivity analyses. Retain text evidence and the mapping from publication date to meeting date.

Use chronological training/development/final segments. Refit personas solely on training statements released by the relevant cutoff. All priors, quotes, lexical choices, staff proxies, input transformations, model identifiers, temperatures and Taylor parameters need a freeze record with hashes. If rolling updating is used, predeclare it and apply the same admissible updating schedule to comparators. Do not select the split or remove difficult meetings based on model accuracy.

Require final-test policy-regime diversity where the available data support it. Report hold, hike and cut counts, stance transitions and roster changes. If cuts or transitions are absent, explicitly limit the population of the claim and do not manufacture evidence by counting more model samples from the same meetings.

## Execution contract

- Use one action-space definition through schemas, prompts, configuration, aggregation and scoring. Include historical +35/+40 actions if exact replication is a target.
- Reject nonfinite and missing essential observations. Declare imputation procedures in advance; preserve an imputation mask.
- Give each prediction an immutable identity including experiment, scenario, meeting, replicate and prompt/config/data hashes. Checkpoints must verify that identity before reuse.
- Assign and pass distinct predeclared seeds. Identical cached responses count as replays, not independent replicates. Record requested and effective provider/model/version, temperature, seed, cache key/hit, raw response, parser correction, fallback reason and retry history for each utterance.
- Persist the exact prompts and consumed upstream messages. Verify that the intended Round 3 outputs enter final voting. If rounds are stateless, say so and explicitly carry each agent's previous preferences into later prompts.
- Recompute outcomes and dissent flags from member ballots. Validate identities, roster completeness, ballot count, aggregation inputs and output consistency.
- Stop on hard budget exceptions. Research failure, unavailable endpoints and malformed responses remain missing/failure observations under a predeclared policy; do not substitute an economic heuristic and call it a successful independent model comparison.

## Comparators and experimental controls

Use the same cutoff and fields for every comparator. Include unchanged-policy persistence, lagged decisions and public ballots, a training-fitted conventional reaction/classification model, and reasonable Taylor alternatives with smoothing and core/forecast inflation. Avoid presenting one hand-assigned Taylor rule as the unique rational benchmark. Fit parameters on training data; publish the search space and selection criterion.

Compare final deliberation with independent Round 1 aggregation, a single-agent prediction, generic versus member-specific personas, and no-peer-information variants. Match added staff features and token budget so that an improvement cannot be attributed solely to extra data or sampling. Name-masked and date-masked variants are useful contamination diagnostics, but do not establish a training-data firewall. A genuinely prospective evaluation is stronger evidence.

For member information ablations, specify exactly which messages are withheld, including final ballots/rationales seen by the Governor. Retain the member as a voter only if that is the intended intervention. For casting-vote ablations, distinguish fixed-ballot mechanical effects from rerunning members under changed rules. Report the event count on which the casting rule can operate.

For shocks, mutate only predeclared fields; assert equality of every other field. Specify whether food, headline inflation, rainfall, expectations and output co-move under an explicit shock model. Use matched baseline/intervention seeds with a clearly stated coupling, distinct immutable outputs and multiple anchors where feasible. Report paired response distributions, interaction effects and null cases. An implausible composite shock may test robustness, but does not establish a realistic economic policy effect.

## Metrics, uncertainty and decision rules

Predeclare one primary forecasting outcome and a practical improvement margin over the strongest admissible baseline. Separately report exact rate accuracy, sign accuracy, per-class direction recall, rate MAE/RMSE in bps, stance accuracy and individual rate/stance ballot accuracy. Report formal rate and formal stance dissent precision/recall/F1 and exact sets separately; union metrics are supplemental. Declare treatment of no-positive cases and failed predictions.

Align by meeting/member identity rather than list position. Assert identical keys and denominator counts. Include all predeclared final meetings, and expose missingness and fallback coverage. Supply confusion matrices with empty classes visible. Do not use a pooled 25-meeting score as a holdout score.

Meetings are the principal experimental units. Seeds are repeated measurements nested within meetings, not additional independent historical observations. Use paired comparisons to the baseline; account for temporal dependence and policy regimes. Any bootstrap with very few meeting clusters is descriptive and fragile. Report uncertainty on improvement, not just point estimates of accuracy.

For a constant-label test, acknowledge that conditional label permutations carry no class information. Choose an appropriate baseline-referenced null rather than uniform random authorized actions. Predeclare handling of multiple outcomes, model families, prompt variants and scenarios. Preserve all attempted settings and their results.

Determine sample size from the practical paired improvement target, discordance assumptions, regime coverage and available independent meetings. A binomial lower bound from perfect performance is not a sample-size justification for added value over persistence. If the available sample is insufficient, report an exploratory study and the detectable effects rather than declaring a validation gate passed.

## Freeze, execute, and report

Before the final test, write a dated freeze manifest, hypothesis/metric protocol, code/data/config/model hashes, environment lock and computational budget. Run the frozen test once. If a blocker requires a fix, record the failure and designate subsequent evaluation as a new test with appropriate data separation; do not silently retune against the inspected final test.

The reproduction command must either recompute the scientific tables from their versioned inputs or identify a verified replay with matching prompt/input/model hashes. It must fail on missing, corrupt, stale, mismatched, mock-labeled-as-live or incomplete artifacts. Generate report numbers directly from recomputed tables and assert agreement. File existence alone is insufficient.

The resulting paper should state which hypotheses were supported, unsupported, or underpowered; which measurements were live, cached, mock or fallback; the empirical scope of the data; and which counterfactual conclusions concern only the simulator. Archive failures and negative results alongside positive observations.
