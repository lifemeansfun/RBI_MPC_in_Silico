"""Zero-generation source and claim eligibility audit of the exposed panel.

Retained-byte integrity, printed release evidence, oracle attendance and
descriptive lexical personas are separate findings.  None demonstrates original
first availability, an authenticated appointment roster, construct validity or
untouched prospective predictive performance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import sys

from src.infra.evidence import file_hash, write_immutable
from src.persona_engine.executable_rolling import _load_rolling, _manifest, MANIFEST_VERSION
from src.persona_engine.rolling_inputs import ROOT, _read_json, source_path, normalized
from src.schemas.decision_space import STANCE_ACTIONS, RATE_ACTIONS_BPS
from src.schemas.macro_schema import MacroMeetingSnapshot, OBSERVABLE_FIELDS, ObservationEvidence, iso_day

MINIMUM_MACRO_FIELDS = ("current_repo_rate_pct", "prev_stance", "cpi_headline_yoy_pct")
OPEN_ECONOMY_FIELDS = ("current_repo_rate_pct", "prev_stance", "cpi_headline_yoy_pct",
                       "output_gap_pct", "us_fed_funds_rate_pct", "usd_inr_exchange_rate",
                       "brent_crude_usd_bbl")


def _error(exc):
    return {"type": type(exc).__name__, "detail": str(exc)}


def _input(root, value):
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Missing or outside source root input: " + str(value))
    return path


def _macro(row, root, *, required, expected_cutoff=None):
    supplied = sorted(name for name in OBSERVABLE_FIELDS if row.get(name) is not None)
    missing = sorted(set(OBSERVABLE_FIELDS) - set(supplied))
    evidence = row.get("observations", [])
    result = {"status": "invalid", "schema": "MacroMeetingSnapshot.observations",
              "supplied_fields": supplied, "missing_fields": missing,
              "missing_required_fields": sorted(set(required) - set(supplied)),
              "unsupported_or_unbound_fields": [], "source_byte_failures": [],
              "timing_failures": [], "schema_failures": [],
              "source_evidence": [], "historical_first_availability_verified": False}
    if not isinstance(evidence, list):
        result["schema_failures"].append({"detail": "observations must be a list"})
        evidence = []
    names = [item.get("field") for item in evidence if isinstance(item, dict)
             and isinstance(item.get("field"), str)]
    result["unsupported_or_unbound_fields"] = sorted(
        set(supplied) ^ {name for name in names if isinstance(name, str)})
    if len(set(names)) != len(names):
        result["schema_failures"].append({"detail": "duplicate observation field identities"})
    try:
        snapshot = MacroMeetingSnapshot.model_validate(row)
        if snapshot.input_track != "source_linked":
            raise ValueError("Macro input is not source_linked")
        if expected_cutoff and snapshot.information_cutoff.isoformat() != expected_cutoff:
            raise ValueError("Macro and roster information cutoffs differ")
    except (ValueError, TypeError, AttributeError) as exc:
        result["schema_failures"].append(_error(exc))
    cutoff = None
    try:
        cutoff = datetime.fromisoformat(row["information_cutoff"])
        if cutoff.tzinfo is None:
            raise ValueError("Macro information cutoff needs a timezone")
    except (KeyError, ValueError, TypeError) as exc:
        result["timing_failures"].append(_error(exc))
    def inspect(item, ancestry=()):
        try:
            observation = ObservationEvidence.model_validate(item)
        except (ValueError, TypeError) as exc:
            result["schema_failures"].append(_error(exc))
            return
        result["source_evidence"].append({"field": observation.field,
            "input_ancestry": list(ancestry), "reference_period": observation.reference_period,
            "units": observation.units, "vintage": observation.vintage,
            "released_at": observation.released_at.isoformat(),
            "availability_basis": observation.availability_basis,
            "source_file": observation.source_file, "source_sha256": observation.source_sha256,
            "source_pointer": observation.source_pointer, "transformation": observation.transformation,
            "timing_status": "repository_transcription_of_retained_release_evidence"})
        try:
            path = source_path(root, observation.source_file)
            if file_hash(path) != observation.source_sha256:
                raise ValueError("Macro source hash mismatch: " + observation.field)
        except (ValueError, OSError) as exc:
            result["source_byte_failures"].append(dict(_error(exc), field=observation.field))
        if cutoff is not None and cutoff.tzinfo is not None and observation.released_at >= cutoff:
            result["timing_failures"].append({"field": observation.field,
                "detail": "release is not strictly before the exclusive information cutoff"})
        for child in item.get("input_evidence", []):
            inspect(child, ancestry + (observation.field,))
    for item in evidence:
        inspect(item)
    if not any(result[key] for key in ("unsupported_or_unbound_fields", "schema_failures",
                                       "source_byte_failures", "timing_failures")):
        result["status"] = "source_bytes_and_declared_release_cutoffs_verified"
    return result


def _truth(row, root):
    result = {"status": "invalid", "failures": [],
              "coding_status": "repository_reported_labels_not_independent_human_validation"}
    try:
        iso_day(row["meeting_date"])
        iso_day(row["publication_date"])
        if row["publication_date"] < row["meeting_date"]:
            raise ValueError("Truth publication predates policy decision")
        if type(row["actual_rate_bps"]) is not int or row["actual_rate_bps"] not in RATE_ACTIONS_BPS:
            raise ValueError("Observed rate action is unsupported by the simulator menu")
        path = source_path(root, row["source_file"])
        if file_hash(path) != row["source_sha256"]:
            raise ValueError("Observed truth source bytes differ from reference")
        from bs4 import BeautifulSoup
        from src.data_pipeline.statement_extractor import StatementExtractor
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        metadata = StatementExtractor.extract_meeting_metadata(soup)
        if (metadata["decision_date"] != row["meeting_date"]
                or metadata["publication_date"] != row["publication_date"]):
            raise ValueError("Observed truth dates differ from retained minutes title/header")
        text = normalized(soup.get_text(" ", strip=True))
        if not row.get("resolution_evidence") or any(normalized(excerpt) not in text
                                                     for excerpt in row["resolution_evidence"]):
            raise ValueError("Observed resolution excerpt missing from retained raw source")
        result["status"] = "source_bytes_and_resolution_excerpt_verified"
    except (KeyError, ValueError, TypeError, OSError) as exc:
        result["failures"].append(_error(exc))
    return result


def _bundle_failures(root):
    failures = []
    try:
        receipt = _read_json(root / "receipt.json")
        for name, digest in receipt.get("output_files", {}).items():
            try:
                if file_hash(source_path(root, name)) != digest:
                    raise ValueError("Rolling output hash mismatch")
            except (ValueError, OSError) as exc:
                failures.append(dict(_error(exc), file=name))
    except (ValueError, TypeError, OSError) as exc:
        failures.append(_error(exc))
    return failures


def audit_existing_panel(*, rolling_root, source_root=ROOT, executable_root=None,
                         snapshots_path="data/processed/vintage_v3/snapshots.json",
                         truth_path="data/processed/vintage_v3/truth.json",
                         required_macro_fields=MINIMUM_MACRO_FIELDS):
    """Return a finite JSON audit; no model or external account is constructed.

    Audit universe is the union of rolling meetings and original macro/truth
    dates. Missing expanded macros and first personal histories remain explicit.
    ``required_macro_fields`` defines the reduced conditional-simulator claim;
    omitted observations remain missing, never invented values. The separate
    full-open-economy and premeeting-forecasting gates are not relaxed by it.
    """
    root, rolling = Path(source_root).resolve(), Path(rolling_root).resolve()
    required = tuple(required_macro_fields)
    if not required or len(set(required)) != len(required) or set(required) - set(OBSERVABLE_FIELDS):
        raise ValueError("Required macro fields must be distinct known observations")
    inputs, input_failures = {}, []
    def read(value, label):
        try:
            path = _input(root, value)
            rows = _read_json(path)
            if not isinstance(rows, list):
                raise ValueError(label + " input must be a list")
            inputs[label] = {"file": str(path.relative_to(root)), "sha256": file_hash(path)}
            return path, rows
        except (ValueError, TypeError, OSError) as exc:
            input_failures.append(dict(_error(exc), input=label))
            return None, []
    snapshots_file, snapshots = read(snapshots_path, "snapshots")
    truth_file, truth_rows = read(truth_path, "truth")
    # The retained panel manifest binds original snapshot/truth transcriptions.
    if snapshots_file and truth_file and snapshots_file.parent == truth_file.parent:
        panel_manifest = snapshots_file.parent / "manifest.json"
        try:
            manifest = _read_json(panel_manifest)
            inputs["panel_manifest"] = {"file": str(panel_manifest.relative_to(root)), "sha256": file_hash(panel_manifest)}
            if (manifest.get("snapshots_sha256") != file_hash(snapshots_file)
                    or manifest.get("truth_sha256") != file_hash(truth_file)):
                raise ValueError("Original macro/truth panel manifest hash mismatch")
        except (ValueError, TypeError, OSError) as exc:
            input_failures.append(dict(_error(exc), input="panel_manifest"))
    source_failures = _bundle_failures(rolling)
    loaded = None
    try:
        loaded = _load_rolling(rolling)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        source_failures.append(_error(exc))
    # Even a corrupt source bundle is enumerated where its index remains readable.
    try:
        packet_index = _read_json(rolling / "packet_index.json")
        roster_values = _read_json(rolling / "realized_rosters.json")
        compatibility = _read_json(rolling / "stance_compatibility_outcomes.json")
    except (ValueError, TypeError, OSError) as exc:
        source_failures.append(_error(exc))
        packet_index, roster_values, compatibility = [], [], []
    def unique_rows(rows, key, label):
        counts = Counter(row.get(key) for row in rows if isinstance(row, dict)
                         and isinstance(row.get(key), str))
        duplicates = sorted(str(identity) for identity, count in counts.items() if count != 1)
        if duplicates:
            input_failures.append({"input": label, "detail": "duplicated identities", "identities": duplicates})
        return {row[key]: row for row in rows if isinstance(row, dict) and isinstance(row.get(key), str)
                and counts[row[key]] == 1}
    macro_by_day = unique_rows(snapshots, "meeting_date", "snapshots")
    truth_by_day = unique_rows(truth_rows, "meeting_date", "truth")
    index = unique_rows(packet_index, "meeting_id", "rolling_index")
    rosters = unique_rows(roster_values, "meeting_id", "rolling_rosters")
    stance_by_meeting = unique_rows(compatibility, "meeting_id", "source_stance_compatibility")
    identities = sorted(set(index) | set(rosters) | {"rbi_mpc_" + day for day in macro_by_day}
                        | {"rbi_mpc_" + day for day in truth_by_day})
    executable_failures, executable = [], {}
    if executable_root is not None:
        executable_path = Path(executable_root).resolve()
        executable_failures = _bundle_failures(executable_path)
        try:
            receipt = _read_json(executable_path / "receipt.json")
            if (receipt.get("version") != "rolling-executable-receipt-v1"
                    or receipt.get("model_calls") != 0
                    or receipt.get("predictive_readiness") is not False
                    or receipt.get("construct_validated") is not False):
                raise ValueError("Unsupported executable persona receipt")
            copied = _load_rolling(executable_path / "rolling_inputs")
            if file_hash(rolling / "receipt.json") != receipt.get("source_receipt_sha256"):
                raise ValueError("Executable corpus originates from a different rolling bundle")
            for row in _read_json(executable_path / "index.json"):
                expected = _manifest(copied, row["meeting_id"])
                path = source_path(executable_path, row["corpus_manifest_file"])
                actual = _read_json(path)
                values = _read_json(source_path(executable_path, row["personas_file"]))
                expected_personas = [dict(member["persona_fields"], corpus_manifest_hash=file_hash(path))
                    for member in expected["members"].values() if member["persona_fields"] is not None]
                if (actual != expected or values != expected_personas
                        or file_hash(path) != row["corpus_manifest_sha256"]):
                    raise ValueError("Executable corpus/persona fields differ from raw-byte reconstruction")
                executable[row["meeting_id"]] = {"status": "reconstructed_fields_and_corpus_hash_verified",
                    "corpus_manifest_sha256": file_hash(path), "version": MANIFEST_VERSION,
                    "complete_roster": not actual["missing_history_member_ids"]}
        except (ValueError, TypeError, KeyError, OSError) as exc:
            executable_failures.append(_error(exc))
    meetings = []
    for meeting_id in identities:
        day, roster = meeting_id.removeprefix("rbi_mpc_"), rosters.get(meeting_id)
        packet_row = index.get(meeting_id)
        macro_row, truth_row = macro_by_day.get(day), truth_by_day.get(day)
        cutoff = roster.get("information_cutoff") if roster else None
        history_counts = packet_row.get("history_counts", {}) if packet_row else {}
        missing_history = packet_row.get("missing_history_member_ids", []) if packet_row else []
        history_status = "unavailable" if not packet_row else (
            "missing_personal_history" if missing_history else "complete_personal_histories")
        macro = _macro(macro_row, root, required=required, expected_cutoff=cutoff) if macro_row else {
            "status": "missing_macro_snapshot", "missing_fields": list(OBSERVABLE_FIELDS),
            "missing_required_fields": list(required), "supplied_fields": [],
            "source_byte_failures": [], "timing_failures": [], "schema_failures": [],
            "unsupported_or_unbound_fields": []}
        truth = _truth(truth_row, root) if truth_row else {"status": "not_supplied_in_original_truth_panel"}
        source_stance = truth_row.get("actual_stance") if truth_row else stance_by_meeting.get(meeting_id, {}).get("source_stance")
        stance = {"source_stance": source_stance, "simulator_ontology": "simulator_v1",
                  "source_stance_supported": source_stance in STANCE_ACTIONS if source_stance else None,
                  "prev_stance_supported": macro_row.get("prev_stance") in STANCE_ACTIONS if macro_row else None,
                  "mapping": None}
        blockers = []
        if input_failures:
            blockers.append("original_panel_input_or_manifest_integrity_failure")
        if source_failures:
            blockers.append("rolling_source_byte_timing_or_semantic_verification_failure")
        if not roster or not packet_row:
            blockers.append("missing_realized_roster_or_rolling_packet")
        if not packet_row or missing_history:
            blockers.append("missing_personal_history_no_substitution")
        if macro["status"] != "source_bytes_and_declared_release_cutoffs_verified":
            blockers.append("macro_snapshot_missing_or_unverified")
        if macro["missing_required_fields"]:
            blockers.append("required_macro_observations_missing")
        if stance["source_stance_supported"] is False or stance["prev_stance_supported"] is False:
            blockers.append("unsupported_source_stance_no_mapping")
        if executable_root is not None and (executable_failures or meeting_id not in executable):
            blockers.append("executable_persona_bundle_unverified")
        forecasting_blockers = blockers + ["realized_attendance_is_oracle_not_pre_cutoff_appointment_evidence",
            "historical_first_availability_not_authenticated", "persona_construct_validation_absent",
            "panel_already_exposed_retrospective"]
        open_missing = sorted(set(OPEN_ECONOMY_FIELDS) - set(macro["supplied_fields"]))
        meetings.append({"meeting_id": meeting_id, "decision_date": day,
            "meeting_start_date": roster.get("meeting_start_date") if roster else None,
            "information_cutoff": cutoff, "panel_status": "exposed_retrospective",
            "macro": macro, "truth": truth, "stance_compatibility": stance,
            "roster": {"status": roster.get("roster_evidence_status") if roster else "missing",
                "source_bytes_and_roles_verified": loaded is not None and not source_failures,
                "roster_available_at_cutoff": False, "appointment_evidence": "absent",
                "member_ids": [member["member_id"] for member in roster.get("members", [])] if roster else [],
                "governor_id": roster.get("governor_id") if roster else None},
            "history": {"status": history_status, "counts": history_counts,
                "missing_history_member_ids": missing_history, "construct_validated": False,
                "source_bytes_attribution_and_pre_cutoff_headers_verified": loaded is not None and not source_failures,
                "historical_first_availability_verified": False,
                "unverified_counts_status": None if loaded is not None else "repository_index_reported_unverified"},
            "executable_personas": executable.get(meeting_id, {"status": "not_requested" if executable_root is None else "unverified"}),
            "eligibility": {"artificial_conditional_simulator": {"eligible": not blockers,
                "blockers": blockers, "claim_scope": "simulator-local intervention conditional on retrospective realized attendance and supplied reduced macro observations"},
                "premeeting_forecasting": {"eligible": False, "blockers": forecasting_blockers},
                "full_open_economy_comparator": {"eligible": not blockers and not open_missing,
                    "missing_required_fields": open_missing},
                "observed_policy_comparison": {"eligible": not blockers and truth["status"] == "source_bytes_and_resolution_excerpt_verified",
                    "coding_status": "repository_reported_unvalidated"}}})
    report = {"version": "existing-panel-eligibility-audit-v1", "model_calls": 0,
        "audited_at": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
        "required_macro_fields": list(required), "input_failures": input_failures,
        "rolling_receipt_sha256": file_hash(rolling / "receipt.json") if (rolling / "receipt.json").is_file() else None,
        "rolling_source_failures": source_failures, "executable_failures": executable_failures,
        "meetings": meetings, "summary": {"meetings_count": len(meetings),
            "original_macro_meetings": len(macro_by_day), "original_truth_meetings": len(truth_by_day),
            "missing_macro_meetings": sum(m["macro"]["status"] == "missing_macro_snapshot" for m in meetings),
            "missing_history_meetings": sum(m["history"]["status"] != "complete_personal_histories" for m in meetings),
            "artificial_conditional_simulator_eligible": sum(m["eligibility"]["artificial_conditional_simulator"]["eligible"] for m in meetings),
            "premeeting_forecasting_eligible": 0,
            "full_open_economy_comparator_eligible": sum(m["eligibility"]["full_open_economy_comparator"]["eligible"] for m in meetings),
            "unsupported_source_stance_meetings": sum(m["stance_compatibility"]["source_stance_supported"] is False for m in meetings)},
        "environment": {"python": sys.version, "platform": platform.platform()},
        "code_sha256": {"eligibility_audit.py": file_hash(__file__)},
        "evidence_limit": "Byte checks and declared/printed release evidence do not authenticate historical first availability. Repository labels and lexical personas lack independent human coding/construct validation. All supplied outcomes are exposed retrospective evidence."}
    # Explicit finite serialization guard for downstream immutable run records.
    json.dumps(report, allow_nan=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rolling-root", required=True)
    parser.add_argument("--source-root", default=str(ROOT))
    parser.add_argument("--executable-root")
    parser.add_argument("--snapshots-path", default="data/processed/vintage_v3/snapshots.json")
    parser.add_argument("--truth-path", default="data/processed/vintage_v3/truth.json")
    parser.add_argument("--output-file", required=True)
    args = parser.parse_args()
    report = audit_existing_panel(rolling_root=args.rolling_root, source_root=args.source_root,
        executable_root=args.executable_root, snapshots_path=args.snapshots_path, truth_path=args.truth_path)
    write_immutable(args.output_file, report)
    print(json.dumps(report["summary"], sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
