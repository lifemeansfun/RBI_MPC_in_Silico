"""
Custom Exception Hierarchy for RBI MPC In Silico.
Provides structured, categorized exceptions for pipeline resilience and defensive coding.
"""

from typing import Optional, Any


class RBIMPCError(Exception):
    """Base exception for all RBI MPC In Silico errors."""
    def __init__(self, message: str, context: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.context = context or {}


# Data & Parsing Exceptions
class DataPipelineError(RBIMPCError):
    """Errors during scraping, parsing, or data ingestion."""
    pass


class StatementParsingError(DataPipelineError):
    """Raised when individual member statements cannot be parsed or validated."""
    pass


class MacroDataMissingError(DataPipelineError):
    """Raised when critical macroeconomic indicators are missing or invalid."""
    pass


# LLM & Infrastructure Exceptions
class LLMInfrastructureError(RBIMPCError):
    """Errors in LLM communication, quotas, or rate limiting."""
    pass


class LLMQuotaExhaustedError(LLMInfrastructureError):
    """Raised when API quotas (RPM or TPM) are completely exhausted after retries."""
    pass


class LLMResponseMalformedError(LLMInfrastructureError):
    """Raised when LLM output violates schema or fails parsing even after normalization."""
    pass


class BudgetExceededError(LLMInfrastructureError):
    """Raised when cost governor hard budget cap is exceeded."""
    pass


# Rule Engine & Orchestration Exceptions
class RuleEngineError(RBIMPCError):
    """Errors in voting tabulation or statutory tie-breaking."""
    pass


class DeliberationContextError(RBIMPCError):
    """Raised when deliberation context is missing, corrupted, or drifted."""
    pass
