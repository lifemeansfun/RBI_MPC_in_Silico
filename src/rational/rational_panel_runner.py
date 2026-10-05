"""
Rational Benchmark Track: Full 25-Meeting Panel Runner.
Executes the Smoothed Open-Economy Taylor Rule under N=1,000 Monte Carlo perturbation draws
across the entire 2020–2024 historical panel (25 meetings).
Merges results with the Behavioral LLM track to compute the Behavioral-versus-Rational Policy Wedge.
Produces:
- results/tables/rational_taylor_panel_results.csv
- results/tables/table4_behavioral_vs_taylor_comparison.csv
"""

import logging
from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.rational.monte_carlo import MonteCarloEngine, MonteCarloResult
from src.infra.config_loader import load_config

logger = logging.getLogger("rbi_mpc.rational_runner")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Calibrated member Taylor rule coefficients fitted to Indian macroeconomic context
MEMBER_TAYLOR_PARAMS = {
    "shaktikanta_das": MemberTaylorParameters("shaktikanta_das", alpha=1.2, beta=0.4, gamma=0.2),
    "michael_patra": MemberTaylorParameters("michael_patra", alpha=1.8, beta=0.6, gamma=0.3),
    "rajiv_ranjan": MemberTaylorParameters("rajiv_ranjan", alpha=1.4, beta=0.5, gamma=0.2),
    "mridul_saggar": MemberTaylorParameters("mridul_saggar", alpha=1.3, beta=0.5, gamma=0.2),
    "jayanth_varma": MemberTaylorParameters("jayanth_varma", alpha=0.5, beta=0.2, gamma=0.0),
    "ashima_goyal": MemberTaylorParameters("ashima_goyal", alpha=0.8, beta=0.3, gamma=0.1),
    "shashanka_bhide": MemberTaylorParameters("shashanka_bhide", alpha=1.3, beta=0.4, gamma=0.2),
}


class RationalPanelRunner:
    """Executes Monte Carlo rational benchmark simulation across historical meetings."""

    def __init__(
        self,
        macro_panel_path: Optional[Path] = None,
        results_dir: Optional[Path] = None,
        n_draws: int = 1000,
        noise_std_pct: float = 0.20,
    ):
        self.macro_panel_path = macro_panel_path or (PROJECT_ROOT / "data" / "processed" / "macro_panel.parquet")
        self.results_dir = results_dir or (PROJECT_ROOT / "results" / "tables")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.n_draws = n_draws
        self.noise_std = noise_std_pct
        self.config = load_config()

        # Initialize Taylor Rule
        self.taylor_rule = SmoothedTaylorRule(
            r_star_pct=self.config.taylor_rule.r_star_pct,
            pi_star_pct=self.config.taylor_rule.pi_star_pct,
            smoothing_rho=self.config.taylor_rule.smoothing_rho,
        )
        self.mc_engine = MonteCarloEngine(
            taylor_rule=self.taylor_rule,
            n_draws=self.n_draws,
            noise_std_pct=self.noise_std,
            seed=self.config.run.seed_base,
        )

    def load_active_roster_params(self, meeting_date_str: str) -> list[MemberTaylorParameters]:
        """Returns the active 6 members' Taylor parameters for the given meeting date."""
        ed_id = "mridul_saggar" if meeting_date_str < "2022-05-01" else "rajiv_ranjan"
        active_ids = [
            "shaktikanta_das",
            "michael_patra",
            ed_id,
            "shashanka_bhide",
            "ashima_goyal",
            "jayanth_varma",
        ]
        return [MEMBER_TAYLOR_PARAMS[m_id] for m_id in active_ids]

    def run_full_panel(self) -> pd.DataFrame:
        """Executes 1,000 Monte Carlo draws per meeting for all 25 meetings."""
        if not self.macro_panel_path.exists():
            raise FileNotFoundError(f"Macro panel not found at {self.macro_panel_path}")

        df_macro = pd.read_parquet(self.macro_panel_path)
        records = df_macro.to_dict(orient="records")
        rational_results = []

        print(f"\n[+] Running Rational Track Monte Carlo ({self.n_draws} draws/meeting) across {len(records)} meetings...")

        for idx, row in enumerate(records, 1):
            snapshot = MacroMeetingSnapshot(**row)
            active_params = self.load_active_roster_params(snapshot.meeting_date)

            mc_res: MonteCarloResult = self.mc_engine.simulate(
                snapshot=snapshot,
                member_params=active_params,
                governor_id="shaktikanta_das",
            )

            # Directional match against ground truth
            actual_bps = row.get("real_rate_decision_bps", 0)
            directional_match = (
                (mc_res.modal_rate_decision_bps > 0 and actual_bps > 0)
                or (mc_res.modal_rate_decision_bps < 0 and actual_bps < 0)
                or (mc_res.modal_rate_decision_bps == 0 and actual_bps == 0)
            )
            exact_match = (mc_res.modal_rate_decision_bps == actual_bps)

            rational_results.append({
                "meeting_date": snapshot.meeting_date,
                "current_repo_rate_pct": snapshot.current_repo_rate_pct,
                "headline_cpi_pct": snapshot.cpi_headline_yoy_pct,
                "actual_rate_bps": actual_bps,
                "actual_stance": row.get("real_stance_decision", "withdrawal_of_accommodation"),
                "taylor_modal_rate_bps": mc_res.modal_rate_decision_bps,
                "taylor_modal_stance": mc_res.modal_stance_decision,
                "taylor_mean_implied_rate_pct": round(mc_res.mean_implied_rate, 2),
                "taylor_exact_match": exact_match,
                "taylor_directional_match": directional_match,
                "taylor_rate_dist": str(mc_res.rate_distribution_pct),
                "taylor_dissent_probs": str(mc_res.dissent_probability_by_member),
            })
            print(f"  [{idx}/{len(records)}] {snapshot.meeting_date}: Actual={actual_bps:+d} bps | Taylor Modal={mc_res.modal_rate_decision_bps:+d} bps (Implied Mean: {mc_res.mean_implied_rate:.2f}%)")

        df_rational = pd.DataFrame(rational_results)
        rational_csv = self.results_dir / "rational_taylor_panel_results.csv"
        df_rational.to_csv(rational_csv, index=False)
        print(f"[+] Saved Rational Track panel results: {rational_csv}")

        # Build Comparative Table (Behavioral LLM vs. Rational Taylor Rule)
        self.build_head_to_head_comparison(df_rational)
        return df_rational

    def build_head_to_head_comparison(self, df_rational: pd.DataFrame) -> pd.DataFrame:
        """Merges Rational and Behavioral tracks to compute the policy wedge and comparative metrics."""
        llm_csv = self.results_dir / "meeting_by_meeting_comparison.csv"
        if not llm_csv.exists():
            logger.warning("LLM comparison CSV %s not found. Comparative table cannot be fully merged.", llm_csv)
            return df_rational

        df_llm = pd.read_csv(llm_csv)

        merged = pd.merge(
            df_rational[[
                "meeting_date", "current_repo_rate_pct", "headline_cpi_pct",
                "actual_rate_bps", "actual_stance",
                "taylor_modal_rate_bps", "taylor_modal_stance", "taylor_mean_implied_rate_pct",
                "taylor_exact_match", "taylor_directional_match"
            ]],
            df_llm[[
                "meeting_date", "sim_rate_bps", "sim_stance",
                "rate_match", "directional_match", "stance_match",
                "actual_dissenters", "sim_dissenters"
            ]],
            on="meeting_date",
            how="inner",
        )

        # Compute Behavioral-vs-Rational Policy Wedge
        # Policy Wedge = LLM Decision - Taylor Decision
        merged["policy_rate_wedge_bps"] = merged["sim_rate_bps"] - merged["taylor_modal_rate_bps"]
        merged["llm_exact_match"] = merged["rate_match"]
        merged["llm_directional_match"] = merged["directional_match"]

        # Reorder columns cleanly
        comparison_cols = [
            "meeting_date",
            "current_repo_rate_pct",
            "headline_cpi_pct",
            "actual_rate_bps",
            "actual_stance",
            "taylor_modal_rate_bps",
            "sim_rate_bps",
            "policy_rate_wedge_bps",
            "taylor_exact_match",
            "llm_exact_match",
            "taylor_directional_match",
            "llm_directional_match",
            "actual_stance",
            "taylor_modal_stance",
            "sim_stance",
            "stance_match",
            "actual_dissenters",
            "sim_dissenters",
        ]
        comparison_df = merged[comparison_cols]
        comp_path = self.results_dir / "table4_behavioral_vs_taylor_comparison.csv"
        comparison_df.to_csv(comp_path, index=False)

        # Summary Statistics
        taylor_exact_acc = comparison_df["taylor_exact_match"].mean() * 100.0
        llm_exact_acc = comparison_df["llm_exact_match"].mean() * 100.0
        taylor_dir_acc = comparison_df["taylor_directional_match"].mean() * 100.0
        llm_dir_acc = comparison_df["llm_directional_match"].mean() * 100.0
        avg_abs_wedge = comparison_df["policy_rate_wedge_bps"].abs().mean()

        print("\n" + "=" * 74)
        print("     HEAD-TO-HEAD COMPARISON: BEHAVIORAL LLM vs. RATIONAL TAYLOR RULE")
        print("=" * 74)
        print(f"Total Historical Meetings:          {len(comparison_df)}")
        print(f"Taylor Rule Exact Rate Accuracy:    {taylor_exact_acc:.1f}%")
        print(f"LLM Multi-Agent Exact Rate Accuracy:{llm_exact_acc:.1f}%")
        print(f"Taylor Rule Directional Accuracy:   {taylor_dir_acc:.1f}%")
        print(f"LLM Multi-Agent Directional Accuracy:{llm_dir_acc:.1f}%")
        print(f"Average Absolute Policy Wedge:      {avg_abs_wedge:.1f} bps")
        print(f"Master Comparative CSV:             {comp_path}")
        print("=" * 74 + "\n")

        return comparison_df


if __name__ == "__main__":
    runner = RationalPanelRunner()
    runner.run_full_panel()
