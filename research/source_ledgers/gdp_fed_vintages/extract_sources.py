"""Offline text/table extraction and representative PDF render/OCR preservation.

OCR assists manual transcription; it never becomes an automatically accepted
economic observation. The original PDF bytes remain the source of record.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pdfplumber
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent
TABLE_PAGES = {
    "gdp_20200529": [8, 9], "gdp_20200831": [5], "gdp_20201127": [5],
    "gdp_20210226": [7, 8], "gdp_20210531_attachment": [7, 8],
    "gdp_20210831_attachment": [4], "gdp_20211130_attachment": [4],
    "gdp_20220228": [6, 7], "gdp_20220531": [7], "gdp_20220831": [4],
    "gdp_20221130_attachment": [4], "gdp_20230228": [9], "gdp_20230531": [7],
    "gdp_20230831_attachment": [4], "gdp_20231130": [4],
    "gdp_20240229_attachment": [9], "gdp_20240531_attachment": [13],
}
OCR_IDS = {"gdp_20200831", "gdp_20201127", "gdp_20210226", "gdp_20210531_attachment", "gdp_20220228", "gdp_20230831_attachment", "gdp_20231130", "gdp_20240531_attachment"}

def render(args):
    stem, n = args
    pdf = OUT / "raw" / (stem + ".pdf")
    prefix = OUT / "visual_checks" / f"{stem}_page{n}"
    command = ["pdftoppm", "-f", str(n), "-singlefile", "-scale-to", "2500", "-png", str(pdf), str(prefix)]
    r = subprocess.run(command, capture_output=True, text=True, check=True)
    logs = [dict(command=command, exit_code=r.returncode, stdout=r.stdout, stderr=r.stderr)]
    if stem in OCR_IDS:
        ocr_prefix = OUT / "extracted" / f"{stem}_page{n}_ocr"
        command = ["tesseract", str(prefix) + ".png", str(ocr_prefix), "-l", "eng"]
        r = subprocess.run(command, capture_output=True, text=True, check=True)
        logs.append(dict(command=command, exit_code=r.returncode, stdout=r.stdout, stderr=r.stderr))
    print(stem, n, "rendered", flush=True)
    return logs

def main():
    manifest = json.loads((OUT / "retrieval_manifest.json").read_text())
    for r in manifest:
        if not r["acquired"]:
            continue
        p = OUT / r["local_file"]
        if r.get("format") == "pdf":
            pages = []
            with pdfplumber.open(p) as pdf:
                for n, page in enumerate(pdf.pages, 1):
                    pages.append(dict(page=n, text=page.extract_text() or "", tables=page.extract_tables()))
            (OUT / "extracted" / (p.stem + ".json")).write_text(json.dumps(dict(local_source_file=r["local_file"], source_sha256=r["sha256"], pages=pages), indent=2) + "\n")
        else:
            soup = BeautifulSoup(p.read_bytes(), "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text("\n", strip=True)
            (OUT / "extracted" / (p.stem + ".txt")).write_text(text + "\n")
        print(r["id"], "extracted", flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        logs = list(pool.map(render, [(stem, n) for stem, nums in TABLE_PAGES.items() for n in nums]))
    (OUT / "render_ocr_log.json").write_text(json.dumps(logs, indent=2) + "\n")

if __name__ == "__main__":
    main()
