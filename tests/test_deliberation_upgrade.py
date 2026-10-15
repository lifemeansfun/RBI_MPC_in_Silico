"""Offline discriminating probes: information paths, strict ballots and voting assumptions."""

import json
from types import SimpleNamespace
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import hashlib

import pytest
from pydantic import ValidationError

from src.behavioral.debate_orchestrator import DebateOrchestrator, InformationVisibility
from src.schemas.debate_schema import InitialStanceOutput, DeliberationOutput, FinalVoteOutput, MeetingCommitteeDecision
from src.schemas.decision_space import RATE_ACTIONS_BPS
from src.schemas.macro_schema import MacroMeetingSnapshot, ObservationEvidence, OBSERVABLE_FIELDS
from src.schemas.persona_schema import MemberPersona
from src.rule_engine.engine import InstitutionalRuleEngine
from src.scenarios.scenario_runner import ScenarioRunner
from src.attribution.attribution_runner import AttributionRunner
from src.infra.transcript_logger import TranscriptLogger
from src.infra.exceptions import BudgetExceededError, GenerationProvenanceError
from src.infra.llm_client import LLMClient
from src.infra.evidence import content_hash
from src.rational.taylor_rule import MemberTaylorParameters


@pytest.fixture
def roster():
    return [MemberPersona(member_id=f"original_id_{i}", name=f"Original Person {i}",
                          role="Governor" if i == 0 else "External Member", is_internal=i == 0,
                          tenure="2020-2024", hawk_dove_score=0.0, voting_priority="Supplied evidence")
            for i in range(6)]


@pytest.fixture
def snapshot():
    return MacroMeetingSnapshot(meeting_date="2023-08-10", current_repo_rate_pct=6.5,
        cpi_headline_yoy_pct=5.4, cpi_core_yoy_pct=4.1, cpi_food_yoy_pct=5.7, cfpi_yoy_pct=6.1,
        iip_growth_yoy_pct=5.2, gva_growth_yoy_pct=6.3, output_gap_pct=0.1,
        system_liquidity_cr=-15000.0, usd_inr_exchange_rate=82.7, brent_crude_usd_bbl=84.0,
        us_fed_funds_rate_pct=5.5, monsoon_departure_lpa_pct=-3.5, prev_stance="accommodative",
        real_rate_decision_bps=35, real_stance_decision="neutral", real_dissenters=["truth"],
        real_dissenters_rate=["rate_truth"], real_dissenters_stance=["stance_truth"],
        real_reservations=["reservation_truth"], real_guidance_disagreements=["guidance_truth"],
        input_track="synthetic")


@pytest.fixture
def source_linked_fixture_snapshot(tmp_path, snapshot, monkeypatch):
    """Synthetic source bytes exercise integrity controls; these are not empirical inputs."""
    source = tmp_path / "synthetic_macro_source.txt"
    source.write_text("Test-only synthetic numbers: current repo 6.5; headline CPI 5.4; stance accommodative")
    source_file = source.name
    verify_sources = MacroMeetingSnapshot.verify_sources
    # Exercise the actual bytes/hash verifier against a scoped test source root.
    # No outside-project empirical file or alternative source is being authorized.
    monkeypatch.setattr(MacroMeetingSnapshot, "verify_sources",
                        lambda self: verify_sources(self, root=tmp_path))
    supplied = {"current_repo_rate_pct": 6.5, "cpi_headline_yoy_pct": 5.4, "prev_stance": "accommodative"}
    observations = tuple(ObservationEvidence(field=key, value=value, units="test_units", reference_period="synthetic_fixture",
        vintage="synthetic_fixture", released_at=datetime(2023, 7, 1, tzinfo=timezone.utc), source_url="https://example.invalid/test-fixture",
        source_file=source_file, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), source_pointer="Test-only fixture",
        availability_basis="synthetic source for offline integrity tests") for key, value in supplied.items())
    payload = snapshot.model_dump()
    payload.update({key: None for key in OBSERVABLE_FIELDS if key not in supplied})
    payload.update(supplied)
    payload.update(input_track="source_linked", meeting_start_date="2023-08-08",
                   information_cutoff=datetime(2023, 8, 7, tzinfo=timezone.utc), observations=observations)
    return MacroMeetingSnapshot.model_validate(payload)


class ScriptedClient:
    def __init__(self, rate=35, fail_call=None, corrupt=None):
        self.calls = []
        self.rate = rate
        self.fail_call = fail_call
        self.corrupt = corrupt

    async def generate_with_metadata(self, **kwargs):
        self.calls.append(kwargs)
        identity = kwargs["request_identity"]
        if len(self.calls) == self.fail_call:
            raise BudgetExceededError("Terminal refusal", context={"request_identity": identity})
        expected = kwargs["expected_identity"]
        member = expected["member_id"]
        round_number = identity["round_number"]
        marker = f"SENTINEL_{identity['member_id']}_R{round_number}"
        if round_number == 1:
            data = {**expected, "proposed_rate_change_bps": self.rate, "proposed_stance": "neutral", "key_rationale": marker}
        elif round_number in (2, 3):
            data = {**expected, "current_rate_preference_bps": self.rate, "current_stance_preference": "neutral", "rebuttal_or_critique": marker}
        else:
            data = {**expected, "final_rate_vote_bps": self.rate, "final_stance_vote": "neutral", "official_statement_rationale": marker}
        if self.corrupt and round_number == self.corrupt[0]:
            data[self.corrupt[1]] = self.corrupt[2]
        output = kwargs["response_schema"].model_validate(data)
        raw = json.dumps(data)
        result = SimpleNamespace(raw_text=raw, parsed=output, validation_error=None, metadata={"evidence_type": "mock"})
        result.to_dict = lambda: {"raw_text": raw, "parsed": data, "validation_error": None,
                                 "request_identity": identity, "metadata": result.metadata}
        return result


def orchestrator(tmp_path, client):
    return DebateOrchestrator(client, TranscriptLogger(run_id="test", output_root=tmp_path))


async def test_actual_runtime_mock_complete_path(tmp_path, snapshot, roster):
    client = LLMClient(provider="mock", cache_enabled=False, ledger_path=tmp_path / "budget.sqlite3")
    decision = await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id,
                                                               experiment_id="runtime_mock")
    assert len(decision.member_votes) == 6 and decision.evidence_types == ["mock"]
    assert decision.fallbacks_count == 0 and decision.generation_count == 24


async def test_actual_runtime_masked_mock_and_full_identity(tmp_path, snapshot, roster):
    identity = {"experiment_id": "masked_runtime", "code_hash": "a" * 64,
                "persona_hash": content_hash([p.model_dump(mode="json") for p in roster]),
                "data_hash": "c" * 64, "config_hash": "d" * 64}
    logger = TranscriptLogger(run_id="masked", output_root=tmp_path, identity=identity)
    client = LLMClient(provider="mock", cache_enabled=False, ledger_path=tmp_path / "budget.sqlite3")
    decision = await DebateOrchestrator(client, logger).run_meeting(snapshot, roster, roster[0].member_id,
        experiment_id="masked_runtime", mask_identity=True, mask_date=True)
    assert len(decision.member_votes) == 6
    artifact = json.loads(next(tmp_path.rglob("round_*.json")).read_text())
    assert artifact["generation"]["request_identity"]["code_hash"] == identity["code_hash"]
    assert artifact["generation"]["request_identity"]["output_member_id"].startswith("member_")
    assert artifact["member_id"].startswith("original_id_")


async def test_cancellation_propagates_without_subsequent_calls(tmp_path, snapshot, roster):
    class CancellingClient(ScriptedClient):
        async def generate_with_metadata(self, **kwargs):
            self.calls.append(kwargs)
            raise asyncio.CancelledError()
    client = CancellingClient()
    with pytest.raises(asyncio.CancelledError):
        await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id)
    assert len(client.calls) == 1
    assert not list(tmp_path.rglob("meeting_outcome.json"))


async def test_live_source_refusal_occurs_before_any_generation(tmp_path, snapshot, roster):
    client = ScriptedClient()
    client.provider = "gemini"
    with pytest.raises(GenerationProvenanceError, match="source-linked"):
        await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id)
    assert client.calls == []
    shocked = ScenarioRunner.build_monsoon_food_shock_snapshot(snapshot)
    with pytest.raises(GenerationProvenanceError, match="parent must be source-linked"):
        await orchestrator(tmp_path, client).run_meeting(shocked, roster, roster[0].member_id)
    assert client.calls == []


@pytest.mark.parametrize("future", [False, True])
async def test_direct_live_and_counterfactual_refuse_undated_or_future_personas_before_calls(tmp_path, source_linked_fixture_snapshot, roster, future):
    client = ScriptedClient()
    client.provider = "gemini"
    if future:
        roster = [p.model_copy(update={"provenance_status": "dated_corpus", "calibration_cutoff": "2023-12-31", "corpus_manifest_hash": "f" * 64}) for p in roster]
    runner = orchestrator(tmp_path, client)
    for supplied in (source_linked_fixture_snapshot, ScenarioRunner.build_monsoon_food_shock_snapshot(source_linked_fixture_snapshot)):
        with pytest.raises(GenerationProvenanceError, match="Undated|future"):
            await runner.run_meeting(supplied, roster, roster[0].member_id)
        assert client.calls == []


async def test_historical_truth_changes_cannot_enter_any_prompt(tmp_path, snapshot, roster):
    altered = snapshot.model_copy(update={"real_rate_decision_bps": -50, "real_stance_decision": "accommodative",
        "real_dissenters": ["TARGET_TRUTH_SECRET"], "real_dissenters_rate": ["TARGET_RATE_SECRET"],
        "real_dissenters_stance": ["TARGET_STANCE_SECRET"], "real_reservations": ["TARGET_RESERVATION_SECRET"],
        "real_guidance_disagreements": ["TARGET_GUIDANCE_SECRET"]})
    client = ScriptedClient()
    runner = orchestrator(tmp_path, client)
    await runner.run_meeting(snapshot, roster, roster[0].member_id, condition_id="truth_original")
    await runner.run_meeting(altered, roster, roster[0].member_id, condition_id="truth_mutated")
    for original, mutated in zip(client.calls[:24], client.calls[24:]):
        assert original["user_prompt"] == mutated["user_prompt"]
        assert original["system_prompt"] == mutated["system_prompt"]
        assert original["seed"] == mutated["seed"]
        assert "TARGET_" not in mutated["user_prompt"]


@pytest.mark.parametrize("corruption", ["changed_fields", "parent_hash", "unrelated_field", "parent_snapshot"])
@pytest.mark.parametrize("provider", ["mock", "gemini"])
async def test_counterfactual_parent_reconciliation_runs_for_mock_and_live_before_calls(tmp_path, source_linked_fixture_snapshot, roster, corruption, provider):
    shocked = ScenarioRunner.build_monsoon_food_shock_snapshot(source_linked_fixture_snapshot)
    payload = shocked.model_dump(mode="json")
    if corruption == "changed_fields":
        payload["intervention"]["changed_fields"]["cpi_headline_yoy_pct"] = 123.0
    elif corruption == "parent_hash":
        payload["intervention"]["parent_snapshot_hash"] = "f" * 64
    elif corruption == "unrelated_field":
        payload["gva_growth_yoy_pct"] = 7.2
    else:
        payload["intervention"]["parent_snapshot"]["current_repo_rate_pct"] = 5.5
    corrupt = MacroMeetingSnapshot.model_validate(payload)
    client = ScriptedClient()
    client.provider = provider
    with pytest.raises(GenerationProvenanceError):
        await orchestrator(tmp_path, client).run_meeting(corrupt, roster, roster[0].member_id)
    assert client.calls == []


async def test_argument_identity_ballot_and_own_state_controls_are_separate(tmp_path, snapshot, roster):
    client = ScriptedClient()
    runner = orchestrator(tmp_path, client)
    await runner.run_meeting(snapshot, roster, roster[0].member_id,
                            visibility=InformationVisibility(peer_arguments=False, governor_ballots=True, own_state=False))
    finals = [c for c in client.calls if c["request_identity"]["round_number"] == 4]
    for call in finals:
        assert "YOUR OWN ROUND" not in call["user_prompt"]
        assert "VISIBLE PEER ROUND" not in call["user_prompt"]
    governor = next(c for c in finals if c["request_identity"]["member_id"] == roster[0].member_id)
    assert "VISIBLE NON-GOVERNOR BINDING BALLOTS" in governor["user_prompt"]
    assert "SENTINEL_original_id_1_R4" not in governor["user_prompt"]
    outputs = {1: {p.member_id: InitialStanceOutput(member_id=p.member_id, member_name=p.name,
        proposed_rate_change_bps=0, proposed_stance="neutral", key_rationale=f"{p.name} as {p.role} cites evidence") for p in roster}}
    context = DebateOrchestrator._round_context(outputs, [1], roster[0], roster,
                                               InformationVisibility(peer_identity=False, own_state=False))
    for person in roster:
        assert person.name not in context and person.member_id not in context and person.role not in context


async def test_attribution_pair_retains_member_effects_and_trace_conditions(tmp_path, snapshot, roster):
    client = ScriptedClient()
    runner = orchestrator(tmp_path, client)
    baseline = await runner.run_meeting(snapshot, roster, roster[0].member_id, replicate_id=2,
                                        condition_id="paired_baseline", seed=77)
    result = await AttributionRunner.run_leave_one_out_ablation(runner, baseline, snapshot, roster,
                                                               roster[0].member_id, roster[2].member_id)
    assert result.replicate_id == 2 and result.estimand_scope == "simulator_local"
    assert not result.outcome_shifted  # null effects must stay null
    assert set(result.member_rate_changes_bps) == {p.member_id for p in roster}
    assert set(result.member_rate_changes_bps.values()) == {0}
    assert result.donor_behavior == "own_state_retained_endogenous_ballot"
    assert len(list(tmp_path.rglob("meeting_outcome.json"))) == 2


async def test_attribution_freezes_generation_settings_and_input_identity(tmp_path, snapshot, roster):
    client = ScriptedClient()
    runner = orchestrator(tmp_path, client)
    baseline = await runner.run_meeting(snapshot, roster, roster[0].member_id,
        experiment_id="frozen_pair", condition_id="baseline", model="frozen_model", temperature=0.12)
    assert len(baseline.snapshot_hash) == 64 and len(baseline.persona_hash) == 64
    result = await AttributionRunner.run_leave_one_out_ablation(runner, baseline, snapshot, roster,
                                                               roster[0].member_id, roster[2].member_id)
    assert result.estimand_scope == "simulator_local"
    assert all(call["model"] == "frozen_model" and call["temperature"] == 0.12 for call in client.calls)


@pytest.mark.parametrize("mismatch", ["seed", "model", "temperature", "snapshot", "personas", "governor"])
async def test_attribution_pairing_refuses_drift_before_calls(tmp_path, snapshot, roster, mismatch):
    client = ScriptedClient()
    runner = orchestrator(tmp_path, client)
    baseline = await runner.run_meeting(snapshot, roster, roster[0].member_id,
        experiment_id="paired_preflight", condition_id="baseline", model="frozen", temperature=0.15, seed=64)
    kwargs = {"orchestrator": runner, "baseline_decision": baseline, "snapshot": snapshot,
              "personas": roster, "governor_id": roster[0].member_id, "ablated_member_id": roster[2].member_id}
    if mismatch in ("seed", "model", "temperature"):
        kwargs[mismatch] = {"seed": 65, "model": "different", "temperature": 0.25}[mismatch]
    elif mismatch == "snapshot":
        kwargs["snapshot"] = snapshot.model_copy(update={"cpi_headline_yoy_pct": 6.1})
    elif mismatch == "personas":
        kwargs["personas"] = [p.model_copy(update={"hawk_dove_score": 0.2}) for p in roster]
    else:
        kwargs["governor_id"] = roster[1].member_id
    before = len(client.calls)
    with pytest.raises(ValueError, match="pair|baseline|Baseline|frozen"):
        await AttributionRunner.run_leave_one_out_ablation(**kwargs)
    assert len(client.calls) == before


@pytest.mark.parametrize("setting,changed", [("model_epoch", "different_epoch"), ("max_output_tokens", 1024), ("provider", "gemini")])
async def test_attribution_refuses_runtime_setting_drift_before_calls(tmp_path, snapshot, roster, setting, changed):
    client = ScriptedClient()
    client.provider = "mock"
    client.cfg = SimpleNamespace(run=SimpleNamespace(dev_model="frozen", temperature=0.2, model_epoch="epoch1", max_output_tokens=2048))
    runner = orchestrator(tmp_path, client)
    baseline = await runner.run_meeting(snapshot, roster, roster[0].member_id)
    for call in client.calls:
        assert call["max_output_tokens"] == 2048 and call["model_epoch"] == "epoch1"
    if setting == "provider":
        client.provider = changed
    else:
        setattr(client.cfg.run, setting, changed)
    before = len(client.calls)
    with pytest.raises(ValueError, match="settings differ"):
        await AttributionRunner.run_leave_one_out_ablation(runner, baseline, snapshot, roster, roster[0].member_id, roster[2].member_id)
    assert len(client.calls) == before


async def test_legacy_baseline_without_frozen_pair_identity_is_refused(tmp_path, snapshot, roster):
    client = ScriptedClient()
    runner = orchestrator(tmp_path, client)
    baseline = await runner.run_meeting(snapshot, roster, roster[0].member_id)
    legacy = baseline.model_copy(update={"snapshot_hash": None, "generation_settings": {}})
    before = len(client.calls)
    with pytest.raises(ValueError, match="lacks frozen"):
        await AttributionRunner.run_macro_muting_ablation(runner, legacy, snapshot, roster, roster[0].member_id, "monsoon")
    assert len(client.calls) == before


async def test_frozen_logger_persona_hash_mismatch_refuses_generation(tmp_path, snapshot, roster):
    client = ScriptedClient()
    logger = TranscriptLogger(run_id="bad_identity", output_root=tmp_path, identity={"persona_hash": "f" * 64})
    with pytest.raises(GenerationProvenanceError, match="persona_hash differs"):
        await DebateOrchestrator(client, logger).run_meeting(snapshot, roster, roster[0].member_id)
    assert not client.calls


@pytest.mark.parametrize("rate", [35, 40])
async def test_seven_action_domain_reaches_committee_and_metadata(tmp_path, snapshot, roster, rate):
    client = ScriptedClient(rate)
    decision = await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id,
                                                              experiment_id="action_probe", seed=52)
    assert decision.rate_decision_bps == rate
    assert decision.generation_count == 24
    assert decision.evidence_types == ["mock"]
    assert len(set(decision.seed_schedule.values())) == 24
    artifacts = list(tmp_path.rglob("round_*.json"))
    assert len(artifacts) == 24
    transcript = json.loads(artifacts[0].read_text())
    assert transcript["generation"]["raw_text"]
    assert transcript["prompt"]["system_prompt"]
    assert transcript["artifact_identity"]["experiment_id"] == "action_probe"
    assert "35, 40" in client.calls[0]["user_prompt"]
    assert not any("1-Year Ahead CPI Expectation" in call["user_prompt"] or "Liquidity Stress Index" in call["user_prompt"] for call in client.calls)


async def test_round_three_sentinels_reach_every_binding_ballot(tmp_path, snapshot, roster):
    client = ScriptedClient()
    await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id)
    final = [call for call in client.calls if call["request_identity"]["round_number"] == 4]
    assert len(final) == 6
    for call in final:
        for person in roster:
            assert f"SENTINEL_{person.member_id}_R3" in call["user_prompt"]
        assert "YOUR OWN ROUND 3 STATE" in call["user_prompt"]


@pytest.mark.parametrize("donor_idx", [0, 2])
async def test_outgoing_ablation_blocks_every_donor_round_and_governor_ballot(tmp_path, snapshot, roster, donor_idx):
    donor = roster[donor_idx].member_id
    client = ScriptedClient()
    decision = await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id, ablated_member_id=donor)
    for call in client.calls:
        recipient = call["request_identity"]["member_id"]
        round_number = call["request_identity"]["round_number"]
        if recipient != donor:
            for prior_round in range(1, 5):
                assert f"SENTINEL_{donor}_R{prior_round}" not in call["user_prompt"]
        elif round_number > 1:
            assert f"SENTINEL_{donor}_R1" in call["user_prompt"]
    assert decision.visibility["ablated_member_id"] == donor
    assert len(decision.member_votes) == 6  # information removal retains the donor's own ballot


@pytest.mark.parametrize("mode,count,r3_visible,ballots_visible", [
    ("full", 24, True, True), ("earlier_rounds", 24, False, True), ("independent", 12, False, False)])
async def test_explicit_controls_and_costs(tmp_path, snapshot, roster, mode, count, r3_visible, ballots_visible):
    client = ScriptedClient()
    decision = await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id, control_mode=mode)
    finals = [c for c in client.calls if c["request_identity"]["round_number"] == 4]
    assert len(client.calls) == decision.generation_count == count
    assert all(("YOUR OWN ROUND 3 STATE" in c["user_prompt"]) is r3_visible for c in finals)
    governor = next(c for c in finals if c["request_identity"]["member_id"] == roster[0].member_id)
    assert ("VISIBLE NON-GOVERNOR BINDING BALLOTS" in governor["user_prompt"]) is ballots_visible
    if mode == "independent":
        for call in finals:
            own = call["request_identity"]["member_id"]
            for peer in roster:
                if peer.member_id != own:
                    assert f"SENTINEL_{peer.member_id}" not in call["user_prompt"]


async def test_named_date_mask_keeps_opaque_output_binding_and_original_joins(tmp_path, snapshot, roster):
    client = ScriptedClient()
    decision = await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id,
                                                               mask_identity=True, mask_date=True)
    assert {v.member_id for v in decision.member_votes} == {p.member_id for p in roster}
    for call in client.calls:
        prompts = call["system_prompt"] + call["user_prompt"]
        assert "2023-08-10" not in prompts
        assert "2020" not in prompts and "2024" not in prompts
        for person in roster:
            assert person.member_id not in prompts and person.name not in prompts
        assert call["expected_identity"]["member_id"].startswith("member_")


async def test_masked_names_in_persona_text_ignore_case_without_replacement_cascades(tmp_path, snapshot, roster):
    roster = [p.model_copy(update={"key_themes": ["ORIGINAL PERSON 2 said ORIGINAL_ID_2 favors inflation"]}) for p in roster]
    client = ScriptedClient()
    await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id, mask_identity=True)
    for call in client.calls:
        prompt = (call["system_prompt"] + call["user_prompt"]).casefold()
        for p in roster:
            assert p.name.casefold() not in prompt and p.member_id.casefold() not in prompt
    peer = {"member_id": roster[1].member_id, "key_rationale": "ORIGINAL PERSON 2 is an EXTERNAL MEMBER"}
    hidden = DebateOrchestrator._anonymize_peer_entry(peer, roster)
    assert "original person" not in hidden["key_rationale"].casefold()
    assert "external member" not in hidden["key_rationale"].casefold()


@pytest.mark.parametrize("setting", ["peer_arguments", "peer_identity", "governor_ballots", "own_state"])
def test_information_visibility_refuses_string_booleans(setting):
    with pytest.raises(ValueError, match="boolean"):
        InformationVisibility(**{setting: "false"})


@pytest.mark.parametrize("settings", [{"fragmentation_policy": "invented"}, {"mask_identity": "false"}, {"mask_date": 1}])
async def test_malformed_condition_controls_fail_before_generation(tmp_path, snapshot, roster, settings):
    client = ScriptedClient()
    with pytest.raises(ValueError):
        await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id, **settings)
    assert not client.calls


@pytest.mark.parametrize("round_number,call_number", [(1, 1), (2, 7), (3, 13), (4, 19)])
async def test_terminal_refusal_stops_every_round_without_later_calls(tmp_path, snapshot, roster, round_number, call_number):
    client = ScriptedClient(fail_call=call_number)
    with pytest.raises(BudgetExceededError, match="Terminal refusal"):
        await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id)
    assert len(client.calls) == call_number
    assert client.calls[-1]["request_identity"]["round_number"] == round_number
    assert not list(tmp_path.rglob("meeting_outcome.json"))
    assert "generation_failed" in next(tmp_path.rglob("run.jsonl")).read_text()


async def test_terminal_budget_error_is_not_replaced_by_failure_logger_error(tmp_path, snapshot, roster):
    class FailedEventLogger(TranscriptLogger):
        def log_event(self, event, payload):
            if event == "generation_failed":
                raise OSError("failure sink unavailable")
            return super().log_event(event, payload)
    client = ScriptedClient(fail_call=1)
    runner = DebateOrchestrator(client, FailedEventLogger(run_id="failed_logger", output_root=tmp_path))
    with pytest.raises(BudgetExceededError) as captured:
        await runner.run_meeting(snapshot, roster, roster[0].member_id)
    assert len(client.calls) == 1
    assert isinstance(captured.value.__cause__, OSError)
    assert any("failure sink unavailable" in note for note in captured.value.__notes__)


@pytest.mark.parametrize("corrupt", [(1, "member_id", "impostor"), (2, "round_number", 3),
                                    (3, "round_number", 2), (4, "member_name", "Impostor"),
                                    (4, "is_internal", True), (1, "fallback_triggered", True)])
async def test_wrong_member_round_role_and_heuristic_outputs_fail_closed(tmp_path, snapshot, roster, corrupt):
    client = ScriptedClient(corrupt=corrupt)
    with pytest.raises(ValueError):
        await orchestrator(tmp_path, client).run_meeting(snapshot, roster, roster[0].member_id)
    assert len(client.calls) == {1: 1, 2: 7, 3: 13, 4: 19}[corrupt[0]]


@pytest.mark.parametrize("bad", [True, "35", "+35 bps", 35.0, 30, float("nan"), float("inf"), None])
def test_invalid_rates_are_rejected_without_snapping(bad):
    with pytest.raises(ValidationError):
        InitialStanceOutput(member_id="m", member_name="M", proposed_rate_change_bps=bad,
                            proposed_stance="neutral", key_rationale="evidence")


@pytest.mark.parametrize("bad", ["Neutral", "neutralish", "withdrawal of accommodation", "", None])
def test_unknown_stance_is_rejected(bad):
    with pytest.raises(ValidationError):
        FinalVoteOutput(member_id="m", member_name="M", final_rate_vote_bps=40,
                        final_stance_vote=bad, official_statement_rationale="evidence")


@pytest.mark.parametrize("field", ["member_id", "member_name", "key_rationale"])
def test_whitespace_only_identity_or_rationale_is_rejected(field):
    data = dict(member_id="m", member_name="M", proposed_rate_change_bps=35, proposed_stance="neutral", key_rationale="evidence")
    data[field] = " \t\n "
    with pytest.raises(ValidationError):
        InitialStanceOutput.model_validate(data)


@pytest.mark.parametrize("corruption", ["wrong_winner", "false_dissent_flag", "duplicate_dissent", "short_roster", "boolean_as_text", "duplicate_canonical_tally"])
async def test_decision_semantics_reject_corruptions_without_repair(tmp_path, snapshot, roster, corruption):
    decision = await orchestrator(tmp_path, ScriptedClient()).run_meeting(snapshot, roster, roster[0].member_id)
    payload = decision.model_dump(mode="json")
    if corruption == "wrong_winner":
        payload.update(rate_decision_bps=40, dissenting_members_rate=[p.member_id for p in roster])
        for vote in payload["member_votes"]:
            vote["dissenting_on_rate"] = True
    elif corruption == "false_dissent_flag":
        payload["member_votes"][0]["dissenting_on_rate"] = True
    elif corruption == "duplicate_dissent":
        payload.update(rate_decision_bps=40, synthetic_resolution_rate=True, rate_resolution_policy="status_quo",
                       dissenting_members_rate=[p.member_id for p in roster] + [roster[0].member_id])
        for vote in payload["member_votes"]:
            vote["dissenting_on_rate"] = True
    elif corruption == "short_roster":
        payload["member_votes"].pop()
        payload["rate_vote_tally"] = {"35": 5}
        payload["stance_vote_tally"] = {"neutral": 5}
    elif corruption == "boolean_as_text":
        payload["tie_broken_by_governor_rate"] = "false"
    else:
        payload["rate_vote_tally"] = {35: 6, "35": 6}
    with pytest.raises(ValidationError):
        MeetingCommitteeDecision.model_validate(payload)


async def test_replicates_use_distinct_seeds_and_paired_conditions_match(tmp_path, snapshot, roster):
    client = ScriptedClient()
    runner = orchestrator(tmp_path, client)
    first = await runner.run_meeting(snapshot, roster, roster[0].member_id, replicate_id=1, condition_id="baseline")
    paired = await runner.run_meeting(snapshot, roster, roster[0].member_id, replicate_id=1, condition_id="treatment", ablated_member_id=roster[2].member_id)
    second = await runner.run_meeting(snapshot, roster, roster[0].member_id, replicate_id=2, condition_id="baseline")
    assert first.seed_schedule == paired.seed_schedule
    assert set(first.seed_schedule.values()).isdisjoint(second.seed_schedule.values())


@pytest.mark.parametrize("builder,changed", [
    (ScenarioRunner.build_monsoon_food_shock_snapshot, {"cpi_headline_yoy_pct", "cpi_food_yoy_pct", "iip_growth_yoy_pct", "output_gap_pct", "monsoon_departure_lpa_pct"}),
    (ScenarioRunner.build_us_fed_spillover_snapshot, {"cpi_headline_yoy_pct", "cpi_core_yoy_pct", "system_liquidity_cr", "usd_inr_exchange_rate", "us_fed_funds_rate_pct"}),
    (ScenarioRunner.build_pandemic_easing_snapshot, {"cpi_headline_yoy_pct", "cpi_core_yoy_pct", "cpi_food_yoy_pct", "iip_growth_yoy_pct", "output_gap_pct", "system_liquidity_cr", "usd_inr_exchange_rate", "brent_crude_usd_bbl", "us_fed_funds_rate_pct", "prev_stance"}),
    (ScenarioRunner.build_taper_tantrum_snapshot, {"cpi_headline_yoy_pct", "cpi_core_yoy_pct", "cpi_food_yoy_pct", "iip_growth_yoy_pct", "output_gap_pct", "system_liquidity_cr", "usd_inr_exchange_rate", "brent_crude_usd_bbl", "us_fed_funds_rate_pct", "prev_stance"}),
])
def test_shocks_preserve_all_unrelated_fields_and_label_synthetic_values(snapshot, builder, changed):
    shocked = builder(snapshot)
    excluded = changed | {"input_track", "intervention", "parent_snapshot_hash"}
    for key, value in snapshot.model_dump().items():
        if key not in excluded:
            assert shocked.model_dump()[key] == value, key
    assert shocked.input_track == "counterfactual"
    assert len(shocked.parent_snapshot_hash) == 64
    assert set(shocked.intervention["changed_fields"]) == changed
    assert shocked.intervention["estimand_scope"] == "simulator_local"


def test_shocks_and_muting_preserve_missing_values_and_zero_food(snapshot):
    missing = snapshot.model_copy(update={"iip_growth_yoy_pct": None, "output_gap_pct": None, "cpi_food_yoy_pct": None})
    shocked = ScenarioRunner.build_monsoon_food_shock_snapshot(missing)
    assert shocked.iip_growth_yoy_pct is None and shocked.output_gap_pct is None and shocked.cpi_food_yoy_pct is None
    with pytest.raises(ValueError, match="observed"):
        AttributionRunner.mute_macro_input(missing, "food_inflation")
    zero_food = snapshot.model_copy(update={"cpi_food_yoy_pct": 0.0})
    assert ScenarioRunner.build_monsoon_food_shock_snapshot(zero_food).cpi_food_yoy_pct == 4.0
    for factor, changed in [("monsoon", {"monsoon_departure_lpa_pct"}), ("food_inflation", {"cpi_headline_yoy_pct", "cpi_food_yoy_pct"})]:
        muted = AttributionRunner.mute_macro_input(snapshot, factor)
        for key, value in snapshot.model_dump().items():
            if key not in changed | {"input_track", "intervention", "parent_snapshot_hash"}:
                assert muted.model_dump()[key] == value


def test_nonfinite_scenario_parameters_and_corrupt_input_fail(snapshot):
    with pytest.raises(ValueError):
        ScenarioRunner.build_us_fed_spillover_snapshot(snapshot, inr_depreciation=float("inf"))
    corrupt = snapshot.model_copy(update={"gva_growth_yoy_pct": float("nan")})
    with pytest.raises(ValueError):
        ScenarioRunner.build_monsoon_food_shock_snapshot(corrupt)


def test_statutory_quorum_and_governor_absence_do_not_invent_deputy_casting():
    votes = {"deputy": 40, "a": 40, "b": 40, "c": 0}
    result = InstitutionalRuleEngine.aggregate_rate_votes(votes, "governor", full_roster=False,
                                                          deputy_governor_id="deputy", fragmentation_policy="reject")
    assert result.winning_action == 40 and result.majority_achieved and result.members_present == 4
    assert not result.full_roster_simulation and not result.tie_broken_by_governor
    with pytest.raises(ValueError, match="Governor"):
        InstitutionalRuleEngine.aggregate_rate_votes(votes, "governor", full_roster=False)
    with pytest.raises(ValueError, match="synthetic"):
        InstitutionalRuleEngine.aggregate_rate_votes({"deputy": 40, "a": 40, "b": 0, "c": 0}, "governor",
                                                     full_roster=False, deputy_governor_id="deputy", fragmentation_policy="reject")
    # Quorum applies to attendance, majority to those present and voting.
    result = InstitutionalRuleEngine.aggregate_rate_votes({"governor": 35, "a": 35, "b": 0}, "governor", full_roster=False,
                                                          attending_member_ids=["governor", "a", "b", "c"])
    assert result.winning_action == 35 and result.members_present == 4
    with pytest.raises(ValueError, match="absent"):
        InstitutionalRuleEngine.aggregate_rate_votes({"outsider": 0}, "governor", full_roster=False,
                                                     attending_member_ids=["governor", "a", "b", "c"])


def test_fragmentation_is_explicit_synthetic_and_never_casting():
    votes = {"governor": 0, "a": 0, "b": 35, "c": 35, "d": 40, "e": 40}
    with pytest.raises(ValueError,match='No majority'):
        InstitutionalRuleEngine.aggregate_rate_votes(votes, "governor")
    result = InstitutionalRuleEngine.aggregate_rate_votes(votes, "governor",fragmentation_policy='legacy_synthetic')
    assert result.synthetic_resolution and not result.tie_broken_by_governor
    assert result.resolution_policy == "synthetic_governor_weighted_median"
    with pytest.raises(ValueError, match="synthetic"):
        InstitutionalRuleEngine.aggregate_rate_votes(votes, "governor", fragmentation_policy="reject")
    stance = {"governor": "neutral", "a": "neutral", "b": "accommodative", "c": "accommodative",
              "d": "withdrawal_of_accommodation", "e": "withdrawal_of_accommodation"}
    with pytest.raises(ValueError,match='No majority'):
        InstitutionalRuleEngine.aggregate_stance_votes(stance, "governor")
    result = InstitutionalRuleEngine.aggregate_stance_votes(stance, "governor",fragmentation_policy='legacy_synthetic')
    assert result.synthetic_resolution and not result.tie_broken_by_governor


def test_scenario_fragmentation_is_rejected_or_explicitly_labeled(snapshot):
    class FragmentedRule:
        def compute_discrete_action(self, supplied, params):
            return (0, 0, 35, 35, 40, 40)[int(params.member_id[1:])], "neutral"
    members = [MemberTaylorParameters(f"m{i}") for i in range(6)]
    with pytest.raises(ValueError, match="synthetic resolution"):
        ScenarioRunner(FragmentedRule()).run_us_fed_spillover_shock(snapshot, members, "m0")
    result = ScenarioRunner(FragmentedRule(), fragmentation_policy="legacy_synthetic").run_us_fed_spillover_shock(snapshot, members, "m0")
    assert result.rate_wedge_bps == 0
    assert result.baseline_repo_rate_change_bps == result.shocked_repo_rate_change_bps == 35
    assert result.synthetic_resolutions["baseline_rate"] and result.synthetic_resolutions["shocked_rate"]
    assert result.resolution_policies["baseline_rate"] == "synthetic_governor_weighted_median"
    assert len(result.baseline_snapshot_hash) == len(result.shocked_snapshot_hash) == 64


def test_binary_casting_removal_preserves_actual_prior_stance():
    outcome = MeetingCommitteeDecision(meeting_date="2023-08-10", replicate_id=1,
        rate_decision_bps=40, stance_decision="neutral", rate_vote_tally={40: 3, 0: 3},
        stance_vote_tally={"neutral": 3, "withdrawal_of_accommodation": 3},
        tie_broken_by_governor_rate=True, tie_broken_by_governor_stance=True,
        dissenting_members_rate=[], dissenting_members_stance=[], member_votes=[], prior_stance="accommodative")
    result = AttributionRunner.ablate_casting_vote(outcome, "governor")
    assert result.ablated_decision_bps == 0
    assert result.ablated_stance == "accommodative"
    assert "synthetic status quo" in result.description
    with pytest.raises(ValueError, match="contradicts"):
        AttributionRunner.ablate_casting_vote(outcome, "governor", prior_stance="neutral")
    outcome.prior_stance = None
    with pytest.raises(ValueError, match="actual prior stance"):
        AttributionRunner.ablate_casting_vote(outcome, "governor")
    outcome.prior_stance = "neutral"
    outcome = outcome.model_copy(update={"synthetic_resolution_rate": True})
    with pytest.raises(ValueError, match="synthetic fragmentation"):
        AttributionRunner.ablate_casting_vote(outcome, "governor")
