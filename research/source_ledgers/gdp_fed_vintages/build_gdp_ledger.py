"""Build sparse dated GDP/GVA source tables without estimating an output gap."""
from __future__ import annotations
import csv
import hashlib
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def csv_out(name, rows):
    with (OUT / name).open("w", newline="") as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

def period(year, q):
    start_month = {1:4, 2:7, 3:10, 4:1}[q]
    cal_year = year + (q == 4)
    start = datetime(cal_year,start_month,1).date()
    next_month = start_month+3
    end = datetime(cal_year + (next_month>12), (next_month-1)%12+1,1).date()-timedelta(days=1)
    return f"FY{year}-{str(year+1)[-2:]}Q{q}", start.isoformat(), end.isoformat()

def main():
    retrieval = json.loads((OUT / "retrieval_manifest.json").read_text())
    sources = {r["id"]:r for r in retrieval}
    tables = json.loads((OUT / "gdp_table_transcriptions.json").read_text())["tables"]
    vintages=[]; snapshots=[]; rounding=[]
    for table in tables:
        src=sources[table["source_id"]]
        assert src["acquired"] and sha(OUT / src["local_file"])==src["sha256"]
        extract=json.loads((OUT / "extracted" / (table["source_id"]+".json")).read_text())
        assert extract["source_sha256"]==src["sha256"]
        date=datetime.fromisoformat(src["release_date"])
        text=" ".join(p["text"] for p in extract["pages"][:4])
        assert "5.30 pm" in text or "5.30pm" in text
        assert re.search(rf"{date.day}(?:st|nd|rd|th)?\s+{date.strftime('%B')}[,]?\s+{date.year}",text),src["id"]
        stamp=date.replace(hour=17,minute=30,tzinfo=ZoneInfo("Asia/Kolkata"))
        q=table["q"];year=table["year"]
        common=dict(release_id=src["id"],release_date=src["release_date"],documented_release_timestamp_ist=stamp.isoformat(),documented_release_timestamp_utc=stamp.astimezone(ZoneInfo("UTC")).isoformat(),release_timestamp_basis="MoSPI PDF printed embargo endpoint, India local time",policy_effective_date="",policy_effective_date_basis="Not applicable to a statistical release",vintage="Quarterly estimate table printed in this dated release; comparisons may be revised",price_basis="Constant 2011-12 prices",observation_kind="Published estimate of an elapsed quarter, not annual advance forecast",source_url=src["url"],local_source_file=src["local_file"],source_sha256=src["sha256"],transcription_basis=table["transcription_basis"])
        snap=dict(**common,latest_reference_period=period(year,q)[0],latest_reference_period_start=period(year,q)[1],latest_reference_period_end=period(year,q)[2],gdp_constant_2011_12_crore=table["gdp"][-1],gva_constant_2011_12_crore=table["gva"][-1],gdp_growth_yoy_pct=table["gdp_growth"][-1],gva_growth_yoy_pct=table["gva_growth"][-1],gdp_source_table_pointer=f"PDF physical page {table['gdp_page']}, constant-price quarterly GDP total and YoY rows",gva_source_table_pointer=f"PDF physical page {table['page']}, constant-price quarterly GVA total and YoY rows")
        snapshots.append(snap)
        for series in ["gdp","gva"]:
            assert len(table[series])==3*q and len(table[series+"_growth"])==2*q
            page=table["gdp_page"] if series=="gdp" else table["page"]
            excerpt=f"Manually adjudicated {series.upper()} level row in printed column order: {table[series]}; published YoY row: {table[series+'_growth']}"
            for n,value in enumerate(table[series]):
                fy=year-2+n//q;quarter=n%q+1
                ref,start,end=period(fy,quarter)
                assert math.isfinite(value) and value>0 and end<src["release_date"]
                vintages.append(dict(**common,reference_period=ref,reference_period_start=start,reference_period_end=end,series=f"{series}_constant_2011_12_crore",value=value,units="Rupees crore at constant 2011-12 prices",source_table_pointer=f"PDF physical page {page}, {series.upper()} total row; fiscal year {fy}-{str(fy+1)[-2:]} Q{quarter}",source_excerpt=excerpt))
            for n,value in enumerate(table[series+"_growth"]):
                fy=year-1+n//q;quarter=n%q+1
                ref,start,end=period(fy,quarter)
                calculated=100*(table[series][n+q]/table[series][n]-1)
                difference=abs(calculated-value)
                assert math.isfinite(value) and difference<=0.05001,(src["id"],series,ref,difference)
                rounding.append(dict(release_id=src["id"],series=series,reference_period=ref,published=value,calculated_from_same_table_levels=calculated,absolute_difference=difference))
                vintages.append(dict(**common,reference_period=ref,reference_period_start=start,reference_period_end=end,series=f"{series}_growth_yoy_pct",value=value,units="Year-on-year percent",source_table_pointer=f"PDF physical page {page}, {series.upper()} YoY row; fiscal year {fy}-{str(fy+1)[-2:]} Q{quarter}",source_excerpt=excerpt))
    snapshots.sort(key=lambda r:r["release_date"])
    meetings=list(csv.DictReader((ROOT / "research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv").open()))
    rows=[];observations=[];gap_checks=[]
    for meeting in meetings:
        cutoff=datetime.fromisoformat(meeting["cutoff_exclusive_ist"])
        candidates=[s for s in snapshots if datetime.fromisoformat(s["documented_release_timestamp_utc"])<cutoff]
        chosen=candidates[-1]
        assert chosen["latest_reference_period_end"]<meeting["meeting_start_date"]
        common=dict(decision_date=meeting["decision_date"],meeting_start_date=meeting["meeting_start_date"],information_cutoff_day=meeting["information_cutoff_day"],cutoff_exclusive_ist=meeting["cutoff_exclusive_ist"])
        rows.append(dict(**common,**chosen,output_gap_pct="",output_gap_ready=False,latest_selection_basis="Latest retained scheduled quarterly-release document before cutoff; intermediate revision/correction completeness not claimed",intermediate_or_correction_releases_exhaustively_ruled_out=False))
        observations += [dict(**common,**v) for v in vintages if v["release_id"]==chosen["release_id"] and v["reference_period"]==chosen["latest_reference_period"]]
        history=[v for v in vintages if v["series"]=="gdp_constant_2011_12_crore" and datetime.fromisoformat(v["documented_release_timestamp_utc"])<cutoff]
        refs=sorted({v["reference_period"] for v in history})
        gap_checks.append(dict(**common,output_gap_pct=None,output_gap_ready=False,distinct_retained_gdp_quarters=len(refs),earliest_retained_reference_period=refs[0],latest_retained_reference_period=refs[-1],history_is_audited_complete_available_vintage=False,seasonal_adjustment_and_one_sided_estimator_frozen=False,reason="Sparse retained vintage tables begin FY2017-18Q1; earlier official available-vintage history and intermediate revisions not acquired; no frozen seasonal adjustment/trend specification or estimated potential output"))
    assert len(rows)==25 and len(observations)==100
    csv_out("gdp_release_snapshots.csv",snapshots)
    csv_out("gdp_gva_release_vintages.csv",vintages)
    csv_out("meeting_gdp_ledger.csv",rows)
    csv_out("meeting_gdp_observations.csv",observations)
    csv_out("output_gap_readiness.csv",gap_checks)
    checks=dict(meetings=len(rows),gdp_release_snapshots=len(snapshots),source_linked_vintage_observations=len(vintages),meeting_current_observations=len(observations),same_vintage_growth_rounding_checks=len(rounding),max_same_table_growth_rounding_difference=max(r["absolute_difference"] for r in rounding),output_gap_ready_meetings=0,legacy_macro_panel_sha256=sha(ROOT / "data/processed/macro_panel.parquet"),cpi_meeting_ledger_sha256=sha(ROOT / "research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv"),transcription_input_sha256=sha(OUT / "gdp_table_transcriptions.json"),meeting_gdp_ledger_sha256=sha(OUT / "meeting_gdp_ledger.csv"),intermediate_revision_completeness=False)
    (OUT / "gdp_ledger.json").write_text(json.dumps(dict(snapshots=snapshots,vintages=vintages,meetings=rows,output_gap_readiness=gap_checks,same_table_rounding_checks=rounding,checks=checks),indent=2)+"\n")
    print(json.dumps(checks,indent=2))

if __name__=="__main__":
    main()
