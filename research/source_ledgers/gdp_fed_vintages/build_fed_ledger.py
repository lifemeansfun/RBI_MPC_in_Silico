"""Offline source-linked Fed target range and RBI meeting cutoff ledger."""
from __future__ import annotations
import csv
import hashlib
import json
import math
import re
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def flat(path):
    return BeautifulSoup(path.read_bytes(), "html.parser").get_text(" ", strip=True).replace("\u2011", "-").replace("\u2010", "-").replace("\u00a0", " ")

def rate(s):
    s = s.strip()
    if "-" in s:
        whole, fraction = s.split("-")
        return float(whole) + float(Fraction(fraction))
    return float(Fraction(s))

def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def main():
    manifest = json.loads((OUT / "retrieval_manifest.json").read_text())
    by_id = {r["id"]: r for r in manifest}
    releases = []
    for record in manifest:
        if record.get("role") != "implementation" or not record["acquired"]:
            continue
        p = OUT / record["local_file"]
        assert sha(p) == record["sha256"]
        text = flat(p)
        match = re.search(r"Effective ([A-Za-z]+ \d{1,2}, \d{4}), the Federal Open Market Committee directs the Desk to:? [Uu]ndertake open market operations as necessary to maintain the federal funds rate in a target range of ([\d/ .-]+) to ([\d/ .-]+) percent", text)
        assert match, record["id"]
        effective_date = datetime.strptime(match[1], "%B %d, %Y").date().isoformat()
        lo, hi = rate(match[2]), rate(match[3])
        assert math.isfinite(lo) and math.isfinite(hi) and 0 <= lo <= hi <= 20
        date = re.search(r"fed_(\d{8})_", record["id"])[1]
        released = datetime.strptime(date, "%Y%m%d").date()
        label = released.strftime("%B %-d, %Y")
        assert f"Implementation Note issued {label}" in text
        statement = by_id[f"fed_{date}_statement"]
        st = flat(OUT / statement["local_file"])
        assert label in st
        tm = re.search(r"For release at (\d{1,2}):(\d{2}) p\.m\. (E[DS]T)", st)
        assert tm, statement["id"]
        hour = int(tm[1]) % 12 + 12
        release_dt = datetime(released.year, released.month, released.day, hour, int(tm[2]), tzinfo=ZoneInfo("America/New_York"))
        assert release_dt.tzname() == tm[3]
        releases.append(dict(release_id=record["id"], release_date=released.isoformat(), documented_release_timestamp_utc=release_dt.astimezone(ZoneInfo("UTC")).isoformat(), release_timestamp_basis="FOMC statement printed For release time, America/New_York", policy_effective_date=effective_date, target_lower_pct=lo, target_upper_pct=hi, source_url=record["url"], local_source_file=record["local_file"], source_sha256=record["sha256"], source_table_pointer="Implementation Note, domestic policy directive", source_excerpt=match[0], statement_source_url=statement["url"], statement_local_source_file=statement["local_file"], statement_source_sha256=statement["sha256"], statement_release_excerpt=tm[0]))
    releases.sort(key=lambda r:r["policy_effective_date"])
    assert len({r["policy_effective_date"] for r in releases}) == len(releases)
    for i,r in enumerate(releases):
        r["valid_until_effective_date_exclusive"] = releases[i+1]["policy_effective_date"] if i+1 < len(releases) else ""
    meetings = list(csv.DictReader((ROOT / "research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv").open()))
    rows = []
    for meeting in meetings:
        cutoff = datetime.fromisoformat(meeting["cutoff_exclusive_ist"])
        usable = [r for r in releases if datetime.fromisoformat(r["documented_release_timestamp_utc"]) < cutoff and r["policy_effective_date"] <= meeting["information_cutoff_day"]]
        assert usable
        chosen = usable[-1]
        assert chosen["valid_until_effective_date_exclusive"] > meeting["meeting_start_date"]
        rows.append(dict(decision_date=meeting["decision_date"], meeting_start_date=meeting["meeting_start_date"], information_cutoff_day=meeting["information_cutoff_day"], cutoff_exclusive_ist=meeting["cutoff_exclusive_ist"], reference_period=f"Policy in force at cutoff; effective from {chosen['policy_effective_date']}", series="us_fed_target_upper_pct", value=chosen["target_upper_pct"], units="percent per annum", vintage="Dated FOMC implementation directive; current retained official bytes", latest_selection_basis="Latest effective policy directive among all retained FOMC calendar decisions; successor effective date is after meeting start", **chosen))
    assert len(rows) == 25 and len({r["decision_date"] for r in rows}) == 25
    write_csv("fed_release_vintages.csv", releases)
    write_csv("meeting_fed_ledger.csv", rows)
    checks = dict(meeting_count=len(rows), dated_fed_directives=len(releases), legacy_macro_panel_sha256=sha(ROOT / "data/processed/macro_panel.parquet"), cpi_meeting_ledger_sha256=sha(ROOT / "research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv"), meeting_fed_ledger_sha256=sha(OUT / "meeting_fed_ledger.csv"), all_release_and_effective_dates_before_cutoffs=True, successor_effective_dates_after_meeting_starts=True, effective_date_precision="Calendar date only; exact implementation instant not assumed", field_semantics="Target upper bound is not the effective federal funds rate or range midpoint")
    (OUT / "fed_ledger.json").write_text(json.dumps(dict(releases=releases, meetings=rows, checks=checks), indent=2) + "\n")
    print(json.dumps(checks, indent=2))

if __name__ == "__main__":
    main()
