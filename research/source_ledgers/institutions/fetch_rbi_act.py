"""Retain an official Act copy and identify MPC provision pages for inspection."""
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import requests

HERE = Path(__file__).resolve().parent
SOURCES = [
    "https://www.indiacode.nic.in/bitstream/123456789/2398/1/a1934-2.pdf",
    "https://financialservices.gov.in/sites/default/files/Act-Policies/2026-01/The-Reserve-Bank-of-India-Act--1934.pdf",
]


def main():
    raw_dir = HERE / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    if (HERE / "source_record.json").exists():
        raise FileExistsError("Existing source record is preserved; use another acquisition directory for a new version")
    failures = []
    for url in SOURCES:
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError("Source returned non-PDF bytes")
            source = raw_dir / "rbi_act_1934.pdf"
            source.write_bytes(response.content)
            pages = []
            with pdfplumber.open(io.BytesIO(response.content)) as document:
                for i, page in enumerate(document.pages):
                    text = page.extract_text() or ""
                    if "45ZI." in text or "45ZL." in text:
                        pages.append({"pdf_page": i + 1, "text": text})
                        (HERE / f"page_{i+1}.txt").write_text(text + "\n")
                        page.to_image(resolution=130).save(HERE / f"page_{i+1}.png")
            record = {
                "url": url,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "bytes": len(response.content),
                "content_type": response.headers.get("Content-Type"),
                "provision_pages": [p["pdf_page"] for p in pages],
                "failed_sources": failures,
                "scope": "Source acquisition and page location only; legal interpretation and visual inspection are separate checks.",
            }
            (HERE / "source_record.json").write_text(json.dumps(record, indent=2) + "\n")
            print(json.dumps(record))
            return
        except Exception as exc:
            failures.append({"url": url, "error_type": type(exc).__name__})
    (HERE / "acquisition_failures.json").write_text(json.dumps(failures, indent=2) + "\n")
    raise RuntimeError("No official PDF source was acquired; see acquisition_failures.json")


if __name__ == "__main__":
    main()
