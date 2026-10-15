"""Offline export from portable scientific annotations and retained primary bytes.

No legacy parquet, audit output, reviewer text, network or model access is used.
The checked-in input manifest is a frozen catalogue; export into a new destination
to check reproducibility. Its optional creation flag is for a new source version.
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.data_pipeline.vintage_panel import (LABEL_DIRECTORY, construct_label_ledger,
                                            digest, observed_member_targets, source_path, write_new)


def observed_targets(ledger):
    return observed_member_targets(ledger)


def scientific_catalogue(root, label_directory):
    root = Path(root).resolve()
    label_directory = Path(label_directory).resolve()
    if not label_directory.is_relative_to(root):
        raise ValueError("A frozen scientific catalogue must live inside its portable source root")
    inputs = {str((label_directory / name).relative_to(root)) for name in
              ("label_annotations.json", "label_ledger.json", "observed_targets.json")}
    inputs.update(("research/source_ledgers/prior_policy/source_record.json",
                   "research/source_ledgers/prior_policy/august_2020_resolution.html"))
    ledgers = ("research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv",
               "research/source_ledgers/gdp_fed_vintages/meeting_gdp_ledger.csv",
               "research/source_ledgers/gdp_fed_vintages/meeting_fed_ledger.csv")
    for name in ledgers:
        path = source_path(root, name)
        inputs.add(name)
        with path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                inputs.add(str((path.parent / row["local_source_file"]).relative_to(root)))
                if row.get("statement_local_source_file"):
                    inputs.add(str((path.parent / row["statement_local_source_file"]).relative_to(root)))
                if row.get("meeting_minutes_file"):
                    inputs.add(row["meeting_minutes_file"])
    return {"version": "historical-scientific-inputs-v1", "files": {
            name: digest(source_path(root, name)) for name in sorted(inputs)},
            "scope": "Source-only offline reconstruction of the exposed original 25-meeting panel",
            "limitations": "Retained official source bytes and documented releases, not authenticated historical endpoint snapshots; no full macro coverage"}


def export(source_root, output_dir, *, freeze_input_manifest=False):
    root = Path(source_root).resolve()
    output = Path(output_dir).resolve()
    ledger = construct_label_ledger(root)
    write_new(output / "label_ledger.json", ledger)
    write_new(output / "observed_targets.json", observed_targets(ledger))
    if freeze_input_manifest:
        if output != (root / LABEL_DIRECTORY).resolve():
            raise ValueError("Freeze requires this source version's canonical scientific label directory")
        write_new(output / "input_manifest.json", scientific_catalogue(root, output))
    return ledger


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--freeze-input-manifest", action="store_true")
    args = parser.parse_args()
    ledger = export(args.source_root, args.output_dir, freeze_input_manifest=args.freeze_input_manifest)
    print(f"Exported {len(ledger['meetings'])} source-checked historical meeting labels")
