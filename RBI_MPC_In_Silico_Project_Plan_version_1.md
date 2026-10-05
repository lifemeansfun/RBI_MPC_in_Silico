# RBI MPC In Silico — Engineering Project Plan
**For direct use by an AI coding agent (Claude Code / Cursor / equivalent). Version 1.0.**

---

## 0. How to use this document

This is not a summary of the research proposal — it is an **engineering specification derived from it**. Everywhere the proposal (a research document, correctly) left a methodological choice implicit, this plan makes it explicit, states the default I am proposing, and flags it as `[ASSUMPTION — CONFIRM]` so you can override it in one line before handing the plan to the coding agent. Everywhere a step genuinely requires your judgment, domain knowledge, or manual action, it is flagged `[HUMAN REQUIRED]` and the agent should **stop and wait**, not improvise.

**Answers you gave that shaped this plan:**
- Timeline: no scope compression — full rigor for journal submission. I have **not** cut panel size, replicate counts, or validation strictness to fit an artificial deadline. Section 9 gives a realistic week-by-week estimate for the full scope; compress by trimming the parameters marked "cost/time lever" if you later need to.
- LLM provider: not decided → I recommend one below, with reasoning and current pricing (Section 7).
- Data: not started → Phase 1 is scoped as a full data-engineering phase, not a "load the CSV" phase.
- Coding agent tool, exact budget cap, and paper/LaTeX deliverable were not specified — I've made explicit, low-risk defaults for each (Sections 6.9, 7, 8) and flagged them so you can change them in one line.

---

## 1. Vibe-coding suitability map

| Phase | Component | Suitability | Why |
|---|---|---|---|
| 0 | Repo scaffold, config, logging, cost governor, caching | **Fully vibe-codable** | Generic infrastructure, testable in isolation, no domain judgment |
| 1 | Data download scripts (once source confirmed) | Vibe-codable | Straightforward once the URL/API is known |
| 1 | Actually locating/exporting series from DBIE, IMD monsoon reports | **[HUMAN REQUIRED]** | These sites are session-based / PDF-only and resist reliable scripting; silent scraper breakage would poison every downstream result |
| 1 | Data cleaning, schema validation, versioning | Fully vibe-codable | Deterministic transforms with clear correctness tests |
| 2 | Persona extraction pipeline (LLM summarization of statements) | Hybrid | Extraction is vibe-codable; **the output must be human-reviewed** |
| 2 | Persona profile sign-off | **[HUMAN REQUIRED]** | This is the single artifact your paper's credibility rests on |
| 3 | Institution rule engine (majority + casting vote) | Fully vibe-codable | Pure deterministic logic, fully unit-testable |
| 4 | Multi-agent debate orchestration (once protocol is fixed) | Vibe-codable | Mechanical once the protocol below is locked |
| 4 | Debate protocol design (rounds, visibility, ordering) | **[HUMAN REQUIRED — pre-decided below]** | Must be fixed *before* coding starts or the agent will invent an inconsistent one |
| 5 | Monte Carlo mechanics (draws, aggregation) | Vibe-codable | Standard numerical simulation |
| 5 | Taylor-rule parameterization (α, β, r*) | **[HUMAN REQUIRED]** | A methodological choice a journal reviewer will scrutinize — needs your (or your advisor's) sign-off, not an LLM's default |
| 6 | Accuracy scoring code | Vibe-codable | Pure functions over labeled data |
| 6 | Recalibration decisions when holdout accuracy is low | **[HUMAN REQUIRED]** | Blind agent-driven prompt tuning against real results is how p-hacking accusations happen |
| 7 | Counterfactual scenario construction | Vibe-codable | Parametrized rerun once Phase 1 data and Phase 4/5 pipelines exist |
| 8 | Attribution experiments | Vibe-codable | Controlled perturbations of existing, tested pipeline |
| 9 | Results tables/figures | Vibe-codable | Deterministic aggregation and plotting |
| 9b | LaTeX/journal formatting | Vibe-codable, optional | Only build if you confirm you want it |
| 10 | Reproducibility pass, final review | Hybrid | Automatable checks + your final read-through before submission |

**Rule of thumb applied throughout:** if a bug in a component would silently corrupt a *number that ends up in the paper*, it is Hybrid or Human-required. If a bug would just crash loudly or fail a test, it is fully vibe-codable.

---

## 2. Global defensive coding standards (apply in every phase)

1. **Single source of truth for parameters.** Every tunable constant (thresholds, model names, replicate counts, action-set granularity, budget cap) lives in `config/config.yaml`, validated by a `pydantic` `Settings` model at startup. No magic numbers in code.
2. **Idempotent, cached LLM calls.** Every call is wrapped by a cache keyed on `hash(model, full_prompt, temperature, seed)`. Re-running a failed pipeline never re-pays for completed calls.
3. **Hard cost governor.** A single module tracks cumulative spend against `config.budget_usd_cap` after every call and raises immediately (not just logs) when the cap is hit.
4. **Checkpointing per unit of work.** The simulation loop checkpoints after every *meeting*, not every pipeline run, so a crash at meeting 9 of 12 resumes at meeting 9.
5. **Full transcript persistence.** Every LLM input/output is written to `runs/{run_id}/transcripts/{meeting_id}/{step}.json`, verbatim. This is both your reproducibility record and the raw material the attribution layer (Phase 8) operates on.
6. **Schema validation at every boundary.** Every data load, every LLM output parse, every inter-module handoff goes through a `pydantic` model. Malformed LLM output triggers a structured-output retry (max 2), then a hard failure logged for manual review — never a silent default.
7. **Holdout lock.** A module-level flag `HOLDOUT_LOCKED` becomes `True` the first time holdout-set data is read for scoring. Any later read of holdout data raises unless explicitly and manually unlocked (logged, with a reason string, by you).
8. **Exhaustive tests for deterministic modules.** The rule engine and Monte Carlo aggregator require unit tests covering every vote-distribution equivalence class, not happy-path only.
9. **Data provenance.** Every raw file in `data/raw/` has a manifest entry (`source_url`, `download_date`, `sha256`). Once Phase 1 exit criteria pass, `data/processed/` is hash-locked into `DATA_VERSION.txt`; any change requires a version bump, never a silent overwrite.
10. **Git discipline.** One feature branch per phase, commit only at that phase's exit criteria, tag `v0.{phase}-complete`. This gives both of you (and reviewers, eventually) a clean audit trail.
11. **No pipeline logic in notebooks.** Notebooks are for exploration/calibration only. Anything that produces a number in the paper lives in a tested `.py` module.

---

## 3. Recommended tech stack

| Layer | Choice | Reasoning |
|---|---|---|
| Language | Python 3.11+ | Standard for this kind of numerical + LLM pipeline |
| Env/lockfile | `uv` (or `poetry`) with a committed lockfile | Reproducibility for a paper's methods section requires a pinned environment |
| LLM SDK | `anthropic` Python SDK, official | See model recommendation below |
| Orchestration | **Plain `asyncio` + the SDK's async client — not LangChain/LangGraph** | A heavy agent framework adds an abstraction layer that hides bugs in exactly the kind of multi-step, cost-sensitive pipeline where you need full visibility. Custom orchestration is ~200 lines and every line is inspectable and testable. |
| Data | `pandas` + `pyarrow` (Parquet), `pydantic` v2 | Fast, typed, standard |
| Numerics | `numpy`, `scipy`, `statsmodels` (for the HP filter) | Standard |
| Config | `pydantic-settings` reading `config/config.yaml` | Single source of truth (Standard #1 above) |
| Logging | stdlib `logging` → JSON Lines files per run | Structured, greppable, no extra dependency |
| Testing | `pytest`, `pytest-cov` | Standard |
| CI | GitHub Actions, unit tests only (no live API calls in CI) | Keep CI free and fast |
| Notebooks | Jupyter, exploratory only | Standard #11 |

### LLM model recommendation `[ASSUMPTION — CONFIRM]`

- **Development / calibration-loop iteration:** Claude Haiku 4.5 (~$1 / $5 per million input/output tokens). Cheap and fast enough for the many throwaway runs during persona tuning.
- **Final, reported, validated runs:** Claude Sonnet 5 (~$2 / $10 per million input/output tokens). Strong instruction-following for persona-grounded roleplay at a fraction of Opus-tier cost.
- Enable **prompt caching** on the shared macro-data snapshot and each persona's system prompt — these are re-read across every debate round and every meeting, so caching materially cuts cost (independent of which tier you pick).
- *(Verify current pricing at platform.claude.com/docs/en/about-claude/pricing before locking your budget — it was current as of early Sept 2026 when I checked.)*
- I am **not** recommending Opus or Fable: this task needs consistent persona-following and reasonable reasoning depth, not frontier-level general intelligence, and the cost multiple (5–10×) isn't justified by the task.

---

## 4. Repository structure

```
rbi-mpc-in-silico/
├── config/
│   └── config.yaml                  # single source of truth, see Section 5
├── data/
│   ├── raw/                         # untouched downloads + manifest.csv (source_url, date, sha256)
│   ├── processed/                   # cleaned, canonical tables
│   │   ├── macro_panel.parquet
│   │   └── mpc_statements/{meeting_date}/{member}.txt
│   └── DATA_VERSION.txt             # hash-lock, see Standard #9
├── personas/
│   ├── pre_oct2024/{member}.yaml
│   ├── post_oct2024/{member}.yaml
│   └── PERSONA_REVIEW.md            # human sign-off log, see Phase 2
├── src/
│   ├── infra/                       # Phase 0: cache, cost governor, retry wrapper, config loader
│   ├── data_pipeline/                # Phase 1
│   ├── persona_pipeline/             # Phase 2
│   ├── rule_engine/                  # Phase 3
│   ├── behavioral_track/             # Phase 4
│   ├── rational_track/               # Phase 5
│   ├── validation/                   # Phase 6
│   ├── scenarios/                    # Phase 7
│   ├── attribution/                  # Phase 8
│   └── reporting/                    # Phase 9
├── runs/{run_id}/
│   ├── transcripts/{meeting_id}/{step}.json
│   ├── logs/run.jsonl
│   └── CALIBRATION_LOG.md            # every recalibration diff + reason, see Phase 6
├── tests/                            # mirrors src/ structure
├── results/
│   ├── tables/  figures/  RESULTS_REPORT.md
├── .env.example
├── DATA_VERSION.txt
├── pyproject.toml / uv.lock
└── README.md
```

---

## 5. Master config schema (`config/config.yaml`)

Every parameter an AI agent might otherwise invent on its own lives here. This is the file you edit to override any `[ASSUMPTION]` in this plan.

```yaml
run:
  budget_usd_cap: 100.0          # hard stop — see Section 7 for why this is generous
  dev_model: "claude-haiku-4-5-20251001"
  final_model: "claude-sonnet-5"
  temperature: 0.7
  n_replicates: 3                # cost/time lever — see Section 7
  seed_base: 42

action_set_bps: [-50, -25, 0, 25, 50]   # discrete vote space — [ASSUMPTION, confirm against real MPC decision granularity]

data:
  roster_change_date: "2024-10-01"
  primary_panel_start: "2024-10-01"     # current-roster panel, see Phase 1/6
  primary_panel_end: "latest"
  stress_panel_start: "2016-10-01"      # pre-2024 generalizability panel
  stress_panel_end: "2024-09-30"
  calibration_holdout_split: 0.67        # ~8 calibration / 4 holdout on a 12-meeting primary panel

taylor_rule:                              # [HUMAN REQUIRED — see Phase 5]
  r_star_pct: 1.4
  pi_star_pct: 4.0
  hp_filter_lambda: 129600                 # monthly-data Ravn-Uhlig convention
  default_alpha: 1.5
  default_beta: 0.5

monte_carlo:
  n_draws: 1000
  noise_std_pct: 0.25                      # [ASSUMPTION — confirm against data volatility]

validation:
  directional_accuracy_threshold: 0.75     # [ASSUMPTION — confirm, see Phase 6, small-n caveat]
  dissent_f1_threshold: 0.5

debate_protocol:
  rounds: 2                                 # after the independent initial stance
  reveal_named_positions: true              # real minutes are signed, so no anonymization
  agent_order_seed: 7
```

---

## 6. Phases

Each phase lists: objective, concrete tasks, deliverables, defensive requirements, exit criteria, and who does what.

### Phase 0 — Foundations & Defensive Infrastructure
**Objective:** everything in Section 2 exists and is tested before any domain code is written.
**Tasks:** repo scaffold per Section 4; `pydantic-settings` config loader; LLM call wrapper with cache + retry (exponential backoff, jitter, max 5 retries) + cost governor; JSON-lines run logger; GitHub Actions CI running `pytest` on push.
**[HUMAN REQUIRED]:** set your actual API key in `.env` (never commit it); confirm `budget_usd_cap`.
**Exit criteria:** `pytest` green; a dummy LLM call round-trips through cache+governor+logger with a unit test proving a repeated call doesn't re-hit the API.

### Phase 1 — Data Acquisition (build from scratch)
**Objective:** a frozen, versioned dataset covering CPI-Combined, core CPI, IIP, GVA growth, repo rate history, system liquidity, USD/INR, Brent crude, US Fed funds rate, monsoon rainfall departure from LPA, and all six-member individually-signed MPC minutes statements per meeting.

**Sources:**
| Series | Source | Notes |
|---|---|---|
| CPI, IIP, GVA, repo rate, system liquidity | RBI DBIE (dbie.rbi.org.in) | **[HUMAN REQUIRED]** — session-based query UI, resists reliable scripting |
| CPI/IIP cross-check | MOSPI (mospi.gov.in) | For validating DBIE pulls |
| MPC minutes (signed statements) | rbi.org.in → Monetary Policy → MPC → Minutes | PDF links are listable — script the crawl, but **spot-check ~10% manually** for OCR/scan quality on older PDFs |
| USD/INR, Brent, Fed funds | FRED (DEXINUS, DCOILBRENTEU, FEDFUNDS) | Has a stable API — fully scriptable |
| Monsoon rainfall departure from LPA | IMD seasonal reports | **[HUMAN REQUIRED]** — typically PDF-only, not a clean API |

**Tasks:**
1. `[HUMAN REQUIRED]` Manually export each DBIE/IMD series into `data/raw/`, following a strict naming convention; script logs each into `manifest.csv` (source_url, download_date, sha256).
2. Vibe-code a crawler for the MPC minutes PDF archive → `data/raw/mpc_minutes/`.
3. Vibe-code FRED pulls via their public API.
4. Vibe-code cleaning/harmonization: canonical long-format table (`date, series_id, value, source, vintage`), reconciling any CPI base-year rebasing across 2016–2026 → `data/processed/macro_panel.parquet`.
5. Vibe-code (LLM-assisted) statement-splitting: isolate each of the 6 signed statements per minutes PDF → `data/processed/mpc_statements/{date}/{member}.txt`. `[HUMAN REQUIRED]` spot-check extraction quality, especially pre-2020 PDFs.
6. Vibe-code the validation suite: schema checks, monotonic dates, sane value ranges, no missing mandatory series for any meeting date in the target panels.
7. Hash-lock `data/processed/` → `DATA_VERSION.txt` (Standard #9).

**Exit criteria:** validation suite green; you have signed off (a one-line note is enough) that statement extraction looks correct for at least the primary calibration set.

### Phase 2 — Persona Construction
**Objective:** one structured, versioned persona profile per member (not per meeting), used as that agent's system prompt across all simulated meetings.

**Schema** (`personas/{roster}/{member}.yaml`):
```yaml
member_name: ""
role: ""                    # Governor | Internal | External
tenure_start: ""
tenure_end: ""
roster_set: ""               # pre_oct2024 | post_oct2024
hawk_dove_score: 0.0          # [-1, 1], computed from historical dissent direction, not vibes
reasoning_themes: []          # e.g. growth-weighted, inflation-hawk, external-sector-focused
representative_excerpts: []   # 3-5 short excerpts from real statements, used only in the prompt
system_prompt_template: ""    # Jinja2, combines the above + a macro-snapshot placeholder
```
**Tasks:**
1. Vibe-code an LLM-assisted summarizer that reads all of a member's Phase-1-extracted statements and drafts the fields above.
2. `[HUMAN REQUIRED]` — review and edit every persona profile (6 current-roster + up to 6 pre-2024-roster). This is the single artifact your paper's central validity claim rests on; do not skip or rubber-stamp this.
3. Log every review/edit in `personas/PERSONA_REVIEW.md`.

**Exit criteria:** all personas reviewed and signed off in `PERSONA_REVIEW.md`; schema-validation unit tests pass.

### Phase 3 — Institution Rule Engine
**Objective:** deterministic, fully-tested implementation of RBI MPC's voting rule.
**Logic:**
- 6 votes drawn from `config.action_set_bps`.
- Clear majority (≥4 of 6 on one action) → that action wins.
- Exact 3–3 split over exactly two actions → Governor's vote counts twice (RBI Act §45ZL casting vote).
- **`[ASSUMPTION — CONFIRM]`** No-majority, non-binary split (e.g. 2-2-1-1): proposed fallback is "the action closest to the vote-weighted median, with the Governor's vote double-weighted in the median calculation." Confirm this or supply your own rule — this edge case isn't addressed in the proposal and needs an explicit decision.
**Tasks:** `rule_engine.py` as pure functions; exhaustive unit tests enumerating every vote-distribution equivalence class (clean majority, binary 3-3 tie, every non-binary fragmented case).
**Exit criteria:** 100% branch coverage on `rule_engine.py`.

### Phase 4 — Behavioral Track (LLM multi-agent simulation)
**Objective:** implement the exact debate protocol below — do not let the coding agent improvise this.

**Protocol `[ASSUMPTION — CONFIRM before Phase 4 starts]`:**
1. **Round 1 (initial stance):** 6 parallel calls. Each agent sees only the shared macro snapshot for that meeting — no cross-visibility. Outputs: discrete vote + reasoning.
2. **Round 2 (debate 1):** 6 parallel calls. Each agent now sees all 6 round-1 positions, named (real statements are signed, so no anonymization; order fixed by `debate_protocol.agent_order_seed`, not always Governor-first). Outputs: updated vote + reasoning.
3. **Round 3 (debate 2):** same as round 2, with round-2 positions.
4. **Round 4 (final vote):** 6 parallel calls, given the full transcript. Output: final discrete vote (must validate against `action_set_bps`) + short rationale.
- Total: 24 LLM calls per meeting per replicate.
- Run `config.n_replicates` independent seeded replicates per meeting (default 3) to get a distribution, not a single point estimate — a single LLM run gives no sense of variance, which a journal reviewer will ask about.

**Defensive requirements:** checkpoint after every meeting; persist full transcripts (Standard #5); structured-output validation with max-2 retries on malformed votes, then hard-fail to manual review queue (never silently default a vote).
**Exit criteria:** full primary-panel behavioral-track run completes with all transcripts present and schema-valid; cost-governor never triggered unexpectedly.

### Phase 5 — Rational Track (Monte Carlo, Taylor-rule baseline)
**Objective:** implement the mathematical-rational track for direct comparison to the behavioral track.

**Formula `[HUMAN REQUIRED — confirm with your advisor before locking]`:**
```
r_i,t = r* + π_t + α_i·(π_t − π*) + β_i·(y_t − y*)
```
where `π_t` = CPI-Combined YoY, `π*` = 4% (RBI's target), `y_t − y*` = output-gap proxy from HP-filtered IIP/GVA (λ per `config.taylor_rule.hp_filter_lambda`), `r*` = neutral real rate (default 1.4%, config-editable).

**Member-specific calibration:** for members with recorded historical dissents, fit `α_i, β_i` by minimizing squared error between the formula's implied action and their real recorded votes across their tenure. For members with no dissent history, use `default_alpha`/`default_beta` (standard textbook Taylor-rule values) — document this explicitly as a limitation, since it means their "rational" persona is partly population-average by construction.

**Monte Carlo:** 1,000 noisy draws per meeting (noise on the data inputs, per `monte_carlo.noise_std_pct`), aggregated via weighted-median voting, then passed through the same Phase 3 rule engine.

**Tasks:** `rational_track.py`; a calibration script/notebook producing a documented parameter-fit table; unit tests validating the formula against 2-3 hand-computed examples.
**Exit criteria:** calibration table reviewed and signed off by you; unit tests pass.

### Phase 6 — Validation Gate
**Objective:** backtest against the held-out panel before any counterfactual/attribution work runs.

**Metrics:**
- **Directional accuracy** = % of holdout meetings where the simulated committee decision (post rule-engine) exactly matches the real historical decision.
- **Dissent-detection** = report both an exact-match rate (simulated dissenting-member set == real set) *and* an F1 score over predicted-vs-real dissenting members, since exact-set-match on a ~4-meeting holdout will be extremely noisy — report both, don't cherry-pick.

**Threshold `[ASSUMPTION — CONFIRM, and read the caveat]:`** directional accuracy ≥ 75%, dissent F1 ≥ 0.5. **Caveat to flag prominently in the paper:** the primary (post-Oct-2024) holdout panel will likely be only 3–4 meetings given the roster is barely two years old — a threshold picked against that small an n needs to be stated as a design choice, not implied as statistically robust. The pre-2024 stress panel (Phase 1 secondary panel) is larger and should be reported as a generalizability check, not used to set the pass/fail threshold.

**Recalibration:** on failure, `[HUMAN REQUIRED]` — you (not the agent unsupervised) revise calibration-set persona prompts only. Every change logged with a diff and stated reason in `CALIBRATION_LOG.md`. `HOLDOUT_LOCKED` flag (Standard #7) prevents any code path from reading holdout data before this loop concludes.
**Exit criteria:** holdout metrics computed exactly once per calibration cycle, logged, and either pass the threshold or the recalibration loop is documented as ongoing.

### Phase 7 — Counterfactual Scenarios
**Objective:** two scenarios, each anchored to a real historical episode from your own Phase 1 data (not an assumed round number).
1. **Monsoon/food-inflation shock:** compute the actual 2023 vegetable-price CPI spike magnitude from `macro_panel.parquet`; apply an equivalent shock to a chosen baseline meeting's macro snapshot; rerun both tracks.
2. **US Fed spillover shock:** compute the actual USD/INR and capital-flow response to a specific historical Fed hike (e.g. a 2022 75bps move) from your own data; apply equivalently; rerun both tracks.
**Exit criteria:** both scenarios rerun on N replicates each, results compared to the validated baseline, effect sizes reported with the LLM-vs-Monte-Carlo wedge.

### Phase 8 — Attribution Layer (exactly 3 experiments, per proposal)
1. **Leave-one-member-out:** in rounds 2–3, withhold one member's stated position from the other 5 agents' context; rerun rounds 2–4; compare final outcome to baseline.
2. **Casting-vote ablation:** rerun the Phase 3 rule engine only (no new LLM calls needed) on existing 3–3-tie transcripts with the casting-vote rule disabled/modified.
3. **Macro-input muting:** hold one macro input constant (e.g. zero the monsoon-rainfall deviation) in the shared snapshot; rerun the full behavioral track for affected meetings.
**Exit criteria:** all three experiments' deltas-vs-baseline documented in a single attribution results table.

### Phase 9 — Results Synthesis
**Objective:** aggregate every phase's outputs into a single reproducible report.
**Deliverables:** `results/tables/*.csv`, `results/figures/*.pdf` (vector, journal-quality), `results/RESULTS_REPORT.md` auto-compiled from all phase outputs (directional/dissent accuracy, LLM-vs-Monte-Carlo wedge, two scenario effects, three attribution values).
**Phase 9b (optional, build only if you confirm you want it):** LaTeX export scaffold for direct journal submission formatting.

### Phase 10 — Reproducibility & Submission Readiness
**Tasks:** `make reproduce-all` script that reruns the full pipeline from `data/raw/` to `results/` on a clean checkout; README with setup instructions; a data/code availability statement (most journals now require one); final environment lockfile check.
**[HUMAN REQUIRED]:** your own final read-through — an AI agent should not be the last reviewer before journal submission.

---

## 7. Cost estimate (answers your "not sure" on budget)

Rough order-of-magnitude, using the primary panel default (12 meetings, 3 replicates, 24 calls/meeting) plus stress panel, scenarios, and attribution:

| Item | Approx. LLM calls | Approx. tokens (in/out, pre-caching) |
|---|---|---|
| Primary panel behavioral runs | ~860 | ~1.7M / 0.35M |
| Stress panel (pre-2024, 1 replicate) | ~240 | ~0.5M / 0.1M |
| Recalibration reruns (assume 2 extra passes, calibration set only) | ~1,150 | ~2.3M / 0.45M |
| Counterfactual scenarios (2 scenarios, 3 meetings, 3 replicates) | ~430 | ~0.9M / 0.18M |
| Attribution (member/macro experiments, ~5 meetings each) | ~240 | ~0.5M / 0.1M |
| **Total (illustrative)** | **~2,900** | **~6M in / 1.2M out** |

At Claude Sonnet 5 pricing (~$2/$10 per million): roughly **$12 input + $12 output ≈ $25–40 total**, likely less with prompt caching. Even doubling this for safety margin, this project's LLM spend is **on the order of $50–150 total** — budget is very unlikely to be your binding constraint. I've still built the hard cost governor (Standard #3) as defensive infrastructure regardless, with a generous default cap of $100 that will alert you well before anything resembling a runaway cost.

---

## 8. Risk register

| Risk | Mitigation |
|---|---|
| DBIE/IMD site structure changes, scraper breaks silently | Manual collection for these two sources by design (Phase 1); manifest checksums make silent corruption detectable |
| LLM non-determinism threatens reproducibility | Seeded replicates, full transcript persistence, N=3 default for variance estimates |
| Primary holdout panel is small (~3-4 meetings) | Report both exact-match and F1 metrics; use pre-2024 panel as a separate, clearly-labeled generalizability check, not for threshold-setting |
| Cost overrun | Hard governor (Standard #3), staged Haiku→Sonnet model use |
| Persona fidelity / unintended bias in LLM-summarized personas | Mandatory human review gate, logged sign-off (Phase 2) |
| Calibration/holdout leakage | Code-enforced `HOLDOUT_LOCKED` flag, not just a naming convention |
| Taylor-rule parameterization challenged by reviewers | Explicit human sign-off required before Phase 5 is marked complete; documented calibration table |
| Vibe-coded orchestration silently diverging from the debate protocol | Protocol fixed and written down *before* Phase 4 coding starts (Section 6, Phase 4) |

---

## 9. Timeline estimate (full scope, no compression)

| Weeks | Phase |
|---|---|
| 1 | Phase 0 (can overlap with early Phase 1 manual collection) |
| 1–3 | Phase 1 (data acquisition is the long pole given "build from scratch") |
| 3–4 | Phase 2 (persona construction + your review) |
| 4 | Phase 3 |
| 5–6 | Phase 4 |
| 6 | Phase 5 |
| 7–8 | Phase 6, including at least one recalibration cycle |
| 9 | Phase 7 |
| 9–10 | Phase 8 |
| 10–11 | Phase 9 |
| 11–12 | Phase 10 + your final review before submission |

**Cost/time levers if you need to compress:** reduce `n_replicates` (3→1), reduce the pre-2024 stress panel size, or narrow the primary panel window — all are single-line config changes, not architecture changes, by design.

---

## 10. Handoff instructions for the coding agent

Give the agent this document plus, in order: `config/config.yaml` (Section 5) → Phase 0 → Phase 1 (stopping at every `[HUMAN REQUIRED]` step) → and so on sequentially. Instruct it explicitly: **do not proceed past a phase's exit criteria without them being met, and do not silently resolve anything marked `[ASSUMPTION]` or `[HUMAN REQUIRED]` on its own — surface it and wait.** Phase boundaries are designed as natural session/checkpoint breaks for tools like Claude Code that work best in bounded units of work.
