"""
Open-Economy Smoothed Taylor Rule Engine for the Rational Benchmark Track.
Calculates implied nominal policy rate with central bank interest-rate inertia,
inflation gap, output gap, and external US Federal Reserve interest rate differential.
"""

from dataclasses import dataclass
from typing import Sequence
from src.schemas.macro_schema import MacroMeetingSnapshot


@dataclass
class MemberTaylorParameters:
    """Calibrated Taylor rule coefficients for an individual committee member."""
    member_id: str
    alpha: float = 1.5   # Inflation gap sensitivity
    beta: float = 0.5    # Output gap sensitivity
    gamma: float = 0.2   # US Fed rate differential sensitivity


class SmoothedTaylorRule:
    """
    Implements:
    r*_t = r_star + pi_t + alpha_i * (pi_t - pi_target) + beta_i * output_gap + gamma_i * (i_us - i_us_target)
    r_t = rho * r_{t-1} + (1 - rho) * r*_t
    """

    def __init__(
        self,
        r_star_pct: float = 1.4,
        pi_star_pct: float = 4.0,
        smoothing_rho: float = 0.75,
        us_neutral_rate_pct: float = 2.5,
        action_set_bps: Sequence[int] = (-50, -25, 0, 25, 50),
    ):
        self.r_star = r_star_pct
        self.pi_star = pi_star_pct
        self.rho = smoothing_rho
        self.us_neutral_rate = us_neutral_rate_pct
        self.action_set_bps = action_set_bps

    def compute_continuous_rate(
        self,
        snapshot: MacroMeetingSnapshot,
        params: MemberTaylorParameters,
    ) -> float:
        """Computes the target nominal policy rate before discretization."""
        # Inflation gap: pi_t - pi*
        inflation_gap = snapshot.cpi_headline_yoy_pct - self.pi_star
        # Output gap: y_t - y*
        output_gap = snapshot.output_gap_pct
        # External US Fed rate gap
        us_rate_gap = snapshot.us_fed_funds_rate_pct - self.us_neutral_rate

        # Unsmoothed Taylor target: r* + pi_t + alpha*(pi - pi*) + beta*gap + gamma*us_gap
        target_rate = (
            self.r_star
            + snapshot.cpi_headline_yoy_pct
            + params.alpha * inflation_gap
            + params.beta * output_gap
            + params.gamma * us_rate_gap
        )

        # Apply interest rate smoothing with previous rate
        prev_rate = snapshot.current_repo_rate_pct
        smoothed_rate = self.rho * prev_rate + (1.0 - self.rho) * target_rate
        return smoothed_rate

    def compute_discrete_action(
        self,
        snapshot: MacroMeetingSnapshot,
        params: MemberTaylorParameters,
    ) -> tuple[int, str]:
        """
        Discretizes the implied continuous rate into the nearest valid basis point action
        and assigns an implied policy stance.
        Returns: (vote_bps, stance_string)
        """
        smoothed_rate = self.compute_continuous_rate(snapshot, params)
        raw_change_bps = (smoothed_rate - snapshot.current_repo_rate_pct) * 100.0

        # Discretize to closest action in action set
        discrete_vote_bps = min(self.action_set_bps, key=lambda a: abs(a - raw_change_bps))

        # Implied stance
        if discrete_vote_bps > 0 or snapshot.cpi_headline_yoy_pct > (self.pi_star + 1.0):
            implied_stance = "withdrawal_of_accommodation"
        elif discrete_vote_bps < 0 and snapshot.cpi_headline_yoy_pct < self.pi_star:
            implied_stance = "accommodative"
        else:
            implied_stance = "neutral"

        return int(discrete_vote_bps), implied_stance
