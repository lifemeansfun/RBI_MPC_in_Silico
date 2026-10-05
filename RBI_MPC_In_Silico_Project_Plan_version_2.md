# RBI MPC In Silico — Engineering Project Plan (Version 2.0)
**Validated Multi-Agent Simulation of India's Monetary Policy Committee with Bounded Counterfactual Attribution**
*Derived from the Research Proposal (adapted from Kazinnik & Sinclair, 2025) and upgraded for architectural decoupling, dual-vote institutional realism, and Google Gemini integration.*

---

## 0. Executive Summary & Key Upgrades from Version 1.0

Version 1.0 laid out an initial sequential engineering pipeline, but contained several critical vulnerabilities: a proprietary single-provider lock-in (Anthropic), a high-risk 12-week waterfall coupling where a data-scraping roadblock in Phase 1 would freeze all downstream work, an undersized post-October-2024 historical panel with low statistical power, an unrealistic Taylor rule lacking policy inertia, and a major omission of the **Policy Stance** vote (where >70% of real RBI dissents occur).

**Version 2.0 introduces six fundamental architectural upgrades:**

1. **Decoupled, Contract-First Phase Architecture:** Every phase is strictly isolated by typed Pydantic v2 schemas and self-contained mock fixtures. If Phase 1 data scraping encounters website changes or delays, Phase 2, 3, 4, and 5 can run and be verified against synthetic/mock baseline fixtures immediately. No phase blocks another.
2. **Two-Stage Milestone Roadmap:**
   - **Stage 1 (Fast MVP — Days 1 to 5):** Complete end-to-end working system on mock/synthetic data (Infra, Rule Engine, 6-Agent Deliberation, Taylor Rule, Synthetic Validation, and Mock Attribution). Guarantees an executable, demonstrable project for university reviews almost immediately.
   - **Stage 2 (Empirical Research Rigor — Weeks 2 to 4):** Full historical panel ingestion (2020–2024), real persona extraction and human sign-off, frozen holdout backtesting, empirical counterfactual shocks, and journal-ready report synthesis.
3. **Primary Benchmark Panel (October 2020 – August 2024):** 24 real bimonthly meetings (16 calibration, 8 holdout) under the Goyal-Bhide-Varma-Das-Patra roster. Covers the post-COVID recovery, the Russia-Ukraine food/fuel shock, 250 bps rate hikes, and the 6.50% pause. The post-October 2024 roster is preserved as an **Out-of-Sample Forward Test Panel**.
4. **Dual-Vote Institutional Realism (Rate + Stance):** Simulates both the **Policy Repo Rate** (`[-50, -25, 0, 25, 50]` bps) and the **Policy Stance** (`withdrawal_of_accommodation`, `neutral`, `accommodative`), capturing the true institutional locus of RBI dissent. Configurable via `simulate_stance: true`.
5. **Native Google Gemini Integration (with Multi-Provider Abstraction):** Powered by the official `google-genai` SDK (Gemini 2.5 Flash / Pro) with context caching and massive token economy (~$1–$5 total project spend). Clean provider adapter also supports OpenAI, Anthropic, or local Ollama (Llama-3.3 / Qwen-2.5) without code changes.
6. **Open-Economy Smoothed Taylor Rule:** Augments the baseline rational track with interest-rate smoothing ($\rho \approx 0.75$) and US Federal Funds rate differential spillover, eliminating erratic rate swings and aligning with actual central bank gradualism.

---

## 1. Vibe-Coding & Autonomy Boundary Map

| Phase | Component | Autonomy Level | Rationale |
|---|---|---|---|
| **0** | Infra: Config, Gemini client, cache, cost governor, mock fixtures | **Fully Autonomous** | Pure systems engineering, deterministic unit tests. |
| **1** | Minutes crawler & FRED automated pull | **Fully Autonomous** | Scriptable against public RBI press releases and FRED API. |
| **1** | DBIE / IMD manual export ingestion & schema validation | **Hybrid** | Python parser handles CSV/Excel ingestion; user drops files if anti-bot blocks DBIE. |
| **2** | Persona extraction pipeline (LLM statement summarizer) | **Fully Autonomous** | Deterministic prompt-driven extraction of quotes and themes. |
| **2** | Persona profile validation & sign-off | **[HUMAN REQUIRED]** | Core academic credibility check; user reviews `PERSONA_REVIEW.md`. |
| **3** | Institutional Rule Engine (RBI Act §45ZL casting vote) | **Fully Autonomous** | 100% unit-testable combinatorial logic covering all vote splits. |
| **4** | Multi-agent debate orchestration (4 rounds, async) | **Fully Autonomous** | Structured prompt orchestration with Pydantic output validation. |
| **5** | Rational Track (Smoothed Open-Economy Taylor Rule + Monte Carlo) | **Fully Autonomous** | Pure numerical simulation (`numpy`, `scipy`, `statsmodels`). |
| **5** | Taylor parameter sign-off ($\alpha, \beta, \gamma, \rho, r^*$) | **[HUMAN REQUIRED]** | Domain calibration check (aligning neutral real rate with RBI literature). |
| **6** | Validation Gate & Holdout Scoring | **Fully Autonomous** | Automated calculation of directional accuracy, stance accuracy, and dissent F1. |
| **6** | Persona recalibration decisions | **[HUMAN REQUIRED]** | Preventing data snooping/p-hacking; logged in `CALIBRATION_LOG.md`. |
| **7** | Counterfactual Scenarios (Monsoon shock, Fed spillover) | **Fully Autonomous** | Parametrized reruns over validated baseline. |
| **8** | Attribution Layer (Leave-one-out, casting vote ablation, macro muting) | **Fully Autonomous** | Controlled transcript and pipeline ablations. |
| **9** | Synthesis, vector figures, markdown report | **Fully Autonomous** | Automated generation of tables, charts, and `RESULTS_REPORT.md`. |
| **10** | Reproducibility harness (`make reproduce`) | **Hybrid** | Automated script execution + human sanity check for submission. |

---

## 2. Global Defensive Standards (Enforced in Code)

1. **Contract-First Independence:** Every phase must declare its input/output schema in `src/schemas/`. Every phase MUST include unit tests that run against offline mock fixtures in `tests/fixtures/`, ensuring continuous CI greenness regardless of external network or scraping state.
2. **Single Source of Truth:** All hyperparameters, model identifiers, API keys, action sets, thresholds, and seeds reside in `config/config.yaml`, validated by `pydantic-settings` at runtime.
3. **Deterministic Cache with Content Hashing:** All LLM calls are intercepted by a disk cache keyed on `sha256(provider + model + system_prompt + user_prompt + temperature + seed)`. Never pay twice for the same token stream.
4. **Hard Cost & Token Governor:** A thread-safe monitor tracks cumulative tokens and estimated USD expenditure. If cumulative spend hits `budget_usd_cap` (default: $25.00), the process raises a `BudgetExceededError` immediately.
5. **Holdout Vaulting (`HOLDOUT_LOCKED`):** Holdout meeting dates are strictly segregated. Attempting to pass holdout data into persona prompt tuning triggers an explicit programmatic assertion.
6. **Strict Transcript Logging:** Every agent utterance, prompt snapshot, intermediate deliberation state, and final vote is written to `runs/{run_id}/transcripts/{meeting_date}/round_{N}_{member}.json`.
7. **Graceful Degradation & Retries:** LLM calls enforce exponential backoff with jitter (max 3 retries). Structured JSON outputs are validated via Pydantic; if an agent fails schema validation twice, it falls back to a deterministic parsing error handler with manual inspection flagging.

---

## 3. Technology Stack

| Layer | Choice | Reasoning |
|---|---|---|
| **Language** | Python 3.11+ | Modern typing, high performance, robust async runtime. |
| **Package Management** | `pip` + `requirements.txt` / virtualenv | Universal portability across macOS and Linux without requiring `uv`/`poetry` binaries. |
| **Primary LLM Provider** | **Google Gemini (Gemini 2.5 Flash / Pro)** via `google-genai` | High reasoning speed, native context caching, massive 1M+ context window, exceptionally low cost (~$0.075 / $0.30 per 1M tokens). |
| **LLM Fallback Adapter** | Lightweight Async Interface (`src/infra/llm_client.py`) | Allows seamless drop-in switching to OpenAI (`gpt-4o-mini`), Anthropic (`claude-3-5-sonnet`), or local Ollama (`llama3.3`). |
| **Data & Tables** | `pandas`, `pyarrow` (Parquet), `pydantic` v2 | Fast, typed, relational-grade tabular storage. |
| **Numerical Modeling** | `numpy`, `scipy`, `statsmodels` (HP filter) | Standard numerical optimization and time-series filtering. |
| **Web Crawling & NLP** | `requests`, `beautifulsoup4`, `pdfplumber` | Clean digital extraction from RBI web releases and PDF minutes. |
| **Visualization** | `matplotlib`, `seaborn` | Clean, journal-grade vector figures (PDF / high-res PNG). |
| **Testing** | `pytest`, `pytest-asyncio`, `pytest-cov` | Exhaustive async testing and branch coverage measurement. |

---

## 4. Repository Directory Structure

```
rbi-mpc-in-silico/
├── config/
│   ├── config.yaml                     # Single source of truth
│   └── default_personas.yaml           # Seed attributes for historical members
├── data/
│   ├── raw/
│   │   ├── minutes_html/               # Downloaded RBI press releases
│   │   ├── minutes_pdf/                # Downloaded official PDFs
│   │   ├── macro_manual_drop/          # Drag-and-drop folder for DBIE/IMD CSVs
│   │   └── manifest.csv                # Provenance log (url, timestamp, sha256)
│   ├── processed/
│   │   ├── macro_panel.parquet         # Harmonized monthly macroeconomic panel
│   │   └── statements/                 # Extracted statements: {meeting_date}/{member}.txt
│   └── DATA_VERSION.txt                # Cryptographic hash lock of processed data
├── personas/
│   ├── 2020_2024_roster/               # Goyal, Bhide, Varma, Das, Patra, Saggar/Ranjan
│   ├── 2024_present_roster/            # Singh, Bhattacharya, Kumar, Das, Patra, Ranjan
│   └── PERSONA_REVIEW.md               # Human qualitative sign-off register
├── src/
│   ├── schemas/                        # Pydantic v2 data and prompt contracts
│   │   ├── macro_schema.py
│   │   ├── debate_schema.py
│   │   └── persona_schema.py
│   ├── infra/                          # Core infrastructure (independent of domain)
│   │   ├── config_loader.py
│   │   ├── llm_client.py               # Gemini + multi-provider async client
│   │   ├── cache.py                    # SQLite/file-based response cache
│   │   ├── cost_governor.py            # Budget watchdog
│   │   └── transcript_logger.py
│   ├── data_pipeline/                  # Phase 1: Ingestion & harmonization
│   │   ├── minutes_crawler.py
│   │   ├── statement_extractor.py
│   │   ├── fred_client.py
│   │   └── macro_builder.py
│   ├── persona_engine/                 # Phase 2: Persona generation & prompt templates
│   │   ├── extractor.py
│   │   └── prompt_templates.py
│   ├── rule_engine/                    # Phase 3: RBI Act §45ZL statutory voting logic
│   │   └── engine.py
│   ├── behavioral/                     # Phase 4: 4-round async multi-agent debate
│   │   ├── agent.py
│   │   └── debate_orchestrator.py
│   ├── rational/                       # Phase 5: Smoothed open-economy Taylor rule + MC
│   │   ├── taylor_rule.py
│   │   └── monte_carlo.py
│   ├── validation/                     # Phase 6: Holdout evaluation & metrics
│   │   ├── evaluator.py
│   │   └── metrics.py
│   ├── scenarios/                      # Phase 7: Food shock & Fed spillover counterfactuals
│   │   └── scenario_runner.py
│   ├── attribution/                    # Phase 8: Leave-one-out, casting vote, macro muting
│   │   └── attribution_runner.py
│   └── reporting/                      # Phase 9: Synthesis & publication assets
│       ├── report_builder.py
│       └── plot_figures.py
├── tests/
│   ├── fixtures/                       # OFFLINE MOCK FIXTURES (Enables Phase Decoupling)
│   │   ├── mock_macro_panel.parquet
│   │   ├── mock_statements/
│   │   └── mock_transcripts/
│   ├── test_infra.py
│   ├── test_rule_engine.py             # 100% branch coverage of voting permutations
│   ├── test_taylor_rule.py
│   ├── test_debate_mock.py             # Full 6-agent simulation in <5s using mock LLM
│   └── test_attribution.py
├── runs/                               # Persisted simulation transcripts and logs
├── results/
│   ├── tables/
│   ├── figures/
│   └── RESULTS_REPORT.md
├── .env.example
├── Makefile
├── requirements.txt
└── README.md
```

---

## 5. Master Configuration Specification (`config/config.yaml`)

```yaml
project:
  name: "RBI_MPC_In_Silico"
  version: "2.0.0"

run:
  provider: "gemini"                      # "gemini" | "openai" | "anthropic" | "ollama"
  dev_model: "gemini-2.5-flash"
  final_model: "gemini-2.5-flash"         # Can elevate to "gemini-2.5-pro" for final report
  budget_usd_cap: 25.0                    # Hard stop limit
  temperature: 0.6
  n_replicates: 3                         # Independent seeded runs per meeting
  seed_base: 42
  use_cache: true

decision_space:
  action_set_bps: [-50, -25, 0, 25, 50]
  simulate_stance: true                   # Enable dual-vote institutional realism
  stance_set: ["withdrawal_of_accommodation", "neutral", "accommodative"]

panels:
  primary_roster: "2020_2024"             # Primary benchmark (Goyal, Bhide, Varma, Das, Patra, Saggar/Ranjan)
  primary_panel_start: "2020-10-01"
  primary_panel_end: "2024-08-31"
  calibration_holdout_split: 0.67         # 16 calibration meetings / 8 holdout meetings
  forward_test_panel_start: "2024-10-01"  # Post-Oct 2024 external roster (Singh, Bhattacharya, Kumar)
  forward_test_panel_end: "latest"

taylor_rule:                              # Smoothed open-economy specification
  r_star_pct: 1.4                         # Equilibrium neutral real rate (RBI working paper baseline)
  pi_star_pct: 4.0                        # Statutory headline inflation target
  hp_filter_lambda: 14400                 # Ravn-Uhlig monthly HP smoothing parameter
  smoothing_rho: 0.75                     # Central bank interest rate inertia parameter
  default_alpha: 1.5                      # Inflation gap responsiveness
  default_beta: 0.5                       # Output gap responsiveness
  default_gamma: 0.2                      # Open-economy US Fed Funds rate differential responsiveness
  us_neutral_rate_pct: 2.5                # Long-run US Fed neutral rate

monte_carlo:
  n_draws: 1000
  macro_noise_std_pct: 0.20               # Parameter shock standard deviation

validation:
  directional_accuracy_threshold: 0.75    # Required match rate on committee rate decision
  stance_accuracy_threshold: 0.70         # Required match rate on committee stance decision
  dissent_f1_threshold: 0.50              # Required member-level dissent detection F1

debate_protocol:
  rounds: 4                               # 1: Initial Stance, 2: Rebuttal, 3: Deliberation, 4: Binding Vote
  order_mode: "fixed_governor_last"       # Real RBI protocol: Governor summarizes and votes last
  cross_visibility: true                  # Named positions revealed after Round 1
```

---

## 6. Detailed Phase Execution Roadmap

### Phase 0: Infrastructure & Contract-First Test Fixtures
- **Objective:** Establish the bedrock system, multi-provider LLM client, caching, cost watchdog, and offline mock fixtures.
- **Tasks:**
  1. Build `src/infra/` modules: `config_loader.py`, `cache.py`, `cost_governor.py`, `transcript_logger.py`.
  2. Implement unified async `src/infra/llm_client.py` wrapping the Google Gemini SDK (`google-genai`) with exponential backoff and disk caching.
  3. Create synthetic test fixtures in `tests/fixtures/`: a valid 12-month `mock_macro_panel.parquet` and synthetic `mock_statements/`.
  4. Implement `test_infra.py`: verify that mock LLM calls round-trip through cache, that repeat calls do not hit the provider, and that cost tracking works.
- **Exit Criteria:** `pytest tests/test_infra.py` passes 100% green without requiring an external internet connection.

---

### Phase 1: Data Acquisition & Decoupled Ingestion Pipeline
- **Objective:** Ingest and harmonize macroeconomic series and MPC minutes, providing both automated scrapers and manual drag-and-drop CSV fallbacks.
- **Series Ingested:**
  - Macro: CPI-Combined YoY, Core CPI, IIP growth, quarterly GVA growth, system liquidity (net LAF), USD/INR exchange rate, Brent crude price, US Federal Funds Rate, and Monsoon rainfall departure from Long Period Average (LPA).
  - Committee: Individual member statements extracted from bi-monthly MPC minutes (2020–2024 and 2024–present).
- **Tasks:**
  1. Script `minutes_crawler.py`: auto-download official minutes press releases from `rbi.org.in` into `data/raw/minutes_html/` and `data/raw/minutes_pdf/`.
  2. Implement `statement_extractor.py`: split each minutes document into 6 signed member text files (`data/processed/statements/{date}/{member}.txt`).
  3. Script `fred_client.py`: auto-fetch `DEXINUS` (USD/INR), `DCOILBRENTEU` (Brent), and `FEDFUNDS`.
  4. Implement `macro_builder.py`: merge DBIE/MOSPI manual drop files (or fallback synthetic data) with FRED series into canonical `data/processed/macro_panel.parquet`.
  5. Build `data_validator.py`: assert zero missing dates, value ranges within historical bounds, and schema conformance.
- **Self-Contained Safeguard:** If DBIE scraping is blocked by the RBI firewall, user drops raw CSVs into `data/raw/macro_manual_drop/`, or runs `make use-synthetic-data` to proceed immediately with downstream development.
- **Exit Criteria:** `macro_panel.parquet` passes all schema checks; statements for the 2020–2024 roster are extracted and verified.

---

### Phase 2: Persona Construction & Human Sign-Off
- **Objective:** Create structured YAML profiles capturing the economic philosophy, growth-vs-inflation priority, and reasoning style of each MPC member.
- **Roster Modeled (2020–2024):**
  - External Members: Prof. Jayanth R. Varma (Academic, Inflation Hawk / Growth Pragmatist, frequent dissenter on stance and tightening), Dr. Ashima Goyal (Academic, Growth-Conscious / Focus on Real Rates), Dr. Shashanka Bhide (Agricultural / Supply-Side Economist).
  - Internal Members: Shaktikanta Das (Governor, Consensus Builder / Pragmatist), Dr. Michael D. Patra (Deputy Governor, Monetary Economics Hawk), Dr. Rajiv Ranjan / Dr. Mridul Saggar (Executive Director, Macro-Liquidity Focus).
- **Persona Schema (`personas/{roster}/{member}.yaml`):**
  ```yaml
  member_name: "Jayanth R. Varma"
  role: "External"
  tenure: "2020-10 to 2024-10"
  historical_dissent_rate_pct: 62.5
  stance_bias: "neutral"
  hawk_dove_score: -0.25 # [-1.0 Dovish to +1.0 Hawkish]
  core_economic_doctrines:
    - "Real interest rates must not excessively penalize post-pandemic economic recovery."
    - "Dissent on stance is essential when forward guidance is excessively rigid."
  key_phrases: ["excessive sacrifice of growth", "real rate of interest", "forward guidance"]
  system_prompt_template: "personas/templates/member_base.jinja2"
  ```
- **Tasks:**
  1. Build `persona_engine/extractor.py`: process historical statements to draft hawk-dove scores, top cited macro indicators, and characteristic arguments.
  2. Populate YAML files for all 6 core members + 3 post-2024 replacement members.
  3. Log qualitative review in `personas/PERSONA_REVIEW.md`.
- **Exit Criteria:** `[HUMAN REQUIRED]` User reviews and marks sign-off in `PERSONA_REVIEW.md`; Pydantic schema validation passes.

---

### Phase 3: Institutional Rule Engine (RBI Act §45ZL)
- **Objective:** Deterministic, mathematical implementation of the Reserve Bank of India's statutory voting rule.
- **Statutory Logic:**
  1. **Dual Decision Aggregation:** Independent aggregation for **Repo Rate Action** ($V^{rate}$) and **Policy Stance** ($V^{stance}$).
  2. **Majority Rule:** If any discrete action receives $\ge 4$ votes, that action is adopted.
  3. **Binary Tie & Governor's Casting Vote:** If votes split 3–3 between exactly two actions, the Governor's vote counts twice (RBI Act §45ZL), deciding the outcome.
  4. **Fragmented Non-Binary Split (e.g., 2-2-1-1 or 2-2-2):** Real central bank procedure evaluates motions sequentially. The Governor's proposal is put forward as the primary motion; if it lacks a majority, the outcome adopts the vote-weighted median action with the Governor's vote weighted $\times 2$.
- **Tasks:**
  1. Implement `src/rule_engine/engine.py` with pure, stateless functions.
  2. Implement `tests/test_rule_engine.py` with exhaustive parameterized test cases covering 100% of branch permutations (unanimous 6-0, 5-1, 4-2, 3-3 tie broken by Governor, 3-3 tie where Governor is in minority, and 2-2-2 multi-way splits).
- **Exit Criteria:** 100% branch and statement coverage on `engine.py`.

---

### Phase 4: Behavioral Track (Multi-Agent Deliberation Simulation)
- **Objective:** Orchestrate the 6 LLM agents through a 4-round deliberation cycle matching actual RBI MPC meetings.
- **Protocol:**
  - **Round 1 (Independent Initial Stance):** 6 parallel calls. Each agent receives only their personal persona prompt and the meeting's macroeconomic snapshot. Outputs: preliminary rate vote, stance vote, and 3-sentence economic rationale.
  - **Round 2 (Cross-Debate & Rebuttal):** 6 parallel calls. Agents see all 6 Round-1 statements (named). Agents critique opposing views (e.g. Varma challenging Patra on real rate sacrifice, or Patra warning of headline inflation persistence).
  - **Round 3 (Deliberation & Compromise):** 6 parallel calls. Agents assess committee consensus and state whether they are open to moving their position.
  - **Round 4 (Final Binding Vote):** 6 calls. Real RBI meeting order (members vote sequentially; Governor votes last). Agents cast binding votes:
    ```json
    {
      "rate_vote_bps": 0,
      "stance_vote": "neutral",
      "rationale": "Inflation has stabilized within the tolerance band while growth requires support...",
      "dissenting": true
    }
    ```
- **Defensive Engineering:** Checkpointing after each meeting; full transcript logging; automatic Pydantic parsing with retry fallback.
- **Exit Criteria:** Full simulation run over test panel executes smoothly, storing complete JSONL transcripts without schema failures.

---

### Phase 5: Rational Track (Smoothed Open-Economy Taylor Rule + Monte Carlo)
- **Objective:** Provide a mathematical benchmark to measure the behavioral LLM-vs-rational wedge.
- **Open-Economy Smoothed Specification:**
  $$r_{i,t}^* = r^* + \pi_t + \alpha_i(\pi_t - \pi^*) + \beta_i(y_t - y^*) + \gamma_i(i^{US}_t - i^{US*})$$
  $$r_{i,t} = \rho r_{t-1} + (1 - \rho) r_{i,t}^*$$
  where:
  - $\pi_t$: CPI-Combined YoY inflation.
  - $\pi^*$: 4.0% (RBI statutory target).
  - $y_t - y^*$: Output gap estimated via monthly HP-filtered IIP ($\lambda = 14400$).
  - $i^{US}_t - i^{US*}$: US Fed Funds rate departure from neutral.
  - $\rho \approx 0.75$: Empirical interest rate smoothing parameter.
  - $\alpha_i, \beta_i, \gamma_i$: Member-specific calibration coefficients fitted by minimizing historical vote errors.
- **Monte Carlo Simulation:** 1,000 parameter and data perturbation draws per meeting; aggregated via the same Phase 3 Rule Engine.
- **Exit Criteria:** Calibration parameter table signed off; unit tests validate numerical stability against hand-computed test matrices.

---

### Phase 6: Empirical Validation Gate & Holdout Backtesting
- **Objective:** Evaluate simulation performance against the frozen 8-meeting holdout panel (Oct 2020 – Aug 2024) before proceeding to counterfactuals.
- **Metrics Evaluated:**
  1. **Directional Rate Accuracy:** Percentage of meetings where the simulated committee rate decision matches the real RBI outcome ($\ge 75\%$).
  2. **Stance Accuracy:** Percentage of meetings where the simulated stance matches the real stance ($\ge 70\%$).
  3. **Member-Level Dissent F1 Score:** Precision, recall, and F1 of detecting which specific individual members dissented ($\ge 0.50$).
- **Recalibration Protocol:** If holdout accuracy is below threshold, persona prompt adjustments are restricted to the 16 calibration meetings. Every modification is logged with git diffs and rationale in `runs/CALIBRATION_LOG.md`.
- **Exit Criteria:** Holdout validation metrics computed and logged; validation gate declared passed.

---

### Phase 7: Counterfactual Scenario Experiments
- **Objective:** Quantify the behavioral-vs-rational wedge under two India-specific economic shocks anchored to real historical data:
  1. **Scenario 1 (Monsoon Failure & Vegetable Food-Inflation Shock):**
     - Anchored to the July 2023 tomato/vegetable inflation spike (+400 bps food CPI surge).
     - Macro snapshot perturbed; both behavioral and rational tracks rerun across $N=3$ replicates.
     - Measures how quickly the simulated committee pivots toward hawkish tightening vs looking through transitory food shocks.
  2. **Scenario 2 (US Federal Reserve Spillover Shock):**
     - Anchored to the aggressive 2022 US Fed tightening (+75 bps hike, capital outflow, INR depreciation to 83.0+).
     - Macro snapshot perturbed; behavioral and rational tracks rerun.
     - Measures committee sensitivity to external balance and currency defense.
- **Exit Criteria:** Both scenarios executed; behavioral-vs-rational wedges quantified and tabulated.

---

### Phase 8: Interaction-Level Attribution Layer (3 Pre-Specified Experiments)
- **Objective:** Determine the causal contribution of specific interactions, rules, and inputs to the committee's decision:
  1. **Experiment 1 (Leave-One-Member-Out Persuasion Ablation):**
     - In Rounds 2 and 3, withhold one member's arguments (e.g. mute Prof. Jayanth Varma or Dr. Michael Patra) from the other 5 agents' contexts.
     - Rerun deliberation and observe if any other members alter their final votes. Directly tests whether members actually persuade one another in LLM debate.
  2. **Experiment 2 (Statutory Casting-Vote Ablation):**
     - On all meetings resulting in a 3–3 tie, re-execute the Phase 3 Rule Engine with the casting-vote rule disabled (requiring a strict 4-vote majority) or assigned to external members.
     - Quantifies the institutional power of the Governor's second vote.
  3. **Experiment 3 (Macro-Factor Muting):**
     - Zero out specific macro inputs (e.g. set monsoon departure to 0.0 or neutralize food CPI) while holding headline numbers constant.
     - Isolates the marginal sensitivity of individual personas to supply-side vs demand-side data.
- **Exit Criteria:** All three attribution experiments executed; Shapley/leave-one-out delta tables generated.

---

### Phase 9: Synthesis, Vector Visualization & Academic Reporting
- **Objective:** Compile all empirical findings into publication-ready figures and an automated report.
- **Deliverables:**
  - `results/tables/`:
    - `table1_holdout_validation_accuracy.csv` (Rate, Stance, Dissent F1)
    - `table2_rational_vs_behavioral_wedge.csv`
    - `table3_counterfactual_shock_responses.csv`
    - `table4_attribution_ablation_effects.csv`
  - `results/figures/`:
    - `fig1_methodology_pipeline.pdf`
    - `fig2_holdout_confusion_matrix.pdf`
    - `fig3_deliberation_stance_trajectories.pdf` (Tracking stance evolution from Round 1 to Round 4)
    - `fig4_counterfactual_impulse_comparison.pdf`
  - `results/RESULTS_REPORT.md`: Auto-generated synthesis document formatted for journal submission or academic project evaluation.
- **Exit Criteria:** All tables and figures successfully built from raw run outputs with zero missing cells.

---

### Phase 10: Reproducibility & Submission Verification
- **Objective:** Ensure single-command end-to-end reproducibility.
- **Harness:** `make reproduce` runs the complete verification suite from clean environment checks to final figures.
- **Exit Criteria:** Clean run from scratch generates matching results within tolerance bounds; code repository packaged for submission.

---

## 7. Budget, Token & Cost Accounting (Google Gemini Engine)

Using Google Gemini 2.5 Flash via the `google-genai` SDK:
- **Pricing:** ~$0.075 per 1M input tokens, ~$0.30 per 1M output tokens (with automatic context caching discounts on prompt repeats).
- **Run Estimation:**
  - Primary Panel (24 meetings $\times$ 4 rounds $\times$ 6 agents $\times$ 3 replicates): ~1,728 calls
  - Calibration Tuning Reruns (2 passes $\times$ 16 meetings): ~768 calls
  - Counterfactuals & Attribution Experiments: ~960 calls
  - **Total Estimated Calls:** ~3,456 calls (~7.0M input tokens / ~1.2M output tokens)
- **Estimated Total Cost:**
  $$\text{Input: } 7.0 \times \$0.075 = \$0.53 \quad|\quad \text{Output: } 1.2 \times \$0.30 = \$0.36 \quad\implies\quad \mathbf{\approx \$1.00 \text{ to } \$3.00 \text{ Total}}$$
- Even if elevated to **Gemini 2.5 Pro** for final validated runs, the total project spend remains under **$10.00 – $15.00**, well within the `$25.00` safety governor cap.

---

## 8. Staged Execution Timeline

```
STAGE 1: FAST MVP (Days 1 to 5) — Decoupled Proof of Concept
├── Day 1: Phase 0 (Infra, Gemini Client, Cache, Cost Watchdog, Mock Fixtures)
├── Day 2: Phase 3 (Institutional Rule Engine with 100% Branch Coverage)
├── Day 3: Phase 2 & 4 (Persona Prompts + 4-Round Mock Deliberation Simulation)
├── Day 4: Phase 5 (Smoothed Open-Economy Taylor Rule + Monte Carlo Baseline)
└── Day 5: End-to-End Integration Run on Synthetic Panel (Fast Demonstration Ready)

STAGE 2: EMPIRICAL RIGOR (Weeks 2 to 4) — Academic & Journal Rigor
├── Week 2: Phase 1 (Real RBI Minutes Scraping, Statement Extraction, FRED Data)
├── Week 3: Phase 6 (Holdout Validation Gate on 2020-2024 Panel, Recalibration Loop)
├── Week 4: Phase 7 & 8 (Empirical Counterfactuals, Attribution Experiments)
└── Final:  Phase 9 & 10 (Vector Figures, RESULTS_REPORT.md, Reproducibility Audit)
```

---

## 9. Immediate Next Actions & Coding Agent Handoff

To execute this plan systematically, proceed phase by phase:
1. **Initialize Phase 0:** Scaffold the repository structure, configure Python environment, and build `src/infra/` with offline mock fixtures.
2. **Verify Phase 0 Exit Criteria:** Run `pytest tests/test_infra.py` to confirm caching, config loading, and token monitoring.
3. **Execute Phase 3 (Rule Engine):** Implement the RBI Act §45ZL voting engine and verify 100% branch coverage with unit tests.
4. **Execute Phase 4 (Mock Debate):** Run a 6-agent mock deliberation using synthetic fixtures to prove end-to-end deliberation mechanics.
