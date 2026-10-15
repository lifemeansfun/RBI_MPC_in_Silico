"""Comparator contract probes use the actual runtime with scripted offline JSON.

No provider call is submitted; these tests do not establish forecast quality.
"""
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.behavioral.comparator_forecasters import (
    ComparatorForecaster, ComparatorRoster, ForecastBallot, JointForecastOutput,
    RosterMember, read_comparator_record,
)
from src.infra.evidence import canonical_json, content_hash, file_hash
from src.infra.exceptions import (
    ArtifactIntegrityError, BudgetExceededError, GenerationCancelledError,
    GenerationProvenanceError, LLMResponseMalformedError, UncertainChargeError,
)
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger, read_transcript
from src.schemas.macro_schema import MacroMeetingSnapshot, ObservationEvidence
from src.schemas.persona_schema import MemberPersona


def inputs():
    snapshot = MacroMeetingSnapshot(meeting_date="2023-08-10", meeting_start_date="2023-08-08",
        information_cutoff=datetime(2023, 8, 8, tzinfo=timezone.utc), input_track="synthetic",
        current_repo_rate_pct=6.5, cpi_headline_yoy_pct=4.81, prev_stance="withdrawal_of_accommodation",
        real_rate_decision_bps=50, real_dissenters_rate=["hidden_truth_only"],
        real_reservations=["hidden_reservation_only"])
    members = tuple(RosterMember(member_id=f"person{i}", member_name=f"Original Name {i}",
        role="Governor" if i == 0 else "External Member", is_internal=i == 0) for i in range(6))
    roster = ComparatorRoster(version="roster_oct2020_aug2024_v1", valid_from="2020-10-01",
        valid_through="2024-08-31", governor_id="person0", members=members)
    personas = [MemberPersona(member_id=m.member_id, name=m.member_name, role=m.role,
        is_internal=m.is_internal, tenure="2020-10 to 2024-10", hawk_dove_score=i/10,
        voting_priority=f"Priority marker {i}; colleague Original Name 0", key_themes=["Theme marker"],
        biography="Biography marker", provenance_status="assumed") for i, m in enumerate(members)]
    return snapshot, roster, personas


def setup(tmp_path, monkeypatch, *, mode="joint_persona", masked=False):
    client = LLMClient(provider="mock", cache_enabled=False)
    logger = TranscriptLogger("probe", output_root=tmp_path/"outputs", condition_id=mode,
                              identity={"experiment_id": "offline_comparator_controls"})
    forecaster = ComparatorForecaster(client, logger, source_root=tmp_path)
    snapshot, roster, personas = inputs()
    calls = []
    def fixture(user, system, model, schema, expected):
        calls.append({"user": user, "system": system, "model": model, "schema": schema.__name__})
        return canonical_json(ballots(roster, masked=masked)), 200, 300
    monkeypatch.setattr(client, "_generate_mock", fixture)
    return forecaster, snapshot, roster, personas, calls


def freeze(forecaster, snapshot, roster, personas, *, mode="joint_persona", **kwargs):
    return forecaster.freeze(snapshot, roster, mode=mode,
        personas=personas if mode == "joint_persona" else (),
        experiment_id="offline_comparator_controls", condition_id=mode, replicate_id=1,
        model="mock", temperature=0.2, seed=17, max_output_tokens=4096, **kwargs)


def ballots(roster, *, masked=False, rates=None, stances=None, committee_rate=0,
            committee_stance="withdrawal_of_accommodation"):
    rates = rates or [0]*6
    stances = stances or ["withdrawal_of_accommodation"]*6
    return {"member_id": "comparator_forecaster", "round_number": 1, "fallback_triggered": False,
        "rate_decision_bps": committee_rate, "stance_decision": committee_stance,
        "member_ballots": [{"member_id": f"member_{i+1}" if masked else m.member_id,
                            "member_name": f"Simulated Member {i+1}" if masked else m.member_name,
                            "is_internal": m.is_internal, "rate_vote_bps": rates[i], "stance_vote": stances[i],
                            "rate_choice_disagreement": rates[i] != committee_rate,
                            "formal_stance_dissent": stances[i] != committee_stance,
                            "rationale": "Offline fixture rationale"} for i, m in enumerate(roster.members)],
        "committee_rationale": "Offline fixture committee rationale"}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["joint_persona", "macro_only"])
async def test_full_runtime_evidence_and_anchored_replay(tmp_path, monkeypatch, mode):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch, mode=mode)
    plan = freeze(forecaster, snapshot, roster, personas, mode=mode)
    record = await forecaster.generate(plan)
    assert len(calls) == 1
    assert record["generation"]["metadata"]["evidence_type"] == "mock"
    assert record["generation"]["metadata"]["token_usage_source"] == "offline_mock_fixture"
    assert record["usage"]["actual_live_provider_submissions"] == 0
    assert record["usage"]["input_tokens_recorded"] == 200
    assert record["usage"]["planned_output_token_bound"] == 4096
    assert record["usage"]["budget_matched_to_panel"] is False
    assert record["usage"]["estimated_cost_usd_from_recorded_usage"] == 0
    assert record["prediction"]["rate_decision_bps"] == 0
    assert record["prediction"]["dissenting_members_rate"] == []
    assert record["prediction"]["dissenting_members_stance"] == []
    assert "hidden_truth_only" not in calls[0]["user"]
    assert "hidden_reservation_only" not in calls[0]["user"]
    assert "Unavailable observations" in calls[0]["user"]
    assert "absolute date" not in calls[0]["user"]
    transcript = read_transcript(record["transcript_path"])
    assert transcript["generation"] == record["generation"]
    result_path = Path(plan.artifact_path).parent/"comparator_forecast.json"
    assert read_comparator_record(result_path, expected_plan_hash=plan.plan_hash) == record
    with pytest.raises(GenerationProvenanceError, match="already submitted"):
        await forecaster.generate(plan)
    assert len(calls) == 1
    if mode == "joint_persona":
        for p in personas:
            assert p.build_system_prompt() in calls[0]["user"]
        assert "Priority marker" in calls[0]["user"]
    else:
        for marker in ("Priority marker", "Theme marker", "Biography marker", "Lexical orientation statistic"):
            assert marker not in calls[0]["user"]
        assert "Governor ID: person0" in calls[0]["user"]


@pytest.mark.asyncio
async def test_common_mask_mapping_preserves_raw_nested_aliases(tmp_path, monkeypatch):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch, masked=True)
    frozen = freeze(forecaster, snapshot, roster, personas, mask_date=True, mask_identity=True)
    record = await forecaster.generate(frozen)
    text = calls[0]["user"] + calls[0]["system"]
    for m in roster.members:
        assert m.member_id not in text
        assert m.member_name not in text
    assert "2023-08-10" not in text
    assert "2020-10" not in text
    assert "Corpus" not in text
    assert record["generation"]["parsed"]["member_ballots"][0]["member_id"] == "member_1"
    assert record["prediction"]["member_ballots"][0]["member_id"] == "person0"
    assert read_transcript(record["transcript_path"])["member_ballots"][0]["member_id"] == "member_1"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["snapshot", "persona", "persona_order", "runtime", "logger", "source", "plan", "cache"])
async def test_frozen_mutation_rejects_before_generation(tmp_path, monkeypatch, mutation):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    if mutation == "source":
        source = tmp_path/"macro.txt"
        source.write_text("official source fixture")
        observations = tuple(ObservationEvidence(field=field, value=value, units="fixture",
            reference_period="2023-06", vintage="June fixture", released_at=datetime(2023, 7, 12, tzinfo=timezone.utc),
            source_url="https://example.invalid/offline-fixture", source_file="macro.txt",
            source_sha256=file_hash(source), source_pointer="fixture", availability_basis="fixture")
            for field, value in snapshot.observable_values().items())
        snapshot = snapshot.model_copy(update={"input_track":"source_linked", "observations":observations})
    frozen = freeze(forecaster, snapshot, roster, personas)
    if mutation == "snapshot":
        snapshot.cpi_headline_yoy_pct = 4.9
    elif mutation == "persona":
        personas[0].hawk_dove_score = .9
    elif mutation == "persona_order":
        personas.reverse()
    elif mutation == "runtime":
        old = forecaster.client.cfg.run.temperature
        monkeypatch.setattr(forecaster.client.cfg.run, "temperature", old+.01)
    elif mutation == "logger":
        forecaster.logger.identity["experiment_id"] = "changed"
    elif mutation == "source":
        source.write_text("changed source")
    elif mutation == "cache":
        forecaster.client.cache_enabled = True
    else:
        Path(frozen.artifact_path).write_text("{}")
    with pytest.raises((GenerationProvenanceError, ValueError)):
        await forecaster.generate(frozen)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [BudgetExceededError, UncertainChargeError, GenerationCancelledError])
async def test_terminal_runtime_failure_propagates_without_retry(tmp_path, monkeypatch, error_type):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    error = error_type("controlled offline terminal failure", context={"retained": "failure context"})
    attempts = []
    async def fail(**kwargs):
        attempts.append(kwargs)
        raise error
    monkeypatch.setattr(forecaster.client, "generate_with_metadata", fail)
    frozen = freeze(forecaster, snapshot, roster, personas)
    with pytest.raises(error_type) as caught:
        await forecaster.generate(frozen)
    assert caught.value is error
    with pytest.raises(GenerationProvenanceError):
        await forecaster.generate(frozen)
    assert len(attempts) == 1 and calls == []
    assert "failure context" in forecaster.logger.log_file.read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_case", ["wrong_roster", "wrong_order", "wrong_role", "wrong_committee",
    "wrong_rate_dissent", "wrong_stance_dissent", "fragmented", "wrong_stance", "bool_rate", "fallback"])
async def test_malformed_semantic_outputs_fail_closed_with_raw_evidence(tmp_path, monkeypatch, bad_case):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    raw = ballots(roster)
    if bad_case == "wrong_roster":
        raw["member_ballots"][0]["member_id"] = "intruder"
    elif bad_case == "wrong_order":
        raw["member_ballots"].reverse()
    elif bad_case == "wrong_role":
        raw["member_ballots"][0]["is_internal"] = False
    elif bad_case == "wrong_committee":
        raw["rate_decision_bps"] = 25
    elif bad_case == "wrong_rate_dissent":
        raw["member_ballots"][0]["rate_choice_disagreement"] = True
    elif bad_case == "wrong_stance_dissent":
        raw["member_ballots"][0]["formal_stance_dissent"] = True
    elif bad_case == "fragmented":
        raw = ballots(roster, rates=[-25,-25,0,0,25,25])
    elif bad_case == "wrong_stance":
        raw["stance_decision"] = "calibrated_tightening"
    elif bad_case == "bool_rate":
        raw["member_ballots"][0]["rate_vote_bps"] = False
    else:
        raw["fallback_triggered"] = True
    submissions = []
    def fixture(*args):
        submissions.append(args)
        return canonical_json(raw), 200, 300
    monkeypatch.setattr(forecaster.client, "_generate_mock", fixture)
    frozen = freeze(forecaster, snapshot, roster, personas)
    with pytest.raises((GenerationProvenanceError, LLMResponseMalformedError, ValueError)):
        await forecaster.generate(frozen)
    assert len(submissions) == 1
    assert not (Path(frozen.artifact_path).parent/"comparator_forecast.json").exists()
    log = forecaster.logger.log_file.read_text()
    assert "comparator_failed" in log and "raw_text" in log


@pytest.mark.asyncio
async def test_casting_and_explicit_synthetic_policy_are_distinct(tmp_path, monkeypatch):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    raw = ballots(roster, rates=[25,25,25,0,0,0], committee_rate=25)
    monkeypatch.setattr(forecaster.client, "_generate_mock", lambda *args: (canonical_json(raw),200,300))
    frozen = freeze(forecaster, snapshot, roster, personas)
    record = await forecaster.generate(frozen)
    assert record["prediction"]["rate_resolution"]["tie_broken_by_governor"] is True
    assert record["prediction"]["rate_resolution"]["synthetic_resolution"] is False
    assert record["prediction"]["dissenting_members_rate"] == ["person3", "person4", "person5"]
    forecaster2, snapshot2, roster2, personas2, calls2 = setup(tmp_path/"second", monkeypatch)
    raw2 = ballots(roster2, rates=[-25,-25,0,0,25,25])
    monkeypatch.setattr(forecaster2.client, "_generate_mock", lambda *args: (canonical_json(raw2),200,300))
    frozen2 = freeze(forecaster2, snapshot2, roster2, personas2, fragmentation_policy="status_quo")
    record2 = await forecaster2.generate(frozen2)
    assert record2["prediction"]["rate_resolution"]["synthetic_resolution"] is True
    assert record2["prediction"]["rate_resolution"]["tie_broken_by_governor"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["prediction", "usage", "frozen_plan", "generation", "record_version", "transcript_sha256"])
async def test_rehashed_corruption_still_rejects_under_external_plan_anchor(tmp_path, monkeypatch, field):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    frozen = freeze(forecaster, snapshot, roster, personas)
    record = await forecaster.generate(frozen)
    if field == "prediction":
        record["prediction"]["rate_decision_bps"] = 25
    elif field == "usage":
        record["usage"]["actual_live_provider_submissions"] = 1
    elif field == "frozen_plan":
        record["frozen_plan"]["control_mode"] = "macro_only"
    elif field == "generation":
        record["generation"]["metadata"]["served_model"] = "unverified mock model"
    elif field == "record_version":
        record["record_version"] = "unregistered_v2"
    else:
        record["transcript_sha256"] = "0"*64
    record.pop("artifact_content_hash")
    record["artifact_content_hash"] = content_hash(record)
    path = tmp_path/"corrupted_record.json"
    path.write_text(canonical_json(record))
    with pytest.raises((ArtifactIntegrityError, GenerationProvenanceError)):
        read_comparator_record(path, expected_plan_hash=frozen.plan_hash)


def test_preflight_roster_and_information_controls(tmp_path, monkeypatch):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    with pytest.raises(GenerationProvenanceError, match="outside declared"):
        freeze(forecaster, snapshot, roster.model_copy(update={"valid_through":"2023-08-01"}), personas)
    with pytest.raises(ValidationError):
        freeze(forecaster, snapshot, roster.model_copy(update={"stance_vocabulary_version":"expanded_v2"}), personas)
    with pytest.raises(GenerationProvenanceError, match="ordered dated roster"):
        freeze(forecaster, snapshot, roster, personas[::-1])
    with pytest.raises(GenerationProvenanceError, match="must not receive personas"):
        forecaster.freeze(snapshot, roster, mode="macro_only", personas=personas,
            experiment_id="offline_comparator_controls", condition_id="macro_only", replicate_id=1,
            model="mock", temperature=.2, seed=17, max_output_tokens=4096)
    dated = personas[0].model_copy(update={"provenance_status":"dated_corpus", "calibration_cutoff":"2023-08-11"})
    with pytest.raises(GenerationProvenanceError, match="Undated, assumed or future"):
        freeze(forecaster, snapshot, roster, [dated,*personas[1:]])
    monkeypatch.setattr(forecaster.client, "provider", "gemini")
    with pytest.raises(GenerationProvenanceError, match="source-linked"):
        freeze(forecaster, snapshot, roster, personas)
    assert calls == []


def test_schema_strict_boolean_integer_and_ontology():
    _, roster, _ = inputs()
    raw = ballots(roster)
    assert JointForecastOutput.model_validate(raw).stance_decision == "withdrawal_of_accommodation"
    for field, value in (("round_number", True),("fallback_triggered",0),("rate_decision_bps",0.0),
                         ("stance_decision","calibrated_tightening"),("committee_rationale"," ")):
        with pytest.raises(ValidationError):
            JointForecastOutput.model_validate({**raw, field:value})


def dated_sources(tmp_path, snapshot, personas):
    source = tmp_path/"official_source_fixture.txt"
    statement = tmp_path/"attributed_statement_fixture.txt"
    source.write_text("OFFLINE primary-document fixture; not authentic scientific data")
    statement.write_text("OFFLINE attributed statement fixture; not authentic persona evidence")
    cutoff = "2023-07-01"
    members = {}
    fitted = []
    for persona in personas:
        members[persona.member_id] = {"name":persona.name, "role":persona.role, "is_internal":persona.is_internal,
            "calibrated_hawk_dove":persona.hawk_dove_score, "stance_bias":persona.stance_bias,
            "voting_priority":persona.voting_priority, "biography":persona.biography,
            "exemplar_quotes":persona.key_themes, "meetings_count":1,
            "corpus_sources":[{"decision_date":"2023-06-08", "publication_date":"2023-06-20",
                "source_file":source.name, "source_sha256":file_hash(source),
                "statement_file":statement.name, "statement_sha256":file_hash(statement)}]}
    manifest = tmp_path/"corpus_manifest.json"
    manifest.write_text(canonical_json({"calibration_cutoff":cutoff, "members":members}))
    for persona in personas:
        fitted.append(persona.model_copy(update={"provenance_status":"dated_corpus",
            "calibration_cutoff":cutoff, "corpus_manifest_hash":file_hash(manifest)}))
    observations = tuple(ObservationEvidence(field=field, value=value, units="offline fixture",
        reference_period="2023-06", vintage="offline pre-cutoff fixture", released_at=datetime(2023,7,12,tzinfo=timezone.utc),
        source_url="https://example.invalid/offline-fixture", source_file=source.name,
        source_sha256=file_hash(source), source_pointer="fixture", availability_basis="offline fixture")
        for field,value in snapshot.observable_values().items())
    snapshot = snapshot.model_copy(update={"input_track":"source_linked", "observations":observations})
    return snapshot, fitted, manifest, source, statement


@pytest.mark.asyncio
async def test_dated_source_contract_verifies_hashes_and_cutoffs(tmp_path, monkeypatch):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    snapshot, fitted, manifest, source, statement = dated_sources(tmp_path, snapshot, personas)
    forecaster.corpus_manifest_path = manifest
    frozen = freeze(forecaster, snapshot, roster, fitted, mask_date=True, mask_identity=True)
    assert set(frozen.plan["source_hashes"]) == {source.name, statement.name, manifest.name}
    user = frozen.plan["user_prompt"]
    assert "release available" in user
    assert "2023-06" not in user and "2023-07" not in user
    assert source.name not in user and manifest.name not in user
    for p in fitted:
        assert p.member_id not in user and p.name not in user
    statement.write_text("changed retained attributed statement")
    with pytest.raises(GenerationProvenanceError, match="changed persona statement"):
        await forecaster.generate(frozen)
    assert calls == []


@pytest.mark.parametrize("mutation", ["future_corpus", "changed_score", "changed_manifest", "future_observation"])
def test_dated_inputs_reject_unavailable_or_changed_evidence(tmp_path, monkeypatch, mutation):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    snapshot, fitted, manifest, source, statement = dated_sources(tmp_path, snapshot, personas)
    forecaster.corpus_manifest_path = manifest
    if mutation == "future_corpus":
        document = json.loads(manifest.read_text())
        document["members"][fitted[0].member_id]["corpus_sources"][0]["publication_date"] = "2023-07-01"
        manifest.write_text(canonical_json(document))
        fitted = [p.model_copy(update={"corpus_manifest_hash":file_hash(manifest)}) for p in fitted]
    elif mutation == "changed_score":
        fitted[0].hawk_dove_score = .7
    elif mutation == "changed_manifest":
        manifest.write_text("{}")
    else:
        later = snapshot.observations[0].model_copy(update={"released_at":snapshot.information_cutoff})
        snapshot = snapshot.model_copy(update={"observations":(later,*snapshot.observations[1:])})
    with pytest.raises((GenerationProvenanceError, ValueError)):
        freeze(forecaster, snapshot, roster, fitted)
    assert calls == []


@pytest.mark.asyncio
async def test_changes_during_awaited_generation_prevent_publication(tmp_path, monkeypatch):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    original = forecaster.client.generate_with_metadata
    async def change(**kwargs):
        result = await original(**kwargs)
        snapshot.cpi_headline_yoy_pct = 4.9
        return result
    monkeypatch.setattr(forecaster.client, "generate_with_metadata", change)
    frozen = freeze(forecaster, snapshot, roster, personas)
    with pytest.raises(GenerationProvenanceError, match="changed after freeze"):
        await forecaster.generate(frozen)
    assert len(calls) == 1
    assert not (Path(frozen.artifact_path).parent/"comparator_forecast.json").exists()
    assert "raw_text" in forecaster.logger.log_file.read_text()


def test_alias_collision_is_explicitly_rejected(tmp_path, monkeypatch):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    members = list(roster.members)
    members[1] = members[1].model_copy(update={"member_id":"member_1"})
    roster = roster.model_copy(update={"members":tuple(members)})
    personas[1].member_id = "member_1"
    with pytest.raises(GenerationProvenanceError, match="collides"):
        freeze(forecaster, snapshot, roster, personas, mask_identity=True)
    assert calls == []


@pytest.mark.asyncio
async def test_complete_transcript_path_and_explicit_portable_mapping(tmp_path, monkeypatch):
    forecaster, snapshot, roster, personas, calls = setup(tmp_path, monkeypatch)
    frozen = freeze(forecaster, snapshot, roster, personas)
    record = await forecaster.generate(frozen)
    original = Path(record["transcript_path"])
    archived = tmp_path/"copied_transcript.json"
    archived.write_bytes(original.read_bytes())
    record["transcript_path"] = str(tmp_path/"unavailable_original_transcript.json")
    record.pop("artifact_content_hash")
    record["artifact_content_hash"] = content_hash(record)
    copied_record = tmp_path/"copied_record.json"
    copied_record.write_text(canonical_json(record))
    with pytest.raises(ArtifactIntegrityError, match="transcript missing"):
        read_comparator_record(copied_record, expected_plan_hash=frozen.plan_hash)
    assert read_comparator_record(copied_record, expected_plan_hash=frozen.plan_hash,
                                  transcript_path=archived) == record
