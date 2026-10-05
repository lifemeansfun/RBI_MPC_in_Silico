"""Offline methodology audit. Writes only beside this script; never calls an API.

Reproduce from repository root:
    .venv/bin/python results/methodology_audit_2026-10-05/data_probe.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import platform
import re
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Fail closed if a future edit attempts network access during this audit.
def deny_network(*args, **kwargs):
    raise AssertionError("This methodology probe must remain offline")

socket.create_connection = deny_network
socket.socket.connect = deny_network

import pandas as pd
import yaml
from bs4 import BeautifulSoup
from src.data_pipeline.macro_builder import HISTORICAL_PANEL_DATA
from src.data_pipeline.statement_extractor import StatementExtractor
from src.persona_engine.extractor import PersonaExtractor, ROSTER_META
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.data_pipeline.fred_client import FREDClient, FRED_SERIES


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


input_paths = sorted((ROOT / "data/raw").rglob("*"))
input_paths += sorted((ROOT / "data/processed").rglob("*"))
input_paths += sorted((ROOT / "personas").rglob("*"))
input_paths = [p for p in input_paths if p.is_file()]
before = {str(p.relative_to(ROOT)): sha(p) for p in input_paths}

panel = pd.read_parquet(ROOT / "data/processed/macro_panel.parquet")
manifest = pd.read_csv(ROOT / "data/raw/manifest.csv")
raw_dir = ROOT / "data/raw/minutes_html"
extractor = StatementExtractor(processed_dir=OUT / "reextracted_statements")
extraction_log = io.StringIO()
manifest_checks = []
source_evidence = []
byte_equal = []
normalized_full_matches = []

for row in manifest.to_dict("records"):
    path = raw_dir / row["local_filename"]
    manifest_checks.append({"file": path.name, "recorded_sha256": row["sha256"], "calculated_sha256": sha(path), "match": row["sha256"] == sha(path)})
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text()
    date = StatementExtractor.extract_meeting_date(soup)
    with contextlib.redirect_stdout(extraction_log):
        statements = extractor.process_html_file(path)
    full_norm = " ".join(raw_text.split())
    for member, text in statements.items():
        existing = ROOT / "data/processed/statements" / date / f"{member}.txt"
        byte_equal.append({"meeting_date": date, "member": member, "existing_present": existing.exists(), "equal": existing.exists() and existing.read_text(encoding="utf-8") == text})
        if existing.exists():
            norm = " ".join(existing.read_text(encoding="utf-8").split())
            normalized_full_matches.append({"meeting_date": date, "member": member, "full_text_in_associated_raw": norm in full_norm})

    # Evidence before the first member statement excludes later anecdotal inflation references.
    statement_pos = re.search(r"Statement\s+by\s+", raw_text, flags=re.I)
    prefix = raw_text[:statement_pos.start()] if statement_pos else raw_text
    paragraphs = []
    for element in soup.find_all("p"):
        text = element.get_text(" ", strip=True)
        if text and text in " ".join(prefix.split()) and any(key in text.lower() for key in ["was held during", "headline", "cpi inflation", "voted", "expressed reservations"]):
            paragraphs.append(text)
    evidence_lines = [i for i, line in enumerate(html.splitlines(), 1) if any(key in line.lower() for key in ["was held during", "headline", "voted", "expressed reservations"])]
    source_evidence.append({"file": path.name, "manifest_title": row["title"], "manifest_date": row["meeting_date"], "extractor_date": date, "member_count": len(statements), "source_lines": evidence_lines, "resolution_paragraphs": paragraphs})

(OUT / "data_extraction_stdout.txt").write_text(extraction_log.getvalue())

persona_extractor = PersonaExtractor(output_dir=OUT / "unused_persona_output")
persona_summaries = []
for member in ROSTER_META:
    corpus = persona_extractor.load_member_corpus(member)
    full = persona_extractor.analyze_member(member)
    calibration = {d: t for d, t in corpus.items() if d <= "2023-04-06"}
    holdout = {d: t for d, t in corpus.items() if d > "2023-04-06"}
    original_loader = persona_extractor.load_member_corpus
    persona_extractor.load_member_corpus = lambda member_id, c=calibration: c
    cal = persona_extractor.analyze_member(member)
    persona_extractor.load_member_corpus = original_loader
    persisted = yaml.safe_load((ROOT / "personas/2020_2024_roster" / f"{member}.yaml").read_text())
    persona_summaries.append({"member": member, "full_meeting_count": len(corpus), "calibration_meeting_count": len(calibration), "holdout_meeting_count": len(holdout), "latest_corpus_date": max(corpus), "full_calibrated_score": full["calibrated_hawk_dove"], "calibration_only_score": cal["calibrated_hawk_dove"], "persisted_score": persisted["hawk_dove_score"], "persisted_matches_full": persisted["hawk_dove_score"] == full["calibrated_hawk_dove"], "full_words": full["total_words"], "calibration_words": cal["total_words"], "holdout_words": sum(len(t.split()) for t in holdout.values())})

# Compare the complete installed parquet against the builder, including label lists.
def canonical(row):
    out = dict(row)
    out["real_dissenters"] = list(out["real_dissenters"])
    return out

actual_records = [canonical(r) for r in panel.to_dict("records")]
panel_consistency = actual_records == HISTORICAL_PANEL_DATA

# Manually adjudicated against each raw resolution section and Varma's signed
# statement. Reservations are a separate observed status, not a neutral ballot.
J = "jayanth_varma"
A = "ashima_goyal"
formal_rate = {"2022-09-30": [A], "2022-12-07": [J], "2023-02-08": [A, J], "2024-02-08": [J], "2024-04-05": [J], "2024-06-07": [A, J], "2024-08-08": [A, J]}
formal_stance = {"2021-08-06": [J], "2021-10-08": [J], "2021-12-08": [J], "2022-02-10": [J], "2022-09-30": [J], "2022-12-07": [A, J], "2023-02-08": [A, J], "2024-02-08": [J], "2024-04-05": [J], "2024-06-07": [A, J], "2024-08-08": [A, J]}
reservations = {d: [J] for d in ["2022-08-05", "2023-04-06", "2023-06-08", "2023-08-10", "2023-10-06", "2023-12-08"]}
guidance = {"2020-10-09": [J]}
evidence_by_date = {e["extractor_date"]: e for e in source_evidence}
truth_mapping = []
for row in actual_records:
    d = row["meeting_date"]
    ev = evidence_by_date[d]
    varma = (ROOT / "data/processed/statements" / d / "jayanth_varma.txt").read_text()
    varma_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", varma) if any(k in s.lower() for k in ["vote", "dissent", "reservation", "abstain"])]
    strict_union = sorted(set(formal_rate.get(d, []) + formal_stance.get(d, [])))
    truth_mapping.append({"panel_meeting_date": d, "adjudicated_meeting_date": "2022-05-04" if d == "2022-05-18" else d, "published_dissenters": row["real_dissenters"], "formal_rate_dissenters": formal_rate.get(d, []), "formal_stance_dissenters": formal_stance.get(d, []), "forward_guidance_dissenters": guidance.get(d, []), "stance_reservations_without_recorded_against_vote": reservations.get(d, []), "strict_rate_stance_dissenters": strict_union, "broad_any_formal_dissenters_including_guidance": sorted(set(strict_union + guidance.get(d, []))), "strict_label_match": sorted(row["real_dissenters"]) == strict_union, "source_file": ev["file"], "source_lines": ev["source_lines"], "resolution_evidence": [p for p in ev["resolution_paragraphs"] if "voted" in p.lower() or "reservations" in p.lower()], "varma_evidence": varma_sentences})
(OUT / "data_adjudicated_truth.json").write_text(json.dumps({"convention": "Strict formal rate/stance dissent requires recorded vote against the majority resolution or an explicit alternative binding vote. Stance reservations are a separate status; do not invent an abstention, yes or neutral vote where source only states reservations. Forward-guidance disagreement has its own field. Mappings are reviewer adjudications from local raw source; preserve original parquet and report both definitions.", "mapping": truth_mapping}, indent=2, ensure_ascii=False))

# Raw minutes report rounded latest observed CPI. This is evidence of contextual
# mismatch, not a substitute for a true release-time vintage archive.
latest_cpi = {
    "2020-10-09": (6.7, "July-August 2020"), "2020-12-04": (7.6, "October 2020"),
    "2021-02-05": (4.6, "December 2020"), "2021-04-07": (5.0, "February 2021"),
    "2021-06-04": (4.3, "April 2021"), "2021-08-06": (6.3, "June 2021"),
    "2021-10-08": (5.3, "August 2021"), "2021-12-08": (4.5, "October 2021"),
    "2022-02-10": (5.6, "December 2021"), "2022-04-08": (6.1, "February 2022"),
    "2022-05-18": (7.0, "March 2022"), "2022-06-08": (7.8, "April 2022"),
    "2022-08-05": (7.0, "May-June 2022"), "2022-09-30": (7.0, "August 2022"),
    "2022-12-07": (6.8, "October 2022"), "2023-02-08": (5.7, "December 2022"),
    "2023-04-06": (6.4, "February 2023"), "2023-06-08": (4.7, "April 2023"),
    "2023-08-10": (4.8, "June 2023"), "2023-10-06": (6.8, "August 2023"),
    "2023-12-08": (4.9, "October 2023"), "2024-02-08": (5.7, "December 2023"),
    "2024-04-05": (5.1, "January-February 2024"), "2024-06-07": (4.8, "April 2024"),
    "2024-08-08": (5.1, "June 2024"),
}
cpi_context = [{"meeting_date": r["meeting_date"], "panel_headline_cpi": r["cpi_headline_yoy_pct"], "raw_minutes_latest_rounded_cpi": latest_cpi[r["meeting_date"]][0], "raw_reference_period": latest_cpi[r["meeting_date"]][1], "differs_beyond_rounding": abs(r["cpi_headline_yoy_pct"] - latest_cpi[r["meeting_date"]][0]) > .051, "source_file": evidence_by_date[r["meeting_date"]]["file"]} for r in actual_records]
pd.DataFrame(cpi_context).to_csv(OUT / "data_cpi_context_comparison.csv", index=False)

# Pure input stress: no field currently tracks data release time or validates a real date.
date_probe = MacroMeetingSnapshot(meeting_date="2023-99-99", current_repo_rate_pct=6.5, cpi_headline_yoy_pct=7.44, cpi_core_yoy_pct=4.9)
labels_probe = MacroMeetingSnapshot(**actual_records[18])
prompt = labels_probe.to_prompt_text()
prompt_truth_values_present = "real_rate_decision_bps" in prompt or "real_dissenters" in prompt or "jayanth_varma" in prompt

# Offline FRED probe: inject a fake final monthly series, do not fetch or write a cache.
fred = FREDClient(cache_dir=OUT / "unused_fred_cache")
series_payload = {series_id: pd.DataFrame({"date": pd.to_datetime(["2023-08-01", "2023-09-01"]), series_id: [5.33, 5.33]}) for series_id in FRED_SERIES.values()}
fred.fetch_series = lambda series_id: series_payload[series_id]
asof_aug10 = fred.get_indicators_for_date("2023-08-10")
no_prior_aug = fred.get_indicators_for_date("2023-07-10")

after = {str(p.relative_to(ROOT)): sha(p) for p in input_paths}
result = {
    "environment": {"python": sys.version, "platform": platform.platform(), "pandas": pd.__version__, "network": "blocked by probe"},
    "input_files_preserved": before == after,
    "input_hashes": before,
    "panel": {"rows": len(panel), "calibration_rows": int((panel.meeting_date <= "2023-04-06").sum()), "holdout_rows": int((panel.meeting_date > "2023-04-06").sum()), "builder_equals_parquet": panel_consistency, "dates_unique": panel.meeting_date.is_unique, "dates_sorted": panel.meeting_date.is_monotonic_increasing, "all_records": actual_records},
    "manifest": {"rows": len(manifest), "checks": manifest_checks, "all_hashes_match": all(x["match"] for x in manifest_checks)},
    "reextraction": {"raw_documents": len(source_evidence), "statements": len(byte_equal), "byte_equal_count": sum(x["equal"] for x in byte_equal), "full_normalized_associated_raw_match_count": sum(x["full_text_in_associated_raw"] for x in normalized_full_matches), "comparisons": byte_equal, "normalized_comparisons": normalized_full_matches},
    "source_evidence": source_evidence,
    "persona_calibration": persona_summaries,
    "cpi_context_comparison": cpi_context,
    "strict_truth_mapping_mismatch_count": sum(not x["strict_label_match"] for x in truth_mapping),
    "schema_probe": {"accepted_invalid_date": date_probe.meeting_date, "ground_truth_field_names_or_dissenter_names_present_in_macro_prompt": prompt_truth_values_present, "macro_fields": list(MacroMeetingSnapshot.model_fields)},
    "fred_probe": {"monthly_final_aug1_observation_for_aug10": asof_aug10, "earliest_future_observation_for_jul10": no_prior_aug, "interpretation": "Observation timestamps alone are not release timestamps. Stub demonstrates selector behavior, not actual FRED source values."},
}
(OUT / "data_probe.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
print(json.dumps({"input_files_preserved": result["input_files_preserved"], "panel": {k:v for k,v in result["panel"].items() if k != "all_records"}, "manifest_all_hashes_match": result["manifest"]["all_hashes_match"], "statements": result["reextraction"]["statements"], "statements_byte_equal": result["reextraction"]["byte_equal_count"], "statements_full_normalized_in_associated_raw": result["reextraction"]["full_normalized_associated_raw_match_count"], "persona_calibration": persona_summaries, "schema_probe": result["schema_probe"], "fred_probe": result["fred_probe"]}, indent=2))
