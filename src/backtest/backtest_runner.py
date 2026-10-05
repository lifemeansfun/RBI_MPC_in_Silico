"""
Empirical Backtesting Runner for RBI MPC In Silico.
Executes the multi-agent deliberation simulation over the 2020–2024 historical panel
(16 calibration meetings + 8 holdout meetings).
Evaluates Directional Rate Accuracy, Stance Accuracy, and Dissent F1 Score.
Generates results/tables/meeting_by_meeting_comparison.csv and results/tables/backtest_metrics.csv.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Literal
import pandas as pd
import yaml

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.schemas.debate_schema import MeetingCommitteeDecision
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.validation.metrics import MetricsEvaluator, ValidationMetricsSummary
from src.infra.config_loader import load_config
from src.infra.exceptions import RBIMPCError

logger = logging.getLogger("rbi_mpc.backtest")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Roster split: May 2022 was when Mridul Saggar retired and Rajiv Ranjan took over
PRE_MAY_2022_ED = "mridul_saggar"
POST_MAY_2022_ED = "rajiv_ranjan"


class BacktestRunner:
    """Executes panel backtesting with strict academic metrics and provenance tracking."""

    def __init__(
        self,
        macro_panel_path: Optional[Path] = None,
        personas_dir: Optional[Path] = None,
        results_dir: Optional[Path] = None,
        orchestrator: Optional[DebateOrchestrator] = None,
    ):
        self.macro_panel_path = macro_panel_path or (PROJECT_ROOT / "data" / "processed" / "macro_panel.parquet")
        self.personas_dir = personas_dir or (PROJECT_ROOT / "personas" / "2020_2024_roster")
        self.results_dir = results_dir or (PROJECT_ROOT / "results" / "tables")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.orchestrator = orchestrator or DebateOrchestrator()
        self.config = load_config()

    def load_panel(self) -> pd.DataFrame:
        """Loads and returns the verified macroeconomic panel."""
        if not self.macro_panel_path.exists():
            raise FileNotFoundError(f"Macro panel not found at {self.macro_panel_path}. Run macro_builder first.")
        return pd.read_parquet(self.macro_panel_path)

    def load_roster_for_date(self, meeting_date_str: str) -> list[MemberPersona]:
        """Loads the active 6 personas for the given meeting date."""
        ed_id = PRE_MAY_2022_ED if meeting_date_str < "2022-05-01" else POST_MAY_2022_ED
        active_ids = [
            "shaktikanta_das",
            "michael_patra",
            ed_id,
            "shashanka_bhide",
            "ashima_goyal",
            "jayanth_varma",
        ]

        personas = []
        for m_id in active_ids:
            p_file = self.personas_dir / f"{m_id}.yaml"
            if not p_file.exists():
                raise FileNotFoundError(f"Persona file {p_file} not found.")
            with open(p_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            personas.append(MemberPersona(**data))
        return personas

    async def run_meeting_backtest(
        self,
        row: dict,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> dict:
        """Executes simulation for a single historical meeting and compares against ground truth."""
        snapshot = MacroMeetingSnapshot(**row)
        personas = self.load_roster_for_date(snapshot.meeting_date)

        logger.info("[Backtest] Running meeting %s (Actual Rate: %+d bps, Stance: %s)...",
                    snapshot.meeting_date, row["real_rate_decision_bps"], row["real_stance_decision"])

        decision: MeetingCommitteeDecision = await self.orchestrator.run_meeting(
            snapshot=snapshot,
            personas=personas,
            governor_id="shaktikanta_das",
            replicate_id=1,
            model=model,
            temperature=temperature,
        )

        # Comparative evaluation
        rate_diff = decision.rate_decision_bps - row["real_rate_decision_bps"]
        rate_match = (decision.rate_decision_bps == row["real_rate_decision_bps"])
        directional_match = (
            (decision.rate_decision_bps > 0 and row["real_rate_decision_bps"] > 0)
            or (decision.rate_decision_bps < 0 and row["real_rate_decision_bps"] < 0)
            or (decision.rate_decision_bps == 0 and row["real_rate_decision_bps"] == 0)
        )
        stance_match = (decision.stance_decision == row["real_stance_decision"])

        sim_dissenters = set(decision.dissenting_members_rate + decision.dissenting_members_stance)
        real_dissenters = set(row.get("real_dissenters", []))

        tp = len(sim_dissenters.intersection(real_dissenters))
        fp = len(sim_dissenters.difference(real_dissenters))
        fn = len(real_dissenters.difference(sim_dissenters))

        return {
            "meeting_date": snapshot.meeting_date,
            "panel_subset": "calibration" if snapshot.meeting_date <= "2023-04-06" else "holdout",
            "actual_rate_bps": row["real_rate_decision_bps"],
            "sim_rate_bps": decision.rate_decision_bps,
            "rate_match": rate_match,
            "directional_match": directional_match,
            "actual_stance": row["real_stance_decision"],
            "sim_stance": decision.stance_decision,
            "stance_match": stance_match,
            "actual_dissenters": ";".join(sorted(real_dissenters)),
            "sim_dissenters": ";".join(sorted(sim_dissenters)),
            "dissent_tp": tp,
            "dissent_fp": fp,
            "dissent_fn": fn,
            "tie_broken": decision.tie_broken_by_governor_rate or decision.tie_broken_by_governor_stance,
            "fallbacks_used": decision.fallbacks_count,
        }

    async def run_panel_backtest(
        self,
        subset: Literal["all", "calibration", "holdout"] = "all",
        max_meetings: Optional[int] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        resume: bool = True,
    ) -> pd.DataFrame:
        """Executes backtesting across the panel with incremental meeting checkpointing."""
        import json
        checkpoint_dir = PROJECT_ROOT / "data" / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        df_panel = self.load_panel()

        if subset == "calibration":
            df_panel = df_panel[df_panel["meeting_date"] <= "2023-04-06"]
        elif subset == "holdout":
            df_panel = df_panel[df_panel["meeting_date"] > "2023-04-06"]

        if max_meetings:
            df_panel = df_panel.head(max_meetings)

        records = df_panel.to_dict(orient="records")
        results = []

        print(f"\n[+] Starting MPC In Silico Panel Backtest: {len(records)} meetings (Subset: {subset}, Resume: {resume})...")

        for idx, row in enumerate(records, 1):
            date_str = row["meeting_date"]
            ckpt_path = checkpoint_dir / f"meeting_{date_str}.json"

            if resume and ckpt_path.exists():
                try:
                    with open(ckpt_path, "r", encoding="utf-8") as f:
                        res = json.load(f)
                    print(f"  [{idx}/{len(records)}] [CHECKPOINT HIT] Loaded {date_str} from cache.")
                    results.append(res)
                    continue
                except Exception as e:
                    logger.warning("Failed to load checkpoint for %s (%s). Re-simulating.", date_str, e)

            print(f"  [{idx}/{len(records)}] Simulating {date_str}...")
            res = await self.run_meeting_backtest(row, model=model, temperature=temperature)
            results.append(res)

            # Atomically persist meeting checkpoint
            temp_ckpt = checkpoint_dir / f".meeting_{date_str}.json.tmp"
            with open(temp_ckpt, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2)
            temp_ckpt.replace(ckpt_path)

        df_results = pd.DataFrame(results)

        # Save meeting-by-meeting comparison
        comparison_path = self.results_dir / "meeting_by_meeting_comparison.csv"
        df_results.to_csv(comparison_path, index=False)

        # Compute aggregate validation metrics
        metrics = self.compute_aggregate_metrics(df_results)
        metrics_df = pd.DataFrame([metrics])
        metrics_path = self.results_dir / "backtest_metrics.csv"
        metrics_df.to_csv(metrics_path, index=False)

        print("\n=======================================================")
        print("           PANEL BACKTESTING RESULTS SUMMARY           ")
        print("=======================================================")
        print(f"Total Meetings Evaluated:    {metrics['total_meetings']}")
        print(f"Directional Rate Accuracy:   {metrics['directional_rate_accuracy']:.1%}")
        print(f"Exact Rate Decision Match:   {metrics['exact_rate_accuracy']:.1%}")
        print(f"Policy Stance Accuracy:      {metrics['stance_accuracy']:.1%}")
        print(f"Dissent Precision:           {metrics['dissent_precision']:.2f}")
        print(f"Dissent Recall:              {metrics['dissent_recall']:.2f}")
        print(f"Dissent F1 Score:            {metrics['dissent_f1']:.2f}")
        print(f"Holdout Gate Status:         {metrics['holdout_gate_status']}")
        print(f"Fallbacks Triggered:         {metrics['total_fallbacks']}")
        print(f"Detailed CSV:                {comparison_path}")
        print("=======================================================\n")

        return df_results

    @staticmethod
    def compute_aggregate_metrics(df: pd.DataFrame) -> dict:
        """Computes academic benchmark metrics from comparison dataframe."""
        total = len(df)
        if total == 0:
            return {}

        dir_acc = float(df["directional_match"].mean())
        exact_rate_acc = float(df["rate_match"].mean())
        stance_acc = float(df["stance_match"].mean())

        total_tp = int(df["dissent_tp"].sum())
        total_fp = int(df["dissent_fp"].sum())
        total_fn = int(df["dissent_fn"].sum())

        prec = total_tp / max(total_tp + total_fp, 1)
        rec = total_tp / max(total_tp + total_fn, 1)
        f1 = (2 * prec * rec) / max(prec + rec, 1e-6)

        gate_passed = (dir_acc >= 0.75 and stance_acc >= 0.70 and f1 >= 0.60)

        return {
            "total_meetings": total,
            "directional_rate_accuracy": round(dir_acc, 4),
            "exact_rate_accuracy": round(exact_rate_acc, 4),
            "stance_accuracy": round(stance_acc, 4),
            "dissent_precision": round(prec, 4),
            "dissent_recall": round(rec, 4),
            "dissent_f1": round(f1, 4),
            "holdout_gate_status": "PASS" if gate_passed else "FAIL",
            "total_fallbacks": int(df["fallbacks_used"].sum()),
        }


if __name__ == "__main__":
    runner = BacktestRunner()
    # Run backtesting
    asyncio.run(runner.run_panel_backtest(subset="all", max_meetings=3))
