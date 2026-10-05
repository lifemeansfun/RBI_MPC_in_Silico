"""Prepare source pointers from local minutes, without validating release vintages.

Run from the project root:
    .venv/bin/python research/review_process/data_preparation/build_cpi_context_preparation.py

Only this script's directory is written. Existing research code/data are read only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
MONTHS = {
    name: n for n, name in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"], 1
    )
}

# Manual source adjudications checked against the raw numbered paragraphs.
# Fields: paragraph, reference period as reported, latest reference month,
# reported period value, explicit individual-month value, additional evidence.
OBSERVATIONS = {
    "50560": (8, "July-August 2020", "2020-08", "6.7", "", []),
    "50831": (8, "October 2020", "2020-10", "7.6", "7.6", []),
    "51161": (8, "December 2020", "2020-12", "4.6", "4.6", []),
    "51456": (8, "February 2021", "2021-02", "5.0", "5.0", []),
    "51754": (9, "April 2021", "2021-04", "4.3", "4.3", []),
    "52088": (10, "June 2021", "2021-06", "6.3", "6.3", []),
    "52450": (11, "August 2021", "2021-08", "5.3", "5.3", []),
    "52843": (11, "October 2021", "2021-10", "4.5", "4.5", []),
    "53319": (11, "December 2021", "2021-12", "5.6", "5.6", []),
    "53601": (11, "February 2022", "2022-02", "6.1", "6.1", []),
    "53728": (9, "March 2022", "2022-03", "7.0", "7.0", []),
    "53904": (10, "April 2022", "2022-04", "7.8", "7.8", []),
    "54236": (8, "May-June 2022", "2022-06", "7.0", "", [18]),
    "54541": (10, "August 2022", "2022-08", "7.0", "7.0", []),
    "54918": (10, "October 2022", "2022-10", "6.8", "6.8", []),
    "55267": (10, "December 2022", "2022-12", "5.7", "5.7", []),
    "55538": (10, "February 2023", "2023-02", "6.4", "6.4", []),
    "55899": (10, "April 2023", "2023-04", "4.7", "4.7", []),
    "56252": (10, "June 2023", "2023-06", "4.8", "4.8", []),
    "56606": (10, "August 2023", "2023-08", "6.8", "6.8", []),
    "56982": (9, "October 2023", "2023-10", "4.9", "4.9", []),
    "57366": (9, "December 2023", "2023-12", "5.7", "5.7", []),
    "57735": (9, "January-February 2024", "2024-02", "5.1", "5.1", [16, 53]),
    "58136": (9, "April 2024", "2024-04", "4.8", "4.8", []),
    "58545": (9, "June 2024", "2024-06", "5.1", "5.1", []),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def title_and_date(soup: BeautifulSoup) -> tuple[str, str]:
    titles = set()
    for node in soup.find_all(["strong", "b", "p", "td"]):
        text = " ".join(node.get_text(" ", strip=True).split())
        if text.startswith("Minutes of the Monetary Policy Committee Meeting") and len(text) < 180:
            titles.add(text)
    assert len(titles) == 1, titles
    title = titles.pop()
    # Parse the title itself, never the earlier publication date. Handles ranges
    # and nonconsecutive lists, including April 3, 5 and 6 and May 2 and 4.
    pattern = r"(" + "|".join(MONTHS) + r")\s+([\d\s,\-–andto]+),\s*(\d{4})$"
    match = re.search(pattern, title)
    assert match, title
    day_values = [int(x) for x in re.findall(r"\d+", match.group(2))]
    assert day_values and all(1 <= d <= 31 for d in day_values)
    decision = date(int(match.group(3)), MONTHS[match.group(1)], max(day_values)).isoformat()
    return title, decision


def paragraph(soup: BeautifulSoup, number: int) -> tuple[str, int]:
    matches = []
    for node in soup.find_all("p"):
        text = " ".join(node.get_text(" ", strip=True).split())
        if text.startswith(f"{number}.") and len(text) < 2500:
            matches.append((text, node.sourceline))
    assert len(matches) == 1, (number, len(matches))
    return matches[0]


def first_sentence(text: str) -> str:
    text = re.sub(r"^\d+\.\s*", "", text)
    return re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]


def main() -> None:
    panel_path = ROOT / "data/processed/macro_panel.parquet"
    panel = pd.read_parquet(panel_path)
    panel_by_date = panel.set_index("meeting_date").to_dict("index")
    manifest_path = ROOT / "data/raw/manifest.csv"
    manifest = list(csv.DictReader(manifest_path.open(newline="")))
    assert len(manifest) == len(OBSERVATIONS) == len(panel) == 25
    rows = []
    for item in manifest:
        source = ROOT / "data/raw/minutes_html" / item["local_filename"]
        calculated = sha(source)
        assert calculated == item["sha256"], source
        soup = BeautifulSoup(source.read_text(), "html.parser")
        title, decision = title_and_date(soup)
        assert title == item["title"], (title, item["title"])
        number, period, reference_month, value, individual, extras = OBSERVATIONS[item["prid"]]
        text, line = paragraph(soup, number)
        assert value in text and "inflation" in text.lower()
        reference_year, reference_month_number = map(int, reference_month.split("-"))
        month_name = next(name for name, n in MONTHS.items() if n == reference_month_number)
        assert month_name in text, (source, reference_month)
        extra_texts = []
        for n in extras:
            additional, _ = paragraph(soup, n)
            additional = re.sub(r"^\d+\.\s*", "", additional)
            sentences = re.split(r"(?<=[.!?])\s+", additional)
            selected = next((sentence for sentence in sentences if value in sentence), sentences[0])
            extra_texts.append(f"Paragraph {n}: {selected}")
        if item["prid"] == "57735":
            assert "February was 5.1 per cent" in extra_texts[0]
            assert "5.1 per cent in each of the months" in extra_texts[1]
        panel_date = "2022-05-18" if decision == "2022-05-04" else decision
        assert panel_date in panel_by_date
        year_basis = "explicit_in_paragraph" if str(reference_year) in text else "calendar_context_from_decision_title"
        ambiguity = ""
        if not individual:
            ambiguity = "Value is stated for a combined two-month period; no standalone latest-month level is assigned."
        if item["prid"] == "57735":
            ambiguity = "Resolution groups January-February; paragraphs 16 and 53 explicitly corroborate February at 5.1%."
        if year_basis == "calendar_context_from_decision_title":
            ambiguity = (ambiguity + " " if ambiguity else "") + "Reference year inferred from past-month narrative and decision-year context."
        rows.append({
            "decision_date_from_title": decision,
            "existing_panel_meeting_date": panel_date,
            "existing_panel_headline_cpi_yoy_pct": panel_by_date[panel_date]["cpi_headline_yoy_pct"],
            "manifest_meeting_month": item["meeting_date"],
            "manifest_month_agrees_with_title": str(item["meeting_date"] == decision[:7]).lower(),
            "latest_reference_month": reference_month,
            "reference_period_as_reported": period,
            "reported_period_cpi_yoy_pct": value,
            "standalone_latest_month_cpi_yoy_pct": individual,
            "reference_year_basis": year_basis,
            "cpi_source_paragraph": number,
            "corroborating_paragraphs": ";".join(map(str, extras)),
            "source_file": str(source.relative_to(ROOT)),
            "source_html_line": line,
            "source_title": title,
            "source_url": item["url"],
            "source_sha256": calculated,
            "evidence_excerpt": first_sentence(text),
            "additional_evidence_excerpt": " | ".join(extra_texts),
            "ambiguity_or_context_note": ambiguity,
            "release_timestamp_verified": "false",
            "vintage_validated": "false",
        })
    rows.sort(key=lambda row: row["decision_date_from_title"])
    assert len(set(row["decision_date_from_title"] for row in rows)) == 25
    assert all(row["latest_reference_month"] < row["decision_date_from_title"][:7] for row in rows)
    csv_path = OUT / "minutes_cpi_context_preparation.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    checks = {
        "documents": len(rows),
        "verified_manifest_hashes": len(rows),
        "titles_matching_manifest_titles": len(rows),
        "unique_decision_dates": len(set(row["decision_date_from_title"] for row in rows)),
        "explicit_standalone_month_values": sum(bool(row["standalone_latest_month_cpi_yoy_pct"]) for row in rows),
        "combined_period_only_rows": [row["decision_date_from_title"] for row in rows if not row["standalone_latest_month_cpi_yoy_pct"]],
        "panel_date_mismatches": [row["decision_date_from_title"] for row in rows if row["decision_date_from_title"] != row["existing_panel_meeting_date"]],
        "manifest_month_mismatches": [row["decision_date_from_title"] for row in rows if row["manifest_month_agrees_with_title"] == "false"],
        "manifest_sha256": sha(manifest_path),
        "macro_panel_sha256": sha(panel_path),
        "preparation_script_sha256": sha(Path(__file__)),
        "output_csv_sha256": sha(csv_path),
        "release_timestamp_verified": False,
        "vintage_validated": False,
    }
    (OUT / "preparation_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
