"""Build a separate source-linked historical panel without altering legacy data.

This is a partially covered retrospective panel, not an untouched evaluation. No
unsourced core inflation, output gap, exchange rate or liquidity values are filled.
"""
import csv
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from bs4 import BeautifulSoup
from src.data_pipeline.statement_extractor import StatementExtractor, MEMBER_PATTERNS
from src.schemas.macro_schema import MacroMeetingSnapshot, ObservationEvidence

ROOT = Path(__file__).resolve().parents[2]
LABEL_DIRECTORY = Path("research/source_ledgers/historical_labels_round002")
SURNAME_IDS = {"bhide": "shashanka_bhide", "goyal": "ashima_goyal", "varma": "jayanth_varma",
               "saggar": "mridul_saggar", "ranjan": "rajiv_ranjan", "patra": "michael_patra",
               "das": "shaktikanta_das"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized(text):
    return " ".join(text.split())


def source_path(root, value):
    root = Path(root).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Missing or outside-source-root scientific input: {value}")
    return path


def read_json(path):
    def reject(value):
        raise ValueError(f"Non-finite JSON constant: {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), parse_constant=reject, object_pairs_hook=unique)


def verify_input_manifest(source_root, manifest_path=None):
    """Verify the separately retained catalogue before accepting any transcription."""
    root = Path(source_root).resolve()
    path = source_path(root, manifest_path or LABEL_DIRECTORY / "input_manifest.json")
    manifest = read_json(path)
    if manifest.get("version") != "historical-scientific-inputs-v1" or not manifest.get("files"):
        raise ValueError("Unsupported or empty scientific input manifest")
    for name, expected in manifest["files"].items():
        if not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError(f"Invalid scientific input digest: {name}")
        if digest(source_path(root, name)) != expected:
            raise ValueError(f"Scientific input hash mismatch: {name}")
    return manifest


def policy_level(clause):
    values = re.findall(r"(?:to|at)\s+([\d.]+)\s*per cent", clause, flags=re.I)
    if "policy repo rate" not in clause.lower() or len(values) != 1:
        raise ValueError("Expected one policy repo rate level in the selected resolution clause")
    level = Decimal(values[0])
    if not level.is_finite() or not 0 <= level <= 20:
        raise ValueError("Invalid policy repo level")
    return level


def policy_stance(clause):
    lower = clause.lower()
    if not lower.startswith("the mpc also decided"):
        raise ValueError("Stance must come from the committee resolution, not a member preference")
    if "continue with the accommodative stance" in lower or "remain accommodative" in lower:
        # April/May 2022 retain the published leading stance, including its qualification.
        return "accommodative"
    if "remain focused on withdrawal of accommodation" in lower:
        return "withdrawal_of_accommodation"
    raise ValueError("Unknown historical committee stance; no silent category substitution")


def member_ballots(soup):
    """Read literal Yes/No cells; duplicated enclosing HTML tables must agree."""
    candidates = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [normalized(td.get_text(" ", strip=True))
                     for td in tr.find_all(["td", "th"], recursive=False)]
            if len(cells) == 2 and cells[1] in ("Yes", "No"):
                members = [identifier for surname, identifier in SURNAME_IDS.items()
                           if re.search(r"\b" + surname + r"\b", cells[0], flags=re.I)]
                if len(members) != 1:
                    raise ValueError("Unknown or ambiguous member in the published rate ballot table")
                rows.append((members[0], cells[1]))
        if len(rows) == 6:
            if len(dict(rows)) != 6:
                raise ValueError("Duplicate member in published ballot table")
            candidates.append(dict(rows))
    if not candidates or any(candidate != candidates[0] for candidate in candidates):
        raise ValueError("Missing or disagreeing six-member rate ballot tables")
    return candidates[0]


def formal_stance_targets(soup, excerpts, roster):
    """Reconstruct observed stance votes in this original panel's source grammar.

    Unsupported source language fails the annotation equality check. An omitted
    or reservations-only vote stays null. The full source excerpts remain the
    scientific authority; this parser is not a general later-roster ontology.
    """
    targets = {member: None for member in roster}
    def named_members(text):
        return {identifier for surname, identifier in SURNAME_IDS.items()
                if identifier in roster and re.search(r"\b" + surname + r"\b", text, flags=re.I)}
    for excerpt in excerpts:
        fragments = re.split(r"\.\s+(?=(?:Dr\.|Prof\.|Shri\b|Furthermore\b|Further,|All members\b))", excerpt)
        for fragment in fragments:
            vote = re.search(r"\bvoted\b", fragment, flags=re.I)
            if not vote:
                continue
            subjects, act = fragment[:vote.start()], fragment[vote.start():].lower()
            before_exception = re.split(r"\bexcept\b", subjects, flags=re.I)[0]
            members = named_members(before_exception)
            if not members and re.search(r"\ball members\b", before_exception, flags=re.I):
                members = set(roster)
            if re.search(r"voted against this part of the resolution|voted for a change in stance to neutral", act):
                for member in members:
                    targets[member] = True
            elif re.search(r"voted.*?(?:continue|remain).*?(?:accommodative|withdrawal of accommodation)", act):
                for member in members:
                    targets[member] = False
    full_text = normalized(soup.get_text(" ", strip=True))
    headings = sorted((match.start(), item["member_id"]) for item in MEMBER_PATTERNS
                      if (match := re.search(item["pattern"], full_text, flags=re.I)))
    for i, (start, member) in enumerate(headings):
        if member not in targets:
            continue
        block = full_text[start:headings[i + 1][0] if i + 1 < len(headings) else len(full_text)]
        if re.search(r"vot(?:e|ing) against (?:the )?(?:accommodative|policy) stance", block, flags=re.I):
            targets[member] = True
    return targets


def observed_member_targets(ledger):
    channels = {name: [] for name in ("literal_rate_no", "exact_rate_disagreement", "formal_stance_dissent")}
    for row in ledger["meetings"]:
        channels["literal_rate_no"].append({"meeting_date": row["meeting_date"],
            "member_targets": {member: value == "No" for member, value in row["literal_rate_ballots"].items()}})
        channels["exact_rate_disagreement"].append({"meeting_date": row["meeting_date"],
            "member_targets": row["exact_rate_disagreement_targets"]})
        channels["formal_stance_dissent"].append({"meeting_date": row["meeting_date"],
            "member_targets": row["formal_stance_targets"]})
    return {"version": "historical-observed-member-targets-v1", "definitions": ledger["definitions"],
            "channels": channels}


def construct_label_ledger(source_root=ROOT, annotations_path=None):
    """Validate portable scientific annotations and derive all numerical policy outcomes.

    Annotations carry the interpretive vote labels, raw excerpts and attribution.
    They are not an independent second coding. The numeric action is calculated
    from consecutive published policy levels, never from the legacy parquet.
    """
    root = Path(source_root).resolve()
    annotations_path = source_path(root, annotations_path or LABEL_DIRECTORY / "label_annotations.json")
    annotations = read_json(annotations_path)
    if annotations.get("version") != "historical-label-annotations-v1":
        raise ValueError("Unsupported scientific annotation version")
    rows = annotations.get("meetings", [])
    dates = [row["meeting_date"] for row in rows]
    if len(dates) != 25 or dates != sorted(set(dates)):
        raise ValueError("Expected 25 unique chronologically ordered annotation dates")
    prior_record_path = source_path(root, "research/source_ledgers/prior_policy/source_record.json")
    prior_record = read_json(prior_record_path)
    prior_source = source_path(root, "research/source_ledgers/prior_policy/august_2020_resolution.html")
    if digest(prior_source) != prior_record["sha256"]:
        raise ValueError("Changed initial policy source")
    prior_soup = BeautifulSoup(prior_source.read_bytes(), "html.parser")
    prior_clauses = {normalized(node.get_text(" ", strip=True))
                     for node in prior_soup.find_all(["p", "li"])}
    prior_levels = {policy_level(clause) for clause in prior_clauses
                    if "policy repo rate" in clause.lower() and len(clause) < 500
                    and re.search(r"(?:to|at)\s+[\d.]+\s*per cent", clause, flags=re.I)}
    if prior_levels != {Decimal(str(prior_record["repo_pct"]))}:
        raise ValueError("Initial repo record does not agree with the published resolution")
    if prior_record["stance"] != "accommodative" or "accommodative stance" not in normalized(prior_soup.get_text(" ", strip=True)).lower():
        raise ValueError("Initial stance is not verified by its resolution")
    previous = prior_levels.pop()
    meetings = []
    for row in rows:
        source = source_path(root, row["source_file"])
        if digest(source) != row["source_sha256"]:
            raise ValueError(f"Label source hash mismatch: {row['meeting_date']}")
        soup = BeautifulSoup(source.read_bytes(), "html.parser")
        metadata = StatementExtractor.extract_meeting_metadata(soup)
        if any(row[key] != metadata[key] for key in ("meeting_date", "meeting_start_date", "publication_date")
               if key != "meeting_date") or row["meeting_date"] != metadata["decision_date"]:
            raise ValueError("Scientific label dates disagree with primary-source metadata")
        clauses = {normalized(node.get_text(" ", strip=True)) for node in soup.find_all(["p", "li"])}
        whole_text = normalized(soup.get_text(" ", strip=True))
        for key in ("policy_rate_clause", "policy_stance_clause"):
            if normalized(row[key]) not in clauses:
                raise ValueError(f"Missing exact committee clause: {key}")
        for excerpt in row["resolution_evidence"]:
            if normalized(excerpt) not in whole_text:
                raise ValueError("Missing scientific vote-resolution excerpt")
        level = policy_level(row["policy_rate_clause"])
        action = (level - previous) * 100
        if action != action.to_integral_value():
            raise ValueError("Historical policy change is not an integer basis point")
        stated_change = re.search(r"by\s+(\d+)\s+basis points", row["policy_rate_clause"], flags=re.I)
        if stated_change and abs(action) != Decimal(stated_change.group(1)):
            raise ValueError("Policy change and consecutive published levels disagree")
        if "unchanged" in row["policy_rate_clause"].lower() and action != 0:
            raise ValueError("Published unchanged policy conflicts with prior level")
        ballots = member_ballots(soup)
        if sorted(member for member, ballot in ballots.items() if ballot == "No") != row["rate_dissenters"]:
            raise ValueError("Annotated rate dissent differs from the literal published ballot")
        stance_targets = row["formal_stance_targets"]
        if set(stance_targets) != set(ballots) or any(value is not None and type(value) is not bool
                                                     for value in stance_targets.values()):
            raise ValueError("Formal stance observability must cover this exact roster with bool or null")
        if stance_targets != formal_stance_targets(soup, row["resolution_evidence"], ballots):
            raise ValueError("Annotated formal stance targets differ from the primary-source votes")
        if sorted(member for member, target in stance_targets.items() if target is True) != row["stance_dissenters"]:
            raise ValueError("Formal stance targets and known-positive labels disagree")
        if sorted(member for member, target in stance_targets.items() if target is None) != row["reservations"]:
            raise ValueError("Unresolved reservations must retain missing formal-vote targets")
        for member, evidence in row["member_stance_evidence"].items():
            if member not in ballots or not evidence or any(normalized(item) not in whole_text for item in evidence):
                raise ValueError("Missing or unattributed formal stance support")
        if set(row["member_stance_evidence"]) != set(ballots):
            raise ValueError("Every formal stance target needs supporting primary-source evidence")
        # Signed statements can resolve a reservation in the committee summary.
        for member in row["statement_stance_dissenters"]:
            evidence = row["member_stance_evidence"][member]
            full_text = normalized(soup.get_text(" ", strip=True))
            patterns = {item["member_id"]: item["pattern"] for item in MEMBER_PATTERNS}
            headings = sorted((match.start(), name) for name, pattern in patterns.items()
                              if (match := re.search(pattern, full_text, flags=re.I)))
            blocks = {name: full_text[start:headings[i + 1][0] if i + 1 < len(headings) else len(full_text)]
                      for i, (start, name) in enumerate(headings)}
            if member not in blocks or not any(normalized(item) in blocks[member]
                       and re.search(r"vot(?:e|ing) against (?:the )?(?:accommodative|policy) stance", item, flags=re.I)
                       for item in evidence):
                raise ValueError("Statement-resolved formal dissent lacks an attributed explicit vote")
        meetings.append({**row, "actual_rate_bps": int(action), "actual_stance": policy_stance(row["policy_stance_clause"]),
                         "repo_before_pct": float(previous), "repo_after_pct": float(level),
                         "literal_rate_ballots": ballots,
                         "exact_rate_disagreement_targets": {member: ballot == "No" for member, ballot in ballots.items()}})
        previous = level
    return {"version": "source-linked-historical-labels-v1", "definitions": annotations["definitions"],
            "annotation_sha256": digest(annotations_path),
            "annotation_file": str(annotations_path.relative_to(root)),
            "provenance": annotations["provenance"], "meetings": meetings}


def write_new(path, obj):
    payload = (json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"Different immutable panel artifact exists: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(payload)


def build_vintage_panel(output_dir, fed_ledger=None, gdp_ledger=None, *, source_root=ROOT,
                        label_ledger=None, cpi_ledger=None, input_manifest=None):
    """Build only from the frozen scientific catalogue, into an explicit new destination.

    The existing positional ledger arguments remain supported. ``source_root``
    allows a clean source-only copy to rebuild without accessing this checkout.
    ``gdp_ledger=None`` retains the prior opt-in GDP behavior; the reconstruction
    CLI explicitly selects the GDP ledger to reproduce vintage_v3.
    """
    root = Path(source_root).resolve()
    if output_dir is None:
        raise ValueError("An explicit new panel output directory is required")
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError("Panel reconstruction requires a new immutable output directory")
    if output_dir == root or root.is_relative_to(output_dir):
        raise ValueError("Output destination cannot contain the scientific source root")
    catalog = verify_input_manifest(root, input_manifest)
    def frozen_input(value):
        path = source_path(root, value)
        name = str(path.relative_to(root))
        if name not in catalog["files"]:
            raise ValueError(f"Input is not declared in the immutable scientific catalogue: {name}")
        return path
    cpi_path = frozen_input(cpi_ledger or "research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv")
    cpi_dir = cpi_path.parent
    def meeting_rows(path):
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        dates = [row["decision_date"] for row in rows]
        if len(dates) != len(set(dates)):
            raise ValueError("Duplicate meeting date in scientific observation ledger")
        return rows
    cpi_rows = sorted(meeting_rows(cpi_path), key=lambda r: r["decision_date"])
    labels_path = frozen_input(label_ledger or LABEL_DIRECTORY / "label_ledger.json")
    ledger = read_json(labels_path)
    reconstructed_labels = construct_label_ledger(root, ledger.get("annotation_file"))
    if ledger != reconstructed_labels:
        raise ValueError("Scientific label ledger differs from its primary-source reconstruction")
    targets_path = frozen_input(labels_path.parent / "observed_targets.json")
    if read_json(targets_path) != observed_member_targets(ledger):
        raise ValueError("Observed member targets differ from the reconstructed scientific labels")
    labels = {r["meeting_date"]: r for r in ledger["meetings"]}
    if len(labels) != len(cpi_rows) or len(cpi_rows) != 25:
        raise ValueError("Expected complete unique 25-meeting historical joins")
    if set(labels) != {row["decision_date"] for row in cpi_rows}:
        raise ValueError("CPI and label dates must form an exact unique join")
    fed_path = frozen_input(fed_ledger or "research/source_ledgers/gdp_fed_vintages/meeting_fed_ledger.csv")
    fed = {r["decision_date"]: r for r in meeting_rows(fed_path)}
    gdp_path = frozen_input(gdp_ledger) if gdp_ledger else None
    gdp = {r["decision_date"]: r for r in meeting_rows(gdp_path)} if gdp_path else {}
    for name, rows in (("Fed", fed), ("GDP", gdp)):
        if rows and set(rows) != set(labels):
            raise ValueError(f"{name} ledger dates do not form an exact historical join")
    prior_dir = root / "research/source_ledgers/prior_policy"
    prior_record = json.loads((prior_dir / "source_record.json").read_text())
    prior_source = prior_dir / "august_2020_resolution.html"
    if digest(prior_source) != prior_record["sha256"]:
        raise ValueError("Changed initial policy source")
    previous = {"repo": prior_record["repo_pct"], "stance": prior_record["stance"], "source": prior_source,
                "release": "2020-08-07T00:00:00+05:30", "period": prior_record["decision_date"], "url": prior_record["url"]}
    snapshots, truth_rows = [], []
    for cpi in cpi_rows:
        meeting = cpi["decision_date"]
        label = labels[meeting]
        source = source_path(root, label["source_file"])
        soup = BeautifulSoup(source.read_bytes(), "html.parser")
        meta = StatementExtractor.extract_meeting_metadata(soup)
        if meta["decision_date"] != meeting:
            raise ValueError("Truth decision date does not agree with source title")
        text = normalized(soup.get_text(" ", strip=True))
        for excerpt in label["resolution_evidence"]:
            if normalized(excerpt) not in text:
                raise ValueError(f"Truth resolution excerpt missing: {meeting}")
        rate_action = label["actual_rate_bps"]
        stance = label["actual_stance"]
        post_repo = label["repo_after_pct"]
        if previous["repo"] != label["repo_before_pct"]:
            raise ValueError("Published policy path has a discontinuity")
        # Require a source clause linking the repo rate to the actual published level.
        clauses = [normalized(n.get_text(" ", strip=True)) for n in soup.find_all(["li", "p"])]
        rate_clauses = [t for t in clauses if "policy repo rate" in t.lower() and len(t) < 1000
                        and any(float(value) == post_repo for value in re.findall(r"(?:to|at)\s+([\d.]+)\s*per cent", t))]
        if not rate_clauses:
            raise ValueError(f"Cannot verify published repo level {post_repo} on {meeting}")
        truth = {"meeting_date": meeting, "actual_rate_bps": rate_action, "actual_stance": stance,
                 "rate_dissenters": label["rate_dissenters"],
                 "stance_dissenters": label["stance_dissenters"],
                 "reservations": label["reservations"],
                 "guidance_disagreements": label["guidance_disagreements"],
                 "source_file": str(source.relative_to(root)), "source_sha256": digest(source),
                 "source_lines": label["source_lines"], "resolution_evidence": label["resolution_evidence"],
                 "publication_date": meta["publication_date"],
                 "definition": "formal rate and stance dissent only; reservations and guidance are separate"}
        truth_rows.append(truth)
        observations = []
        def add(field, value, units, period, vintage, released, url, path, sha, pointer, basis):
            observations.append(ObservationEvidence(field=field, value=value, units=units,
                reference_period=period, vintage=vintage, released_at=released, source_url=url,
                source_file=str(Path(path).relative_to(root)), source_sha256=sha,
                source_pointer=pointer, availability_basis=basis))
        for field, value in (("current_repo_rate_pct", previous["repo"]), ("prev_stance", previous["stance"])):
            add(field, value, "% per annum" if field.startswith("current") else "stance category",
                previous["period"], "prior published resolution", previous["release"], previous["url"],
                previous["source"], digest(previous["source"]), "Published resolution repo rate and stance",
                "Prior resolution release; conservative following calendar day availability")
        cpi_source = cpi_dir / cpi["local_source_file"]
        for field, column in (("cpi_headline_yoy_pct", "headline_cpi_yoy_pct"), ("cfpi_yoy_pct", "cfpi_yoy_pct")):
            add(field, float(cpi[column]), "YoY %", cpi["reference_month"], cpi["vintage"],
                cpi["documented_release_timestamp_ist"], cpi["source_url"], cpi_source,
                cpi["source_sha256"], cpi["source_table_pointer"], cpi["release_timestamp_basis"])
        extra = {}
        if fed:
            row = fed[meeting]
            if row["series"] != "us_fed_target_upper_pct":
                raise ValueError("Fed series must be target upper bound")
            cutoff_day = datetime.fromisoformat(cpi["cutoff_exclusive_ist"]).date()
            if date.fromisoformat(row["policy_effective_date"]) >= cutoff_day:
                raise ValueError("Future or unavailable effective Fed policy at information cutoff")
            successor = row.get("valid_until_effective_date_exclusive")
            if successor and date.fromisoformat(successor) < cutoff_day:
                raise ValueError("Superseded Fed policy is not in force at information cutoff")
            field, value = "us_fed_funds_rate_pct", float(row["value"])
            extra[field] = value
            add(field, value, row["units"], row["reference_period"], row["vintage"],
                row["documented_release_timestamp_utc"], row["source_url"], fed_path.parent / row["local_source_file"],
                row["source_sha256"], row["source_table_pointer"], row["release_timestamp_basis"])
        # GDP integration uses an independently verified ledger with the same evidence contract.
        if gdp:
            row = gdp[meeting]
            for field in ("gdp_growth_yoy_pct", "gva_growth_yoy_pct"):
                if row.get(field):
                    value = extra[field] = float(row[field])
                    add(field, value, "YoY %", row["latest_reference_period"], row["vintage"], row["documented_release_timestamp_ist"],
                        row["source_url"], gdp_path.parent / row["local_source_file"], row["source_sha256"],
                        row["gdp_source_table_pointer" if field.startswith("gdp") else "gva_source_table_pointer"], row["release_timestamp_basis"])
        snapshot = MacroMeetingSnapshot(meeting_date=meeting, meeting_start_date=cpi["meeting_start_date"],
            information_cutoff=cpi["cutoff_exclusive_ist"], input_track="source_linked",
            current_repo_rate_pct=previous["repo"], prev_stance=previous["stance"],
            cpi_headline_yoy_pct=float(cpi["headline_cpi_yoy_pct"]), cfpi_yoy_pct=float(cpi["cfpi_yoy_pct"]),
            observations=tuple(observations), **extra)
        snapshot.verify_sources(root)
        snapshots.append(snapshot.model_dump(mode="json"))
        previous = {"repo": post_repo, "stance": stance, "source": source,
                    "release": meta["publication_date"] + "T23:59:59+05:30", "period": meeting,
                    "url": f"https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid={source.stem.rsplit('_', 1)[-1]}"}
    # Re-check every input before publication so concurrent mutation fails closed.
    if catalog != verify_input_manifest(root, input_manifest):
        raise ValueError("Scientific input manifest changed during reconstruction")
    write_new(output_dir / "snapshots.json", snapshots)
    write_new(output_dir / "truth.json", truth_rows)
    write_new(output_dir / "manifest.json", {"version": "source-linked-historical-v3-portable", "n_meetings": len(snapshots),
        "historical_split": {"calibration_through": "2023-04-06", "calibration_count": 17,
                             "retrospective_evaluation_after": "2023-04-06", "evaluation_count": 8},
        "exposure_status": "Entire 2020-2024 panel was already inspected; evaluation is retrospective",
        "snapshots_sha256": digest(output_dir / "snapshots.json"), "truth_sha256": digest(output_dir / "truth.json"),
        "cpi_ledger_sha256": digest(cpi_path), "fed_ledger_sha256": digest(fed_path) if fed else None,
        "gdp_ledger_sha256": digest(gdp_path) if gdp else None,
        "label_ledger_sha256": digest(labels_path),
        "input_manifest_sha256": digest(source_path(root, input_manifest or LABEL_DIRECTORY / "input_manifest.json")),
        "label_observability": "Archival truth retains known-positive lists; formal stance unknowns are explicit in the standalone label ledger",
        "withheld_fields": [f for f in ("cpi_core_yoy_pct", "cpi_food_yoy_pct", "output_gap_pct", "iip_growth_yoy_pct",
                              "system_liquidity_cr", "usd_inr_exchange_rate", "brent_crude_usd_bbl", "monsoon_departure_lpa_pct")],
        "full_open_economy_benchmark_ready": False,
        "limits": "Printed release timing and current retained bytes; not independently archived contemporaneous hashes."})
    return snapshots, truth_rows


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gdp-ledger", type=Path)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--label-ledger", type=Path)
    parser.add_argument("--input-manifest", type=Path)
    args = parser.parse_args()
    build_vintage_panel(args.output_dir, gdp_ledger=args.gdp_ledger, source_root=args.source_root,
                        label_ledger=args.label_ledger, input_manifest=args.input_manifest)
