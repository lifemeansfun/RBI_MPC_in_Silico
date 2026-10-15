"""Fail-closed generation with immutable metadata and durable pre-call accounting.

The tuple generate adapter remains for legacy callers. Mock and cache replay are
explicit evidence types, never independent live-model observations. There is one
provider submission per request; SDK retries and model fallbacks are disabled.
"""

import asyncio
import json
import logging
import math
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.infra.cache import LLMCache
from src.infra.config_loader import get_config
from src.infra.cost_governor import (
    PRICE_REVISION, PRICE_SOURCE, TOKEN_RATES_PER_MILLION, CostGovernor, get_governor,
)
from src.infra.evidence import canonical_json, content_hash
from src.infra.generation_evidence import validate_generation_evidence, validate_recorded_schema
from src.infra.exceptions import (
    ArtifactIntegrityError, GenerationCancelledError, GenerationProvenanceError,
    LLMInfrastructureError, LLMResponseMalformedError, UncertainChargeError, UnknownPriceError,
)

logger = logging.getLogger("rbi_mpc.llm_client")
T = TypeVar("T", bound=BaseModel)
REQUIRED_REQUEST_FIELDS = frozenset({"experiment_id", "condition_id", "meeting_date",
                                    "replicate_id", "member_id", "round_number"})


def normalize_request_identity(identity: dict | None, *, required: bool) -> dict:
    identity = dict(identity or {})
    for short, full in {"experiment": "experiment_id", "condition": "condition_id",
                        "meeting": "meeting_date", "replicate": "replicate_id",
                        "member": "member_id", "round": "round_number"}.items():
        if short in identity:
            if full in identity and identity[short] != identity[full]:
                raise GenerationProvenanceError(f"Conflicting identity aliases: {short}/{full}")
            identity[full] = identity.pop(short)
    if required and REQUIRED_REQUEST_FIELDS - identity.keys():
        raise GenerationProvenanceError("Live generation requires complete experiment/condition/meeting/replicate/member/round identity")
    if any(value is None or value == "" for value in identity.values()):
        raise GenerationProvenanceError("Request identity contains missing values")
    for field in ("replicate_id", "round_number"):
        if field in identity and (type(identity[field]) is not int or identity[field] < (1 if field == "round_number" else 0)):
            raise GenerationProvenanceError(f"{field} must be a valid integer")
    if "meeting_date" in identity:
        try:
            if date.fromisoformat(identity["meeting_date"]).isoformat() != identity["meeting_date"]:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise GenerationProvenanceError("meeting_date must be an actual ISO calendar date") from exc
    for field in ("experiment_id", "condition_id", "member_id", "output_member_id"):
        if field in identity and (not isinstance(identity[field], str) or not identity[field].strip()):
            raise GenerationProvenanceError(f"{field} must be a nonempty string")
    return json.loads(canonical_json(identity))


@dataclass(frozen=True)
class GenerationMetadata:
    request_id: str
    request_hash: str
    request_payload_json: str
    provider: str
    requested_model: str
    routed_model: str
    served_model: str | None
    model_epoch: str | None
    response_id: str | None
    seed: int
    provider_reported_seed: int | None
    temperature: float
    max_output_tokens: int
    input_token_bound: int
    input_bound_method: str
    schema_name: str | None
    schema_hash: str
    schema_json: str
    parser_version: str
    prompt_hash: str
    system_prompt: str | None
    user_prompt: str
    cache_key: str
    cache_replay: bool
    source_request_id: str | None
    source_evidence_type: str | None
    evidence_type: str
    attempt_count: int
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    token_usage_source: str
    estimated_cost_usd: float
    reservation_id: str | None
    price_revision: str | None
    price_source: str | None
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GenerationResult:
    raw_text: str
    parsed: BaseModel | None
    validation_error: str | None
    request_identity_json: str
    metadata: GenerationMetadata

    @property
    def request_identity(self) -> dict:
        return json.loads(self.request_identity_json)

    def to_dict(self) -> dict:
        return {"raw_text": self.raw_text,
                "parsed": self.parsed.model_dump(mode="json") if self.parsed is not None else None,
                "validation_error": self.validation_error, "request_identity": self.request_identity,
                "metadata": self.metadata.to_dict()}


@dataclass(frozen=True)
class ProviderResponse:
    raw_text: str
    input_tokens: int | None
    output_tokens: int | None
    served_model: str | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    provider_reported_seed: int | None = None
    token_usage_source: str = "provider_reported"


class LLMClient:
    def __init__(self, provider: Optional[str] = None, cache_enabled: bool = True, *,
                 governor: CostGovernor | None = None, cache: LLMCache | None = None,
                 ledger_path=None, request_timeout_seconds: float | None = None):
        self.cfg = get_config()
        self.provider = provider or self.cfg.run.provider
        self.cache_enabled = cache_enabled and self.cfg.run.use_cache
        self.cache = (cache or LLMCache(self.cfg.run.cache_dir)) if self.cache_enabled else None
        self.governor = governor
        if self.governor is None and self.provider != "mock":
            self.governor = get_governor(self.cfg.run.budget_usd_cap,
                                       ledger_path or getattr(self.cfg.run, "budget_ledger_path", None))
        self.request_timeout_seconds = (request_timeout_seconds if request_timeout_seconds is not None
                                        else getattr(self.cfg.run, "request_timeout_seconds", 60.0))
        if not math.isfinite(self.request_timeout_seconds) or self.request_timeout_seconds <= 0:
            raise GenerationProvenanceError("request_timeout_seconds must be finite and positive")
        self._gemini_client = None
        self._semaphore = asyncio.Semaphore(1)
        self._min_interval = 60.0 / max(1, getattr(self.cfg.run, "rate_limit_rpm", 5))
        self._last_call_time = 0.0

    def _get_gemini_client(self):
        if self._gemini_client is None:
            from google import genai
            from google.genai import types
            if not self.cfg.gemini_api_key:
                raise GenerationProvenanceError("GEMINI_API_KEY is missing")
            self._gemini_client = genai.Client(
                api_key=self.cfg.gemini_api_key,
                http_options=types.HttpOptions(timeout=int(self.request_timeout_seconds * 1000),
                                               retry_options=types.HttpRetryOptions(attempts=1)),
            )
        return self._gemini_client

    async def generate(self, *args, **kwargs) -> tuple[str, Optional[T]]:
        result = await self.generate_with_metadata(*args, **kwargs)
        return result.raw_text, result.parsed

    async def generate_with_metadata(
        self, user_prompt: str, system_prompt: Optional[str] = None,
        model: Optional[str] = None, temperature: Optional[float] = None,
        seed: Optional[int] = None, response_schema: Optional[Type[T]] = None,
        max_retries: int = 1, *, request_identity: dict | None = None,
        request_context: dict | None = None, expected_identity: dict | None = None,
        max_output_tokens: int | None = None, input_token_bound: int | None = None,
        parser_version: str = "strict-json-v1", model_epoch: str | None = None,
    ) -> GenerationResult:
        model = model or self.cfg.run.dev_model
        temperature = self.cfg.run.temperature if temperature is None else temperature
        seed = self.cfg.run.seed_base if seed is None else seed
        max_output_tokens = (getattr(self.cfg.run, "max_output_tokens", 2048)
                             if max_output_tokens is None else max_output_tokens)
        model_epoch = model_epoch or getattr(self.cfg.run, "model_epoch", None)
        if not isinstance(user_prompt, str) or not user_prompt or (system_prompt is not None and not isinstance(system_prompt, str)):
            raise GenerationProvenanceError("Prompts must be nonempty text")
        if type(temperature) not in (float, int) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise GenerationProvenanceError("Temperature must be finite and within [0,2]")
        if type(seed) is not int or type(max_output_tokens) is not int or max_output_tokens <= 0:
            raise GenerationProvenanceError("Seed must be integer; output must have a positive token bound")
        if parser_version != "strict-json-v1":
            raise GenerationProvenanceError("This implementation only supports parser_version strict-json-v1")
        if request_context is not None:
            if request_identity is not None and request_identity != request_context:
                raise GenerationProvenanceError("Conflicting request identity/context")
            request_identity = request_context
        identity = normalize_request_identity(request_identity, required=self.provider != "mock")
        schema = response_schema.model_json_schema() if response_schema else None
        if schema is not None:
            # Dependency/schema failures are preflight errors, before paid calls.
            validate_recorded_schema(None, schema, schema_only=True)
        expected = dict(expected_identity or {})
        properties = (schema or {}).get("properties", {})
        for field in ("member_id", "round_number"):
            if field in identity and field in properties:
                bound_value = identity.get("output_member_id", identity[field]) if field == "member_id" else identity[field]
                if field in expected and expected[field] != bound_value:
                    raise GenerationProvenanceError("Requested output identity conflicts with request identity")
                expected[field] = bound_value
        if response_schema and set(expected) - set(properties):
            raise GenerationProvenanceError("Expected identity contains fields absent from output schema")
        if self.provider != "mock":
            if self.provider != "gemini" or model not in TOKEN_RATES_PER_MILLION or model == "mock":
                raise UnknownPriceError(f"Unverified provider/model price: {self.provider}/{model}",
                                        context={"request_identity": identity, "user_prompt": user_prompt,
                                                 "system_prompt": system_prompt, "model": model,
                                                 "seed": seed, "max_output_tokens": max_output_tokens})
            if not model_epoch:
                raise GenerationProvenanceError("Live generation requires an explicit model_epoch marker",
                                                 context={"request_identity": identity, "user_prompt": user_prompt,
                                                          "system_prompt": system_prompt, "model": model})
        # UTF-8 bytes + defensive framing allowance is conservative for this text-
        # only interface and is checked against the provider token-count endpoint.
        if self.provider == "mock":
            input_bound_method = "offline_mock_explicit_bound" if input_token_bound is not None else "offline_mock_utf8_bytes_plus_8192"
        else:
            input_bound_method = "explicit_bound_verified_by_provider_count" if input_token_bound is not None else "utf8_bytes_plus_8192_verified_by_provider_count"
        if input_token_bound is None:
            input_token_bound = len(canonical_json({"system": system_prompt, "user": user_prompt, "schema": schema}).encode("utf-8")) + 8192
        if type(input_token_bound) is not int or input_token_bound < 0:
            raise GenerationProvenanceError("input_token_bound must be a nonnegative integer")
        request_payload = LLMCache.request_payload(
            self.provider, model, system_prompt, user_prompt, temperature, seed,
            max_output_tokens=max_output_tokens, schema=schema, parser_version=parser_version,
            model_epoch=model_epoch, request_identity=identity, expected_identity=expected,
            generation_config={"response_mime_type": "application/json", "candidate_count": 1,
                               "tools": [], "input_token_bound": input_token_bound},
        )
        cache_key = content_hash(request_payload)
        request_id = uuid.uuid4().hex
        metadata = GenerationMetadata(
            request_id=request_id, request_hash=cache_key, request_payload_json=canonical_json(request_payload), provider=self.provider,
            requested_model=model, routed_model=model, served_model=None, model_epoch=model_epoch,
            response_id=None, seed=seed, provider_reported_seed=None, temperature=temperature,
            max_output_tokens=max_output_tokens, input_token_bound=input_token_bound,
            input_bound_method=input_bound_method, schema_name=response_schema.__name__ if response_schema else None,
            schema_hash=content_hash(schema), schema_json=canonical_json(schema), parser_version=parser_version,
            prompt_hash=content_hash({"system": system_prompt, "user": user_prompt}),
            system_prompt=system_prompt, user_prompt=user_prompt, cache_key=cache_key,
            cache_replay=False, source_request_id=None, source_evidence_type=None,
            evidence_type="mock" if self.provider == "mock" else "live_model", attempt_count=1,
            finish_reason=None, input_tokens=None, output_tokens=None, token_usage_source="unreported",
            estimated_cost_usd=0.0, reservation_id=None,
            price_revision=PRICE_REVISION if self.provider != "mock" else None,
            price_source=PRICE_SOURCE if self.provider != "mock" else None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        raw_text = ""
        try:
            if self.provider != "mock":
                self.governor.assert_can_submit()
            if self.cache:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    source = cached.get("metadata")
                    if not isinstance(source, dict) or not source or cached.get("request_payload") != request_payload:
                        raise ArtifactIntegrityError("Cached result lacks matching complete generation provenance")
                    envelope_fields = {"provider": "provider", "model": "routed_model", "system_prompt": "system_prompt",
                                       "user_prompt": "user_prompt", "temperature": "temperature", "seed": "seed",
                                       "input_tokens": "input_tokens", "output_tokens": "output_tokens"}
                    if any(cached.get(field) != source.get(recorded) or type(cached.get(field)) is not type(source.get(recorded))
                           for field, recorded in envelope_fields.items()):
                        raise ArtifactIntegrityError("Cached envelope contradicts generation metadata")
                    if source.get("request_hash") != cache_key or source.get("cache_key") != cache_key:
                        raise ArtifactIntegrityError("Cached generation provenance identity mismatch")
                    for field in ("provider", "requested_model", "routed_model", "model_epoch", "seed",
                                  "temperature", "max_output_tokens", "input_token_bound", "schema_name",
                                  "schema_hash", "schema_json", "parser_version", "prompt_hash",
                                  "system_prompt", "user_prompt", "request_payload_json"):
                        if source.get(field) != getattr(metadata, field):
                            raise ArtifactIntegrityError(f"Cached generation {field} differs from request")
                    raw_text = cached["response_text"]
                    try:
                        metadata = replace(GenerationMetadata(**source), request_id=request_id,
                                           cache_replay=True, evidence_type="cache_replay",
                                           source_request_id=source["request_id"],
                                           source_evidence_type=source["evidence_type"],
                                           created_at=metadata.created_at)
                    except (TypeError, KeyError) as exc:
                        raise ArtifactIntegrityError("Cached generation metadata is incomplete") from exc
                    parsed = self._parse_schema(raw_text, response_schema, expected)
                    validate_generation_evidence({
                        "raw_text": raw_text, "parsed": parsed.model_dump(mode="json") if parsed is not None else None,
                        "validation_error": None, "request_identity": identity, "metadata": source,
                    })
                    if source["provider"] != "mock":
                        receipt = self.governor.receipt_for(source["reservation_id"])
                        comparisons = {"attempt_id": "request_id", "provider": "provider", "model": "routed_model",
                                       "price_revision": "price_revision", "input_bound": "input_token_bound",
                                       "output_bound": "max_output_tokens", "input_tokens": "input_tokens",
                                       "output_tokens": "output_tokens", "estimated_cost_usd": "estimated_cost_usd"}
                        if any(receipt[field] != source[recorded] or type(receipt[field]) is not type(source[recorded])
                               for field, recorded in comparisons.items()):
                            raise ArtifactIntegrityError("Cached source metadata contradicts durable accounting receipt")
                        if any(receipt["evidence"].get(field) != source[field]
                               for field in ("response_id", "token_usage_source")):
                            raise ArtifactIntegrityError("Cached provider receipt differs from durable source evidence")
                    return GenerationResult(raw_text, parsed, None, canonical_json(identity), metadata)
            if self.provider == "mock":
                raw_text, it, ot = self._generate_mock(user_prompt, system_prompt, model, response_schema, expected)
                metadata = replace(metadata, input_tokens=it, output_tokens=ot,
                                   token_usage_source="offline_mock_fixture", finish_reason="mock")
            else:
                async with self._semaphore:
                    # Reserve before *any* provider call: budget refusal submits none.
                    rid = self.governor.reserve(request_id, self.provider, model,
                                                input_token_bound, max_output_tokens, PRICE_REVISION)
                    metadata = replace(metadata, reservation_id=rid)
                    submitted = False
                    try:
                        counted = await asyncio.wait_for(
                            self._count_gemini_input(user_prompt, system_prompt, model, response_schema),
                            timeout=self.request_timeout_seconds)
                        if type(counted) is not int or counted < 0 or counted > input_token_bound:
                            raise GenerationProvenanceError("Provider input count is missing or exceeds reserved bound")
                        now = asyncio.get_running_loop().time()
                        if now - self._last_call_time < self._min_interval:
                            await asyncio.sleep(self._min_interval - (now - self._last_call_time))
                        self.governor.assert_can_submit()
                        self.governor.mark_submitted(rid)
                        submitted = True
                        self._last_call_time = asyncio.get_running_loop().time()
                        response = await asyncio.wait_for(
                            self._call_gemini(user_prompt, system_prompt, model, temperature, seed,
                                              response_schema=response_schema, max_output_tokens=max_output_tokens),
                            timeout=self.request_timeout_seconds)
                        if isinstance(response, tuple):
                            # Explicit legacy test/provider adapter, never native live evidence.
                            response = ProviderResponse(*response, token_usage_source="legacy_tuple_adapter")
                            metadata = replace(metadata, evidence_type="legacy_provider_adapter")
                        if not isinstance(response, ProviderResponse):
                            raise GenerationProvenanceError("Provider response has no structured provenance")
                        raw_text = response.raw_text
                        metadata = replace(metadata, served_model=response.served_model,
                                           response_id=response.response_id, finish_reason=response.finish_reason,
                                           provider_reported_seed=response.provider_reported_seed,
                                           input_tokens=response.input_tokens, output_tokens=response.output_tokens,
                                           token_usage_source=response.token_usage_source)
                        if type(response.input_tokens) is not int or type(response.output_tokens) is not int:
                            raise GenerationProvenanceError("Billable usage is unreported; reservation retained")
                        cost = self.governor.commit(rid, {"input_tokens": response.input_tokens,
                                                         "output_tokens": response.output_tokens,
                                                         "response_id": response.response_id,
                                                         "token_usage_source": response.token_usage_source})
                        submitted = False  # resolved, even if output validation subsequently fails
                        metadata = replace(metadata, estimated_cost_usd=cost)
                    except BaseException as exc:
                        # A bound violation may raise after committing known real
                        # usage. Retain its settled cost in the failure context.
                        if submitted:
                            try:
                                receipt = self.governor.receipt_for(rid)
                            except LLMInfrastructureError:
                                pass
                            else:
                                metadata = replace(metadata, estimated_cost_usd=receipt["estimated_cost_usd"])
                                submitted = False
                        if submitted:
                            # A timed-out thread may continue remotely. No release/retry.
                            try:
                                self.governor.mark_uncertain(rid, f"{type(exc).__name__}: {exc}")
                            except LLMInfrastructureError:
                                # commit may already have retained real usage before raising.
                                pass
                        else:
                            # This path precedes the generation submission.
                            try:
                                self.governor.release(rid, evidence={"status": "not_submitted", "reference": f"preflight:{request_id}:{type(exc).__name__}"})
                            except LLMInfrastructureError:
                                pass
                        if isinstance(exc, asyncio.CancelledError):
                            raise GenerationCancelledError("Generation cancelled; unresolved submitted charges halt the study") from exc
                        if isinstance(exc, LLMInfrastructureError):
                            raise
                        raise UncertainChargeError("Provider failed/timed out; submitted charges retained" if submitted
                                                   else "Provider preflight failed before generation; no generation submitted") from exc
                if (metadata.evidence_type == "live_model" and metadata.finish_reason != "STOP"
                        or metadata.evidence_type == "legacy_provider_adapter" and metadata.finish_reason not in (None, "STOP")):
                    raise LLMResponseMalformedError(f"Provider did not finish normally: {metadata.finish_reason}")
            parsed = self._parse_schema(raw_text, response_schema, expected)
            result = GenerationResult(raw_text, parsed, None, canonical_json(identity), metadata)
            validate_generation_evidence(result.to_dict())
            if self.cache:
                self.cache.set(cache_key, self.provider, model, system_prompt, user_prompt, temperature,
                               seed, raw_text, metadata.input_tokens or 0, metadata.output_tokens or 0,
                               metadata=metadata.to_dict(), request_payload=request_payload)
            return result
        except LLMInfrastructureError as exc:
            exc.context.update({"request_identity": identity, "raw_text": raw_text,
                                "metadata": metadata.to_dict(), "validation_error": str(exc)})
            raise

    def _parse_schema(self, text: str, schema: Optional[Type[T]], expected_identity: dict | None = None) -> Optional[T]:
        if schema is None:
            return None
        def no_duplicates(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError(f"Duplicate JSON field {key!r}")
                data[key] = value
            return data
        def no_constants(value):
            raise ValueError(f"Nonfinite JSON value {value}")
        try:
            # Strict JSON: fenced text/extra prose is failed evidence, not repaired.
            data = json.loads(text, object_pairs_hook=no_duplicates, parse_constant=no_constants)
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            allowed = set(schema.model_json_schema().get("properties", {}))
            if set(data) - allowed:
                raise ValueError(f"Unexpected output fields: {sorted(set(data)-allowed)}")
            if data.get("fallback_triggered", False) is not False:
                raise ValueError("Fallback output is not permitted as research generation")
            for field, expected in (expected_identity or {}).items():
                if field not in data or type(data[field]) is not type(expected) or data[field] != expected:
                    raise ValueError(f"Output impersonates/misidentifies requested {field}")
            return schema.model_validate(data, strict=True)
        except (json.JSONDecodeError, ValueError, TypeError, ValidationError) as exc:
            raise LLMResponseMalformedError(f"Invalid {schema.__name__} output: {exc}") from exc

    async def _count_gemini_input(self, user_prompt, system_prompt, model, response_schema=None) -> int:
        client = self._get_gemini_client()
        schema = response_schema.model_json_schema() if response_schema else None
        # The Developer API count endpoint does not support system_instruction or
        # generation_config. Count every supplied text as an envelope; retain the
        # separate UTF-8/framing reserve rather than treating this as exact billing.
        envelope = canonical_json({"system_instruction": system_prompt,
                                   "user_prompt": user_prompt, "response_json_schema": schema})
        response = await asyncio.to_thread(client.models.count_tokens, model=model, contents=envelope)
        return getattr(response, "total_tokens", None)

    async def _call_gemini(self, user_prompt: str, system_prompt: Optional[str], model: str,
                           temperature: float, seed: int, *, response_schema=None,
                           max_output_tokens=2048) -> ProviderResponse:
        client = self._get_gemini_client()
        from google.genai import types
        config = types.GenerateContentConfig(
            temperature=temperature, seed=seed, system_instruction=system_prompt,
            max_output_tokens=max_output_tokens, candidate_count=1,
            response_mime_type="application/json",
            response_json_schema=response_schema.model_json_schema() if response_schema else None,
        )
        response = await asyncio.to_thread(client.models.generate_content, model=model, contents=user_prompt, config=config)
        usage = getattr(response, "usage_metadata", None)
        it = getattr(usage, "prompt_token_count", None)
        candidates = getattr(usage, "candidates_token_count", None)
        thoughts = getattr(usage, "thoughts_token_count", None)
        # Thinking is charged at output rates. Unreported total usage never becomes 0.
        total = getattr(usage, "total_token_count", None)
        if type(it) is int and type(total) is int:
            ot = total - it
        elif type(candidates) is int and type(thoughts) is int:
            ot = candidates + thoughts
        else:
            ot = None
        finish = None
        if getattr(response, "candidates", None):
            reason = getattr(response.candidates[0], "finish_reason", None)
            finish = getattr(reason, "value", str(reason)) if reason is not None else None
        return ProviderResponse(response.text or "", it, ot,
                                served_model=getattr(response, "model_version", None),
                                response_id=getattr(response, "response_id", None), finish_reason=finish)
    def _generate_mock(
        self,
        user_prompt: str,
        system_prompt: Optional[str],
        model: str,
        response_schema: Optional[Type[T]] = None,
        expected_identity: dict | None = None,
    ) -> tuple[str, int, int]:
        """Offline mock responses for deterministic unit and integration tests."""
        import re
        schema_name = response_schema.__name__ if response_schema else ""

        # Dynamically extract member_id and member_name if present in prompt template
        expected_identity = expected_identity or {}
        m_ids = re.findall(r'"member_id":\s*"([^"]+)"', user_prompt)
        member_id = expected_identity.get("member_id", m_ids[-1] if m_ids else "mock_member")

        m_names = re.findall(r'"member_name":\s*"([^"]+)"', user_prompt)
        member_name = expected_identity.get("member_name", m_names[-1] if m_names else member_id.replace("_", " ").title())

        m_internals = re.findall(r'"is_internal":\s*(true|false)', user_prompt, re.IGNORECASE)
        is_internal = expected_identity.get("is_internal", m_internals[-1].lower() == "true" if m_internals else True)

        # Extract prevailing stance from prompt if present
        prev_stance_m = re.search(r"Prevailing (?:Policy )?Stance:\s*([^\n\r]+)", user_prompt, re.IGNORECASE)
        prev_stance = prev_stance_m.group(1).lower().replace(" ", "_") if prev_stance_m else "withdrawal_of_accommodation"
        
        # Scripted identity/date fixture behavior, never evidence of realism.
        if "accommodat" in prev_stance and "withdrawal" not in prev_stance:
            if member_id == "jayanth_varma" and any(y in user_prompt for y in ["2021-08", "2021-10", "2021-12", "2022"]):
                stance = "neutral"  # Varma's famous dissents starting Aug 2021
            else:
                stance = "accommodative"
        else:
            stance = "neutral" if member_id in ["jayanth_varma", "ashima_goyal"] else "withdrawal_of_accommodation"

        logger.debug("[RESEARCH INTEGRITY NOTICE] Using offline mock generator for offline testing.")
        if schema_name == "InitialStanceOutput" or (response_schema is None and "Round 1" in user_prompt):
            mock_data = {
                "member_id": member_id,
                "member_name": member_name,
                "proposed_rate_change_bps": 0,
                "proposed_stance": stance,
                "key_rationale": f"[OFFLINE MOCK BASELINE] {member_name} notes inflation is moderating while recovery progresses.",
            }
        elif schema_name == "FinalVoteOutput" or (response_schema is None and "Round 4" in user_prompt):
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
                "round_number": expected_identity.get("round_number", 3 if "Round 3" in user_prompt else 2),
                "current_rate_preference_bps": 0,
                "current_stance_preference": stance,
                "rebuttal_or_critique": f"[OFFLINE MOCK BASELINE] {member_name} analyzes colleagues' views and maintains strategic stance.",
                "open_to_compromise": True,
            }

        raw_text = json.dumps(mock_data)
        return raw_text, 120, 45
