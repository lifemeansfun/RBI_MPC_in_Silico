# Independent scientific peer review

Reviewed: 2026-10-05. Input: the supplied workings summary, file map, and copied tree at `/var/folders/wh/rvj5dycx0zgbk951gfhl9jb80000gn/T/rbi_blind_review_4vrztkjc`. No original-checkout files, Git history, memory, previous reviews, or other reviewers' work were consulted. The shared virtual environment was used as authorized. Supplied-context isolation is not operating-system isolation; this was an independent review of supplied evidence, not a security-isolated execution.

## Scientific judgment

The project is a promising course-level simulation framework with useful engineering and a locally reproducible numerical comparator. It does **not** yet establish the scientific claims that deliberation improves RBI decision prediction, that the reported historical scores validate the multi-agent model, or that the reported wedges identify human persuasion or superior economic judgment. The decisive issues are demonstrated input lookahead, persona calibration on the supposed holdout, a disconnected deliberation round, weak baselines, and insufficient experiment provenance. Passing code checks does not resolve these issues.

A defensible question is: **Does peer deliberation add predictive information beyond independent persona prompts and historical persistence when predicting committee decisions and individual rate/stance ballots from information available before a meeting?** A separate question is whether controlled information-flow changes cause changes *inside this simulator*. Neither question implies that simulated responses identify causal effects in the real MPC.

## Verified strengths and executable results

- `.venv/bin/python -m pytest tests -q`: **28 passed in 0.93 seconds**.
- `scripts/deep_verification_battery.py`: **16/16 checks passed**. `scripts/intensive_academic_verification.py`: **17/17 passed**. `scripts/academic_integrity_guard.py` passed on the initially supplied artifacts. These are executable assertions and numerical checks, not 33 formal scientific proofs.
- `scripts/verify_contamination_audit.py` passed its text-masking and arithmetic checks. It does not evaluate a model on a genuinely unseen panel.
- `scripts/reproduce.py` completed successfully and regenerated figures from existing evidence. Its source does not rerun the empirical model or regenerate its research tables.
- A fresh **25 meetings × 1,000 Monte Carlo draws** run through `RationalPanelRunner(results_dir=reviewer_evidence/rational_results)` reproduced **all shared values of the saved rational table exactly**.
- All **25 copied raw HTML files** match their copied manifest hashes. All **150 statements** are normalized verbatim substrings of the corresponding release after correcting the manifest's September 2022 month label. This demonstrates strong local archival consistency; it does not establish independently published “official SHA-256 hashes.”
- All **29 saved holdout-date outcome packages** found before reviewer-generated runs have 24 round files; reaggregated final rate and stance ballots agree with their stored committee outcomes, and their committee rates agree with the holdout CSV. Their saved fallback counts are zero. These are internally consistent saved artifacts, not independent authentication of provider/model identity.
- An independent exhaustive check of the **20 binary 3–3 rate splits** correctly selected the Governor's ballot. The pure rule engine is useful within this restricted modeled domain.
- Ground-truth labels reside in `MacroMeetingSnapshot`, but `to_prompt_text()` omits them. I found no direct label-string leakage through that formatter; this positive result must be distinguished from the demonstrated other leakage routes.

Raw commands, outputs, controlled probe scripts, captured prompts, environment versions, and key input hashes are preserved in the attached `reviewer_evidence.zip`. The probes make **zero external generation calls**.

## Consequential deficiencies, remedies, and acceptance checks

### D1 — The “real-time” macro panel contains verified future information

**Source:** `src/data_pipeline/macro_builder.py:365–381`, especially headline 7.44 and food 11.51 for August 10, 2023; `src/schemas/macro_schema.py:11–15,51–84`; report `results/RESULTS_REPORT.md:65,138,239`.

Those exact July CPI/CFPI figures were released on **August 14**, four days after the simulated meeting, according to [MoSPI's official release](https://mospi.gov.in/sites/default/files/press_release/CPI_PR_14aug23.pdf). The [RBI retrospective](https://www.rbi.org.in/scripts/BS_ViewBulletin.aspx?Id=22120) describes June inflation around 4.8 as the latest observed inflation entering the meeting; the copied release says the same. This is a demonstrated input leak, independent of whether the LLM memorized any historical decisions.

The builder persists a hand-entered list rather than acquiring vintage-aware observations. There are no observation/release timestamps or per-cell sources. The output gap is hand-entered; a search of the data and rational modules found no implementation producing the claimed HP-filtered series. Schema validation establishes type/range conformity, not historical availability or accuracy.

**Impact:** The holdout and both comparator tracks cannot be interpreted as pre-meeting forecasting evidence. Corrections may change either model's performance; the direction and size are unverified.

**Remedy:** Rebuild a source-linked vintage panel with reference period, release time, vintage/revision identifier, and transformation for each input. Compute any output gap from only available history or label it as a synthetic assumption.

**Acceptance:** An executable assertion rejects every input whose release time exceeds the meeting cutoff; manually cross-check several early and late meetings against original releases, including August 2023, then rerun the frozen evaluation.

### D2 — Persona construction uses the entire purported holdout

**Source:** `src/persona_engine/extractor.py:115–128,150–172,208–227`; `src/backtest/run_holdout_live.py:38–55,73–86`; `src/schemas/persona_schema.py:39–67`.

The default extractor reads all dated statements without a cutoff. For all six active holdout members its corpus includes all eight holdout meeting statements. Every stored persona score equals the score recomputed from this full corpus. Calibration-only scores differ: for example Varma **−0.28 versus stored −0.31**, Das **0.21 versus 0.23**, and Ranjan **0.46 versus 0.43**. The supplied code contains no `HOLDOUT_LOCKED` enforcement in persona construction. The actual split is **17 calibration + 8 holdout**, despite repeated 16+8 specifications.

A prompt saying “zero knowledge” of future events does not untrain a foundation model or prevent same-year lookahead. `_scan_lookahead_leakage` only warns about explicit future years; it neither validates provenance nor excludes contaminated outputs.

**Impact:** “Unseen holdout,” “zero heuristic contamination,” and clean temporal-firewall claims are unsupported. Pretraining contamination remains an additional possibility, not a proven explanation of every correct vote.

**Remedy:** Freeze personas, prompts, model version and calibration before a new evaluation window; enforce a source cutoff and record corpus hashes. Separate development, historical retrospective testing, and genuinely prospective testing.

**Acceptance:** A test intentionally adding a holdout statement to calibration must fail. Produce a manifest proving every persona source predates the cutoff, and report new prospective or untouched post-cutoff performance with matched baselines.

### D3 — Binding votes cannot depend on Round 3's compromise output

**Source:** `src/behavioral/debate_orchestrator.py:148–169,181–205`; report `results/RESULTS_REPORT.md:64–68,176–180,238`.

Round 3 is computed and saved but the final digest contains **only Round 1 and Round 2**. There is no persistent conversation state in the client's generation calls. In my controlled probe, changing every Round 3 preference from −50 to +50 and changing every rationale token left **all six Round 4 user prompts identical**; no Round 3 sentinel reached any binding vote prompt.

**Impact:** The Round 3 “compromise dip” cannot be the channel causing final voting behavior. The four-stage process and claims that compromise assessment drives final decisions do not describe the implemented information graph.

**Remedy:** Pass validated Round 3 synthesis, including each agent's own revised view, to final voting; define the intended information graph explicitly.

**Acceptance:** Sentinel-based tests must establish that permitted Round 3 information reaches the intended final voters. Then compare independent-only, two-round and full-round protocols under paired conditions; do not treat any resulting change as necessarily an improvement.

### D4 — The holdout performance does not demonstrate incremental predictive advantage

**Source:** `results/tables/holdout_meeting_by_meeting_comparison.csv`; `src/backtest/run_holdout_live.py:174–197`; `scripts/stress_test_permutation.py:14–38`; `results/stress_test_results.md`.

My recomputation from the saved labels is:

| Method | Rate accuracy | Stance accuracy | Dissent TP / FP / FN | Dissent F1 |
|---|---:|---:|---:|---:|
| Saved live model | 8/8 | 8/8 | 10 / 4 / 0 | 0.8333 |
| Always pause + preserve prevailing stance | 8/8 | 8/8 | — | — |
| Always predict Varma as dissenter | — | — | 8 / 0 / 2 | 0.8889 |
| Preserve previous meeting's dissenters | — | — | 9 / 0 / 1 | 0.9474 |
| Aggregate saved independent Round 1 outputs | 8/8 | 8/8 | 10 / 5 / 0 | 0.8000 |

Every holdout decision is a pause and every committee stance is unchanged. The model improves one aggregate dissent false positive relative to the saved independent initial positions, but performs worse than persistence on the stated F1 objective. The Varma-only baseline uses a strong identity prior; the prior-meeting baseline uses public previous ballots and requires no future labels.

Eight successes imply an independent-binomial exact 95% interval of approximately **[0.631, 1.000]**, even before recognizing serial dependence. Six members × rounds × meetings are not independent new policy regimes. Only one replicate is executed despite configured `n_replicates: 3`. The “permutation” script draws uniformly from five actions; `5^{-8}` is the probability under that contrived random-action null. It neither permutes observed labels nor tests advantage over persistence. A correct rejection of uniform guessing does not establish forecasting skill.

**Remedy:** Make persistence, calibrated reaction functions, independent-agent aggregation and a comparable single-agent model mandatory baselines; use broader regime coverage, rate and stance ballots separately, paired meeting-level uncertainty, and preregistered decision criteria.

**Acceptance:** Publish all baseline predictions, confusion matrices, class counts, uncertainty, and paired effect sizes on a clean frozen panel containing hikes, holds and cuts. Incremental claims require demonstrated advantage over strong baselines, not only threshold passage.

### D5 — Institutional fidelity extends beyond the authority actually supported

**Source:** `src/rule_engine/engine.py:3–9,40–41,77–86,147–162`; `scripts/intensive_academic_verification.py:276–296`; `src/attribution/attribution_runner.py:39–59`; report `results/RESULTS_REPORT.md:14,27–31,127,235`.

The project repeatedly attributes casting votes to **§45ZL**, which addresses publication of proceedings; voting is governed by **§45ZI(7)–(8)**. Official [government MPC guidance](https://ies.gov.in/arthapedia/concept/monetary-policy-committee-mpc) and [RBI's institutional explanation](https://systemhealth.rbi.org.in/Scripts/FS_Overview2752.aspx.html) specify a quorum of **four**, with majority of members present and voting and a Governor casting vote on equality. Rejecting four or five members proves a chosen full-roster restriction, not “statutory quorum enforcement.”

The Governor-weighted median for rate fragmentation and plurality/Governor stance fallbacks are modeling assumptions for multicandidate preferences, not demonstrated statutory resolution procedures. The code also labels some fragmented profiles as casting-vote cases. Neutral is hard-coded as the stance “status quo” in casting ablation even where the prior stance is withdrawal. A universal statutory dual-vote mandate and Governor-last visibility protocol need primary procedural support.

**Remedy:** Correct legal references; distinguish a six-present research protocol from legal quorum; model voting on proposed resolutions or document and sensitivity-test alternative multicandidate aggregation assumptions. Preserve actual prior stance when using a status-quo comparator.

**Acceptance:** Review every institutional rule against primary text and representative actual minutes. Cover valid four-, five- and six-present cases where relevant; explicitly mark unsupported synthetic cases and ensure casting flags denote the mechanism actually applied.

### D6 — Attribution does not cleanly isolate persuasion and currently supplies no committee-level persuasion effect

**Source:** `src/behavioral/debate_orchestrator.py:97–106,136–143,191–205,261–277`; `src/attribution/attribution_runner.py:125–167`; `src/scenarios/run_counterfactual_experiments.py:252–334`; report `results/RESULTS_REPORT.md:18,203–224`.

Withholding Varma removes his initial/rebuttal rows from peers, but my capture shows **his final rationale still reaches the Governor**. His vote remains, intentionally, yet vote visibility is an unblocked information path. Round 3 is already disconnected. The ablated member also receives altered context about the committee, so this is not simply removing one outgoing message stream while holding that member's own behavior fixed.

Between independent Round 1 and later rounds, agents also receive fabricated “confidential” SPF forecasts calculated deterministically from the briefing and labeled as survey/internal data. Thus changes between rounds combine peer messages, extra economic signals and different task instructions. A behavioral–Taylor wedge likewise changes model class, inputs and parameterization simultaneously; it cannot isolate deliberation.

The supplied attribution table reports no committee shift for both leave-outs and both macro mutings. The tied casting example is manually constructed with `member_votes=[]`, and its neutral fallback is an assumed rule. These are useful null results and a code illustration, not empirical evidence identifying human causal mechanisms.

**Remedy:** Specify the estimand and intervention graph. Separate message content, identity/authority, vote visibility and staff information. Label synthetic forecasts accurately. Freeze donor outputs or use a well-defined rerun intervention, with paired seeds and repeated conditions.

**Acceptance:** Information-flow probes establish absence/presence of every intended pathway; publish member-level as well as committee-level paired effects, intervals and nulls. Claim simulator-local causal effects only; real-MPC mechanism claims need external validation.

### D7 — Provenance, checkpoint identity and reproduction are insufficient for the stated claims

**Source:** `src/infra/transcript_logger.py:37–64`; `src/backtest/backtest_runner.py:145–185`; `src/backtest/run_holdout_live.py:92–122`; `src/scenarios/run_counterfactual_experiments.py:93–95,114–115,148–149`; `scripts/reproduce.py:91–115`.

Transcripts save parsed outputs, without the promised per-call prompt snapshots, resolved model/fallback identity, API receipt, token/cost record or configuration hash. Checkpoints are keyed only by date, and the live runner adopts older saved outcomes without verifying model/persona/input identity. Changing the experimental condition does not invalidate these checkpoints.

Baseline and shocked runs reuse meeting date and replicate ID under one logger. My overwrite probe confirms both write the **same path**, leaving only the shocked payload. Leave-outs and macro mutings collide too. Therefore the remaining date-based transcripts cannot fully trace every table condition. `replicate_id` does not enter the generation seed; calls default to the same seed and cache identity.

`make reproduce` verifies existing artifacts and renders figures; it does not regenerate the backtest or intervention tables. Missing artifacts emit a warning followed by a success message. Passing it is verified; “all scientific results reproduced” is not.

**Remedy:** Use immutable experiment IDs derived from data/persona/prompt/model/seed/condition hashes; log raw responses and exact prompts with resolved metadata; invalidate mismatched checkpoints; provide separate deterministic replay and fresh-generation commands.

**Acceptance:** Changing one input/model/seed forces a new checkpoint; all conditions coexist without overwrites; every table row traces to a manifest and complete inputs. Offline replay reconstructs tables in an empty results directory and fails nonzero for missing/corrupt evidence.

### D8 — Report and integrity-check conclusions exceed what the checks establish

**Source:** report `results/RESULTS_REPORT.md:18,100,104–132,206–207,241,247–250,265–267`; `src/run_stage2_pipeline.py:65–72,141`; `scripts/academic_integrity_guard.py:68–103,117–124,157–169`; `scripts/deep_verification_battery.py:275–301`.

The abstract calls **76%/76%/0.68** multi-agent results, while Table 1A correctly labels them a status-quo/stance heuristic; the stage-two script explicitly chooses `provider="mock"`. The report's early-2022 “deliberation wedge” likewise uses the benchmark panel. Report persona parameters differ from supplied YAML (for example Goyal −0.18 in the report versus −0.07 in the profile).

My controlled guard probes show that **F1=0.01** in an alternative metrics table still passes table/report concordance because the report contains 0.83, and **225 files containing “NOT JSON”** pass the claimed complete transcript-chain check. Neither hashes nor JSON contents are validated there.

Other checks are overinterpreted: persona SVD rank does not prove independent cognition, a hand-entered ranking correlation does not establish empirical dissent ranking, and positive inflation derivatives alone do not prove determinacy in an unspecified macroeconomic equilibrium. These issues undermine the research conclusions without negating useful mathematical/code checks.

**Remedy:** Generate reported metrics and parameters from typed evidence with explicit track labels. Replace substring/existence assertions with semantic reconciliation and validation. Call numerical tests numerical tests and restrict economic conclusions to the models actually analyzed.

**Acceptance:** Mutation tests reject wrong metrics, invalid JSON, altered ballots, wrong track labels and missing receipts. Abstract, tables and conclusion reconcile automatically to genuine experiment manifests; heuristic performance cannot be presented as LLM performance.

### D9 — Comparator interpretation and novelty are not yet demonstrated

**Source:** `src/rational/rational_panel_runner.py:25–34`; `src/rational/taylor_rule.py:55–92`; `src/rational/monte_carlo.py:66–69,119–120`; report `results/RESULTS_REPORT.md:75,84–100,228–241,267`; bundled `kazinnik_extracted.txt:864–919`.

The numerical comparator is reproducible, but its coefficients are constants with no supplied fitting procedure, calibration uncertainty or fitted-loss report. Gaussian input noise is a specified sensitivity model rather than demonstrated real-time forecast error. Its dissent probabilities count rate dissent only, whereas behavioral scoring unions rate and stance dissent. Headline-only insensitivity to the food/core split is true by construction; it cannot validate LLM economic superiority or identify the value of debate.

The saved stress-test report correctly records the second-model comparison as inconclusive because an endpoint returned 404 and a heuristic fallback ran. I did not independently rerun that provider check. The pandemic and taper-tantrum scenarios are synthetic shocks to existing panel anchors, not empirical validation on those historical episodes or a new roster.

The October 2025 Kazinnik paper does contain interactive discussion, though it imposes an explicit final-rate/dissent mechanism; a fair comparison must distinguish those choices. The [current author version](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5424097) reports a much larger historical backtest, so the report's frontier comparison is version-specific and now incomplete. [MiniFed](https://arxiv.org/abs/2410.18012) and [hawkish/dovish latent-belief debate research](https://arxiv.org/abs/2511.02469) also predate this review. Their reported results were not independently replicated here.

**Remedy:** Estimate/tune comparators only on calibration, document objective and parameter uncertainty, align dissent targets, include forecast/core-sensitive reaction rules and strong simple baselines, and update versioned related work. Position the contribution as an RBI-specific, empirically tested adaptation unless a stronger novel result is established.

**Acceptance:** Run identical clean evaluation inputs and outcome definitions across tracks; publish calibration choices and heldout effect sizes. A novelty matrix must identify the new institution-specific question/result rather than count components or assert generalized superiority.

### D10 — Legal output values can crash integration, and budget errors are swallowed

**Source:** `src/schemas/debate_schema.py:11,135–158`; `src/rule_engine/engine.py:33,43–45`; `src/behavioral/debate_orchestrator.py:339–361,514–538`; `src/infra/llm_client.py:84–95`.

Schemas accept 35 and 40 bps, but the orchestrator's aggregator permits only −50, −25, 0, 25 and 50. A valid-schema 35-bps fake response produces a final **ValueError**; these sizes actually occur in the historical panel. Invalid rate text silently becomes zero and invalid stance text is accepted with `fallback_triggered=False`.

A fake client raising `BudgetExceededError` on every call did **not halt** the meeting: the orchestrator made **24 attempts**, reported **24 fallbacks**, and completed. The source's cost check occurs after provider generation, so this is not a strict pre-call cap. No billing or cap overrun was incurred in my probe.

**Remedy:** Share one declared action/stance domain across schemas, prompts, configuration and aggregation; fail or visibly flag invalid output. Propagate budget/cancellation errors and reserve expenditure before launch; preserve resolved model identity on fallback.

**Acceptance:** End-to-end valid 35/40-bps historical cases succeed if in scope; invalid payloads are rejected/flagged; budget exhaustion aborts before any subsequent provider request.

## Feasibility and limits

The required improvements are feasible without abandoning the framework: fix the information graph, add immutable experiment manifests, rebuild vintage inputs, freeze calibration, and evaluate against stronger baselines. A broader prospective evaluation is the main empirical burden. Offline replay is inexpensive; meaningful repeated and cross-provider experiments require verified current API access and a measured resource/cost plan.

I did not invoke Gemini or any other paid generation, reproduce private deliberations, independently authenticate every raw release remotely, establish foundation-model training contamination, or reproduce the author-reported results of outside papers. The direct RBI URL yielded a navigation view and India Code PDF opening timed out; other official sources supported the identified availability/legal issues. No infrastructure failure prevented the offline checks. Some commands intentionally create altered artifacts solely under the copied tree, and their evidence is explicitly marked as controlled probes. None of the review's negative findings requires assuming that the stored live transcripts were fabricated.

The existing implementation and archive support a useful demonstration and further research. Clean predictive and mechanistic validation remain unfinished.

Not fully elite research grade
