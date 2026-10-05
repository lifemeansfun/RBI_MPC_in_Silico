"""
Counterfactual Scenario Runner:
1. Monsoon Failure & Food Inflation Shock (anchored to July 2023 vegetable surge)
2. US Federal Reserve Spillover Shock (anchored to 2022 Fed rate hiking cycle)
Quantifies the Behavioral-versus-Rational policy wedge under each shock.
"""

from typing import Sequence
from dataclasses import dataclass

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.rule_engine.engine import InstitutionalRuleEngine


@dataclass
class ScenarioOutcome:
    scenario_name: str
    baseline_repo_rate_change_bps: int
    shocked_repo_rate_change_bps: int
    baseline_stance: str
    shocked_stance: str
    rate_wedge_bps: int
    stance_changed: bool
    dissenting_members_shocked: list[str]


class ScenarioRunner:
    """Executes counterfactual stress tests over the rational benchmark track."""

    def __init__(self, taylor_rule: SmoothedTaylorRule):
        self.rule = taylor_rule

    def run_monsoon_food_shock(
        self,
        baseline_snapshot: MacroMeetingSnapshot,
        member_params: Sequence[MemberTaylorParameters],
        governor_id: str,
        food_cpi_shock_pct: float = 4.0,  # +400 bps food inflation spike
        monsoon_departure_pct: float = -20.0,
    ) -> ScenarioOutcome:
        """Applies food inflation & monsoon shock to baseline snapshot."""
        # 1. Baseline Run
        base_rate_votes = {}
        base_stance_votes = {}
        for p in member_params:
            r, s = self.rule.compute_discrete_action(baseline_snapshot, p)
            base_rate_votes[p.member_id] = r
            base_stance_votes[p.member_id] = s

        base_rate_res = InstitutionalRuleEngine.aggregate_rate_votes(base_rate_votes, governor_id)
        base_stance_res = InstitutionalRuleEngine.aggregate_stance_votes(base_stance_votes, governor_id)

        # 2. Shocked Snapshot (Food shock feeds ~46% weight into headline CPI in India)
        implied_headline_increase = food_cpi_shock_pct * 0.458
        shocked_snapshot = MacroMeetingSnapshot(
            meeting_date=baseline_snapshot.meeting_date,
            current_repo_rate_pct=baseline_snapshot.current_repo_rate_pct,
            cpi_headline_yoy_pct=baseline_snapshot.cpi_headline_yoy_pct + implied_headline_increase,
            cpi_core_yoy_pct=baseline_snapshot.cpi_core_yoy_pct,
            cpi_food_yoy_pct=(baseline_snapshot.cpi_food_yoy_pct or 5.0) + food_cpi_shock_pct,
            iip_growth_yoy_pct=baseline_snapshot.iip_growth_yoy_pct - 0.5,  # Rural demand drag
            gva_growth_yoy_pct=baseline_snapshot.gva_growth_yoy_pct,
            output_gap_pct=baseline_snapshot.output_gap_pct - 0.2,
            system_liquidity_cr=baseline_snapshot.system_liquidity_cr,
            usd_inr_exchange_rate=baseline_snapshot.usd_inr_exchange_rate,
            brent_crude_usd_bbl=baseline_snapshot.brent_crude_usd_bbl,
            us_fed_funds_rate_pct=baseline_snapshot.us_fed_funds_rate_pct,
            monsoon_departure_lpa_pct=monsoon_departure_pct,
            prev_stance=baseline_snapshot.prev_stance,
        )

        shock_rate_votes = {}
        shock_stance_votes = {}
        for p in member_params:
            r, s = self.rule.compute_discrete_action(shocked_snapshot, p)
            shock_rate_votes[p.member_id] = r
            shock_stance_votes[p.member_id] = s

        shock_rate_res = InstitutionalRuleEngine.aggregate_rate_votes(shock_rate_votes, governor_id)
        shock_stance_res = InstitutionalRuleEngine.aggregate_stance_votes(shock_stance_votes, governor_id)

        return ScenarioOutcome(
            scenario_name="Monsoon Failure & Food Inflation Shock",
            baseline_repo_rate_change_bps=base_rate_res.winning_action,
            shocked_repo_rate_change_bps=shock_rate_res.winning_action,
            baseline_stance=base_stance_res.winning_action,
            shocked_stance=shock_stance_res.winning_action,
            rate_wedge_bps=shock_rate_res.winning_action - base_rate_res.winning_action,
            stance_changed=(shock_stance_res.winning_action != base_stance_res.winning_action),
            dissenting_members_shocked=shock_rate_res.dissenting_members,
        )

    def run_us_fed_spillover_shock(
        self,
        baseline_snapshot: MacroMeetingSnapshot,
        member_params: Sequence[MemberTaylorParameters],
        governor_id: str,
        fed_hike_bps: int = 75,
        inr_depreciation: float = 1.50,
    ) -> ScenarioOutcome:
        """Applies aggressive US Fed rate hike and capital flow spillover."""
        # Baseline
        base_rate_votes = {p.member_id: self.rule.compute_discrete_action(baseline_snapshot, p)[0] for p in member_params}
        base_stance_votes = {p.member_id: self.rule.compute_discrete_action(baseline_snapshot, p)[1] for p in member_params}
        base_r = InstitutionalRuleEngine.aggregate_rate_votes(base_rate_votes, governor_id).winning_action
        base_s = InstitutionalRuleEngine.aggregate_stance_votes(base_stance_votes, governor_id).winning_action

        # Shocked
        shocked_snapshot = MacroMeetingSnapshot(
            meeting_date=baseline_snapshot.meeting_date,
            current_repo_rate_pct=baseline_snapshot.current_repo_rate_pct,
            cpi_headline_yoy_pct=baseline_snapshot.cpi_headline_yoy_pct + 0.30,  # Imported inflation
            cpi_core_yoy_pct=baseline_snapshot.cpi_core_yoy_pct + 0.20,
            cpi_food_yoy_pct=baseline_snapshot.cpi_food_yoy_pct,
            iip_growth_yoy_pct=baseline_snapshot.iip_growth_yoy_pct,
            output_gap_pct=baseline_snapshot.output_gap_pct,
            system_liquidity_cr=baseline_snapshot.system_liquidity_cr - 30000.0,  # FX intervention drain
            usd_inr_exchange_rate=baseline_snapshot.usd_inr_exchange_rate + inr_depreciation,
            brent_crude_usd_bbl=baseline_snapshot.brent_crude_usd_bbl,
            us_fed_funds_rate_pct=baseline_snapshot.us_fed_funds_rate_pct + (fed_hike_bps / 100.0),
            monsoon_departure_lpa_pct=baseline_snapshot.monsoon_departure_lpa_pct,
            prev_stance=baseline_snapshot.prev_stance,
        )

        shock_r_votes = {p.member_id: self.rule.compute_discrete_action(shocked_snapshot, p)[0] for p in member_params}
        shock_s_votes = {p.member_id: self.rule.compute_discrete_action(shocked_snapshot, p)[1] for p in member_params}
        shock_r_res = InstitutionalRuleEngine.aggregate_rate_votes(shock_r_votes, governor_id)
        shock_s_res = InstitutionalRuleEngine.aggregate_stance_votes(shock_s_votes, governor_id)

        return ScenarioOutcome(
            scenario_name="US Federal Reserve Spillover Shock (+75 bps)",
            baseline_repo_rate_change_bps=base_r,
            shocked_repo_rate_change_bps=shock_r_res.winning_action,
            baseline_stance=base_s,
            shocked_stance=shock_s_res.winning_action,
            rate_wedge_bps=shock_r_res.winning_action - base_r,
            stance_changed=(shock_s_res.winning_action != base_s),
            dissenting_members_shocked=shock_r_res.dissenting_members,
        )

    def run_pandemic_easing_shock(
        self,
        baseline_snapshot: MacroMeetingSnapshot,
        member_params: Sequence[MemberTaylorParameters],
        governor_id: str,
    ) -> ScenarioOutcome:
        """Applies pandemic easing shock over the baseline."""
        # Baseline
        base_rate_votes = {p.member_id: self.rule.compute_discrete_action(baseline_snapshot, p)[0] for p in member_params}
        base_stance_votes = {p.member_id: self.rule.compute_discrete_action(baseline_snapshot, p)[1] for p in member_params}
        base_r = InstitutionalRuleEngine.aggregate_rate_votes(base_rate_votes, governor_id).winning_action
        base_s = InstitutionalRuleEngine.aggregate_stance_votes(base_stance_votes, governor_id).winning_action

        # Shocked
        shocked_snapshot = self.build_pandemic_easing_snapshot(baseline_snapshot)
        shock_r_votes = {p.member_id: self.rule.compute_discrete_action(shocked_snapshot, p)[0] for p in member_params}
        shock_s_votes = {p.member_id: self.rule.compute_discrete_action(shocked_snapshot, p)[1] for p in member_params}
        shock_r_res = InstitutionalRuleEngine.aggregate_rate_votes(shock_r_votes, governor_id)
        shock_s_res = InstitutionalRuleEngine.aggregate_stance_votes(shock_s_votes, governor_id)

        return ScenarioOutcome(
            scenario_name="2020 Pandemic Easing Cycle",
            baseline_repo_rate_change_bps=base_r,
            shocked_repo_rate_change_bps=shock_r_res.winning_action,
            baseline_stance=base_s,
            shocked_stance=shock_s_res.winning_action,
            rate_wedge_bps=shock_r_res.winning_action - base_r,
            stance_changed=(shock_s_res.winning_action != base_s),
            dissenting_members_shocked=shock_r_res.dissenting_members,
        )

    def run_taper_tantrum_shock(
        self,
        baseline_snapshot: MacroMeetingSnapshot,
        member_params: Sequence[MemberTaylorParameters],
        governor_id: str,
    ) -> ScenarioOutcome:
        """Applies 2013 Taper Tantrum shock over the baseline."""
        # Baseline
        base_rate_votes = {p.member_id: self.rule.compute_discrete_action(baseline_snapshot, p)[0] for p in member_params}
        base_stance_votes = {p.member_id: self.rule.compute_discrete_action(baseline_snapshot, p)[1] for p in member_params}
        base_r = InstitutionalRuleEngine.aggregate_rate_votes(base_rate_votes, governor_id).winning_action
        base_s = InstitutionalRuleEngine.aggregate_stance_votes(base_stance_votes, governor_id).winning_action

        # Shocked
        shocked_snapshot = self.build_taper_tantrum_snapshot(baseline_snapshot)
        shock_r_votes = {p.member_id: self.rule.compute_discrete_action(shocked_snapshot, p)[0] for p in member_params}
        shock_s_votes = {p.member_id: self.rule.compute_discrete_action(shocked_snapshot, p)[1] for p in member_params}
        shock_r_res = InstitutionalRuleEngine.aggregate_rate_votes(shock_r_votes, governor_id)
        shock_s_res = InstitutionalRuleEngine.aggregate_stance_votes(shock_s_votes, governor_id)

        return ScenarioOutcome(
            scenario_name="2013 Taper Tantrum Crisis",
            baseline_repo_rate_change_bps=base_r,
            shocked_repo_rate_change_bps=shock_r_res.winning_action,
            baseline_stance=base_s,
            shocked_stance=shock_s_res.winning_action,
            rate_wedge_bps=shock_r_res.winning_action - base_r,
            stance_changed=(shock_s_res.winning_action != base_s),
            dissenting_members_shocked=shock_r_res.dissenting_members,
        )

    @staticmethod
    def build_monsoon_food_shock_snapshot(
        baseline_snapshot: MacroMeetingSnapshot,
        food_cpi_shock_pct: float = 4.0,
        monsoon_departure_pct: float = -20.0,
    ) -> MacroMeetingSnapshot:
        """Constructs counterfactual perturbed snapshot for Monsoon & Food shock."""
        implied_headline_increase = food_cpi_shock_pct * 0.458
        return MacroMeetingSnapshot(
            meeting_date=baseline_snapshot.meeting_date,
            current_repo_rate_pct=baseline_snapshot.current_repo_rate_pct,
            cpi_headline_yoy_pct=baseline_snapshot.cpi_headline_yoy_pct + implied_headline_increase,
            cpi_core_yoy_pct=baseline_snapshot.cpi_core_yoy_pct,
            cpi_food_yoy_pct=(baseline_snapshot.cpi_food_yoy_pct or 5.0) + food_cpi_shock_pct,
            iip_growth_yoy_pct=baseline_snapshot.iip_growth_yoy_pct - 0.5,
            gva_growth_yoy_pct=baseline_snapshot.gva_growth_yoy_pct,
            output_gap_pct=baseline_snapshot.output_gap_pct - 0.2,
            system_liquidity_cr=baseline_snapshot.system_liquidity_cr,
            usd_inr_exchange_rate=baseline_snapshot.usd_inr_exchange_rate,
            brent_crude_usd_bbl=baseline_snapshot.brent_crude_usd_bbl,
            us_fed_funds_rate_pct=baseline_snapshot.us_fed_funds_rate_pct,
            monsoon_departure_lpa_pct=monsoon_departure_pct,
            prev_stance=baseline_snapshot.prev_stance,
        )

    @staticmethod
    def build_us_fed_spillover_snapshot(
        baseline_snapshot: MacroMeetingSnapshot,
        fed_hike_bps: int = 75,
        inr_depreciation: float = 1.50,
    ) -> MacroMeetingSnapshot:
        """Constructs counterfactual perturbed snapshot for US Fed Spillover shock."""
        return MacroMeetingSnapshot(
            meeting_date=baseline_snapshot.meeting_date,
            current_repo_rate_pct=baseline_snapshot.current_repo_rate_pct,
            cpi_headline_yoy_pct=baseline_snapshot.cpi_headline_yoy_pct + 0.30,
            cpi_core_yoy_pct=baseline_snapshot.cpi_core_yoy_pct + 0.20,
            cpi_food_yoy_pct=baseline_snapshot.cpi_food_yoy_pct,
            iip_growth_yoy_pct=baseline_snapshot.iip_growth_yoy_pct,
            output_gap_pct=baseline_snapshot.output_gap_pct,
            system_liquidity_cr=baseline_snapshot.system_liquidity_cr - 30000.0,
            usd_inr_exchange_rate=baseline_snapshot.usd_inr_exchange_rate + inr_depreciation,
            brent_crude_usd_bbl=baseline_snapshot.brent_crude_usd_bbl,
            us_fed_funds_rate_pct=baseline_snapshot.us_fed_funds_rate_pct + (fed_hike_bps / 100.0),
            monsoon_departure_lpa_pct=baseline_snapshot.monsoon_departure_lpa_pct,
            prev_stance=baseline_snapshot.prev_stance,
        )

    @staticmethod
    def build_pandemic_easing_snapshot(
        baseline_snapshot: MacroMeetingSnapshot,
    ) -> MacroMeetingSnapshot:
        """Constructs counterfactual OOD perturbed snapshot for 2020 Pandemic Easing Cycle."""
        return MacroMeetingSnapshot(
            meeting_date=baseline_snapshot.meeting_date,
            current_repo_rate_pct=baseline_snapshot.current_repo_rate_pct,
            cpi_headline_yoy_pct=4.50, # Deflationary impulse
            cpi_core_yoy_pct=3.50,
            cpi_food_yoy_pct=5.50,
            iip_growth_yoy_pct=-16.7, # Massive industrial collapse
            output_gap_pct=-4.0, # Severe negative output gap
            system_liquidity_cr=baseline_snapshot.system_liquidity_cr + 150000.0, # Huge liquidity injection
            usd_inr_exchange_rate=76.0,
            brent_crude_usd_bbl=25.0, # Oil crash
            us_fed_funds_rate_pct=0.25, # Fed ZIRP
            monsoon_departure_lpa_pct=baseline_snapshot.monsoon_departure_lpa_pct,
            prev_stance="accommodative",
        )

    @staticmethod
    def build_taper_tantrum_snapshot(
        baseline_snapshot: MacroMeetingSnapshot,
    ) -> MacroMeetingSnapshot:
        """Constructs counterfactual OOD perturbed snapshot for 2013 Taper Tantrum crisis."""
        return MacroMeetingSnapshot(
            meeting_date=baseline_snapshot.meeting_date,
            current_repo_rate_pct=baseline_snapshot.current_repo_rate_pct,
            cpi_headline_yoy_pct=9.84, # Massive 2013 inflation
            cpi_core_yoy_pct=8.00,
            cpi_food_yoy_pct=13.00,
            iip_growth_yoy_pct=1.0, 
            output_gap_pct=0.5,
            system_liquidity_cr=-80000.0, # Severe liquidity deficit (defense)
            usd_inr_exchange_rate=68.80, # Severe depreciation (2013 tantrum levels)
            brent_crude_usd_bbl=110.0, # High crude
            us_fed_funds_rate_pct=0.25, # Fed taper talk
            monsoon_departure_lpa_pct=baseline_snapshot.monsoon_departure_lpa_pct,
            prev_stance="withdrawal_of_accommodation",
        )

