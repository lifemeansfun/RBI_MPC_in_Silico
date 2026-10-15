"""Preserve official source bytes; do not replace successful retained responses.

URLs in source_catalog.json were found with primary-source web search/open. Fed
statement URLs and GDP PDF attachments are discovered from retained official
HTML hyperlinks rather than constructed from presumed naming conventions.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent
ALLOWED = {"www.federalreserve.gov", "federalreserve.gov", "www.mospi.gov.in", "mospi.gov.in", "www.pib.gov.in", "pib.gov.in", "static.pib.gov.in"}


def acquire(item: dict) -> dict:
    assert urlparse(item["url"]).hostname in ALLOWED
    path = OUT / "raw" / (item["id"] + (".pdf" if item.get("format") == "pdf" else ".html"))
    meta = path.with_suffix(path.suffix + ".metadata.json")
    if meta.exists():
        saved = json.loads(meta.read_text())
        assert hashlib.sha256((OUT / saved["local_file"]).read_bytes()).hexdigest() == saved["sha256"]
        for field in ("release_date", "printed_document_date", "release_date_basis"):
            if field in item and item[field] != saved.get(field):
                saved.setdefault("catalog_metadata_corrections", {})[field] = dict(initial=saved.get(field), corrected=item[field])
                saved[field] = item[field]
        print(item["id"], "retained", saved["acquired"], flush=True)
        return saved
    record = {**item, "retrieved_at_utc": datetime.now(timezone.utc).isoformat()}
    try:
        r = requests.get(item["url"], timeout=(15, 35), headers={"User-Agent": "Mozilla/5.0 (compatible; research-source-preservation/1.0)"})
        assert urlparse(r.url).hostname in ALLOWED
        record.update(status_code=r.status_code, final_url=r.url, response_headers={k:v for k,v in r.headers.items() if k.lower() != "set-cookie"}, bytes=len(r.content))
        if not r.ok or (item.get("format") == "pdf" and not r.content.startswith(b"%PDF")):
            path = OUT / "raw" / (item["id"] + "_failed_response.bin")
            path.write_bytes(r.content)
            record.update(acquired=False, error="HTTP failure or expected PDF header missing")
        else:
            path.write_bytes(r.content)
            record.update(acquired=True)
        record.update(local_file=str(path.relative_to(OUT)), sha256=hashlib.sha256(r.content).hexdigest())
    except Exception as e:
        record.update(acquired=False, error=f"{type(e).__name__}: {e}")
    if "local_file" in record:
        meta.write_text(json.dumps(record, indent=2) + "\n")
    print(item["id"], "acquired" if record["acquired"] else "FAILED", record.get("bytes", ""), flush=True)
    return record


def acquire_batch(items):
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(acquire, items))


def main():
    catalog = json.loads((OUT / "source_catalog.json").read_text())
    (OUT / "raw").mkdir(exist_ok=True)
    records = acquire_batch(catalog["sources"])
    discovered = []
    for record in records:
        if not record["acquired"] or record.get("format") == "pdf":
            continue
        soup = BeautifulSoup((OUT / record["local_file"]).read_bytes(), "html.parser")
        for a in soup.find_all("a", href=True):
            url = urljoin(record["url"], a["href"])
            if record["id"].startswith("fed_calendar"):
                m = re.search(r"/monetary(20\d{6})a(1?)\.htm$", url)
                if m and "20200901" <= m[1] <= "20240930":
                    role = "implementation" if m[2] else "statement"
                    discovered.append(dict(id=f"fed_{m[1]}_{role}", url=url, format="html", role=role, discovery_parent_id=record["id"], discovery_parent_sha256=record["sha256"]))
            elif record.get("role") == "gdp_release_html" and url.lower().endswith(".pdf") and urlparse(url).hostname in ALLOWED:
                discovered.append(dict(id=record["id"] + "_attachment", url=url, format="pdf", role="gdp_release_pdf", release_date=record["release_date"], reference_period=record.get("reference_period", ""), discovery_parent_id=record["id"], discovery_parent_sha256=record["sha256"]))
    unique = {d["id"]: d for d in discovered}
    records += acquire_batch(list(unique.values()))
    # Historical 2020 calendar links statements; statements themselves link notes.
    more = []
    ids = {r["id"] for r in records}
    for r in records:
        if r.get("role") != "statement" or not r["acquired"]:
            continue
        soup = BeautifulSoup((OUT / r["local_file"]).read_bytes(), "html.parser")
        for a in soup.find_all("a", href=True):
            url = urljoin(r["url"], a["href"])
            m = re.search(r"/monetary(20\d{6})a1\.htm$", url)
            if m and f"fed_{m[1]}_implementation" not in ids:
                more.append(dict(id=f"fed_{m[1]}_implementation", url=url, format="html", role="implementation", discovery_parent_id=r["id"], discovery_parent_sha256=r["sha256"]))
    records += acquire_batch(more)
    (OUT / "retrieval_manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    (OUT / "discovered_source_catalog.json").write_text(json.dumps({"sources": list(unique.values()) + more}, indent=2) + "\n")
    print("Acquired", sum(r["acquired"] for r in records), "of", len(records), flush=True)


if __name__ == "__main__":
    main()
