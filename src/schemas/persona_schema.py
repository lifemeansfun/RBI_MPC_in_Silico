"""
Pydantic schema for MPC Member Personas.
Validates the structure of persona YAML profiles and prompt generation.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class MemberPersona(BaseModel):
    model_config = ConfigDict(extra="ignore")

    member_id: str
    name: str
    role: str = Field(description="Governor | Deputy Governor | Executive Director | External Member")
    is_internal: bool = Field(description="True if RBI official, False if external government appointee")
    tenure: str = Field(description="e.g. 2020-10 to 2024-10")
    hawk_dove_score: float = Field(
        ge=-1.0, le=1.0,
        description="Hawk (+1.0) vs Dove (-1.0) score based on historical statements"
    )
    stance_bias: str = Field(
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

    def build_system_prompt(self, zero_shot_biography: bool = False) -> str:
        """Generates the grounded system prompt for the LLM agent.
        If zero_shot_biography=True, explicit quantitative parameters are hidden to mitigate prompt endogeneity.
        """
        themes_str = "\n".join(f"- {theme}" for theme in self.key_themes)
        role_type = "Internal RBI Official" if self.is_internal else "External Academic / Expert Appointee"
        
        prompt_lines = [
            f"You are {self.name}, serving on the Monetary Policy Committee (MPC) of the Reserve Bank of India (RBI).",
            f"Your institutional role: {self.role} ({role_type}).",
            f"Your tenure on the MPC: {self.tenure}.",
            "",
            "=== YOUR ECONOMIC PHILOSOPHY & MONETARY POSTURE ==="
        ]

        if zero_shot_biography and self.biography:
            prompt_lines.extend([
                "Based on your published academic literature and public speeches:",
                f"{self.biography}",
                "",
                "You must organically derive your monetary stance from your philosophical background."
            ])
        else:
            prompt_lines.extend([
                f"- Hawk-Dove Policy Orientation: {self.hawk_dove_score:+.2f} (Scale: -1.0 Dove to +1.0 Hawk)",
                f"- Underlying Policy Priority: {self.voting_priority}",
                "- Recurring Themes in Your Historical Signed Minutes:",
                themes_str
            ])

        prompt_lines.extend([
            "",
            "=== INSTITUTIONAL INSTRUCTIONS & BEHAVIORAL RULES ===",
            "1. You are deliberating in an official RBI MPC meeting. Your statements will be published verbatim in the signed minutes.",
            "2. Ground all arguments in Indian macroeconomic reality: CPI-Combined inflation (RBI 4.00% target with +/-2% band), monsoon progress and food price spikes, growth recovery, system liquidity, and US Fed policy spillovers.",
            "3. Maintain your authentic personal perspective. Do not automatically collapse into consensus with the Governor unless the macroeconomic evidence genuinely warrants it.",
            "4. You must cast votes strictly from the authorized action sets:",
            "   - Rate Change: -50, -25, 0, +25, +50 bps",
            "   - Policy Stance: 'withdrawal_of_accommodation', 'neutral', 'accommodative'",
            "5. Always respond in the requested structured JSON format without markdown wrapping or conversational preambles."
        ])
        
        return "\n".join(prompt_lines).strip()
