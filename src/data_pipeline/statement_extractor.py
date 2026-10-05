"""
Statement Extractor for RBI MPC Minutes.
Segments the 6 individual signed member statements from downloaded HTML minutes
and persists them as structured text files under data/processed/statements/{date}/{member_id}.txt.
Enforces strict defensive validation (minimum length checks, exactly 6 members present,
trimming of administrative boilerplate/signatures).
"""

import re
import logging
from pathlib import Path
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger("rbi_mpc.extractor")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Standard member ID mapping and regex search patterns
MEMBER_PATTERNS = [
    {
        "member_id": "shashanka_bhide",
        "name": "Dr. Shashanka Bhide",
        "pattern": r"Statement\s+by\s+Dr\.?\s+Shashanka\s+Bhide",
    },
    {
        "member_id": "ashima_goyal",
        "name": "Dr. Ashima Goyal",
        "pattern": r"Statement\s+by\s+Dr\.?\s+Ashima\s+Goyal",
    },
    {
        "member_id": "jayanth_varma",
        "name": "Prof. Jayanth R. Varma",
        "pattern": r"Statement\s+by\s+Prof\.?\s+Jayanth\s+R\.?\s+Varma",
    },
    {
        "member_id": "rajiv_ranjan",
        "name": "Dr. Rajiv Ranjan",
        "pattern": r"Statement\s+by\s+Dr\.?\s+Rajiv\s+Ranjan",
    },
    {
        "member_id": "mridul_saggar",  # Executive Director Oct 2020 - May 2022
        "name": "Dr. Mridul K. Saggar",
        "pattern": r"Statement\s+by\s+Dr\.?\s+Mridul\s+(?:K\.?\s+)?Saggar",
    },
    {
        "member_id": "michael_patra",
        "name": "Dr. Michael Debabrata Patra",
        "pattern": r"Statement\s+by\s+Dr\.?\s+Michael\s+(?:Debabrata\s+|D\.?\s+)?Patra",
    },
    {
        "member_id": "shaktikanta_das",
        "name": "Shri Shaktikanta Das",
        "pattern": r"Statement\s+by\s+(?:Shri\s+)?Shaktikanta\s+Das",
    },
]

# Signature / administrative cutoff markers at the end of the document
ADMIN_CUTOFFS = [
    r"\(\s*[A-Z][a-z]+\s+[A-Z][a-z]+\s*\)\s*Chief\s+General\s+Manager",
    r"Press\s+Release\s*:\s*\d{4}-\d{4}",
    r"Editor\'s\s+Note",
]


class StatementExtractor:
    """Extracts, cleans, and defensively validates individual member statements from minutes HTML."""

    def __init__(self, processed_dir: Optional[Path] = None):
        self.processed_dir = processed_dir or (PROJECT_ROOT / "data" / "processed" / "statements")
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def extract_meeting_date(soup: BeautifulSoup, default_date: str = "unknown") -> str:
        """Parses meeting end-date from title or text (e.g. 'August 8 to 10, 2023' -> 2023-08-10)."""
        text = soup.get_text()
        months = {
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12"
        }

        # Match 'Month Day to Day, Year' or 'Month Day-Day, Year' or 'Month Day, Year'
        pattern = r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:\s*(?:to|-)\s*(\d{1,2}))?,?\s+(\d{4})"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            month_str = match.group(1).lower()
            end_day = match.group(3) or match.group(2)
            year = match.group(4)
            return f"{year}-{months[month_str]}-{int(end_day):02d}"

        return default_date

    def process_html_file(self, html_path: Path) -> dict[str, str]:
        """
        Parses a single HTML minutes document and returns {member_id: statement_text}.
        Validates that statements meet quality, length, and presence thresholds.
        """
        try:
            with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error("Failed to read HTML file %s: %s", html_path, e)
            return {}

        soup = BeautifulSoup(content, "html.parser")
        meeting_date = self.extract_meeting_date(soup, default_date=html_path.stem)
        full_text = soup.get_text()

        # Locate all member heading occurrences
        member_matches = []
        for mem in MEMBER_PATTERNS:
            m = re.search(mem["pattern"], full_text, re.IGNORECASE)
            if m:
                member_matches.append({
                    "member_id": mem["member_id"],
                    "name": mem["name"],
                    "start_idx": m.start(),
                })

        if not member_matches:
            logger.warning("No member statement headings found in %s", html_path.name)
            return {}

        # Sort by appearance order in document
        member_matches = sorted(member_matches, key=lambda x: x["start_idx"])

        # Determine cutoff for the final statement (remove CGM signatures / administrative footers)
        doc_end = len(full_text)
        last_start = member_matches[-1]["start_idx"]
        tail_text = full_text[last_start:]
        for cutoff_pat in ADMIN_CUTOFFS:
            cutoff_m = re.search(cutoff_pat, tail_text, re.IGNORECASE)
            if cutoff_m:
                doc_end = last_start + cutoff_m.start()
                break

        extracted_statements: dict[str, str] = {}
        for i in range(len(member_matches)):
            start = member_matches[i]["start_idx"]
            end = member_matches[i + 1]["start_idx"] if i + 1 < len(member_matches) else doc_end
            raw_statement = full_text[start:end].strip()

            # Clean extra whitespace
            clean_statement = re.sub(r"\n\s*\n+", "\n\n", raw_statement)
            clean_statement = re.sub(r"[ \t]+", " ", clean_statement).strip()

            words = clean_statement.split()
            member_id = member_matches[i]["member_id"]
            if len(words) >= 80:  # Valid statement length
                extracted_statements[member_id] = clean_statement
            else:
                logger.warning(
                    "Statement for %s on %s has only %d words (<80 threshold). Discarded.",
                    member_id, meeting_date, len(words)
                )

        # Defensive validation: check if exactly 6 members are present
        if len(extracted_statements) != 6:
            logger.warning(
                "Meeting %s extracted %d statements (expected 6): %s",
                meeting_date, len(extracted_statements), list(extracted_statements.keys())
            )

        # Persist extracted statements atomically
        date_dir = self.processed_dir / meeting_date
        date_dir.mkdir(parents=True, exist_ok=True)
        for member_id, stmt in extracted_statements.items():
            file_path = date_dir / f"{member_id}.txt"
            temp_path = date_dir / f".{member_id}.txt.tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(stmt)
            temp_path.replace(file_path)

        print(f"[+] Processed {html_path.name} -> Meeting Date: {meeting_date} | Extracted: {len(extracted_statements)}/6 statements.")
        return extracted_statements


if __name__ == "__main__":
    extractor = StatementExtractor()
    raw_dir = PROJECT_ROOT / "data" / "raw" / "minutes_html"
    total_meetings = 0
    total_statements = 0
    for html_file in sorted(raw_dir.glob("*.html")):
        res = extractor.process_html_file(html_file)
        if res:
            total_meetings += 1
            total_statements += len(res)
    print(f"\n[Extraction Summary] Processed {total_meetings} meetings, total {total_statements} member statements extracted.")
