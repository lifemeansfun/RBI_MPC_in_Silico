# Independent architecture, causal-validity and reproducibility audit

Date: 5 October 2026. Scope: behavioral deliberation, persona interfaces, experiment execution, institutional aggregation, fallback handling, caching and claimed reproduction. This review complements the separate data, statistical and primary-literature audits. No production code, old result, old transcript or existing cache was edited. No live provider request was made.

## Judgment

The project has useful modular components and an executable institutional simulation. Its current evidence does **not** validate a four-stage mechanism in which Round 3 compromise causes final voting, genuine independent LLM replicates, complete provider provenance, or causal explanations of real RBI committee behavior. Those are stronger claims than the implementation and experimental controls support. Several failures are demonstrated by offline adversarial executions, rather than inferred from wording alone.

This is not evidence that all existing transcripts were fabricated, or that every model output is wrong. Existing holdout artifacts declare zero heuristic fallbacks, and a read-only cache inventory contains 192 Gemini-labeled responses at temperature 0.1, consistent in count with eight meetings and 24 calls per meeting. However, counts and declared flags do not independently authenticate the provider or establish the missing mechanisms. Missing provenance must be reported as missing provenance.

The existing verification batteries test some useful algebra and implementation invariants. Passing them cannot rescue incorrect information flow or establish economic identification. In particular, mathematical diversity of prompt parameters is not a measurement of agent cognition; file existence is not authenticated live-provider provenance; and a date instruction is not an empirical test of pretrained historical-memory contamination.

## Reproducible evidence

The audit uses the project's existing Python 3.11.16 environment. The following command completed with exit status 0 and wrote only new audit evidence plus temporary test directories:

```sh
.venv/bin/python results/methodology_audit_2026-10-05/arch_probes.py > results/methodology_audit_2026-10-05/arch_probe_stdout.txt 2> results/methodology_audit_2026-10-05/arch_probe_stderr.txt
```

Files: `arch_probes.py`, `arch_probe_results.json`, `arch_probe_stdout.txt`, `arch_probe_stderr.txt`. The JSON contains environment information, hashes of reviewed source files, each counterexample and a read-only inventory of existing outcomes and cache groups. The probe script deliberately injects bad outputs or outages, replaces logging with in-memory loggers or temporary directories, and mocks the provider transport. Its exit status means the probe completed; it does **not** mean the production methodology passed.

## Findings, ranked by consequence

### A1 — Critical: Round 3 cannot influence final voting through its output

**Verified implementation:** `src/behavioral/debate_orchestrator.py:149–166` computes and logs all six Round 3 outputs. Lines 168–169 then build the final deliberation digest from only Round 1 and Round 2. Lines 183–185 and 203–205 supply that digest to final voters. Each round invokes the stateless client with a fresh prompt; no retained conversation history restores the omitted output (`src/infra/llm_client.py:202–230`).

**Executed counterexample:** The audit injected a -50 bps Round 3 preference in one execution and +50 bps in the other, with distinct Round 3 markers. All six final prompts were byte-identical; none included a Round 3 marker. Both outcomes were 0 bps. This demonstrates the absence of the intended output-to-final-vote channel, regardless of any particular provider's behavior.

**Consequence:** The Round 3 “Compromise Dip” is a descriptive pattern in separately generated responses. It cannot substantiate a claim that those compromises determine Round 4. `results/RESULTS_REPORT.md:179–180` and `src/reporting/plot_figures.py:422–426` interpret that pattern as deliberative compromise. Round 1 and Round 2 can still affect final prompts, so this finding does not establish that the entire simulation is nondeliberative.

**Rescue:** Carry validated Round 3 outputs into the final context, preserve each agent's own preceding state, and run randomized no-debate, R1-only, R1+R2 and full-context conditions with paired draws. Measure vote-transition probabilities and peer-specific changes, not merely committee outcome or cross-sectional dispersion.

### A2 — Critical: “Replicates” replay a cached realization

**Verified implementation:** `run_meeting` accepts `replicate_id`, but round calls never supply a seed (`debate_orchestrator.py:340–345,396–401,455–460,514–519`). `LLMClient.generate` defaults every request to `cfg.run.seed_base` (`llm_client.py:66–75`). Replicate ID is absent from prompts and cache identity. `config/config.yaml:13–15` specifies three replicates, seed 42 and caching, but the backtest and scenario runners use replicate 1.

**Executed counterexample:** With the real client in offline mock mode and a temporary SQLite cache, replicate 1 invoked the generator 24 times. Replicate 2 invoked it **zero** additional times; outputs were identical apart from replicate ID. The cache contained only seed 42.

**Consequence:** Replicate labels cannot provide independent stochastic uncertainty. Caching is useful for deterministic replay, but replay must not be counted as a new experiment. Existing cache groups also all use seed 42; this is an inventory observation, not proof of a provider's seed determinism.

**Rescue:** Define a frozen seed schedule keyed by experiment, meeting, replicate, member and round; distinguish cache replay from newly generated draws; retain paired baseline/intervention seeds and report run-level uncertainty with meetings as clustered units. Explain that providers may not guarantee bit-for-bit determinism even with seeds.

### A3 — Critical: Experiment artifacts overwrite each other; checkpoints ignore the experiment definition

**Verified implementation:** `TranscriptLogger` names files only by run, meeting, replicate, round and member, and writes with mode `w` (`src/infra/transcript_logger.py:37–64`). The scenario runner reuses a single orchestrator/logger and uses the same meeting date and replicate ID for baseline, shock and ablations (`src/scenarios/run_counterfactual_experiments.py:94–95,114–115,148–149,248–273`; attribution calls hardcode replicate 1 at `src/attribution/attribution_runner.py:142–149,188–194`). Backtest checkpoints are identified only by meeting date (`src/backtest/backtest_runner.py:163–173`); live holdout checkpoints similarly omit configuration, prompt, persona, data and code hashes (`src/backtest/run_holdout_live.py:90–111`).

**Executed counterexample:** Running a baseline and modified CPI shock through the actual logger in a temporary project root left 25 files after the baseline and still 25 after the shock. Paths were identical and the outcome file was overwritten.

**Consequence:** A table can represent an earlier condition while the only remaining transcript represents a later one. A changed model or dataset can also silently reuse a stale date checkpoint. These flaws prevent reliable condition-to-evidence reconstruction.

**Rescue:** Include experiment ID, condition ID and replicate in immutable artifact paths. Write a content-addressed run manifest containing code/config/persona/data/prompt hashes and requested/served model metadata; reject checkpoint reuse unless its manifest identity matches. Persist baseline and each intervention separately.

### A4 — Critical: The integrity and reproduction guards have demonstrated false positives

**Verified implementation:** The live transcript guard checks filenames across any run directory and never parses, hashes or authenticates their contents (`scripts/academic_integrity_guard.py:79–95`). The F1 concordance check allows the literal `0.83` anywhere in the report regardless of the CSV F1 (`:118–125`). Missing comparison files and other missing tables can pass optional checks. `scripts/reproduce.py:91–97` runs tests, batteries, figure generation and the guard, but does not run data construction, persona calibration, live holdout or counterfactual/attribution experiments. Missing tables/figures only print a warning (`:104–107`); a missing report is optional (`:109–112`), followed by “ALL PHASES VERIFIED GREEN” (`:114–116`).

**Executed counterexamples:**

- 225 files containing invalid JSON were accepted as nine verified live transcript chains, with no violation.
- A CSV F1 of 0.10 and a report F1 of 0.83 passed concordance, with no violation.
- With subprocess step returns mocked successful and all expected artifacts/report absent, `reproduce.main()` returned without `SystemExit` and printed all phases verified green. This isolates the harness's own control-flow flaw; it is not a real scientific reproduction.

**Consequence:** Existing green guard results cannot certify the four advertised invariants. The advertised single-command harness (`RESULTS_REPORT.md:247–258`) verifies parts of an existing artifact collection; it does not reproduce all scientific results from a clean, identified state.

**Rescue:** Parse and validate every required artifact, recompute aggregates from linked ballot records, compare all report values to named table cells, require nonoptional inputs and make missing or inconsistent artifacts exit nonzero. Split offline replay, fresh provider evaluation, and scientific reproduction into accurately named commands. Fresh reproduction must build data/personas/experiments in a new output directory and never depend silently on old artifacts.

### A5 — High: Requested model labels can conceal fallback models; live provenance is incomplete

**Verified implementation:** The retry function changes `current_model` on rate limits (`src/infra/llm_client.py:188–192`) but returns only response text and token counts. The outer `generate` records cost and caches under the originally requested `model` (`:94–107`). Parsed round transcripts omit prompts, raw responses, effective model, seed, temperature, provider request ID and cache-hit status. The outcome schema also has no such fields (`src/schemas/debate_schema.py:161–174`).

**Executed counterexample:** Two injected 429 errors followed by a successful response from `fallback-model` yielded attempted models `[requested-model,requested-model,fallback-model]`. Cost accounting and the cache row both labeled the successful result `requested-model`.

**Existing-artifact observation:** All eight `holdout_live_run` outcome files lack provider, model, seed, temperature, prompt hash and condition ID. Their flags declare zero fallbacks. SQLite contains useful raw request/response material, but no verified linkage from each published ballot to a cache entry or provider receipt, and model rotation can mislabel entries.

**Consequence:** The effective treatment can be a mixture of model versions, while comparisons claim a single model. The audit cannot authenticate “100% live” solely from these summaries.

**Rescue:** Return and persist requested model and served model separately, provider response identifiers, full request metadata and raw response, parser repairs, retries and cache status. Exclude model-switched trials from strict single-model analysis or report a prespecified mixed-model analysis. Hashes prove a saved file stayed unchanged relative to a manifest; they do not authenticate its remote origin by themselves.

### A6 — High: Outage behavior can be reported as successful model robustness

**Verified implementation:** Round handlers broadly catch exceptions and substitute a deterministic heuristic (`debate_orchestrator.py:350–361,406–417,465–476,524–538`). The cross-model stress script compares only final rate equality and ignores fallback flags (`scripts/stress_test_multi_model.py:28–45`). The recession stress script labels a 0 bps result as confirmed temporal leakage without ruling out fallback or alternative economic behavior (`scripts/stress_test_ablation.py:50–55`).

**Executed counterexamples:** A provider-outage injection produced a complete meeting with 24 heuristic fallbacks and a 50 bps decision. Running the repository's actual cross-model stress function with both requested models unavailable produced two identical 50 bps heuristic outputs and a **PASSED** robustness verdict despite zero provider calls. For the Governor persona, the recession CPI=1/output-gap=-5 heuristic yields 0 bps, which the recession test would label confirmed historical leakage.

**Additional resource-control observation:** With a tiny mock cost cap, all 24 generation calls were attempted and all became fallbacks after budget exceptions. The meeting returned normally. The cost governor raises after recording usage, and the orchestrator swallows that exception like an API outage; it is not an effective hard stop in this path.

**Consequence:** Operational resilience is being conflated with successful evaluation of LLM behavior. “Both models agree,” “leakage confirmed” and “fallback rejection proves no mode collapse” are not valid conclusions under these controls.

**Rescue:** Treat unavailable model trials as unavailable. Separate pure-provider, repaired-output, model-switched and heuristic results; never count fallbacks toward a live-model robustness gate. Propagate budget errors as terminal conditions. Define falsification criteria that distinguish contamination, economic inertia, prompt noncompliance and provider failure rather than assigning one explanation to every unexpected vote.

### A7 — High: Output validation silently changes the estimand and accepts wrong identities

**Verified implementation:** `src/schemas/debate_schema.py:11` accepts 35 and 40 bps, while the rule engine defaults to only `(-50,-25,0,25,50)` (`src/rule_engine/engine.py:33`). The orchestrator calls that default at `:226`. Rate validators map unparseable values to 0 and snap arbitrary numbers with no repair indicator. Stances are unconstrained `str`, despite the unused literal `StanceType`; member identities and round numbers are not bound to the caller.

**Executed counterexamples:** `"not a number"` became a 0 bps vote with `fallback_triggered=False`; 35 and 40 bps parsed successfully but were rejected by aggregation; an unknown stance parsed as a successful output. A final Varma response relabeled `intruder` was accepted, included in the six-member tally and returned in a successful meeting.

**Consequence:** Silent repairs can inflate pause frequency and hide generation failures. Legitimate historical action sizes can crash after generation, and corrupted identities can alter member-level dissent scoring.

**Rescue:** Share one action-space contract across prompts, schemas and aggregation; choose whether the historical benchmark needs 35/40 bps. Bind IDs, roster membership and round to the request, validate stances, record every normalization/snap and report sensitivity to strict rejection versus audited repair. No silently repaired response should be labeled unmodified LLM output.

### A8 — High: Institutional “strict statutory fidelity” is overstated

**Primary-source fact:** The official [Reserve Bank of India Act](https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/The-Reserve-Bank-of-India-Act--1934.pdf), PDF page 88, places quorum, individual voting and majority/casting vote in §45ZI(5),(7),(8). PDF page 89, §45ZL concerns publication of minutes after fourteen days. The repository repeatedly cites §45ZL as the voting rule. The official text permits quorum four with the specified chair; exact-six rejection models full attendance rather than statutory quorum. The voting provisions alone do not prescribe fixed Governor-last ballot visibility, an automatic weighted-median fragmented-split solution, or a neutral stance on unresolved motions.

**Verified implementation:** On fragmented rate profiles the engine always adds an extra Governor vote before taking a median (`src/rule_engine/engine.py:77–85`), even without a binary tie. For fragmented stance profiles it can accept three votes as plurality (`:147–162`). These may be reasonable *simulation conventions* but are not established statutory consequences. The actual repository's synthetic casting experiment creates a meeting decision with `member_votes=[]` (`run_counterfactual_experiments.py:288–302`). The ablation hardcodes an unresolved stance to `neutral` (`attribution_runner.py:55–59`), although prevailing historical stance may be withdrawal.

**Consequence:** The experiment demonstrates the behavior of a chosen resolution rule, not empirical casting-vote leverage. A hardcoded neutral switch can manufacture a stance-shift finding. Tests showing that a custom rule is internally consistent do not establish that it is legally mandated.

**Rescue:** Cite §45ZI correctly, explicitly scope full-attendance simulation, distinguish statutory binary-resolution voting from continuous preference aggregation, and source procedural assumptions independently. Retain abstention/quorum/resolution state if claiming general legal fidelity. Represent unresolved decisions as unresolved or carry a supplied actual prevailing stance; label constructed tie scenarios as synthetic.

### A9 — High: Current removal experiments do not identify peer persuasion or real-world macro causes

**Verified implementation:** The leave-one-out filter removes a member from Round 1/2 context for every agent, including the member itself (`debate_orchestrator.py:97–102,136–142`). The member remains in the voting committee. Its final ballot and rationale are again exposed to the Governor (`:197–203`). `AttributionResult` reports committee outcome changes rather than peer-level transitions (`attribution_runner.py:152–168`). Tests are run on one selected anchor and one realization, without independent replicates or a frozen no-communication baseline.

**Executed counterexample:** The ablated member's initial/rebuttal markers were absent from the Governor's final prompt, but its final-rationale marker remained present and the member still cast a ballot.

**Consequence:** This is a limited message-withholding intervention, not removal of a member or complete exclusion of its influence. Changes may include effects on the sender's own subsequent state and the Governor's visible votes. Zero committee shifts do not establish lack of persuasion because individual changes can cancel or remain below the majority threshold. Single-run simulation contrasts are model-internal sensitivity observations; they do not identify real RBI causal mechanisms.

**Rescue:** Prespecify the estimand: sender-message influence on *other members*, agenda visibility, member removal, or voting-rule effect. Freeze the sender's own policy state and ballot when measuring persuasion; control message length/order; log every peer ballot before/after; use paired repeated trials across diverse, prespecified anchors. Report causal interpretation within the explicit simulation separately from transportability to actual committees.

### A10 — Moderate: Synthetic “latent forecasts” and compound shocks add unvalidated assumptions

**Verified implementation:** `_generate_staff_forecast` (`debate_orchestrator.py:261–277`) deterministically shrinks current CPI toward 4%, adds 0.1 times the gap to current GVA, thresholds liquidity and derives a rate premium. These values are presented as confidential SPF/staff data that must be incorporated. They do not contain independently observed private forecasts or recover omitted latent variables. Named forecasting data can change model behavior through authority cues, even when it adds no independent information.

**Executed counterexample:** The Fed counterfactual builder omits GVA (`src/scenarios/scenario_runner.py:229–250`); at the actual 2022-08-05 anchor it changes GVA from 11.2% to `None`, removing the GVA briefing line. Thus the condition differs by an additional missing information field beyond its documented economic shocks. Other OOD builders also manually replace multiple fields and preserve modern meeting dates/rosters.

**Consequence:** Scenario outputs are responses to researcher-specified joint bundles, not separately identified monsoon or Fed impulses. Labels such as a “2013 Taper Tantrum” do not make a modern-roster, modern-date synthetic bundle a historical validation. The behavioral-versus-Taylor wedge cannot uniquely be assigned to discretion or supply-shock understanding when information and model specification differ.

**Rescue:** Build shocks by copying a validated snapshot and changing an explicit, hashed intervention list; assert all other fields are equal. Label generated expectations as synthetic assumptions, test no-forecast and alternative-forecast conditions, and use actual pre-meeting SPF/staff forecasts where available. Add one-factor and coherent multivariate scenarios, dose-response curves and saturation checks.

### A11 — Moderate: Persona and anti-contamination demonstrations are interface checks, not validated behavioral safeguards

**Verified implementation:** Normal round calls always use `build_system_prompt()` with the default quantitative persona (`debate_orchestrator.py:342,398,457,516`). The zero-shot test (`scripts/verify_zero_shot.py:21–31`) only asserts that a prompt string changes; it runs no model comparison. `system_prompt_override` is accepted in the schema but not used by `build_system_prompt` (`src/schemas/persona_schema.py:37–81`). Persona calibration loads all statements without a cutoff (`src/persona_engine/extractor.py:115–128`) and mixes 60% hand-set prior with 40% lexical ratio (`:168–173`); this is a fixed weighted blend, not a documented estimated Bayesian posterior. Dissent mandates differ by external/internal role and hawk-dove score (`debate_orchestrator.py:289–298`), so prompt objectivity requires testing rather than assertion.

Temporal output scanning logs warnings only, searches years 2020–2039, and does not detect a same-year event after the meeting (`:300–309`). It cannot erase a model's pretrained knowledge or reject contaminated outputs. Entity-masking tests demonstrate substitution on example strings and macro text, but normal persona prompts retain real names, roles and tenure.

**Consequence:** Claimed zero-shot, temporal-firewall and unbiased-prompt mitigation remains unverified at the behavior level. This finding is compatible with the safeguards helping; their causal benefit has simply not been measured.

**Rescue:** Freeze persona construction to a calibration cutoff, preregister priors and weighting, test biography-only, numeric-only, anonymous role and identity/date-masked variants, and independently score blinded rationales. Use post-cutoff unseen meetings and fictitious calendars/countries as contamination controls. Retain negative results and distinguish prompt-string correctness from demonstrated leakage resistance.

## Strengths to preserve

- Components have clear interfaces: macro snapshot, persona, round outputs, aggregation and logging are separate, making targeted falsification practical.
- Round 1 prompts do not explicitly include peer arguments, and macro prompt formatting excludes optional ground-truth decision fields. These are useful isolation choices; statistical independence does not follow automatically from using one common model and input.
- The cache includes provider and requested model in its identity, which helps separate normal mock and live cache namespaces. Its recorded raw prompts/responses are valuable starting evidence even though effective-model and result linkage are incomplete.
- The heuristic fallback flag and aggregate fallback counter exist. Preserve them while excluding fallback outcomes from pure-provider research claims.
- Binary majority and casting-vote behavior can be tested exhaustively. Root's separate exhaustive checks found the implemented rate/stance aggregation internally stable across its chosen five-action space and monotonic rate perturbations. These checks support the implementation of that chosen rule, without converting all custom extensions into law.
- Existing artifacts permit offline numerical recomputation and inspection. That is a substantial advantage over claims unsupported by any saved data.

## Minimum evidence needed before stronger conclusions

First repair information flow, action/identity validation, immutable condition logging, checkpoint identity and terminal budget errors. Freeze a manifest before obtaining new experimental responses. Then evaluate a prespecified factorial design across fresh seed schedules and temporally separated meetings: model version, persona mode, identity/date masking, communication depth and speaker order. Keep actual pre-meeting information identical across paired behavioral and rational comparisons.

Report pause/prevailing-stance and calibrated rational baselines, per-member and per-channel dissent, paired model differences, uncertainty by meeting, completion/repair/fallback rates and all planned negative results. Single-model claims require served-model metadata; deliberation claims require a successful information-flow check and an advantage relative to independent voting; real-world causal claims need external identification beyond model-internal interventions. Until then, the defensible description is **a retrospective multi-agent simulation prototype with reproducible portions of its offline analysis**, not a validated causal digital twin of the RBI MPC.
