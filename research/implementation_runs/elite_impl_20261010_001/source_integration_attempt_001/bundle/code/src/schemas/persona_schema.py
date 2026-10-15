"""
Pydantic schema for MPC Member Personas.
Validates the structure of persona YAML profiles and prompt generation.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict
from src.schemas.decision_space import RATE_ACTIONS_BPS, STANCE_ACTIONS, StanceType


class MemberPersona(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    member_id: str
    name: str
    role: str = Field(description="Governor | Deputy Governor | Executive Director | External Member")
    is_internal: bool = Field(description="True if RBI official, False if external government appointee")
    tenure: str = Field(description="e.g. 2020-10 to 2024-10")
    hawk_dove_score: float = Field(
        ge=-1.0, le=1.0,
        description="Hawk (+1.0) vs Dove (-1.0) score based on historical statements"
    )
    stance_bias: StanceType = Field(
        default="withdrawal_of_accommodation",
        description="Historical tendency on stance (withdrawal_of_accommodation, neutral, accommodative)"
    )
    voting_priority: str = Field(
        description="Summary of primary monetary policy objective and behavioral posture"
    )
    biography: Optional[str] = Field(
        default=None,
        description="Double-blind qualitative abstract of academic/policy background for zero-shot prompting."
    )
    key_themes: list[str] = Field(
        default_factory=list,
        description="3-5 recurring economic concepts or arguments cited in official minutes"
    )
    system_prompt_override: Optional[str] = None
    calibration_cutoff: Optional[str] = None
    corpus_manifest_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provenance_status: Literal["legacy_unverified", "dated_corpus", "assumed"] = "legacy_unverified"

    def build_system_prompt(self, zero_shot_biography: bool = False, mask_identity: bool = False) -> str:
        """Generates the grounded system prompt for the LLM agent.
        If zero_shot_biography=True, explicit quantitative parameters are hidden to mitigate prompt endogeneity.
        """
        themes_str = "\n".join(f"- {theme}" for theme in self.key_themes)
        role_type = "Internal RBI Official" if self.is_internal else "External Academic / Expert Appointee"
        
        prompt_lines = [
            f"You are {'a simulated committee member' if mask_identity else self.name}, serving in a simulated RBI Monetary Policy Committee (MPC).",
            f"Member ID: {self.member_id}",
            f"Your institutional role: {self.role} ({role_type}).",
            f"Persona evidence status: {self.provenance_status}.",
            "",
            "=== YOUR ECONOMIC PHILOSOPHY & MONETARY POSTURE ==="
        ]

        if zero_shot_biography and self.biography:
            prompt_lines.extend([
                "Supplied biography (its availability must be established by the experiment):",
                f"{self.biography}",
                "",
                "Use only this supplied background, without recalling historical meeting outcomes."
            ])
        else:
            prompt_lines.extend([
                f"- Lexical orientation statistic: {self.hawk_dove_score:+.2f} (Scale: -1.0 Dove to +1.0 Hawk; not a validated structural preference)",
                f"- Underlying Policy Priority: {self.voting_priority}",
                "- Recurring Themes in Your Historical Signed Minutes:",
                themes_str
            ])

        prompt_lines.extend([
            "",
            "=== INSTITUTIONAL INSTRUCTIONS & BEHAVIORAL RULES ===",
            "1. You are deliberating in a simulation. Your outputs are generated statements, not actual official minutes.",
            "2. Ground all arguments in Indian macroeconomic reality: CPI-Combined inflation (RBI 4.00% target with +/-2% band), monsoon progress and food price spikes, growth recovery, system liquidity, and US Fed policy spillovers.",
            "3. Maintain your authentic personal perspective. Do not automatically collapse into consensus with the Governor unless the macroeconomic evidence genuinely warrants it.",
            "4. You must cast votes strictly from the authorized action sets:",
            "   - Rate Change: " + ", ".join(f"{a:+d}" if a > 0 else str(a) for a in RATE_ACTIONS_BPS) + " bps",
            "   - Policy Stance: " + ", ".join(repr(s) for s in STANCE_ACTIONS),
            "5. Always respond in the requested structured JSON format without markdown wrapping or conversational preambles."
        ])
        
        return "\n".join(prompt_lines).strip()
