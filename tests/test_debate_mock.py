"""
Integration test for the 4-round behavioral debate loop using offline Mock LLM client.
Verifies complete deliberation mechanics, transcript logging, and §45ZI aggregation.
"""

import pytest
import tempfile
from pathlib import Path

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger


@pytest.fixture
def mock_personas():
    return [
        MemberPersona(
            member_id="shaktikanta_das",
            name="Shaktikanta Das",
            role="Governor",
            is_internal=True,
            tenure="2018-present",
            hawk_dove_score=0.1,
            voting_priority="Consensus and disinflation",
        ),
        MemberPersona(
            member_id="michael_patra",
            name="Michael Patra",
            role="Deputy Governor",
            is_internal=True,
            tenure="2020-present",
            hawk_dove_score=0.75,
            voting_priority="Inflation hawk",
        ),
        MemberPersona(
            member_id="rajiv_ranjan",
            name="Rajiv Ranjan",
            role="Executive Director",
            is_internal=True,
            tenure="2022-present",
            hawk_dove_score=0.35,
            voting_priority="System liquidity alignment",
        ),
        MemberPersona(
            member_id="jayanth_varma",
            name="Jayanth R. Varma",
            role="External Member",
            is_internal=False,
            tenure="2020-2024",
            hawk_dove_score=-0.60,
            voting_priority="Growth critic, stance dissenter",
        ),
        MemberPersona(
            member_id="ashima_goyal",
            name="Ashima Goyal",
            role="External Member",
            is_internal=False,
            tenure="2020-2024",
            hawk_dove_score=-0.25,
            voting_priority="Real rate targeting",
        ),
        MemberPersona(
            member_id="shashanka_bhide",
            name="Shashanka Bhide",
            role="External Member",
            is_internal=False,
            tenure="2020-2024",
            hawk_dove_score=0.20,
            voting_priority="Monsoon and food supplies",
        ),
    ]


@pytest.fixture
def sample_snapshot():
    return MacroMeetingSnapshot(
        meeting_date="2023-08-10",
        current_repo_rate_pct=6.50,
        cpi_headline_yoy_pct=5.40,
        cpi_core_yoy_pct=4.10,
        iip_growth_yoy_pct=5.20,
        output_gap_pct=0.10,
        system_liquidity_cr=-15000.0,
        usd_inr_exchange_rate=82.75,
        brent_crude_usd_bbl=84.00,
        us_fed_funds_rate_pct=5.50,
    )


@pytest.mark.asyncio
async def test_full_mock_debate_simulation(mock_personas, sample_snapshot):
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TranscriptLogger(run_id="test_mock_run", output_root=Path(tmpdir))

        client = LLMClient(provider="mock", cache_enabled=False)
        orchestrator = DebateOrchestrator(llm_client=client, logger=logger)

        decision = await orchestrator.run_meeting(
            snapshot=sample_snapshot,
            personas=mock_personas,
            governor_id="shaktikanta_das",
            replicate_id=1,
            model="gemini-2.5-flash",
        )

        assert decision.meeting_date == "2023-08-10"
        assert decision.rate_decision_bps in [-50, -25, 0, 25, 35, 40, 50]
        assert decision.stance_decision in ["withdrawal_of_accommodation", "neutral", "accommodative"]
        assert len(decision.member_votes) == 6

        # Verify transcripts were generated on disk
        rep_dir = logger._directory("2023-08-10", 1, "legacy", "full")
        assert (rep_dir / "meeting_outcome.json").exists()
        assert (rep_dir / "round_1_shaktikanta_das.json").exists()
        assert (rep_dir / "round_4_jayanth_varma.json").exists()
