"""Bounded official-RBI acquisition. Writes only this source-ledger directory."""
from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
INDEX_URL = "https://www.rbi.org.in/Scripts/Annualpolicy.aspx"
LOG = []


def fetch(url, name, *, data=None):
    dest = ROOT / "raw" / name
    for attempt in range(1, 3):
        event = {"url": url, "method": "POST" if data else "GET", "attempt": attempt,
                 "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "path": str(dest.relative_to(ROOT))}
        try:
            response = (requests.post(url, data=data, timeout=30) if data else requests.get(url, timeout=30))
            event.update(http_status=response.status_code, final_url=response.url, byte_count=len(response.content))
            response.raise_for_status()
            if response.url.split('/')[2] not in ("www.rbi.org.in", "rbi.org.in", "rbidocs.rbi.org.in"):
                raise ValueError("Redirect outside official RBI domains")
            if len(response.content) < 1500:
                raise ValueError("Unexpectedly short official response")
            if dest.exists() and dest.read_bytes() != response.content:
                # Preserve earlier successful bytes rather than silently replacing them.
                dest = dest.with_name(dest.stem + "_retrieval_" + datetime.now(timezone.utc).strftime("%H%M%S") + dest.suffix)
            dest.write_bytes(response.content)
            event.update(status="retained", path=str(dest.relative_to(ROOT)), sha256=hashlib.sha256(response.content).hexdigest())
            LOG.append(event)
            return dest, response.content
        except Exception as exc:
            event.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            LOG.append(event)
    return None, None


def main():
    ROOT.joinpath("raw").mkdir(exist_ok=True)
    ROOT.joinpath("extracted").mkdir(exist_ok=True)
    catalog = {}
    for year in (2027, 2026, 2025):
        if year == 2027:
            path, raw = fetch(INDEX_URL, "annualpolicy_2027.html")
        else:
            # Each form starts from a fresh official GET and its own validation inputs.
            _, initial = fetch(INDEX_URL, f"annualpolicy_form_{year}.html")
            if not initial:
                continue
            soup = BeautifulSoup(initial, "html.parser")
            data = {item["name"]: item.get("value", "") for item in soup.select("input[name]")}
            data["hdnYear"] = str(year)
            path, raw = fetch(INDEX_URL, f"annualpolicy_{year}.html", data=data)
        if not raw:
            continue
        soup = BeautifulSoup(raw, "html.parser")
        for a in soup.select("a[href]"):
            text = " ".join(a.get_text(" ", strip=True).split())
            href = a["href"]
            parent_text = " ".join(a.find_parent("td").get_text(" ", strip=True).split()) if a.find_parent("td") else text
            kind = None
            if text.startswith("Minutes of the Monetary Policy Committee Meeting"):
                kind = "minutes"
            elif text == "Full Document" and parent_text.startswith("Resolution of the Monetary Policy Committee"):
                kind = "resolution"
                text = parent_text.removesuffix("Full Document").strip()
            elif "Rescheduled" in text:
                kind = "reschedule"
            if kind:
                prid = parse_qs(urlparse(href).query).get("prid", [None])[0]
                if prid:
                    catalog[prid] = {"source_id": "rbi_prid_" + prid, "prid": prid, "source_kind": kind,
                                     "url": href, "index_title": text, "index_path": str(path.relative_to(ROOT))}
    for prid, kind in (("60062", "schedule"), ("62422", "schedule")):
        catalog[prid] = {"source_id": "rbi_prid_" + prid, "prid": prid, "source_kind": kind,
                         "url": f"https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid={prid}",
                         "index_title": "Schedule, discovered by primary-source navigation/search"}
    for rec in catalog.values():
        path, raw = fetch(rec["url"], rec["source_id"] + ".html")
        rec["acquisition_status"] = "retained" if path else "failed"
        if not path:
            continue
        soup = BeautifulSoup(raw, "html.parser")
        body = soup.select_one("#doublescroll")
        if body is None:
            rec["acquisition_status"] = "unexpected_content"
            continue
        text = "\n".join(" ".join(x.get_text(" ", strip=True).split()) for x in body.find_all(["p", "tr"]))
        plain = " ".join(body.get_text(" ", strip=True).split())
        pub = re.search(r"Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", plain)
        publication_date = datetime.strptime(pub[1], "%b %d, %Y").date().isoformat() if pub else None
        # Full body preserves table structure separately for offline ballot verification.
        extract = ROOT / "extracted" / (rec["source_id"] + ".txt")
        extract.write_text(plain + "\n", encoding="utf-8")
        tables = []
        for table in body.select("table"):
            rows = [[" ".join(c.get_text(" ", strip=True).split()) for c in row.find_all(["td", "th"], recursive=False)]
                    for row in table.find_all("tr") if row.find_parent("table") is table]
            if rows and rows[0][:2] == ["Member", "Vote"] and 1 < len(rows) < 15:
                tables.append(rows)
        rec.update(raw_path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(raw).hexdigest(),
                   byte_count=len(raw), extracted_text_path=str(extract.relative_to(ROOT)),
                   publication_date=publication_date, publication_time=None,
                   availability_precision="date only; no exact first-posting time proved",
                   extracted_body_character_count=len(plain), vote_tables=tables)
        print(rec["source_id"], rec["source_kind"], publication_date, len(plain), flush=True)
    ROOT.joinpath("source_catalog.json").write_text(json.dumps({"panel_as_of_date": "2026-10-08", "records": list(catalog.values())}, indent=2) + "\n")
    ROOT.joinpath("acquisition_log.json").write_text(json.dumps({"python": sys.version, "platform": platform.platform(),
        "requests_version": requests.__version__, "events": LOG}, indent=2) + "\n")


if __name__ == "__main__":
    main()
