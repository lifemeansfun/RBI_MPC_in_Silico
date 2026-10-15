"""Build portable, immutable retrospective roster and rolling-persona packets.

No model call, outcome-dependent fit, retrospective biography, or silent ontology
mapping occurs here.  Realized attendance remains an explicitly oracle input.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import platform
import re
import sys
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from src.schemas.temporal_panel_schema import (
    DatedSourceRef, PersonalStatementRef, RollingPersonaPacket, TemporalMeetingRoster,
    TemporalMember, SOURCE_STANCE_ACTIONS_V2,
)

ROOT = Path(__file__).resolve().parents[2]
EXPANDED = Path("research/source_ledgers/expanded_panel_oct08")
ORIGINAL = Path("data/processed/statements_v2")
ALIAS = {"michael_patra": "michael_debabrata_patra"}
# Names/roles below are verified against each attendance paragraph and personal
# heading before use; these are identifiers, not fitted policy personalities.
MEMBERS = {
    "shashanka_bhide": ("Shashanka Bhide", "External Member"),
    "ashima_goyal": ("Ashima Goyal", "External Member"),
    "jayanth_varma": ("Jayanth R. Varma", "External Member"),
    "mridul_saggar": ("Mridul K. Saggar", "Executive Director"),
    "michael_debabrata_patra": ("Michael Debabrata Patra", "Deputy Governor"),
    "rajiv_ranjan": ("Rajiv Ranjan", "Executive Director"),
    "shaktikanta_das": ("Shaktikanta Das", "Governor"),
    "nagesh_kumar": ("Nagesh Kumar", "External Member"),
    "saugata_bhattacharya": ("Saugata Bhattacharya", "External Member"),
    "ram_singh": ("Ram Singh", "External Member"),
    "m_rajeshwar_rao": ("Rajeshwar Rao", "Deputy Governor"),
    "sanjay_malhotra": ("Sanjay Malhotra", "Governor"),
    "poonam_gupta": ("Poonam Gupta", "Deputy Governor"),
    "indranil_bhattacharyya": ("Indranil Bhattacharyya", "Executive Director"),
}
# Fixed descriptive lexicons, inherited transparently from the current extractor.
# Their reuse prevents selecting a new lexical statistic after viewing outcomes.
HAWK_LEXICON = ("inflation", "restrictive", "vigilance", "unanchored", "persistence",
                "second-round", "overheating", "pressures", "brake", "firm", "committed", "tolerance", "target")
DOVE_LEXICON = ("growth", "slack", "over-tightening", "lag", "lags", "sacrifice", "soften",
                "real rate", "neutral", "output gap", "recovery", "headwind", "downturn")


def sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def normalized(text):
    return " ".join(text.split())


def canonical_member_id(value):
    result = ALIAS.get(value, value)
    if result not in MEMBERS:
        raise ValueError(f"Unknown member identity: {value}")
    return result


def canonical_roster(values):
    result = tuple(canonical_member_id(value) for value in values)
    if len(result) != 6 or len(set(result)) != 6:
        raise ValueError("Alias normalization would duplicate or omit an attendee")
    return result


def _read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key {key}")
            result[key] = value
        return result
    def reject(value):
        raise ValueError(f"Invalid JSON constant {value}")
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=reject)


def source_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Missing or outside-root scientific input: {relative}")
    return path


def _publication_day(soup):
    """Read retained RBI header only; never infer publication from decision day."""
    body = soup.select_one("#doublescroll")
    if body is None:
        return None
    matches = re.findall(r"Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
                         normalized(body.get_text(" ", strip=True))[:300])
    if len(matches) != 1:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(matches[0], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _name_present(text, identifier):
    name = MEMBERS[identifier][0]
    # The original roster abbreviates Jayanth R. and Mridul K. inconsistently.
    if identifier == "jayanth_varma":
        return bool(re.search(r"Jayanth\s+(?:R\.?\s+)?Varma", text))
    if identifier == "mridul_saggar":
        return bool(re.search(r"Mridul\s+(?:K\.?\s+)?Saggar", text))
    return name in text


def _personal_heading(text, identifier):
    prefix = re.match(r"Statement\s+by\s+(.+?)(?=\s+\d+\.|$)", normalized(text))
    if prefix is None or not _name_present(prefix.group(0), identifier):
        raise ValueError(f"Personal attribution heading missing or wrong for {identifier}")
    return prefix.group(0)


class _SourceStore:
    def __init__(self, root):
        self.root = root
        self.inputs = {}
        self.payloads = {}
        self.origin_to_portable = {}
        self.soups = {}

    def read(self, relative, expected=None):
        path = source_path(self.root, relative)
        payload = path.read_bytes()
        digest = sha256(payload)
        if expected is not None and digest != expected:
            raise ValueError(f"Scientific input hash mismatch: {relative}")
        self.inputs[str(relative)] = digest
        portable = "sources/" + digest + path.suffix
        self.payloads[portable] = payload
        self.origin_to_portable[str(relative)] = portable
        return path, payload

    def ref(self, relative, expected, source_id, url, claimed_publication):
        _, payload = self.read(relative, expected)
        soup = BeautifulSoup(payload, "html.parser")
        publication = _publication_day(soup)
        # A missing header stays missing. A disagreement is corruption, not an
        # opportunity to prefer the ledger's date.
        if publication is not None and publication != claimed_publication:
            raise ValueError(f"Publication ledger/header mismatch for {relative}")
        self.soups[str(relative)] = soup
        return DatedSourceRef(
            source_id=source_id, source_file=str(relative), source_sha256=expected,
            source_url=url, publication_date=publication,
            publication_status="verified_retained_header" if publication else "unresolved")


def _roster(meeting, ids, source, excerpt, *, previous_role_evidence=None):
    ids = canonical_roster(ids)
    if any(not _name_present(excerpt, identifier) for identifier in ids):
        raise ValueError("Attendance excerpt does not support every normalized identity")
    # October 2026's resolution names attendees without repeating every role.
    # Carry only unchanged identities' prior explicitly documented role source;
    # do not reinterpret that source as a pre-cutoff appointment announcement.
    roles_explicit = all(role in excerpt for role in ("Governor", "Deputy Governor", "Executive Director"))
    members = []
    for identifier in ids:
        if roles_explicit:
            role_source, role_excerpt = source, excerpt
        else:
            if previous_role_evidence is None or identifier not in previous_role_evidence:
                raise ValueError("Role missing from attendance and no earlier documented role source")
            role_source, role_excerpt = previous_role_evidence[identifier]
        members.append(TemporalMember(member_id=identifier, name=MEMBERS[identifier][0],
                                      role=MEMBERS[identifier][1],
                                      is_internal=MEMBERS[identifier][1] != "External Member",
                                      role_evidence_source=role_source, role_evidence_excerpt=role_excerpt))
    members = tuple(members)
    governor = [m.member_id for m in members if m.role == "Governor"]
    if len(governor) != 1:
        raise ValueError("Attendance excerpt does not support exactly one known Governor")
    # The role labels must be present in the attendance text; external roles are
    # source-designated non-RBI members, not estimated behavioral preferences.
    return TemporalMeetingRoster(
        meeting_id=meeting["meeting_id"], decision_date=meeting["decision_date"],
        meeting_start_date=meeting["meeting_start_date"],
        information_cutoff=meeting["meeting_start_date"] + "T00:00:00+05:30",
        members=members, governor_id=governor[0], roster_source=source,
        roster_source_excerpt=excerpt)


def _original_inputs(store):
    meetings, statements = [], []
    directory = source_path(store.root, ORIGINAL / "2020-10-09/source_manifest.json").parent.parent
    for manifest_path in sorted(directory.glob("*/source_manifest.json")):
        relative = manifest_path.relative_to(store.root)
        store.read(relative)
        meta = _read_json(manifest_path)
        decision = meta["decision_date"]
        if manifest_path.parent.name != decision:
            raise ValueError("Original statement folder and decision disagree")
        source_id = Path(meta["source_file"]).stem
        prid = source_id.rsplit("_", 1)[-1]
        source = store.ref(meta["source_file"], meta["source_sha256"], source_id,
                           "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=" + prid,
                           meta["publication_date"])
        soup = store.soups[meta["source_file"]]
        body = soup.select_one("#doublescroll")
        if body is None:
            raise ValueError("Missing official minutes article body")
        blocks = [normalized(e.get_text(" ", strip=True)) for e in body.find_all("p")]
        excerpts = [b for b in blocks if b.startswith("2.") and "meeting was attended" in b.lower()]
        if len(excerpts) != 1:
            raise ValueError("Ambiguous original attendance paragraph")
        meeting = {"meeting_id": "rbi_mpc_" + decision, "decision_date": decision,
                   "meeting_start_date": meta["meeting_start_date"]}
        roster = _roster(meeting, tuple(meta["statement_sha256"]), source, excerpts[0])
        meetings.append(roster)
        raw_text = normalized(soup.get_text())
        for old_id, digest in sorted(meta["statement_sha256"].items()):
            identifier = canonical_member_id(old_id)
            name = str(manifest_path.parent.relative_to(store.root) / (old_id + ".txt"))
            _, payload = store.read(name, digest)
            text = payload.decode("utf-8")
            if normalized(text) not in raw_text:
                raise ValueError("Personal statement is not in retained raw minutes")
            heading = _personal_heading(text, identifier)
            statements.append((PersonalStatementRef(
                statement_id=meeting["meeting_id"] + ":" + identifier, member_id=identifier,
                original_member_id=old_id, meeting_id=meeting["meeting_id"], decision_date=decision,
                source=source, statement_file=name, statement_sha256=digest,
                attribution_heading=heading), text))
    return meetings, statements


def _expanded_inputs(store):
    catalog_path, _ = store.read(EXPANDED / "source_catalog.json")
    ledger_path, _ = store.read(EXPANDED / "meeting_label_ledger.json")
    statement_path, _ = store.read(EXPANDED / "member_statements.jsonl")
    catalog = {r["source_id"]: r for r in _read_json(catalog_path)["records"]}
    ledger = _read_json(ledger_path)
    meetings, refs, prior_roles = [], {}, {}
    for row in ledger["meetings"]:
        evidence = row["roster_source_excerpt"]
        record = catalog[evidence["source_id"]]
        relative = EXPANDED / evidence["source_path"]
        if record["sha256"] != evidence["source_sha256"] or record["raw_path"] != evidence["source_path"]:
            raise ValueError("Roster source/catalog mismatch")
        source = store.ref(relative, record["sha256"], record["source_id"], record["url"],
                           record["publication_date"])
        if row["information_cutoff_exclusive_ist"] != row["meeting_start_date"] + "T00:00:00+05:30":
            raise ValueError("Expanded cutoff is inconsistent with meeting start")
        soup = store.soups[str(relative)]
        body = soup.select_one("#doublescroll")
        if body is None or normalized(evidence["text"]) not in normalized(body.get_text(" ", strip=True)):
            raise ValueError("Roster excerpt missing from raw source")
        roster = _roster(row, row["roster_ids"], source, evidence["text"], previous_role_evidence=prior_roles)
        meetings.append(roster)
        for member in roster.members:
            prior_roles[member.member_id] = (member.role_evidence_source, member.role_evidence_excerpt)
        refs[source.source_id] = source
    statements = []
    for row in [json.loads(line) for line in statement_path.read_text().splitlines() if line.strip()]:
        identifier = canonical_member_id(row["member_id"])
        record = catalog[row["source_id"]]
        source = refs[row["source_id"]]
        if (row["source_sha256"] != source.source_sha256
                or row["minutes_publication_date"] != record["publication_date"]):
            raise ValueError("Statement publication/source differs from verified source ledger")
        soup = store.soups[source.source_file]
        body = soup.select_one("#doublescroll")
        active, personal, heading = None, [], None
        for elem in body.find_all(lambda e: e.name == "p" or (e.name == "span" and "head" in e.get("class", []))):
            text = normalized(elem.get_text(" ", strip=True))
            if text.startswith("Statement by"):
                matches = [key for key in MEMBERS if _name_present(text, key)]
                if len(matches) != 1:
                    raise ValueError("Ambiguous personal statement heading")
                active = matches[0]
                if active == identifier:
                    heading = text
            elif active == identifier and text:
                personal.append(text)
        if heading is None or personal != row["statement_paragraphs"]:
            raise ValueError("Personal statement segmentation differs from raw bytes")
        # Text is derived deterministically, retained with its own digest; the
        # exact source JSONL bytes and raw HTML remain in the portable catalogue.
        text = heading + "\n\n" + "\n\n".join(personal) + "\n"
        payload = text.encode("utf-8")
        digest = sha256(payload)
        name = "derived_statements/" + row["meeting_id"] + "/" + identifier + ".txt"
        store.payloads[name] = payload
        statements.append((PersonalStatementRef(
            statement_id=row["meeting_id"] + ":" + identifier, member_id=identifier,
            original_member_id=row["member_id"], meeting_id=row["meeting_id"],
            decision_date=row["decision_date"], source=source, statement_file=name,
            statement_sha256=digest, attribution_heading=heading), text))
    # Unsupported source category is a diagnostic outcome, never a persona input.
    compatibility = [{"meeting_id": row["meeting_id"], "source_stance": row["committee_stance"],
                      "simulator_v1_supported": row["committee_stance"] != "calibrated_tightening",
                      "mapping": None, "ontology": "expanded_source_v2",
                      "status": "outcome_diagnostic_excluded_from_persona_inputs"}
                     for row in ledger["meetings"]]
    return meetings, statements, compatibility


def _rolling_partition(roster, statements):
    cutoff_day = roster.information_cutoff.date().isoformat()
    packets, exclusions = [], []
    for member in roster.members:
        included = []
        texts = []
        for statement, text in statements:
            if statement.member_id != member.member_id:
                continue
            publication = statement.source.publication_date
            reason = None
            if statement.meeting_id == roster.meeting_id:
                reason = "same_meeting_outcome_statement"
            elif statement.decision_date >= cutoff_day:
                reason = "decision_not_before_cutoff"
            elif publication is None:
                reason = "unresolved_publication_timing"
            elif publication >= cutoff_day:
                reason = "publication_day_not_strictly_before_cutoff"
            if reason:
                exclusions.append({"member_id": member.member_id, "statement_id": statement.statement_id,
                                   "decision_date": statement.decision_date, "publication_date": publication,
                                   "reason": reason, "source_sha256": statement.source.source_sha256,
                                   "statement_sha256": statement.statement_sha256})
            else:
                included.append(statement)
                texts.append(text)
        hawk = sum(len(re.findall(r"\b" + re.escape(word) + r"\b", text, re.I))
                   for text in texts for word in HAWK_LEXICON)
        dove = sum(len(re.findall(r"\b" + re.escape(word) + r"\b", text, re.I))
                   for text in texts for word in DOVE_LEXICON)
        packets.append(RollingPersonaPacket(
            meeting_id=roster.meeting_id, member_id=member.member_id,
            information_cutoff=roster.information_cutoff, statements=tuple(included),
            history_status="available_personal_history" if included else "missing_personal_history",
            lexical_orientation=(hawk - dove) / max(hawk + dove, 1) if included else None,
            lexical_hawk_hits=hawk, lexical_dove_hits=dove))
    return packets, exclusions


def _regimes(rosters):
    regimes = []
    for roster in rosters:
        signature = tuple(sorted(m.member_id for m in roster.members))
        if not regimes or tuple(regimes[-1]["member_ids"]) != signature:
            regimes.append({"regime_id": "observed_roster_" + roster.decision_date,
                            "member_ids": list(signature), "governor_id": roster.governor_id,
                            "first_observed_decision": roster.decision_date,
                            "last_observed_decision": roster.decision_date,
                            "meeting_ids": [], "source_refs": [], "appointment_start_date": None,
                            "appointment_end_date": None,
                            "status": "realized_attendance_interval_not_appointment_tenure"})
        regime = regimes[-1]
        regime["last_observed_decision"] = roster.decision_date
        regime["meeting_ids"].append(roster.meeting_id)
        regime["source_refs"].append(roster.roster_source.model_dump(mode="json"))
    for index, regime in enumerate(regimes):
        if index:
            prior = regimes[index - 1]
            regime["turnover_bracket"] = {
                "after_old_roster_observed_decision": prior["last_observed_decision"],
                "by_new_roster_observed_decision": regime["first_observed_decision"],
                "appointment_day_known": False,
                "added_member_ids": sorted(set(regime["member_ids"]) - set(prior["member_ids"])),
                "departed_member_ids": sorted(set(prior["member_ids"]) - set(regime["member_ids"]))}
        else:
            regime["turnover_bracket"] = None
    return regimes


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _portable_refs(value, mapping):
    """Copy reference topology, replacing only explicitly verified source paths."""
    if isinstance(value, list):
        return [_portable_refs(item, mapping) for item in value]
    if isinstance(value, dict):
        result = {key: _portable_refs(item, mapping) for key, item in value.items()}
        if "source_file" in value and "source_sha256" in value:
            result["origin_source_file"] = value["source_file"]
            result["source_file"] = mapping[value["source_file"]]
        return result
    return value


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def build_rolling_inputs(*, output_root, source_root=ROOT):
    """Verify first, then exclusively create one new portable input destination."""
    root = Path(source_root).resolve()
    out = Path(output_root).resolve()
    if out.exists():
        raise FileExistsError("Rolling input destinations must be unused")
    store = _SourceStore(root)
    for code in ("src/schemas/temporal_panel_schema.py", "src/persona_engine/rolling_inputs.py",
                 "src/persona_engine/extractor.py"):
        store.read(code)
    original_rosters, original_statements = _original_inputs(store)
    expanded_rosters, expanded_statements, compatibility = _expanded_inputs(store)
    rosters = sorted(original_rosters + expanded_rosters, key=lambda r: r.decision_date)
    statements = sorted(original_statements + expanded_statements,
                        key=lambda pair: (pair[0].decision_date, pair[0].member_id))
    if len({r.meeting_id for r in rosters}) != len(rosters) or len({s.statement_id for s, _ in statements}) != len(statements):
        raise ValueError("Duplicated meeting or personally attributed source identity")
    for statement, _ in statements:
        roster = next((r for r in rosters if r.meeting_id == statement.meeting_id), None)
        if roster is None or statement.member_id not in {m.member_id for m in roster.members}:
            raise ValueError("Statement belongs to no verified realized attendance roster")
    protocol = {
        "version": "rolling-persona-retrospective-input-v1",
        "panel_status": "exposed_retrospective_2020_2026",
        "fit_schedule": "expanding_personal_history_refit_before_each_first_meeting_day",
        "information_cutoff": "exclusive midnight IST on first meeting day; entire publication day must precede cutoff",
        "minimum_personal_statements": 1,
        "missing_history_policy": "explicit_missing_no_identity_substitution",
        "eligible_sources": "personally attributed retained minutes only; no same-meeting statements, current biography, or outcome labels",
        "lexical_fit": {"hawk_lexicon": HAWK_LEXICON, "dove_lexicon": DOVE_LEXICON,
                        "statistic": "(hawk_hits-dove_hits)/max(hawk_hits+dove_hits,1)",
                        "scope": "descriptive fixed lexical statistic; not construct validated or an identified policy utility",
                        "selection_source": "existing src/persona_engine/extractor.py fixed lexicons"},
        "identity_aliases": ALIAS,
        "identity_alias_basis": "Both source IDs refer to personal heading Dr. Michael Debabrata Patra and the same attendance name; duplicate canonical attendees are rejected",
        "source_stance_ontology": {"version": "expanded_source_v2", "actions": SOURCE_STANCE_ACTIONS_V2,
                                  "simulator_v1_policy": "reject unsupported calibrated_tightening; mapping remains null",
                                  "integration_status": "additive_source_contract_not_existing_simulator_integration"},
        "roster_evidence_status": "retrospective_oracle_attendance",
        "roster_available_at_cutoff": False,
        "predictive_readiness": False,
        "readiness_blockers": ["pre-cutoff membership/appointment evidence not retained in this packet",
                               "missing personal history at entry", "expanded macro packets not supplied by this builder",
                               "simulator stance v2 integration not supplied by this builder",
                               "no live model generation or untouched prospective outcome"]}
    payloads = dict(store.payloads)
    payloads["protocol.json"] = _json_bytes(protocol)
    payloads["realized_rosters.json"] = _json_bytes(_portable_refs(
        [r.model_dump(mode="json") for r in rosters], store.origin_to_portable))
    payloads["observed_roster_regimes.json"] = _json_bytes(_portable_refs(_regimes(rosters), store.origin_to_portable))
    payloads["stance_compatibility_outcomes.json"] = _json_bytes(compatibility)
    summary = []
    for roster in rosters:
        packets, exclusions = _rolling_partition(roster, statements)
        # References in persona packets are converted to content-addressed paths
        # so the packet can be inspected without the original checkout.
        persona_rows = [p.model_dump(mode="json") for p in packets]
        for packet in persona_rows:
            for statement in packet["statements"]:
                source = statement["source"]
                source["origin_source_file"] = source["source_file"]
                source["source_file"] = store.origin_to_portable[source["source_file"]]
                origin = statement["statement_file"]
                statement["origin_statement_file"] = origin
                statement["statement_file"] = store.origin_to_portable.get(origin, origin)
        training_meetings = sorted({s.meeting_id for p in packets for s in p.statements})
        row = {"version": "rolling-persona-packet-v1", "meeting_id": roster.meeting_id,
               "information_cutoff": roster.information_cutoff.isoformat(),
               "evaluation_meeting_ids": [roster.meeting_id],
               "rolling_fit_meeting_ids": training_meetings,
               "roster_evidence_status": "retrospective_oracle_attendance",
               "roster_available_at_cutoff": False, "predictive_readiness": False,
               "members": persona_rows, "exclusions": exclusions,
               "fit_protocol_sha256": sha256(payloads["protocol.json"])}
        name = "packets/" + roster.meeting_id + ".json"
        payloads[name] = _json_bytes(row)
        summary.append({"meeting_id": roster.meeting_id, "packet_file": name,
                        "packet_sha256": sha256(payloads[name]),
                        "history_counts": {p.member_id: len(p.statements) for p in packets},
                        "missing_history_member_ids": [p.member_id for p in packets if not p.statements],
                        "rolling_fit_meeting_ids": training_meetings,
                        "same_meeting_sources_excluded": sum(e["reason"] == "same_meeting_outcome_statement" for e in exclusions)})
    # Capture all directly reused code bytes and reject accidental lexicon drift.
    extractor_path, _ = store.read("src/persona_engine/extractor.py")
    assignments = {}
    for node in ast.parse(extractor_path.read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("HAWK_LEXICON", "DOVE_LEXICON"):
                    assignments[target.id] = tuple(ast.literal_eval(node.value))
    if assignments.get("HAWK_LEXICON") != HAWK_LEXICON or assignments.get("DOVE_LEXICON") != DOVE_LEXICON:
        raise ValueError("Existing frozen lexical rule differs from the registered rolling rule")
    for code in ("src/schemas/temporal_panel_schema.py", "src/persona_engine/rolling_inputs.py"):
        store.read(code)
    payloads.update(store.payloads)
    changed = [name for name, digest in store.inputs.items() if sha256(source_path(root, name).read_bytes()) != digest]
    if changed:
        raise ValueError(f"Scientific inputs changed during construction: {changed}")
    payloads["packet_index.json"] = _json_bytes(summary)
    receipt = {"version": "rolling-persona-receipt-v1", "build_status": "verified_inputs_built",
               "predictive_readiness": False, "model_calls": 0, "meetings_count": len(rosters),
               "member_packets_count": sum(len(r.members) for r in rosters),
               "source_statements_count": len(statements),
               "missing_history_member_packets": sum(len(r["missing_history_member_ids"]) for r in summary),
               "unresolved_publication_statements": sum(s.source.publication_date is None for s, _ in statements),
               "original_inputs": store.inputs, "origin_to_portable": store.origin_to_portable,
               "output_files": {name: sha256(payload) for name, payload in sorted(payloads.items())},
               "input_immutability_verified": True,
               "environment": {"python": sys.version, "platform": platform.platform()},
               "command": sys.argv,
               "evidence_limit": "retained byte consistency and header dates; no authenticated historical first posting or policy-preference construct validation"}
    payloads["receipt.json"] = _json_bytes(receipt)
    for name, payload in sorted(payloads.items()):
        _write(out / name, payload)
    return receipt


def verify_portable_rolling_inputs(output_root):
    """Validate every frozen byte and the cross-identity/date/source firewall."""
    root = Path(output_root).resolve()
    receipt = _read_json(root / "receipt.json")
    for name, digest in receipt["output_files"].items():
        if sha256(source_path(root, name).read_bytes()) != digest:
            raise ValueError(f"Portable input hash mismatch: {name}")
    verified_sources = {}
    def clean_source(value):
        value = dict(value)
        value.pop("origin_source_file", None)
        ref = DatedSourceRef.model_validate(value)
        key = (ref.source_file, ref.source_sha256, ref.publication_date)
        if key not in verified_sources:
            payload = source_path(root, ref.source_file).read_bytes()
            if sha256(payload) != ref.source_sha256:
                raise ValueError("Portable source reference hash mismatch")
            if _publication_day(BeautifulSoup(payload, "html.parser")) != ref.publication_date:
                raise ValueError("Portable source reference publication/header mismatch")
            verified_sources[key] = ref
        return ref
    rosters = {}
    for value in _read_json(root / "realized_rosters.json"):
        value = dict(value)
        value["roster_source"] = clean_source(value["roster_source"])
        members = []
        for member in value["members"]:
            member = dict(member)
            member["role_evidence_source"] = clean_source(member["role_evidence_source"])
            members.append(TemporalMember.model_validate(member))
        value["members"] = tuple(members)
        roster = TemporalMeetingRoster.model_validate(value)
        if roster.meeting_id in rosters:
            raise ValueError("Duplicated portable realized attendance identity")
        rosters[roster.meeting_id] = roster
    index = _read_json(root / "packet_index.json")
    for row in index:
        packet = _read_json(source_path(root, row["packet_file"]))
        if sha256(source_path(root, row["packet_file"]).read_bytes()) != row["packet_sha256"]:
            raise ValueError("Packet index/hash mismatch")
        roster = rosters.get(packet["meeting_id"])
        if (roster is None or set(m["member_id"] for m in packet["members"]) != {m.member_id for m in roster.members}
                or len(packet["members"]) != 6 or packet["information_cutoff"] != roster.information_cutoff.isoformat()):
            raise ValueError("Portable persona packet and attendance roster/cutoff differ")
        for member in packet["members"]:
            clean = dict(member)
            clean_statements = []
            for statement in member["statements"]:
                statement = dict(statement)
                statement.pop("origin_statement_file", None)
                source = clean_source(statement["source"])
                statement["source"] = source
                if sha256(source_path(root, statement["statement_file"]).read_bytes()) != statement["statement_sha256"]:
                    raise ValueError("Portable personal statement differs from source reference")
                clean_statements.append(PersonalStatementRef.model_validate(statement))
            clean["statements"] = tuple(clean_statements)
            RollingPersonaPacket.model_validate(clean)
        if packet["roster_evidence_status"] != "retrospective_oracle_attendance" or packet["predictive_readiness"] is not False:
            raise ValueError("Portable packet misrepresents retrospective readiness")
    return {"status": "portable_source_bytes_and_persona_firewall_verified",
            "meetings_count": len(index), "verified_files": len(receipt["output_files"]),
            "predictive_readiness": False, "model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--source-root", default=str(ROOT))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        result = verify_portable_rolling_inputs(args.output_root)
    else:
        result = build_rolling_inputs(output_root=args.output_root, source_root=args.source_root)
        result = {key: result[key] for key in ("build_status", "meetings_count", "source_statements_count",
                  "member_packets_count", "missing_history_member_packets", "predictive_readiness", "model_calls")}
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
