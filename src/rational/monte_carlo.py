"""
Monte Carlo Simulation Engine for the Rational Benchmark Track.
Perturbs macroeconomic observations with calibrated Gaussian noise across N=1,000 draws
and aggregates member votes through the statutory InstitutionalRuleEngine.
Incorporates defensive numerical guards, NaN/None handling, and bounds checking.
"""

import numpy as np
import logging
from typing import Sequence, Optional
from dataclasses import dataclass

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.rule_engine.engine import InstitutionalRuleEngine

logger = logging.getLogger("rbi_mpc.monte_carlo")


@dataclass
class MonteCarloResult:
    meeting_date: str
    mean_implied_rate: float
    modal_rate_decision_bps: int
    modal_stance_decision: str
    rate_distribution_pct: dict[int, float]
    stance_distribution_pct: dict[str, float]
    dissent_probability_by_member: dict[str, float]


class MonteCarloEngine:
    """Orchestrates noisy Monte Carlo draws and statistical aggregation with defensive validation."""

    def __init__(
        self,
        taylor_rule: SmoothedTaylorRule,
        n_draws: int = 1000,
        noise_std_pct: float = 0.20,
        seed: int = 42,
    ):
        self.rule = taylor_rule
        self.n_draws = n_draws
        self.noise_std = noise_std_pct
        self.seed = seed

    def simulate(
        self,
        snapshot: MacroMeetingSnapshot,
        member_params: Sequence[MemberTaylorParameters],
        governor_id: str = "shaktikanta_das",
    ) -> MonteCarloResult:
        """
        Simulates n_draws macroeconomic perturbations and aggregates decisions via §45ZL rule.
        Defensively handles missing/None variables and prevents numerical overflow.
        """
        if len(member_params) != 6:
            raise ValueError(f"Monte Carlo simulation requires exactly 6 members; got {len(member_params)}")

        rng = np.random.default_rng(self.seed)

        # Defensive fallback for optional macro variables
        base_cpi = snapshot.cpi_headline_yoy_pct if snapshot.cpi_headline_yoy_pct is not None else 4.0
        base_gap = snapshot.output_gap_pct if snapshot.output_gap_pct is not None else 0.0
        base_us = snapshot.us_fed_funds_rate_pct if snapshot.us_fed_funds_rate_pct is not None else 5.0

        # Generate perturbation vectors
        cpi_noise = rng.normal(0.0, self.noise_std, self.n_draws)
        gap_noise = rng.normal(0.0, self.noise_std * 1.5, self.n_draws)
        us_noise = rng.normal(0.0, self.noise_std * 0.5, self.n_draws)

        rate_decisions: list[int] = []
        stance_decisions: list[str] = []
        member_dissents: dict[str, int] = {p.member_id: 0 for p in member_params}
        continuous_rates: list[float] = []

        for i in range(self.n_draws):
            # Noisy snapshot with clamped bounds
            perturbed_cpi = float(np.clip(base_cpi + cpi_noise[i], 0.0, 25.0))
            perturbed_gap = float(np.clip(base_gap + gap_noise[i], -10.0, 10.0))
            perturbed_us = float(np.clip(base_us + us_noise[i], 0.0, 20.0))

            noisy_snap = MacroMeetingSnapshot(
                meeting_date=snapshot.meeting_date,
                current_repo_rate_pct=snapshot.current_repo_rate_pct,
                cpi_headline_yoy_pct=perturbed_cpi,
                cpi_core_yoy_pct=snapshot.cpi_core_yoy_pct,
                cpi_food_yoy_pct=snapshot.cpi_food_yoy_pct,
                iip_growth_yoy_pct=snapshot.iip_growth_yoy_pct,
                gva_growth_yoy_pct=snapshot.gva_growth_yoy_pct,
                output_gap_pct=perturbed_gap,
                system_liquidity_cr=snapshot.system_liquidity_cr,
                usd_inr_exchange_rate=snapshot.usd_inr_exchange_rate,
                brent_crude_usd_bbl=snapshot.brent_crude_usd_bbl,
                us_fed_funds_rate_pct=perturbed_us,
                monsoon_departure_lpa_pct=snapshot.monsoon_departure_lpa_pct,
                prev_stance=snapshot.prev_stance,
            )

            member_rate_votes: dict[str, int] = {}
            member_stance_votes: dict[str, str] = {}

            for p in member_params:
                r_vote, s_vote = self.rule.compute_discrete_action(noisy_snap, p)
                member_rate_votes[p.member_id] = r_vote
                member_stance_votes[p.member_id] = s_vote
                continuous_rates.append(self.rule.compute_continuous_rate(noisy_snap, p))

            # Aggregate through institutional rule engine (§45ZL)
            rate_res = InstitutionalRuleEngine.aggregate_rate_votes(
                member_rate_votes, governor_id=governor_id, valid_actions=self.rule.action_set_bps
            )
            stance_res = InstitutionalRuleEngine.aggregate_stance_votes(
                member_stance_votes, governor_id=governor_id
            )

            rate_decisions.append(rate_res.winning_action)
            stance_decisions.append(stance_res.winning_action)

            for dissenter in rate_res.dissenting_members:
                member_dissents[dissenter] += 1

        # Calculate empirical distributions
        rate_tally: dict[int, int] = {}
        for r in rate_decisions:
            rate_tally[r] = rate_tally.get(r, 0) + 1
        rate_dist = {k: round(v / self.n_draws * 100.0, 2) for k, v in sorted(rate_tally.items())}
        modal_rate = max(rate_tally.items(), key=lambda x: x[1])[0]

        stance_tally: dict[str, int] = {}
        for s in stance_decisions:
            stance_tally[s] = stance_tally.get(s, 0) + 1
        stance_dist = {k: round(v / self.n_draws * 100.0, 2) for k, v in sorted(stance_tally.items())}
        modal_stance = max(stance_tally.items(), key=lambda x: x[1])[0]

        dissent_probs = {k: round(v / self.n_draws, 3) for k, v in member_dissents.items()}

        return MonteCarloResult(
            meeting_date=snapshot.meeting_date,
            mean_implied_rate=float(np.mean(continuous_rates)),
            modal_rate_decision_bps=modal_rate,
            modal_stance_decision=modal_stance,
            rate_distribution_pct=rate_dist,
            stance_distribution_pct=stance_dist,
            dissent_probability_by_member=dissent_probs,
        )
