"""
Zero-Shot Biographical Persona Test (Mitigation for Prompt Endogeneity).
"""
import sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas.persona_schema import MemberPersona

def test_zero_shot():
    p = PROJECT_ROOT / "personas" / "2020_2024_roster" / "jayanth_varma.yaml"
    with open(p, "r") as f:
        data = yaml.safe_load(f)
    
    persona = MemberPersona(**data)
    
    # 1. Test Baseline Prompt
    baseline = persona.build_system_prompt(zero_shot_biography=False)
    assert "-0.31" in baseline
    assert "Hawk-Dove Policy Orientation" in baseline
    
    # 2. Test Zero-Shot Prompt
    zero_shot = persona.build_system_prompt(zero_shot_biography=True)
    assert "-0.31" not in zero_shot
    assert "Hawk-Dove Policy Orientation" not in zero_shot
    assert "Professor of Finance" in zero_shot
    assert "highly critical of excessively high real interest rates" in zero_shot.lower()
    
    print("[PASS] Zero-Shot Biographical injection successfully removes quantitative anchors.")
    return True

if __name__ == "__main__":
    success = test_zero_shot()
    sys.exit(0 if success else 1)
