"""Download only the authoritative exact URLs already verified by web search/open.

Run .venv/bin/python research/source_ledgers/cpi_vintages/acquire_sources.py
Each original response body is retained; no existing successful source is replaced.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent


def main() -> None:
    catalog = json.loads((OUT / "source_catalog.json").read_text())
    raw = OUT / "raw"
    raw.mkdir(exist_ok=True)
    records = []
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; research-source-preservation/1.0)"
    for item in catalog["sources"]:
        for role in ["url", "additional_url"]:
            if role not in item:
                continue
            url = item[role]
            suffix = ".pdf" if url.lower().endswith(".pdf") else ".html"
            path = raw / f"{item['reference_month']}_{role}{suffix}"
            metadata_path = path.with_suffix(path.suffix + ".metadata.json")
            if path.exists() and metadata_path.exists():
                record = json.loads(metadata_path.read_text())
                assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
                records.append(record)
                print(item["reference_month"], role, "retained", path.stat().st_size, flush=True)
                continue
            record = dict(reference_month=item["reference_month"], role=role, requested_url=url,
                          retrieved_at_utc=datetime.now(timezone.utc).isoformat(), discovery=item["discovery"])
            try:
                response = session.get(url, timeout=(15, 35))
                record.update(status_code=response.status_code, final_url=response.url,
                              response_headers={key: value for key, value in response.headers.items()
                                                if key.lower() != "set-cookie"}, bytes=len(response.content))
                body_hash = hashlib.sha256(response.content).hexdigest()
                response.raise_for_status()
                if suffix == ".pdf" and not response.content.startswith(b"%PDF"):
                    failure_path = raw / f"{item['reference_month']}_{role}_non_pdf_response.html"
                    failure_path.write_bytes(response.content)
                    record.update(failure_response_file=str(failure_path.relative_to(OUT)),
                                  failure_response_sha256=body_hash)
                    raise ValueError("Expected PDF bytes; response does not have a PDF header")
                record.update(local_file=str(path.relative_to(OUT)), sha256=body_hash,
                              acquired=True)
                path.write_bytes(response.content)
                metadata_path.write_text(json.dumps(record, indent=2) + "\n")
            except Exception as error:
                record.update(acquired=False, error=f"{type(error).__name__}: {error}")
            records.append(record)
            print(item["reference_month"], role, "acquired" if record["acquired"] else "FAILED",
                  record.get("bytes", ""), flush=True)
    (OUT / "retrieval_manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print("Acquired", sum(record["acquired"] for record in records), "of", len(records), flush=True)


if __name__ == "__main__":
    main()
