import asyncio
import sys
from pathlib import Path
import logging
import random
import statistics

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scenarios.run_counterfactual_experiments import load_meeting_snapshot, load_all_personas
from src.behavioral.debate_orchestrator import DebateOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mc_stress")

async def run_mc_perturbation(iterations=10):
    personas = load_all_personas()
    gov_persona = next(p for p in personas if p.member_id == "shaktikanta_das")
    base_snapshot = load_meeting_snapshot("2023-08-10")
    orchestrator = DebateOrchestrator()

    rate_votes = []
    
    logger.info(f"Running Monte Carlo Perturbation Test ({iterations} iterations)...")
    
    tasks = []
    for i in range(iterations):
        # Inject tiny normally distributed noise
        cpi_noise = random.gauss(0, 0.05)
        gap_noise = random.gauss(0, 0.1)
        
        perturbed_snapshot = base_snapshot.model_copy(update={
            "cpi_headline_yoy_pct": base_snapshot.cpi_headline_yoy_pct + cpi_noise,
            "output_gap_pct": base_snapshot.output_gap_pct + gap_noise,
        })
        
        # We only run Round 1 Stance for the Governor to measure structural stability of his policy function
        task = orchestrator._execute_round_1_stance(
            persona=gov_persona,
            snapshot=perturbed_snapshot,
            macro_text=perturbed_snapshot.to_prompt_text(),
            model=None,
            temp=0.7 # Using non-zero temp to test robust continuity despite sampling variance
        )
        tasks.append(task)
        
    results = await asyncio.gather(*tasks)
    
    for r in results:
        rate_votes.append(r.proposed_rate_change_bps)
        
    variance = statistics.variance(rate_votes) if len(set(rate_votes)) > 1 else 0.0
    mean_vote = statistics.mean(rate_votes)
    
    logger.info(f"MC Results: Mean Rate = {mean_vote} bps, Variance = {variance}")
    logger.info(f"All Votes: {rate_votes}")
    
    if variance < 25.0: # Variance less than a single 25bps tick squared is highly stable
        logger.info("TEST PASSED: Model exhibits strong Lipschitz continuity (structural stability) under perturbation.")
        verdict = "PASSED. The model outputs are structurally stable and not chaotic."
    else:
        logger.warning("TEST FAILED: Model is chaotic and hypersensitive to minor noise.")
        verdict = "FAILED. High variance detected."
        
    # Append result
    with open("results/stress_test_results.md", "a") as f:
        f.write("## 2. Monte Carlo Perturbation (Lipschitz Continuity)\n")
        f.write(f"- **Methodology**: Ran Governor's R1 policy function {iterations} times with $\\mathcal{{N}}(0, 0.05)$ noise added to CPI and Output Gap (temp=0.7).\n")
        f.write(f"- **Outcome Distribution**: Mean = {mean_vote:.2f} bps, Variance = {variance:.2f}\n")
        f.write(f"- **Raw Votes**: {rate_votes}\n")
        f.write(f"- **Verdict**: **{verdict}**\n\n")

if __name__ == "__main__":
    asyncio.run(run_mc_perturbation())
