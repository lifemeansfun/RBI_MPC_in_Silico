"""
Hard cost and token governor for LLM invocations.
Tracks cumulative spend and enforces the hard budget cap.
"""

import threading
from typing import Optional


class BudgetExceededError(Exception):
    """Raised when cumulative LLM expenditure reaches or exceeds the budget cap."""
    pass


# Default token rates in USD per 1M tokens (as of early 2026)
TOKEN_RATES_PER_MILLION = {
    # Gemini rates
    "gemini-3.1-flash-lite": {"input": 0.05, "output": 0.20},
    "gemini-3.8-flash": {"input": 0.075, "output": 0.30},
    "gemini-3.6-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    # OpenAI rates
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    # Anthropic rates
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    # Local/Mock
    "mock": {"input": 0.0, "output": 0.0},
    "ollama": {"input": 0.0, "output": 0.0},
}


class CostGovernor:
    """Thread-safe cost and token governor."""

    def __init__(self, budget_cap_usd: float = 25.0):
        self.budget_cap_usd = budget_cap_usd
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_estimated_cost_usd = 0.0
        self.call_count = 0
        self._lock = threading.Lock()

    def record_usage(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """
        Records token consumption and raises BudgetExceededError if budget cap is crossed.
        Returns the incremental cost of the call.
        """
        rates = TOKEN_RATES_PER_MILLION.get(model, {"input": 0.15, "output": 0.60})
        call_cost = (
            (input_tokens / 1_000_000.0) * rates["input"]
            + (output_tokens / 1_000_000.0) * rates["output"]
        )

        with self._lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_estimated_cost_usd += call_cost
            self.call_count += 1

            if self.total_estimated_cost_usd >= self.budget_cap_usd:
                raise BudgetExceededError(
                    f"CRITICAL: Budget cap of ${self.budget_cap_usd:.2f} reached! "
                    f"Current spend: ${self.total_estimated_cost_usd:.4f} across {self.call_count} calls. "
                    "Execution halted to prevent unintended billing."
                )

        return call_cost

    def get_summary(self) -> dict:
        """Returns a snapshot of consumption metrics."""
        with self._lock:
            return {
                "call_count": self.call_count,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_input_tokens + self.total_output_tokens,
                "total_estimated_cost_usd": round(self.total_estimated_cost_usd, 5),
                "budget_cap_usd": self.budget_cap_usd,
                "budget_remaining_usd": round(max(0.0, self.budget_cap_usd - self.total_estimated_cost_usd), 5),
            }


# Module singleton
_DEFAULT_GOVERNOR: Optional[CostGovernor] = None


def get_governor(budget_cap_usd: float = 25.0) -> CostGovernor:
    global _DEFAULT_GOVERNOR
    if _DEFAULT_GOVERNOR is None:
        _DEFAULT_GOVERNOR = CostGovernor(budget_cap_usd=budget_cap_usd)
    return _DEFAULT_GOVERNOR
