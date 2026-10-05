"""Extract retained authoritative documents for source adjudication (offline).

Run .venv/bin/python research/source_ledgers/cpi_vintages/extract_sources.py
Preserves page text and first-page table geometry for PDFs, all tables for HTML.
"""
from __future__ import annotations

import json
from pathlib import Path

import pdfplumber
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent


def main() -> None:
    records = json.loads((OUT / "retrieval_manifest.json").read_text())
    extraction_dir = OUT / "extracted"
    extraction_dir.mkdir(exist_ok=True)
    for record in records:
        if not record["acquired"]:
            continue
        source = OUT / record["local_file"]
        destination = extraction_dir / source.stem
        if source.suffix == ".pdf":
            with pdfplumber.open(source) as document:
                pages = [{"page": i + 1, "text": page.extract_text() or ""}
                         for i, page in enumerate(document.pages)]
                tables = [{"page": i + 1, "tables": page.extract_tables()}
                          for i, page in enumerate(document.pages[:2])]
                extracted = dict(source_file=record["local_file"], sha256=record["sha256"],
                                 page_count=len(pages), pages=pages, tables=tables,
                                 method="pdfplumber text and geometry tables")
            (destination.with_suffix(".txt")).write_text("\n\n".join(
                f"--- PAGE {page['page']} ---\n{page['text']}" for page in pages) + "\n")
        else:
            soup = BeautifulSoup(source.read_bytes(), "html.parser")
            for node in soup(["script", "style"]):
                node.decompose()
            text = soup.get_text("\n", strip=True)
            tables = []
            for table in soup.find_all("table"):
                rows = [[" ".join(cell.get_text(" ", strip=True).split())
                         for cell in row.find_all(["th", "td"], recursive=False)]
                        for row in table.find_all("tr")]
                if rows:
                    tables.append(rows)
            extracted = dict(source_file=record["local_file"], sha256=record["sha256"],
                             text=text, tables=tables, method="BeautifulSoup HTML text and table cells")
            (destination.with_suffix(".txt")).write_text(text + "\n")
        destination.with_suffix(".json").write_text(json.dumps(extracted, indent=2, ensure_ascii=False) + "\n")
        print(record["reference_month"], record["role"], extracted["method"], flush=True)


if __name__ == "__main__":
    main()
