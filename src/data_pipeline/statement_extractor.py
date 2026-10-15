"""
Statement Extractor for RBI MPC Minutes.
Segments the 6 individual signed member statements from downloaded HTML minutes
and persists them as structured text files under data/processed/statements/{date}/{member_id}.txt.
Enforces strict defensive validation (minimum length checks, exactly 6 members present,
trimming of administrative boilerplate/signatures).
"""

import re
import logging
import hashlib
import json
from datetime import date, datetime
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
        self.processed_dir = processed_dir or (PROJECT_ROOT / "data" / "processed" / "statements_v2")
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def extract_meeting_date(soup: BeautifulSoup, default_date: str = "unknown") -> str:
        """Parses meeting end-date from title or text (e.g. 'August 8 to 10, 2023' -> 2023-08-10)."""
        return StatementExtractor.extract_meeting_metadata(soup)["decision_date"]

    @staticmethod
    def extract_meeting_metadata(soup: BeautifulSoup) -> dict:
        """Parse the meeting title and publication header independently.

        No full-document date search may accidentally use the later press-release date.
        """
        months = {name.lower(): n for n, name in enumerate(
            ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"), 1)}
        titles = set()
        for node in soup.find_all(["strong", "b", "p", "td"]):
            text = " ".join(node.get_text(" ", strip=True).split())
            if text.startswith("Minutes of the Monetary Policy Committee Meeting") and len(text) < 180:
                titles.add(text)
        if len(titles) != 1:
            raise ValueError("Expected one unambiguous MPC meeting title")
        title = titles.pop()
        pattern = r"(" + "|".join(months) + r")\s+([\d\s,\-–andto]+),\s*(\d{4})$"
        match = re.search(pattern, title, re.IGNORECASE)
        if not match:
            raise ValueError(f"Unrecognized meeting title: {title}")
        days = [int(x) for x in re.findall(r"\d+", match.group(2))]
        year, month = int(match.group(3)), months[match.group(1).lower()]
        start, decision = date(year, month, min(days)), date(year, month, max(days))
        text = " ".join(soup.get_text(" ", strip=True).split())
        header = text[:text.index(title)]
        published = re.findall(r"Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", header)
        if len(published) != 1:
            raise ValueError("Missing or ambiguous minutes publication header")
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                publication = datetime.strptime(published[0], fmt).date()
                break
            except ValueError:
                continue
        else:
            raise ValueError("Unrecognized publication date")
        if publication < decision:
            raise ValueError("Minutes publication predates decision")
        return {"title": title, "meeting_start_date": start.isoformat(),
                "decision_date": decision.isoformat(), "publication_date": publication.isoformat(),
                "availability_basis": "RBI press-release header date; conservatively available after that day"}

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
        metadata = self.extract_meeting_metadata(soup)
        meeting_date = metadata["decision_date"]
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
            raise ValueError(f"Meeting {meeting_date} has {len(extracted_statements)} statements, expected 6")

        # Persist extracted statements atomically
        date_dir = self.processed_dir / meeting_date
        date_dir.mkdir(parents=True, exist_ok=True)
        for member_id, stmt in extracted_statements.items():
            file_path = date_dir / f"{member_id}.txt"
            payload = stmt.encode("utf-8")
            if file_path.exists() and file_path.read_bytes() != payload:
                raise FileExistsError(f"Refusing to overwrite a different statement: {file_path}")
            if not file_path.exists():
                with file_path.open("xb") as f:
                    f.write(payload)
        metadata.update({"source_file": str(html_path.resolve().relative_to(PROJECT_ROOT)),
                         "source_sha256": hashlib.sha256(html_path.read_bytes()).hexdigest(),
                         "statement_sha256": {m: hashlib.sha256(s.encode()).hexdigest()
                                               for m, s in extracted_statements.items()}})
        meta_path = date_dir / "source_manifest.json"
        payload = (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode()
        if meta_path.exists() and meta_path.read_bytes() != payload:
            raise FileExistsError(f"Conflicting statement metadata: {meta_path}")
        if not meta_path.exists():
            with meta_path.open("xb") as f:
                f.write(payload)

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
