"""
Executes a live 4-round multi-agent deliberation meeting using Google Gemini (gemini-3.1-flash-lite)
with verified real macroeconomic data and calibrated empirical personas.
"""

import asyncio
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from src.infra.config_loader import load_config
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.behavioral.debate_orchestrator import DebateOrchestrator


async def main():
    print("=" * 72)
    print("      RBI MPC IN SILICO — LIVE GOOGLE GEMINI MEETING SIMULATION")
    print("=" * 72)

    cfg = load_config()
    print(f"[+] Provider: {cfg.run.provider} | Model: {cfg.run.dev_model}")
    if not cfg.gemini_api_key:
        print("[-] GEMINI_API_KEY not found in environment. Please set it in .env.")
        return

    # Load representative meeting from real panel (August 2023 Tomato/Food Surge)
    macro_path = Path("data/processed/macro_panel.parquet")
    df_panel = pd.read_parquet(macro_path)
    aug23_row = df_panel[df_panel["meeting_date"] == "2023-08-10"].iloc[0].to_dict()
    snapshot = MacroMeetingSnapshot(**aug23_row)

    print(f"[+] Simulating Meeting: {snapshot.meeting_date}")
    print(f"    Current Repo Rate: {snapshot.current_repo_rate_pct:.2f}% | Headline CPI: {snapshot.cpi_headline_yoy_pct:.2f}% | Food CPI: {snapshot.cpi_food_yoy_pct:.2f}%")

    # Load calibrated personas from personas/2020_2024_roster/
    personas_dir = PROJECT_ROOT / "personas" / "2020_2024_roster"
    active_ids = [
        "shaktikanta_das",
        "michael_patra",
        "rajiv_ranjan",
        "shashanka_bhide",
        "ashima_goyal",
        "jayanth_varma",
    ]
    personas = []
    for m_id in active_ids:
        p_file = personas_dir / f"{m_id}.yaml"
        with open(p_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        personas.append(MemberPersona(**data))

    print(f"[+] Loaded {len(personas)} calibrated personas from {personas_dir}.")

    client = LLMClient(provider="gemini")
    logger = TranscriptLogger(run_id="live_gemini_meeting")
    orchestrator = DebateOrchestrator(llm_client=client, logger=logger)

    print("\n[+] Initiating live 4-round deliberation with Google Gemini...")
    decision = await orchestrator.run_meeting(
        snapshot=snapshot,
        personas=personas,
        governor_id="shaktikanta_das",
        replicate_id=1,
        model=cfg.run.dev_model,
        temperature=0.1,  # Low entropy for high empirical consistency
    )

    print("\n" + "-" * 72)
    print("LIVE COMMITTEE OUTCOME (RBI ACT §45ZL AGGREGATION)")
    print("-" * 72)
    print(f"Policy Repo Rate Decision: {decision.rate_decision_bps:+d} bps (Tally: {decision.rate_vote_tally})")
    print(f"Policy Stance Decision:    {decision.stance_decision.replace('_', ' ').title()} (Tally: {decision.stance_vote_tally})")
    print(f"Governor Tie-Breaker:      {'Exercised' if decision.tie_broken_by_governor_rate else 'Majority Decision'}")
    print(f"Rate Dissenters:           {decision.dissenting_members_rate or 'None (Unanimous)'}")
    print(f"Stance Dissenters:         {decision.dissenting_members_stance or 'None (Unanimous)'}")
    print("\nIndividual Member Final Votes:")
    for v in decision.member_votes:
        role = "Internal" if v.is_internal else "External"
        print(f" - {v.member_name:<28} ({role:<8}): Rate: {v.final_rate_vote_bps:+d} bps | Stance: {v.final_stance_vote:<28} | Dissent: {'Yes' if v.dissenting_on_stance or v.dissenting_on_rate else 'No'}")

    print(f"\n[+] Total Cost & Tokens: {client.governor.get_summary()}")
    print(f"[+] Fallbacks Used: {decision.fallbacks_count}")
    print(f"[+] Transcripts saved to: runs/live_gemini_meeting/transcripts/{snapshot.meeting_date}/rep_1/")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
