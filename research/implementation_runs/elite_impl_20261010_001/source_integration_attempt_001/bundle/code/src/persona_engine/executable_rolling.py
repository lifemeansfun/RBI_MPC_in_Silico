"""Source-preserving executable adapter for retrospective rolling histories.

The fixed lexical statistic and selected quotations are descriptive inputs.  A
neutral stance parameter is procedural, not a fitted stance preference.  Realized
attendance is an oracle input, and no appointment or construct validation is
asserted.  Missing personal histories never become executable personas.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

from src.infra.evidence import file_hash, safe_component
from src.infra.exceptions import GenerationProvenanceError
from src.persona_engine.rolling_inputs import (
    ROOT, MEMBERS, HAWK_LEXICON, DOVE_LEXICON, _read_json, _json_bytes,
    _name_present, _personal_heading, _publication_day, _write,
    canonical_member_id, normalized, sha256, source_path,
    verify_portable_rolling_inputs,
)
from src.schemas.persona_schema import MemberPersona
from src.schemas.temporal_panel_schema import (
    DatedSourceRef, PersonalStatementRef, RollingPersonaPacket,
    TemporalMeetingRoster,
)

MANIFEST_VERSION = "dated-lexical-rolling-v3"
EXTRACTION_RULE = {
    "version": "rolling-executable-lexical-v1",
    "hawk_lexicon": list(HAWK_LEXICON), "dove_lexicon": list(DOVE_LEXICON),
    "orientation": "(hawk_hits-dove_hits)/max(hawk_hits+dove_hits,1); no rounding",
    "quotes": "first 20-60-word sentence per chronological source; first, middle, last distinct indices",
    "stance_bias": "neutral; fixed procedural parameter, not extracted or construct validated",
    "priority": "fixed RBI-mandate instruction, not a fitted member preference",
    "tenure": "corpus-coverage label only; no appointment-tenure claim",
    "biography": None,
}
PRIORITY = "Evaluate supplied inflation and activity evidence under the RBI mandate."


def _clean_source(value):
    value = dict(value)
    value.pop("origin_source_file", None)
    return DatedSourceRef.model_validate(value)


def _clean_statement(value):
    value = dict(value)
    value.pop("origin_statement_file", None)
    value["source"] = _clean_source(value["source"])
    return PersonalStatementRef.model_validate(value)


def _clean_roster(value):
    value = dict(value)
    value["roster_source"] = _clean_source(value["roster_source"])
    value["members"] = [dict(m, role_evidence_source=_clean_source(m["role_evidence_source"]))
                        for m in value["members"]]
    return TemporalMeetingRoster.model_validate(value)


class _RawVerifier:
    """Verify byte, printed-day and personal-attribution evidence separately."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.sources = {}
        self.statements = {}

    def source(self, value):
        ref = _clean_source(value)
        key = (ref.source_file, ref.source_sha256, ref.publication_date)
        if key not in self.sources:
            path = source_path(self.root, ref.source_file)
            payload = path.read_bytes()
            if sha256(payload) != ref.source_sha256:
                raise ValueError("Rolling raw source bytes differ from reference")
            soup = BeautifulSoup(payload, "html.parser")
            if _publication_day(soup) != ref.publication_date:
                raise ValueError("Rolling source publication differs from retained header")
            self.sources[key] = soup
        # Source IDs are retained identities, not silently rewritten URL aliases.
        origin = value.get("origin_source_file")
        if origin is not None and Path(origin).stem != ref.source_id:
            raise ValueError("Rolling source identity differs from its retained origin")
        return ref, self.sources[key]

    def roster(self, value):
        roster = _clean_roster(value)
        _, soup = self.source(value["roster_source"])
        body = soup.select_one("#doublescroll")
        if body is None or normalized(roster.roster_source_excerpt) not in normalized(body.get_text(" ", strip=True)):
            raise ValueError("Realized attendance excerpt is absent from raw source")
        for member, original in zip(roster.members, value["members"]):
            expected_name, expected_role = MEMBERS[canonical_member_id(member.member_id)]
            if (member.name != expected_name or member.role != expected_role
                    or not _name_present(roster.roster_source_excerpt, member.member_id)):
                raise ValueError("Executable identity or role disagrees with documented roster")
            _, role_soup = self.source(original["role_evidence_source"])
            role_text = normalized(role_soup.get_text(" ", strip=True))
            excerpt = member.role_evidence_excerpt
            if normalized(excerpt) not in role_text or not _name_present(excerpt, member.member_id):
                raise ValueError("Role evidence excerpt is absent or belongs to another person")
            if member.is_internal and member.role not in excerpt:
                raise ValueError("Internal institutional role is not documented in its excerpt")
        return roster

    def statement(self, value):
        ref = _clean_statement(value)
        _, soup = self.source(value["source"])
        if (canonical_member_id(ref.original_member_id) != ref.member_id
                or ref.statement_id != ref.meeting_id + ":" + ref.member_id):
            raise ValueError("Canonical statement identity differs from personal attribution")
        key = (ref.statement_id, ref.statement_file, ref.statement_sha256,
               ref.source.source_file, ref.source.source_sha256,
               ref.attribution_heading, value.get("origin_statement_file"))
        if key not in self.statements:
            text = source_path(self.root, ref.statement_file).read_text(encoding="utf-8")
            if sha256(text.encode("utf-8")) != ref.statement_sha256:
                raise ValueError("Personal statement bytes differ from reference")
            origin = value.get("origin_statement_file", ref.statement_file)
            heading = (text.split("\n\n", 1)[0] if origin.startswith("derived_statements/")
                       else _personal_heading(text, ref.member_id))
            if (not _name_present(heading, ref.member_id)
                    or heading != ref.attribution_heading):
                raise ValueError("Personal heading or canonical statement identity differs")
            if origin.startswith("derived_statements/"):
                # Recreate the existing expanded-source segmentation from raw
                # DOM blocks, including any repeated source callout blocks.
                body = soup.select_one("#doublescroll")
                if body is None:
                    raise ValueError("Missing source article body")
                active, heading, paragraphs = None, None, []
                for elem in body.find_all(lambda e: e.name == "p" or
                                          (e.name == "span" and "head" in e.get("class", []))):
                    block = normalized(elem.get_text(" ", strip=True))
                    if block.startswith("Statement by"):
                        matches = [identifier for identifier in MEMBERS if _name_present(block, identifier)]
                        if len(matches) != 1:
                            raise ValueError("Ambiguous raw personal heading")
                        active = matches[0]
                        if active == ref.member_id:
                            heading = block
                    elif active == ref.member_id and block:
                        paragraphs.append(block)
                reconstructed = (heading + "\n\n" + "\n\n".join(paragraphs) + "\n") if heading else None
                if reconstructed != text:
                    raise ValueError("Derived personal text does not reconstruct from raw source")
            else:
                # Recreate the original signed-heading boundaries and its
                # administrative-footer cutoff. Whole-document containment
                # alone could incorrectly include the next person's statement.
                from src.data_pipeline.statement_extractor import MEMBER_PATTERNS, ADMIN_CUTOFFS
                full_text = soup.get_text()
                headings = sorted((match.start(), canonical_member_id(item["member_id"]))
                    for item in MEMBER_PATTERNS
                    if (match := re.search(item["pattern"], full_text, re.I)))
                matches = [i for i, (_, identifier) in enumerate(headings) if identifier == ref.member_id]
                if len(matches) != 1 or len(headings) != 6:
                    raise ValueError("Original raw signed-heading boundaries are incomplete")
                i = matches[0]
                start = headings[i][0]
                end = headings[i + 1][0] if i + 1 < len(headings) else len(full_text)
                if i + 1 == len(headings):
                    for pattern in ADMIN_CUTOFFS:
                        cutoff_match = re.search(pattern, full_text[start:], re.I)
                        if cutoff_match:
                            end = start + cutoff_match.start()
                            break
                reconstructed = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n",
                    full_text[start:end].strip())).strip()
                if reconstructed != text:
                    raise ValueError("Original personal text does not reconstruct within its own signed-heading boundaries")
            self.statements[key] = text
        return ref, self.statements[key]


def _load_rolling(rolling_root):
    root = Path(rolling_root).resolve()
    verify_portable_rolling_inputs(root)
    receipt = _read_json(root / "receipt.json")
    if (receipt.get("version") != "rolling-persona-receipt-v1"
            or receipt.get("predictive_readiness") is not False
            or receipt.get("model_calls") != 0):
        raise ValueError("Unsupported or misrepresented rolling source receipt")
    protocol = _read_json(root / "protocol.json")
    lexical = protocol.get("lexical_fit", {})
    if (lexical.get("hawk_lexicon") != list(HAWK_LEXICON)
            or lexical.get("dove_lexicon") != list(DOVE_LEXICON)
            or protocol.get("roster_evidence_status") != "retrospective_oracle_attendance"
            or protocol.get("roster_available_at_cutoff") is not False
            or protocol.get("predictive_readiness") is not False):
        raise ValueError("Rolling protocol differs from the disclosed source/extraction rule")
    verifier = _RawVerifier(root)
    rosters = {row["meeting_id"]: (row, verifier.roster(row))
               for row in _read_json(root / "realized_rosters.json")}
    index = _read_json(root / "packet_index.json")
    if len(index) != len(rosters) or len({row["meeting_id"] for row in index}) != len(index):
        raise ValueError("Rolling packet index does not cover the exact realized roster panel")
    packets = {}
    for row in index:
        packet = _read_json(source_path(root, row["packet_file"]))
        roster = rosters[row["meeting_id"]][1]
        if packet["meeting_id"] != row["meeting_id"]:
            raise ValueError("Packet index and meeting identity disagree")
        if (packet.get("roster_available_at_cutoff") is not False
                or packet.get("evaluation_meeting_ids") != [roster.meeting_id]
                or packet.get("fit_protocol_sha256") != file_hash(root / "protocol.json")):
            raise ValueError("Rolling packet misrepresents its cutoff, evaluation or fit protocol")
        for value in packet["members"]:
            clean = dict(value, statements=[_clean_statement(s) for s in value["statements"]])
            member = RollingPersonaPacket.model_validate(clean)
            if (member.meeting_id != roster.meeting_id
                    or member.information_cutoff != roster.information_cutoff):
                raise ValueError("Personal packet and realized meeting identity/cutoff differ")
            texts = [verifier.statement(s)[1] for s in value["statements"]]
            hawk, dove = _hits(texts)
            if (hawk, dove) != (member.lexical_hawk_hits, member.lexical_dove_hits):
                raise ValueError("Rolling lexical counts do not reconstruct from personal source bytes")
            for statement in member.statements:
                prior = rosters.get(statement.meeting_id)
                if prior is None or statement.member_id not in {m.member_id for m in prior[1].members}:
                    raise ValueError("Personal history has no corresponding documented realized roster")
        expected_counts = {m["member_id"]: len(m["statements"]) for m in packet["members"]}
        if row["history_counts"] != expected_counts or row["missing_history_member_ids"] != [
                m["member_id"] for m in packet["members"] if not m["statements"]]:
            raise ValueError("Rolling index misrepresents missing personal histories")
        if packet["information_cutoff"] != roster.information_cutoff.isoformat():
            raise ValueError("Rolling packet and realized roster cutoffs differ")
        training = sorted({s["meeting_id"] for m in packet["members"] for s in m["statements"]})
        if packet["rolling_fit_meeting_ids"] != training or row["rolling_fit_meeting_ids"] != training:
            raise ValueError("Rolling training-meeting identities differ from personal source history")
        packets[row["meeting_id"]] = (row, packet)
    return root, receipt, rosters, packets, verifier


def _hits(texts):
    return tuple(sum(len(re.findall(r"\b" + re.escape(word) + r"\b", text, re.I))
                     for text in texts for word in lexicon)
                 for lexicon in (HAWK_LEXICON, DOVE_LEXICON))


def _member_fit(member, packet, verifier):
    sources, sentences, texts = [], [], []
    for value in packet["statements"]:
        ref, text = verifier.statement(value)
        texts.append(text)
        sources.append(value)
        candidates = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text)
                      if 20 <= len(s.split()) <= 60]
        if candidates:
            sentences.append((ref, candidates[0]))
    hawk, dove = _hits(texts)
    indices = sorted({0, len(sentences) // 2, len(sentences) - 1}) if sentences else []
    quotes = [{"text": sentences[i][1], "statement_id": sentences[i][0].statement_id,
               "statement_sha256": sentences[i][0].statement_sha256,
               "decision_date": sentences[i][0].decision_date} for i in indices]
    fields = None
    if sources:
        cutoff_day = datetime.fromisoformat(packet["information_cutoff"]).date().isoformat()
        fields = {"member_id": member.member_id, "name": member.name, "role": member.role,
                  "is_internal": member.is_internal,
                  "tenure": "Personal corpus coverage " + sources[0]["decision_date"] + " to " + sources[-1]["decision_date"] + "; appointment tenure unverified",
                  "hawk_dove_score": (hawk - dove) / max(hawk + dove, 1),
                  "stance_bias": "neutral", "voting_priority": PRIORITY,
                  "biography": None,
                  "key_themes": [f'"{q["text"]}" ({q["decision_date"]})' for q in quotes],
                  "system_prompt_override": None, "calibration_cutoff": cutoff_day,
                  "provenance_status": "dated_corpus"}
    return {"history_status": packet["history_status"], "meetings_count": len(sources),
            "total_words": sum(len(text.split()) for text in texts),
            "hawk_hits": hawk, "dove_hits": dove, "corpus_sources": sources,
            "quote_evidence": quotes, "persona_fields": fields,
            "role_evidence_status": member.role_evidence_status,
            "construct_validated": False}


def _manifest(loaded, meeting_id, *, prefix="rolling_inputs/"):
    root, receipt, rosters, packets, verifier = loaded
    index, packet = packets[meeting_id]
    original_roster, roster = rosters[meeting_id]
    member_packets = {row["member_id"]: row for row in packet["members"]}
    members = {member.member_id: _member_fit(member, member_packets[member.member_id], verifier)
               for member in roster.members}
    return {"version": MANIFEST_VERSION, "meeting_id": meeting_id,
            "calibration_cutoff": roster.meeting_start_date,
            "information_cutoff": roster.information_cutoff.isoformat(),
            "source_bundle_root": prefix.rstrip("/"),
            "rolling_receipt_file": prefix + "receipt.json",
            "rolling_receipt_sha256": file_hash(root / "receipt.json"),
            "packet_file": prefix + index["packet_file"], "packet_sha256": index["packet_sha256"],
            "rosters_file": prefix + "realized_rosters.json",
            "rosters_sha256": receipt["output_files"]["realized_rosters.json"],
            "protocol_file": prefix + "protocol.json",
            "protocol_sha256": receipt["output_files"]["protocol.json"],
            "roster": original_roster, "members": members,
            "extraction_rule": EXTRACTION_RULE,
            "missing_history_member_ids": [key for key, member in members.items() if not member["meetings_count"]],
            "roster_evidence_status": "retrospective_oracle_attendance",
            "roster_available_at_cutoff": False, "construct_validated": False,
            "historical_first_availability_verified": False, "predictive_readiness": False,
            "evidence_limit": "Verified retained raw bytes, attribution and printed publication headers; neither authenticated historical first availability nor validated policy-preference constructs or pre-cutoff membership."}


def build_executable_rolling_bundle(*, rolling_root, output_root):
    """Copy verified rolling inputs and derive per-meeting executable manifests.

    Destination creation is exclusive.  The existing source bundle is preserved.
    All 38 (or explicitly supplied) meetings remain in the index, including those
    excluded for absent histories.  No client, credential or generation is used.
    """
    out = Path(output_root).resolve()
    root = Path(rolling_root).resolve()
    if out.exists():
        raise FileExistsError("Executable persona destinations must be unused")
    if root == out or root.is_relative_to(out):
        raise ValueError("Executable destination cannot contain its source bundle")
    loaded = _load_rolling(root)
    receipt = loaded[1]
    payloads = {"rolling_inputs/" + name: source_path(root, name).read_bytes()
                for name in receipt["output_files"]}
    payloads["rolling_inputs/receipt.json"] = (root / "receipt.json").read_bytes()
    index = []
    for meeting_id in loaded[3]:
        manifest = _manifest(loaded, meeting_id)
        name = "meetings/" + safe_component(meeting_id) + "/corpus_manifest.json"
        payload = _json_bytes(manifest)
        payloads[name] = payload
        digest = sha256(payload)
        personas = [MemberPersona(**row["persona_fields"], corpus_manifest_hash=digest).model_dump()
                    for row in manifest["members"].values() if row["persona_fields"] is not None]
        persona_file = "meetings/" + meeting_id + "/personas.json"
        payloads[persona_file] = _json_bytes(personas)
        index.append({"meeting_id": meeting_id, "information_cutoff": manifest["information_cutoff"],
                      "corpus_manifest_file": name, "corpus_manifest_sha256": digest,
                      "personas_file": persona_file, "personas_sha256": sha256(payloads[persona_file]),
                      "missing_history_member_ids": manifest["missing_history_member_ids"],
                      "complete_executable_roster": not manifest["missing_history_member_ids"],
                      "predictive_readiness": False})
    payloads["index.json"] = _json_bytes(index)
    result = {"version": "rolling-executable-receipt-v1", "model_calls": 0,
              "meetings_count": len(index),
              "complete_executable_meetings": sum(row["complete_executable_roster"] for row in index),
              "missing_history_member_packets": sum(len(row["missing_history_member_ids"]) for row in index),
              "source_receipt_sha256": file_hash(root / "receipt.json"),
              "output_files": {name: sha256(payload) for name, payload in sorted(payloads.items())},
              "predictive_readiness": False, "construct_validated": False,
              "environment": {"python": sys.version, "platform": platform.platform()},
              "command": sys.argv,
              "code_sha256": {"executable_rolling.py": file_hash(__file__)}}
    payloads["receipt.json"] = _json_bytes(result)
    # Detect any source change between verification and copying.
    if file_hash(root / "receipt.json") != result["source_receipt_sha256"] or any(
            sha256(source_path(root, name).read_bytes()) != digest
            for name, digest in receipt["output_files"].items()):
        raise ValueError("Rolling source changed during executable bundle construction")
    for name, payload in sorted(payloads.items()):
        _write(out / name, payload)
    return result


def verify_rolling_manifest(personas, *, source_root, corpus_manifest_path, cutoff):
    """Reconstruct v3 fields from source bytes, then bind every persona field."""
    root = Path(source_root).resolve()
    path = Path(corpus_manifest_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise GenerationProvenanceError("Rolling corpus manifest is missing or outside source root")
    try:
        manifest = _read_json(path)
        if manifest.get("version") != MANIFEST_VERSION:
            raise ValueError("Unsupported executable rolling manifest version")
        digest = file_hash(path)
        for name in ("rolling_receipt", "packet", "rosters", "protocol"):
            if file_hash(source_path(root, manifest[name + "_file"])) != manifest[name + "_sha256"]:
                raise ValueError("Missing or changed rolling corpus input " + name)
        rolling_root = (root / manifest["source_bundle_root"]).resolve()
        if not rolling_root.is_relative_to(root):
            raise ValueError("Rolling source bundle escapes the source root")
        loaded = _load_rolling(rolling_root)
        expected = _manifest(loaded, manifest["meeting_id"], prefix=manifest["source_bundle_root"].rstrip("/") + "/")
        if manifest != expected:
            raise ValueError("Rolling corpus fields differ from reconstruction from raw bytes")
        cutoff_day = cutoff.date().isoformat() if isinstance(cutoff, datetime) else cutoff
        if cutoff_day != manifest["calibration_cutoff"] or (isinstance(cutoff, datetime)
                and cutoff != datetime.fromisoformat(manifest["information_cutoff"])):
            raise ValueError("Rolling persona prediction cutoff differs from its frozen meeting cutoff")
        for persona in personas:
            expected_fields = manifest["members"].get(persona.member_id, {}).get("persona_fields")
            if expected_fields is None:
                raise ValueError("Member has missing personal history or is outside the exact realized roster")
            if persona.model_dump() != dict(expected_fields, corpus_manifest_hash=digest):
                raise ValueError("Persona fields differ from their reconstructed rolling corpus fit")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise GenerationProvenanceError(str(exc)) from exc
    return personas


def load_executable_personas(bundle_root, meeting_id, *, cutoff=None, require_complete=True):
    """Return ``(personas, verification_context)`` for one frozen meeting.

    Context has exactly ``source_root`` and ``corpus_manifest_path`` and can be
    passed unchanged to ``verify_personas``.  ``require_complete=False`` supports
    audit-only inspection of an explicitly incomplete roster, never substitution.
    """
    from src.persona_engine.provenance import verify_personas
    root = Path(bundle_root).resolve()
    receipt = _read_json(root / "receipt.json")
    if (receipt.get("version") != "rolling-executable-receipt-v1"
            or receipt.get("model_calls") != 0
            or receipt.get("predictive_readiness") is not False
            or receipt.get("construct_validated") is not False):
        raise GenerationProvenanceError("Unsupported executable persona bundle")
    for name, digest in receipt["output_files"].items():
        if file_hash(source_path(root, name)) != digest:
            raise GenerationProvenanceError("Executable persona bundle hash mismatch: " + name)
    rows = [row for row in _read_json(root / "index.json") if row["meeting_id"] == meeting_id]
    if len(rows) != 1:
        raise GenerationProvenanceError("Missing or duplicated executable meeting identity")
    row = rows[0]
    if require_complete and row["missing_history_member_ids"]:
        raise GenerationProvenanceError("Missing personal history: " + ", ".join(row["missing_history_member_ids"]))
    manifest_path = source_path(root, row["corpus_manifest_file"])
    personas_path = source_path(root, row["personas_file"])
    if (file_hash(manifest_path) != row["corpus_manifest_sha256"]
            or file_hash(personas_path) != row["personas_sha256"]):
        raise GenerationProvenanceError("Executable meeting artifact differs from its index")
    personas = [MemberPersona.model_validate(value) for value in _read_json(personas_path)]
    manifest = _read_json(manifest_path)
    expected_ids = {identifier for identifier, member in manifest["members"].items()
                    if member["persona_fields"] is not None}
    if {p.member_id for p in personas} != expected_ids or len(personas) != len(expected_ids):
        raise GenerationProvenanceError("Executable personas omit or duplicate an available personal history")
    context = {"source_root": str(root), "corpus_manifest_path": str(manifest_path)}
    prediction_cutoff = cutoff or datetime.fromisoformat(row["information_cutoff"])
    if personas:
        verify_personas(personas, prediction_cutoff, **context)
    else:
        verify_rolling_manifest([], cutoff=prediction_cutoff, **context)
    return personas, context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rolling-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = build_executable_rolling_bundle(rolling_root=args.rolling_root, output_root=args.output_root)
    print(json.dumps({key: result[key] for key in ("version", "meetings_count", "complete_executable_meetings",
          "missing_history_member_packets", "predictive_readiness", "model_calls")}, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
