import asyncio
import sys
from pathlib import Path
import logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scenarios.run_counterfactual_experiments import load_meeting_snapshot, load_all_personas
from src.behavioral.debate_orchestrator import DebateOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ablation_stress")

async def run_ablation_test():
    personas = load_all_personas()
    gov_persona = next(p for p in personas if p.member_id == "shaktikanta_das")
    
    # 1. Base Snapshot: 2023-08-10 (Historically a Pause/0 bps)
    base_snapshot = load_meeting_snapshot("2023-08-10")
    
    # 2. Ablated Snapshot: Wipe out inflation and growth data, simulating extreme deflation
    # If the model is cheating using the date, it will output 0 bps (historical reality).
    # If it is honestly reasoning, a CPI of 1.0% should trigger a massive rate cut.
    ablated_snapshot = base_snapshot.model_copy(update={
        "cpi_headline_yoy_pct": 1.0, # Way below 4% target
        "cpi_core_yoy_pct": 1.0,
        "cpi_food_yoy_pct": 1.0,
        "output_gap_pct": -5.0, # Massive recession
        "iip_growth_yoy_pct": -10.0,
    })

    orchestrator = DebateOrchestrator()
    
    logger.info("Running Round 1 with Information-Ablated 'Blindfolded' Snapshot...")
    
    r1 = await orchestrator._execute_round_1_stance(
        persona=gov_persona,
        snapshot=ablated_snapshot,
        macro_text=ablated_snapshot.to_prompt_text(),
        model=None,
        temp=0.0
    )
    
    logger.info(f"Ablation Output Rate: {r1.proposed_rate_change_bps}")
    logger.info(f"Ablation Output Stance: {r1.proposed_stance}")
    logger.info(f"Ablation Output Rationale: {r1.key_rationale}")

    if r1.proposed_rate_change_bps == 0:
        logger.warning("TEST FAILED: Temporal Data Leakage detected! Model guessed the historical 0 bps pause despite being fed deep recession data.")
        verdict = "FAILED. Temporal data leakage confirmed."
    elif r1.proposed_rate_change_bps < 0:
        logger.info("TEST PASSED: Model ignored the historical date and correctly cut rates in response to the deep recession data.")
        verdict = "PASSED. Model strictly followed the provided macro data and cut rates, ignoring historical reality for that date."
    else:
        logger.warning("TEST FAILED: Unexpected behavior.")
        verdict = "FAILED. Unexpected behavior."

    # Save result
    with open("results/stress_test_results.md", "a") as f:
        f.write("## 3. Information Ablation (The \"Blindfolded\" Committee)\n")
        f.write("- **Methodology**: Took the 2023-08-10 meeting (historically a 0 bps pause) and overrode CPI to 1.0% and Output Gap to -5.0% to test for temporal data leakage.\n")
        f.write(f"- **Outcome Rate**: {r1.proposed_rate_change_bps} bps\n")
        f.write(f"- **Outcome Rationale**: {r1.key_rationale}\n")
        f.write(f"- **Verdict**: **{verdict}**\n\n")

if __name__ == "__main__":
    asyncio.run(run_ablation_test())
