"""Offline, source-backed expansion. Curated fields are validated against retained RBI text."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
# Consecutive official meeting order; never selected on predicted/model outcomes.
# start, decision, minutes PRID, resolution PRID, resulting repo, change bps, stance
MEETINGS = [
    ("2024-10-07", "2024-10-09", "58958", "58850", 6.50, 0, "neutral"),
    ("2024-12-04", "2024-12-06", "59347", "59244", 6.50, 0, "neutral"),
    ("2025-02-05", "2025-02-07", "59818", "59692", 6.25, -25, "neutral"),
    ("2025-04-07", "2025-04-09", "60279", "60176", 6.00, -25, "accommodative"),
    ("2025-06-04", "2025-06-06", "60686", "60604", 5.50, -50, "neutral"),
    ("2025-08-04", "2025-08-06", "61056", "60957", 5.50, 0, "neutral"),
    ("2025-09-29", "2025-10-01", "61433", "61332", 5.50, 0, "neutral"),
    ("2025-12-03", "2025-12-05", "61856", "61749", 5.25, -25, "neutral"),
    ("2026-02-04", "2026-02-06", "62261", "62169", 5.25, 0, "neutral"),
    ("2026-04-06", "2026-04-08", "62599", "62514", 5.25, 0, "neutral"),
    ("2026-06-03", "2026-06-05", "62974", "62863", 5.25, 0, "neutral"),
    ("2026-08-03", "2026-08-05", "63403", "63287", 5.25, 0, "neutral"),
    ("2026-10-05", "2026-10-07", None, "63742", 5.50, 25, "calibrated_tightening"),
]
NAMES = {
    "nagesh_kumar": "Nagesh Kumar", "saugata_bhattacharya": "Saugata Bhattacharya", "ram_singh": "Ram Singh",
    "rajiv_ranjan": "Rajiv Ranjan", "michael_debabrata_patra": "Michael Debabrata Patra",
    "shaktikanta_das": "Shaktikanta Das", "m_rajeshwar_rao": "Rajeshwar Rao",
    "sanjay_malhotra": "Sanjay Malhotra", "poonam_gupta": "Poonam Gupta", "indranil_bhattacharyya": "Indranil Bhattacharyya",
}


def member_id(text):
    found = [key for key, name in NAMES.items() if name in text]
    if len(found) != 1:
        raise ValueError(f"Ambiguous member identity: {text}")
    return found[0]


def paragraphs(source):
    soup = BeautifulSoup(ROOT.joinpath(source["raw_path"]).read_bytes(), "html.parser").select_one("#doublescroll")
    blocks = []
    active = None
    statements = {}
    for elem in soup.find_all(lambda e: e.name == "p" or (e.name == "span" and "head" in e.get("class", []))):
        text = " ".join(elem.get_text(" ", strip=True).split())
        if not text:
            continue
        if text.startswith("Statement by"):
            active = member_id(text)
            statements[active] = []
        elif active:
            statements[active].append(text)
        else:
            blocks.append(text)
    return blocks, statements


def quote(text, source, *, pointer):
    # The whitespace-normalized extract is the text cited by all labels.
    body = ROOT.joinpath(source["extracted_text_path"]).read_text()
    if text not in body:
        raise ValueError("Excerpt is not present in retained source")
    return {"text": text, "pointer": pointer, "source_id": source["source_id"], "source_url": source["url"],
            "source_path": source["raw_path"], "source_sha256": source["sha256"]}


def paragraph_pointer(text):
    match = re.match(r"(\d+)\.", text)
    return "paragraph " + match[1] if match else "statement text or nested list item"


def csv_write(name, rows):
    with ROOT.joinpath(name).open("w", newline="", encoding="utf-8") as handle:
        out = csv.DictWriter(handle, fieldnames=list(rows[0]))
        out.writeheader()
        for row in rows:
            out.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                          for key, value in row.items()})


def main():
    catalog = json.loads(ROOT.joinpath("source_catalog.json").read_text())
    sources = {r["prid"]: r for r in catalog["records"]}
    meeting_rows, ballot_rows, statement_rows = [], [], []
    evidence = []
    prior_repo = 6.50
    for ordinal, (start, decision, minutes_prid, resolution_prid, repo, change, stance) in enumerate(MEETINGS, 51):
        res = sources[resolution_prid]
        mins = sources.get(minutes_prid) if minutes_prid else None
        label_source = mins or res
        if label_source["acquisition_status"] != "retained":
            raise ValueError(f"Required label source not retained: {label_source['source_id']}")
        blocks, statements = paragraphs(label_source)
        text = ROOT.joinpath(label_source["extracted_text_path"]).read_text()
        res_blocks, _ = paragraphs(res)
        roster_excerpt = next(p for p in blocks if ((p.startswith("2.") and "members" in p) or
                              (p.startswith("1.") and "MPC members" in p) or
                              (p.startswith("The Monetary") and "MPC members" in p)))
        roster = [key for key, name in NAMES.items() if name in roster_excerpt]
        assert len(roster) == 6, (decision, roster)
        assert res["publication_date"] == decision
        assert abs((repo-prior_repo)*100-change) < 1e-9
        assert "calibrated tightening" in text if stance == "calibrated_tightening" else stance in text.lower()
        assert re.search(rf"{repo:.2f}|{repo:.1f}", text)
        if mins:
            assert mins["publication_date"] == (date.fromisoformat(decision)+timedelta(days=14)).isoformat()
            assert set(statements) == set(roster), (decision, set(statements), set(roster))
        decision_quotes = [quote(p, label_source, pointer=paragraph_pointer(p)) for p in blocks if
                           ("policy repo rate" in p and any(w in p.lower() for w in ("voted", "decided", "unchanged"))) or
                           ("stance" in p and ("voted" in p or "However" in p or "Two members" in p))]
        meeting_title = label_source["index_title"]
        expected_pub = (date.fromisoformat(decision)+timedelta(days=14)).isoformat()
        publication_quote = next(p for p in res_blocks if "minutes of the MPC" in p and "published" in p)
        meet = {
            "meeting_id": "rbi_mpc_"+decision, "meeting_number": ordinal, "meeting_start_date": start,
            "meeting_title": meeting_title, "date_source_id": label_source["source_id"],
            "date_source_sha256": label_source["sha256"],
            "decision_date": decision, "information_cutoff_exclusive_ist": start+"T00:00:00+05:30",
            "information_cutoff_day": (date.fromisoformat(start)-timedelta(days=1)).isoformat(),
            "panel_role": "retrospective expansion; not prospective or untouched evaluation",
            "roster_ids": roster, "roster_source_excerpt": quote(roster_excerpt, label_source, pointer=paragraph_pointer(roster_excerpt)),
            "policy_repo_before_pct": prior_repo, "policy_repo_after_pct": repo, "policy_change_bps": change,
            "policy_direction": "cut" if change < 0 else "increase" if change > 0 else "hold",
            "committee_stance": stance, "resolution_source_id": res["source_id"],
            "resolution_publication_date": res["publication_date"], "resolution_publication_time": None,
            "minutes_source_id": mins["source_id"] if mins else None,
            "minutes_publication_date": mins["publication_date"] if mins else None,
            "minutes_scheduled_publication_date": expected_pub,
            "minutes_availability_status": "retained" if mins else "scheduled after as-of date; not yet available",
            "minutes_publication_schedule_excerpt": quote(publication_quote, res, pointer=paragraph_pointer(publication_quote)),
            "release_time_precision": "documented calendar day only; exact first availability time unknown",
            "formal_rate_choice_disagreements": [], "explicit_formal_stance_vote_disagreements": [],
            "stated_stance_preference_disagreements": [],
            "decision_evidence": decision_quotes,
        }
        voting_table = mins["vote_tables"][0] if mins else None
        if mins:
            assert len(mins["vote_tables"]) == 1
            assert len(voting_table) == 7
        for member in roster:
            individual = statements.get(member, [])
            own_stance = [p for p in individual if any(word in p.lower() for word in
                          ("stance", "neutral", "accommodative", "calibrated tightening"))]
            own_vote = [p for p in individual if "vote" in p.lower() or "support" in p.lower()]
            # Preserve the committee's published Yes/No separately from rate magnitude.
            # June 2025 records six Yes votes on *reducing*, with one smaller magnitude.
            if voting_table:
                row = next(row for row in voting_table[1:] if member_id(row[0]) == member)
                published_vote = row[1]
                published_magnitude = int(row[2]) if len(row) == 3 else None
                preferred_change = -published_magnitude if published_magnitude is not None else change
                if published_vote == "No":
                    assert decision in ("2024-10-09", "2024-12-06")
                    preferred_change = -25
                vote_basis = "official rate table; ascribed choice/magnitude, not narrative prediction"
                rate_evidence = {"source_id": mins["source_id"], "pointer": "Voting on the Resolution table",
                                 "table_header": voting_table[0], "verbatim_cells": row, "source_sha256": mins["sha256"]}
            else:
                assert "voted unanimously to increase" in text
                preferred_change, published_vote, published_magnitude = change, None, None
                vote_basis = "explicit unanimous rate resolution plus attended six-member roster; no individual minutes yet"
                rate_evidence = decision_quotes
            rate_disagreement = preferred_change != change
            if rate_disagreement:
                meet["formal_rate_choice_disagreements"].append(member)
            # Curated stated positions, each supported below by its own statement or
            # a named resolution excerpt. This is broader than explicit formal voting.
            preferred_stance = stance
            if (decision == "2025-10-01" and member in ("nagesh_kumar", "ram_singh")) or \
               (decision in ("2025-12-05", "2026-02-06") and member == "ram_singh"):
                preferred_stance = "accommodative"
            if decision == "2026-10-07":
                preferred_stance = "neutral" if member in ("nagesh_kumar", "ram_singh") else None
            if preferred_stance is not None:
                stance_disagreement = preferred_stance != stance
                if stance_disagreement:
                    meet["stated_stance_preference_disagreements"].append(member)
            else:
                stance_disagreement = None
            # Only explicit 'voted' attribution to stance is a confirmed formal stance vote.
            # Narrative 'view/support/propose' stays a position, with formal ballot null.
            formal_stance = None
            formal_basis = "no separate formal stance ballot proven; retain stated position independently"
            formal_quote = []
            if decision in ("2024-10-09", "2024-12-06"):
                formal_stance = "neutral"
                formal_basis = "resolution explicitly attributes neutral stance votes to all six named members"
                formal_quote = [p for p in blocks if "voted" in p and "stance" in p and NAMES[member] in p]
            elif decision == "2025-02-07":
                formal_stance = "neutral"
                formal_basis = "resolution explicitly says MPC unanimously voted to continue with neutral stance"
                formal_quote = [p for p in blocks if "unanimously voted" in p and "neutral stance" in p]
            # Member-specific vote wording must explicitly vote *on* stance, not merely
            # a rate vote adjacent to a preference; these reviewed exceptions are explicit.
            elif decision == "2025-08-06" and member == "saugata_bhattacharya":
                formal_stance = "neutral"
                formal_basis = "own statement explicitly votes status quo in both repo rate and stance"
                formal_quote = [p for p in own_stance if p.startswith("31.")]
            elif decision == "2026-02-06" and member == "nagesh_kumar":
                formal_stance = "neutral"
                formal_basis = "own statement explicitly votes status quo on both repo rate and stance"
                formal_quote = [p for p in own_stance if p.startswith("23.")]
            if formal_stance is not None:
                assert formal_quote
            # Reservations/guidance differences are supported positive annotations;
            # other rows remain unassessed, never silently negative.
            reservation = True if decision == "2025-04-09" and member == "saugata_bhattacharya" else None
            guidance = True if decision == "2025-04-09" and member == "saugata_bhattacharya" else None
            note = "" if mins else "Member's full statement not yet published; stance preferences only for named minority."
            if decision == "2025-06-06" and member == "saugata_bhattacharya":
                note = "Published Yes is assent to rate reduction; 25 vs 50 bps is a distinct magnitude disagreement."
            if reservation:
                note = "Prior reservation was explicitly followed by concurrence; do not label it a final stance dissent."
            stance_excerpts = own_stance if mins else [p for p in res_blocks if "Two members" in p and NAMES[member] in p]
            rec = {
                "meeting_id": meet["meeting_id"], "decision_date": decision, "member_id": member, "member_name": NAMES[member],
                "published_rate_vote_cell": published_vote, "published_rate_reduction_magnitude_bps": published_magnitude,
                "preferred_rate_change_bps": preferred_change, "rate_choice_disagrees_with_resolution": rate_disagreement,
                "rate_evidence_basis": vote_basis, "rate_source_evidence": rate_evidence,
                "explicit_formal_stance_vote": formal_stance,
                "explicit_formal_stance_vote_disagrees_with_resolution": formal_stance != stance if formal_stance else None,
                "formal_stance_evidence_basis": formal_basis,
                "formal_stance_excerpts": [quote(p, label_source, pointer=paragraph_pointer(p)) for p in formal_quote],
                "stated_stance_preference": preferred_stance,
                "stated_stance_preference_disagrees_with_resolution": stance_disagreement,
                "stance_position_source_excerpts": [quote(p, label_source, pointer=paragraph_pointer(p)) for p in stance_excerpts],
                "documented_prior_reservation": reservation, "documented_guidance_qualification": guidance,
                "reservation_or_guidance_candidate_excerpts": [quote(p, label_source, pointer=paragraph_pointer(p))
                    for p in individual if "reservation" in p.lower() or "guidance" in p.lower()],
                "candidate_excerpt_selection_basis": "lexical retrieval aid only; not exhaustive or a disagreement label",
                "reservation_and_guidance_status": "positive curated April case; other rows unassessed, not negative",
                "annotation_status": "single source-collector extraction; independent double coding not performed",
                "ambiguity_note": note,
            }
            if mins:
                assert own_stance, (decision, member, "No stance-position evidence")
                if preferred_stance == "accommodative":
                    assert any("accommodative" in p.lower() for p in own_stance)
                statement_rows.append({"meeting_id": meet["meeting_id"], "decision_date": decision, "member_id": member,
                                       "source_id": mins["source_id"], "source_sha256": mins["sha256"],
                                       "minutes_publication_date": mins["publication_date"],
                                       "statement_paragraphs": individual,
                                       "use_constraint": "evaluation/retrospective evidence; unavailable at own meeting cutoff"})
            ballot_rows.append(rec)
        meeting_rows.append(meet)
        prior_repo = repo
    ROOT.joinpath("meeting_label_ledger.json").write_text(json.dumps({
        "schema_version": 1, "as_of_date": "2026-10-08", "selection_rule": "Consecutive official meetings since 2024-10-01; include all decisions and preserve not-yet-published minutes as missing",
        "meetings": meeting_rows, "member_ballots": ballot_rows,
        "limitations": ["Retrospective, exposed panel, not prospective evidence", "Single extraction with no independent double coding",
            "Formal stance votes remain null unless explicitly attributed as votes; positions remain separately recorded",
            "Reservation/guidance flags are positive annotations for one clear case; other cases remain unassessed",
            "No macro information expansion was performed; full model inputs are not ready",
            "Source bytes were retrieved currently; no contemporaneous immutable publication hashes proved"]}, indent=2, ensure_ascii=False)+"\n")
    csv_write("meeting_ledger.csv", meeting_rows)
    csv_write("member_ballot_ledger.csv", ballot_rows)
    with ROOT.joinpath("member_statements.jsonl").open("w") as handle:
        for row in statement_rows:
            handle.write(json.dumps(row, ensure_ascii=False)+"\n")
    print(json.dumps({"meetings": len(meeting_rows), "member_records": len(ballot_rows), "available_member_statements": len(statement_rows)}, indent=2))


if __name__ == "__main__":
    main()
