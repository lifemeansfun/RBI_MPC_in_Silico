"""
Defensive Coding, Validation, and Anti-Hallucination Unit Tests.
Verifies input sanitization, schema resilience, fallback triggers, and negative constraints.
"""

import pytest
from src.schemas.debate_schema import (
    InitialStanceOutput,
    DeliberationOutput,
    FinalVoteOutput,
)
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.behavioral.debate_orchestrator import DebateOrchestrator


def test_schema_coercion_dirty_strings():
    """Verifies that dirty rate strings and irregular stance casing are defensively sanitized."""
    # Dirty rate strings with plus signs, "bps", and spaces
    out = InitialStanceOutput(
        member_id="jayanth_varma",
        member_name="Jayanth R. Varma",
        proposed_rate_change_bps="+25 bps",
        proposed_stance="WITHDRAWAL OF ACCOMMODATION",
        key_rationale="Testing dirty input string sanitization.",
    )
    assert out.proposed_rate_change_bps == 25
    assert out.proposed_stance == "withdrawal_of_accommodation"

    # Out of range rate snapping to closest statutory action
    out2 = FinalVoteOutput(
        member_id="michael_patra",
        member_name="Michael Debabrata Patra",
        final_rate_vote_bps="48",  # dirty float-like string near 50
        final_stance_vote="Withdrawal-of-accommodation",
        official_statement_rationale="Testing nearest discrete statutory action snapping.",
    )
    assert out2.final_rate_vote_bps == 50
    assert out2.final_stance_vote == "withdrawal_of_accommodation"


def test_anti_hallucination_macro_prompt_constraints():
    """Verifies that MacroMeetingSnapshot generates strict anti-hallucination instructions."""
    snapshot = MacroMeetingSnapshot(
        meeting_date="2023-08-10",
        current_repo_rate_pct=6.50,
        cpi_headline_yoy_pct=7.44,
        cpi_core_yoy_pct=4.90,
        cpi_food_yoy_pct=11.51,
        iip_growth_yoy_pct=5.70,
        output_gap_pct=0.60,
        system_liquidity_cr=120000.0,
        usd_inr_exchange_rate=82.80,
        brent_crude_usd_bbl=86.40,
        us_fed_funds_rate_pct=5.33,
        prev_stance="withdrawal_of_accommodation",
    )

    prompt = snapshot.to_prompt_text()
    assert "OFFICIAL MACROECONOMIC BRIEFING FOR MPC MEETING: 2023-08-10" in prompt
    assert "7.44%" in prompt
    assert "6.50%" in prompt
    assert "CRITICAL GROUNDING CONSTRAINT:" in prompt
    assert "Do NOT cite fictitious numbers or invent macroeconomic indicators" in prompt


def test_defensive_rate_heuristic_calibration():
    """Verifies that the emergency heuristic behaves economically consistent with member personas."""
    high_cpi_snapshot = MacroMeetingSnapshot(
        meeting_date="2022-06-08",
        current_repo_rate_pct=4.40,
        cpi_headline_yoy_pct=7.04,
        cpi_core_yoy_pct=6.20,
        prev_stance="accommodative",
    )

    hawk_persona = MemberPersona(
        member_id="michael_patra",
        name="Michael Debabrata Patra",
        role="Deputy Governor",
        is_internal=True,
        tenure="2020-01 to present",
        hawk_dove_score=0.70,
        stance_bias="withdrawal_of_accommodation",
        voting_priority="Strict inflation hawk",
    )

    dove_persona = MemberPersona(
        member_id="jayanth_varma",
        name="Jayanth R. Varma",
        role="External Member",
        is_internal=False,
        tenure="2020-10 to 2024-10",
        hawk_dove_score=-0.65,
        stance_bias="neutral",
        voting_priority="Growth preservation",
    )

    # Under high CPI (7.04%), hawk should recommend a hike (+50 or +25 bps)
    hawk_rate = DebateOrchestrator._compute_defensive_rate_heuristic(hawk_persona, high_cpi_snapshot)
    assert hawk_rate in [25, 50]

    # Under lower CPI (3.5%), dove should recommend a pause (0) or cut (-25)
    low_cpi_snapshot = MacroMeetingSnapshot(
        meeting_date="2024-08-08",
        current_repo_rate_pct=6.50,
        cpi_headline_yoy_pct=3.54,
        cpi_core_yoy_pct=3.15,
        prev_stance="withdrawal_of_accommodation",
    )
    dove_rate = DebateOrchestrator._compute_defensive_rate_heuristic(dove_persona, low_cpi_snapshot)
    assert dove_rate in [-25, 0]


def test_persona_system_prompt_anti_hallucination_rules():
    """Verifies that MemberPersona system prompt includes institutional behavioral guardrails."""
    persona = MemberPersona(
        member_id="shashanka_bhide",
        name="Dr. Shashanka Bhide",
        role="External Member",
        is_internal=False,
        tenure="2020-10 to 2024-10",
        hawk_dove_score=0.20,
        stance_bias="withdrawal_of_accommodation",
        voting_priority="Agricultural economist vigilant on food prices",
        key_themes=["Food price pressures require close monitoring"],
    )

    sys_prompt = persona.build_system_prompt()
    assert "Dr. Shashanka Bhide" in sys_prompt
    assert "External Academic / Expert Appointee" in sys_prompt
    assert "Ground all arguments in Indian macroeconomic reality" in sys_prompt
    assert "Rate Change: -50, -25, 0, +25, +50 bps" in sys_prompt
