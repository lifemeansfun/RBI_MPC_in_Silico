"""Offline integrity/source consistency QA, not independent label adjudication."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import platform
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    catalog = json.loads(ROOT.joinpath("source_catalog.json").read_text())
    labels = json.loads(ROOT.joinpath("meeting_label_ledger.json").read_text())
    records = catalog["records"]
    sources = {r["source_id"]: r for r in records}
    checks = []

    def require(name, condition, details=None):
        checks.append({"check": name, "passed": bool(condition), "details": details})

    require("all retained source hashes match", all(sha(ROOT/r["raw_path"]) == r["sha256"] for r in records))
    require("all source URLs are official", all(urlparse(r["url"]).hostname in ("www.rbi.org.in", "rbi.org.in") for r in records))
    require("all 34 enumerated sources retained", len(records) == 34 and all(r["acquisition_status"] == "retained" for r in records))
    require("all source dates no later than as-of date", all(r["publication_date"] <= "2026-10-08" for r in records))
    require("consecutive meeting identifiers 51 through 63", [m["meeting_number"] for m in labels["meetings"]] == list(range(51, 64)))
    require("unique ordered decision dates", [m["decision_date"] for m in labels["meetings"]] == sorted(set(m["decision_date"] for m in labels["meetings"])))
    require("six unique roster members in every meeting", all(len(m["roster_ids"]) == len(set(m["roster_ids"])) == 6 for m in labels["meetings"]))
    require("78 aligned member records", len(labels["member_ballots"]) == 78 and len({(b["meeting_id"], b["member_id"]) for b in labels["member_ballots"]}) == 78)
    for m in labels["meetings"]:
        start, decision = date.fromisoformat(m["meeting_start_date"]), date.fromisoformat(m["decision_date"])
        require("meeting and decision dates match retained title " + m["decision_date"],
                start.strftime("%B") in m["meeting_title"] and str(start.day) in m["meeting_title"] and
                decision.strftime("%B") in m["meeting_title"] and str(decision.day) in m["meeting_title"] and str(decision.year) in m["meeting_title"])
        require("cutoff precedes meeting " + m["decision_date"], m["information_cutoff_day"] < m["meeting_start_date"] <= m["decision_date"])
        require("member roster aligned " + m["decision_date"], {b["member_id"] for b in labels["member_ballots"] if b["meeting_id"] == m["meeting_id"]} == set(m["roster_ids"]))
        if m["minutes_source_id"]:
            rows = sources[m["minutes_source_id"]]["vote_tables"]
            require("single complete source rate table " + m["decision_date"], len(rows) == 1 and len(rows[0]) == 7)
        require("finite rate level and exact basis-point change " + m["decision_date"],
                abs((m["policy_repo_after_pct"]-m["policy_repo_before_pct"])*100 - m["policy_change_bps"]) < 1e-9)
    latest = labels["meetings"][-1]
    require("October 2026 minutes not backfilled before scheduled release", latest["minutes_source_id"] is None and latest["minutes_publication_date"] is None and latest["minutes_scheduled_publication_date"] == "2026-10-21")
    # Validate every quoted substring and referenced retained-source hash, recursively.
    quote_count = 0
    bad_quotes = []

    def visit(obj):
        nonlocal quote_count
        if isinstance(obj, dict):
            if "text" in obj and "source_id" in obj and "source_sha256" in obj:
                quote_count += 1
                s = sources[obj["source_id"]]
                body = ROOT.joinpath(s["extracted_text_path"]).read_text()
                if obj["text"] not in body or obj["source_sha256"] != s["sha256"]:
                    bad_quotes.append(obj)
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            for value in obj:
                visit(value)
    visit(labels)
    require("all verbatim evidence excerpts and source hashes match", not bad_quotes, {"quote_count": quote_count, "bad_quote_count": len(bad_quotes)})
    june = [b for b in labels["member_ballots"] if b["decision_date"] == "2025-06-06" and b["member_id"] == "saugata_bhattacharya"][0]
    require("June 2025 Yes is preserved alongside smaller magnitude disagreement", june["published_rate_vote_cell"] == "Yes" and june["preferred_rate_change_bps"] == -25 and june["rate_choice_disagrees_with_resolution"] is True)
    april = [b for b in labels["member_ballots"] if b["decision_date"] == "2025-04-09" and b["member_id"] == "saugata_bhattacharya"][0]
    require("April prior reservation not promoted to final stance disagreement", april["documented_prior_reservation"] is True and april["stated_stance_preference"] == "accommodative" and april["stated_stance_preference_disagrees_with_resolution"] is False)
    require("unproved formal stance ballots stay missing", sum(b["explicit_formal_stance_vote"] is None for b in labels["member_ballots"]) == 58)
    require("reservation negative evidence not invented", all(b["documented_prior_reservation"] in (None, True) for b in labels["member_ballots"]))
    require("72 available full statements", sum(1 for _ in ROOT.joinpath("member_statements.jsonl").open()) == 72)
    distribution = collections.Counter(m["policy_direction"] for m in labels["meetings"])
    require("rate directions retained without outcome exclusion", distribution == {"hold": 8, "cut": 4, "increase": 1}, dict(distribution))
    # Future scheduled meetings explicitly remain missing and outside the as-of panel.
    availability = [{"meeting_id": m["meeting_id"], "meeting_start_date": m["meeting_start_date"], "decision_date": m["decision_date"],
                     "resolution_status": "retained", "minutes_status": m["minutes_availability_status"],
                     "scheduled_minutes_date": m["minutes_scheduled_publication_date"], "in_as_of_panel": True} for m in labels["meetings"]]
    for start, decision in (("2026-12-02", "2026-12-04"), ("2027-02-03", "2027-02-05")):
        availability.append({"meeting_id": "rbi_mpc_"+decision, "meeting_start_date": start, "decision_date": decision,
            "resolution_status": "future scheduled meeting; no observed decision", "minutes_status": "future scheduled meeting; no source",
            "scheduled_minutes_date": None, "in_as_of_panel": False})
    ROOT.joinpath("availability_ledger.json").write_text(json.dumps({"as_of_date": "2026-10-08", "future_schedule_source_id": "rbi_prid_62422", "meetings": availability}, indent=2)+"\n")
    artifacts = {str(p.relative_to(ROOT)): sha(p) for p in ROOT.rglob("*") if p.is_file() and p.name != "source_qa.json" and p.suffix != ".log"}
    report = {"scope": "Offline source integrity, calendar/roster/choice consistency; not independent empirical or label validation", "python": sys.version,
              "platform": platform.platform(), "checks": checks, "passed": all(c["passed"] for c in checks),
              "source_records": len(records), "panel_meetings": 13, "member_records": 78,
              "available_full_statements": 72, "raw_retained_source_sha256": {r["source_id"]: r["sha256"] for r in records},
              "artifacts_sha256": artifacts,
              "remaining_missing": ["October 2026 individual minutes until Oct 21", "Exact first posting times", "Contemporaneous archive hashes",
                  "Independent double-coded labels", "Exhaustive reservations/guidance adjudication", "Expanded macro/persona information packets"],
              "failed_checks": [c for c in checks if not c["passed"]]}
    ROOT.joinpath("source_qa.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks), "quoted_excerpts_verified": quote_count, "action_distribution": dict(distribution)}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
