"""Reconstruct the original historical scientific panel entirely offline.

Invoke from a source-only checkout with an explicit new output root. Comparisons
against an archival panel are optional diagnostics, never reconstruction inputs.
"""
import argparse
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.data_pipeline.vintage_panel import (LABEL_DIRECTORY, build_vintage_panel, digest,
                                            read_json, source_path, verify_input_manifest, write_new)
from research.source_ledgers.historical_labels_round002.export_labels import export


def rebuild_scientific_inputs(source_root, output_root, *, expected_input_manifest_sha256=None,
                              reference_panel=None):
    root = Path(source_root).resolve()
    output = Path(output_root).resolve()
    if output.exists():
        raise FileExistsError("Use a new output root; reconstruction never overwrites an existing artifact")
    if output == root or root.is_relative_to(output):
        raise ValueError("Output root cannot contain the scientific source root")
    input_manifest_path = source_path(root, LABEL_DIRECTORY / "input_manifest.json")
    input_manifest_hash = digest(input_manifest_path)
    if expected_input_manifest_sha256 is not None and expected_input_manifest_sha256 != input_manifest_hash:
        raise ValueError("Separately supplied scientific input manifest anchor does not match")
    catalog = verify_input_manifest(root)
    # These are the actual numerical reconstruction dependencies, not code history.
    code_paths = ("src/data_pipeline/vintage_panel.py", "src/data_pipeline/statement_extractor.py",
                  "src/schemas/macro_schema.py", "src/schemas/decision_space.py",
                  "research/source_ledgers/historical_labels_round002/export_labels.py",
                  "research/verification/rebuild_scientific_inputs.py")
    code_hashes = {name: digest(source_path(root, name)) for name in code_paths}
    build_vintage_panel(output / "panel", gdp_ledger="research/source_ledgers/gdp_fed_vintages/meeting_gdp_ledger.csv",
                        source_root=root)
    export(root, output / "labels")
    if catalog != verify_input_manifest(root) or digest(input_manifest_path) != input_manifest_hash:
        raise ValueError("Scientific inputs changed during offline reconstruction")
    if any(digest(source_path(root, name)) != sha for name, sha in code_hashes.items()):
        raise ValueError("Scientific reconstruction code changed during execution")
    comparisons = {}
    if reference_panel is not None:
        reference = Path(reference_panel).resolve()
        for name in ("snapshots.json", "truth.json", "manifest.json"):
            original, rebuilt = reference / name, output / "panel" / name
            before, after = read_json(original), read_json(rebuilt)
            comparisons[name] = {"reference_sha256": digest(original), "rebuilt_sha256": digest(rebuilt),
                                 "byte_equal": original.read_bytes() == rebuilt.read_bytes(),
                                 "semantic_equal": before == after}
            if name == "manifest.json":
                comparisons[name]["different_keys"] = sorted(key for key in set(before) | set(after)
                                                             if before.get(key) != after.get(key))
    versions = {name: importlib.metadata.version(name) for name in ("pydantic", "beautifulsoup4")}
    receipt = {"version": "offline-historical-input-reconstruction-v1", "status": "complete",
               "input_manifest_sha256": input_manifest_hash, "scientific_input_files": len(catalog["files"]),
               "input_hashes": catalog["files"], "code_sha256": code_hashes,
               "environment": {"python": sys.version, "executable": sys.executable,
                               "platform": platform.platform(), "dependencies": versions},
               "command_arguments": sys.argv, "reference_comparison": comparisons,
               "reference_used_for_construction": False, "network_calls": 0, "model_calls": 0,
               "scope": "Source reconstruction and observability, not empirical model replication or superiority"}
    write_new(output / "reconstruction_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-input-manifest-sha256")
    parser.add_argument("--reference-panel", type=Path)
    args = parser.parse_args()
    result = rebuild_scientific_inputs(args.source_root, args.output_root,
                                      expected_input_manifest_sha256=args.expected_input_manifest_sha256,
                                      reference_panel=args.reference_panel)
    print(json.dumps({"status": result["status"], "scientific_input_files": result["scientific_input_files"],
                      "reference_comparison": result["reference_comparison"]}, sort_keys=True))
