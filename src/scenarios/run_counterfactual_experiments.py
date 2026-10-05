"""
Master Counterfactual Scenarios & Attribution Experiments Runner (Phases 7 & 8).
Executes:
- Phase 7:
  1. Scenario 1: Monsoon Failure & Food Inflation Surge (+400 bps food CPI, anchored on 2023-08-10)
  2. Scenario 2: US Federal Reserve Spillover Shock (+75 bps Fed Funds, INR depreciation, anchored on 2022-08-05)
  Quantifies Behavioral-vs-Rational Policy Wedges across both tracks.
- Phase 8:
  1. Experiment 1: Leave-One-Member-Out Persuasion Ablation (withholding Varma & Patra)
  2. Experiment 2: Statutory Casting-Vote Ablation (RBI Act Section 45ZL)
  3. Experiment 3: Macro-Factor Muting (Neutralizing Monsoon departure & Food inflation)
Exports:
- results/tables/table3_counterfactual_shock_responses.csv
- results/tables/table4_attribution_ablation_effects.csv
"""

import asyncio
import logging
import sys
from pathlib import Path
import yaml
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.rational.taylor_rule import SmoothedTaylorRule
from src.rational.rational_panel_runner import MEMBER_TAYLOR_PARAMS
from src.scenarios.scenario_runner import ScenarioRunner
from src.attribution.attribution_runner import AttributionRunner, AttributionResult
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.infra.llm_client import LLMClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rbi_mpc.counterfactual_runner")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def load_all_personas() -> list[MemberPersona]:
    """Loads calibrated YAML personas for the core 2020-2024 committee."""
    personas_dir = PROJECT_ROOT / "personas" / "2020_2024_roster"
    core_members = ["shaktikanta_das", "michael_patra", "rajiv_ranjan", "shashanka_bhide", "ashima_goyal", "jayanth_varma"]
    personas = []
    for m in core_members:
        y_path = personas_dir / f"{m}.yaml"
        with open(y_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            personas.append(MemberPersona(**data))
    return personas


def load_meeting_snapshot(meeting_date: str) -> MacroMeetingSnapshot:
    """Loads macro snapshot for a given historical meeting from processed parquet panel."""
    parquet_path = PROJECT_ROOT / "data" / "processed" / "macro_panel.parquet"
    df = pd.read_parquet(parquet_path)
    row = df[df["meeting_date"] == meeting_date]
    if row.empty:
        raise ValueError(f"Meeting date {meeting_date} not found in macro panel")
    r = row.iloc[0].to_dict()
    return MacroMeetingSnapshot(
        meeting_date=r["meeting_date"],
        current_repo_rate_pct=float(r["current_repo_rate_pct"]),
        cpi_headline_yoy_pct=float(r["cpi_headline_yoy_pct"]),
        cpi_core_yoy_pct=float(r["cpi_core_yoy_pct"]),
        cpi_food_yoy_pct=float(r.get("cpi_food_yoy_pct", 5.0)),
        iip_growth_yoy_pct=float(r.get("iip_growth_yoy_pct", 4.0)),
        gva_growth_yoy_pct=float(r.get("gva_growth_yoy_pct", 6.0)),
        output_gap_pct=float(r.get("output_gap_pct", 0.0)),
        system_liquidity_cr=float(r.get("system_liquidity_cr", -10000.0)),
        usd_inr_exchange_rate=float(r.get("usd_inr_exchange_rate", 82.0)),
        brent_crude_usd_bbl=float(r.get("brent_crude_usd_bbl", 85.0)),
        us_fed_funds_rate_pct=float(r.get("us_fed_funds_rate_pct", 5.0)),
        monsoon_departure_lpa_pct=float(r.get("monsoon_departure_lpa_pct", 0.0)),
        prev_stance=str(r["prev_stance"]),
    )


async def run_phase_7_and_8():
    logger.info("Initializing Phase 7 & 8: Counterfactuals & Attribution Layer...")
    results_dir = PROJECT_ROOT / "results" / "tables"
    results_dir.mkdir(parents=True, exist_ok=True)

    personas = load_all_personas()
    gov_id = "shaktikanta_das"
    taylor_rule = SmoothedTaylorRule()
    scenario_runner = ScenarioRunner(taylor_rule=taylor_rule)
    member_params = [MEMBER_TAYLOR_PARAMS[p.member_id] for p in personas]

    # Initialize Debate Orchestrator
    client = LLMClient()
    orchestrator = DebateOrchestrator(llm_client=client)

    # =========================================================================
    # PHASE 7: COUNTERFACTUAL SCENARIO EXPERIMENTS
    # =========================================================================
    logger.info("--- Executing Phase 7: Counterfactual Scenario Experiments ---")
    scenario_records = []

    # Scenario 1: Monsoon Failure & Food Inflation Surge (Anchored to 2023-08-10)
    snap_monsoon_base = load_meeting_snapshot("2023-08-10")
    snap_monsoon_shock = ScenarioRunner.build_monsoon_food_shock_snapshot(
        snap_monsoon_base, food_cpi_shock_pct=4.0, monsoon_departure_pct=-20.0
    )

    # Rational Track
    rat_monsoon = scenario_runner.run_monsoon_food_shock(snap_monsoon_base, member_params, gov_id)

    # Behavioral Track
    logger.info("Running Behavioral Deliberation Track on Monsoon Shock (2023-08-10)...")
    beh_monsoon_base = await orchestrator.run_meeting(snap_monsoon_base, personas, gov_id, replicate_id=1)
    beh_monsoon_shock = await orchestrator.run_meeting(snap_monsoon_shock, personas, gov_id, replicate_id=1)

    wedge_monsoon_base = beh_monsoon_base.rate_decision_bps - rat_monsoon.baseline_repo_rate_change_bps
    wedge_monsoon_shock = beh_monsoon_shock.rate_decision_bps - rat_monsoon.shocked_repo_rate_change_bps

    scenario_records.append({
        "scenario_id": "SCENARIO_1_MONSOON_FOOD",
        "scenario_name": "Monsoon Failure & Vegetable Price Surge",
        "anchor_meeting_date": "2023-08-10",
        "rational_baseline_rate_bps": rat_monsoon.baseline_repo_rate_change_bps,
        "rational_shocked_rate_bps": rat_monsoon.shocked_repo_rate_change_bps,
        "rational_rate_delta_bps": rat_monsoon.rate_wedge_bps,
        "rational_baseline_stance": rat_monsoon.baseline_stance,
        "rational_shocked_stance": rat_monsoon.shocked_stance,
        "behavioral_baseline_rate_bps": beh_monsoon_base.rate_decision_bps,
        "behavioral_shocked_rate_bps": beh_monsoon_shock.rate_decision_bps,
        "behavioral_rate_delta_bps": beh_monsoon_shock.rate_decision_bps - beh_monsoon_base.rate_decision_bps,
        "behavioral_baseline_stance": beh_monsoon_base.stance_decision,
        "behavioral_shocked_stance": beh_monsoon_shock.stance_decision,
        "policy_rate_wedge_baseline_bps": wedge_monsoon_base,
        "policy_rate_wedge_shocked_bps": wedge_monsoon_shock,
        "shocked_dissenters_behavioral": ";".join(beh_monsoon_shock.dissenting_members_rate + beh_monsoon_shock.dissenting_members_stance),
    })

    # Scenario 2: US Federal Reserve Spillover Shock (Anchored to 2022-08-05)
    snap_fed_base = load_meeting_snapshot("2022-08-05")
    snap_fed_shock = ScenarioRunner.build_us_fed_spillover_snapshot(
        snap_fed_base, fed_hike_bps=75, inr_depreciation=1.50
    )

    rat_fed = scenario_runner.run_us_fed_spillover_shock(snap_fed_base, member_params, gov_id)

    logger.info("Running Behavioral Deliberation Track on US Fed Shock (2022-08-05)...")
    beh_fed_base = await orchestrator.run_meeting(snap_fed_base, personas, gov_id, replicate_id=1)
    beh_fed_shock = await orchestrator.run_meeting(snap_fed_shock, personas, gov_id, replicate_id=1)

    wedge_fed_base = beh_fed_base.rate_decision_bps - rat_fed.baseline_repo_rate_change_bps
    wedge_fed_shock = beh_fed_shock.rate_decision_bps - rat_fed.shocked_repo_rate_change_bps

    scenario_records.append({
        "scenario_id": "SCENARIO_2_US_FED_SPILLOVER",
        "scenario_name": "US Federal Reserve External Tightening (+75 bps)",
        "anchor_meeting_date": "2022-08-05",
        "rational_baseline_rate_bps": rat_fed.baseline_repo_rate_change_bps,
        "rational_shocked_rate_bps": rat_fed.shocked_repo_rate_change_bps,
        "rational_rate_delta_bps": rat_fed.rate_wedge_bps,
        "rational_baseline_stance": rat_fed.baseline_stance,
        "rational_shocked_stance": rat_fed.shocked_stance,
        "behavioral_baseline_rate_bps": beh_fed_base.rate_decision_bps,
        "behavioral_shocked_rate_bps": beh_fed_shock.rate_decision_bps,
        "behavioral_rate_delta_bps": beh_fed_shock.rate_decision_bps - beh_fed_base.rate_decision_bps,
        "behavioral_baseline_stance": beh_fed_base.stance_decision,
        "behavioral_shocked_stance": beh_fed_shock.stance_decision,
        "policy_rate_wedge_baseline_bps": wedge_fed_base,
        "policy_rate_wedge_shocked_bps": wedge_fed_shock,
        "shocked_dissenters_behavioral": ";".join(beh_fed_shock.dissenting_members_rate + beh_fed_shock.dissenting_members_stance),
    })

    # Scenario 3: 2020 Pandemic Easing Cycle (OOD Stress Test)
    snap_pandemic_base = load_meeting_snapshot("2020-10-09")
    snap_pandemic_shock = ScenarioRunner.build_pandemic_easing_snapshot(snap_pandemic_base)

    rat_pandemic = scenario_runner.run_pandemic_easing_shock(snap_pandemic_base, member_params, gov_id)

    logger.info("Running Behavioral Deliberation Track on Pandemic Easing Shock...")
    beh_pandemic_base = await orchestrator.run_meeting(snap_pandemic_base, personas, gov_id, replicate_id=1)
    beh_pandemic_shock = await orchestrator.run_meeting(snap_pandemic_shock, personas, gov_id, replicate_id=1)

    wedge_pandemic_base = beh_pandemic_base.rate_decision_bps - rat_pandemic.baseline_repo_rate_change_bps
    wedge_pandemic_shock = beh_pandemic_shock.rate_decision_bps - rat_pandemic.shocked_repo_rate_change_bps

    scenario_records.append({
        "scenario_id": "SCENARIO_3_PANDEMIC_EASING",
        "scenario_name": "2020 Pandemic Easing Cycle (OOD Stress Test)",
        "anchor_meeting_date": "2020-10-09",
        "rational_baseline_rate_bps": rat_pandemic.baseline_repo_rate_change_bps,
        "rational_shocked_rate_bps": rat_pandemic.shocked_repo_rate_change_bps,
        "rational_rate_delta_bps": rat_pandemic.rate_wedge_bps,
        "rational_baseline_stance": rat_pandemic.baseline_stance,
        "rational_shocked_stance": rat_pandemic.shocked_stance,
        "behavioral_baseline_rate_bps": beh_pandemic_base.rate_decision_bps,
        "behavioral_shocked_rate_bps": beh_pandemic_shock.rate_decision_bps,
        "behavioral_rate_delta_bps": beh_pandemic_shock.rate_decision_bps - beh_pandemic_base.rate_decision_bps,
        "behavioral_baseline_stance": beh_pandemic_base.stance_decision,
        "behavioral_shocked_stance": beh_pandemic_shock.stance_decision,
        "policy_rate_wedge_baseline_bps": wedge_pandemic_base,
        "policy_rate_wedge_shocked_bps": wedge_pandemic_shock,
        "shocked_dissenters_behavioral": ";".join(beh_pandemic_shock.dissenting_members_rate + beh_pandemic_shock.dissenting_members_stance),
    })

    # Scenario 4: 2013 Taper Tantrum Crisis (OOD Stress Test)
    snap_taper_base = load_meeting_snapshot("2022-08-05")
    snap_taper_shock = ScenarioRunner.build_taper_tantrum_snapshot(snap_taper_base)

    rat_taper = scenario_runner.run_taper_tantrum_shock(snap_taper_base, member_params, gov_id)

    logger.info("Running Behavioral Deliberation Track on Taper Tantrum Shock...")
    beh_taper_base = await orchestrator.run_meeting(snap_taper_base, personas, gov_id, replicate_id=1)
    beh_taper_shock = await orchestrator.run_meeting(snap_taper_shock, personas, gov_id, replicate_id=1)

    wedge_taper_base = beh_taper_base.rate_decision_bps - rat_taper.baseline_repo_rate_change_bps
    wedge_taper_shock = beh_taper_shock.rate_decision_bps - rat_taper.shocked_repo_rate_change_bps

    scenario_records.append({
        "scenario_id": "SCENARIO_4_TAPER_TANTRUM",
        "scenario_name": "2013 Taper Tantrum Crisis (OOD Stress Test)",
        "anchor_meeting_date": "2022-08-05",
        "rational_baseline_rate_bps": rat_taper.baseline_repo_rate_change_bps,
        "rational_shocked_rate_bps": rat_taper.shocked_repo_rate_change_bps,
        "rational_rate_delta_bps": rat_taper.rate_wedge_bps,
        "rational_baseline_stance": rat_taper.baseline_stance,
        "rational_shocked_stance": rat_taper.shocked_stance,
        "behavioral_baseline_rate_bps": beh_taper_base.rate_decision_bps,
        "behavioral_shocked_rate_bps": beh_taper_shock.rate_decision_bps,
        "behavioral_rate_delta_bps": beh_taper_shock.rate_decision_bps - beh_taper_base.rate_decision_bps,
        "behavioral_baseline_stance": beh_taper_base.stance_decision,
        "behavioral_shocked_stance": beh_taper_shock.stance_decision,
        "policy_rate_wedge_baseline_bps": wedge_taper_base,
        "policy_rate_wedge_shocked_bps": wedge_taper_shock,
        "shocked_dissenters_behavioral": ";".join(beh_taper_shock.dissenting_members_rate + beh_taper_shock.dissenting_members_stance),
    })

    df_scenarios = pd.DataFrame(scenario_records)
    table3_path = results_dir / "table3_counterfactual_shock_responses.csv"
    df_scenarios.to_csv(table3_path, index=False)
    logger.info("Saved Phase 7 Counterfactual Results to %s", table3_path)

    # =========================================================================
    # PHASE 8: INTERACTION-LEVEL ATTRIBUTION LAYER
    # =========================================================================
    logger.info("--- Executing Phase 8: Interaction-Level Attribution Layer ---")
    attribution_records = []

    # Anchor on 2023-08-10 baseline decision
    anchor_snap = snap_monsoon_base
    anchor_decision = beh_monsoon_base

    # Experiment 1A: Leave-One-Out Persuasion Ablation (Withhold Jayanth Varma)
    logger.info("Running Experiment 1A: Leave-One-Out (Withhold Jayanth Varma)...")
    res_ablate_varma = await AttributionRunner.run_leave_one_out_ablation(
        orchestrator=orchestrator,
        baseline_decision=anchor_decision,
        snapshot=anchor_snap,
        personas=personas,
        governor_id=gov_id,
        ablated_member_id="jayanth_varma",
    )
    attribution_records.append(res_ablate_varma.__dict__)

    # Experiment 1B: Leave-One-Out Persuasion Ablation (Withhold Michael Patra)
    logger.info("Running Experiment 1B: Leave-One-Out (Withhold Michael Patra)...")
    res_ablate_patra = await AttributionRunner.run_leave_one_out_ablation(
        orchestrator=orchestrator,
        baseline_decision=anchor_decision,
        snapshot=anchor_snap,
        personas=personas,
        governor_id=gov_id,
        ablated_member_id="michael_patra",
    )
    attribution_records.append(res_ablate_patra.__dict__)

    # Experiment 2: Statutory Casting-Vote Ablation (§45ZL)
    logger.info("Running Experiment 2: Statutory Casting-Vote Ablation (§45ZL)...")
    # 2A. Untied Baseline Meeting (Casting vote dormant)
    res_casting_untied = AttributionRunner.ablate_casting_vote(
        meeting_outcome=anchor_decision,
        governor_id=gov_id,
    )
    res_casting_untied.experiment_id = "EXP_2_CASTING_VOTE_UNTIED"
    res_casting_untied.experiment_name = "Governor Casting-Vote Ablation (Untied Baseline Meeting)"
    res_casting_untied.description = "Evaluates casting vote on baseline meeting where majority was already established; casting vote is dormant."
    attribution_records.append(res_casting_untied.__dict__)

    # 2B. Statutory Equality of Votes (3-3 Tie Split under §45ZL)
    from src.schemas.debate_schema import MeetingCommitteeDecision
    tie_split_decision = MeetingCommitteeDecision(
        meeting_date=anchor_snap.meeting_date,
        replicate_id=1,
        rate_decision_bps=0,
        stance_decision="withdrawal_of_accommodation",
        rate_vote_tally={0: 3, 25: 3},
        stance_vote_tally={"withdrawal_of_accommodation": 3, "neutral": 3},
        tie_broken_by_governor_rate=True,
        tie_broken_by_governor_stance=True,
        dissenting_members_rate=["michael_patra", "rajiv_ranjan", "shashanka_bhide"],
        dissenting_members_stance=["jayanth_varma", "ashima_goyal", "shashanka_bhide"],
        member_votes=[],
    )
    res_casting_tie = AttributionRunner.ablate_casting_vote(
        meeting_outcome=tie_split_decision,
        governor_id=gov_id,
    )
    res_casting_tie.experiment_id = "EXP_2_CASTING_VOTE_TIE_SPLIT"
    res_casting_tie.experiment_name = "Governor Statutory Casting-Vote Ablation (3-3 Tie Split under §45ZL)"
    res_casting_tie.description = "Evaluates whether Governor casting vote breaks a 3-3 equality of votes; without casting vote, motion fails to reach majority."
    attribution_records.append(res_casting_tie.__dict__)

    # Experiment 3A: Macro-Factor Muting (Neutralize Food Inflation)
    logger.info("Running Experiment 3A: Macro Muting (Food Inflation)...")
    res_mute_food = await AttributionRunner.run_macro_muting_ablation(
        orchestrator=orchestrator,
        baseline_decision=anchor_decision,
        snapshot=anchor_snap,
        personas=personas,
        governor_id=gov_id,
        muted_factor="food_inflation",
    )
    attribution_records.append(res_mute_food.__dict__)

    # Experiment 3B: Macro-Factor Muting (Neutralize Monsoon Deficit)
    logger.info("Running Experiment 3B: Macro Muting (Monsoon Departure)...")
    res_mute_monsoon = await AttributionRunner.run_macro_muting_ablation(
        orchestrator=orchestrator,
        baseline_decision=anchor_decision,
        snapshot=anchor_snap,
        personas=personas,
        governor_id=gov_id,
        muted_factor="monsoon",
    )
    attribution_records.append(res_mute_monsoon.__dict__)

    df_attribution = pd.DataFrame(attribution_records)
    table4_path = results_dir / "table4_attribution_ablation_effects.csv"
    df_attribution.to_csv(table4_path, index=False)
    logger.info("Saved Phase 8 Attribution Results to %s", table4_path)

    print("\n" + "=" * 78)
    print("PHASES 7 & 8 EXECUTION COMPLETE")
    print("=" * 78)
    print(f"Table 3 (Counterfactual Shocks): {table3_path}")
    print(f"Table 4 (Attribution Ablations):  {table4_path}")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(run_phase_7_and_8())
