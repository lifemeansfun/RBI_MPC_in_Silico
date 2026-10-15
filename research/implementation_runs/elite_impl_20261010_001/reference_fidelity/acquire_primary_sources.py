"""Bounded public primary-source acquisition; no credentials, retries or bypasses."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import urllib.error
import urllib.request

DESTINATION = Path(__file__).resolve().parent
ROOT = DESTINATION.parents[3]
RETAINED = ROOT / "research/source_ledgers/literature/current_oct09/acquisition_attempt_001/gwu_fomc_2025.pdf"
TARGETS = (
    ("fedsight_arxiv_2512_15728v1", "https://arxiv.org/pdf/2512.15728v1", "pdf"),
    ("takano_arxiv_2511_02469v1", "https://arxiv.org/pdf/2511.02469v1", "pdf"),
    ("acl_2025_findings_606", "https://aclanthology.org/2025.findings-acl.606.pdf", "pdf"),
    ("gwu_current_2025_005", "https://www2.gwu.edu/~forcpgm/2025-005.pdf", "pdf"),
    ("ssrn_record_5424097", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5424097", "html"),
    ("ssrn_papers_delivery_5424097", "https://papers.ssrn.com/sol3/Delivery.cfm?abstractid=5424097", "bin"),
    ("ssrn_download_delivery_5424097", "https://download.ssrn.com/sol3/Delivery.cfm?abstractid=5424097", "bin"),
    ("stanford_publication", "https://digitaleconomy.stanford.edu/publication/fomc-in-silico-a-multi-agent-system-for-monetary-policy-decision-modeling/", "html"),
    ("gwu_working_papers", "https://cer.columbian.gwu.edu/working-papers", "html"),
)


def acquire(target):
    identity, url, extension = target
    record = {"id": identity, "url": url, "accessed_at_utc": datetime.now(timezone.utc).isoformat(),
              "request_timeout_seconds": 35, "max_attempts": 1, "credentials": False}
    body = b""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Research evidence acquisition (public sources)"})
        try:
            response = urllib.request.urlopen(request, timeout=35)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read(12_000_001)
            record.update(status_code=response.code, final_url=response.geturl(),
                          content_type=response.headers.get("Content-Type"))
        if len(body) > 12_000_000:
            record.update(status="failed", error="12 MB bound exceeded; response not retained")
            body = b""
        else:
            record.update(status="acquired" if record["status_code"] == 200 else "http_failure")
    except Exception as error:
        record.update(status="failed", error_type=type(error).__name__, error=str(error))
    if body:
        path = DESTINATION / "sources" / f"{identity}.{extension}"
        with path.open("xb") as handle:
            handle.write(body)
        record.update(file=str(path.relative_to(DESTINATION)), sha256=hashlib.sha256(body).hexdigest(),
                      bytes=len(body), valid_pdf_magic=body.startswith(b"%PDF-"))
    return record


def main():
    (DESTINATION / "sources").mkdir(parents=True, exist_ok=True)
    retained_hash = hashlib.sha256(RETAINED.read_bytes()).hexdigest()
    if retained_hash != "bb87d87e450d7a73206ab8845afc21d595dd6a3965c4a23b647f53f28ca70914":
        raise RuntimeError("Retained GWU source differs from its recorded original hash")
    retained_copy = DESTINATION / "sources/gwu_retained_august_2025.pdf"
    with retained_copy.open("xb") as handle:
        handle.write(RETAINED.read_bytes())
    records = [{"id": "gwu_retained_august_2025", "status": "copied_retained_exact_bytes",
                "url": "https://www2.gwu.edu/~forcpgm/2025-005.pdf", "source_file": str(RETAINED.relative_to(ROOT)),
                "file": str(retained_copy.relative_to(DESTINATION)), "sha256": retained_hash,
                "bytes": retained_copy.stat().st_size, "valid_pdf_magic": True,
                "accessed_at_utc": datetime.now(timezone.utc).isoformat()}]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records.extend(pool.map(acquire, TARGETS))
    document = {"scope": "Public primary-source retrieval, internal research reference preservation; no authentication or retries",
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "records": records}
    with (DESTINATION / "retrieval_records.json").open("x") as handle:
        json.dump(document, handle, indent=2)
    print(json.dumps(document, indent=2))


if __name__ == "__main__":
    main()
