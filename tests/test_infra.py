"""
Unit tests for Infrastructure components: ConfigLoader, CostGovernor, LLMCache, and LLMClient.
Can run 100% offline without external API keys.
"""

import pytest
import tempfile
from pathlib import Path

from src.infra.config_loader import load_config, get_config
from src.infra.cost_governor import CostGovernor, BudgetExceededError
from src.infra.cache import LLMCache
from src.infra.llm_client import LLMClient
from src.schemas.debate_schema import InitialStanceOutput, FinalVoteOutput


def test_config_loader():
    cfg = load_config()
    assert cfg.project_name == "RBI_MPC_In_Silico"
    assert cfg.run.provider in ["gemini", "mock", "openai", "anthropic", "ollama"]
    assert cfg.decision_space.action_set_bps == [-50, -25, 0, 25, 35, 40, 50]
    assert cfg.decision_space.simulate_stance is True
    assert cfg.taylor_rule.r_star_pct == 1.4
    assert cfg.taylor_rule.smoothing_rho == 0.75


def test_cost_governor_tracking():
    gov = CostGovernor(budget_cap_usd=1.0)
    # Record 100,000 input tokens and 50,000 output tokens for gemini-3.1-flash-lite
    # Input rate: $0.25/M, Output rate: $1.50/M
    cost = gov.record_usage("gemini-3.1-flash-lite", 100_000, 50_000)
    expected_cost = (100_000 / 1e6) * 0.25 + (50_000 / 1e6) * 1.50
    assert abs(cost - expected_cost) < 1e-6

    summary = gov.get_summary()
    assert summary["call_count"] == 1
    assert summary["total_input_tokens"] == 100_000
    assert summary["total_output_tokens"] == 50_000
    assert summary["budget_remaining_usd"] < 1.0


def test_cost_governor_budget_exceeded():
    gov = CostGovernor(budget_cap_usd=0.01)
    with pytest.raises(BudgetExceededError):
        # 200k tokens at $1.50/M output will cross $0.01 cap
        gov.record_usage("gemini-3.1-flash-lite", 100_000, 200_000)


def test_llm_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cache.sqlite"
        cache = LLMCache(db_path=db_path)

        key = cache.compute_key("mock", "gemini-3.1-flash-lite", "SysPrompt", "UserPrompt", 0.6, 42)
        assert cache.get(key) is None

        cache.set(
            cache_key=key,
            provider="mock",
            model="gemini-3.1-flash-lite",
            system_prompt="SysPrompt",
            user_prompt="UserPrompt",
            temperature=0.6,
            seed=42,
            response_text='{"rate_vote_bps": 0}',
            input_tokens=50,
            output_tokens=20,
        )

        hit = cache.get(key)
        assert hit is not None
        assert hit["response_text"] == '{"rate_vote_bps": 0}'
        assert hit["cached"] is True


@pytest.mark.asyncio
async def test_mock_llm_client_generation():
    client = LLMClient(provider="mock", cache_enabled=False)

    # 1. Test Initial Stance schema parsing
    prompt = "State your Initial Stance on repo rate and stance for meeting 2023-08-10."
    raw_text, parsed = await client.generate(
        user_prompt=prompt,
        model="gemini-3.1-flash-lite",
        response_schema=InitialStanceOutput,
    )
    assert parsed is not None
    assert isinstance(parsed, InitialStanceOutput)
    assert parsed.proposed_rate_change_bps in [-50, -25, 0, 25, 35, 40, 50]
    assert parsed.proposed_stance in ["withdrawal_of_accommodation", "neutral", "accommodative"]

    # 2. Test Final Vote schema parsing
    vote_prompt = "Cast your final binding vote on repo rate and stance."
    raw_vote, parsed_vote = await client.generate(
        user_prompt=vote_prompt,
        model="gemini-3.1-flash-lite",
        response_schema=FinalVoteOutput,
    )
    assert parsed_vote is not None
    assert isinstance(parsed_vote, FinalVoteOutput)
    assert parsed_vote.final_rate_vote_bps in [-50, -25, 0, 25, 35, 40, 50]
