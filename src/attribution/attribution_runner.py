"""
Attribution Layer: Exactly 3 Pre-Specified Removal-Based Experiments.
1. Leave-One-Member-Out Debate Persuasion Ablation
2. Statutory Casting-Vote Mechanism Ablation
3. Macroeconomic Input Muting
"""

from typing import Sequence, Optional
from dataclasses import dataclass

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.schemas.debate_schema import MeetingCommitteeDecision
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.rule_engine.engine import InstitutionalRuleEngine


@dataclass
class AttributionResult:
    experiment_id: str
    experiment_name: str
    baseline_decision_bps: int
    ablated_decision_bps: int
    baseline_stance: str
    ablated_stance: str
    outcome_shifted: bool
    marginal_contribution_bps: int
    description: str


class AttributionRunner:
    """Orchestrates causal and removal-based attribution experiments."""

    @staticmethod
    def ablate_casting_vote(
        meeting_outcome: MeetingCommitteeDecision,
        governor_id: str,
    ) -> AttributionResult:
        """
        Experiment 2: Statutory Casting-Vote Ablation.
        Tests what the committee would have decided on 3-3 ties if the Governor's casting
        vote were disabled (strict 4-vote majority required, otherwise status quo 0 bps holds).
        """
        base_rate = meeting_outcome.rate_decision_bps
        base_stance = meeting_outcome.stance_decision
        tie_rate = meeting_outcome.tie_broken_by_governor_rate
        tie_stance = meeting_outcome.tie_broken_by_governor_stance

        if tie_rate:
            # If tie-breaker disabled, committee fails to reach majority -> status quo 0 bps holds
            ablated_rate = 0
        else:
            ablated_rate = base_rate

        if tie_stance:
            # Status quo stance holds
            ablated_stance = "neutral"
        else:
            ablated_stance = base_stance

        shifted = (ablated_rate != base_rate) or (ablated_stance != base_stance)
        marginal_contribution = base_rate - ablated_rate

        return AttributionResult(
            experiment_id="EXP_2_CASTING_VOTE",
            experiment_name="Governor Statutory Casting-Vote Ablation (§45ZL)",
            baseline_decision_bps=base_rate,
            ablated_decision_bps=ablated_rate,
            baseline_stance=base_stance,
            ablated_stance=ablated_stance,
            outcome_shifted=shifted,
            marginal_contribution_bps=marginal_contribution,
            description="Evaluates whether the Governor's casting vote changed the outcome during a 3-3 split.",
        )

    @staticmethod
    def mute_macro_input(
        baseline_snapshot: MacroMeetingSnapshot,
        muted_factor: str,  # e.g., 'monsoon' or 'food_inflation'
    ) -> MacroMeetingSnapshot:
        """
        Experiment 3: Macroeconomic Input Muting.
        Zeros out or neutralizes a specific macroeconomic shock while keeping all other series intact.
        """
        if muted_factor == "monsoon":
            return MacroMeetingSnapshot(
                meeting_date=baseline_snapshot.meeting_date,
                current_repo_rate_pct=baseline_snapshot.current_repo_rate_pct,
                cpi_headline_yoy_pct=baseline_snapshot.cpi_headline_yoy_pct,
                cpi_core_yoy_pct=baseline_snapshot.cpi_core_yoy_pct,
                cpi_food_yoy_pct=baseline_snapshot.cpi_food_yoy_pct,
                iip_growth_yoy_pct=baseline_snapshot.iip_growth_yoy_pct,
                gva_growth_yoy_pct=baseline_snapshot.gva_growth_yoy_pct,
                output_gap_pct=baseline_snapshot.output_gap_pct,
                system_liquidity_cr=baseline_snapshot.system_liquidity_cr,
                usd_inr_exchange_rate=baseline_snapshot.usd_inr_exchange_rate,
                brent_crude_usd_bbl=baseline_snapshot.brent_crude_usd_bbl,
                us_fed_funds_rate_pct=baseline_snapshot.us_fed_funds_rate_pct,
                monsoon_departure_lpa_pct=0.0,  # Neutralized
                prev_stance=baseline_snapshot.prev_stance,
            )
        elif muted_factor == "food_inflation":
            # Set food inflation to historical normal ~4.0%
            food_delta = (baseline_snapshot.cpi_food_yoy_pct or 4.0) - 4.0
            headline_adjustment = food_delta * 0.458
            return MacroMeetingSnapshot(
                meeting_date=baseline_snapshot.meeting_date,
                current_repo_rate_pct=baseline_snapshot.current_repo_rate_pct,
                cpi_headline_yoy_pct=baseline_snapshot.cpi_headline_yoy_pct - headline_adjustment,
                cpi_core_yoy_pct=baseline_snapshot.cpi_core_yoy_pct,
                cpi_food_yoy_pct=4.0,  # Neutralized
                iip_growth_yoy_pct=baseline_snapshot.iip_growth_yoy_pct,
                gva_growth_yoy_pct=baseline_snapshot.gva_growth_yoy_pct,
                output_gap_pct=baseline_snapshot.output_gap_pct,
                system_liquidity_cr=baseline_snapshot.system_liquidity_cr,
                usd_inr_exchange_rate=baseline_snapshot.usd_inr_exchange_rate,
                brent_crude_usd_bbl=baseline_snapshot.brent_crude_usd_bbl,
                us_fed_funds_rate_pct=baseline_snapshot.us_fed_funds_rate_pct,
                monsoon_departure_lpa_pct=baseline_snapshot.monsoon_departure_lpa_pct,
                prev_stance=baseline_snapshot.prev_stance,
            )
        else:
            raise ValueError(f"Unknown muting factor: {muted_factor}")

    @classmethod
    async def run_leave_one_out_ablation(
        cls,
        orchestrator: DebateOrchestrator,
        baseline_decision: MeetingCommitteeDecision,
        snapshot: MacroMeetingSnapshot,
        personas: Sequence[MemberPersona],
        governor_id: str,
        ablated_member_id: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> AttributionResult:
        """
        Experiment 1: Leave-One-Member-Out Persuasion Ablation.
        Withholds ablated_member_id's arguments during Rounds 2 and 3 and determines
        whether peer agents alter their final binding votes.
        """
        ablated_decision = await orchestrator.run_meeting(
            snapshot=snapshot,
            personas=personas,
            governor_id=governor_id,
            replicate_id=1,
            model=model,
            temperature=temperature,
            ablated_member_id=ablated_member_id,
        )

        shifted = (
            ablated_decision.rate_decision_bps != baseline_decision.rate_decision_bps
            or ablated_decision.stance_decision != baseline_decision.stance_decision
        )
        marginal_delta = baseline_decision.rate_decision_bps - ablated_decision.rate_decision_bps

        return AttributionResult(
            experiment_id=f"EXP_1_LEAVE_OUT_{ablated_member_id.upper()}",
            experiment_name=f"Leave-One-Out Persuasion Ablation ({ablated_member_id})",
            baseline_decision_bps=baseline_decision.rate_decision_bps,
            ablated_decision_bps=ablated_decision.rate_decision_bps,
            baseline_stance=baseline_decision.stance_decision,
            ablated_stance=ablated_decision.stance_decision,
            outcome_shifted=shifted,
            marginal_contribution_bps=marginal_delta,
            description=f"Withholds {ablated_member_id}'s statements in Rounds 2 & 3 to measure peer persuasion influence.",
        )

    @classmethod
    async def run_macro_muting_ablation(
        cls,
        orchestrator: DebateOrchestrator,
        baseline_decision: MeetingCommitteeDecision,
        snapshot: MacroMeetingSnapshot,
        personas: Sequence[MemberPersona],
        governor_id: str,
        muted_factor: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> AttributionResult:
        """
        Experiment 3: Macro-Factor Muting.
        Neutralizes a specific macroeconomic driver (e.g. food inflation or monsoon)
        and re-runs deliberation to measure marginal macro sensitivity.
        """
        muted_snap = cls.mute_macro_input(snapshot, muted_factor)
        muted_decision = await orchestrator.run_meeting(
            snapshot=muted_snap,
            personas=personas,
            governor_id=governor_id,
            replicate_id=1,
            model=model,
            temperature=temperature,
        )

        shifted = (
            muted_decision.rate_decision_bps != baseline_decision.rate_decision_bps
            or muted_decision.stance_decision != baseline_decision.stance_decision
        )
        marginal_delta = baseline_decision.rate_decision_bps - muted_decision.rate_decision_bps

        return AttributionResult(
            experiment_id=f"EXP_3_MUTE_{muted_factor.upper()}",
            experiment_name=f"Macroeconomic Factor Muting ({muted_factor})",
            baseline_decision_bps=baseline_decision.rate_decision_bps,
            ablated_decision_bps=muted_decision.rate_decision_bps,
            baseline_stance=baseline_decision.stance_decision,
            ablated_stance=muted_decision.stance_decision,
            outcome_shifted=shifted,
            marginal_contribution_bps=marginal_delta,
            description=f"Neutralizes {muted_factor} from committee briefing to measure causal macro sensitivity.",
        )

