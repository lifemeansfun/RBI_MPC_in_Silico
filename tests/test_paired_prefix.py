"""Offline engineering controls for retained actual outputs and branch isolation."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.behavioral.paired_prefix import FrozenPrefix, PairedPrefixOrchestrator
from src.infra.evidence import content_hash, file_hash
from src.infra.exceptions import ArtifactIntegrityError, BudgetExceededError, GenerationProvenanceError, LLMResponseMalformedError
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger
from src.schemas.macro_schema import MacroMeetingSnapshot, ObservationEvidence
from src.schemas.persona_schema import MemberPersona


@pytest.fixture
def roster():
    return [MemberPersona(member_id=f"member_{i}", name=f"Member Name {i}", role="Governor" if i == 0 else "External Member",
                          is_internal=i == 0, tenure="2020-2024", hawk_dove_score=0,
                          voting_priority="Reason only from supplied evidence") for i in range(6)]


@pytest.fixture
def snapshot():
    return MacroMeetingSnapshot(meeting_date="2023-08-10", current_repo_rate_pct=6.5,
                                cpi_headline_yoy_pct=5.4, prev_stance="neutral", input_track="synthetic")


class RecordingMock(LLMClient):
    """Use the real strict parser/receipts; replace only the offline mock text."""
    def __init__(self, *, rates=None, stances=None, fail=None, malformed=False):
        super().__init__(provider="mock", cache_enabled=False)
        self.calls = []
        self.rates = rates or {}
        self.stances = stances or {}
        self.fail = fail
        self.malformed = malformed
        self.expected_prefix = None

    async def generate_with_metadata(self, **kwargs):
        self.calls.append(kwargs)
        request = kwargs["request_identity"]
        if request["condition_id"].startswith("branch_"):
            # The complete actual prefix must already exist before submission.
            document = json.loads(Path(self.expected_prefix).read_text())
            assert document["generation_count"] == 23 and document["status"] == "complete"
            assert len(document["transcripts"]) == 23
            assert all((Path(self.expected_prefix).parent / row["path"]).is_file()
                       for row in document["transcripts"].values())
        if self.fail is not None and len(self.calls) == self.fail:
            raise BudgetExceededError("Offline scripted terminal refusal", context={"request_identity": request})
        return await super().generate_with_metadata(**kwargs)

    def _generate_mock(self, user_prompt, system_prompt, model, response_schema=None, expected_identity=None):
        raw, input_tokens, output_tokens = super()._generate_mock(user_prompt, system_prompt, model, response_schema, expected_identity)
        data = json.loads(raw)
        member = expected_identity["member_id"]
        if response_schema.__name__ == "FinalVoteOutput":
            if self.malformed and member == "member_0":
                return '{"member_id":"wrong"}', input_tokens, output_tokens
            data.update(final_rate_vote_bps=self.rates.get(member, 0), final_stance_vote=self.stances.get(member, "neutral"),
                        dissenting_on_rate=False, dissenting_on_stance=False,
                        official_statement_rationale=f"R4_SECRET_{member}")
        elif response_schema.__name__ == "InitialStanceOutput":
            data["key_rationale"] = f"EARLY_{member}_R1"
        else:
            data["rebuttal_or_critique"] = f"EARLY_{member}_R{data['round_number']}"
        return json.dumps(data), input_tokens, output_tokens


def adapter(tmp_path, client):
    logger = TranscriptLogger(run_id="paired_engineering", output_root=tmp_path / "runs")
    return PairedPrefixOrchestrator(DebateOrchestrator(client, logger))


async def prefix_fixture(tmp_path, snapshot, roster, client=None, **kwargs):
    client = client or RecordingMock()
    paired = adapter(tmp_path, client)
    prefix = await paired.generate_shared_prefix(snapshot, roster, "member_0", experiment_id="offline_engineering",
                                                 replicate_id=1, seed=47, **kwargs)
    client.expected_prefix = prefix.artifact_path
    return paired, client, prefix


def final_channel(prompt):
    marker = "NON-GOVERNOR FINAL INFORMATION (SIMULATION CHOICE):\n"
    before, rest = prompt.split(marker)
    payload, after = rest.split("\n\nTASK:", 1)
    return before, json.loads(payload), after


async def test_exact_actual_prefix_then_only_three_governor_calls_and_field_projection(tmp_path, snapshot, roster):
    paired, client, prefix = await prefix_fixture(tmp_path, snapshot, roster)
    original_bytes = Path(prefix.artifact_path).read_bytes()
    document = prefix.to_dict()
    assert len(client.calls) == 23
    assert {(c["request_identity"]["member_id"], c["request_identity"]["round_number"]) for c in client.calls} == {
        (f"member_{i}", r) for i in range(6) for r in range(1, 5) if (i, r) != (0, 4)}
    for key, row in document["transcripts"].items():
        raw = json.loads((Path(prefix.artifact_path).parent / row["path"]).read_text())
        assert row["raw_output_hash_kind"] == "sha256_utf8_v1"
        assert row["raw_output_hash"] == hashlib.sha256(raw["generation"]["raw_text"].encode()).hexdigest()
        member, number = key.split(":round_")
        assert document["output_hashes"][key] == content_hash(document["outputs"][number][member])
    results = [await paired.run_governor_branch(prefix, snapshot, roster, condition=c, branch_draw_id=1) for c in ("H", "B", "N")]
    assert len(client.calls) == 26 and Path(prefix.artifact_path).read_bytes() == original_bytes
    assert all(len(r["votes"]) == 6 and r["status"] == "complete" for r in results)
    assert all(r["governor_transcript"]["raw_output_hash_kind"] == "sha256_utf8_v1" for r in results)
    assert all(r["votes"][:5] == document["non_governor_votes"] for r in results)
    calls = client.calls[23:]
    parsed = [final_channel(c["user_prompt"]) for c in calls]
    assert parsed[0][0] == parsed[1][0] == parsed[2][0]
    assert parsed[0][2] == parsed[1][2] == parsed[2][2]
    assert calls[0]["system_prompt"] == calls[1]["system_prompt"] == calls[2]["system_prompt"]
    assert parsed[0][1] == {"status": "withheld", "tuples": None}
    assert parsed[1][1]["status"] == "binding ballots"
    assert parsed[2][1]["status"] == "nonbinding preferences"
    assert parsed[1][1]["tuples"] == parsed[2][1]["tuples"] == [
        {"member_id": f"member_{i}", "final_rate_vote_bps": 0, "final_stance_vote": "neutral"} for i in range(1, 6)]
    for call in calls:
        assert "R4_SECRET" not in call["user_prompt"]
        assert all(f"EARLY_member_{i}_R{r}" in call["user_prompt"] for i in range(6) for r in (1, 2, 3))
        assert call["request_identity"]["prefix_hash"] == document["artifact_content_hash"]


async def test_fragmented_raw_ballots_keep_rate_stance_and_joint_agreement(tmp_path, snapshot, roster):
    # Independent hand oracle: pairs of each of three rate/stance labels => 3/15.
    rates = dict(zip([f"member_{i}" for i in range(6)], [-25, -25, 0, 0, 25, 25]))
    stances = dict(zip([f"member_{i}" for i in range(6)], ["neutral", "neutral", "accommodative", "accommodative",
                                                         "withdrawal_of_accommodation", "withdrawal_of_accommodation"]))
    paired, client, prefix = await prefix_fixture(tmp_path, snapshot, roster, RecordingMock(rates=rates, stances=stances))
    result = await paired.run_governor_branch(prefix, snapshot, roster, condition="B", branch_draw_id=1)
    assert len(result["member_votes"]) == 6 and len(client.calls) == 24
    assert result["aggregation"]["rate"]["status"] == result["aggregation"]["stance"]["status"] == "unresolved"
    for kind in ("rate", "stance", "joint"):
        assert result["pair_agreement"][kind] == {"agreeing_pairs": 3, "total_pairs": 15, "value": 0.2}
    assert all(v["dissenting_on_rate"] is False and v["dissenting_on_stance"] is False for v in result["member_votes"])
    assert len(list(tmp_path.rglob("branch_outcome.json"))) == 1


@pytest.mark.parametrize("failure", ["malformed", "refusal", "cancellation"])
async def test_branch_failure_is_retained_propagated_without_retry_or_overwrite(tmp_path, snapshot, roster, failure):
    paired, client, prefix = await prefix_fixture(tmp_path, snapshot, roster)
    client.malformed = failure == "malformed"
    if failure == "refusal":
        client.fail = 24
    if failure == "cancellation":
        original = client.generate_with_metadata
        async def cancel(**kwargs):
            client.calls.append(kwargs)
            raise asyncio.CancelledError()
        client.generate_with_metadata = cancel
    expected = {"malformed": LLMResponseMalformedError, "refusal": BudgetExceededError, "cancellation": asyncio.CancelledError}[failure]
    with pytest.raises(expected):
        await paired.run_governor_branch(prefix, snapshot, roster, condition="N", branch_draw_id="failure_draw")
    assert len(client.calls) == 24
    retained = json.loads(next(tmp_path.rglob("branch_failure.json")).read_text())
    assert retained["status"] == "failed" and retained["condition"] == "N" and retained["branch_draw_id"] == "failure_draw"
    assert retained["prefix_hash"] == prefix.artifact_content_hash and retained["error_type"] == expected.__name__
    assert not list(tmp_path.rglob("branch_outcome.json"))
    with pytest.raises(ArtifactIntegrityError, match="already exists"):
        await paired.run_governor_branch(prefix, snapshot, roster, condition="N", branch_draw_id="failure_draw")
    assert len(client.calls) == 24
    if failure == "cancellation":
        client.generate_with_metadata = original


async def test_fresh_draws_distinct_paths_duplicate_prefix_and_draw_fail_before_call(tmp_path, snapshot, roster):
    paired, client, prefix = await prefix_fixture(tmp_path, snapshot, roster)
    first = await paired.run_governor_branch(prefix, snapshot, roster, condition="H", branch_draw_id=1)
    second = await paired.run_governor_branch(prefix, snapshot, roster, condition="H", branch_draw_id=2)
    assert first["branch_id"] != second["branch_id"] and first["seed"] != second["seed"]
    assert len(list(tmp_path.rglob("branch_outcome.json"))) == 2
    with pytest.raises(ArtifactIntegrityError):
        await paired.run_governor_branch(prefix, snapshot, roster, condition="H", branch_draw_id=1)
    with pytest.raises(ArtifactIntegrityError):
        await paired.generate_shared_prefix(snapshot, roster, "member_0", experiment_id="offline_engineering", replicate_id=1, seed=47)
    assert len(client.calls) == 25


@pytest.mark.parametrize("corruption", ["output", "receipt_bytes", "request_identity", "missing_receipt", "prefix_id", "roster", "settings", "hash_kind"])
async def test_prefix_corruption_rejected_before_any_governor_submission(tmp_path, snapshot, roster, corruption):
    paired, client, prefix = await prefix_fixture(tmp_path, snapshot, roster)
    document = prefix.to_dict()
    path = Path(prefix.artifact_path)
    record = document["transcripts"]["member_1:round_1"]
    receipt_path = path.parent / record["path"]
    if corruption == "output":
        document["outputs"]["1"]["member_1"]["key_rationale"] = "Forged but syntactically valid rationale"
        document["output_hashes"]["member_1:round_1"] = content_hash(document["outputs"]["1"]["member_1"])
    elif corruption == "receipt_bytes":
        receipt_path.write_text(receipt_path.read_text() + " ")
    elif corruption == "missing_receipt":
        receipt_path.unlink()
    elif corruption == "request_identity":
        receipt = json.loads(receipt_path.read_text())
        receipt["generation"]["request_identity"]["member_id"] = "member_2"
        receipt["artifact_content_hash"] = content_hash({k: v for k, v in receipt.items() if k != "artifact_content_hash"})
        receipt_path.write_text(json.dumps(receipt))
        record["sha256"] = file_hash(receipt_path)
        record["artifact_content_hash"] = receipt["artifact_content_hash"]
    elif corruption == "prefix_id":
        document["prefix_id"] = "prefix_" + "f" * 24
    elif corruption == "roster":
        document["roster_ids"] = list(reversed(document["roster_ids"]))
    elif corruption == "settings":
        document["generation_settings"]["temperature"] = 0.77
        document["generation_settings_hash"] = content_hash(document["generation_settings"])
    else:
        record["raw_output_hash_kind"] = "ambiguous_other_kind"
    # Re-sealing adversarial changes exercises semantic controls, beyond digests.
    document["artifact_content_hash"] = content_hash({k: v for k, v in document.items() if k != "artifact_content_hash"})
    path.write_text(json.dumps(document))
    corrupt = FrozenPrefix.from_path(path)
    with pytest.raises((ArtifactIntegrityError, GenerationProvenanceError, FileNotFoundError)):
        await paired.run_governor_branch(corrupt, snapshot, roster, condition="B", branch_draw_id=1)
    assert len(client.calls) == 23
    assert json.loads(next(tmp_path.rglob("branch_failure.json")).read_text())["status"] == "failed"


@pytest.mark.parametrize("changed", ["snapshot", "persona", "settings", "cache"])
async def test_current_inputs_and_client_settings_revalidated(tmp_path, snapshot, roster, changed):
    paired, client, prefix = await prefix_fixture(tmp_path, snapshot, roster)
    if changed == "snapshot":
        snapshot = snapshot.model_copy(update={"cpi_headline_yoy_pct": 6.4})
    elif changed == "persona":
        roster = [p.model_copy(update={"voting_priority": "Changed priority"}) if p.member_id == "member_1" else p for p in roster]
    elif changed == "settings":
        client.cfg = client.cfg.model_copy(deep=True)
        client.cfg.run.max_output_tokens += 1
    else:
        client.cache_enabled = True
    with pytest.raises(GenerationProvenanceError):
        await paired.run_governor_branch(prefix, snapshot, roster, condition="H", branch_draw_id=1)
    assert len(client.calls) == 23


def linked_snapshot(tmp_path, snapshot):
    source = tmp_path / "macro_source.txt"
    source.write_text("Engineering synthetic source fixture, not empirical data")
    observations = tuple(ObservationEvidence(field=field, value=value, units="test", reference_period="fixture",
        vintage="fixture", released_at=datetime(2023, 7, 1, tzinfo=timezone.utc), source_url="https://example.invalid/mock",
        source_file=source.name, source_sha256=file_hash(source), source_pointer="fixture",
        availability_basis="offline engineering fixture") for field, value in snapshot.observable_values().items())
    return snapshot.model_copy(update={"input_track": "source_linked", "meeting_start_date": "2023-08-08",
        "information_cutoff": datetime(2023, 8, 7, tzinfo=timezone.utc), "observations": observations})


async def test_source_hash_rechecked_and_copied_prefix_is_portable(tmp_path, snapshot, roster):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    snapshot = linked_snapshot(source_root, snapshot)
    paired, client, prefix = await prefix_fixture(tmp_path, snapshot, roster, source_root=source_root)
    copied = tmp_path / "copied_prefix"
    shutil.copytree(Path(prefix.artifact_path).parent, copied)
    relocated_source = tmp_path / "relocated_sources"
    shutil.copytree(source_root, relocated_source)
    relocated = FrozenPrefix.from_path(copied / "shared_prefix.json")
    client.expected_prefix = relocated.artifact_path
    result = await paired.run_governor_branch(relocated, snapshot, roster, condition="B", branch_draw_id=1, source_root=relocated_source)
    assert result["prefix_hash"] == prefix.artifact_content_hash and len(client.calls) == 24
    (relocated_source / "macro_source.txt").write_text("Corrupt source")
    with pytest.raises(ValueError, match="hash mismatch"):
        await paired.run_governor_branch(relocated, snapshot, roster, condition="N", branch_draw_id=1, source_root=relocated_source)
    assert len(client.calls) == 24


async def test_live_snapshot_and_persona_preflight_and_cache_replay_refusal(tmp_path, snapshot, roster):
    client = RecordingMock()
    client.provider = "gemini"
    paired = adapter(tmp_path, client)
    with pytest.raises(GenerationProvenanceError, match="source-linked"):
        await paired.generate_shared_prefix(snapshot, roster, "member_0", experiment_id="live_refusal", replicate_id=1)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    linked = linked_snapshot(source_root, snapshot)
    with pytest.raises(GenerationProvenanceError, match="Undated|future"):
        await paired.generate_shared_prefix(linked, roster, "member_0", experiment_id="persona_refusal", replicate_id=1, source_root=source_root)
    client.provider = "mock"
    client.cache_enabled = True
    with pytest.raises(GenerationProvenanceError, match="cache disabled"):
        await paired.generate_shared_prefix(snapshot, roster, "member_0", experiment_id="cache_refusal", replicate_id=1)
    assert client.calls == []


async def test_persona_context_relocation_requires_same_manifest_fit_and_source_bytes(tmp_path, snapshot, roster):
    source_root = tmp_path / "sources"
    source_root.mkdir()
    snapshot = linked_snapshot(source_root, snapshot)
    persona_root = tmp_path / "persona_sources"
    persona_root.mkdir()
    (persona_root / "raw.txt").write_text("Offline engineering synthetic persona source")
    (persona_root / "statement.txt").write_text("Offline engineering synthetic signed statement")
    row = {"decision_date": "2023-04-06", "publication_date": "2023-04-20", "source_file": "raw.txt",
           "source_sha256": file_hash(persona_root / "raw.txt"), "statement_file": "statement.txt",
           "statement_sha256": file_hash(persona_root / "statement.txt")}
    manifest = {"calibration_cutoff": "2023-05-01", "members": {p.member_id: {
        "name": p.name, "role": p.role, "is_internal": p.is_internal, "calibrated_hawk_dove": p.hawk_dove_score,
        "stance_bias": p.stance_bias, "voting_priority": p.voting_priority, "biography": p.biography,
        "exemplar_quotes": p.key_themes, "corpus_sources": [row], "meetings_count": 1} for p in roster}}
    manifest_path = persona_root / "corpus.json"
    manifest_path.write_text(json.dumps(manifest))
    dated = [p.model_copy(update={"provenance_status": "dated_corpus", "calibration_cutoff": "2023-05-01",
                                 "corpus_manifest_hash": file_hash(manifest_path)}) for p in roster]
    context = {"source_root": str(persona_root), "corpus_manifest_path": str(manifest_path)}
    paired, client, prefix = await prefix_fixture(tmp_path, snapshot, dated, source_root=source_root,
                                                 persona_verification_context=context)
    relocated = tmp_path / "relocated_personas"
    shutil.copytree(persona_root, relocated)
    new_context = {"source_root": str(relocated), "corpus_manifest_path": str(relocated / "corpus.json")}
    result = await paired.run_governor_branch(prefix, snapshot, dated, condition="H", branch_draw_id=1,
                                              persona_verification_context=new_context)
    assert result["prefix_hash"] == prefix.artifact_content_hash and len(client.calls) == 24
    (relocated / "raw.txt").write_text("Changed source bytes")
    with pytest.raises(GenerationProvenanceError, match="changed persona source"):
        await paired.run_governor_branch(prefix, snapshot, dated, condition="B", branch_draw_id=1,
                                         persona_verification_context=new_context)
    assert len(client.calls) == 24


async def test_legacy_meeting_behavior_stays_twenty_four_calls(tmp_path, snapshot, roster):
    client = RecordingMock()
    paired = adapter(tmp_path, client)
    decision = await paired.orchestrator.run_meeting(snapshot, roster, "member_0", experiment_id="legacy_control")
    assert len(client.calls) == 24 and decision.generation_count == 24 and len(decision.member_votes) == 6
    assert decision.rate_decision_bps == 0 and decision.stance_decision == "neutral"
