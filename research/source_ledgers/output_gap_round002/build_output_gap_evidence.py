"""Parse actual source GDP vectors; preserve strict missingness and ex-post outputs."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from bs4 import BeautifulSoup
from src.data_pipeline.output_gap_estimation import (
    GDP_FIELD, GDPVintage, OutputGapProtocol, QuarterlyGDPInput, estimate_output_gap,
    numerical_proxy_diagnostics, quarter_period,
)
from src.schemas.macro_schema import ObservationEvidence

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, payload):
    with Path(path).open("x") as stream:
        stream.write(json.dumps(payload, indent=2, allow_nan=False) + "\n")


def column(address):
    result = 0
    for char in re.match(r"[A-Z]+", address)[0]:
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def source(id):
    matches = []
    for receipt in sorted((HERE / "acquisition").glob("*/receipt.json")):
        for row in json.loads(receipt.read_text())["sources"]:
            if row["id"] == id:
                matches.append(row)
    if len(matches) != 1 or not matches[0]["acquired"]:
        raise ValueError(f"Expected one acquired source: {id}")
    row = matches[0]
    path = HERE / row["local_file"]
    if sha(path) != row["sha256"]:
        raise ValueError(f"Raw acquisition hash mismatch: {id}")
    return row, path


def parse_xlsx(id, edition):
    row, path = source(id)
    with ZipFile(path) as archive:
        names = archive.namelist()
        strings = ["".join(x.itertext()) for x in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", NS)] if "xl/sharedStrings.xml" in names else []
        sheets = [name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)]
        matches = []
        for sheet in sheets:
            rows = {}
            for xml_row in ET.fromstring(archive.read(sheet)).findall(".//s:row", NS):
                values = []
                for c in xml_row.findall("s:c", NS):
                    v = c.find("s:v", NS)
                    inline = c.find("s:is", NS)
                    if v is None and inline is None:
                        continue
                    value = v.text if v is not None else "".join(inline.itertext())
                    if c.get("t") == "s":
                        value = strings[int(value)]
                    formula = c.find("s:f", NS)
                    values.append({"cell": c.get("r"), "column": column(c.get("r")), "text": value,
                                   "formula": formula.text if formula is not None else None,
                                   "type": c.get("t", "numeric")})
                rows[int(xml_row.get("r"))] = values
            titles = [v["text"] for values in rows.values() for v in values if "Statement 8.18.2" in v["text"]]
            markers = [n for n, values in rows.items() if any("at 2011-12 prices" in v["text"] for v in values)]
            for marker in markers:
                headers = [(n, values) for n, values in rows.items() if marker < n <= marker + 3 and any(v["text"].strip() == "2011-12" for v in values)]
                totals = [(n, values) for n, values in rows.items() if n > marker and any(v["text"].strip().lower() == "gross domestic product" for v in values)]
                if len(headers) != 1 or len(totals) != 1 or len(titles) != 1:
                    raise ValueError("Ambiguous expenditure/GDP constant-price worksheet")
                header_n, header = headers[0]; total_n, total = totals[0]
                years = [v for v in header if re.fullmatch(r"20\d\d-\d\d", v["text"].strip())]
                quarter_header = {v["column"]: v["text"].strip() for v in rows[header_n + 1]}
                cells = {v["column"]: v for v in total}
                observations = []
                for item in years:
                    fy = int(item["text"][:4])
                    if item["text"] != f"{fy}-{str(fy + 1)[-2:]}":
                        raise ValueError("Invalid fiscal-year column label")
                    for q in (1, 2, 3, 4):
                        col = item["column"] + q - 1
                        if quarter_header.get(col) != f"Q{q}":
                            raise ValueError("GDP quarter-header alignment failure")
                        cell = cells[col]
                        value = Decimal(cell["text"])
                        if not value.is_finite() or value <= 0 or cell["type"] not in ("numeric", "n"):
                            raise ValueError("Non-numeric/invalid GDP total cell")
                        label, first, last = quarter_period(fy, q)
                        observations.append({"fiscal_year": fy, "quarter": q, "reference_period": label,
                            "reference_period_start": first.isoformat(), "reference_period_end": last.isoformat(),
                            "value_crore": float(value), "source_numeric_lexeme": cell["text"],
                            "cached_formula": cell["formula"], "source_pointer": f"{sheet} cell {cell['cell']}, constant2011-12 GDP total row{total_n}"})
                core = ET.fromstring(archive.read("docProps/core.xml"))
                metadata = {node.tag.rsplit("}", 1)[-1]: node.text for node in core}
                matches.append({"source_id": id, "edition": edition, "observations": observations,
                    "worksheet_title": titles[0], "constant_price_marker_row": marker, "gdp_total_row": total_n,
                    "core_properties_diagnostic_only": metadata,
                    "external_links_present": any(name.startswith("xl/externalLinks/") for name in names),
                    "source_url": row["url"], "source_file": str(path.relative_to(ROOT)), "source_sha256": row["sha256"],
                    "retrieved_at_utc": row["retrieved_at_utc"], "historical_version_availability_verified": False,
                    "availability_reason": "Current exact workbook version has no independently retained historical publication/link witness; edition month and file metadata are not sufficient"})
        if len(matches) != 1:
            raise ValueError("Expected one unambiguous constant-price GDP vector")
        return matches[0]


def nas2019_vector():
    row, path = source("nas2019_gdp_expenditure")
    values = [2102863,2042870,2225135,2365461,2205223,2195946,2344767,2467082,
        2347396,2357079,2497997,2598898,2535751,2562242,2645947,2783733,
        2728279,2768087,2836387,3036738,2983818,3013489,3050425,3250592,
        3162537,3217465,3284971,3514884,3413997,3442739,3501020,3719830]
    observations = []
    for i, value in enumerate(values):
        year, q = 2011 + i // 4, i % 4 + 1
        label, start, end = quarter_period(year, q)
        observations.append({"fiscal_year": year, "quarter": q, "reference_period": label,
            "reference_period_start": start.isoformat(), "reference_period_end": end.isoformat(),
            "value_crore": value, "source_numeric_lexeme": str(value), "cached_formula": None,
            "source_pointer": f"PDF physical page2, at2011-12 prices, Gross domestic product row, {label}; visual transcription"})
    return {"source_id": "nas2019_gdp_expenditure", "edition": 2019, "observations": observations,
        "source_url": row["url"], "source_file": str(path.relative_to(ROOT)), "source_sha256": row["sha256"],
        "retrieved_at_utc": row["retrieved_at_utc"], "historical_version_availability_verified": False,
        "availability_reason": "Official report supports September2019 edition publication; no historical exact-table version witness retained", "visual_check": "visual_checks/nas2019_gdp_constant_page2.png"}


def diagnostic(vector, protocol):
    records = vector["observations"]
    return numerical_proxy_diagnostics([r["value_crore"] for r in records], [r["quarter"] for r in records],
                                      [r["fiscal_year"] for r in records], protocol)


def main():
    destination = ROOT / "results/upgrade_validation_round_002/output_gap_oct09" / sys.argv[1]
    destination.mkdir(parents=True, exist_ok=False)
    receipt = json.loads((HERE / "protocol_freeze_receipt.json").read_text())
    protocol = OutputGapProtocol.from_file(HERE / "protocol_v1.json", receipt["protocol_sha256"])
    sources = [nas2019_vector(), parse_xlsx("nas2020_quarterly_candidate_2", 2020)]
    sources += [parse_xlsx(f"nas{year}_quarterly_gdp_xlsx", year) for year in range(2021, 2025)]
    input_files = {v["source_file"]: v["source_sha256"] for v in sources}
    for name in ("research/source_ledgers/gdp_fed_vintages/gdp_table_transcriptions.json",
                 "research/source_ledgers/gdp_fed_vintages/gdp_ledger.json",
                 "research/source_ledgers/gdp_fed_vintages/meeting_gdp_ledger.csv",
                 "research/source_ledgers/output_gap_round002/protocol_v1.json",
                 "src/data_pipeline/output_gap_estimation.py"):
        input_files[name] = sha(ROOT / name)
    write_new(destination / "input_manifest.json", {"files": input_files, "protocol_sha256": protocol.protocol_sha256})
    write_new(destination / "coherent_downloaded_gdp_vectors.json", {"version": "downloaded-gdp-vectors-v1", "vectors": sources})
    # Read both source bytes and their actual numeric values. No date inferred from an edition label.
    proxy_outputs = []
    endpoints = []
    for vector in sources:
        result = diagnostic(vector, protocol)
        proxy_outputs.append({"source_id": vector["source_id"], "source_sha256": vector["source_sha256"],
            "provenance": "Ex-post retained downloaded edition/version; not contemporaneous MPC evidence", "result": result})
        for n in range(28, len(vector["observations"]) + 1):
            prefix = {**vector, "observations": vector["observations"][:n]}
            at_prefix = diagnostic(prefix, protocol)["primary"]
            later_log = result["primary"]["log_cycle"][n - 1]
            import math
            later_pct = 100 * math.expm1(later_log)
            endpoints.append({"source_id": vector["source_id"], "reference_period": prefix["observations"][-1]["reference_period"],
                "prefix_quarters": n, "extended_quarters": len(vector["observations"]),
                "prefix_endpoint_gap_pct": at_prefix["output_gap_pct"], "ex_post_extended_fit_same_quarter_gap_pct": later_pct,
                "change_percentage_points": later_pct - at_prefix["output_gap_pct"],
                "diagnostic_scope": "Pseudo-real-time endpoint/seasonal-refit sensitivity conditional on one current downloaded vector; not dated real-time error"})
    write_new(destination / "ex_post_proxy_sensitivities.json", {"protocol_sha256": protocol.protocol_sha256,
        "original_meeting_input_eligible": False, "outputs": proxy_outputs})
    write_new(destination / "ex_post_endpoint_sensitivity.json", {"original_meeting_input_eligible": False,
        "ineligible_first_prefixes_per_vector": 27, "outputs": endpoints})
    revisions = []
    import math
    for prior, later in zip(sources, sources[1:]):
        n = min(len(prior["observations"]), len(later["observations"]))
        old = diagnostic({**prior, "observations": prior["observations"][:n]}, protocol)["primary"]
        revised = diagnostic({**later, "observations": later["observations"][:n]}, protocol)["primary"]
        full = diagnostic(later, protocol)["primary"]
        extended_pct = 100 * math.expm1(full["log_cycle"][n - 1])
        differences = [{"reference_period": a["reference_period"], "old_crore": a["value_crore"], "new_crore": b["value_crore"],
                        "change_crore": b["value_crore"] - a["value_crore"]} for a, b in zip(prior["observations"][:n], later["observations"][:n]) if abs(a["value_crore"] - b["value_crore"]) > 0.5]
        revisions.append({"prior_source_id": prior["source_id"], "later_source_id": later["source_id"], "common_prefix_quarters": n,
            "reference_period": prior["observations"][n - 1]["reference_period"], "prior_downloaded_prefix_gap_pct": old["output_gap_pct"],
            "later_downloaded_same_prefix_gap_pct": revised["output_gap_pct"], "later_downloaded_extended_fit_gap_pct": extended_pct,
            "source_value_change_effect_pp": revised["output_gap_pct"] - old["output_gap_pct"],
            "endpoint_and_seasonal_refit_extension_effect_pp": extended_pct - revised["output_gap_pct"],
            "changed_quarters_above_half_crore_rounding": differences,
            "scope": "Ex-post source version and endpoint decomposition; original release availability not authenticated"})
    write_new(destination / "ex_post_source_revision_decomposition.json", {"outputs": revisions, "original_meeting_input_eligible": False})
    # Compare to the 17 retained dated releases; disagreements are preserved, never silently repaired.
    old_ledger = json.loads((ROOT / "research/source_ledgers/gdp_fed_vintages/gdp_ledger.json").read_text())
    cross_checks = []
    for vector in sources:
        lookup = {r["reference_period"]: r["value_crore"] for r in vector["observations"]}
        for observation in old_ledger["vintages"]:
            if observation["series"] != GDP_FIELD or observation["reference_period"] not in lookup:
                continue
            difference = lookup[observation["reference_period"]] - observation["value"]
            cross_checks.append({"downloaded_source_id": vector["source_id"], "dated_release_id": observation["release_id"],
                "dated_release_date": observation["release_date"], "reference_period": observation["reference_period"],
                "dated_release_value_crore": observation["value"], "downloaded_value_crore": lookup[observation["reference_period"]],
                "change_crore": difference, "agrees_with_half_crore_rounding": abs(difference) <= 0.5,
                "interpretation": "Agreement is not a full historical version/link witness; disagreements may be revisions or source/table differences"})
    write_new(destination / "dated_release_numeric_cross_checks.json", {"checks": cross_checks})
    example = sources[1]
    records = tuple(QuarterlyGDPInput(r["fiscal_year"], r["quarter"], ObservationEvidence(
        field=GDP_FIELD, value=r["value_crore"], units="INR crore at constant2011-12 prices",
        reference_period=r["reference_period"], vintage=example["source_id"],
        released_at=datetime.fromisoformat(example["retrieved_at_utc"]), source_url=example["source_url"],
        source_file=example["source_file"], source_sha256=example["source_sha256"], source_pointer=r["source_pointer"],
        availability_basis="Current acquisition proves availability at retrieval only; original exact-version publication remains unverified"))
        for r in example["observations"])
    vintage = GDPVintage(example["source_id"], records, availability_state="retrieval_only", availability_note=example["availability_reason"])
    rows = []; source_failures = []
    with (ROOT / "research/source_ledgers/gdp_fed_vintages/meeting_gdp_ledger.csv").open() as stream:
        meetings = list(csv.DictReader(stream))
    for meeting in meetings:
        failed = estimate_output_gap(vintage, datetime.fromisoformat(meeting["cutoff_exclusive_ist"]), protocol, ROOT)
        assert failed.status == "missing" and failed.output_gap_pct is None
        source_failures.append({"decision_date": meeting["decision_date"], "example_source_only_not_selected_historical_vintage": example["source_id"], "result": failed.to_dict()})
        rows.append({"decision_date": meeting["decision_date"], "meeting_start_date": meeting["meeting_start_date"],
            "cutoff_exclusive_ist": meeting["cutoff_exclusive_ist"], "latest_reference_from_verified_retained_quarterly_release": meeting["latest_reference_period"],
            "latest_quarterly_release_source_sha256": meeting["source_sha256"], "strict_output_gap_pct": None,
            "strict_historical_output_gap_ready": False, "coherent_downloaded_source_vectors": len(sources),
            "reason": "No retained full GDP vector has publication/link evidence authenticating its particular downloaded version before this cutoff; current edition files cannot fill that missingness"})
    write_new(destination / "strict_source_failure_results.json", {"records": source_failures})
    write_new(destination / "meeting_output_gap_readiness.json", {"meetings": rows})
    write_new(destination / "strict_observation_candidates.json", {"version": "strict-output-gap-observation-candidates-v1", "observations": [],
        "covered_original_meetings": 0, "total_original_meetings": len(rows), "reason": rows[0]["reason"]})
    states = {"current_source_vectors_ready": len(sources), "numerically_eligible_downloaded_vectors": len(proxy_outputs),
        "strict_historical_meetings_ready": 0, "strict_historical_observation_candidates": 0,
        "source_quarter_counts": {v["source_id"]: len(v["observations"]) for v in sources},
        "ex_post_endpoint_cases": len(endpoints), "ex_post_source_revision_pairs": len(revisions),
        "dated_release_numeric_cross_checks": len(cross_checks), "version_availability_not_inferred_from_metadata": True,
        "method_frozen_before_proxy_computation": True, "protocol_sha256": protocol.protocol_sha256,
        "code_sha256": sha(ROOT / "src/data_pipeline/output_gap_estimation.py"), "builder_sha256": sha(Path(__file__)),
        "python_version": sys.version, "platform": platform.platform(), "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_input_files_unchanged": {name: sha(ROOT / name) == digest for name, digest in input_files.items()},
        "paid_provider_or_model_generation_calls": 0,
        "remaining_limit": "Coherent contemporaneous version witnesses and a separately frozen full-comparator integration are missing; numerical diagnostics do not establish economic slack or forecast improvement"}
    assert all(states["original_input_files_unchanged"].values())
    write_new(destination / "build_receipt.json", states)
    print(json.dumps(states, indent=2))


if __name__ == "__main__":
    main()
