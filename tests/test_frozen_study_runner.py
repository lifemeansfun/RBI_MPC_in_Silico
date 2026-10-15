"""Complete engineering path and fail-before-client controls for the new runner."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from src.backtest.run_frozen_study import (
    create_engineering_fixture, read_spec, planned_schedule, run_study,
    replay_study, live_preflight, scientific_recipe_hash,
)
from src.infra.evidence import content_hash
from src.infra.exceptions import GenerationProvenanceError, BudgetLedgerError
from src.schemas.frozen_study_schema import StudySpec


def _protocol(tmp_path):
    return create_engineering_fixture(tmp_path / "bundle")


def _seal_file(path, document):
    document.pop("artifact_content_hash", None)
    document["artifact_content_hash"] = content_hash(document)
    path.write_text(json.dumps(document, indent=2))


def _forbid_client(monkeypatch):
    from src.infra.llm_client import LLMClient
    monkeypatch.setattr(LLMClient, "__init__", lambda *a, **k: pytest.fail("Client constructed before resource/source gates"))


def test_default_validation_never_constructs_client(tmp_path, monkeypatch):
    protocol = _protocol(tmp_path)
    _forbid_client(monkeypatch)
    result = asyncio.run(run_study(protocol, tmp_path / "validate"))
    assert result["actual_generation_calls"] == 0
    assert result["planned_generation_calls"] == 29
    assert result["scientific_readiness"] == "not_established_by_engineering_validation"


def test_complete_mock_path_and_independent_replay(tmp_path, monkeypatch):
    protocol = _protocol(tmp_path)
    result = asyncio.run(run_study(protocol, tmp_path / "mock", execution="mock"))
    assert result["status"] == "complete" and result["actual_generation_calls"] == 29
    assert result["evidence_type"] == "engineering_mock" and result["provider_spend_usd"] == 0
    root = tmp_path / "mock"
    assert len(list(root.rglob("shared_prefix.json"))) == 1
    assert len(list(root.rglob("branch_outcome.json"))) == 6
    assert len(list(root.rglob("round_*.json"))) == 29
    analysis = json.loads((root / "analysis.json").read_text())["B_minus_H"]
    assert all(v["complete"] == 2 for v in analysis["condition_counts"].values())
    _forbid_client(monkeypatch)
    replay = replay_study(protocol, root, tmp_path / "replay")
    assert replay["actual_generation_calls"] == 0
    assert replay["source_evidence_track"] == "engineering_mock"
    assert json.loads((root / "analysis.json").read_text()) == json.loads((tmp_path / "replay/analysis.json").read_text())


@pytest.mark.parametrize("target", ["inputs/snapshot.json", "code/src/schemas/macro_schema.py"])
def test_corrupt_frozen_input_or_code_blocks_before_client(tmp_path, monkeypatch, target):
    protocol = _protocol(tmp_path)
    path = protocol.parent / target
    path.write_bytes(path.read_bytes() + b"\nCORRUPTION\n")
    _forbid_client(monkeypatch)
    with pytest.raises(GenerationProvenanceError, match="hash mismatch"):
        asyncio.run(run_study(protocol, tmp_path / "blocked", execution="mock"))
    failure = json.loads((tmp_path / "blocked/failure.json").read_text())
    assert failure["actual_generation_calls"] == 0 and failure["planned_branches"] == 6
    partial = json.loads((tmp_path / "blocked/partial_analysis.json").read_text())["B_minus_H"]
    assert partial["all_planned_point"] is None
    assert partial["condition_counts"]["H"]["unattempted"] == 2


def test_changed_cutoff_even_resealed_fails_before_client(tmp_path, monkeypatch):
    protocol = _protocol(tmp_path)
    document = json.loads(protocol.read_text())
    document["meetings"][0]["information_cutoff"] = "2023-08-09T00:00:00+05:30"
    _seal_file(protocol, document)
    _forbid_client(monkeypatch)
    with pytest.raises(GenerationProvenanceError, match="date/cutoff/roster"):
        asyncio.run(run_study(protocol, tmp_path / "blocked"))


def test_counterbalanced_schedule_and_no_duplicate_draw_ids(tmp_path):
    spec = read_spec(_protocol(tmp_path))
    extended = spec.model_copy(update={"governor_draws": 6})
    schedule = planned_schedule(extended)
    assert len({row["branch_id"] for row in schedule}) == 18
    orders = [tuple(row["condition"] for row in schedule[i:i+3]) for i in range(0, 18, 3)]
    assert len(set(orders)) == 6


def test_live_fixture_and_existing_destinations_refused(tmp_path, monkeypatch):
    protocol = _protocol(tmp_path)
    _forbid_client(monkeypatch)
    with pytest.raises(GenerationProvenanceError, match="distinct registered"):
        asyncio.run(run_study(protocol, tmp_path / "live", execution="live"))
    with pytest.raises(FileExistsError):
        asyncio.run(run_study(protocol, tmp_path / "live"))
    with pytest.raises(FileExistsError):
        create_engineering_fixture(protocol.parent)


def test_replay_detects_resealed_ballot_disagreement(tmp_path):
    protocol = _protocol(tmp_path)
    asyncio.run(run_study(protocol, tmp_path / "mock", execution="mock"))
    artifact = next((tmp_path / "mock").rglob("branch_outcome.json"))
    document = json.loads(artifact.read_text())
    document["votes"][0]["vote"] = 25
    _seal_file(artifact, document)
    with pytest.raises(ValueError):
        replay_study(protocol, tmp_path / "mock", tmp_path / "bad_replay")


def _live_spec_for_preflight(tmp_path):
    """Structure fixture for read-only preflight, never claims actual readiness."""
    protocol = _protocol(tmp_path)
    document = read_spec(protocol).model_dump(mode="json")
    document["evidence_track"] = "registered_simulator_study"
    document["settings"].update(provider="gemini", model="gemini-3.1-flash-lite", allowed_served_models=["gemini-3.1-flash-lite"])
    packet = document["meetings"][0]
    packet.update(exposure="exposed_retrospective", roster_basis="retrospective_oracle_attendance", history_policy="complete_dated_history")
    root = protocol.parent
    def record(name, value):
        payload = json.dumps(value).encode()
        (root / name).write_bytes(payload)
        ref = {"path": name, "sha256": hashlib.sha256(payload).hexdigest()}
        document["files"].append(ref)
        return ref
    packet["corpus_manifest"] = record("corpus.json", {"fixture": True})
    document["readiness_receipts"] = {gate: record(gate + ".json", {
        "gate": gate, "status": "passed", "experiment_id": document["experiment_id"],
        "reviewer": "TEST FIXTURE", "evidence": ["TEST FIXTURE"], "limitations": ["TEST FIXTURE"],
        "external_timestamp_url": "https://example.invalid/test-fixture"})
        for gate in ("contribution", "source_and_ontology", "precision_and_resources", "preregistration")}
    ledger = tmp_path / "absent.sqlite"
    resources = document["resources"]
    resources.update(max_live_calls=29, max_token_count_requests=29, max_provider_requests=58,
                     max_spend_usd=1.0, input_token_bound=100,
                     ledger_path=str(ledger), ledger_cap_usd=1.0)
    from src.infra.cost_governor import PRICE_REVISION
    resources["accounting_receipt"] = record("account.json", {"status": "externally_reconciled",
        "provider_account_evidence": ["TEST FIXTURE"], "authorization_evidence": ["TEST FIXTURE"],
        "ledger_path": str(ledger), "price_revision": PRICE_REVISION,
        "remaining_allowance_usd": 1.0, "requests_available": 58,
        "request_quota_definition": "generation_plus_token_count_conservative_bound"})
    document.pop("artifact_content_hash")
    document["artifact_content_hash"] = content_hash(document)
    spec = StudySpec.model_validate_json(json.dumps(document))
    for ref in (*spec.readiness_receipts.values(), spec.resources.accounting_receipt):
        path = root / ref.path
        receipt = json.loads(path.read_text())
        receipt["scientific_recipe_hash"] = scientific_recipe_hash(spec)
        path.write_text(json.dumps(receipt))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        for file_ref in document["files"]:
            if file_ref["path"] == ref.path:
                file_ref["sha256"] = digest
        for gate, file_ref in document["readiness_receipts"].items():
            if file_ref["path"] == ref.path:
                file_ref["sha256"] = digest
        if document["resources"]["accounting_receipt"]["path"] == ref.path:
            document["resources"]["accounting_receipt"]["sha256"] = digest
    document.pop("artifact_content_hash")
    document["artifact_content_hash"] = content_hash(document)
    return StudySpec.model_validate_json(json.dumps(document)), root, ledger


def test_absent_accounting_never_initializes_ledger(tmp_path):
    spec, root, ledger = _live_spec_for_preflight(tmp_path)
    with pytest.raises(BudgetLedgerError, match="cannot be initialized"):
        live_preflight(spec, root)
    assert not ledger.exists() and not ledger.with_name(ledger.name + ".initialized.json").exists()


def test_existing_ledger_unresolved_charge_blocks(tmp_path):
    spec, root, ledger = _live_spec_for_preflight(tmp_path)
    from src.infra.cost_governor import CostGovernor
    governor = CostGovernor(1.0, ledger)
    reservation = governor.reserve("test-pending-charge", "gemini", "gemini-3.1-flash-lite", 100, 2048)
    before = ledger.read_bytes()
    with pytest.raises(BudgetLedgerError, match="unresolved charges"):
        live_preflight(spec, root)
    assert ledger.read_bytes() == before
    assert reservation


def test_infeasible_call_budget_refused_before_accounting(tmp_path):
    spec, root, ledger = _live_spec_for_preflight(tmp_path)
    limited = spec.model_copy(update={"resources": spec.resources.model_copy(update={"max_live_calls": 28})})
    with pytest.raises(BudgetLedgerError, match="cannot cover planned"):
        live_preflight(limited, root)
    assert not ledger.exists()


def test_malformed_branch_stops_with_full_planned_denominator(tmp_path, monkeypatch):
    from src.infra.llm_client import LLMClient
    from src.infra.exceptions import LLMResponseMalformedError
    protocol = _protocol(tmp_path)
    generate = LLMClient.generate_with_metadata
    async def failing(self, *args, **kwargs):
        if kwargs.get("request_identity", {}).get("branch_condition"):
            raise LLMResponseMalformedError("Engineering fixture malformed branch")
        return await generate(self, *args, **kwargs)
    monkeypatch.setattr(LLMClient, "generate_with_metadata", failing)
    with pytest.raises(LLMResponseMalformedError):
        asyncio.run(run_study(protocol, tmp_path / "failed", execution="mock"))
    root = tmp_path / "failed"
    partial = json.loads((root / "partial_analysis.json").read_text())["B_minus_H"]
    assert partial["all_planned_point"] is None
    assert sum(c["planned"] for c in partial["condition_counts"].values()) == 6
    assert sum(c["failed"] for c in partial["condition_counts"].values()) == 1
    assert sum(c["unattempted"] for c in partial["condition_counts"].values()) == 5
    assert len(list(root.rglob("shared_prefix.json"))) == 1
    assert len(list(root.rglob("branch_failure.json"))) == 1
    assert json.loads((root / "failure.json").read_text())["client_generation_attempts"] == 24


def test_replay_requires_original_frozen_input_identity(tmp_path):
    protocol = _protocol(tmp_path)
    asyncio.run(run_study(protocol, tmp_path / "mock", execution="mock"))
    artifact = next((tmp_path / "mock").rglob("shared_prefix.json"))
    document = json.loads(artifact.read_text())
    document["snapshot_hash"] = "0" * 64
    _seal_file(artifact, document)
    with pytest.raises(GenerationProvenanceError, match="ex ante frozen"):
        replay_study(protocol, tmp_path / "mock", tmp_path / "bad_replay")


def test_readiness_for_a_different_recipe_cannot_be_reused(tmp_path):
    spec, root, _ = _live_spec_for_preflight(tmp_path)
    changed = spec.model_copy(update={"seed_base": 43})
    with pytest.raises(GenerationProvenanceError, match="readiness receipt"):
        live_preflight(changed, root)


def test_alternate_code_root_cannot_bypass_executing_tree_check(tmp_path, monkeypatch):
    protocol = _protocol(tmp_path)
    _forbid_client(monkeypatch)
    with pytest.raises(GenerationProvenanceError, match="executing module tree"):
        asyncio.run(run_study(protocol, tmp_path / "blocked", execution="mock", code_root=protocol.parent / "code"))
    assert json.loads((tmp_path / "blocked/failure.json").read_text())["actual_generation_calls"] == 0
