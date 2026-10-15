"""Counterexamples for the retrospective roster/source/persona input firewall."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.persona_engine.rolling_inputs import (
    ROOT, _publication_day, build_rolling_inputs, canonical_member_id,
    canonical_roster, sha256, verify_portable_rolling_inputs,
)
from src.schemas.temporal_panel_schema import (
    DatedSourceRef, PersonalStatementRef, RollingPersonaPacket, TemporalMeetingRoster,
    validate_temporal_stance,
)


def source(publication="2024-08-22"):
    return {"source_id": "rbi_test", "source_file": "raw/source.html",
            "source_sha256": "a" * 64, "source_url": "https://www.rbi.org.in/source",
            "publication_date": publication,
            "publication_status": "verified_retained_header" if publication else "unresolved"}


def statement(publication="2024-08-22", decision="2024-08-08", member="nagesh_kumar"):
    return {"statement_id": "rbi_mpc_" + decision + ":" + member,
            "member_id": member, "original_member_id": member,
            "meeting_id": "rbi_mpc_" + decision, "decision_date": decision,
            "source": source(publication), "statement_file": "statements/person.txt",
            "statement_sha256": "b" * 64, "attribution_heading": "Statement by Dr. Nagesh Kumar"}


def packet(statements=None):
    values = [statement()] if statements is None else statements
    return {"meeting_id": "rbi_mpc_2024-10-09", "member_id": "nagesh_kumar",
            "information_cutoff": "2024-10-07T00:00:00+05:30", "statements": values,
            "history_status": "available_personal_history" if values else "missing_personal_history",
            "lexical_hawk_hits": 3 if values else 0, "lexical_dove_hits": 1 if values else 0,
            "lexical_orientation": .5 if values else None}


def test_source_ontology_requires_explicit_version_and_rejects_mapping():
    assert validate_temporal_stance("calibrated_tightening", ontology="expanded_source_v2") == "calibrated_tightening"
    with pytest.raises(ValueError, match="Unsupported stance"):
        validate_temporal_stance("calibrated_tightening", ontology="simulator_v1")
    with pytest.raises(ValueError):
        validate_temporal_stance("neutral", ontology="implied")
    with pytest.raises(TypeError):
        validate_temporal_stance("neutral")


def test_identity_alias_is_explicit_and_cannot_collapse_duplicate_attendees():
    assert canonical_member_id("michael_patra") == canonical_member_id("michael_debabrata_patra")
    with pytest.raises(ValueError, match="duplicate"):
        canonical_roster(["michael_patra", "michael_debabrata_patra", "shaktikanta_das",
                          "rajiv_ranjan", "nagesh_kumar", "ram_singh"])
    with pytest.raises(ValueError, match="Unknown"):
        canonical_member_id("new_member_without_source")


@pytest.mark.parametrize("publication,decision", [
    ("2024-10-07", "2024-08-08"), ("2024-10-08", "2024-08-08"),
    (None, "2024-08-08"), ("2024-10-23", "2024-10-09"),
    ("2025-01-01", "2024-12-06"),
])
def test_equal_day_unknown_same_meeting_future_sources_fail_closed(publication, decision):
    with pytest.raises(ValueError):
        RollingPersonaPacket.model_validate(packet([statement(publication, decision)]))


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(information_cutoff="2024-10-07T00:00:00"),
    lambda p: p.update(information_cutoff="2024-10-07T00:00:00+00:00"),
    lambda p: p.update(information_cutoff="2024-10-07T01:00:00+05:30"),
    lambda p: p.update(history_status="missing_personal_history"),
    lambda p: p.update(lexical_orientation=.9),
    lambda p: p["statements"][0].update(member_id="ram_singh"),
    lambda p: p["statements"].append(copy.deepcopy(p["statements"][0])),
])
def test_persona_contract_rejects_changed_identity_cutoff_fit_or_duplicate_source(mutate):
    data = packet()
    mutate(data)
    with pytest.raises(ValueError):
        RollingPersonaPacket.model_validate(data)


def test_missing_history_is_missing_not_zero_prior_or_other_identity():
    result = RollingPersonaPacket.model_validate(packet([]))
    assert result.history_status == "missing_personal_history"
    assert result.lexical_orientation is None
    assert result.construct_validated is False
    bad = packet([])
    bad["lexical_orientation"] = 0
    with pytest.raises(ValueError, match="Missing personal history"):
        RollingPersonaPacket.model_validate(bad)


def test_source_paths_and_unknown_publication_do_not_get_fabricated():
    assert DatedSourceRef.model_validate(source(None)).publication_date is None
    bad = source(None)
    bad["publication_status"] = "verified_retained_header"
    with pytest.raises(ValueError):
        DatedSourceRef.model_validate(bad)
    for path in ("../source.html", "/source.html", "raw\\source.html"):
        bad = source()
        bad["source_file"] = path
        with pytest.raises(ValueError):
            DatedSourceRef.model_validate(bad)
    assert _publication_day(BeautifulSoup('<div id="doublescroll">Date : Oct 23, 2024 Minutes</div>', "html.parser")) == "2024-10-23"
    assert _publication_day(BeautifulSoup('<div id="doublescroll">Decision October 9, 2024</div>', "html.parser")) is None


@pytest.fixture(scope="module")
def built_inputs(tmp_path_factory):
    directory = tmp_path_factory.mktemp("rolling_packet") / "built"
    receipt = build_rolling_inputs(output_root=directory)
    return directory, receipt


def read_packet(directory, decision):
    return json.loads((directory / "packets" / ("rbi_mpc_" + decision + ".json")).read_text())


def test_retained_panel_is_complete_chronological_and_oracle_status_explicit(built_inputs):
    directory, receipt = built_inputs
    assert (receipt["meetings_count"], receipt["member_packets_count"], receipt["source_statements_count"]) == (38, 228, 222)
    assert receipt["missing_history_member_packets"] == 14
    assert receipt["model_calls"] == 0 and receipt["predictive_readiness"] is False
    assert receipt["unresolved_publication_statements"] == 0
    rosters = json.loads((directory / "realized_rosters.json").read_text())
    days = [r["decision_date"] for r in rosters]
    assert days == sorted(set(days))
    for row in rosters:
        assert row["roster_evidence_status"] == "retrospective_oracle_attendance"
        assert row["roster_available_at_cutoff"] is False
        assert row["appointment_dates"] is None
    regimes = json.loads((directory / "observed_roster_regimes.json").read_text())
    assert len(regimes) == 6
    governor_change = next(r for r in regimes if r["first_observed_decision"] == "2025-02-07")
    assert governor_change["governor_id"] == "sanjay_malhotra"
    assert governor_change["turnover_bracket"]["after_old_roster_observed_decision"] == "2024-12-06"
    assert governor_change["appointment_start_date"] is None


def test_rolling_sources_reuse_only_same_identity_before_cutoff(built_inputs):
    directory, _ = built_inputs
    first = read_packet(directory, "2024-10-09")
    members = {m["member_id"]: m for m in first["members"]}
    assert members["nagesh_kumar"]["history_status"] == "missing_personal_history"
    assert members["michael_debabrata_patra"]["history_status"] == "available_personal_history"
    assert all(s["original_member_id"] == "michael_patra" for s in members["michael_debabrata_patra"]["statements"])
    assert all(e["reason"] != "eligible" for e in first["exclusions"])
    assert sum(e["reason"] == "same_meeting_outcome_statement" for e in first["exclusions"]) == 6
    feb = {m["member_id"]: m for m in read_packet(directory, "2025-02-07")["members"]}
    assert feb["sanjay_malhotra"]["history_status"] == "missing_personal_history"
    assert feb["m_rajeshwar_rao"]["history_status"] == "missing_personal_history"
    assert "michael_debabrata_patra" not in feb
    last = read_packet(directory, "2026-10-07")
    for row in last["members"]:
        assert all(s["source"]["publication_date"] < "2026-10-05" for s in row["statements"])
        assert all(s["meeting_id"] != last["meeting_id"] for s in row["statements"])
    assert last["roster_available_at_cutoff"] is False
    compatibility = json.loads((directory / "stance_compatibility_outcomes.json").read_text())[-1]
    assert compatibility["source_stance"] == "calibrated_tightening"
    assert compatibility["simulator_v1_supported"] is False and compatibility["mapping"] is None


def test_portable_verification_and_source_only_rebuild_have_identical_packets(built_inputs, tmp_path):
    directory, receipt = built_inputs
    verified = verify_portable_rolling_inputs(directory)
    assert verified["meetings_count"] == 38 and verified["predictive_readiness"] is False
    source_root = tmp_path / "allowed_scientific_sources"
    for origin, portable in receipt["origin_to_portable"].items():
        destination = source_root / origin
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(directory / portable, destination)
    assert not (source_root / "results").exists()
    assert not (source_root / ".git").exists()
    new = tmp_path / "rebuilt"
    reconstructed = build_rolling_inputs(output_root=new, source_root=source_root)
    assert reconstructed["output_files"] == receipt["output_files"]
    assert verify_portable_rolling_inputs(new)["verified_files"] == verified["verified_files"]
    with pytest.raises(FileExistsError):
        build_rolling_inputs(output_root=new, source_root=source_root)


def test_corrupt_portable_statement_fails_before_verification(built_inputs, tmp_path):
    directory, _ = built_inputs
    copy_root = tmp_path / "corrupt"
    shutil.copytree(directory, copy_root)
    packet_row = read_packet(copy_root, "2024-12-06")["members"][0]["statements"][0]
    path = copy_root / packet_row["statement_file"]
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_portable_rolling_inputs(copy_root)


def test_changed_publication_ledger_rejects_raw_header_disagreement(built_inputs, tmp_path):
    directory, receipt = built_inputs
    source_root = tmp_path / "changed_source_ledger"
    for origin, portable in receipt["origin_to_portable"].items():
        destination = source_root / origin
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(directory / portable, destination)
    path = source_root / "research/source_ledgers/expanded_panel_oct08/source_catalog.json"
    data = json.loads(path.read_text())
    row = next(r for r in data["records"] if r["source_id"] == "rbi_prid_58958")
    row["publication_date"] = "2024-10-09"
    path.write_text(json.dumps(data))
    out = tmp_path / "rejected"
    with pytest.raises(ValueError, match="Publication ledger/header mismatch"):
        build_rolling_inputs(output_root=out, source_root=source_root)
    assert not out.exists()
