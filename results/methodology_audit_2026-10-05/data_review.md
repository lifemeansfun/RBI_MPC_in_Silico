# Independent data, timing, persona and label audit

Audit date: 5 October 2026. This review concerns the current working tree, including the user's existing modifications. It does not infer that the current code produced every older transcript. No production source, existing dataset, existing persona, checkpoint or result was changed. All probes were offline; no model API was called. SHA-256 comparison before and after the probes confirms preservation of the 185 audited data/persona input files.

## Assessment

The local minutes-to-statements chain is unusually well preserved: 25/25 HTML files match their recorded hashes, all 150 extracted member statements reproduce byte for byte, and their complete normalized texts occur in the corresponding raw source. However, local source integrity does not establish valid historical information sets or valid labels. The existing panel contains demonstrated future CPI releases, the persona calibration uses the held-out statement corpus, and the dissent truth merges reservations with formal votes inconsistently. These defects prevent the published results from supporting an uncontaminated historical prediction claim.

These conclusions concern the evaluation design, not intent. The artifacts are useful as an exploratory reconstruction of committee behavior once their retrospective inputs and coding choices are disclosed.

## Reproduction and evidence

Run from the repository root:

```sh
.venv/bin/python results/methodology_audit_2026-10-05/data_probe.py
```

The script blocks socket connections and only writes under this audit directory. Evidence is preserved in:

- `data_probe.py`: complete reproducible probe, including explicit manually adjudicated mappings.
- `data_probe.json`: environment, before/after input hashes, 25 source paragraphs, panel comparisons, persona scores, and schema/FRED probes.
- `data_probe_stdout.txt`: raw printed summary and the observed FRED warning behavior.
- `data_extraction_stdout.txt` and `reextracted_statements/`: extraction log and safely re-extracted source corpus.
- `data_adjudicated_truth.json`: separate rate votes, stance votes, guidance disagreement, and reservation status, with source evidence for all 25 meetings. This preserves the original ground truth and states the reviewer's coding convention.
- `data_cpi_context_comparison.csv`: the panel's CPI against the latest rounded observation described in the associated minutes for every meeting.

Probe environment: Python 3.11.16, macOS arm64, pandas as recorded in `data_probe.json`. Source citations below use repository-relative paths and verified line numbers; raw RBI HTML commonly embeds the entire minutes body on line 863 or 864, so paragraph numbers disambiguate those references.

## Findings

### D1 — P1: Historical information sets contain proven future CPI releases

**Verified implementation and data:** `src/data_pipeline/macro_builder.py:365-369` assigns the 10 August 2023 snapshot headline CPI 7.44% and food CPI 11.51%. These are also the installed parquet values; the complete parquet matches the hardcoded builder. The July 2023 values were released on **14 August 2023 at 17:30**, after the meeting, as the [official MoSPI release](https://www.mospi.gov.in/sites/default/files/press_release/CPI_PR_14aug23.pdf) documents. This source was retrieved by the coordinating reviewer. The associated raw RBI minutes, `data/raw/minutes_html/mpc_minutes_prid_56252.html:863`, paragraph 10, state that headline CPI increased to **4.8% in June**, and paragraph 12 discusses the prospective vegetable spike. The difference is not rounding or a disagreement about policy outcomes.

The same defect recurs for **8 August 2024**: `macro_builder.py:479-483` supplies headline CPI **3.54%**, while the [official July 2024 release](https://mospi.gov.in/sites/default/files/press_release/CPI_PR_12aug24.pdf), corroborated by the [PIB release](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2044604&lang=2&reg=48), is dated **12 August 2024 at 17:30**. These sources were also retrieved by the coordinating reviewer. The corresponding raw minutes `mpc_minutes_prid_58545.html:863`, paragraph 9, identify **5.1% in June** as the observed latest headline inflation.

**Broader offline evidence:** 21 of 25 panel CPI values differ by more than 0.051 percentage points from the latest rounded CPI identified in their own minutes. Seven of eight holdout meetings have this clear contextual mismatch. For June 2024, the panel's 4.75% rounds to the minutes' 4.8%, so rounded-text comparison alone cannot resolve its vintage. The complete table is in `data_cpi_context_comparison.csv`. We do not equate every contextual mismatch with separately proven post-meeting publication: individual release archives are needed for that stronger claim.

**Impact:** The future prints enter every agent's official briefing (`src/schemas/macro_schema.py:56-64`) and Taylor benchmark, changing the information available to both systems. Temporal language in the prompt cannot make a future number historically available. This invalidates a real-time backtest interpretation and contaminates shock scenarios built on those snapshots. Whether correcting the data reduces, preserves or improves model accuracy remains untested.

**Remedy:** Rebuild snapshots from a per-series vintage ledger with reference period, release timestamp, revision/vintage, source URL, units and value. Assert release timestamp is strictly before the decision's information cutoff. Preserve the retrospective panel under an explicitly retrospective name and rerun only after the corrected protocol is frozen.

### D2 — P1: The supposedly held-out statement corpus calibrates the personas

**Verified implementation:** `src/persona_engine/extractor.py:115-128` loads all date directories, with no cutoff or forbidden holdout assertion. `extractor.py:150-173` computes lexical frequency and mixes it with a fixed prior. `src/backtest/backtest_runner.py:55-75` and `src/backtest/run_holdout_live.py:38-55` load the same static YAML files for every evaluated meeting. Searching the implementation finds no `HOLDOUT_LOCKED` enforcement promised in the plan's line 52.

**Executed quantitative probe:** All seven persisted YAML scores exactly reproduce full-corpus calibration. All six members active in the holdout use statements from **all eight holdout dates**, through 8 August 2024. Recomputing on dates at or before 6 April 2023 changes all six scores:

| Member | Calibration statements | Holdout statements | Persisted/full-corpus score | Calibration-only score |
|---|---:|---:|---:|---:|
| Das | 17 | 8 | +0.23 | +0.21 |
| Patra | 17 | 8 | +0.61 | +0.60 |
| Ranjan | 7 | 8 | +0.43 | +0.46 |
| Varma | 17 | 8 | -0.31 | -0.28 |
| Goyal | 17 | 8 | -0.07 | -0.06 |
| Bhide | 17 | 8 | +0.15 | +0.14 |

Ranjan's holdout statements contribute 7,699 of 14,997 words, exceeding his calibration corpus of 7,298 words. Saggar has no holdout statements and is the one uncontaminated score in this specific comparison.

The static exemplar quotes also violate an expanding historical information set in early calibration meetings. For example, `personas/2020_2024_roster/jayanth_varma.yaml:15-23` includes December 2020 excerpts when simulating October 2020. Bhide's themes include February and June 2021. Even statements from the target meeting itself are post-decision material if the task is prediction before the vote.

**Impact:** A split in the evaluation loop does not create an unseen holdout when its documents helped construct model inputs. The modest score changes do not establish how much they alter decisions; that requires a controlled rerun. The flaw is sufficient to withdraw the claim that the current holdout was unexposed to calibration.

**Remedy:** Freeze personas from calibration documents only, including biographies, priors, quotes and author-selected interpretations. Store calibration date limits and content hashes in each persona. For historical calibration replay, either use a genuinely expanding window or explicitly call it retrospective reconstruction. Do not repair the existing holdout and then claim it is fresh; reserve an untouched future panel.

### D3 — P1: Dissent labels inconsistently merge reservations and formal ballots

**Verified source error:** `macro_builder.py:194-210` labels Varma as a dissenter on **8 April 2022**. Raw `mpc_minutes_prid_53601.html:864`, paragraphs 18 and 19, record unanimous rate and stance votes. Varma's signed statement says he votes for both resolutions. This is a definite false positive, independent of reservation terminology.

**Verified holdout coding defect:** The first four holdout dates have unanimous hold votes and Varma expressing reservations on stance. The June 2023 signed statement explicitly says the **main reason for not dissenting** is that the stance appears vestigial. April 2023 says he **refrains from dissenting**. August, October and December 2023 continue reservations, without a recorded vote for neutral or against the stance. Nevertheless, `macro_builder.py:327-419` assigns Varma to `real_dissenters` in every one of these meetings.

This is not a harmless uniform definition of dissent: **August 2022** also records Varma's reservations, with his signed statement expressly declining an outright dissent, yet `macro_builder.py:251-267` records no dissenter. One convention therefore cannot explain all existing labels.

| Holdout meeting | Recorded rate disagreement | Recorded formal stance disagreement | Separate reservation status |
|---|---|---|---|
| June, August, October, December 2023 | None | None recorded | Varma |
| February, April 2024 | Varma: -25 bps | Varma: neutral | — |
| June, August 2024 | Varma and Goyal: -25 bps | Varma and Goyal: neutral | — |

The full 25-row adjudication is in `data_adjudicated_truth.json`. Under strict formal rate/stance disagreement, six panel rows differ from the installed truth: April 2022 and April/June/August/October/December 2023. We do **not** infer a yes vote, an abstention or a neutral ballot where the minutes merely say reservations. Those are distinct statuses.

An additional scope issue occurs in October 2020: the raw resolution records Varma voting against the **time-contingent forward-guidance formulation**, while agreeing with the accommodative stance category. The existing label is empty. It can be correct for a narrow coarse stance-class target, but not for a claim to capture every formal committee dissent. The adjudication preserves a separate guidance field so that this choice is visible.

**Impact:** Union-of-member dissent metrics (`backtest_runner.py:109-114`; `run_holdout_live.py:133-138`) compare formal simulated alternative ballots to the conflated truth. Their precision, recall and F1 cannot be interpreted as formal dissent prediction without re-adjudication. The statistical reviewer is independently calculating sensitivity to the strict-ballot convention. Rate and stance dissent also need separate metrics because the union can credit the correct member for the wrong issue.

**Remedy:** Maintain ballot tables with rate action, stance action, guidance disagreement and reservation/abstention status for each member. Record source paragraphs and double-adjudicate borderline cases. Report both a strict-ballot score and any explicitly defined broader qualitative disagreement score.

### D4 — P2: May 2022's meeting is dated by its minutes publication

`macro_builder.py:213` and the installed parquet give **18 May 2022** for the +40 bps decision. The manifest title (`data/raw/manifest.csv:22`) and the raw introductory paragraph identify the off-cycle meeting as **2 and 4 May 2022**. The [official policy announcement](https://www.rbi.org.in/commonman/Upload/English/PressRelease/PDFs/PR154MPC04052022.pdf) is dated 4 May and was retrieved by the coordinating reviewer.

The executed extractor also returns 18 May for this raw document. Its regex (`statement_extractor.py:82-89`) supports `to`, hyphens and a single day, but does not correctly support the title's `May 2 and 4, 2022`; it searches the full webpage and finds another date. The raw and processed chain is internally consistent but consistently dates the wrong event.

This shifts the historical cutoff by 14 days. It is especially material because the raw signed statement explicitly anticipates April CPI's publication on **12 May**; the panel supplies April CPI 7.79%. Dating the decision to 18 May obscures that leakage. Fix the event date independently of publication date and preserve both.

### D5 — P1: Macro provenance and output-gap claims exceed the implemented pipeline

`macro_builder.py:20-497` is a hand-authored literal panel. `build_macro_panel` validates types/bounds and writes that literal (`:509-540`); it does not merge domestic release files or fetch FRED. The current raw directory contains minutes and their manifest, but no cached FRED or domestic indicator source archive. The parquet matches the literal exactly.

The output gap is described as HP-filtered (`macro_schema.py:25`), and `config.yaml:34` declares a monthly smoothing parameter. However, no HP-filter implementation or underlying output-level series appears in `src`, `scripts` or tests. All 25 gaps are literals. We can therefore verify neither filter execution nor one-sided vintage safety. The relevant finding is missing evidence, not a demonstrated two-sided HP computation. No claim of HP lookahead should be made without an implemented and archived filter to test.

The builder's Pydantic validation verifies formatting and selected numeric bounds, not that values came from an official source, were available on the date, have the correct unit or agree with minutes. `macro_schema.py:14` asserts that every value was available at the meeting, without an availability field or corresponding validator.

**Remedy:** Add provenance records as part of the dataset, not merely prose claims. For output gap, document the actual definition, underlying frequency, transformation, filter/window and every vintage. Validate rolling estimation against an added-future-data test; if no empirical gap exists, mark it as assumed rather than estimated.

### D6 — P2: FRED alignment confuses observation dates with release dates and can use a future fallback

The dormant FRED client selects the last observation whose **observation timestamp** is no later than the meeting (`fred_client.py:85-94`). This is insufficient for monthly series such as `FEDFUNDS`, whose full-month values are not available at the month-start timestamp. The client stores no release/vintage date and uses the latest downloaded historical revisions. Its no-prior-data branch explicitly returns the earliest observation even if it lies in the future (`:95-99`).

An offline stub probe demonstrated both selection behaviors, including the warning followed by a future value for 10 July when the earliest observation is 1 August. This is a behavioral test of the selector, not a retrieval of real FRED data. It does not establish that the current hand-authored panel was generated through this client.

There is also a definition mismatch: the client chooses `FEDFUNDS` (`:21-24`), while `macro_schema.py:29` defines the field as the **upper target rate**. Independently read official metadata confirms that [FEDFUNDS](https://fred.stlouisfed.org/series/FEDFUNDS) is a monthly average of daily **effective** rates, whereas [DFEDTARU](https://fred.stlouisfed.org/series/DFEDTARU) is the daily upper target limit. The observed panel sequence resembles effective monthly rates, but source metadata is needed to confirm every entry. Define one economic series consistently in both its provenance and its model interpretation. Missing prior data should fail or remain missing, with a documented imputation policy.

### D7 — P1: Synthetic expectations are presented to agents as observed SPF and market data

`debate_orchestrator.py:261-277` creates CPI expectations by shrinking current CPI toward 4%, creates a GDP growth expectation from current **GVA** growth plus a gap term, and creates a forward-rate premium from the CPI expectation. The generated prompt labels them **Survey of Professional Forecasters**, **Market-Implied** and confidential data; it does not tell the agent that these are synthetic formulas. `:104-105` requires agents to consider them from round 2 onward.

These quantities contain no new independent latent information, and the GVA-to-GDP growth conversion has no reconciliation. Calling them latent variables or confidential professional forecasts cannot compensate for the missing data. A zero-valued GVA is also replaced by 6.5 through the `or` expression, whereas negative nonzero values are retained.

**Impact:** Agents may give unwarranted weight to an invented independent information source. This adds a researcher-selected policy signal and changes the causal interpretation of the debate.

**Remedy:** Obtain genuinely dated staff/survey forecasts, or visibly label the values synthetic and treat them as an experimental condition. Compare runs with and without the synthetic signal using identical original macro inputs and report the comparison as a sensitivity, not recovered observables.

### D8 — P2: Persona calibration and its validation are insufficiently independent

The score called a Bayesian blend is literally `0.60*fixed_prior + 0.40*lexical_score` (`extractor.py:165-172`), with no likelihood, posterior uncertainty or fitted blend weight. It counts words such as inflation, target, growth and recovery without distinguishing endorsement, negation or context. The paper's claim that voting records empirically calibrate the scores is not implemented in this function.

Exemplar selection uses the sign of the fixed prior (`:175-183`), so qualitative evidence is selected to align with a prior interpretation. The validation's supposedly empirical ranking is another hardcoded subjective member ranking (`scripts/deep_verification_battery.py:275-301`), not a computed blind external target. Correlation with that ranking measures agreement between two researcher-selected orderings; it does not independently validate economic posture or predictive value.

The resulting scores and quotes are transparent and interpretable, which is a strength. They are appropriate documented assumptions for exploration. To claim empirical calibration, fit a stated estimator only on permitted training labels, assess uncertainty, compare against fixed-prior and text-only baselines, and validate on genuinely independent annotated statements/votes.

### D9 — P2: The described 16/8 split is actually 17/8

The panel has 25 rows; the implemented cutoff at 6 April 2023 yields **17 calibration and 8 holdout**. The extra off-cycle meeting explains the arithmetic, but the configuration comment and runner descriptions still say 16/8 (`config.yaml:27`; `backtest_runner.py:3-4`). The configured `calibration_holdout_split` is not used by the hardcoded date filter (`backtest_runner.py:150-153`). This is a reproducibility discrepancy, not evidence that the implemented eight holdout dates were misidentified.

### D10 — P2: Current date validation does not enforce a real date

The validator (`macro_schema.py:43-49`) checks only split-part count and year length. The executed probe accepted `2023-99-99`. It also does not enforce zero-padding, so downstream string comparisons need not be chronological for arbitrary accepted inputs. All existing panel dates are unique, sorted and formatted uniformly, so the malformed-date bug is a demonstrated robustness flaw rather than an observed disorder in this dataset. A genuine date type/parser should enforce calendar validity.

## Fair strengths and limits

- **Verified:** All 25 local raw files match the manifest, all 150 processed statements reproduce, and full-text attribution to their corresponding raw documents succeeds. Existing extraction tests had checked only a 120-character prefix in any raw file (`deep_verification_battery.py:239-240`); this audit supplies a stronger association check.
- **Verified:** The installed parquet and literal builder agree exactly, so the problems are not unexplained processing drift. Every source yields six member statements, and the 2022 roster switch appears consistent with the raw roster. Dates are sorted and unique in the current data.
- **Verified narrow protection:** `MacroMeetingSnapshot.to_prompt_text` does not serialize truth columns or dissenter identities. The presence of truth columns inside the snapshot object alone is not evidence that the LLM sees those labels. Our confirmed leakage pathways are later published macro observations and future statement calibration.
- **Limited provenance:** Manifest hashes were generated by the downloader (`minutes_crawler.py:91-92`), rather than supplied as official RBI checksums. Matching them establishes local consistency and accidental-corruption detection, not independent server authentication or a pre-evaluation freeze.
- **Unverified:** We did not obtain every original domestic release, reconstruct all inflation/IIP/GVA/monsoon/liquidity vintages, run any paid/live model evaluation or quantify how repaired inputs change decisions. No code path for an empirical HP filter was available to stress. The report distinguishes those missing validations from demonstrated failures.

## Minimum conditions for a defensible next evaluation

1. Specify whether the task is retrospective reconstruction or prediction with information available before the vote.
2. Freeze a source-backed vintage panel and a separately adjudicated ballot table; retain the current artifacts as historical evidence.
3. Freeze personas and model/prompt/config hashes using only permitted training information. Enforce the cutoff programmatically, including quotes and synthetic inputs.
4. Evaluate on a genuinely untouched panel and report separate rate, stance, guidance and reservation outcomes against appropriate simple baselines.
5. Run sensitivity comparisons for repaired vintages, calibration-only personas and synthetic forecasts, preserving every run and all null/negative outcomes. Correct the methodology claims before claiming that a successful sensitivity run restores an untouched holdout.
