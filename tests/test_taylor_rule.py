"""
Unit tests for the Rational Track (Taylor Rule and Monte Carlo simulation).
"""

import pytest
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.rational.monte_carlo import MonteCarloEngine


@pytest.fixture
def sample_snapshot():
    return MacroMeetingSnapshot(
        meeting_date="2023-08-10",
        current_repo_rate_pct=6.50,
        cpi_headline_yoy_pct=4.80,
        cpi_core_yoy_pct=4.20,
        cpi_food_yoy_pct=6.10,
        iip_growth_yoy_pct=4.50,
        gva_growth_yoy_pct=7.80,
        output_gap_pct=0.20,
        system_liquidity_cr=-25000.0,
        usd_inr_exchange_rate=82.80,
        brent_crude_usd_bbl=85.50,
        us_fed_funds_rate_pct=5.50,
        monsoon_departure_lpa_pct=-5.0,
        prev_stance="withdrawal_of_accommodation",
    )


def test_taylor_rule_continuous_computation(sample_snapshot):
    rule = SmoothedTaylorRule(
        r_star_pct=1.4,
        pi_star_pct=4.0,
        smoothing_rho=0.75,
        us_neutral_rate_pct=2.5,
    )
    params = MemberTaylorParameters(member_id="michael_patra", alpha=1.8, beta=0.6, gamma=0.3)

    # Inflation gap = 4.8 - 4.0 = 0.8
    # Output gap = 0.2
    # US rate gap = 5.5 - 2.5 = 3.0
    # target = 1.4 + 4.8 + 1.8*(0.8) + 0.6*(0.2) + 0.3*(3.0) = 6.2 + 1.44 + 0.12 + 0.90 = 8.66%
    # smoothed = 0.75 * 6.50 + 0.25 * 8.66 = 4.875 + 2.165 = 7.04%
    continuous_rate = rule.compute_continuous_rate(sample_snapshot, params)
    assert round(continuous_rate, 2) == 7.04

    # Discretized change = (7.04 - 6.50) * 100 = +54 bps -> closest action is +50 bps
    action_bps, stance = rule.compute_discrete_action(sample_snapshot, params)
    assert action_bps == 50
    assert stance == "withdrawal_of_accommodation"


def test_dovish_member_taylor_action(sample_snapshot):
    rule = SmoothedTaylorRule(
        r_star_pct=1.4,
        pi_star_pct=4.0,
        smoothing_rho=0.75,
    )
    # Dovish member: lower alpha, higher focus on potential output
    params = MemberTaylorParameters(member_id="jayanth_varma", alpha=0.5, beta=0.2, gamma=0.0)
    continuous_rate = rule.compute_continuous_rate(sample_snapshot, params)
    action_bps, stance = rule.compute_discrete_action(sample_snapshot, params)
    # Dovish member should prefer a lower or unchanged rate
    assert action_bps <= 25


def test_monte_carlo_engine(sample_snapshot):
    rule = SmoothedTaylorRule()
    members = [
        MemberTaylorParameters("shaktikanta_das", alpha=1.2, beta=0.4),
        MemberTaylorParameters("michael_patra", alpha=1.8, beta=0.6),
        MemberTaylorParameters("rajiv_ranjan", alpha=1.4, beta=0.5),
        MemberTaylorParameters("jayanth_varma", alpha=0.5, beta=0.2),
        MemberTaylorParameters("ashima_goyal", alpha=0.8, beta=0.3),
        MemberTaylorParameters("shashanka_bhide", alpha=1.3, beta=0.4),
    ]

    engine = MonteCarloEngine(taylor_rule=rule, n_draws=100, noise_std_pct=0.15, seed=123)
    result = engine.simulate(sample_snapshot, members, governor_id="shaktikanta_das")

    assert result.modal_rate_decision_bps in [-50, -25, 0, 25, 50]
    assert result.modal_stance_decision in ["withdrawal_of_accommodation", "neutral", "accommodative"]
    assert sum(result.rate_distribution_pct.values()) == pytest.approx(100.0, rel=1e-2)
    assert "jayanth_varma" in result.dissent_probability_by_member
