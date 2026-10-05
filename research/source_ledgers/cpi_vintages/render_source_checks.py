"""Render original PDF first pages and compose readable table QA sheets.

Run .venv/bin/python research/source_ledgers/cpi_vintages/render_source_checks.py
Original PDF bytes are unchanged. Renders are QA evidence, not replacement sources.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pdfplumber
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent


def main() -> None:
    qa = OUT / "visual_checks"
    qa.mkdir(exist_ok=True)
    records = json.loads((OUT / "retrieval_manifest.json").read_text())
    panels = []
    for record in records:
        if not record["acquired"] or not record["local_file"].endswith(".pdf"):
            continue
        source = OUT / record["local_file"]
        destination = qa / (source.stem + "_page1")
        command = ["pdftoppm", "-f", "1", "-singlefile", "-scale-to-x", "1200",
                   "-scale-to-y", "-1", "-png", str(source), str(destination)]
        subprocess.run(command, check=True, capture_output=True)
        page_image = Image.open(destination.with_suffix(".png")).convert("RGB")
        with pdfplumber.open(source) as document:
            page = document.pages[0]
            table = page.find_tables()[0]
            scale = page_image.width / page.width
            x0, y0, x1, y1 = table.bbox
            table_image = page_image.crop((max(0, int(x0*scale) - 5), max(0, int(y0*scale) - 5),
                                          min(page_image.width, int(x1*scale) + 5),
                                          min(page_image.height, int(y1*scale) + 5)))
        panel = Image.new("RGB", (1200, table_image.height + 52), "white")
        draw = ImageDraw.Draw(panel)
        draw.text((12, 10), f"{record['reference_month']} | {source.name} | first-page inflation summary", fill="black")
        panel.paste(table_image, (12, 42))
        panels.append(panel)
        print(source.name, page_image.size, table_image.size, flush=True)
    for start in range(0, len(panels), 5):
        batch = panels[start:start + 5]
        sheet = Image.new("RGB", (1200, sum(panel.height for panel in batch) + 20*(len(batch) - 1)), "#dddddd")
        top = 0
        for panel in batch:
            sheet.paste(panel, (0, top))
            top += panel.height + 20
        name = qa / f"table_check_sheet_{start//5 + 1:02d}.png"
        sheet.save(name)
        print("Sheet", name.name, sheet.size, flush=True)


if __name__ == "__main__":
    main()
