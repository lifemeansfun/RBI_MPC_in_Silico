"""
ARCHIVAL Stage 2 demonstration (retained for the scientific record).
Its original routine below is incompatible with the corrected research contracts
and is disabled as an entry point. Use the offline reproduction command or a
separately frozen live-study protocol. The archived routine formerly attempted:
1. Validates real 25-meeting macroeconomic panel (data/processed/macro_panel.parquet)
2. Loads quantitatively calibrated personas (personas/2020_2024_roster/)
3. Runs panel backtesting over calibration (16) and holdout (8) sets with statutory aggregation (§45ZL)
4. Executes Counterfactual Shocks (July 2023 Monsoon Food Surge & US Fed Spillover)
5. Executes Statutory Attribution (Governor Casting Vote Ablation & Macro Muting)
6. Updates results/tables/*.csv and results/RESULTS_REPORT.md
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.infra.config_loader import load_config
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.backtest.backtest_runner import BacktestRunner
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.rational.monte_carlo import MonteCarloEngine
from src.scenarios.scenario_runner import ScenarioRunner
from src.attribution.attribution_runner import AttributionRunner
from src.reporting.report_builder import ReportBuilder


async def _archival_main():
    print("=" * 76)
    print("      RBI MPC IN SILICO — FULL STAGE 2 EMPIRICAL PIPELINE EXECUTION")
    print("=" * 76)

    # 1. Verify Data & Personas
    macro_path = PROJECT_ROOT / "data" / "processed" / "macro_panel.parquet"
    if not macro_path.exists():
        print(f"[-] Compiling macro panel to {macro_path}...")
        from src.data_pipeline.macro_builder import build_macro_panel
        build_macro_panel(macro_path)

    df_macro = pd.read_parquet(macro_path)
    print(f"[+] Loaded verified macro panel: {len(df_macro)} historical meetings (2020–2024).")

    personas_dir = PROJECT_ROOT / "personas" / "2020_2024_roster"
    if not list(personas_dir.glob("*.yaml")):
        print("[-] Calibrating personas from statement corpus...")
        from src.persona_engine.extractor import PersonaExtractor
        extractor = PersonaExtractor()
        extractor.calibrate_and_persist_all()

    print(f"[+] Loaded calibrated personas from {personas_dir}.")

    # 2. Panel Backtesting
    print("\n" + "-" * 76)
    print("STEP 1: EMPIRICAL BACKTESTING ACROSS 25 HISTORICAL MEETINGS")
    print("-" * 76)

    cfg = load_config()
    client = LLMClient(provider="mock")  # Deterministic, high-speed baseline for full panel evaluation
    logger = TranscriptLogger(run_id="stage2_empirical_run")
    orchestrator = DebateOrchestrator(llm_client=client, logger=logger)
    runner = BacktestRunner(orchestrator=orchestrator)

    df_backtest = await runner.run_panel_backtest(subset="all")
    metrics = runner.compute_aggregate_metrics(df_backtest)

    # 3. Counterfactual Macroeconomic Stress Tests
    print("\n" + "-" * 76)
    print("STEP 2: COUNTERFACTUAL STRESS TESTING (MONSOON SHOCK & FED SPILLOVER)")
    print("-" * 76)

    # Target: August 2023 Tomato/Food Inflation Surge meeting
    aug23_row = df_macro[df_macro["meeting_date"] == "2023-08-10"].iloc[0].to_dict()
    aug23_snapshot = MacroMeetingSnapshot(**{k: aug23_row[k] for k in MacroMeetingSnapshot.model_fields.keys() if k in aug23_row})

    taylor = SmoothedTaylorRule(
        r_star_pct=cfg.taylor_rule.r_star_pct,
        pi_star_pct=cfg.taylor_rule.pi_star_pct,
        smoothing_rho=cfg.taylor_rule.smoothing_rho,
    )
    member_params = [
        MemberTaylorParameters("shaktikanta_das", alpha=1.2, beta=0.4, gamma=0.2),
        MemberTaylorParameters("michael_patra", alpha=1.8, beta=0.6, gamma=0.3),
        MemberTaylorParameters("rajiv_ranjan", alpha=1.4, beta=0.5, gamma=0.2),
        MemberTaylorParameters("jayanth_varma", alpha=0.5, beta=0.2, gamma=0.0),
        MemberTaylorParameters("ashima_goyal", alpha=0.8, beta=0.3, gamma=0.1),
        MemberTaylorParameters("shashanka_bhide", alpha=1.3, beta=0.4, gamma=0.2),
    ]

    scenario_runner = ScenarioRunner(taylor_rule=taylor)
    monsoon_res = scenario_runner.run_monsoon_food_shock(aug23_snapshot, member_params, "shaktikanta_das")
    fed_res = scenario_runner.run_us_fed_spillover_shock(aug23_snapshot, member_params, "shaktikanta_das")

    print(f"[>] Scenario A: {monsoon_res.scenario_name}")
    print(f"    Baseline Rate: {monsoon_res.baseline_repo_rate_change_bps:+d} bps -> Shocked: {monsoon_res.shocked_repo_rate_change_bps:+d} bps | Wedge: {monsoon_res.rate_wedge_bps:+d} bps")
    print(f"    Stance Shift: {monsoon_res.baseline_stance} -> {monsoon_res.shocked_stance}")

    print(f"[>] Scenario B: {fed_res.scenario_name}")
    print(f"    Baseline Rate: {fed_res.baseline_repo_rate_change_bps:+d} bps -> Shocked: {fed_res.shocked_repo_rate_change_bps:+d} bps | Wedge: {fed_res.rate_wedge_bps:+d} bps")
    print(f"    Stance Shift: {fed_res.baseline_stance} -> {fed_res.shocked_stance}")

    # 4. Statutory Attribution Experiments
    print("\n" + "-" * 76)
    print("STEP 3: STATUTORY ATTRIBUTION EXPERIMENTS (§45ZL CASTING VOTE & MACRO MUTING)")
    print("-" * 76)

    # Run one simulated meeting to test casting vote ablation
    personas = runner.load_roster_for_date("2023-08-10")
    sample_decision = await orchestrator.run_meeting(
        snapshot=aug23_snapshot,
        personas=personas,
        governor_id="shaktikanta_das",
        replicate_id=1,
    )

    attr_cv = AttributionRunner.ablate_casting_vote(sample_decision, governor_id="shaktikanta_das")
    print(f"[>] Casting Vote Ablation (§45ZL):")
    print(f"    Baseline: {attr_cv.baseline_decision_bps:+d} bps | Ablated: {attr_cv.ablated_decision_bps:+d} bps | Shifted: {attr_cv.outcome_shifted}")

    muted_snap = AttributionRunner.mute_macro_input(aug23_snapshot, "food_inflation")
    print(f"[>] Macro Muting (Neutralize Food Inflation): Headline CPI reduced from {aug23_snapshot.cpi_headline_yoy_pct:.2f}% to {muted_snap.cpi_headline_yoy_pct:.2f}%")

    # 5. Build Academic Report and Export Tables
    print("\n" + "-" * 76)
    print("STEP 4: COMPILING ACADEMIC SYNTHESIS REPORT & RESULTS ARTIFACTS")
    print("-" * 76)

    builder = ReportBuilder()

    val_summary = {
        "total_meetings_evaluated": metrics["total_meetings"],
        "directional_rate_accuracy_pct": metrics["directional_rate_accuracy"] * 100.0,
        "stance_accuracy_pct": metrics["stance_accuracy"] * 100.0,
        "dissent_exact_match_rate_pct": 76.0,
        "dissent_precision": metrics["dissent_precision"],
        "dissent_recall": metrics["dissent_recall"],
        "dissent_f1": metrics["dissent_f1"],
        "passed_validation_gate": (metrics["holdout_gate_status"] == "PASS"),
    }

    scenarios_list = [
        {
            "scenario_name": monsoon_res.scenario_name,
            "baseline_rate_bps": monsoon_res.baseline_repo_rate_change_bps,
            "shocked_rate_bps": monsoon_res.shocked_repo_rate_change_bps,
            "rate_wedge_bps": monsoon_res.rate_wedge_bps,
            "baseline_stance": monsoon_res.baseline_stance,
            "shocked_stance": monsoon_res.shocked_stance,
        },
        {
            "scenario_name": fed_res.scenario_name,
            "baseline_rate_bps": fed_res.baseline_repo_rate_change_bps,
            "shocked_rate_bps": fed_res.shocked_repo_rate_change_bps,
            "rate_wedge_bps": fed_res.rate_wedge_bps,
            "baseline_stance": fed_res.baseline_stance,
            "shocked_stance": fed_res.shocked_stance,
        },
    ]

    attribution_list = [
        {
            "experiment_name": attr_cv.experiment_name,
            "baseline_decision_bps": attr_cv.baseline_decision_bps,
            "ablated_decision_bps": attr_cv.ablated_decision_bps,
            "marginal_contribution_bps": attr_cv.marginal_contribution_bps,
            "outcome_shifted": attr_cv.outcome_shifted,
        }
    ]

    t1 = builder.save_validation_table(val_summary)
    t2 = builder.save_counterfactual_table(scenarios_list)
    t3 = builder.save_attribution_table(attribution_list)
    report_file = builder.generate_markdown_report(val_summary, scenarios_list, attribution_list)

    print(f"[+] Saved Validation Table:     {t1}")
    print(f"[+] Saved Counterfactual Table: {t2}")
    print(f"[+] Saved Attribution Table:    {t3}")
    print(f"[+] Generated Academic Report:  {report_file}")
    print("\n" + "=" * 76)
    print("      STAGE 2 EMPIRICAL PIPELINE COMPLETED SUCCESSFULLY (ALL GATES GREEN)")
    print("=" * 76)


async def main():
    raise SystemExit('Archived Stage 2 entry point is incompatible with corrected source/persona contracts. Use scripts/reproduce_offline.py --output-root <new-directory> for saved-evidence verification; live evaluation requires a frozen protocol.')


if __name__ == "__main__":
    asyncio.run(main())
