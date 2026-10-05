"""
Automated RBI MPC Minutes Crawler.
Queries official press release archive on rbi.org.in across the primary benchmark panel (2020-2024),
identifies MPC Minutes press releases, downloads raw HTML, and records SHA256 checksums in manifest.csv.
"""

import hashlib
import time
import re
import csv
import logging
from pathlib import Path
from typing import Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("rbi_mpc.crawler")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class MinutesCrawler:
    """Robust crawler for Reserve Bank of India MPC Minutes archive."""

    BASE_URL = "https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, raw_dir: Optional[Path] = None):
        self.raw_dir = raw_dir or (PROJECT_ROOT / "data" / "raw" / "minutes_html")
        self.manifest_path = PROJECT_ROOT / "data" / "raw" / "manifest.csv"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._init_manifest()

    def _init_manifest(self) -> None:
        if not self.manifest_path.exists():
            with open(self.manifest_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["prid", "meeting_date", "title", "url", "sha256", "local_filename"])

    def fetch_month_releases(self, year: int, month: int, session: requests.Session) -> list[dict]:
        """Queries RBI press release archive for a specific month/year."""
        # 1. Initial GET to obtain fresh __VIEWSTATE and __EVENTVALIDATION
        r = session.get(self.BASE_URL, headers=self.HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        viewstate = soup.find("input", id="__VIEWSTATE")["value"]
        viewgen = soup.find("input", id="__VIEWSTATEGENERATOR")["value"]
        eventval = soup.find("input", id="__EVENTVALIDATION")["value"]

        data = {
            "__EVENTTARGET": "btn",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewgen,
            "__EVENTVALIDATION": eventval,
            "hdnYear": str(year),
            "hdnMonth": str(month),
            "btn": "Submit",
        }

        # 2. POST to retrieve the month's press releases
        r2 = session.post(self.BASE_URL, data=data, headers=self.HEADERS, timeout=20)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        results = []
        for a in soup2.find_all("a", href=True):
            text = a.get_text().strip()
            href = a["href"]
            if "Minutes of the Monetary Policy Committee" in text and "prid=" in href:
                prid_match = re.search(r"prid=(\d+)", href)
                if prid_match:
                    prid = prid_match.group(1)
                    full_url = f"https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid={prid}"
                    results.append({
                        "prid": prid,
                        "title": text,
                        "url": full_url,
                        "year": year,
                        "month": month,
                    })

        return results

    def download_minutes(self, prid: str, url: str, session: requests.Session) -> tuple[Path, str]:
        """Downloads single minutes HTML and computes SHA256 checksum."""
        r = session.get(url, headers=self.HEADERS, timeout=20)
        r.raise_for_status()

        html_content = r.content
        sha256 = hashlib.sha256(html_content).hexdigest()

        filename = f"mpc_minutes_prid_{prid}.html"
        file_path = self.raw_dir / filename
        with open(file_path, "wb") as f:
            f.write(html_content)

        return file_path, sha256

    def crawl_panel(self, start_year: int = 2020, end_year: int = 2024) -> list[dict]:
        """Crawls all bimonthly meetings across the specified year range."""
        session = requests.Session()
        all_downloaded = []

        # Target bimonthly meeting schedule: Feb, Apr, Jun, Aug, Oct, Dec (+ May 2022 off-cycle)
        months_to_check = [2, 4, 5, 6, 8, 10, 12]

        print(f"[+] Crawling RBI MPC Minutes archive from {start_year} to {end_year}...")
        for year in range(start_year, end_year + 1):
            for month in months_to_check:
                # Skip pre-October 2020
                if year == 2020 and month < 10:
                    continue
                # Skip post-August 2024
                if year == 2024 and month > 8:
                    continue

                try:
                    releases = self.fetch_month_releases(year, month, session)
                    for rel in releases:
                        prid = rel["prid"]
                        print(f"    Found: {rel['title'][:65]} (PRID: {prid})")
                        file_path, sha256 = self.download_minutes(prid, rel["url"], session)

                        # Extract meeting date from title
                        date_str = f"{year}-{month:02d}"
                        rel["sha256"] = sha256
                        rel["local_filename"] = file_path.name
                        rel["meeting_date"] = date_str

                        # Append to manifest
                        with open(self.manifest_path, "a", newline="", encoding="utf-8") as f:
                            writer = csv.writer(f)
                            writer.writerow([prid, date_str, rel["title"], rel["url"], sha256, file_path.name])

                        all_downloaded.append(rel)
                    time.sleep(0.5)  # Polite crawling delay
                except Exception as e:
                    logger.warning("Failed querying %d-%02d: %s", year, month, str(e))
                    time.sleep(1.0)

        print(f"[+] Finished crawl. Total MPC minutes harvested: {len(all_downloaded)}")
        return all_downloaded


if __name__ == "__main__":
    crawler = MinutesCrawler()
    # Test crawling 2023-2024
    crawler.crawl_panel(start_year=2023, end_year=2024)
