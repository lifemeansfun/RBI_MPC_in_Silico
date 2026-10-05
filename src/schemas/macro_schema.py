"""
Pydantic schemas for Macroeconomic Data Panel and meeting snapshots.
Defines strict validation for all series entering the simulation.
Includes defensive bounds, type coercion, and prompt formatting with anti-hallucination constraints.
"""

from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator


class MacroMeetingSnapshot(BaseModel):
    """
    A single meeting's observable macroeconomic snapshot presented to all committee members.
    Every number here corresponds to actual data available at the time of the meeting.
    """
    model_config = ConfigDict(extra="ignore", frozen=False)

    meeting_date: str = Field(description="Meeting date in YYYY-MM-DD format")
    current_repo_rate_pct: float = Field(ge=0.0, le=20.0, description="Pre-meeting policy repo rate (e.g., 6.50)")
    cpi_headline_yoy_pct: float = Field(description="Latest available headline CPI YoY (e.g., 5.4)")
    cpi_core_yoy_pct: float = Field(description="Latest available Core CPI YoY (e.g., 3.8)")
    cpi_food_yoy_pct: Optional[float] = Field(default=None, description="Food CPI YoY inflation")
    iip_growth_yoy_pct: Optional[float] = Field(default=0.0, description="Index of Industrial Production YoY growth")
    gva_growth_yoy_pct: Optional[float] = Field(default=None, description="Latest quarterly Gross Value Added growth")
    output_gap_pct: Optional[float] = Field(default=0.0, description="HP-filtered output gap estimate (y - y*) in percentage")
    system_liquidity_cr: Optional[float] = Field(default=0.0, description="Net LAF liquidity in INR Crores (+ surplus, - deficit)")
    usd_inr_exchange_rate: Optional[float] = Field(default=82.5, ge=40.0, le=150.0, description="Spot USD/INR rate")
    brent_crude_usd_bbl: Optional[float] = Field(default=80.0, ge=10.0, le=250.0, description="Brent crude price in USD per barrel")
    us_fed_funds_rate_pct: Optional[float] = Field(default=5.0, ge=0.0, le=20.0, description="US Federal Funds upper target rate")
    monsoon_departure_lpa_pct: Optional[float] = Field(
        default=0.0, description="Cumulative monsoon rainfall departure from LPA in percentage"
    )
    prev_stance: str = Field(
        default="withdrawal_of_accommodation",
        description="Prevailing policy stance prior to the meeting"
    )

    # Optional Ground Truth columns for historical backtesting and evaluation
    real_rate_decision_bps: Optional[int] = Field(default=None, description="Actual RBI rate change in bps")
    real_stance_decision: Optional[str] = Field(default=None, description="Actual stance adopted")
    real_dissenters: Optional[list[str]] = Field(default_factory=list, description="List of actual dissenting member IDs")

    @field_validator("meeting_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        parts = v.strip().split("-")
        if len(parts) != 3 or len(parts[0]) != 4:
            raise ValueError(f"Invalid date format '{v}', expected YYYY-MM-DD")
        return v.strip()

    def to_prompt_text(self) -> str:
        """
        Formats the macro snapshot into a clear, readable text block for LLM prompts.
        Embeds explicit anti-hallucination grounding instructions.
        """
        lines = [
            f"=== OFFICIAL MACROECONOMIC BRIEFING FOR MPC MEETING: {self.meeting_date} ===",
            f"- Current Policy Repo Rate: {self.current_repo_rate_pct:.2f}%",
            f"- Prevailing Policy Stance: {self.prev_stance.replace('_', ' ').title()}",
            f"- Headline CPI Inflation (YoY): {self.cpi_headline_yoy_pct:.2f}% (Statutory RBI Target: 4.00%, Tolerance Band: 2.00% - 6.00%)",
            f"- Core CPI Inflation (YoY): {self.cpi_core_yoy_pct:.2f}%",
        ]
        if self.cpi_food_yoy_pct is not None:
            lines.append(f"- Food CPI Inflation (YoY): {self.cpi_food_yoy_pct:.2f}%")
        if self.iip_growth_yoy_pct is not None:
            lines.append(f"- Industrial Production (IIP YoY): {self.iip_growth_yoy_pct:.2f}%")
        if self.gva_growth_yoy_pct is not None:
            lines.append(f"- Gross Value Added (GVA Growth YoY): {self.gva_growth_yoy_pct:.2f}%")
        if self.output_gap_pct is not None:
            lines.append(f"- Estimated Output Gap: {self.output_gap_pct:+.2f}%")
        if self.system_liquidity_cr is not None:
            lines.append(f"- Banking System Net Liquidity: {self.system_liquidity_cr:+,.0f} Crore INR")
        if self.usd_inr_exchange_rate is not None:
            lines.append(f"- USD/INR Exchange Rate: {self.usd_inr_exchange_rate:.2f}")
        if self.brent_crude_usd_bbl is not None:
            lines.append(f"- Brent Crude Oil: ${self.brent_crude_usd_bbl:.2f} / barrel")
        if self.us_fed_funds_rate_pct is not None:
            lines.append(f"- US Federal Funds Rate: {self.us_fed_funds_rate_pct:.2f}%")
        if self.monsoon_departure_lpa_pct is not None:
            lines.append(f"- Monsoon Rainfall Departure from LPA: {self.monsoon_departure_lpa_pct:+.1f}%")
        lines.append("=========================================================================")
        lines.append("CRITICAL GROUNDING CONSTRAINT:")
        lines.append("You MUST ground your reasoning ONLY in the data points above. Do NOT cite fictitious numbers or invent macroeconomic indicators not present in this briefing.")
        lines.append("=========================================================================")
        return "\n".join(lines)


# Convenient alias
MacroSnapshot = MacroMeetingSnapshot
