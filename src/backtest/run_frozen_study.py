"""Validate or execute an explicit portable paired study; default is zero calls.

Use ``--execution mock`` only for engineering evidence. Live research requires
retained readiness/accounting receipts and an existing reconciled shared ledger.
No constructor may initialize an absent ledger during live preflight. Every
planned branch survives in the denominator on interruption or scientific failure.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
from importlib.metadata import version, PackageNotFoundError
from datetime import datetime, timezone
from itertools import permutations
import json
import platform
from pathlib import Path
import sqlite3
import sys
import time

from src.infra.evidence import content_hash, file_hash, write_immutable
from src.infra.exceptions import GenerationProvenanceError, BudgetLedgerError
from src.infra.generation_evidence import strict_json
from src.schemas.frozen_study_schema import StudySpec
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.schemas.decision_space import RATE_ACTIONS_BPS, STANCE_ACTIONS
from src.persona_engine.provenance import verify_personas

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_READINESS = {"contribution", "source_and_ontology", "precision_and_resources", "preregistration"}


def _code_names(root):
    names = {str(p.relative_to(root)) for folder in ("src", "scripts") for p in (root / folder).rglob("*.py")}
    names |= {name for name in ("Makefile", "config/config.yaml", "requirements.txt", "requirements-lock.txt") if (root / name).is_file()}
    return sorted(names)


def _runtime_root(code_root):
    if Path(code_root).resolve() != ROOT.resolve():
        raise GenerationProvenanceError("Validated code root must be the executing module tree; launch the portable code in a fresh process")
    for name, module in list(sys.modules.items()):
        if name.startswith("src.") and getattr(module, "__file__", None):
            if not Path(module.__file__).resolve().is_relative_to(ROOT):
                raise GenerationProvenanceError("Loaded research module comes from a different code tree")


def dependency_environment():
    installed, mismatches = {}, []
    lock = ROOT / "requirements-lock.txt"
    if lock.is_file():
        for line in lock.read_text().splitlines():
            if "==" not in line or line.startswith("#"):
                continue
            name, expected = line.split("==", 1)
            try:
                actual = version(name)
            except PackageNotFoundError:
                actual = None
            installed[name] = actual
            if actual != expected:
                mismatches.append({"package": name, "locked": expected, "installed": actual})
    return {"installed_locked_packages": installed, "lock_mismatches": mismatches,
            "clean_install_verified": False, "limit": "Version reconciliation does not prove a clean installation"}


def _path(root, name):
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise GenerationProvenanceError("Frozen path escapes portable root")
    return path


def _seal(document):
    return {**document, "artifact_content_hash": content_hash(document)}


def _json(path):
    return strict_json(Path(path).read_text(encoding="utf-8"))


def read_spec(protocol_path):
    document = _json(protocol_path)
    if document.get("artifact_content_hash") != content_hash({k: v for k, v in document.items() if k != "artifact_content_hash"}):
        raise GenerationProvenanceError("Frozen protocol hash mismatch")
    return StudySpec.model_validate_json(json.dumps(document, allow_nan=False))


def freeze_study_bundle(output_root, *, spec_fields, payloads, code_root=ROOT):
    """Freeze caller-selected inputs and the entire current executable source.

    This records selection; it never decides a cohort or certifies human review.
    Payload paths cover every linked source byte needed for portable validation.
    An unused destination is compulsory, including for fixtures.
    """
    out = Path(output_root).resolve()
    if out.exists():
        raise FileExistsError("Frozen bundle destination must be unused")
    code_root = Path(code_root).resolve()
    code_names = _code_names(code_root)
    code_payloads = {name: _path(code_root, name).read_bytes() for name in code_names}
    files = []
    for name, payload in sorted(payloads.items()):
        _path(out, name)
        if name == "protocol.json" or name == "code" or name.startswith("code/") or not isinstance(payload, bytes):
            raise ValueError("Reserved input path or non-byte frozen input")
        files.append({"path": name, "sha256": hashlib.sha256(payload).hexdigest()})
    code_files = [{"path": name, "sha256": hashlib.sha256(payload).hexdigest()} for name, payload in sorted(code_payloads.items())]
    document = _seal({**spec_fields, "files": files, "code_files": code_files})
    StudySpec.model_validate_json(json.dumps(document, allow_nan=False))
    out.mkdir(parents=True, exist_ok=False)
    for name, payload in {**payloads, **{"code/" + k: v for k, v in code_payloads.items()}}.items():
        path = _path(out, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(payload)
    write_immutable(out / "protocol.json", document)
    return out / "protocol.json"


def create_engineering_fixture(output_root, *, experiment_id="paired_engineering_fixture", code_root=ROOT):
    """An explicit artificial committee, never a source-eligible research cohort."""
    from src.schemas.debate_schema import InitialStanceOutput, DeliberationOutput, FinalVoteOutput
    schemas = {1: InitialStanceOutput, 2: DeliberationOutput, 3: DeliberationOutput, 4: FinalVoteOutput}
    personas = [MemberPersona(member_id="fixture_" + str(i), name="Fixture member " + str(i),
        role="Governor" if i == 0 else "Artificial committee member", is_internal=i < 3,
        tenure="Engineering fixture", hawk_dove_score=0.0, voting_priority="Engineering fixture") for i in range(6)]
    snapshot = MacroMeetingSnapshot(meeting_date="2023-08-10", meeting_start_date="2023-08-08",
        information_cutoff="2023-08-08T00:00:00+05:30", input_track="synthetic",
        current_repo_rate_pct=6.5, cpi_headline_yoy_pct=5.4)
    payloads = {"inputs/snapshot.json": (json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, indent=2) + "\n").encode(),
                "inputs/personas.json": (json.dumps([p.model_dump(mode="json") for p in personas], sort_keys=True, indent=2) + "\n").encode()}
    fields = {"experiment_id": experiment_id, "evidence_track": "engineering_mock", "prefix_replicates": 1,
        "governor_draws": 2, "seed_base": 42,
        "settings": {"provider": "mock", "model": "mock", "temperature": 0.6,
                     "model_epoch": "engineering-fixture-v1", "max_output_tokens": 2048,
                     "round_schema_hashes": {str(n): content_hash(s.model_json_schema()) for n, s in schemas.items()}},
        "resources": {"max_live_calls": 0, "max_spend_usd": 0.0, "input_token_bound": 65000,
                      "output_token_bound": 2048, "max_elapsed_seconds": 120, "rate_limit_rpm": 10000},
        "meetings": [{"meeting_date": snapshot.meeting_date, "information_cutoff": snapshot.information_cutoff.isoformat(),
            "snapshot": {"path": "inputs/snapshot.json", "sha256": hashlib.sha256(payloads["inputs/snapshot.json"]).hexdigest()},
            "personas": {"path": "inputs/personas.json", "sha256": hashlib.sha256(payloads["inputs/personas.json"]).hexdigest()},
            "governor_id": personas[0].member_id, "roster_ids": [p.member_id for p in personas],
            "exposure": "engineering_fixture", "roster_basis": "engineering_fixture", "history_policy": "engineering_fixture"}]}
    return freeze_study_bundle(output_root, spec_fields=fields, payloads=payloads, code_root=code_root)


def planned_schedule(spec):
    from src.behavioral.paired_prefix import prefix_identity, branch_identity
    rows = []
    orders = list(permutations(("H", "B", "N")))
    position = 0
    for meeting in spec.meetings:
        for replicate in range(1, spec.prefix_replicates + 1):
            prefix_id = prefix_identity(spec.experiment_id, meeting.meeting_date, replicate)
            for draw in range(1, spec.governor_draws + 1):
                for condition in orders[position % len(orders)]:
                    rows.append({"experiment_id": spec.experiment_id, "meeting_date": meeting.meeting_date,
                                 "replicate_id": replicate, "prefix_id": prefix_id,
                                 "branch_draw_id": str(draw), "condition": condition,
                                 "branch_id": branch_identity(prefix_id, condition, str(draw))})
                position += 1
    return rows


def validate_inputs(spec, bundle_root, *, code_root=ROOT):
    _runtime_root(code_root)
    bundle_root, code_root = Path(bundle_root).resolve(), Path(code_root).resolve()
    for ref in spec.files:
        if file_hash(_path(bundle_root, ref.path)) != ref.sha256:
            raise GenerationProvenanceError("Frozen input hash mismatch: " + ref.path)
    actual_code = set(_code_names(code_root))
    if actual_code != {ref.path for ref in spec.code_files}:
        raise GenerationProvenanceError("Frozen executable code file set changed")
    for ref in spec.code_files:
        if file_hash(_path(code_root, ref.path)) != ref.sha256 or file_hash(_path(bundle_root / "code", ref.path)) != ref.sha256:
            raise GenerationProvenanceError("Frozen code/config hash mismatch: " + ref.path)
    loaded = []
    for packet in spec.meetings:
        snapshot = MacroMeetingSnapshot.model_validate(_json(_path(bundle_root, packet.snapshot.path)))
        personas = [MemberPersona.model_validate(value) for value in _json(_path(bundle_root, packet.personas.path))]
        if (snapshot.meeting_date != packet.meeting_date or snapshot.information_cutoff is None
                or snapshot.information_cutoff.isoformat() != packet.information_cutoff
                or [p.member_id for p in personas] != list(packet.roster_ids)):
            raise GenerationProvenanceError("Packet date/cutoff/roster differs from retained inputs")
        if any(getattr(snapshot, name) not in (None, []) for name in type(snapshot).model_fields if name.startswith("real_")):
            raise GenerationProvenanceError("Outcome labels are forbidden in experimental macro packets")
        macro_root = _path(bundle_root, packet.macro_source_root)
        context = {}
        if snapshot.input_track == "source_linked":
            snapshot.verify_sources(root=macro_root)
            # Match the exclusive conservative local start-day cutoff.
            start = datetime.fromisoformat(snapshot.meeting_start_date + "T00:00:00+05:30")
            if snapshot.information_cutoff != start:
                raise GenerationProvenanceError("Snapshot must use exclusive start-day midnight IST")
        elif spec.evidence_track != "engineering_mock":
            raise GenerationProvenanceError("Research macro inputs must be source linked")
        if packet.corpus_manifest:
            context = {"source_root": str(_path(bundle_root, packet.persona_source_root)),
                       "corpus_manifest_path": str(_path(bundle_root, packet.corpus_manifest.path))}
            verify_personas(personas, snapshot.information_cutoff, **context)
            manifest = _json(context["corpus_manifest_path"])
            if manifest.get("roster_evidence_status") != packet.roster_basis:
                raise GenerationProvenanceError("Roster claim differs from retained source evidence")
        elif spec.evidence_track != "engineering_mock":
            raise GenerationProvenanceError("Research persona manifest absent")
        loaded.append((packet, snapshot, personas, context, macro_root))
    return loaded


def scientific_recipe_hash(spec):
    """Bind external receipts to inputs/code/design without a circular file hash."""
    core = spec.model_dump(mode="json")
    receipt_names = {r.path for r in spec.readiness_receipts.values()}
    if spec.resources.accounting_receipt:
        receipt_names.add(spec.resources.accounting_receipt.path)
    core.pop("artifact_content_hash")
    core.pop("readiness_receipts")
    core["resources"].pop("accounting_receipt")
    core["files"] = [ref for ref in core["files"] if ref["path"] not in receipt_names]
    return content_hash(core)


def live_preflight(spec, bundle_root):
    """Read-only resource and readiness audit before any LLM/ledger constructor."""
    from src.infra.cost_governor import PRICE_REVISION, _cost_nanos
    if spec.evidence_track != "registered_simulator_study" or spec.settings.provider == "mock":
        raise GenerationProvenanceError("Live execution requires a distinct registered research protocol")
    resources = spec.resources
    if resources.max_live_calls < spec.planned_generation_calls or resources.max_spend_usd <= 0:
        raise BudgetLedgerError("Frozen live call/dollar allowance cannot cover planned schedule")
    if (resources.max_token_count_requests < spec.planned_generation_calls
            or resources.max_provider_requests < 2 * spec.planned_generation_calls):
        raise BudgetLedgerError("Frozen provider-request allowance must cover input counting and generation")
    if spec.planned_generation_calls * 60 / resources.rate_limit_rpm > resources.max_elapsed_seconds:
        raise BudgetLedgerError("Frozen wall-clock allowance is below pacing floor")
    if not spec.settings.allowed_served_models:
        raise GenerationProvenanceError("Provider revision/alias drift policy is absent")
    if set(spec.readiness_receipts) != REQUIRED_READINESS:
        raise GenerationProvenanceError("Scientific readiness receipts are incomplete")
    recipe_hash = scientific_recipe_hash(spec)
    for gate, ref in spec.readiness_receipts.items():
        if file_hash(_path(bundle_root, ref.path)) != ref.sha256:
            raise GenerationProvenanceError("Readiness receipt bytes differ from frozen manifest")
        receipt = _json(_path(bundle_root, ref.path))
        if (receipt.get("gate") != gate or receipt.get("status") != "passed"
                or receipt.get("experiment_id") != spec.experiment_id or receipt.get("scientific_recipe_hash") != recipe_hash
                or not receipt.get("reviewer")
                or not receipt.get("evidence") or not receipt.get("limitations")):
            raise GenerationProvenanceError("Incomplete externally assessed readiness receipt: " + gate)
        if gate == "preregistration" and not receipt.get("external_timestamp_url"):
            raise GenerationProvenanceError("Local hash alone cannot establish registration timing")
    if resources.accounting_receipt is None or resources.ledger_path is None or resources.ledger_cap_usd is None:
        raise BudgetLedgerError("Missing authenticated allowance reconciliation and existing shared ledger")
    if file_hash(_path(bundle_root, resources.accounting_receipt.path)) != resources.accounting_receipt.sha256:
        raise BudgetLedgerError("Accounting receipt bytes differ from frozen manifest")
    account = _json(_path(bundle_root, resources.accounting_receipt.path))
    ledger = Path(resources.ledger_path).resolve()
    if (account.get("status") != "externally_reconciled" or account.get("scientific_recipe_hash") != recipe_hash
            or not account.get("provider_account_evidence")
            or not account.get("authorization_evidence") or account.get("ledger_path") != str(ledger)
            or account.get("price_revision") != PRICE_REVISION
            or type(account.get("remaining_allowance_usd")) not in (float, int)
            or account["remaining_allowance_usd"] < resources.max_spend_usd
            or account.get("requests_available", 0) < 2 * spec.planned_generation_calls
            or account.get("request_quota_definition") != "generation_plus_token_count_conservative_bound"):
        raise BudgetLedgerError("Accounting, authorization, tariff or actual quota reconciliation incomplete")
    marker = ledger.with_name(ledger.name + ".initialized.json")
    if not ledger.is_file() or not marker.is_file():
        raise BudgetLedgerError("Absent ledger cannot be initialized to manufacture an allowance")
    marker_data = _json(marker)
    cap = __import__("src.infra.cost_governor", fromlist=["_nanos"])._nanos(resources.ledger_cap_usd)
    if marker_data != {"ledger_filename": ledger.name, "cap_nanos": cap, "schema_version": 1}:
        raise BudgetLedgerError("Existing ledger initialization/cap differs")
    try:
        with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as conn:
            config = conn.execute("SELECT cap_nanos,schema_version FROM budget_config WHERE id=1").fetchone()
            pending = conn.execute("SELECT COUNT(*) FROM reservations WHERE state IN ('reserved','submitted','uncertain')").fetchone()[0]
            spent = conn.execute("SELECT COALESCE(SUM(actual_nanos),0) FROM reservations WHERE state='committed'").fetchone()[0]
            if config != (cap, 1) or pending:
                raise BudgetLedgerError("Existing ledger is changed or has unresolved charges")
    except sqlite3.Error as error:
        raise BudgetLedgerError("Existing ledger schema is unreadable; accounting not reset") from error
    bound = spec.planned_generation_calls * _cost_nanos(spec.settings.model, resources.input_token_bound, resources.output_token_bound)
    if bound > int(resources.max_spend_usd * 1e9) or bound + spent > cap:
        raise BudgetLedgerError("Conservative planned token cost exceeds reconciled allowance")
    return {"existing_ledger": str(ledger), "planned_cost_bound_usd": bound / 1e9,
            "provider_request_upper_bound": 2 * spec.planned_generation_calls,
            "prior_estimated_spend_usd": spent / 1e9,
            "readiness_limit": "Byte/structure checks do not independently authenticate human assessments or account statements"}


class _BoundedClient:
    def __init__(self, client, spec):
        self.client, self.spec = client, spec
        self.provider, self.cfg, self.cache_enabled = client.provider, client.cfg, False
        self.calls = 0
        self.started = time.monotonic()

    async def generate_with_metadata(self, *args, **kwargs):
        elapsed = time.monotonic() - self.started
        remaining = self.spec.resources.max_elapsed_seconds - elapsed
        ceiling = self.spec.planned_generation_calls if self.provider == "mock" else self.spec.resources.max_live_calls
        if remaining <= 0 or self.calls >= ceiling:
            raise BudgetLedgerError("Frozen call or wall-clock budget exhausted")
        self.calls += 1
        if self.provider != "mock":
            kwargs["input_token_bound"] = self.spec.resources.input_token_bound
        result = await asyncio.wait_for(self.client.generate_with_metadata(*args, **kwargs), timeout=remaining)
        if self.provider != "mock" and result.metadata.served_model not in self.spec.settings.allowed_served_models:
            raise GenerationProvenanceError("Provider reported model changed; stop affected epoch")
        return result


def _analysis(schedule, prefixes, branches, menu):
    from src.validation.paired_consensus import analyze_pairs
    return {"B_minus_H": analyze_pairs(schedule, prefixes, branches, allowed_labels=menu),
            "B_minus_N": analyze_pairs(schedule, prefixes, branches, allowed_labels=menu, contrast=("B", "N"))}


def _artifact_analysis(schedule, evidence_root, menu, *, spec, loaded):
    from src.validation.paired_consensus import reconstruct_from_artifacts
    prefix_paths = sorted(Path(evidence_root).rglob("shared_prefix.json"))
    branch_paths = sorted(Path(evidence_root).rglob("branch_outcome.json")) + sorted(Path(evidence_root).rglob("branch_failure.json"))
    expected = {packet.meeting_date: (packet, snapshot, personas) for packet, snapshot, personas, _, _ in loaded}
    settings = spec.settings.model_dump(exclude={"allowed_served_models"})
    for path in prefix_paths:
        prefix = _checked_document(path)
        if prefix["meeting_date"] not in expected:
            raise GenerationProvenanceError("Retained prefix meeting absent from protocol")
        packet, snapshot, personas = expected[prefix["meeting_date"]]
        if (prefix["snapshot_hash"] != content_hash(snapshot.model_dump(mode="json"))
                or prefix["persona_hash"] != content_hash([p.model_dump(mode="json") for p in personas])
                or prefix["roster_ids"] != list(packet.roster_ids) or prefix["governor_id"] != packet.governor_id
                or prefix["generation_settings"] != settings or prefix["generation_settings_hash"] != content_hash(settings)
                or prefix["seed_base"] != spec.seed_base):
            raise GenerationProvenanceError("Retained prefix differs from ex ante frozen inputs/settings")
        for receipt in prefix["transcripts"].values():
            transcript = _json(_path(path.parent, receipt["path"]))
            if transcript["generation"]["request_identity"].get("protocol_hash") != spec.artifact_content_hash:
                raise GenerationProvenanceError("Prefix request differs from ex ante protocol identity")
    for path in branch_paths:
        branch = _checked_document(path)
        if branch["status"] == "complete":
            transcript = _json(_path(path.parent, branch["governor_transcript"]["path"]))
            if transcript["generation"]["request_identity"].get("protocol_hash") != spec.artifact_content_hash:
                raise GenerationProvenanceError("Branch request differs from ex ante protocol identity")
    return {"B_minus_H": reconstruct_from_artifacts(schedule, prefix_paths, branch_paths, allowed_labels=menu),
            "B_minus_N": reconstruct_from_artifacts(schedule, prefix_paths, branch_paths, allowed_labels=menu, contrast=("B", "N"))}


def _checked_document(path):
    document = _json(path)
    if document.get("artifact_content_hash") != content_hash({k: v for k, v in document.items() if k != "artifact_content_hash"}):
        raise GenerationProvenanceError("Retained study artifact hash mismatch")
    return document


def replay_study(protocol_path, retained_root, output_root, *, code_root=ROOT):
    """Independent saved-output reconstruction; no LLM client or ledger exists."""
    out, retained = Path(output_root).resolve(), Path(retained_root).resolve()
    if out.exists():
        raise FileExistsError("Replay output must be unused")
    spec = read_spec(protocol_path)
    loaded = validate_inputs(spec, Path(protocol_path).resolve().parent, code_root=code_root)
    schedule = planned_schedule(spec)
    retained_schedule = _checked_document(retained / "planned_schedule.json")
    if retained_schedule["protocol_hash"] != spec.artifact_content_hash or retained_schedule["planned"] != schedule:
        raise GenerationProvenanceError("Retained schedule differs from frozen protocol")
    menu = [{"vote": rate, "stance": stance} for rate in RATE_ACTIONS_BPS for stance in STANCE_ACTIONS]
    analysis = _artifact_analysis(schedule, retained / "generations", menu, spec=spec, loaded=loaded)
    saved = retained / "analysis.json"
    if saved.is_file() and analysis != {k: v for k, v in _checked_document(saved).items() if k != "artifact_content_hash"}:
        raise GenerationProvenanceError("Independent replay differs from reported analysis")
    out.mkdir(parents=True, exist_ok=False)
    write_immutable(out / "analysis.json", _seal(analysis))
    result = {"status": "replayed", "evidence_type": "deterministic_artifact_replay",
              "source_evidence_track": spec.evidence_track, "actual_generation_calls": 0,
              "protocol_hash": spec.artifact_content_hash,
              "scientific_readiness": "not_established_by_saved_output_replay"}
    write_immutable(out / "replay_receipt.json", _seal(result))
    return result


async def run_study(protocol_path, output_root, *, execution="validate", code_root=ROOT):
    protocol_path, out = Path(protocol_path).resolve(), Path(output_root).resolve()
    if out.exists():
        raise FileExistsError("Execution output must be unused; retained attempts cannot be reset")
    if execution not in ("validate", "mock", "live"):
        raise ValueError("Execution must be validate, mock or live; use replay_study for retained evidence")
    out.mkdir(parents=True, exist_ok=False)
    schedule, prefixes, branches = [], [], []
    client = None
    try:
        _runtime_root(code_root)
        environment = dependency_environment()
        write_immutable(out / "execution_environment.json", {"command": sys.argv, "python": sys.version,
                        "python_executable": sys.executable, "platform": platform.platform(),
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "execution": execution, "protocol_file_sha256": file_hash(protocol_path), **environment})
        spec = read_spec(protocol_path)
        schedule = planned_schedule(spec)
        write_immutable(out / "planned_schedule.json", _seal({"protocol_hash": spec.artifact_content_hash, "planned": schedule}))
        loaded = validate_inputs(spec, protocol_path.parent, code_root=code_root)
        report = {"status": "validated", "protocol_hash": spec.artifact_content_hash,
                  "planned_generation_calls": spec.planned_generation_calls, "actual_generation_calls": 0,
                  "evidence_track": spec.evidence_track, "scientific_readiness": "not_established_by_engineering_validation",
                  "meetings": len(loaded), "input_files": len(spec.files), "code_files": len(spec.code_files)}
        if execution == "validate":
            write_immutable(out / "validation.json", _seal(report))
            return report
        if execution == "mock" and spec.evidence_track != "engineering_mock":
            raise GenerationProvenanceError("Mock cannot substitute for frozen research provider")
        if execution == "live" and environment["lock_mismatches"]:
            raise GenerationProvenanceError("Installed package versions differ from frozen lock")
        preflight = live_preflight(spec, protocol_path.parent) if execution == "live" else {"provider_spend_usd": 0}
        write_immutable(out / "preflight.json", _seal(preflight))
        # This import/construction happens only after all zero-generation gates.
        from src.infra.llm_client import LLMClient
        from src.infra.transcript_logger import TranscriptLogger
        from src.behavioral.debate_orchestrator import DebateOrchestrator
        from src.behavioral.paired_prefix import PairedPrefixOrchestrator
        governor = None
        if execution == "live":
            from src.infra.cost_governor import CostGovernor
            governor = CostGovernor(spec.resources.ledger_cap_usd, spec.resources.ledger_path)
        raw_client = LLMClient(provider=spec.settings.provider, cache_enabled=False, governor=governor)
        raw_client.cfg = raw_client.cfg.model_copy(deep=True)
        raw_client.cfg.run.max_output_tokens = spec.settings.max_output_tokens
        raw_client.cfg.run.model_epoch = spec.settings.model_epoch
        raw_client._min_interval = 60 / spec.resources.rate_limit_rpm
        client = _BoundedClient(raw_client, spec)
        logger = TranscriptLogger(run_id="frozen_execution", output_root=out / "generations",
                                  identity={"experiment_id": spec.experiment_id, "protocol_hash": spec.artifact_content_hash})
        orchestrator = DebateOrchestrator(client, logger)
        settings = orchestrator.generation_settings(model=spec.settings.model, temperature=spec.settings.temperature)
        if settings != spec.settings.model_dump(exclude={"allowed_served_models"}):
            raise GenerationProvenanceError("Runtime settings/schema differ from frozen protocol")
        adapter = PairedPrefixOrchestrator(orchestrator)
        for packet, snapshot, personas, context, macro_root in loaded:
            for replicate in range(1, spec.prefix_replicates + 1):
                prefix = await adapter.generate_shared_prefix(snapshot, personas, packet.governor_id,
                    experiment_id=spec.experiment_id, replicate_id=replicate, seed=spec.seed_base,
                    model=spec.settings.model, temperature=spec.settings.temperature,
                    persona_verification_context=context, source_root=macro_root)
                prefixes.append(prefix.to_dict())
                write_immutable(out / (prefix.prefix_id + "_locator.json"), {"path": str(Path(prefix.artifact_path).relative_to(out))})
                for row in [r for r in schedule if r["prefix_id"] == prefix.prefix_id]:
                    branch = await adapter.run_governor_branch(prefix, snapshot, personas, condition=row["condition"],
                         branch_draw_id=row["branch_draw_id"], persona_verification_context=context, source_root=macro_root)
                    branches.append(branch)
        report.update(status="complete", actual_generation_calls=client.calls, client_generation_attempts=client.calls,
                      evidence_type="engineering_mock" if execution == "mock" else "live_model",
                      provider_spend_usd=0 if execution == "mock" else governor.get_summary()["total_estimated_cost_usd"] - preflight["prior_estimated_spend_usd"])
        write_immutable(out / "outcomes.json", _seal({"protocol_hash": spec.artifact_content_hash, "prefixes": prefixes, "branches": branches}))
        menu = [{"vote": rate, "stance": stance} for rate in RATE_ACTIONS_BPS for stance in STANCE_ACTIONS]
        write_immutable(out / "analysis.json", _seal(_artifact_analysis(schedule, out / "generations", menu, spec=spec, loaded=loaded)))
        write_immutable(out / "completion.json", _seal(report))
        return report
    except BaseException as error:
        # Include adapter-retained failures, without repairing or replacing them.
        known = {b["branch_id"] for b in branches}
        for path in (out / "generations").rglob("branch_failure.json"):
            failure = _json(path)
            if failure["branch_id"] not in known:
                branches.append(failure)
        write_immutable(out / "failure.json", _seal({"status": "failed", "error_type": type(error).__name__, "error": str(error),
            "actual_generation_calls": client.calls if client else 0,
            "client_generation_attempts": client.calls if client else 0,
            "failed_call_limit": "A failed client attempt may precede actual provider submission; retain receipts for billing",
            "planned_branches": len(schedule)}))
        if schedule:
            try:
                menu = [{"vote": rate, "stance": stance} for rate in RATE_ACTIONS_BPS for stance in STANCE_ACTIONS]
                write_immutable(out / "partial_outcomes.json", _seal({"prefixes": prefixes, "branches": branches}))
                write_immutable(out / "partial_analysis.json", _seal(_analysis(schedule, prefixes, branches, menu)))
            except BaseException as retention_error:
                error.add_note("Partial analysis also failed: " + str(retention_error))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--protocol")
    source.add_argument("--create-fixture", action="store_true")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--execution", choices=("validate", "mock", "live", "replay"), default="validate")
    parser.add_argument("--retained-root")
    args = parser.parse_args()
    if args.create_fixture:
        result = {"protocol": str(create_engineering_fixture(args.output_root)), "evidence_type": "engineering_fixture", "actual_generation_calls": 0}
    elif args.execution == "replay":
        if not args.retained_root:
            parser.error("Replay requires --retained-root")
        result = replay_study(args.protocol, args.retained_root, args.output_root)
    else:
        result = asyncio.run(run_study(args.protocol, args.output_root, execution=args.execution))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
