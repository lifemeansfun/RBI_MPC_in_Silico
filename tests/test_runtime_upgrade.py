"""Offline fault/concurrency probes for corrected runtime. No provider calls."""

import asyncio
import json
import multiprocessing
import queue
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from src.infra.cache import LLMCache
from src.infra.checkpoint import CheckpointStore
from src.infra.cost_governor import CostGovernor, PRICE_REVISION
from src.infra.evidence import content_hash
from src.infra.exceptions import (
    ArtifactIntegrityError, BudgetExceededError, BudgetLedgerError,
    GenerationCancelledError, GenerationProvenanceError, LLMInfrastructureError,
    LLMResponseMalformedError, UncertainChargeError, UnknownPriceError,
)
from src.infra.llm_client import LLMClient, ProviderResponse
from src.infra.transcript_logger import TranscriptLogger


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    member_id: str
    round_number: int
    action: int


IDENTITY = {"experiment_id": "study", "condition_id": "full", "meeting_date": "2023-08-10",
            "replicate_id": 1, "member_id": "member", "round_number": 2}
RAW = '{"member_id":"member","round_number":2,"action":35}'


def make_live(tmp_path, *, cap=1.0, timeout=1):
    governor = CostGovernor(cap, tmp_path / "budget.sqlite")
    client = LLMClient(provider="gemini", cache_enabled=False, governor=governor,
                       request_timeout_seconds=timeout)
    client._min_interval = 0
    return client, governor


async def invoke(client, **kwargs):
    return await client.generate_with_metadata(
        user_prompt="Exact user prompt", system_prompt="Exact system prompt",
        model="gemini-3.1-flash-lite", model_epoch="verified-2026-10-05",
        response_schema=Output, request_identity=IDENTITY, input_token_bound=1000,
        max_output_tokens=1000, **kwargs)


@pytest.mark.asyncio
async def test_complete_metadata_tuple_and_replay(tmp_path, monkeypatch):
    cache = LLMCache(tmp_path / "cache.sqlite")
    client = LLMClient(provider="mock", cache=cache)
    monkeypatch.setattr(client, "_generate_mock", lambda *args: (RAW, 10, 5))
    first = await invoke(client, temperature=0.60001, seed=91)
    second = await invoke(client, temperature=0.60001, seed=91)
    assert first.parsed.action == 35
    assert first.metadata.evidence_type == "mock"
    assert first.metadata.user_prompt == "Exact user prompt"
    assert first.metadata.system_prompt == "Exact system prompt"
    assert first.metadata.temperature == 0.60001
    assert first.metadata.seed == 91
    assert first.metadata.max_output_tokens == 1000
    assert first.metadata.schema_hash == content_hash(Output.model_json_schema())
    assert first.metadata.provider_reported_seed is None
    assert first.metadata.served_model is None
    assert second.metadata.evidence_type == "cache_replay"
    assert second.metadata.source_evidence_type == "mock"
    assert second.metadata.source_request_id == first.metadata.request_id
    assert first.metadata.request_id != second.metadata.request_id
    assert second.request_identity == IDENTITY
    assert (await client.generate(user_prompt="x", response_schema=None))[1] is None
    with pytest.raises(FrozenInstanceError):
        first.metadata.seed = 2
    first.request_identity["member_id"] = "changed"
    assert first.request_identity == IDENTITY


def test_canonical_complete_cache_keys():
    base = ("gemini", "gemini-3.1-flash-lite", "system", "user", 0.60001, 42)
    settings = {"max_output_tokens": 1000, "schema": Output.model_json_schema(),
                "parser_version": "v1", "model_epoch": "v1", "request_identity": IDENTITY}
    baseline = LLMCache.compute_key(*base, **settings)
    for field, value in {"max_output_tokens": 1001, "schema": {"different": True},
                         "parser_version": "v2", "model_epoch": "v2",
                         "request_identity": {**IDENTITY, "replicate_id": 2}}.items():
        assert LLMCache.compute_key(*base, **{**settings, field: value}) != baseline
    assert LLMCache.compute_key(*base[:4], 0.60002, base[5], **settings) != baseline
    # The old delimiter serialization conflated these prompt pairs.
    assert LLMCache.compute_key("mock", "m", "a::b", "c", .6, 1) != LLMCache.compute_key("mock", "m", "a", "b::c", .6, 1)
    assert LLMCache.compute_key(*base, **{**settings, "request_identity": dict(reversed(list(IDENTITY.items())))}) == baseline
    with pytest.raises(GenerationProvenanceError):
        LLMCache.compute_key(*base[:4], float("nan"), base[5])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    '{"member_id":"impostor","round_number":2,"action":35}',
    '{"member_id":"member","round_number":3,"action":35}',
    '{"member_id":"member","round_number":2,"action":35,"extra":1}',
    '{"member_id":"member","member_id":"member","round_number":2,"action":35}',
    '{"member_id":"member","round_number":2,"action":NaN}',
    '{"member_id":"member","round_number":2,"action":true}',
    '```json\n' + RAW + '\n```',
])
async def test_failed_output_preserves_raw_request_and_no_fallback(tmp_path, monkeypatch, bad):
    client = LLMClient(provider="mock", cache_enabled=False)
    calls = []
    def generate(*args):
        calls.append(args)
        return bad, 10, 5
    monkeypatch.setattr(client, "_generate_mock", generate)
    with pytest.raises(LLMResponseMalformedError) as caught:
        await invoke(client)
    assert len(calls) == 1
    assert caught.value.context["raw_text"] == bad
    assert caught.value.context["request_identity"] == IDENTITY
    assert caught.value.context["metadata"]["user_prompt"] == "Exact user prompt"
    assert caught.value.context["validation_error"]


@pytest.mark.asyncio
async def test_unknown_price_identity_and_budget_refusal_submit_zero(tmp_path, monkeypatch):
    client, gov = make_live(tmp_path, cap=.001)
    calls = []
    async def count(*args):
        calls.append("count")
        return 10
    async def generate(*args, **kwargs):
        calls.append("generate")
        return ProviderResponse(RAW, 10, 5)
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    with pytest.raises(BudgetExceededError):
        await invoke(client)
    assert calls == []
    assert gov.get_summary()["unresolved_reservations"] == 0
    with pytest.raises(UnknownPriceError):
        await client.generate_with_metadata("x", model="unknown", request_identity=IDENTITY)
    with pytest.raises(GenerationProvenanceError):
        await client.generate_with_metadata("x", model="gemini-3.1-flash-lite", model_epoch="v1")
    with pytest.raises(GenerationProvenanceError):
        await invoke(client, expected_identity={"member_id": "other"})
    assert calls == []


@pytest.mark.asyncio
async def test_live_response_usage_resolved_before_output_failure(tmp_path, monkeypatch):
    client, gov = make_live(tmp_path)
    async def count(*args):
        return 10
    async def generate(*args, **kwargs):
        return ProviderResponse("invalid JSON", 10, 5, "provider-version", "response-1", "STOP")
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    with pytest.raises(LLMResponseMalformedError) as caught:
        await invoke(client)
    assert gov.get_summary()["call_count"] == 1
    assert gov.get_summary()["unresolved_reservations"] == 0
    assert gov.get_summary()["total_estimated_cost_usd"] == .00001
    assert caught.value.context["metadata"]["served_model"] == "provider-version"
    assert caught.value.context["metadata"]["response_id"] == "response-1"
    assert caught.value.context["raw_text"] == "invalid JSON"


@pytest.mark.asyncio
async def test_timeout_retains_reservation_across_restart_and_blocks_next(tmp_path, monkeypatch):
    client, gov = make_live(tmp_path, timeout=.02)
    calls = []
    async def count(*args):
        calls.append("count")
        return 10
    async def hung(*args, **kwargs):
        calls.append("generate")
        await asyncio.sleep(1)
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", hung)
    with pytest.raises(UncertainChargeError) as caught:
        await invoke(client)
    assert caught.value.context["metadata"]["reservation_id"]
    assert calls == ["count", "generate"]
    restarted = CostGovernor(1.0, tmp_path / "budget.sqlite")
    assert restarted.get_summary()["uncertain_reservations"] == 1
    assert restarted.get_summary()["reserved_and_spent_usd"] == .00175
    with pytest.raises(UncertainChargeError):
        await invoke(client)
    assert calls == ["count", "generate"]
    with pytest.raises(BudgetLedgerError):
        restarted.release(caught.value.context["metadata"]["reservation_id"], evidence={"status": "not_submitted", "reference": "unsupported assertion"})


@pytest.mark.asyncio
async def test_cancellation_after_submission_is_terminal_and_persisted(tmp_path, monkeypatch):
    client, gov = make_live(tmp_path)
    submitted = asyncio.Event()
    async def count(*args):
        return 10
    async def hung(*args, **kwargs):
        submitted.set()
        await asyncio.sleep(100)
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", hung)
    task = asyncio.create_task(invoke(client))
    await submitted.wait()
    task.cancel()
    with pytest.raises(GenerationCancelledError):
        await task
    assert gov.get_summary()["uncertain_reservations"] == 1
    with pytest.raises(UncertainChargeError):
        gov.assert_can_submit()


@pytest.mark.asyncio
async def test_preflight_failure_releases_only_with_no_submission_evidence(tmp_path, monkeypatch):
    client, gov = make_live(tmp_path)
    calls = []
    async def count(*args):
        raise RuntimeError("count unavailable")
    async def generate(*args, **kwargs):
        calls.append(1)
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    with pytest.raises(LLMInfrastructureError):
        await invoke(client)
    assert calls == []
    assert gov.get_summary()["reserved_and_spent_usd"] == 0
    with sqlite3.connect(gov.ledger_path) as conn:
        state, evidence = conn.execute("SELECT state,evidence FROM reservations").fetchone()
    assert state == "released"
    assert json.loads(evidence)["status"] == "not_submitted"


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [(None, 5), (10, None), (10, 1001)])
async def test_missing_or_overbound_usage_halts_future_submissions(tmp_path, monkeypatch, usage):
    client, gov = make_live(tmp_path)
    async def count(*args):
        return 10
    async def generate(*args, **kwargs):
        return ProviderResponse(RAW, *usage)
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    with pytest.raises(GenerationProvenanceError):
        await invoke(client)
    with pytest.raises((UncertainChargeError, GenerationProvenanceError)):
        gov.assert_can_submit()
    restarted = CostGovernor(1.0, gov.ledger_path)
    with pytest.raises((UncertainChargeError, GenerationProvenanceError)):
        restarted.assert_can_submit()


def _reserve_worker(ledger, start, done, output, number):
    try:
        gov = CostGovernor(.0025, ledger)
        start.wait(10)
        try:
            rid = gov.reserve(f"worker-{number}", "gemini", "gemini-3.1-flash-lite", 1000, 1000)
            output.put(("reserved", rid))
        except LLMInfrastructureError as exc:
            output.put((type(exc).__name__, str(exc)))
        done.wait(10)
    except Exception as exc:
        output.put(("worker_failed", str(exc)))


def test_cross_process_budget_and_dead_owner_restart(tmp_path):
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(4)
    done = context.Event()
    output = context.Queue()
    ledger = str(tmp_path / "shared.sqlite")
    processes = [context.Process(target=_reserve_worker, args=(ledger, start, done, output, i)) for i in range(4)]
    for process in processes:
        process.start()
    try:
        outcomes = [output.get(timeout=15) for _ in processes]
        assert [value[0] for value in outcomes].count("reserved") == 1, outcomes
        assert [value[0] for value in outcomes].count("BudgetExceededError") == 3, outcomes
        gov = CostGovernor(.0025, ledger)
        assert gov.get_summary()["reserved_and_spent_usd"] == .00175
    finally:
        done.set()
        for process in processes:
            process.join(timeout=15)
            if process.is_alive():
                process.terminate()
                process.join()
    assert all(process.exitcode == 0 for process in processes)
    # A reservation cannot disappear when its owner dies, even before submission.
    restarted = CostGovernor(.0025, ledger)
    with pytest.raises(UncertainChargeError):
        restarted.reserve("restart", "gemini", "gemini-3.1-flash-lite", 1, 1)
    assert restarted.get_summary()["uncertain_reservations"] == 1


def test_ledger_integrity_unknown_price_and_duplicate_reservation(tmp_path):
    gov = CostGovernor(1, tmp_path / "budget.sqlite")
    with pytest.raises(UnknownPriceError):
        gov.reserve("unknown", "gemini", "not-priced", 1, 1)
    rid = gov.reserve("one", "gemini", "gemini-3.1-flash-lite", 10, 10)
    with pytest.raises(BudgetLedgerError):
        gov.reserve("one", "gemini", "gemini-3.1-flash-lite", 10, 10)
    with pytest.raises(BudgetLedgerError):
        gov.release(rid, evidence={})
    with pytest.raises(BudgetLedgerError):
        CostGovernor(2, gov.ledger_path)
    with sqlite3.connect(gov.ledger_path) as conn:
        conn.execute("UPDATE reservations SET reserved_nanos=0")
    with pytest.raises(BudgetLedgerError):
        gov.get_summary()
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"not sqlite")
    with pytest.raises(BudgetLedgerError):
        CostGovernor(1, corrupt)


@pytest.mark.asyncio
async def test_sdk_request_bound_schema_seed_and_thinking_accounted(tmp_path):
    client, gov = make_live(tmp_path)
    calls = []
    class Models:
        def count_tokens(self, **kwargs):
            calls.append(("count", kwargs))
            return SimpleNamespace(total_tokens=10)
        def generate_content(self, **kwargs):
            calls.append(("generate", kwargs))
            return SimpleNamespace(text=RAW, model_version="gemini-3.1-flash-lite",
                                   response_id="provider-response", candidates=[SimpleNamespace(finish_reason="STOP")],
                                   usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5,
                                                                  thoughts_token_count=7, total_token_count=22))
    client._gemini_client = SimpleNamespace(models=Models())
    result = await invoke(client, seed=123, temperature=.600023)
    config = calls[1][1]["config"]
    assert config.max_output_tokens == 1000
    assert config.seed == 123
    assert config.temperature == .600023
    assert config.response_json_schema == Output.model_json_schema()
    assert config.candidate_count == 1
    assert config.system_instruction == "Exact system prompt"
    assert result.metadata.output_tokens == 12  # billed thinking included
    assert result.metadata.served_model == "gemini-3.1-flash-lite"
    assert result.metadata.response_id == "provider-response"
    assert result.metadata.evidence_type == "live_model"
    assert gov.get_summary()["total_estimated_cost_usd"] == .0000205
    envelope = json.loads(calls[0][1]["contents"])
    assert envelope["system_instruction"] == "Exact system prompt"
    assert envelope["response_json_schema"] == Output.model_json_schema()


def test_immutable_logger_conditions_replicates_and_replay(tmp_path):
    logger = TranscriptLogger("same-run", output_root=tmp_path, identity={"experiment_id": "study", "code_hash": "a" * 64})
    first = logger.save_round_transcript("2023-08-10", 1, 2, "member", {"action": 35}, condition_id="full")
    second = logger.save_round_transcript("2023-08-10", 1, 2, "member", {"action": 40}, condition_id="removed")
    replicate = logger.save_round_transcript("2023-08-10", 2, 2, "member", {"action": 50}, condition_id="full")
    assert len({first, second, replicate}) == 3
    before = first.read_bytes()
    with pytest.raises(ArtifactIntegrityError):
        logger.save_round_transcript("2023-08-10", 1, 2, "member", {"action": 35}, condition_id="full")
    logger.save_round_transcript("2023-08-10", 1, 2, "member", {"action": 35}, condition_id="full", replay=True)
    with pytest.raises(ArtifactIntegrityError):
        logger.save_round_transcript("2023-08-10", 1, 2, "member", {"action": 0}, condition_id="full", replay=True)
    assert first.read_bytes() == before
    with pytest.raises(ArtifactIntegrityError):
        TranscriptLogger("same-run", output_root=tmp_path, identity={"experiment_id": "study", "code_hash": "b" * 64})
    with pytest.raises(GenerationProvenanceError):
        logger.save_round_transcript("../outside", 1, 2, "member", {})


def test_cache_hash_corruption_fails_closed_and_preserves_legacy(tmp_path):
    database = tmp_path / "cache.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE response_cache (response_text TEXT)")
        conn.execute("INSERT INTO response_cache VALUES ('legacy')")
    cache = LLMCache(database)
    key = cache.compute_key("mock", "m", None, "p", .6, 1)
    cache.set(key, "mock", "m", None, "p", .6, 1, RAW, 1, 1)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE response_cache_v2 SET payload_json='{}'")
    with pytest.raises(ArtifactIntegrityError):
        cache.get(key)
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT response_text FROM response_cache").fetchone()[0] == "legacy"


def full_identity():
    return {**IDENTITY, **{key: "a" * 64 for key in ("code_hash", "config_hash", "data_hash", "persona_hash", "intervention_hash")},
            "seed_schedule_version": "paired-v1", "model_hash": "b" * 64, "prompt_hash": "c" * 64}


def test_full_identity_checkpoint_artifacts_and_corruption(tmp_path):
    identity = full_identity()
    logger = TranscriptLogger("run", output_root=tmp_path, identity={"experiment_id": "study"})
    artifact = logger.save_meeting_summary("2023-08-10", 1, {"rate": 35}, condition_id="full")
    store = CheckpointStore(tmp_path)
    path = store.save(identity, {"rate": 35}, {"summary": artifact})
    assert store.load(identity)["payload"] == {"rate": 35}
    for field in ("code_hash", "config_hash", "data_hash", "persona_hash", "intervention_hash", "model_hash", "prompt_hash"):
        assert store.load({**identity, field: "d" * 64}) is None
    assert store.load({**identity, "condition_id": "removed"}) is None
    assert store.load({**identity, "replicate_id": 2}) is None
    with pytest.raises(ArtifactIntegrityError):
        store.save(identity, {"rate": 40}, {"summary": artifact})
    with pytest.raises(GenerationProvenanceError):
        store.load({"meeting_date": "2023-08-10"})
    document = json.loads(path.read_text())
    document["payload"]["rate"] = 40
    path.write_text(json.dumps(document))
    with pytest.raises(ArtifactIntegrityError):
        store.load(identity)
    # Restore only our isolated test file to exercise a referenced-file mutation.
    document["payload"]["rate"] = 35
    path.write_text(json.dumps(document))
    artifact.write_text("corrupt")
    with pytest.raises(ArtifactIntegrityError):
        store.load(identity)


@pytest.mark.asyncio
async def test_declared_masked_alias_retains_actual_request_identity(tmp_path, monkeypatch):
    client = LLMClient(provider="mock", cache_enabled=False)
    monkeypatch.setattr(client, "_generate_mock", lambda *args: (RAW.replace('"member"', '"member_2"'), 10, 5))
    result = await client.generate_with_metadata(
        "anonymous Round 2", response_schema=Output,
        request_identity={**IDENTITY, "output_member_id": "member_2"},
        expected_identity={"member_id": "member_2", "round_number": 2})
    assert result.parsed.member_id == "member_2"
    assert result.request_identity["member_id"] == "member"
    assert result.request_identity["output_member_id"] == "member_2"
    logger = TranscriptLogger("masked", output_root=tmp_path)
    path = logger.save_round_transcript("2023-08-10", 1, 2, "member", {"member_id": "member"},
                                       experiment_id="study", condition_id="full", generation=result)
    document = json.loads(path.read_text())
    assert document["generation"]["raw_text"] == RAW.replace('"member"', '"member_2"')
    assert document["artifact_identity"]["member_id"] == "member"
    assert document["generation"]["request_identity"]["output_member_id"] == "member_2"


@pytest.mark.asyncio
async def test_cache_replay_does_not_resubmit_or_debit_again(tmp_path, monkeypatch):
    gov = CostGovernor(1, tmp_path / "budget.sqlite")
    cache = LLMCache(tmp_path / "cache.sqlite")
    client = LLMClient(provider="gemini", cache_enabled=True, governor=gov, cache=cache)
    client._min_interval = 0
    calls = []
    async def count(*args):
        calls.append("count")
        return 10
    async def generate(*args, **kwargs):
        calls.append("generate")
        return ProviderResponse(RAW, 10, 5, "served-v1", "receipt", "STOP")
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    first = await invoke(client)
    second = await invoke(client)
    assert calls == ["count", "generate"]
    assert gov.get_summary()["call_count"] == 1
    assert second.metadata.evidence_type == "cache_replay"
    assert second.metadata.source_request_id == first.metadata.request_id
    assert second.metadata.response_id == "receipt"
    assert second.metadata.reservation_id == first.metadata.reservation_id
    # Metadata preserves source estimated cost; replay does not create a new debit.
    assert second.metadata.estimated_cost_usd == first.metadata.estimated_cost_usd


@pytest.mark.asyncio
async def test_non_normal_finish_rejected_after_retaining_cost(tmp_path, monkeypatch):
    client, gov = make_live(tmp_path)
    async def count(*args):
        return 10
    async def generate(*args, **kwargs):
        return ProviderResponse(RAW, 10, 5, finish_reason="MAX_TOKENS")
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    with pytest.raises(LLMResponseMalformedError) as caught:
        await invoke(client)
    assert caught.value.context["raw_text"] == RAW
    assert gov.get_summary()["call_count"] == 1
    assert gov.get_summary()["unresolved_reservations"] == 0


def test_deleted_ledger_table_cannot_reset_spend(tmp_path):
    path = tmp_path / "budget.sqlite"
    gov = CostGovernor(1, path)
    gov.record_usage("gemini-3.1-flash-lite", 10, 5)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE reservations")
    with pytest.raises(BudgetLedgerError):
        CostGovernor(1, path)


@pytest.mark.asyncio
async def test_empty_output_artifact_replay_and_missing_corrupt_evidence(tmp_path, monkeypatch):
    from src.infra.transcript_logger import read_transcript
    source_root = tmp_path / "source"
    target_root = tmp_path / "empty-target"
    client = LLMClient(provider="mock", cache_enabled=False)
    monkeypatch.setattr(client, "_generate_mock", lambda *args: (RAW, 10, 5))
    result = await invoke(client)
    source = TranscriptLogger("run", output_root=source_root, identity={"experiment_id": "study"})
    round_path = source.save_round_transcript("2023-08-10", 1, 2, "member", result.parsed.model_dump(),
                                             condition_id="full", generation=result)
    summary_path = source.save_meeting_summary("2023-08-10", 1, {"rate": 35}, condition_id="full")
    assert not target_root.exists()
    target = TranscriptLogger("run", output_root=target_root, identity={"experiment_id": "study"})
    recreated_round = target.replay_artifact(round_path, IDENTITY)
    recreated_summary = target.replay_artifact(summary_path, {key: value for key, value in IDENTITY.items() if key not in {"round_number", "member_id"}})
    assert recreated_round.read_bytes() == round_path.read_bytes()
    assert recreated_summary.read_bytes() == summary_path.read_bytes()
    events = [json.loads(line) for line in target.log_file.read_text().splitlines()]
    assert len(events) == 2
    assert all(event["data"]["evidence_type"] == "deterministic_artifact_replay" for event in events)
    with pytest.raises(ArtifactIntegrityError):
        target.replay_artifact(tmp_path / "missing.json")
    with pytest.raises(ArtifactIntegrityError):
        read_transcript(round_path, {**IDENTITY, "member_id": "impostor"})
    document = json.loads(round_path.read_text())
    document["generation"]["raw_text"] = RAW.replace('"member"', '"other"')
    # Even rehashed outer content cannot hide a semantic identity contradiction.
    document.pop("artifact_content_hash")
    document["artifact_content_hash"] = content_hash(document)
    round_path.write_text(json.dumps(document))
    with pytest.raises(ArtifactIntegrityError):
        target.replay_artifact(round_path)


def _rehash_transcript(path, mutation):
    document = json.loads(path.read_text())
    mutation(document)
    document.pop("artifact_content_hash")
    document["artifact_content_hash"] = content_hash(document)
    path.write_text(json.dumps(document))


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda d: d["generation"]["parsed"].pop("action"),
    lambda d: d["generation"].update(raw_text='{"member_id":"member","round_number":2}',
                                      parsed={"member_id": "member", "round_number": 2}),
    lambda d: d["generation"].update(raw_text='{"member_id":"member","round_number":2,"action":true}',
                                      parsed={"member_id": "member", "round_number": 2, "action": True}),
    lambda d: d["generation"]["metadata"].update(evidence_type="live_model"),
    lambda d: d.update(action=40),
])
async def test_replay_rejects_rehashed_schema_track_and_payload_contradictions(tmp_path, monkeypatch, mutation):
    from src.infra.transcript_logger import read_transcript
    client = LLMClient(provider="mock", cache_enabled=False)
    monkeypatch.setattr(client, "_generate_mock", lambda *args: (RAW, 10, 5))
    result = await invoke(client)
    logger = TranscriptLogger("source", output_root=tmp_path, identity={"experiment_id": "study"})
    path = logger.save_round_transcript("2023-08-10", 1, 2, "member", result.parsed.model_dump(),
                                        condition_id="full", generation=result)
    assert read_transcript(path)["generation"]["metadata"]["evidence_type"] == "mock"
    _rehash_transcript(path, mutation)
    with pytest.raises(ArtifactIntegrityError):
        read_transcript(path)


def test_submit_rechecks_uncertain_ledger_atomically(tmp_path):
    governor = CostGovernor(1, tmp_path / "budget.sqlite")
    earlier = governor.reserve("earlier", "gemini", "gemini-3.1-flash-lite", 100, 100)
    pending = governor.reserve("pending", "gemini", "gemini-3.1-flash-lite", 100, 100)
    governor.mark_submitted(earlier)
    governor.assert_can_submit()
    # Another task settles an unknown charge after the pending task's precheck.
    governor.mark_uncertain(earlier, "provider timeout")
    with pytest.raises(UncertainChargeError):
        governor.mark_submitted(pending)
    with sqlite3.connect(governor.ledger_path) as connection:
        assert connection.execute("SELECT state FROM reservations WHERE reservation_id=?", (pending,)).fetchone()[0] == "reserved"


def test_deleted_budget_config_row_cannot_reinitialize_cap(tmp_path):
    path = tmp_path / "budget.sqlite"
    governor = CostGovernor(1, path)
    governor.record_usage("gemini-3.1-flash-lite", 10, 5)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM budget_config")
    with pytest.raises(BudgetLedgerError):
        CostGovernor(2, path)


@pytest.mark.asyncio
async def test_missing_finish_evidence_is_failed_and_known_cost_retained(tmp_path, monkeypatch):
    client, governor = make_live(tmp_path)
    async def count(*args):
        return 10
    async def generate(*args, **kwargs):
        return ProviderResponse(RAW, 10, 5)
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    with pytest.raises(LLMResponseMalformedError) as caught:
        await invoke(client)
    assert caught.value.context["raw_text"] == RAW
    assert caught.value.context["metadata"]["estimated_cost_usd"] == .00001
    assert governor.get_summary()["call_count"] == 1
    assert governor.get_summary()["unresolved_reservations"] == 0


@pytest.mark.asyncio
async def test_bound_violation_failure_context_retains_settled_cost(tmp_path, monkeypatch):
    client, governor = make_live(tmp_path)
    async def count(*args):
        return 10
    async def generate(*args, **kwargs):
        return ProviderResponse(RAW, 10, 1001, finish_reason="STOP")
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    with pytest.raises(GenerationProvenanceError) as caught:
        await invoke(client)
    assert caught.value.context["metadata"]["estimated_cost_usd"] == .001504
    assert governor.get_summary()["bound_violations"] == 1
    assert governor.get_summary()["unresolved_reservations"] == 0
    with sqlite3.connect(governor.ledger_path) as connection:
        connection.execute("UPDATE reservations SET reason=NULL")
    with pytest.raises(BudgetLedgerError):
        governor.assert_can_submit()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda payload: payload["metadata"].update(evidence_type="live_model"),
    lambda payload: payload["metadata"].update(cache_replay=True),
    lambda payload: payload["metadata"].update(estimated_cost_usd=.00001),
])
async def test_mock_cache_cannot_relabel_even_with_recomputed_digest(tmp_path, monkeypatch, mutation):
    cache = LLMCache(tmp_path / "cache.sqlite")
    client = LLMClient(provider="mock", cache_enabled=True, cache=cache)
    calls = []
    def generate(*args):
        calls.append(1)
        return RAW, 10, 5
    monkeypatch.setattr(client, "_generate_mock", generate)
    first = await invoke(client)
    with sqlite3.connect(cache.db_path) as connection:
        payload = json.loads(connection.execute("SELECT payload_json FROM response_cache_v2").fetchone()[0])
        mutation(payload)
        connection.execute("UPDATE response_cache_v2 SET payload_json=?,payload_hash=?", (json.dumps(payload), content_hash(payload)))
    with pytest.raises(ArtifactIntegrityError):
        await invoke(client)
    assert calls == [1]
    assert cache.get(first.metadata.cache_key)["metadata"] == payload["metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["response_id", "reservation_id", "cost", "tokens"])
async def test_live_cache_reconciles_ledger_receipt_without_new_submission(tmp_path, monkeypatch, tamper):
    governor = CostGovernor(1, tmp_path / "budget.sqlite")
    cache = LLMCache(tmp_path / "cache.sqlite")
    client = LLMClient(provider="gemini", cache_enabled=True, cache=cache, governor=governor)
    client._min_interval = 0
    calls = []
    async def count(*args):
        calls.append("count")
        return 10
    async def generate(*args, **kwargs):
        calls.append("generate")
        return ProviderResponse(RAW, 10, 5, "served-v1", "source-receipt", "STOP")
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    await invoke(client)
    with sqlite3.connect(cache.db_path) as connection:
        payload = json.loads(connection.execute("SELECT payload_json FROM response_cache_v2").fetchone()[0])
        if tamper == "response_id":
            payload["metadata"]["response_id"] = "wrong-receipt"
        elif tamper == "reservation_id":
            payload["metadata"]["reservation_id"] = "missing-reservation"
        elif tamper == "cost":
            payload["metadata"]["estimated_cost_usd"] = .00002
        else:
            payload["metadata"].update(input_tokens=20, estimated_cost_usd=.0000125)
        connection.execute("UPDATE response_cache_v2 SET payload_json=?,payload_hash=?", (json.dumps(payload), content_hash(payload)))
    with pytest.raises((ArtifactIntegrityError, BudgetLedgerError)):
        await invoke(client)
    assert calls == ["count", "generate"]
    assert governor.get_summary()["call_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", [35, 40])
async def test_recorded_action_domain_replay_and_invalid_rate_injection(tmp_path, monkeypatch, rate):
    from src.schemas.debate_schema import FinalVoteOutput
    from src.infra.transcript_logger import read_transcript
    identity = {**IDENTITY, "round_number": 4}
    data = {"member_id": "member", "member_name": "Member", "is_internal": False,
            "final_rate_vote_bps": rate, "final_stance_vote": "neutral", "official_statement_rationale": "Synthetic fixture"}
    client = LLMClient(provider="mock", cache_enabled=False)
    monkeypatch.setattr(client, "_generate_mock", lambda *args: (json.dumps(data), 10, 5))
    result = await client.generate_with_metadata("Round 4", response_schema=FinalVoteOutput, request_identity=identity,
                                                expected_identity={"member_name": "Member", "is_internal": False})
    logger = TranscriptLogger("source", output_root=tmp_path, identity={"experiment_id": "study"})
    path = logger.save_round_transcript("2023-08-10", 1, 4, "member", result.parsed.model_dump(),
                                        condition_id="full", generation=result)
    assert read_transcript(path)["final_rate_vote_bps"] == rate
    def mutate(document):
        raw = json.loads(document["generation"]["raw_text"])
        raw["final_rate_vote_bps"] = 30
        document["generation"]["raw_text"] = json.dumps(raw)
        document["generation"]["parsed"]["final_rate_vote_bps"] = 30
        document["final_rate_vote_bps"] = 30
    _rehash_transcript(path, mutate)
    with pytest.raises(ArtifactIntegrityError):
        read_transcript(path)


def test_required_generation_metadata_matches_runtime_contract():
    from dataclasses import fields
    from src.infra.llm_client import GenerationMetadata
    from src.infra.generation_evidence import REQUIRED_METADATA_FIELDS
    assert REQUIRED_METADATA_FIELDS == {field.name for field in fields(GenerationMetadata)}


@pytest.mark.asyncio
async def test_missing_schema_dependency_fails_before_provider_or_reservation(tmp_path, monkeypatch):
    import builtins
    client, governor = make_live(tmp_path)
    calls = []
    original_import = builtins.__import__
    def blocked_import(name, *args, **kwargs):
        if name == "jsonschema" or name.startswith("jsonschema."):
            raise ImportError("Dependency unavailable fixture")
        return original_import(name, *args, **kwargs)
    async def count(*args):
        calls.append("count")
        return 10
    async def generate(*args, **kwargs):
        calls.append("generate")
        return ProviderResponse(RAW, 10, 5, finish_reason="STOP")
    monkeypatch.setattr(client, "_count_gemini_input", count)
    monkeypatch.setattr(client, "_call_gemini", generate)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", blocked_import)
        with pytest.raises(ArtifactIntegrityError, match="dependency"):
            await invoke(client)
    assert calls == []
    assert governor.get_summary()["reserved_and_spent_usd"] == 0


def test_schema_references_are_local_and_nested_integer_validation_is_strict():
    from src.infra.generation_evidence import validate_recorded_schema
    schema = {"type": "object", "properties": {"entry": {"$ref": "#/$defs/Entry"}}, "required": ["entry"],
              "$defs": {"Entry": {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]}}}
    validate_recorded_schema({"entry": {"value": 35}}, schema)
    for wrong in (True, "35", 35.0):
        with pytest.raises(ArtifactIntegrityError):
            validate_recorded_schema({"entry": {"value": wrong}}, schema)
    with pytest.raises(ArtifactIntegrityError, match="external references"):
        validate_recorded_schema({}, {"$ref": "https://invalid.example/schema"}, schema_only=True)


@pytest.mark.asyncio
async def test_real_mock_client_masked_meeting_has_replayable_complete_evidence(tmp_path):
    from src.behavioral.debate_orchestrator import DebateOrchestrator
    from src.schemas.macro_schema import MacroMeetingSnapshot
    from src.schemas.persona_schema import MemberPersona
    from src.infra.transcript_logger import read_transcript
    roster = [MemberPersona(member_id=f"original_{i}", name=f"Person {i}",
                            role="Governor" if i == 0 else "External Member", is_internal=i == 0,
                            tenure="2020-2024", hawk_dove_score=0.0, voting_priority="Synthetic fixture") for i in range(6)]
    snapshot = MacroMeetingSnapshot(meeting_date="2023-08-10", current_repo_rate_pct=6.5,
                                    cpi_headline_yoy_pct=5.4, prev_stance="neutral", input_track="synthetic")
    logger = TranscriptLogger("source", output_root=tmp_path / "source", identity={"experiment_id": "masked"})
    client = LLMClient(provider="mock", cache_enabled=False)
    decision = await DebateOrchestrator(client, logger).run_meeting(snapshot, roster, roster[0].member_id,
        experiment_id="masked", mask_identity=True, mask_date=True)
    rounds = sorted((tmp_path / "source").rglob("round_*.json"))
    assert len(rounds) == decision.generation_count == 24
    summaries = sorted((tmp_path / "source").rglob("meeting_outcome.json"))
    target = TranscriptLogger("replay", output_root=tmp_path / "empty_target", identity={"experiment_id": "masked"})
    for source in rounds + summaries:
        document = read_transcript(source)
        assert document["artifact_identity"]["experiment_id"] == "masked"
        if "round_number" in document["artifact_identity"]:
            assert document["generation"]["metadata"]["evidence_type"] == "mock"
            assert document["member_id"].startswith("original_")
        recreated = target.replay_artifact(source)
        assert recreated.read_bytes() == source.read_bytes()
    assert len(list((tmp_path / "empty_target").rglob("round_*.json"))) == 24


@pytest.mark.parametrize("corruption", ["missing", "empty_file"])
def test_previously_initialized_ledger_cannot_reset_on_new_owner(tmp_path, corruption):
    path = tmp_path / "budget.sqlite"
    governor = CostGovernor(1, path)
    governor.record_usage("gemini-3.1-flash-lite", 10, 5)
    if corruption == "missing":
        path.unlink()
    else:
        path.write_bytes(b"")
    with pytest.raises(BudgetLedgerError):
        CostGovernor(1, path)
