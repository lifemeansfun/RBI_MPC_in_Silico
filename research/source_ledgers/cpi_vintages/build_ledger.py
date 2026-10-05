"""Build a preparation ledger from retained original CPI release documents.

Offline command:
    .venv/bin/python research/source_ledgers/cpi_vintages/build_ledger.py

Does not modify the historical research inputs or declare the full macro panel valid.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
IST = timezone(timedelta(hours=5, minutes=30))
MONTHS = {name: i for i, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}
MONTH_PATTERN = "|".join(MONTHS)
DATE_PATTERN = rf"\b(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*({MONTH_PATTERN})\s*,?\s*(\d{{4}})\b"

# Manual transcription from the first/current Provisional Combined columns,
# checked against the retained sources. This is a check, not a fallback series.
ADJUDICATED_VALUES = {
    "2020-08": ("6.69", "9.05"), "2020-10": ("7.61", "11.07"),
    "2020-12": ("4.59", "3.41"), "2021-02": ("5.03", "3.87"),
    "2021-04": ("4.29", "2.02"), "2021-06": ("6.26", "5.15"),
    "2021-08": ("5.30", "3.11"), "2021-10": ("4.48", "0.85"),
    "2021-12": ("5.59", "4.05"), "2022-02": ("6.07", "5.85"),
    "2022-03": ("6.95", "7.68"), "2022-04": ("7.79", "8.38"),
    "2022-06": ("7.01", "7.75"), "2022-08": ("7.00", "7.62"),
    "2022-10": ("6.77", "7.01"), "2022-12": ("5.72", "4.19"),
    "2023-02": ("6.44", "5.95"), "2023-04": ("4.70", "3.84"),
    "2023-06": ("4.81", "4.49"), "2023-08": ("6.83", "9.94"),
    "2023-10": ("4.87", "6.61"), "2023-12": ("5.69", "9.53"),
    "2024-02": ("5.09", "8.66"), "2024-04": ("4.83", "8.70"),
    "2024-06": ("5.08", "9.36"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_date(text: str) -> date:
    match = re.search(DATE_PATTERN, text, re.I)
    assert match, text
    name = next(name for name in MONTHS if name.lower() == match.group(2).lower())
    return date(int(match.group(3)), MONTHS[name], int(match.group(1)))


def previous_month(month: str) -> str:
    year, n = map(int, month.split("-"))
    return f"{year - (n == 1):04d}-{12 if n == 1 else n - 1:02d}"


def extract_rows(extracted: dict) -> tuple[list[str], list[str], str]:
    if "pages" in extracted:
        text = extracted["pages"][0]["text"]
        cpi_line = next(line for line in text.splitlines()
                        if "CPI (General)" in line and re.search(r"\d+\.\d+", line))
        cfpi_line = next(line for line in text.splitlines()
                         if re.match(r"CFPI\s+[\d.-]", line))
        cpi = re.findall(r"-?\d+\.\d+", cpi_line)
        cfpi = re.findall(r"-?\d+\.\d+", cfpi_line)
        tables = [(page["page"], i + 1, table) for page in extracted["tables"]
                  for i, table in enumerate(page["tables"])]
    else:
        cpi = cfpi = None
        tables = [(None, i + 1, table) for i, table in enumerate(extracted["tables"])]
    # Pick the original inflation summary; reject an index/month-change table.
    matches = []
    for page, index, table in tables:
        flattened = " ".join(str(cell or "") for row in table for cell in row)
        if "Prov." not in flattened or "Final" not in flattened:
            continue
        cpi_rows = [row for row in table if any("CPI" in str(cell) and "General" in str(cell) for cell in row)]
        cfpi_rows = [row for row in table if any(str(cell).strip() == "CFPI" for cell in row)]
        if not cpi_rows or not cfpi_rows:
            continue
        values_cpi = [str(cell) for cell in cpi_rows[0] if re.fullmatch(r"-?\d+\.\d+", str(cell))]
        values_cfpi = [str(cell) for cell in cfpi_rows[0] if re.fullmatch(r"-?\d+\.\d+", str(cell))]
        if len(values_cpi) < 6 or len(values_cfpi) < 6 or max(map(float, values_cpi[:6])) > 40:
            continue
        matches.append((values_cpi, values_cfpi,
                        f"PDF page {page}, table {index}" if page else f"HTML table {index}"))
    assert matches, extracted["source_file"]
    geometry_cpi, geometry_cfpi, pointer = matches[0]
    if cpi is not None:
        assert cpi == geometry_cpi and cfpi == geometry_cfpi, extracted["source_file"]
    return geometry_cpi, geometry_cfpi, pointer


def source_record(record: dict) -> dict:
    path = OUT / record["local_file"]
    assert sha(path) == record["sha256"]
    extracted_path = OUT / "extracted" / (path.stem + ".json")
    extracted = json.loads(extracted_path.read_text())
    text = " ".join((" ".join(page["text"] for page in extracted["pages"])
                     if "pages" in extracted else extracted["text"]).split())
    cpi, cfpi, pointer = extract_rows(extracted)
    assert (cpi[2], cfpi[2]) == ADJUDICATED_VALUES[record["reference_month"]]
    if "pages" in extracted:
        header = text.split("GOVERNMENT OF INDIA")[0]
        assert "embargoed" in header.lower() and re.search(r"5[.:]30\s*pm", header, re.I)
        release_day = parse_date(header)
        release_at = datetime.combine(release_day, time(17, 30), IST)
        basis = "MoSPI release embargo endpoint; India local time"
        timestamp_evidence = header
    else:
        posted = re.search(r"(?:Posted On:|प्रविष्टि तिथि:)\s*(\d{1,2})\s+([A-Z]{3})\s+(\d{4})\s+(\d{1,2}):(\d{2})(AM|PM)\s+by PIB\s+\w+", text)
        assert posted, record["reference_month"]
        release_day = datetime.strptime(" ".join(posted.group(i) for i in [1, 2, 3]), "%d %b %Y").date()
        hour = int(posted.group(4)) % 12 + (12 if posted.group(6) == "PM" else 0)
        release_at = datetime.combine(release_day, time(hour, int(posted.group(5))), IST)
        basis = "PIB Posted On timestamp; PIB Delhi / India local time"
        timestamp_evidence = posted.group(0)
    assert release_day.strftime("%Y-%m") == (
        f"{int(record['reference_month'][:4]) + 1}-01" if record["reference_month"].endswith("-12")
        else f"{int(record['reference_month'][:4]):04d}-{int(record['reference_month'][5:]) + 1:02d}")
    next_pointer = text.find("Next date of release")
    assert next_pointer >= 0
    next_excerpt = text[next_pointer:next_pointer + 240]
    next_day = parse_date(next_excerpt)
    assert next_day > release_day
    return dict(reference_month=record["reference_month"], vintage="Provisional", series_base="2012=100",
                geography="All India Combined", headline_cpi_yoy_pct=cpi[2], cfpi_yoy_pct=cfpi[2],
                previous_final_reference_month=previous_month(record["reference_month"]),
                previous_final_headline_cpi_yoy_pct=cpi[5], previous_final_cfpi_yoy_pct=cfpi[5],
                documented_release_timestamp_ist=release_at.isoformat(),
                documented_release_timestamp_utc=release_at.astimezone(timezone.utc).isoformat(),
                release_timestamp_basis=basis, timestamp_evidence=timestamp_evidence,
                next_scheduled_release_date=next_day.isoformat(), next_release_evidence=next_excerpt,
                source_url=record["requested_url"], local_source_file=record["local_file"],
                source_sha256=record["sha256"], retrieved_at_utc=record["retrieved_at_utc"],
                source_table_pointer=pointer, extracted_evidence_file=str(extracted_path.relative_to(OUT)),
                cpi_summary_row_values=cpi, cfpi_summary_row_values=cfpi,
                first_website_availability_independently_measured=False,
                contemporaneous_archive_hash_available=False)


def write_csv(name: str, rows: list[dict]) -> None:
    with (OUT / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    retrieval = json.loads((OUT / "retrieval_manifest.json").read_text())
    releases = []
    for month in sorted(ADJUDICATED_VALUES):
        successful = [record for record in retrieval if record["reference_month"] == month and record["acquired"]]
        assert successful, month
        # Prefer the primary release; if it failed, use the verified PIB fallback.
        primary = next((record for record in successful if record["role"] == "url"), successful[0])
        releases.append(source_record(primary))
        if month == "2024-02":
            corroboration = json.loads((OUT / "extracted/2024-02_additional_url.json").read_text())
            cpi, cfpi, _ = extract_rows(corroboration)
            assert (cpi[2], cfpi[2]) == ADJUDICATED_VALUES[month]
    context_path = ROOT / "research/review_process/data_preparation/minutes_cpi_context_preparation.csv"
    contexts = list(csv.DictReader(context_path.open()))
    assert len(contexts) == len(releases) == 25
    meetings = []
    for context in contexts:
        title = context["source_title"]
        match = re.search(rf"({MONTH_PATTERN})\s+([\d\s,\-–andto]+),\s*(\d{{4}})$", title)
        assert match, title
        days = list(map(int, re.findall(r"\d+", match.group(2))))
        start = date(int(match.group(3)), MONTHS[match.group(1)], min(days))
        end = date(int(match.group(3)), MONTHS[match.group(1)], max(days))
        assert end.isoformat() == context["decision_date_from_title"]
        soup = BeautifulSoup((ROOT / context["source_file"]).read_text(), "html.parser")
        assert title in " ".join(soup.get_text(" ", strip=True).split())
        cutoff_exclusive = datetime.combine(start, time(0), IST)
        available = [release for release in releases
                     if datetime.fromisoformat(release["documented_release_timestamp_ist"]) < cutoff_exclusive]
        chosen = max(available, key=lambda release: release["documented_release_timestamp_ist"])
        assert chosen["reference_month"] == context["latest_reference_month"]
        assert date.fromisoformat(chosen["next_scheduled_release_date"]) >= start
        meetings.append(dict(decision_date=end.isoformat(), meeting_start_date=start.isoformat(),
            information_cutoff_day=(start - timedelta(days=1)).isoformat(),
            cutoff_exclusive_ist=cutoff_exclusive.isoformat(),
            reference_month=chosen["reference_month"], vintage=chosen["vintage"],
            headline_cpi_yoy_pct=chosen["headline_cpi_yoy_pct"], cfpi_yoy_pct=chosen["cfpi_yoy_pct"],
            documented_release_timestamp_ist=chosen["documented_release_timestamp_ist"],
            documented_release_timestamp_utc=chosen["documented_release_timestamp_utc"],
            release_timestamp_basis=chosen["release_timestamp_basis"],
            next_scheduled_release_date=chosen["next_scheduled_release_date"],
            latest_selection_basis="Latest retained release before meeting start; next scheduled release is after cutoff",
            source_url=chosen["source_url"], local_source_file=chosen["local_source_file"],
            source_sha256=chosen["source_sha256"], source_table_pointer=chosen["source_table_pointer"],
            existing_panel_meeting_date=context["existing_panel_meeting_date"],
            existing_panel_headline_cpi_yoy_pct=context["existing_panel_headline_cpi_yoy_pct"],
            meeting_title=title, meeting_minutes_file=context["source_file"],
            meeting_minutes_sha256=sha(ROOT / context["source_file"]),
            preparation_status="Source-backed CPI/CFPI release ledger; full macro panel remains unvalidated",
            unexpected_intermediate_or_correction_releases_exhaustively_ruled_out="false"))
    versions = []
    for release in releases:
        for vintage, month, headline, food in [
            ("Provisional", release["reference_month"], release["headline_cpi_yoy_pct"], release["cfpi_yoy_pct"]),
            ("Final", release["previous_final_reference_month"], release["previous_final_headline_cpi_yoy_pct"], release["previous_final_cfpi_yoy_pct"]),
        ]:
            versions.append(dict(release_reference_month=release["reference_month"], reference_month=month,
                vintage=vintage, headline_cpi_yoy_pct=headline, cfpi_yoy_pct=food,
                documented_release_timestamp_ist=release["documented_release_timestamp_ist"],
                source_url=release["source_url"], local_source_file=release["local_source_file"],
                source_sha256=release["source_sha256"], source_table_pointer=release["source_table_pointer"]))
    write_csv("meeting_cpi_ledger.csv", meetings)
    write_csv("release_vintages.csv", versions)
    checks = dict(meetings=len(meetings), release_months=len(releases), recorded_vintages=len(versions),
                  acquired_original_documents=sum(record["acquired"] for record in retrieval),
                  failed_source_attempts=sum(not record["acquired"] for record in retrieval),
                  all_release_timestamps_before_meeting_start=True,
                  all_next_scheduled_release_dates_after_cutoff=True,
                  all_current_combined_values_match_manual_source_adjudication=True,
                  all_primary_pdf_rate_rows_match_geometry_tables=True,
                  full_macro_panel_validated=False,
                  python=platform.python_version(), platform=platform.platform(),
                  source_catalog_sha256=sha(OUT / "source_catalog.json"),
                  context_preparation_sha256=sha(context_path),
                  legacy_macro_panel_sha256=sha(ROOT / "data/processed/macro_panel.parquet"),
                  script_sha256=sha(Path(__file__)),
                  output_csv_sha256=sha(OUT / "meeting_cpi_ledger.csv"))
    bundle = dict(scope="All India Combined CPI-General / CFPI, base 2012=100; source acquisition preparation",
                  information_cutoff="Exclusive midnight at meeting start in IST, including the previous calendar day",
                  limitations=["Documented embargo or PIB posting times are retained; first web availability was not independently measured.",
                               "No exhaustive search ruled out unexpected intermediate correction/re-release documents.",
                               "Retrieved bytes are currently hosted original release files; there are no independently archived contemporaneous hashes.",
                               "CPI/CFPI only. Core CPI, other macro series, personas, labels and evaluation design remain outside this ledger."],
                  checks=checks, release_records=releases, meeting_records=meetings,
                  missing_release_months=[], failed_retrievals=[record for record in retrieval if not record["acquired"]])
    (OUT / "cpi_release_ledger.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    (OUT / "ledger_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    print(json.dumps(checks, indent=2))
    for meeting in meetings:
        print(meeting["decision_date"], meeting["reference_month"], meeting["headline_cpi_yoy_pct"],
              meeting["cfpi_yoy_pct"], meeting["documented_release_timestamp_ist"])


if __name__ == "__main__":
    main()
