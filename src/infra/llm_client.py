"""
Unified Async LLM Client with Multi-Provider Support, Caching, and Budget Governance.
Primary backend: Google Gemini (google-genai).
Fallback backends: OpenAI, Anthropic, Ollama, Mock.
"""

import asyncio
import json
import logging
import random
from typing import Any, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

from src.infra.config_loader import get_config
from src.infra.cache import LLMCache
from src.infra.cost_governor import get_governor

logger = logging.getLogger("rbi_mpc.llm_client")
T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Async client managing calls to Gemini / other providers with caching and retries."""

    def __init__(self, provider: Optional[str] = None, cache_enabled: bool = True):
        cfg = get_config()
        self.provider = provider or cfg.run.provider
        self.cache_enabled = cache_enabled and cfg.run.use_cache
        self.cache = LLMCache() if self.cache_enabled else None
        self.governor = get_governor(budget_cap_usd=cfg.run.budget_usd_cap)
        self.cfg = cfg
        self._gemini_client = None
        self._semaphore = asyncio.Semaphore(1)
        rpm = getattr(cfg.run, "rate_limit_rpm", 5)
        self._min_interval = 60.0 / max(1, rpm)
        self._last_call_time = 0.0

    def _get_gemini_client(self):
        """Lazy initialization of the official google-genai Client."""
        if self._gemini_client is None:
            try:
                from google import genai
                api_key = self.cfg.gemini_api_key
                if not api_key:
                    logger.warning("GEMINI_API_KEY is not set in environment or config.")
                self._gemini_client = genai.Client(api_key=api_key)
            except ImportError:
                logger.error("google-genai package is not installed. Please install requirements.txt")
                raise
        return self._gemini_client

    async def generate(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        seed: Optional[int] = None,
        response_schema: Optional[Type[T]] = None,
        max_retries: int = 4,
    ) -> tuple[str, Optional[T]]:
        """
        Executes an LLM call with caching, exponential backoff, cost tracking, and schema validation.
        Returns: (raw_response_text, parsed_pydantic_model)
        """
        model = model or self.cfg.run.dev_model
        temperature = temperature if temperature is not None else self.cfg.run.temperature
        seed = seed if seed is not None else self.cfg.run.seed_base

        # 1. Check cache first
        cache_key = None
        if self.cache_enabled and self.cache:
            cache_key = self.cache.compute_key(
                self.provider, model, system_prompt, user_prompt, temperature, seed
            )
            cached = self.cache.get(cache_key)
            if cached:
                logger.debug("Cache hit for model %s (key: %s)", model, cache_key[:8])
                raw_text = cached["response_text"]
                parsed = self._parse_schema(raw_text, response_schema)
                return raw_text, parsed

        # 2. Execute call with retry loop
        raw_text, in_tokens, out_tokens = await self._call_provider_with_retry(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            seed=seed,
            response_schema=response_schema,
            max_retries=max_retries,
        )

        # 3. Record cost in governor
        self.governor.record_usage(model=model, input_tokens=in_tokens, output_tokens=out_tokens)

        # 4. Save to cache
        if self.cache_enabled and self.cache and cache_key:
            self.cache.set(
                cache_key=cache_key,
                provider=self.provider,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                seed=seed,
                response_text=raw_text,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
            )

        # 5. Parse schema
        parsed = self._parse_schema(raw_text, response_schema)
        return raw_text, parsed

    def _parse_schema(self, text: str, schema: Optional[Type[T]]) -> Optional[T]:
        """Extracts and validates JSON matching the Pydantic schema from the raw output."""
        if schema is None:
            return None

        clean_text = text.strip()
        # Strip markdown code fencing if present
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()

        try:
            data = json.loads(clean_text)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Failed to parse schema %s from LLM output: %s", schema.__name__, str(e))
            return None

    async def _call_provider_with_retry(
        self,
        user_prompt: str,
        system_prompt: Optional[str],
        model: str,
        temperature: float,
        seed: int,
        response_schema: Optional[Type[T]] = None,
        max_retries: int = 4,
    ) -> tuple[str, int, int]:
        """Handles provider routing with pacing semaphore, 429 handling, and fallback models."""
        import re
        last_exception = None
        current_model = model

        for attempt in range(1, max_retries + 1):
            try:
                # Rate pacing with semaphore
                async with self._semaphore:
                    if self.provider != "mock":
                        now = asyncio.get_running_loop().time()
                        elapsed = now - self._last_call_time
                        if elapsed < self._min_interval:
                            wait_time = self._min_interval - elapsed
                            logger.info("Rate limiter pacing: waiting %.1fs before next call...", wait_time)
                            await asyncio.sleep(wait_time)
                        self._last_call_time = asyncio.get_running_loop().time()

                    if self.provider == "mock":
                        return self._generate_mock(user_prompt, system_prompt, current_model, response_schema)
                    elif self.provider == "gemini":
                        return await self._call_gemini(user_prompt, system_prompt, current_model, temperature, seed)
                    else:
                        raise ValueError(f"Unsupported provider: {self.provider}")

            except Exception as exc:
                last_exception = exc
                err_str = str(exc)

                if attempt == max_retries:
                    logger.error("All %d retries failed for model %s: %s", max_retries, current_model, err_str)
                    raise

                # Check if rate limit (429 / RESOURCE_EXHAUSTED)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    # Extract suggested retryDelay from error if present (e.g. 'retryDelay': '26s')
                    match = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)", err_str)
                    wait_delay = int(match.group(1)) + 2 if match else 20.0
                    logger.warning("429 Rate Limit encountered. Sleeping %ds before retry...", int(wait_delay))

                    # Switch to fallback model on second 429 retry
                    fallbacks = getattr(self.cfg.run, "fallback_models", [])
                    if fallbacks and attempt >= 2:
                        current_model = fallbacks[(attempt - 2) % len(fallbacks)]
                        logger.info("Flipping to fallback model: %s", current_model)

                    await asyncio.sleep(wait_delay)
                else:
                    backoff = (2 ** (attempt - 1)) + random.uniform(0.5, 1.5)
                    logger.warning("Call failed (attempt %d/%d): %s. Backing off %.2fs", attempt, max_retries, exc, backoff)
                    await asyncio.sleep(backoff)

        raise last_exception or RuntimeError("Unexpected retry loop termination")

    async def _call_gemini(
        self,
        user_prompt: str,
        system_prompt: Optional[str],
        model: str,
        temperature: float,
        seed: int,
    ) -> tuple[str, int, int]:
        """Calls Google Gemini using the official google-genai SDK."""
        client = self._get_gemini_client()
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            seed=seed,
            system_instruction=system_prompt if system_prompt else None,
            response_mime_type="application/json",
        )

        # Run client.models.generate_content in threadpool with defensive 60s timeout
        loop = asyncio.get_running_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config,
                ),
            ),
            timeout=60.0,
        )

        text = response.text or ""
        # Token usage extraction
        in_tokens = 0
        out_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            in_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            out_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        else:
            # Approximate fallback: ~4 chars per token
            in_tokens = len(user_prompt + (system_prompt or "")) // 4
            out_tokens = len(text) // 4

        return text, in_tokens, out_tokens

    def _generate_mock(
        self,
        user_prompt: str,
        system_prompt: Optional[str],
        model: str,
        response_schema: Optional[Type[T]] = None,
    ) -> tuple[str, int, int]:
        """Offline mock responses for deterministic unit and integration tests."""
        import re
        schema_name = response_schema.__name__ if response_schema else ""

        # Dynamically extract member_id and member_name if present in prompt template
        m_id = re.search(r'"member_id":\s*"([^"]+)"', user_prompt)
        member_id = m_id.group(1) if m_id else "mock_member"

        m_name = re.search(r'"member_name":\s*"([^"]+)"', user_prompt)
        member_name = m_name.group(1) if m_name else member_id.replace("_", " ").title()

        m_int = re.search(r'"is_internal":\s*(true|false)', user_prompt, re.IGNORECASE)
        is_internal = (m_int.group(1).lower() == "true") if m_int else True

        # Extract prevailing stance from prompt if present
        prev_stance_m = re.search(r"Prevailing Policy Stance:\s*([^\n\r]+)", user_prompt, re.IGNORECASE)
        prev_stance = prev_stance_m.group(1).lower().replace(" ", "_") if prev_stance_m else "withdrawal_of_accommodation"
        
        # Determine realistic mock stance
        if "accommodat" in prev_stance and "withdrawal" not in prev_stance:
            if member_id == "jayanth_varma" and any(y in user_prompt for y in ["2021-08", "2021-10", "2021-12", "2022"]):
                stance = "neutral"  # Varma's famous dissents starting Aug 2021
            else:
                stance = "accommodative"
        else:
            stance = "neutral" if member_id in ["jayanth_varma", "ashima_goyal"] else "withdrawal_of_accommodation"

        logger.debug("[RESEARCH INTEGRITY NOTICE] Using offline mock generator for offline testing.")
        if schema_name == "InitialStanceOutput" or "Round 1" in user_prompt:
            mock_data = {
                "member_id": member_id,
                "member_name": member_name,
                "proposed_rate_change_bps": 0,
                "proposed_stance": stance,
                "key_rationale": f"[OFFLINE MOCK BASELINE] {member_name} notes inflation is moderating while recovery progresses.",
            }
        elif schema_name == "FinalVoteOutput" or "Round 4" in user_prompt:
            mock_data = {
                "member_id": member_id,
                "member_name": member_name,
                "is_internal": is_internal,
                "final_rate_vote_bps": 0,
                "final_stance_vote": stance,
                "dissenting_on_rate": False,
                "dissenting_on_stance": (stance == "neutral"),
                "official_statement_rationale": f"[OFFLINE MOCK BASELINE] Official signed statement for {member_name} in MPC minutes.",
            }
        else:
            mock_data = {
                "member_id": member_id,
                "round_number": 2,
                "current_rate_preference_bps": 0,
                "current_stance_preference": stance,
                "rebuttal_or_critique": f"[OFFLINE MOCK BASELINE] {member_name} analyzes colleagues' views and maintains strategic stance.",
                "open_to_compromise": True,
            }

        raw_text = json.dumps(mock_data)
        return raw_text, 120, 45
