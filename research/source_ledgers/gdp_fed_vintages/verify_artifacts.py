"""Offline source integrity, cutoff, semantics and intentional failure controls."""
from __future__ import annotations
import copy
import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def csv_read(p):return list(csv.DictReader(p.open()))

def provenance(row):
    source=(OUT / row["local_source_file"]).resolve()
    assert source.is_relative_to(OUT / "raw") and source.is_file()
    assert sha(source)==row["source_sha256"]
    stamp=datetime.fromisoformat(row["documented_release_timestamp_utc"])
    cutoff=datetime.fromisoformat(row["cutoff_exclusive_ist"])
    assert stamp.tzinfo is not None and cutoff.tzinfo is not None and stamp<cutoff
    assert row["source_url"].startswith("https://") and row["source_table_pointer"]
    assert math.isfinite(float(row["value"]))

def validate_fed(row, canonical):
    provenance(row)
    assert row["series"]=="us_fed_target_upper_pct"
    assert row["policy_effective_date"]<=row["information_cutoff_day"]
    expected=canonical[row["release_id"]]
    assert float(row["value"])==expected["target_upper_pct"]
    assert row["valid_until_effective_date_exclusive"]==expected["valid_until_effective_date_exclusive"]
    assert row["valid_until_effective_date_exclusive"]>row["meeting_start_date"]
    assert row["policy_effective_date"]==expected["policy_effective_date"]
    assert row["source_sha256"]==expected["source_sha256"]
    assert sha(OUT / row["statement_local_source_file"])==row["statement_source_sha256"]

def validate_gdp(row, canonical):
    provenance(row)
    key=(row["release_id"],row["reference_period"],row["series"])
    assert key in canonical
    expected=canonical[key]
    assert float(row["value"])==expected["value"]
    assert row["source_sha256"]==expected["source_sha256"]
    assert row["documented_release_timestamp_utc"]==expected["documented_release_timestamp_utc"]
    assert row["price_basis"]=="Constant 2011-12 prices"
    assert row["reference_period_end"]<row["meeting_start_date"]

def rejected(name,row,mutate,validate):
    wrong=copy.deepcopy(row);mutate(wrong)
    try:validate(wrong)
    except (AssertionError, ValueError):return dict(control=name,rejected=True)
    raise AssertionError("Corrupt input accepted: "+name)

def main():
    retrieval=json.loads((OUT / "retrieval_manifest.json").read_text())
    assert len(retrieval)==94 and all(r["acquired"] for r in retrieval)
    assert len({r["id"] for r in retrieval})==len(retrieval)
    for r in retrieval:assert sha(OUT/r["local_file"])==r["sha256"]
    fed=json.loads((OUT / "fed_ledger.json").read_text())
    gdp=json.loads((OUT / "gdp_ledger.json").read_text())
    fm=csv_read(OUT / "meeting_fed_ledger.csv");gm=csv_read(OUT / "meeting_gdp_ledger.csv")
    obs=csv_read(OUT / "meeting_gdp_observations.csv")
    fedcanonical={r["release_id"]:r for r in fed["releases"]}
    gdpcanonical={(r["release_id"],r["reference_period"],r["series"]):r for r in gdp["vintages"]}
    assert len(fm)==25 and len(gm)==25 and len(obs)==100 and len(gdpcanonical)==440
    ids={r["decision_date"] for r in fm}
    assert len(ids)==25 and ids=={r["decision_date"] for r in gm}=={r["decision_date"] for r in obs}
    for r in fm:validate_fed(r,fedcanonical)
    for r in obs:validate_gdp(r,gdpcanonical)
    for r in gm:
        assert r["output_gap_pct"]=="" and r["output_gap_ready"]=="False"
        assert r["intermediate_or_correction_releases_exhaustively_ruled_out"]=="False"
    assert len(gdp["same_table_rounding_checks"])==176
    assert max(r["absolute_difference"] for r in gdp["same_table_rounding_checks"])<=0.05001
    assert sha(ROOT / "data/processed/macro_panel.parquet")==fed["checks"]["legacy_macro_panel_sha256"]==gdp["checks"]["legacy_macro_panel_sha256"]
    assert sha(ROOT / "research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv")==fed["checks"]["cpi_meeting_ledger_sha256"]==gdp["checks"]["cpi_meeting_ledger_sha256"]
    controls=[]
    fv=lambda r:validate_fed(r,fedcanonical);gv=lambda r:validate_gdp(r,gdpcanonical)
    for kind,row,validator in [("fed",fm[0],fv),("gdp",obs[0],gv)]:
        controls += [rejected(kind+"_future_release",row,lambda r:r.update(documented_release_timestamp_utc="2026-10-05T12:00:00+00:00"),validator),rejected(kind+"_changed_source_hash",row,lambda r:r.update(source_sha256="0"*64),validator),rejected(kind+"_nonfinite_value",row,lambda r:r.update(value="nan"),validator),rejected(kind+"_changed_value",row,lambda r:r.update(value=999),validator),rejected(kind+"_unknown_series",row,lambda r:r.update(series="unsupported_output_gap_pct"),validator)]
    controls += [rejected("fed_future_effective_date",fm[0],lambda r:r.update(policy_effective_date="2026-10-05"),fv),rejected("gdp_current_price_series_substitution",obs[0],lambda r:r.update(price_basis="Current prices"),gv)]
    assert len(list((OUT / "visual_checks").glob("*.png")))==21
    log=json.loads((OUT / "render_ocr_log.json").read_text())
    assert all(entry["exit_code"]==0 for batch in log for entry in batch)
    result=dict(verified_at_utc=datetime.now().astimezone().isoformat(),source_bodies_verified=94,dated_fed_directives=33,fed_meetings=25,gdp_release_snapshots=17,gdp_vintage_observations=440,gdp_meetings=25,gdp_current_meeting_observations=100,output_gap_ready_meetings=0,same_table_rounding_checks=176,intentional_failure_controls=controls,rendered_pdf_table_pages=21,legacy_panel_preserved=True,exhaustive_intermediate_revision_coverage=False,independent_first_website_availability_proof=False,verification_scope="Offline engineering/transcription/cutoff checks; no forecasting, model generation or empirical superiority test",environment=dict(python=sys.version,platform=platform.platform(),executable=sys.executable),input_hashes={name:sha(OUT/name) for name in ["source_catalog.json","gdp_table_transcriptions.json","meeting_fed_ledger.csv","meeting_gdp_ledger.csv","gdp_gva_release_vintages.csv"]})
    (OUT / "final_verification.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))

if __name__=="__main__":main()
