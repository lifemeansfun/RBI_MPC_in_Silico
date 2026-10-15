"""Semantic validation of copied generation evidence, beyond content digests.

Digests detect accidental changes; they do not authenticate a provider invoice.
Replay must also reconcile the recorded schema, request, evidence track and cost.
"""

import json
import math
from datetime import date, datetime

from src.infra.cost_governor import PRICE_REVISION, PRICE_SOURCE, TOKEN_RATES_PER_MILLION
from src.infra.evidence import canonical_json, content_hash
from src.infra.exceptions import ArtifactIntegrityError, GenerationProvenanceError

REQUIRED_METADATA_FIELDS = frozenset("""
request_id request_hash request_payload_json provider requested_model routed_model served_model model_epoch
response_id seed provider_reported_seed temperature max_output_tokens input_token_bound input_bound_method
schema_name schema_hash schema_json parser_version prompt_hash system_prompt user_prompt cache_key cache_replay
source_request_id source_evidence_type evidence_type attempt_count finish_reason input_tokens output_tokens
token_usage_source estimated_cost_usd reservation_id price_revision price_source created_at
""".split())


def strict_json(text: str):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field {key!r}")
            result[key] = value
        return result

    def finite(value):
        raise ValueError(f"Nonfinite JSON value {value}")

    value = json.loads(text, object_pairs_hook=unique, parse_constant=finite)
    canonical_json(value)  # Also rejects overflow such as 1e999.
    return value


def validate_recorded_schema(value, schema: dict, *, schema_only: bool = False) -> None:
    """Use the actual recorded schema, with strict integers and no remote fetching."""
    try:
        from jsonschema import Draft202012Validator, validators
        from jsonschema.exceptions import SchemaError, ValidationError
        from referencing import Registry
        from referencing.exceptions import NoSuchResource, Unresolvable
    except ImportError as exc:
        raise ArtifactIntegrityError("jsonschema dependency is required to validate replay evidence") from exc

    def no_remote(uri):
        raise NoSuchResource(ref=uri)

    def check_references(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"$ref", "$dynamicRef"} and (not isinstance(child, str) or not child.startswith("#")):
                    raise ArtifactIntegrityError("Recorded schema may not fetch external references")
                check_references(child)
        elif isinstance(node, list):
            for child in node:
                check_references(child)

    try:
        check_references(schema)
        Draft202012Validator.check_schema(schema)
        checker = Draft202012Validator.TYPE_CHECKER.redefine(
            "integer", lambda _, item: type(item) is int,
        ).redefine("number", lambda _, item: type(item) is int or type(item) is float and math.isfinite(item))
        validator = validators.extend(Draft202012Validator, type_checker=checker)
        if not schema_only:
            validator(schema, registry=Registry(retrieve=no_remote)).validate(value)
    except (SchemaError, ValidationError, Unresolvable, TypeError, ValueError) as exc:
        raise ArtifactIntegrityError(f"Output violates recorded strict schema: {exc}") from exc


def validate_generation_evidence(generation: dict, *, identity_aliases: dict | None = None) -> dict | None:
    """Reject semantic contradictions in a successful generation/cache/replay record."""
    try:
        canonical_json(generation)
        metadata = generation["metadata"]
        if not isinstance(metadata, dict) or set(metadata) != REQUIRED_METADATA_FIELDS:
            raise ArtifactIntegrityError("Generation metadata is incomplete or has unknown fields")
        request = strict_json(metadata["request_payload_json"])
        identity = generation["request_identity"]
        if not isinstance(identity, dict) or request["request_identity"] != identity:
            raise ArtifactIntegrityError("Canonical generation identity differs from the request")
        if metadata["request_hash"] != content_hash(request) or metadata["cache_key"] != metadata["request_hash"]:
            raise ArtifactIntegrityError("Generation request hash mismatch")
        for field in ("provider", "routed_model", "temperature", "seed", "max_output_tokens", "model_epoch",
                      "parser_version", "system_prompt", "user_prompt"):
            if request[field] != metadata[field] or type(request[field]) is not type(metadata[field]):
                raise ArtifactIntegrityError(f"Generation {field} differs from canonical request")
        if metadata["requested_model"] != metadata["routed_model"]:
            raise ArtifactIntegrityError("Unexpected model substitution in generation evidence")
        schema = request["schema"]
        if metadata["schema_hash"] != content_hash(schema) or strict_json(metadata["schema_json"]) != schema:
            raise ArtifactIntegrityError("Generation schema provenance differs from request")
        if metadata["prompt_hash"] != content_hash({"system": request["system_prompt"], "user": request["user_prompt"]}):
            raise ArtifactIntegrityError("Generation prompt hash mismatch")
        if type(metadata["seed"]) is not int or type(metadata["attempt_count"]) is not int or metadata["attempt_count"] != 1:
            raise ArtifactIntegrityError("Generation seed/attempt count is invalid")
        if type(metadata["temperature"]) not in (float, int) or not 0 <= metadata["temperature"] <= 2:
            raise ArtifactIntegrityError("Generation temperature is invalid")
        for field, minimum in (("input_token_bound", 0), ("max_output_tokens", 1), ("input_tokens", 0), ("output_tokens", 0)):
            if type(metadata[field]) is not int or metadata[field] < minimum:
                raise ArtifactIntegrityError(f"Generation {field} is missing or invalid")
        if metadata["input_token_bound"] != request["generation_config"]["input_token_bound"]:
            raise ArtifactIntegrityError("Generation input reservation differs from request")
        if request["generation_config"] != {"response_mime_type": "application/json", "candidate_count": 1,
                                            "tools": [], "input_token_bound": metadata["input_token_bound"]}:
            raise ArtifactIntegrityError("Evidence claims an unsupported generation/cost configuration")
        if metadata["input_bound_method"] not in {"explicit_bound_verified_by_provider_count", "utf8_bytes_plus_8192_verified_by_provider_count",
                                                "offline_mock_explicit_bound", "offline_mock_utf8_bytes_plus_8192"}:
            raise ArtifactIntegrityError("Generation input-bound method is unknown")
        if datetime.fromisoformat(metadata["created_at"]).tzinfo is None:
            raise ArtifactIntegrityError("Generation time lacks a timezone")
        if metadata["provider_reported_seed"] is not None and type(metadata["provider_reported_seed"]) is not int:
            raise ArtifactIntegrityError("Provider-reported seed is invalid")
        for field in ("response_id", "served_model"):
            if metadata[field] is not None and (not isinstance(metadata[field], str) or not metadata[field].strip()):
                raise ArtifactIntegrityError("Provider identity/receipt metadata is malformed")
        if metadata["parser_version"] != "strict-json-v1" or generation["validation_error"] is not None:
            raise ArtifactIntegrityError("Failed/unknown parser evidence cannot replay as successful generation")
        if not isinstance(generation["raw_text"], str) or not isinstance(metadata["request_id"], str) or not metadata["request_id"]:
            raise ArtifactIntegrityError("Generation lacks raw text/request identity")
        for field in ("replicate_id", "round_number"):
            if field in identity and (type(identity[field]) is not int or identity[field] < (1 if field == "round_number" else 0)):
                raise ArtifactIntegrityError("Generation identity has invalid round/replicate")
        if "meeting_date" in identity and date.fromisoformat(identity["meeting_date"]).isoformat() != identity["meeting_date"]:
            raise ArtifactIntegrityError("Generation identity has invalid meeting date")
        for field in ("experiment_id", "condition_id", "member_id", "output_member_id"):
            if field in identity and (not isinstance(identity[field], str) or not identity[field].strip()):
                raise ArtifactIntegrityError("Generation identity has missing study/member values")

        evidence_type = metadata["evidence_type"]
        replay = evidence_type == "cache_replay"
        if type(metadata["cache_replay"]) is not bool or metadata["cache_replay"] != replay:
            raise ArtifactIntegrityError("Cache evidence label contradicts replay flag")
        origin = metadata["source_evidence_type"] if replay else evidence_type
        if replay:
            if not isinstance(metadata["source_request_id"], str) or not metadata["source_request_id"] or metadata["source_request_id"] == metadata["request_id"]:
                raise ArtifactIntegrityError("Cache replay lacks distinct source request identity")
        elif metadata["source_request_id"] is not None or metadata["source_evidence_type"] is not None:
            raise ArtifactIntegrityError("Fresh generation incorrectly carries replay source metadata")
        if origin == "mock":
            if not metadata["input_bound_method"].startswith("offline_mock_"):
                raise ArtifactIntegrityError("Mock bound cannot claim provider verification")
            if metadata["provider"] != "mock" or metadata["token_usage_source"] != "offline_mock_fixture" or metadata["finish_reason"] != "mock":
                raise ArtifactIntegrityError("Mock evidence contradicts provider/usage/finish metadata")
            if metadata["estimated_cost_usd"] != 0 or any(metadata[field] is not None for field in ("reservation_id", "price_revision", "price_source", "response_id", "served_model")):
                raise ArtifactIntegrityError("Mock evidence incorrectly carries live accounting/provenance")
        elif origin in {"live_model", "legacy_provider_adapter"}:
            if metadata["input_bound_method"].startswith("offline_mock_"):
                raise ArtifactIntegrityError("Live generation lacks provider-count bound verification")
            if metadata["provider"] != "gemini" or metadata["routed_model"] not in TOKEN_RATES_PER_MILLION or metadata["routed_model"] == "mock":
                raise ArtifactIntegrityError("Live evidence has an unsupported provider/model")
            required = {"experiment_id", "condition_id", "meeting_date", "replicate_id", "member_id", "round_number"}
            if required - identity.keys() or not isinstance(metadata["model_epoch"], str) or not metadata["model_epoch"].strip():
                raise ArtifactIntegrityError("Live evidence lacks complete request/model epoch identity")
            if metadata["price_revision"] != PRICE_REVISION or metadata["price_source"] != PRICE_SOURCE or not isinstance(metadata["reservation_id"], str) or not metadata["reservation_id"]:
                raise ArtifactIntegrityError("Live evidence lacks versioned reservation accounting")
            usage_source = "provider_reported" if origin == "live_model" else "legacy_tuple_adapter"
            if metadata["token_usage_source"] != usage_source or (origin == "live_model" and metadata["finish_reason"] != "STOP"):
                raise ArtifactIntegrityError("Live/adapter evidence contradicts usage or completion provenance")
            if metadata["input_tokens"] > metadata["input_token_bound"] or metadata["output_tokens"] > metadata["max_output_tokens"]:
                raise ArtifactIntegrityError("Successful evidence exceeded reserved token bounds")
            rates = TOKEN_RATES_PER_MILLION[metadata["routed_model"]]
            cost = (metadata["input_tokens"] * rates["input"] + metadata["output_tokens"] * rates["output"]) / 1e6
            recorded_cost = metadata["estimated_cost_usd"]
            if type(recorded_cost) not in (int, float) or not math.isfinite(recorded_cost) or not math.isclose(recorded_cost, cost, abs_tol=1e-9, rel_tol=0):
                raise ArtifactIntegrityError("Generation cost contradicts versioned token accounting")
        else:
            raise ArtifactIntegrityError("Generation has an unknown source evidence type")

        if schema is None:
            if generation["parsed"] is not None or metadata["schema_name"] is not None or request["expected_identity"]:
                raise ArtifactIntegrityError("Unstructured evidence claims schema validation")
            return None
        if not isinstance(schema, dict) or not isinstance(metadata["schema_name"], str) or not metadata["schema_name"]:
            raise ArtifactIntegrityError("Structured evidence lacks schema identity")
        raw = strict_json(generation["raw_text"])
        parsed = generation["parsed"]
        properties = schema.get("properties", {})
        if not isinstance(raw, dict) or not isinstance(parsed, dict) or set(raw) - properties.keys() or set(parsed) - properties.keys():
            raise ArtifactIntegrityError("Output does not match recorded schema fields")
        validate_recorded_schema(raw, schema)
        validate_recorded_schema(parsed, schema)
        expected = dict(request["expected_identity"])
        for field in ("member_id", "round_number"):
            if field in identity and field in properties:
                bound = identity.get("output_member_id", identity[field]) if field == "member_id" else identity[field]
                if field in expected and (expected[field] != bound or type(expected[field]) is not type(bound)):
                    raise ArtifactIntegrityError("Recorded expected identity contradicts scientific request")
                expected[field] = bound
        if any(field not in raw or raw[field] != value or type(raw[field]) is not type(value) for field, value in expected.items()):
            raise ArtifactIntegrityError("Raw output violates recorded expected identity")
        if raw.get("fallback_triggered", False) is not False or parsed.get("fallback_triggered", False) is not False:
            raise ArtifactIntegrityError("Fallback cannot replay as successful research evidence")
        aliases = identity_aliases or {}
        if not isinstance(aliases, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in aliases.items()):
            raise ArtifactIntegrityError("Declared identity aliases must be a text mapping")
        if len(set(aliases.values())) != len(aliases):
            raise ArtifactIntegrityError("Declared identity aliases must be unambiguous")
        for field, value in raw.items():
            normalized = parsed.get(field)
            if normalized == value and type(normalized) is type(value):
                continue
            member_alias = (field == "member_id" and value == identity.get("output_member_id") and normalized == identity["member_id"])
            name_alias = field == "member_name" and aliases.get(normalized) == value
            if not (member_alias or name_alias):
                raise ArtifactIntegrityError("Parsed output differs from raw outside declared identity normalization")
        for field in parsed.keys() - raw.keys():
            default = properties[field].get("default")
            if "default" not in properties[field] or parsed[field] != default or type(parsed[field]) is not type(default):
                raise ArtifactIntegrityError("Parsed output adds undeclared values absent from raw generation")
        return parsed
    except (KeyError, ValueError, TypeError, GenerationProvenanceError) as exc:
        raise ArtifactIntegrityError("Incomplete/corrupt semantic generation evidence") from exc
