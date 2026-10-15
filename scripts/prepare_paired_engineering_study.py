"""Freeze selected audited source-linked meetings for engineering integration.

The default uses the earliest eligible meeting solely for a path check. Explicit
meeting selection is recorded and never defines a confirmatory scientific cohort.
All resulting protocols use mock evidence, zero live calls and zero spending.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.run_frozen_study import freeze_study_bundle
from src.infra.evidence import content_hash, file_hash
from src.infra.generation_evidence import strict_json
from src.persona_engine.executable_rolling import load_executable_personas
from src.schemas.debate_schema import InitialStanceOutput, DeliberationOutput, FinalVoteOutput
from src.schemas.macro_schema import MacroMeetingSnapshot


def prepare(output_root, *, executable_root, audit_path, meeting_dates=(), experiment_id="source_linked_engineering"):
    audit_path, executable_root = Path(audit_path).resolve(), Path(executable_root).resolve()
    audit = strict_json(audit_path.read_text())
    if audit.get("model_calls") != 0 or any(audit[key] for key in ("input_failures", "rolling_source_failures", "executable_failures")):
        raise ValueError("Engineering preparation requires a complete zero-generation source audit")
    candidates = [row for row in audit["meetings"] if row["eligibility"]["artificial_conditional_simulator"]["eligible"]]
    selected = set(meeting_dates) if meeting_dates else {candidates[0]["decision_date"]} if candidates else set()
    if not selected or selected - {row["decision_date"] for row in candidates}:
        raise ValueError("Selected meeting missing or ineligible; no substitutions")
    snapshots_file = ROOT / audit["inputs"]["snapshots"]["file"]
    if file_hash(snapshots_file) != audit["inputs"]["snapshots"]["sha256"]:
        raise ValueError("Audited macro inputs changed")
    snapshots = {row["meeting_date"]: row for row in strict_json(snapshots_file.read_text())}
    receipt = strict_json((executable_root / "receipt.json").read_text())
    payloads = {"source_audit.json": audit_path.read_bytes()}
    for name, digest in receipt["output_files"].items():
        path = (executable_root / name).resolve()
        if not path.is_relative_to(executable_root) or file_hash(path) != digest:
            raise ValueError("Executable source bundle changed")
        payloads["persona_inputs/" + name] = path.read_bytes()
    payloads["persona_inputs/receipt.json"] = (executable_root / "receipt.json").read_bytes()
    packets = []
    def ref(name):
        return {"path": name, "sha256": hashlib.sha256(payloads[name]).hexdigest()}
    def collect(observation):
        name = observation.source_file
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or file_hash(path) != observation.source_sha256:
            raise ValueError("Macro source bytes changed")
        payloads["macro_inputs/" + name] = path.read_bytes()
        for child in observation.input_evidence:
            collect(child)
    for row in candidates:
        if row["decision_date"] not in selected:
            continue
        raw = dict(snapshots[row["decision_date"]])
        for name in list(raw):
            if name.startswith("real_"):
                raw.pop(name)
        snapshot = MacroMeetingSnapshot.model_validate(raw)
        personas, context = load_executable_personas(executable_root, row["meeting_id"], cutoff=snapshot.information_cutoff)
        for observation in snapshot.observations:
            collect(observation)
        snapshot_name = "packets/" + row["decision_date"] + "/snapshot.json"
        personas_name = "packets/" + row["decision_date"] + "/personas.json"
        payloads[snapshot_name] = (json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True) + "\n").encode()
        payloads[personas_name] = (json.dumps([p.model_dump(mode="json") for p in personas], indent=2, sort_keys=True) + "\n").encode()
        manifest_name = "persona_inputs/" + str(Path(context["corpus_manifest_path"]).relative_to(executable_root))
        packets.append({"meeting_date": snapshot.meeting_date, "information_cutoff": snapshot.information_cutoff.isoformat(),
            "snapshot": ref(snapshot_name), "personas": ref(personas_name), "corpus_manifest": ref(manifest_name),
            "macro_source_root": "macro_inputs", "persona_source_root": "persona_inputs",
            "governor_id": row["roster"]["governor_id"], "roster_ids": [p.member_id for p in personas],
            "exposure": "exposed_retrospective", "roster_basis": "retrospective_oracle_attendance",
            "history_policy": "complete_dated_history"})
    schemas = {1: InitialStanceOutput, 2: DeliberationOutput, 3: DeliberationOutput, 4: FinalVoteOutput}
    fields = {"experiment_id": experiment_id, "evidence_track": "engineering_mock",
        "prefix_replicates": 1, "governor_draws": 1, "seed_base": 42,
        "settings": {"provider": "mock", "model": "mock", "temperature": 0.6,
            "model_epoch": "source-linked-engineering-v1", "max_output_tokens": 2048,
            "round_schema_hashes": {str(n): content_hash(s.model_json_schema()) for n, s in schemas.items()}},
        "resources": {"max_live_calls": 0, "max_spend_usd": 0.0, "input_token_bound": 65000,
            "output_token_bound": 2048, "max_elapsed_seconds": 1200, "rate_limit_rpm": 10000},
        "meetings": packets,
        "exclusions": [{"meeting_date": row["decision_date"], "reason": "not_selected_for_engineering_integration" if row in candidates else row["eligibility"]["artificial_conditional_simulator"]["blockers"]}
                       for row in audit["meetings"] if row["decision_date"] not in selected]}
    return freeze_study_bundle(output_root, spec_fields=fields, payloads=payloads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable-root", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--meeting-date", action="append", default=[])
    args = parser.parse_args()
    print(prepare(args.output_root, executable_root=args.executable_root, audit_path=args.audit, meeting_dates=args.meeting_date))


if __name__ == "__main__":
    main()
