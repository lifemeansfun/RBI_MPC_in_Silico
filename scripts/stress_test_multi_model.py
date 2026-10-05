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
logger = logging.getLogger("multi_model_stress")

async def run_multi_model_test():
    personas = load_all_personas()
    gov_persona = next(p for p in personas if p.member_id == "shaktikanta_das")
    base_snapshot = load_meeting_snapshot("2023-08-10")
    
    orchestrator = DebateOrchestrator()
    
    models = ["gemini-3.1-flash-lite", "gemini-1.5-pro"]
    results_map = {}
    
    for m in models:
        try:
            logger.info(f"Running Round 1 with model: {m}")
            r1 = await orchestrator._execute_round_1_stance(
                persona=gov_persona,
                snapshot=base_snapshot,
                macro_text=base_snapshot.to_prompt_text(),
                model=m,
                temp=0.0
            )
            results_map[m] = r1.proposed_rate_change_bps
            logger.info(f"[{m}] Rate Vote: {r1.proposed_rate_change_bps} bps")
        except Exception as e:
            logger.error(f"Failed to run model {m}: {e}")
            results_map[m] = "FAILED"
            
    # Check consistency
    if results_map.get("gemini-3.1-flash-lite") == results_map.get("gemini-1.5-pro"):
        logger.info("TEST PASSED: High Inter-Rater Reliability across model architectures.")
        verdict = "PASSED. Both models output the identical rate decision based on the same economic schema."
    else:
        logger.warning("TEST FAILED: Model outputs diverged, suggesting artifact of training rather than schema robustness.")
        verdict = "FAILED/INCONCLUSIVE. Model divergence detected or API unavailable."

    # Save result
    with open("results/stress_test_results.md", "a") as f:
        f.write("## 4. Cross-Model Multi-Agent Matrix (Inter-Rater Reliability)\n")
        f.write("- **Methodology**: Evaluated the 2023-08-10 snapshot simultaneously across `gemini-3.1-flash-lite` and `gemini-1.5-pro` to test structural prompt robustness over model RLHF bias.\n")
        for m, v in results_map.items():
            f.write(f"- **{m} Output**: {v} bps\n")
        f.write(f"- **Verdict**: **{verdict}**\n\n")

if __name__ == "__main__":
    asyncio.run(run_multi_model_test())
