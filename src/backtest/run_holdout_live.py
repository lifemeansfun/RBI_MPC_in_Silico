"""
Holdout Empirical Live Runner (Gold-Standard Validation).
Executes live multi-agent deliberation on Google Gemini (gemini-3.1-flash-lite)
across the 8 holdout historical meetings (June 2023 – August 2024).
Features:
- Incremental, atomic JSON checkpointing in data/checkpoints/
- Complete 25-file transcript logging in runs/holdout_live_run/
- Dynamic calculation of genuine Holdout Directional Rate Accuracy, Stance Accuracy, and Dissent F1
- Exports:
  - results/tables/holdout_validation_live_metrics.csv
  - results/tables/holdout_meeting_by_meeting_comparison.csv
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infra.config_loader import load_config
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.schemas.debate_schema import MeetingCommitteeDecision
from src.behavioral.debate_orchestrator import DebateOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rbi_mpc.holdout_live")


def load_personas() -> list[MemberPersona]:
    """Loads the core 2020-2024 committee personas."""
    personas_dir = PROJECT_ROOT / "personas" / "2020_2024_roster"
    core_ids = [
        "shaktikanta_das",
        "michael_patra",
        "rajiv_ranjan",
        "shashanka_bhide",
        "ashima_goyal",
        "jayanth_varma",
    ]
    personas = []
    for m_id in core_ids:
        p_file = personas_dir / f"{m_id}.yaml"
        with open(p_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        personas.append(MemberPersona(**data))
    return personas


async def run_holdout_panel():
    print("=" * 78)
    print("      RBI MPC IN SILICO: LIVE HOLDOUT EMPIRICAL DELIBERATION PANEL      ")
    print("=" * 78)

    cfg = load_config()
    if not cfg.gemini_api_key:
        print("[-] GEMINI_API_KEY is not set. Cannot run live holdout evaluation.")
        sys.exit(1)

    checkpoint_dir = PROJECT_ROOT / "data" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    results_dir = PROJECT_ROOT / "results" / "tables"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Load holdout panel from verified parquet file
    macro_path = PROJECT_ROOT / "data" / "processed" / "macro_panel.parquet"
    df_panel = pd.read_parquet(macro_path)
    df_holdout = df_panel[df_panel["meeting_date"] > "2023-04-06"].copy()
    holdout_records = df_holdout.to_dict(orient="records")

    print(f"[+] Loaded {len(holdout_records)} holdout meetings (June 2023 – August 2024).")

    # Initialize live client with safe rate-limiting pacing (12 RPM = 5s interval)
    client = LLMClient(provider="gemini")
    client._min_interval = 5.0  # 12 RPM safe pacing
    logger_run = TranscriptLogger(run_id="holdout_live_run")
    orchestrator = DebateOrchestrator(llm_client=client, logger=logger_run)
    personas = load_personas()

    results = []

    for idx, row in enumerate(holdout_records, 1):
        date_str = row["meeting_date"]
        ckpt_path = checkpoint_dir / f"holdout_meeting_{date_str}.json"

        # Check existing checkpoint
        if ckpt_path.exists():
            try:
                with open(ckpt_path, "r", encoding="utf-8") as f:
                    res = json.load(f)
                print(f"  [{idx}/{len(holdout_records)}] [CHECKPOINT HIT] Loaded {date_str} from cache.")
                results.append(res)
                continue
            except Exception as e:
                logger.warning("Corrupt checkpoint for %s: %s. Re-simulating.", date_str, e)

        # Check if verified live run already exists in live_gemini_meeting
        existing_run_outcome = PROJECT_ROOT / "runs" / "live_gemini_meeting" / "transcripts" / date_str / "rep_1" / "meeting_outcome.json"
        if existing_run_outcome.exists():
            with open(existing_run_outcome, "r", encoding="utf-8") as f:
                base_data = json.load(f)
            decision = MeetingCommitteeDecision(**base_data)
            print(f"  [{idx}/{len(holdout_records)}] [VERIFIED RUN HIT] Loaded {date_str} from live_gemini_meeting.")
        else:
            print(f"\n  [{idx}/{len(holdout_records)}] Simulating {date_str} LIVE with Google Gemini ({cfg.run.dev_model})...")
            snapshot = MacroMeetingSnapshot(**row)
            decision = await orchestrator.run_meeting(
                snapshot=snapshot,
                personas=personas,
                governor_id="shaktikanta_das",
                replicate_id=1,
                model=cfg.run.dev_model,
                temperature=0.1,
            )

        # Comparative evaluation against official RBI MPC decision
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

        res_record = {
            "meeting_date": date_str,
            "panel_subset": "holdout",
            "actual_rate_bps": int(row["real_rate_decision_bps"]),
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

        # Atomically save checkpoint
        tmp_ckpt = checkpoint_dir / f".holdout_meeting_{date_str}.json.tmp"
        with open(tmp_ckpt, "w", encoding="utf-8") as f:
            json.dump(res_record, f, indent=2)
        tmp_ckpt.replace(ckpt_path)

        results.append(res_record)
        print(f"       Outcome: Rate={decision.rate_decision_bps:+d} bps (Actual: {row['real_rate_decision_bps']:+d}) | Stance={decision.stance_decision} (Actual: {row['real_stance_decision']}) | Dissenters: {sorted(sim_dissenters)}")

    df_res = pd.DataFrame(results)

    # Save detailed holdout comparison CSV
    holdout_comp_path = results_dir / "holdout_meeting_by_meeting_comparison.csv"
    df_res.to_csv(holdout_comp_path, index=False)

    # Calculate metrics
    dir_acc = float(df_res["directional_match"].mean()) * 100.0
    exact_acc = float(df_res["rate_match"].mean()) * 100.0
    stance_acc = float(df_res["stance_match"].mean()) * 100.0

    total_tp = int(df_res["dissent_tp"].sum())
    total_fp = int(df_res["dissent_fp"].sum())
    total_fn = int(df_res["dissent_fn"].sum())

    prec = total_tp / max(total_tp + total_fp, 1)
    rec = total_tp / max(total_tp + total_fn, 1)
    f1 = (2 * prec * rec) / max(prec + rec, 1e-6)

    gate_passed = (dir_acc >= 75.0 and stance_acc >= 70.0 and f1 >= 0.50)

    summary = {
        "total_holdout_meetings": len(df_res),
        "directional_rate_accuracy_pct": round(dir_acc, 2),
        "exact_rate_accuracy_pct": round(exact_acc, 2),
        "stance_accuracy_pct": round(stance_acc, 2),
        "dissent_precision": round(prec, 4),
        "dissent_recall": round(rec, 4),
        "dissent_f1": round(f1, 4),
        "passed_validation_gate": gate_passed,
    }

    metrics_df = pd.DataFrame([summary])
    metrics_path = results_dir / "holdout_validation_live_metrics.csv"
    metrics_df.to_csv(metrics_path, index=False)

    print("\n" + "=" * 78)
    print("      LIVE HOLDOUT EMPIRICAL DELIBERATION PANEL COMPLETE       ")
    print("=" * 78)
    print(f"Total Holdout Meetings:      {summary['total_holdout_meetings']}")
    print(f"Directional Rate Accuracy:   {summary['directional_rate_accuracy_pct']:.1f}%")
    print(f"Exact Rate Match Accuracy:   {summary['exact_rate_accuracy_pct']:.1f}%")
    print(f"Policy Stance Accuracy:      {summary['stance_accuracy_pct']:.1f}%")
    print(f"Member Dissent Precision:    {summary['dissent_precision']:.2f}")
    print(f"Member Dissent Recall:       {summary['dissent_recall']:.2f}")
    print(f"Member Dissent F1 Score:     {summary['dissent_f1']:.2f}")
    print(f"Holdout Validation Gate:     {'PASSED' if gate_passed else 'RECALIBRATION NEEDED'}")
    print("=" * 78)
    print(f"Saved Holdout Comparison Table to: {holdout_comp_path}")
    print(f"Saved Holdout Metrics Table to:    {metrics_path}")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(run_holdout_panel())
