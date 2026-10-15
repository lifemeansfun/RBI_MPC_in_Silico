"""Engineering failure controls for source-linked rolling execution and audit."""
from __future__ import annotations

import copy
from datetime import datetime
import json
from pathlib import Path
import shutil

import pytest

from src.backtest.eligibility_audit import audit_existing_panel, _macro, MINIMUM_MACRO_FIELDS
from src.infra.evidence import file_hash
from src.infra.exceptions import GenerationProvenanceError
from src.persona_engine.executable_rolling import (
    MANIFEST_VERSION, _RawVerifier, build_executable_rolling_bundle, load_executable_personas,
)
from src.persona_engine.provenance import verify_personas
from src.persona_engine.rolling_inputs import ROOT, build_rolling_inputs, _json_bytes, sha256
from src.schemas.persona_schema import MemberPersona


@pytest.fixture(scope="module")
def source_bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("source_owner_engineering")
    rolling = root / "rolling"
    build_rolling_inputs(output_root=rolling)
    executable = root / "executable"
    receipt = build_executable_rolling_bundle(rolling_root=rolling, output_root=executable)
    return rolling, executable, receipt


def read(path):
    return json.loads(Path(path).read_text())


def test_complete_portable_adapter_retains_exclusions_and_raw_grounding(source_bundle):
    rolling, executable, receipt = source_bundle
    assert receipt["model_calls"] == 0 and receipt["predictive_readiness"] is False
    assert receipt["construct_validated"] is False
    assert (receipt["meetings_count"], receipt["complete_executable_meetings"],
            receipt["missing_history_member_packets"]) == (38, 32, 14)
    index = read(executable / "index.json")
    assert len(index) == 38
    assert all(file_hash(executable / name) == digest for name, digest in receipt["output_files"].items())
    personas, context = load_executable_personas(executable, "rbi_mpc_2024-12-06")
    assert set(context) == {"source_root", "corpus_manifest_path"}
    assert len(personas) == 6 and all(p.biography is None for p in personas)
    assert {p.member_id for p in personas} == {
        "nagesh_kumar", "ram_singh", "saugata_bhattacharya", "rajiv_ranjan",
        "michael_debabrata_patra", "shaktikanta_das"}
    manifest = read(context["corpus_manifest_path"])
    assert manifest["version"] == MANIFEST_VERSION
    assert "procedural" in manifest["extraction_rule"]["stance_bias"]
    assert manifest["roster_available_at_cutoff"] is False
    assert manifest["historical_first_availability_verified"] is False
    for member in manifest["members"].values():
        for ref in member["corpus_sources"]:
            assert ref["source"]["publication_date"] < manifest["calibration_cutoff"]
            assert ref["meeting_id"] != manifest["meeting_id"]
        for quote in member["quote_evidence"]:
            ref = next(r for r in member["corpus_sources"] if r["statement_id"] == quote["statement_id"])
            assert quote["text"] in (rolling / ref["statement_file"]).read_text()
            assert quote["statement_sha256"] == ref["statement_sha256"]


def test_missing_histories_are_exclusions_never_scores_or_substituted_personas(source_bundle):
    _, executable, _ = source_bundle
    with pytest.raises(GenerationProvenanceError, match="Missing personal history"):
        load_executable_personas(executable, "rbi_mpc_2020-10-09")
    personas, context = load_executable_personas(executable, "rbi_mpc_2020-10-09", require_complete=False)
    assert personas == []
    manifest = read(context["corpus_manifest_path"])
    assert len(manifest["missing_history_member_ids"]) == 6
    assert all(member["persona_fields"] is None and member["meetings_count"] == 0
               for member in manifest["members"].values())
    with pytest.raises(GenerationProvenanceError, match="Missing personal history"):
        load_executable_personas(executable, "rbi_mpc_2022-05-04")
    entry_personas, _ = load_executable_personas(executable, "rbi_mpc_2022-05-04", require_complete=False)
    assert "rajiv_ranjan" not in {p.member_id for p in entry_personas}
    assert "mridul_saggar" not in {p.member_id for p in entry_personas}


@pytest.mark.parametrize("change", [
    {"tenure": "Invented appointment tenure"}, {"biography": "Invented current biography"},
    {"key_themes": ["Invented quotation"]}, {"hawk_dove_score": -1},
    {"name": "Wrong person"}, {"role": "Governor"}, {"stance_bias": "accommodative"},
    {"voting_priority": "Undocumented preference"}, {"provenance_status": "assumed"},
    {"system_prompt_override": "Unregistered prompt"},
])
def test_every_executable_persona_field_remains_bound_to_raw_fit(source_bundle, change):
    _, executable, _ = source_bundle
    # Read the frozen fields directly to avoid a redundant full verification;
    # each counterexample below invokes the production verifier itself.
    path = executable / "meetings/rbi_mpc_2020-12-04"
    personas = [MemberPersona.model_validate(p) for p in read(path / "personas.json")]
    personas[0] = personas[0].model_copy(update=change)
    with pytest.raises(GenerationProvenanceError, match="Persona fields"):
        verify_personas(personas, datetime.fromisoformat("2020-12-02T00:00:00+05:30"),
            source_root=executable, corpus_manifest_path=path / "corpus_manifest.json")


def test_manifest_rehash_cannot_authorize_corrupt_fitted_fields(source_bundle, tmp_path):
    _, executable, _ = source_bundle
    path = tmp_path / "forged_corpus_manifest.json"
    manifest = read(executable / "meetings/rbi_mpc_2020-12-04/corpus_manifest.json")
    identifier = next(iter(manifest["members"]))
    manifest["members"][identifier]["persona_fields"]["hawk_dove_score"] = -.99
    path.write_bytes(_json_bytes(manifest))
    # The root is the original bundle, so write the deliberately forged manifest
    # inside an isolated copy rather than relaxing source confinement.
    copied = tmp_path / "copied"
    shutil.copytree(executable, copied)
    forged = copied / "forged_corpus_manifest.json"
    shutil.copyfile(path, forged)
    personas = [MemberPersona.model_validate(p) for p in read(copied / "meetings/rbi_mpc_2020-12-04/personas.json")]
    personas[0] = personas[0].model_copy(update={"hawk_dove_score": -.99, "corpus_manifest_hash": file_hash(forged)})
    with pytest.raises(GenerationProvenanceError, match="reconstruction"):
        verify_personas(personas, "2020-12-02", source_root=copied, corpus_manifest_path=forged)


@pytest.mark.parametrize("cutoff", ["2020-12-01", "2020-12-03",
    datetime.fromisoformat("2020-12-02T12:00:00+05:30")])
def test_rolling_cutoff_is_bound_to_frozen_meeting_not_only_future_safe(source_bundle, cutoff):
    _, executable, _ = source_bundle
    with pytest.raises(GenerationProvenanceError, match="cutoff"):
        load_executable_personas(executable, "rbi_mpc_2020-12-04", cutoff=cutoff)


def test_raw_byte_corruption_and_confined_context_fail_closed(source_bundle, tmp_path):
    _, executable, _ = source_bundle
    copied = tmp_path / "copied"
    shutil.copytree(executable, copied)
    manifest = read(copied / "meetings/rbi_mpc_2020-12-04/corpus_manifest.json")
    member = next(iter(manifest["members"].values()))
    source = copied / "rolling_inputs" / member["corpus_sources"][0]["source"]["source_file"]
    source.write_bytes(source.read_bytes() + b"source corruption")
    with pytest.raises(GenerationProvenanceError, match="hash mismatch"):
        load_executable_personas(copied, "rbi_mpc_2020-12-04")
    personas = [MemberPersona.model_validate(p) for p in read(executable / "meetings/rbi_mpc_2020-12-04/personas.json")]
    with pytest.raises(GenerationProvenanceError, match="explicit portable source_root"):
        verify_personas(personas, "2020-12-02", corpus_manifest_path=executable / "meetings/rbi_mpc_2020-12-04/corpus_manifest.json")
    with pytest.raises(GenerationProvenanceError, match="outside source root"):
        verify_personas(personas, "2020-12-02", source_root=tmp_path,
            corpus_manifest_path=executable / "meetings/rbi_mpc_2020-12-04/corpus_manifest.json")


def test_rehashed_same_day_source_cannot_enter_executable_history(source_bundle, tmp_path):
    rolling, _, _ = source_bundle
    copied = tmp_path / "rolling"
    shutil.copytree(rolling, copied)
    packet_file = "packets/rbi_mpc_2020-12-04.json"
    packet = read(copied / packet_file)
    packet["members"][0]["statements"][0]["source"]["publication_date"] = "2020-12-02"
    (copied / packet_file).write_bytes(_json_bytes(packet))
    index = read(copied / "packet_index.json")
    next(row for row in index if row["meeting_id"] == packet["meeting_id"])["packet_sha256"] = file_hash(copied / packet_file)
    (copied / "packet_index.json").write_bytes(_json_bytes(index))
    receipt = read(copied / "receipt.json")
    for name in (packet_file, "packet_index.json"):
        receipt["output_files"][name] = file_hash(copied / name)
    (copied / "receipt.json").write_bytes(_json_bytes(receipt))
    with pytest.raises(ValueError):
        build_executable_rolling_bundle(rolling_root=copied, output_root=tmp_path / "must_not_exist")
    assert not (tmp_path / "must_not_exist").exists()


def test_cached_raw_history_cannot_be_reassigned_to_another_person(source_bundle):
    rolling, _, _ = source_bundle
    packet = read(rolling / "packets/rbi_mpc_2020-12-04.json")
    ref = copy.deepcopy(packet["members"][0]["statements"][0])
    verifier = _RawVerifier(rolling)
    verifier.statement(ref)
    ref.update(member_id="jayanth_varma", original_member_id="jayanth_varma")
    with pytest.raises(ValueError, match="statement identity"):
        verifier.statement(ref)


def test_original_statement_cannot_include_the_next_person_even_after_rehash(source_bundle, tmp_path):
    rolling, _, _ = source_bundle
    copied = tmp_path / "rolling"
    shutil.copytree(rolling, copied)
    packet = read(copied / "packets/rbi_mpc_2020-12-04.json")
    by_person = {m["member_id"]: m["statements"][0] for m in packet["members"]}
    ref = copy.deepcopy(by_person["ashima_goyal"])
    own = copied / ref["statement_file"]
    next_person = copied / by_person["jayanth_varma"]["statement_file"]
    own.write_text(own.read_text() + "\n\n" + next_person.read_text())
    ref["statement_sha256"] = file_hash(own)
    with pytest.raises(ValueError, match="signed-heading boundaries"):
        _RawVerifier(copied).statement(ref)


def test_rehashed_derived_statement_still_requires_raw_dom_reconstruction(source_bundle, tmp_path):
    rolling, _, _ = source_bundle
    copied = tmp_path / "rolling"
    shutil.copytree(rolling, copied)
    packet = read(copied / "packets/rbi_mpc_2024-12-06.json")
    ref = copy.deepcopy(next(member["statements"][0] for member in packet["members"]
                             if member["member_id"] == "nagesh_kumar"))
    path = copied / ref["statement_file"]
    path.write_bytes(path.read_bytes() + b"An invented argument must never become raw-source evidence.\n")
    ref["statement_sha256"] = file_hash(path)
    with pytest.raises(ValueError, match="reconstruct"):
        _RawVerifier(copied).statement(ref)


@pytest.mark.parametrize("field,value", [("predictive_readiness", True),
    ("construct_validated", True), ("model_calls", 1)])
def test_executable_receipt_cannot_relabel_its_evidence(source_bundle, tmp_path, field, value):
    _, executable, _ = source_bundle
    copied = tmp_path / "executable"
    shutil.copytree(executable, copied)
    receipt = read(copied / "receipt.json")
    receipt[field] = value
    (copied / "receipt.json").write_bytes(_json_bytes(receipt))
    with pytest.raises(GenerationProvenanceError, match="Unsupported executable"):
        load_executable_personas(copied, "rbi_mpc_2020-12-04")


def test_legacy_v2_persona_verification_remains_supported():
    import yaml
    directory = ROOT / "personas/calibration_2023-04-30_v2"
    personas = [MemberPersona.model_validate(yaml.safe_load(path.read_text()))
                for path in sorted(directory.glob("*.yaml"))]
    assert len(verify_personas(personas, "2023-05-01")) == 7


def test_panel_audit_enumerates_all_meetings_and_separates_claims(source_bundle):
    rolling, executable, _ = source_bundle
    report = audit_existing_panel(rolling_root=rolling, executable_root=executable)
    assert report["model_calls"] == 0
    assert report["input_failures"] == report["rolling_source_failures"] == report["executable_failures"] == []
    assert report["summary"] == {"meetings_count": 38, "original_macro_meetings": 25,
        "original_truth_meetings": 25, "missing_macro_meetings": 13,
        "missing_history_meetings": 6, "artificial_conditional_simulator_eligible": 23,
        "premeeting_forecasting_eligible": 0, "full_open_economy_comparator_eligible": 0,
        "unsupported_source_stance_meetings": 1}
    rows = {row["decision_date"]: row for row in report["meetings"]}
    assert rows["2020-10-09"]["history"]["status"] == "missing_personal_history"
    assert rows["2020-10-09"]["roster"]["source_bytes_and_roles_verified"] is True
    assert rows["2020-10-09"]["history"]["source_bytes_attribution_and_pre_cutoff_headers_verified"] is True
    assert rows["2020-10-09"]["history"]["historical_first_availability_verified"] is False
    assert rows["2022-05-04"]["history"]["missing_history_member_ids"] == ["rajiv_ranjan"]
    assert rows["2020-12-04"]["eligibility"]["artificial_conditional_simulator"]["eligible"] is True
    assert rows["2024-12-06"]["macro"]["status"] == "missing_macro_snapshot"
    assert rows["2026-10-07"]["stance_compatibility"]["source_stance"] == "calibrated_tightening"
    assert rows["2026-10-07"]["stance_compatibility"]["mapping"] is None
    assert all(row["eligibility"]["premeeting_forecasting"]["eligible"] is False for row in rows.values())
    assert all("cpi_food_yoy_pct" in row["macro"]["missing_fields"] for row in rows.values())
    assert all("cfpi_yoy_pct" in row["macro"]["supplied_fields"] for row in list(rows.values())[:25])


def test_macro_audit_uses_observations_and_detects_source_cutoff_and_missing_evidence(tmp_path):
    row = read(ROOT / "data/processed/vintage_v3/snapshots.json")[0]
    verified = _macro(row, ROOT, required=MINIMUM_MACRO_FIELDS)
    assert verified["status"] == "source_bytes_and_declared_release_cutoffs_verified"
    missing = copy.deepcopy(row)
    missing["observations"] = [item for item in missing["observations"] if item["field"] != "cfpi_yoy_pct"]
    result = _macro(missing, ROOT, required=MINIMUM_MACRO_FIELDS)
    assert "cfpi_yoy_pct" in result["unsupported_or_unbound_fields"]
    future = copy.deepcopy(row)
    future["observations"][0]["released_at"] = row["information_cutoff"]
    assert _macro(future, ROOT, required=MINIMUM_MACRO_FIELDS)["timing_failures"]
    corrupt = copy.deepcopy(row)
    corrupt["observations"][0]["source_sha256"] = "a" * 64
    assert _macro(corrupt, ROOT, required=MINIMUM_MACRO_FIELDS)["source_byte_failures"]
    unknown = copy.deepcopy(row)
    unknown["observations"][0]["field"] = "invented_macro_observation"
    assert "invented_macro_observation" in _macro(unknown, ROOT, required=MINIMUM_MACRO_FIELDS)["unsupported_or_unbound_fields"]
    assert _macro(row, ROOT, required=("output_gap_pct",))["missing_required_fields"] == ["output_gap_pct"]


def test_audit_preserves_failed_bundle_and_never_raises_eligibility_on_corruption(source_bundle, tmp_path):
    rolling, _, _ = source_bundle
    copied = tmp_path / "rolling"
    shutil.copytree(rolling, copied)
    packet = read(copied / "packets/rbi_mpc_2020-12-04.json")
    ref = packet["members"][0]["statements"][0]
    path = copied / ref["statement_file"]
    path.write_bytes(path.read_bytes() + b"corruption")
    report = audit_existing_panel(rolling_root=copied)
    assert report["summary"]["meetings_count"] == 38
    assert report["rolling_source_failures"]
    assert report["summary"]["artificial_conditional_simulator_eligible"] == 0
    assert report["summary"]["premeeting_forecasting_eligible"] == 0
    json.dumps(report, allow_nan=False)
