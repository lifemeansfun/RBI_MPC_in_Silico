"""Hand oracles for independent ballot arithmetic and retained planned failures.

All fixtures are engineering mock data. No producer scoring or generation
helper is imported, and these tests do not establish scientific adequacy.
"""

import hashlib
import json
from itertools import permutations

import pytest

from src.infra.evidence import canonical_json, content_hash, file_hash
from src.validation.paired_consensus import (
    agreement_range, analyze_pairs, ballot_metrics, enumerate_peer_partitions,
    governor_contrast, reconstruct_from_artifacts,
)


MENU = [{"vote": vote, "stance": "neutral"} for vote in (-50, -25, 0, 25, 35, 40, 50)]
ROSTER = ["a", "b", "c", "d", "e", "governor"]


def vote(member, rate=0, stance="neutral"):
    return {"agent_id": member, "vote": rate, "stance": stance}


def seal(document):
    payload = {key: value for key, value in document.items() if key != "artifact_content_hash"}
    return {**payload, "artifact_content_hash": content_hash(payload)}


def prefix(day="2024-01-01", replicate=1, peer_rates=None, menu=MENU):
    identity = {"experiment_id": "engineering_mock", "meeting_date": day, "replicate_id": replicate}
    return seal({**identity, "prefix_id": "prefix_" + content_hash(identity)[:24],
        "roster_ids": ROSTER, "governor_id": "governor", "status": "complete",
        "allowed_labels": menu,
        "non_governor_votes": [vote(member, rate) for member, rate in zip(ROSTER[:-1], peer_rates or [0] * 5)]})


def planned(pref, condition, draw="1"):
    identity = {"prefix_id": pref["prefix_id"], "condition": condition, "branch_draw_id": draw}
    return {**{key: pref[key] for key in ("experiment_id", "meeting_date", "replicate_id")},
            **identity, "branch_id": "branch_" + content_hash(identity)[:24]}


def branch(pref, condition, rate=0, draw="1", status="complete"):
    document = {**planned(pref, condition, draw), "prefix_hash": pref["artifact_content_hash"],
        "roster_ids": pref["roster_ids"], "governor_id": pref["governor_id"], "status": status}
    if status == "complete":
        document["votes"] = [*pref["non_governor_votes"], vote("governor", rate)]
        document["aggregation"] = {"rate": {"status": "unresolved"}}
    return seal(document)


def analyze(pref, artifacts=(), schedule=None, menu=MENU):
    return analyze_pairs(schedule or [planned(pref, "H"), planned(pref, "B")],
                         [pref], artifacts, allowed_labels=menu)


def test_six_member_unanimity_hand_oracle():
    result = ballot_metrics([vote(member) for member in ROSTER])
    assert result["pair_count"] == result["joint_agreeing_pairs"] == 15
    assert result["joint_agreement"] == result["rate_agreement"] == result["stance_agreement"] == 1
    assert result["rate_population_sd_bps"] == result["mean_pair_absolute_rate_difference_bps"] == 0


def test_joint_rate_stance_channels_are_distinct_hand_oracle():
    ballots = [vote("a", 0, "neutral"), vote("b", 0, "neutral"), vote("c", 0, "accommodative"),
               vote("d", 25, "neutral"), vote("e", 25, "neutral"), vote("governor", 25, "accommodative")]
    result = ballot_metrics(ballots)
    assert result["joint_agreeing_pairs"] == 2
    assert result["rate_agreeing_pairs"] == 6
    assert result["stance_agreeing_pairs"] == 7
    assert result["rate_population_sd_bps"] == 12.5
    assert result["rate_range_bps"] == 25
    assert result["mean_pair_absolute_rate_difference_bps"] == 15


def test_fragmented_valid_ballots_remain_measurable_without_resolution():
    pref = prefix(peer_rates=[-50, -25, 0, 25, 35])
    result = analyze(pref, [branch(pref, "H", 40), branch(pref, "B", 50)])
    assert result["complete_pairs"] == 1 and result["all_planned_point"] == 0
    assert all(metrics["joint_agreement"] == 0 for metrics in result["branch_metrics"].values())
    assert result["prompt_semantic_leakage_validation"]["status"] == "manual_unverified"
    assert result["uncertainty"]["precision_adequacy_verified"] is False


def test_ballot_permutations_do_not_change_metrics():
    ballots = [vote(member, rate) for member, rate in zip(ROSTER, [0, 0, 0, 25, 25, -25])]
    expected = ballot_metrics(ballots)
    assert expected["joint_agreeing_pairs"] == 4
    for shuffled in permutations(ballots):
        assert ballot_metrics(shuffled) == expected


@pytest.mark.parametrize("bad", [True, 0.0, float("inf"), float("nan"), "0", None, 7])
def test_malformed_or_unknown_rates_are_failure_not_zero_agreement(bad):
    ballots = [vote(member) for member in ROSTER]
    ballots[0]["vote"] = bad
    with pytest.raises(ValueError):
        ballot_metrics(ballots)


@pytest.mark.parametrize("bad", ["", " ", "unsupported", None, 1])
def test_unknown_stance_is_failure_not_successful_consensus(bad):
    ballots = [vote(member) for member in ROSTER]
    ballots[0]["stance"] = bad
    with pytest.raises(ValueError):
        ballot_metrics(ballots)


def test_duplicate_missing_and_crossed_roster_fail_closed():
    ballots = [vote(member) for member in ROSTER]
    with pytest.raises(ValueError, match="exactly 6"):
        ballot_metrics(ballots[:-1])
    ballots[-1]["agent_id"] = "a"
    with pytest.raises(ValueError, match="Duplicate"):
        ballot_metrics(ballots)
    with pytest.raises(ValueError, match="roster"):
        ballot_metrics([vote(member) for member in ROSTER], roster=[*ROSTER[:-1], "unplanned"])


def test_all_seven_hand_enumerated_partitions_and_effect_ceiling():
    rows = enumerate_peer_partitions()
    assert [row["partition"] for row in rows] == [[5], [4, 1], [3, 2], [3, 1, 1], [2, 2, 1], [2, 1, 1, 1], [1, 1, 1, 1, 1]]
    assert [row["peer_agreeing_pairs"] for row in rows] == [10, 6, 4, 3, 2, 1, 0]
    assert [row["contrast_upper"] for row in rows] == [1 / 3, 4 / 15, 1 / 5, 1 / 5, 2 / 15, 2 / 15, 1 / 15]
    assert rows[0]["contrast_lower"] == -1 / 3 and rows[-1]["contrast_lower"] == -1 / 15


def test_fixed_peers_feasible_menu_sharpens_range():
    peers = prefix(peer_rates=[0, 0, 0, 0, 25])["non_governor_votes"]
    result = agreement_range(peers, [{"vote": 0, "stance": "neutral"}, {"vote": 25, "stance": "neutral"}])
    assert result["peer_agreeing_pairs"] == 6
    assert result["attainable_joint_agreement"] == [7 / 15, 10 / 15]
    assert result["contrast_lower"] == -3 / 15 and result["contrast_upper"] == 3 / 15
    assert agreement_range(peers, MENU)["contrast_upper"] == 4 / 15


def test_five_distinct_peers_exact_governor_contrast_oracle():
    peers = prefix(peer_rates=[-50, -25, 0, 25, 35])["non_governor_votes"]
    result = governor_contrast(peers, {"vote": 40, "stance": "neutral"}, {"vote": 0, "stance": "neutral"})
    assert result == {"numerator": 1, "denominator": 15, "contrast": 1 / 15}
    assert agreement_range(peers, MENU)["contrast_upper"] == 1 / 15


def test_asymmetric_failed_branch_retains_all_planned_denominator():
    pref = prefix()
    result = analyze(pref, [branch(pref, "H"), branch(pref, "B", status="failed")])
    assert result["planned_pairs"] == 1 and result["complete_pairs"] == 0
    assert result["condition_counts"]["B"] == {"planned": 1, "complete": 0, "failed": 1, "unattempted": 0}
    assert result["all_planned_point"] is None and result["successful_pair_sensitivity"] is None
    assert result["sharp_missing_outcome_bounds"]["lower"] == pytest.approx(-1 / 3)
    assert result["sharp_missing_outcome_bounds"]["upper"] == 0
    assert result["uncertainty"]["conditional_governor_draw_monte_carlo_standard_error"] is None


def test_observed_positive_branch_reverses_asymmetric_failure_bound():
    pref = prefix()
    result = analyze(pref, [branch(pref, "B"), branch(pref, "H", status="failed")])
    assert result["sharp_missing_outcome_bounds"]["lower"] == 0
    assert result["sharp_missing_outcome_bounds"]["upper"] == pytest.approx(1 / 3)


def test_unattempted_pairs_and_missing_prefix_use_correct_logical_bounds():
    pref = prefix(peer_rates=[-50, -25, 0, 25, 35])
    result = analyze(pref)
    assert result["sharp_missing_outcome_bounds"]["upper"] == 1 / 15
    assert result["condition_counts"]["H"]["unattempted"] == 1
    missing = analyze_pairs([planned(pref, "H"), planned(pref, "B")], [], [], allowed_labels=MENU)
    assert missing["sharp_missing_outcome_bounds"]["lower"] == -1 / 3
    assert missing["sharp_missing_outcome_bounds"]["upper"] == 1 / 3
    assert missing["pairs"][0]["bound_source"] == "unobserved_prefix_global_feasible_actions"


def test_missing_bounds_are_attained_by_enumerating_feasible_governor_completions():
    pref = prefix(peer_rates=[0, 0, 0, 25, 25])
    result = analyze(pref, [branch(pref, "H", 25), branch(pref, "B", status="failed")])
    completed = [analyze(pref, [branch(pref, "H", 25), branch(pref, "B", action["vote"])])["all_planned_point"] for action in MENU]
    assert result["sharp_missing_outcome_bounds"]["lower"] == pytest.approx(min(completed))
    assert result["sharp_missing_outcome_bounds"]["upper"] == pytest.approx(max(completed))


def test_meetings_prefixes_and_draws_get_declared_weights_with_partial_failure():
    first = prefix()
    second = prefix(replicate=2)
    third = prefix(day="2024-02-01")
    schedule, artifacts = [], []
    for pref, draws in ((first, ("1", "2", "3")), (second, ("1",)), (third, ("1",))):
        for draw in draws:
            schedule += [planned(pref, "H", draw), planned(pref, "B", draw)]
            h_rate, b_rate = (25, 0) if pref is first else (0, 25)
            artifacts += [branch(pref, "H", h_rate, draw), branch(pref, "B", b_rate, draw)]
    result = analyze_pairs(schedule, [first, second, third], artifacts, allowed_labels=MENU)
    # Meeting 1: mean(+1/3,-1/3)=0 regardless of unequal draw count.
    # Meeting 2: -1/3. Equal meeting mean = -1/6.
    assert result["all_planned_point"] == pytest.approx(-1 / 6)
    assert result["sharp_missing_outcome_bounds"]["lower"] == pytest.approx(-1 / 6)
    artifacts[-1] = branch(third, "B", status="failed")
    result = analyze_pairs(schedule, [first, second, third], artifacts, allowed_labels=MENU)
    assert result["all_planned_point"] is None
    assert result["successful_pair_sensitivity"] == 0
    assert result["sharp_missing_outcome_bounds"]["lower"] == pytest.approx(-1 / 6)
    assert result["sharp_missing_outcome_bounds"]["upper"] == 0
    assert result["planned_pairs"] == 5 and result["complete_pairs"] == 4


def test_fixed_cohort_mc_uncertainty_does_not_create_temporal_evidence():
    prefixes = [prefix(replicate=1), prefix(replicate=2)]
    schedule, artifacts = [], []
    for pref in prefixes:
        for draw in ("1", "2"):
            schedule += [planned(pref, "H", draw), planned(pref, "B", draw)]
            artifacts += [branch(pref, "H", 25, draw), branch(pref, "B", 0 if draw == "1" else 25, draw)]
    result = analyze_pairs(schedule, prefixes, artifacts, allowed_labels=MENU)
    assert result["all_planned_point"] == pytest.approx(1 / 6)
    assert result["uncertainty"]["conditional_governor_draw_monte_carlo_standard_error"] == pytest.approx(1 / (6 * 2 ** 0.5))
    assert result["uncertainty"]["fixed_cohort_prefix_monte_carlo_standard_error"] == 0
    assert result["uncertainty"]["temporal_generalization_interval"] is None
    assert result["planned_meetings"] == 1 and result["uncertainty"]["precision_adequacy_verified"] is False


def test_b_minus_n_mechanism_contrast_keeps_other_scheduled_counts():
    pref = prefix()
    schedule = [planned(pref, condition) for condition in ("H", "B", "N")]
    artifacts = [branch(pref, "H"), branch(pref, "B"), branch(pref, "N", 25)]
    result = analyze_pairs(schedule, [pref], artifacts, allowed_labels=MENU, contrast=("B", "N"))
    assert result["all_planned_point"] == 1 / 3
    assert result["planned_branches"] == 3 and result["condition_counts"]["H"]["complete"] == 1


@pytest.mark.parametrize("corruption", ["hash", "changed_peer", "crossed_meeting", "crossed_prefix", "roster", "unknown_status", "bool_vote"])
def test_corrupt_branches_fail_closed_even_when_resealed(corruption):
    pref = prefix()
    h, b = branch(pref, "H"), branch(pref, "B")
    if corruption == "hash":
        b["votes"][0]["vote"] = 25
    elif corruption == "changed_peer":
        b["votes"][0]["vote"] = 25
        b = seal(b)
    elif corruption == "crossed_meeting":
        b["meeting_date"] = "2024-02-01"
        b = seal(b)
    elif corruption == "crossed_prefix":
        b["prefix_hash"] = "0" * 64
        b = seal(b)
    elif corruption == "roster":
        b["votes"][-1]["agent_id"] = "unplanned"
        b = seal(b)
    elif corruption == "unknown_status":
        b["status"] = "success"
        b = seal(b)
    else:
        b["votes"][-1]["vote"] = False
        b = seal(b)
    with pytest.raises(ValueError):
        analyze(pref, [h, b])


def test_duplicate_unplanned_and_unpaired_schedule_fail_closed():
    pref = prefix()
    h, b = branch(pref, "H"), branch(pref, "B")
    with pytest.raises(ValueError, match="Duplicate planned"):
        analyze(pref, [h, b], [planned(pref, "H"), planned(pref, "B"), planned(pref, "B")])
    with pytest.raises(ValueError, match="both conditions"):
        analyze(pref, [h], [planned(pref, "H")])
    with pytest.raises(ValueError, match="Duplicate retained branch"):
        analyze(pref, [h, b, b])
    with pytest.raises(ValueError, match="Unplanned retained branch"):
        analyze(pref, [h, b, branch(pref, "N")])
    with pytest.raises(ValueError, match="Duplicate retained prefix"):
        analyze_pairs([planned(pref, "H"), planned(pref, "B")], [pref, pref], [h, b], allowed_labels=MENU)


def test_zero_effect_and_negative_effect_are_preserved():
    pref = prefix()
    assert analyze(pref, [branch(pref, "H"), branch(pref, "B")])["all_planned_point"] == 0
    assert analyze(pref, [branch(pref, "H"), branch(pref, "B", 25)])["all_planned_point"] == -1 / 3


def raw_payload(member, round_number, rate=0):
    base = {"member_id": member, "fallback_triggered": False}
    if round_number == 1:
        return {**base, "member_name": member, "proposed_rate_change_bps": rate,
                "proposed_stance": "neutral", "key_rationale": "Engineering fixture"}
    if round_number in (2, 3):
        return {**base, "round_number": round_number, "current_rate_preference_bps": rate,
                "current_stance_preference": "neutral", "rebuttal_or_critique": "Engineering fixture", "open_to_compromise": False}
    return {**base, "member_name": member, "is_internal": True, "final_rate_vote_bps": rate,
            "final_stance_vote": "neutral", "dissenting_on_rate": False, "dissenting_on_stance": False,
            "official_statement_rationale": "Engineering fixture"}


def retain_transcript(directory, payload, identity, request_id, settings, schema, seed):
    request = {"request_identity": identity, "system_prompt": "Engineering fixture", "user_prompt": "Engineering fixture",
               "provider": settings["provider"], "routed_model": settings["model"], "schema": schema,
               **{key: settings[key] for key in ("temperature", "model_epoch", "max_output_tokens", "parser_version")}, "seed": seed}
    raw = canonical_json(payload)
    metadata = {"request_payload_json": canonical_json(request), "request_hash": content_hash(request),
                "request_id": request_id, "cache_replay": False, "evidence_type": "mock",
                "system_prompt": request["system_prompt"], "user_prompt": request["user_prompt"],
                "provider": settings["provider"], "requested_model": settings["model"], "routed_model": settings["model"],
                **{key: settings[key] for key in ("temperature", "model_epoch", "max_output_tokens", "parser_version")}, "seed": seed,
                "schema_hash": content_hash(schema), "schema_json": canonical_json(schema),
                "prompt_hash": content_hash({"system": request["system_prompt"], "user": request["user_prompt"]})}
    transcript = seal({**payload, "artifact_identity": identity,
        "generation": {"request_identity": identity, "metadata": metadata, "raw_text": raw, "parsed": payload, "validation_error": None},
        "prompt": {"system_prompt": request["system_prompt"], "user_prompt": request["user_prompt"]}})
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"round_{identity['round_number']}_{identity['member_id']}.json"
    path.write_text(canonical_json(transcript) + "\n", encoding="utf-8")
    return {"path": path.name, "sha256": file_hash(path), "artifact_content_hash": transcript["artifact_content_hash"],
            "raw_output_hash": hashlib.sha256(raw.encode()).hexdigest(), "raw_output_hash_kind": "sha256_utf8_v1"}


def retained_fixture(tmp_path):
    pref = prefix()
    schemas = {}
    for number in (1, 2, 3, 4):
        payload = raw_payload("governor", number)
        properties = {key: {"type": "boolean" if type(value) is bool else "integer" if type(value) is int else "string"}
                      for key, value in payload.items()}
        schemas[str(number)] = {"type": "object", "properties": properties, "required": list(payload), "additionalProperties": False}
    settings = {"provider": "mock", "model": "mock", "temperature": 0.0, "model_epoch": "engineering_fixture",
                "max_output_tokens": 64, "parser_version": "strict-json-v1",
                "round_schema_hashes": {number: content_hash(schema) for number, schema in schemas.items()}}
    pref.update(artifact_version="actual-paired-prefix-v1", generation_count=23,
                generation_settings=settings, generation_settings_hash=content_hash(settings), seed_base=42, seed_schedule={},
                snapshot_hash="0" * 64, persona_hash="1" * 64, outputs={}, output_hashes={}, transcripts={})
    for round_number in (1, 2, 3, 4):
        pref["outputs"][str(round_number)] = {}
        for member in ROSTER if round_number < 4 else ROSTER[:-1]:
            payload = raw_payload(member, round_number)
            pref["outputs"][str(round_number)][member] = payload
            key = f"{member}:round_{round_number}"
            pref["output_hashes"][key] = content_hash(payload)
            identity = {key: pref[key] for key in ("experiment_id", "meeting_date", "replicate_id", "prefix_id", "snapshot_hash", "persona_hash", "generation_settings_hash")}
            identity.update(member_id=member, round_number=round_number, condition_id="shared_prefix")
            seed_input = json.dumps(["paired-member-round-v1", 42, pref["meeting_date"], pref["replicate_id"],
                                    member, round_number], separators=(",", ":")).encode()
            seed = int.from_bytes(hashlib.sha256(seed_input).digest()[:4], "big") & 0x7FFFFFFF
            pref["seed_schedule"][key] = seed
            pref["transcripts"][key] = retain_transcript(tmp_path / "prefix", payload, identity, f"mock-{key}",
                                                       settings, schemas[str(round_number)], seed)
    pref = seal(pref)
    pref_path = tmp_path / "prefix" / "shared_prefix.json"
    pref_path.write_text(canonical_json(pref) + "\n", encoding="utf-8")
    branch_paths = []
    for condition, rate in (("H", 25), ("B", 0)):
        record = branch(pref, condition, rate)
        payload = raw_payload("governor", 4, rate)
        record.update(artifact_version="governor-final-information-v1",
                      member_votes=[*pref["outputs"]["4"].values(), payload], governor_output_hash=content_hash(payload))
        identity = {key: pref[key] for key in ("experiment_id", "meeting_date", "replicate_id", "prefix_id", "snapshot_hash", "persona_hash", "generation_settings_hash")}
        identity.update(member_id="governor", round_number=4, condition_id=f"branch_{condition}_draw_1")
        identity.update({key: record[key] for key in ("branch_id", "branch_draw_id", "prefix_hash")})
        identity["branch_condition"] = condition
        seed = int(content_hash({"seed_base": 42, "branch_id": record["branch_id"]})[:8], 16) & 0x7FFFFFFF
        record["seed"] = seed
        record["governor_transcript"] = retain_transcript(tmp_path / condition, payload, identity, f"mock-{condition}",
                                                         settings, schemas["4"], seed)
        record = seal(record)
        path = tmp_path / condition / "branch_outcome.json"
        path.write_text(canonical_json(record) + "\n", encoding="utf-8")
        branch_paths.append(path)
    return [planned(pref, "H"), planned(pref, "B")], pref_path, branch_paths


def test_independent_reconstruction_verifies_23_prefix_plus_two_branch_generations(tmp_path):
    schedule, pref_path, branch_paths = retained_fixture(tmp_path)
    result = reconstruct_from_artifacts(schedule, [pref_path], branch_paths, allowed_labels=MENU)
    assert result["all_planned_point"] == 1 / 3
    assert result["reconstructed_generation_count"] == 25
    assert result["reconstructed_generation_tracks"] == {"mock": 25}
    assert result["prompt_semantic_leakage_validation"]["status"] == "manual_unverified"


def test_raw_output_hash_mismatch_is_rejected_after_summary_reseal(tmp_path):
    schedule, pref_path, branch_paths = retained_fixture(tmp_path)
    document = json.loads(branch_paths[0].read_text())
    document["governor_transcript"]["raw_output_hash"] = "0" * 64
    branch_paths[0].write_text(canonical_json(seal(document)) + "\n")
    with pytest.raises(ValueError, match="Raw generation text hash"):
        reconstruct_from_artifacts(schedule, [pref_path], branch_paths, allowed_labels=MENU)


def test_duplicate_json_and_escaping_transcript_paths_are_rejected(tmp_path):
    schedule, pref_path, branch_paths = retained_fixture(tmp_path)
    original = pref_path.read_text()
    pref_path.write_text(original.replace('"status":"complete"', '"status":"complete","status":"complete"'))
    with pytest.raises(ValueError, match="Duplicate JSON"):
        reconstruct_from_artifacts(schedule, [pref_path], branch_paths, allowed_labels=MENU)
    pref_path.write_text(original)
    document = json.loads(branch_paths[0].read_text())
    document["governor_transcript"]["path"] = "../prefix/round_1_a.json"
    branch_paths[0].write_text(canonical_json(seal(document)) + "\n")
    with pytest.raises(ValueError, match="Transcript path"):
        reconstruct_from_artifacts(schedule, [pref_path], branch_paths, allowed_labels=MENU)


def test_resealed_projection_cannot_disagree_with_retained_raw_vote(tmp_path):
    schedule, pref_path, branch_paths = retained_fixture(tmp_path)
    document = json.loads(branch_paths[0].read_text())
    document["votes"][-1]["vote"] = 0
    branch_paths[0].write_text(canonical_json(seal(document)) + "\n")
    with pytest.raises(ValueError, match="projection differs"):
        reconstruct_from_artifacts(schedule, [pref_path], branch_paths, allowed_labels=MENU)


@pytest.mark.parametrize("field", ["branch_condition", "seed", "schema", "max_output_tokens", "model_epoch", "request_id", "digest_kind"])
def test_resealed_canonical_requests_and_receipts_cannot_cross_join_or_change_settings(tmp_path, field):
    schedule, pref_path, branch_paths = retained_fixture(tmp_path)
    document = json.loads(branch_paths[0].read_text())
    transcript_path = branch_paths[0].parent / document["governor_transcript"]["path"]
    transcript = json.loads(transcript_path.read_text())
    metadata = transcript["generation"]["metadata"]
    request = json.loads(metadata["request_payload_json"])
    if field == "branch_condition":
        # Artifact condition H is immutable in the schedule; the actual request
        # uses its explicit branch_condition alias, not an untyped extra field.
        transcript["generation"]["request_identity"]["branch_condition"] = "B"
        request["request_identity"]["branch_condition"] = "B"
    elif field == "schema":
        request["schema"]["properties"]["final_rate_vote_bps"]["type"] = "number"
        metadata["schema_json"] = canonical_json(request["schema"])
        metadata["schema_hash"] = content_hash(request["schema"])
    elif field == "request_id":
        metadata["request_id"] = "mock-a:round_1"
    elif field == "digest_kind":
        document["governor_transcript"]["raw_output_hash_kind"] = "sha256_canonical_json_string_v1"
    else:
        value = "different_epoch" if field == "model_epoch" else metadata[field] + 1
        metadata[field] = request[field] = value
    metadata["request_payload_json"] = canonical_json(request)
    metadata["request_hash"] = content_hash(request)
    transcript = seal(transcript)
    transcript_path.write_text(canonical_json(transcript) + "\n")
    document["governor_transcript"]["sha256"] = file_hash(transcript_path)
    document["governor_transcript"]["artifact_content_hash"] = transcript["artifact_content_hash"]
    branch_paths[0].write_text(canonical_json(seal(document)) + "\n")
    with pytest.raises(ValueError):
        reconstruct_from_artifacts(schedule, [pref_path], branch_paths, allowed_labels=MENU)
