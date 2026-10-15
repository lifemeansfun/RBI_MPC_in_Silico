"""
Contamination Audit Runner (Mitigation for Data Leakage).
Tests the prompt output to ensure no real entities are leaked in the masked prompt.
"""
import sys
import logging
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.validation.data_perturbation import DataPerturbator

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def run_contamination_audit():
    print("=" * 80)
    print("   RUNNING ENTITY-MASKED PERTURBATION AUDIT (DATA LEAKAGE MITIGATION)")
    print("=" * 80)

    # 1. Test Entity Masking
    sample_text = (
        "The Reserve Bank of India, under the leadership of Shaktikanta Das and Michael Patra, "
        "has decided to hold the INR rate steady due to the Monsoon departure. The system liquidity "
        "is currently at 50000 Crore Rupees."
    )
    masked_text = DataPerturbator.mask_entities_in_text(sample_text)
    
    print("\n--- ORIGINAL TEXT ---")
    print(sample_text)
    print("\n--- MASKED TEXT ---")
    print(masked_text)

    assert "Reserve Bank of India" not in masked_text
    assert "Shaktikanta Das" not in masked_text
    assert "Michael Patra" not in masked_text
    assert "Crore" not in masked_text
    
    print("\n[PASS] Entity masking successfully scrubs real-world RBI identifiers.")

    # 2. Test Macroeconomic Shock Injection
    base_snap = MacroMeetingSnapshot(
        meeting_date="2023-08-10",
        current_repo_rate_pct=6.50,
        cpi_headline_yoy_pct=7.44,
        cpi_core_yoy_pct=4.90,
        cpi_food_yoy_pct=11.51,
        output_gap_pct=0.60,
        us_fed_funds_rate_pct=5.33,
        prev_stance="withdrawal_of_accommodation"
    )

    perturbed_snap = DataPerturbator.apply_macro_shock(base_snap, cpi_shock=2.5, food_shock=4.0)

    print("\n--- BASELINE SNAPSHOT ---")
    print(f"Headline CPI: {base_snap.cpi_headline_yoy_pct}% | Food CPI: {base_snap.cpi_food_yoy_pct}%")
    
    print("\n--- PERTURBED (SHOCKED) SNAPSHOT ---")
    print(f"Headline CPI: {perturbed_snap.cpi_headline_yoy_pct}% | Food CPI: {perturbed_snap.cpi_food_yoy_pct}%")

    assert math.isclose(perturbed_snap.cpi_headline_yoy_pct, 9.94, abs_tol=1e-5)
    assert math.isclose(perturbed_snap.cpi_food_yoy_pct, 15.51, abs_tol=1e-5)

    print("\n[PASS] Data perturbation accurately injects macro shocks.")

    # 3. Test Full Prompt Masking
    masked_prompt = DataPerturbator.get_masked_prompt(base_snap)
    assert "Reserve Bank of India" not in masked_prompt
    assert "RBI" not in masked_prompt
    assert "INR" not in masked_prompt
    
    print("\n[PASS] Full prompt correctly masked and generated.")
    print("=" * 80)
    print("   CONTAMINATION AUDIT SUCCESSFUL")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = run_contamination_audit()
    sys.exit(0 if success else 1)
