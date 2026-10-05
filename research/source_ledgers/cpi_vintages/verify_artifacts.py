"""Offline integrity and portability checks for the acquired CPI preparation.

Run .venv/bin/python research/source_ledgers/cpi_vintages/verify_artifacts.py
Writes only this directory's final_verification.json and stdout.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def credential_pattern_check() -> list[dict]:
    patterns = {
        "private_key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "github_token": r"gh[pousr]_[A-Za-z0-9]{25,}",
        "github_pat": r"github_pat_[A-Za-z0-9_]{25,}",
        "aws_access_id": r"AKIA[0-9A-Z]{16}",
        "google_key_shape": r"AIza[0-9A-Za-z_-]{30,}",
        "literal_assignment": r'''(?i)(?:api_key|secret_key|access_token|password)\s*[:=]\s*["'][^"'\n]{12,}''',
    }
    findings = []
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path.suffix in (".png", ".pdf"):
            continue
        for number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            for name, pattern in patterns.items():
                if not re.search(pattern, line):
                    continue
                assert path.parent.name == "raw" and path.suffix == ".html", (path, number, name)
                if name == "literal_assignment" and "BOOMR_API_key=" in line:
                    classification = "Public PIB browser telemetry key assignment in anonymously retrieved source HTML"
                elif name == "google_key_shape" and 'id="__VIEWSTATE"' in line:
                    classification = "Credential-shaped substring inside public PIB encoded ASP.NET VIEWSTATE"
                else:
                    raise AssertionError((str(path.relative_to(OUT)), number, name))
                findings.append(dict(file=str(path.relative_to(OUT)), line=number,
                                     pattern=name, classification=classification,
                                     secret_value_printed=False))
    return findings


def main() -> None:
    retrieval = json.loads((OUT / "retrieval_manifest.json").read_text())
    ledger = json.loads((OUT / "cpi_release_ledger.json").read_text())
    meetings = list(csv.DictReader((OUT / "meeting_cpi_ledger.csv").open()))
    vintages = list(csv.DictReader((OUT / "release_vintages.csv").open()))
    good = [row for row in retrieval if row["acquired"]]
    assert len(good) == 26 and len(meetings) == 25 and len(vintages) == 50
    assert len({row["decision_date"] for row in meetings}) == 25
    assert all((OUT / row["local_file"]).is_file() for row in good)
    assert all(sha(OUT / row["local_file"]) == row["sha256"] for row in good)
    failed = [row for row in retrieval if not row["acquired"]]
    assert all(sha(OUT / row["failure_response_file"]) == row["failure_response_sha256"]
               for row in failed)
    assert sha(ROOT / "data/processed/macro_panel.parquet") == ledger["checks"]["legacy_macro_panel_sha256"]
    assert sha(OUT / "meeting_cpi_ledger.csv") == ledger["checks"]["output_csv_sha256"]
    assert all(sha(ROOT / row["meeting_minutes_file"]) == row["meeting_minutes_sha256"] for row in meetings)
    assert all(datetime.fromisoformat(row["documented_release_timestamp_ist"]) <
               datetime.fromisoformat(row["cutoff_exclusive_ist"]) for row in meetings)
    assert all((OUT / row["local_source_file"]).is_file() and
               sha(OUT / row["local_source_file"]) == row["source_sha256"] for row in meetings)
    local_links = re.findall(r"\]\(([^)]+)\)", (OUT / "SOURCE_NOTE.md").read_text())
    local_links = [link for link in local_links if not urlparse(link).scheme]
    assert all((OUT / unquote(link.split("#")[0])).exists() for link in local_links)
    files = [path for path in OUT.rglob("*") if path.is_file()]
    pdfs = [row for row in good if row["local_file"].endswith(".pdf")]
    assert len(pdfs) == 21
    assert all((OUT / "visual_checks" / (Path(row["local_file"]).stem + "_page1.png")).is_file()
               for row in pdfs)
    assert len(list((OUT / "visual_checks").glob("table_check_sheet_*.png"))) == 5
    result = dict(successful_original_sources=26, original_pdf_sources=21, original_html_sources=5,
                  retained_failed_attempts=sum(not row["acquired"] for row in retrieval),
                  distinct_meetings=25, source_table_vintage_rows=50,
                  all_original_source_hashes_match=True, all_meeting_source_hashes_match=True,
                  all_preserved_failed_response_hashes_match=True,
                  all_release_timestamps_before_conservative_cutoff=True,
                  legacy_macro_panel_hash_unchanged=True, local_note_links_resolve=True,
                  visual_qa=dict(inspected_pdf_first_page_summary_tables=21,
                                 inspected_contact_sheets=5,
                                 findings="Current/final labels, Combined columns and transcribed values agree; no table clipping found",
                                 basis="Manual inspection of the five rendered contact sheets using view_image"),
                  credential_pattern_scan=dict(unexplained_findings=0,
                                               classified_public_source_matches=credential_pattern_check(),
                                               note="Patterns are a limited check; original anonymous public source HTML is preserved unchanged"),
                  full_macro_panel_validated=False,
                  file_count=len(files), total_bytes=sum(path.stat().st_size for path in files),
                  largest_file=max(((path.stat().st_size, str(path.relative_to(OUT))) for path in files)),
                  python=platform.python_version(), platform=platform.platform(),
                  verification_script_sha256=sha(Path(__file__)))
    (OUT / "final_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
