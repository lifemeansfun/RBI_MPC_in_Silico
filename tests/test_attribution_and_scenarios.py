"""
Unit and integration tests for Validation Metrics, Counterfactual Scenarios,
Attribution Experiments, and Report Generation.
"""

import pytest
import tempfile
from pathlib import Path

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.schemas.debate_schema import MeetingCommitteeDecision, FinalVoteOutput
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.validation.metrics import MetricsEvaluator
from src.scenarios.scenario_runner import ScenarioRunner
from src.attribution.attribution_runner import AttributionRunner
from src.reporting.report_builder import ReportBuilder


@pytest.fixture
def baseline_snapshot():
    return MacroMeetingSnapshot(
        meeting_date="2023-08-10",
        current_repo_rate_pct=6.50,
        cpi_headline_yoy_pct=4.80,
        cpi_core_yoy_pct=4.20,
        cpi_food_yoy_pct=5.50,
        iip_growth_yoy_pct=4.50,
        output_gap_pct=0.20,
        system_liquidity_cr=-20000.0,
        usd_inr_exchange_rate=82.80,
        brent_crude_usd_bbl=85.00,
        us_fed_funds_rate_pct=5.50,
        monsoon_departure_lpa_pct=0.0,
        prev_stance="withdrawal_of_accommodation",
    )


def test_metrics_evaluator():
    sim_rates = [0, 0, 25, 0]
    true_rates = [0, 0, 25, 0]
    sim_stances = ["withdrawal_of_accommodation", "neutral", "withdrawal_of_accommodation", "withdrawal_of_accommodation"]
    true_stances = ["withdrawal_of_accommodation", "neutral", "withdrawal_of_accommodation", "withdrawal_of_accommodation"]
    pred_dissents = [["jayanth_varma"], ["jayanth_varma", "ashima_goyal"], [], ["jayanth_varma"]]
    true_dissents = [["jayanth_varma"], ["jayanth_varma", "ashima_goyal"], [], ["jayanth_varma"]]

    summary = MetricsEvaluator.evaluate_panel(
        simulated_rate_actions=sim_rates,
        ground_truth_rate_actions=true_rates,
        simulated_stances=sim_stances,
        ground_truth_stances=true_stances,
        predicted_dissenters=pred_dissents,
        ground_truth_dissenters=true_dissents,
        predicted_rate_dissenters=[["jayanth_varma"], ["jayanth_varma"], [], ["jayanth_varma"]],
        true_rate_dissenters=[["jayanth_varma"], ["jayanth_varma"], [], ["jayanth_varma"]],
        predicted_stance_dissenters=[[], ["ashima_goyal"], [], []],
        true_stance_dissenters=[[], ["ashima_goyal"], [], []],
    )

    assert summary.directional_rate_accuracy_pct == 100.0
    assert summary.stance_accuracy_pct == 100.0
    assert summary.dissent_f1 == 1.0
    assert summary.dissent_exact_match_rate_pct == 100.0
    assert summary.passed_validation_gate is True


def test_scenario_runner(baseline_snapshot):
    rule = SmoothedTaylorRule()
    members = [
        MemberTaylorParameters("shaktikanta_das", alpha=1.2, beta=0.4),
        MemberTaylorParameters("michael_patra", alpha=1.8, beta=0.6),
        MemberTaylorParameters("rajiv_ranjan", alpha=1.4, beta=0.5),
        MemberTaylorParameters("jayanth_varma", alpha=0.5, beta=0.2),
        MemberTaylorParameters("ashima_goyal", alpha=0.8, beta=0.3),
        MemberTaylorParameters("shashanka_bhide", alpha=1.3, beta=0.4),
    ]

    # This legacy fixture tests shock arithmetic under an explicit synthetic resolver.
    runner = ScenarioRunner(taylor_rule=rule, fragmentation_policy='legacy_synthetic')
    monsoon_res = runner.run_monsoon_food_shock(baseline_snapshot, members, "shaktikanta_das")
    assert monsoon_res.scenario_name == "Monsoon Failure & Food Inflation Shock"
    assert monsoon_res.shocked_repo_rate_change_bps >= monsoon_res.baseline_repo_rate_change_bps

    fed_res = runner.run_us_fed_spillover_shock(baseline_snapshot, members, "shaktikanta_das")
    assert "US Federal Reserve" in fed_res.scenario_name


def test_attribution_runner(baseline_snapshot):
    # Test casting vote ablation on a simulated 3-3 tie
    decision = MeetingCommitteeDecision(
        meeting_date="2023-08-10",
        replicate_id=1,
        rate_decision_bps=25,
        stance_decision="withdrawal_of_accommodation",
        rate_vote_tally={25: 3, 0: 3},
        stance_vote_tally={"withdrawal_of_accommodation": 3, "neutral": 3},
        tie_broken_by_governor_rate=True,
        tie_broken_by_governor_stance=True,
        dissenting_members_rate=["jayanth_varma", "ashima_goyal", "shashanka_bhide"],
        dissenting_members_stance=["jayanth_varma", "ashima_goyal", "shashanka_bhide"],
        member_votes=[],
        prior_stance=baseline_snapshot.prev_stance,
    )

    attr_res = AttributionRunner.ablate_casting_vote(decision, governor_id="shaktikanta_das")
    assert attr_res.outcome_shifted is True
    assert attr_res.ablated_decision_bps == 0
    assert attr_res.marginal_contribution_bps == 25

    # Test macro input muting
    muted = AttributionRunner.mute_macro_input(baseline_snapshot, "monsoon")
    assert muted.monsoon_departure_lpa_pct == 0.0


def test_report_builder():
    with tempfile.TemporaryDirectory() as tmpdir:
        builder = ReportBuilder(output_dir=Path(tmpdir))

        val_summary = {
            "directional_rate_accuracy_pct": 88.9,
            "stance_accuracy_pct": 83.3,
            "dissent_precision": 0.85,
            "dissent_recall": 0.80,
            "dissent_f1": 0.82,
            "passed_validation_gate": True,
        }
        scenarios = [
            {
                "scenario_name": "Monsoon Failure",
                "baseline_rate_bps": 0,
                "shocked_rate_bps": 25,
                "rate_wedge_bps": 25,
                "baseline_stance": "withdrawal_of_accommodation",
                "shocked_stance": "withdrawal_of_accommodation",
            }
        ]
        attributions = [
            {
                "experiment_name": "Casting Vote Ablation",
                "baseline_decision_bps": 25,
                "ablated_decision_bps": 0,
                "marginal_contribution_bps": 25,
                "outcome_shifted": True,
            }
        ]

        t1 = builder.save_validation_table(val_summary)
        t2 = builder.save_counterfactual_table(scenarios)
        t3 = builder.save_attribution_table(attributions)
        report_file = builder.generate_markdown_report(val_summary, scenarios, attributions)

        assert t1.exists()
        assert t2.exists()
        assert t3.exists()
        assert report_file.exists()
        report_text = report_file.read_text(encoding="utf-8")
        assert "Configured numerical thresholds:** met" in report_text
        assert "PASSED" not in report_text
        assert "does not authenticate" in report_text
        assert "No scientific verdict is issued here" in report_text


def test_scenario_snapshot_builders(baseline_snapshot):
    # Test Monsoon & Food Shock snapshot builder
    monsoon_snap = ScenarioRunner.build_monsoon_food_shock_snapshot(
        baseline_snapshot, food_cpi_shock_pct=4.0, monsoon_departure_pct=-20.0
    )
    assert monsoon_snap.cpi_food_yoy_pct == baseline_snapshot.cpi_food_yoy_pct + 4.0
    expected_headline_delta = 4.0 * 0.458
    assert abs(monsoon_snap.cpi_headline_yoy_pct - (baseline_snapshot.cpi_headline_yoy_pct + expected_headline_delta)) < 1e-5
    assert monsoon_snap.monsoon_departure_lpa_pct == -20.0
    assert monsoon_snap.iip_growth_yoy_pct == baseline_snapshot.iip_growth_yoy_pct - 0.5

    # Test US Fed Spillover snapshot builder
    fed_snap = ScenarioRunner.build_us_fed_spillover_snapshot(
        baseline_snapshot, fed_hike_bps=75, inr_depreciation=1.50
    )
    assert fed_snap.us_fed_funds_rate_pct == baseline_snapshot.us_fed_funds_rate_pct + 0.75
    assert fed_snap.usd_inr_exchange_rate == baseline_snapshot.usd_inr_exchange_rate + 1.50
    assert fed_snap.system_liquidity_cr == baseline_snapshot.system_liquidity_cr - 30000.0


@pytest.mark.asyncio
async def test_async_attribution_runner_mock(baseline_snapshot):
    from src.behavioral.debate_orchestrator import DebateOrchestrator
    from src.infra.llm_client import LLMClient
    from src.infra.transcript_logger import TranscriptLogger

    personas = [
        MemberPersona(
            member_id="shaktikanta_das", name="Shaktikanta Das", role="Governor",
            is_internal=True, tenure="2018-present", hawk_dove_score=0.1, voting_priority="Consensus"
        ),
        MemberPersona(
            member_id="michael_patra", name="Michael Patra", role="Deputy Governor",
            is_internal=True, tenure="2020-present", hawk_dove_score=0.75, voting_priority="Inflation hawk"
        ),
        MemberPersona(
            member_id="rajiv_ranjan", name="Rajiv Ranjan", role="Executive Director",
            is_internal=True, tenure="2022-present", hawk_dove_score=0.35, voting_priority="Liquidity"
        ),
        MemberPersona(
            member_id="jayanth_varma", name="Jayanth R. Varma", role="External Member",
            is_internal=False, tenure="2020-2024", hawk_dove_score=-0.60, voting_priority="Growth"
        ),
        MemberPersona(
            member_id="ashima_goyal", name="Ashima Goyal", role="External Member",
            is_internal=False, tenure="2020-2024", hawk_dove_score=-0.25, voting_priority="Pragmatic"
        ),
        MemberPersona(
            member_id="shashanka_bhide", name="Shashanka Bhide", role="External Member",
            is_internal=False, tenure="2020-2024", hawk_dove_score=0.15, voting_priority="Agriculture"
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        client = LLMClient(provider="mock", cache_enabled=False)
        logger = TranscriptLogger(run_id="test_mock_run", output_root=Path(tmpdir))
        orchestrator = DebateOrchestrator(llm_client=client, logger=logger)

        base_decision = await orchestrator.run_meeting(
            snapshot=baseline_snapshot, personas=personas, governor_id="shaktikanta_das"
        )
        assert base_decision is not None

        # Test Leave-One-Out Ablation
        res_loo = await AttributionRunner.run_leave_one_out_ablation(
            orchestrator=orchestrator,
            baseline_decision=base_decision,
            snapshot=baseline_snapshot,
            personas=personas,
            governor_id="shaktikanta_das",
            ablated_member_id="jayanth_varma",
        )
        assert res_loo.experiment_id == "EXP_1_LEAVE_OUT_JAYANTH_VARMA"
        assert isinstance(res_loo.outcome_shifted, bool)

        # Test Macro Muting Ablation
        res_mute = await AttributionRunner.run_macro_muting_ablation(
            orchestrator=orchestrator,
            baseline_decision=base_decision,
            snapshot=baseline_snapshot,
            personas=personas,
            governor_id="shaktikanta_das",
            muted_factor="food_inflation",
        )
        assert res_mute.experiment_id == "EXP_3_MUTE_FOOD_INFLATION"
        assert isinstance(res_mute.marginal_contribution_bps, int)
