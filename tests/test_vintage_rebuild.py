"""Scientific reconstruction, leakage and corruption controls in isolated outputs."""
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from research.verification.rebuild_scientific_inputs import rebuild_scientific_inputs
from src.data_pipeline.vintage_panel import (LABEL_DIRECTORY, ROOT, build_vintage_panel,
                                            construct_label_ledger, read_json)


@pytest.fixture
def source_only(tmp_path):
    root = tmp_path / "scientific_source"
    catalog_path = ROOT / LABEL_DIRECTORY / "input_manifest.json"
    catalog = read_json(catalog_path)
    for name in list(catalog["files"]) + [str(LABEL_DIRECTORY / "input_manifest.json")]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    shutil.copytree(ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for name in (LABEL_DIRECTORY / "export_labels.py", Path("research/verification/rebuild_scientific_inputs.py")):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    assert not (root / "results").exists()
    assert not (root / "data/processed").exists()
    assert not (root / ".git").exists()
    return root


def reanchor(root, name):
    """Deliberately freeze a modified test input to exercise semantic controls."""
    path = root / LABEL_DIRECTORY / "input_manifest.json"
    manifest = read_json(path)
    manifest["files"][name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def change_csv(root, name, column, value, *, duplicate=False):
    path = root / name
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    rows[0][column] = value
    if duplicate:
        rows.append(rows[0].copy())
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    reanchor(root, name)


def test_source_only_cli_rebuild_equals_archival_scientific_files(source_only, tmp_path):
    output = tmp_path / "offline_rebuild"
    anchor = hashlib.sha256((source_only / LABEL_DIRECTORY / "input_manifest.json").read_bytes()).hexdigest()
    command = [sys.executable, str(source_only / "research/verification/rebuild_scientific_inputs.py"),
               "--source-root", str(source_only), "--output-root", str(output),
               "--expected-input-manifest-sha256", anchor]
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT")}
    env.update(PYTHONPATH=str(source_only), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(command, cwd=source_only, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    for name in ("snapshots.json", "truth.json"):
        assert (output / "panel" / name).read_bytes() == (ROOT / "data/processed/vintage_v3" / name).read_bytes()
    receipt = read_json(output / "reconstruction_receipt.json")
    assert receipt["reference_comparison"] == {}
    assert receipt["reference_used_for_construction"] is False
    assert receipt["network_calls"] == receipt["model_calls"] == 0
    assert receipt["input_manifest_sha256"] == anchor
    assert receipt["scientific_input_files"] == len(receipt["input_hashes"])


def test_reference_comparison_honestly_versions_manifest(source_only, tmp_path):
    output = tmp_path / "compared_rebuild"
    receipt = rebuild_scientific_inputs(source_only, output, reference_panel=ROOT / "data/processed/vintage_v3")
    comparisons = receipt["reference_comparison"]
    assert all(comparisons[name]["byte_equal"] and comparisons[name]["semantic_equal"]
               for name in ("snapshots.json", "truth.json"))
    assert comparisons["manifest.json"]["byte_equal"] is False
    assert comparisons["manifest.json"]["semantic_equal"] is False
    assert comparisons["manifest.json"]["different_keys"] == ["input_manifest_sha256", "label_ledger_sha256",
                                                                "label_observability", "version"]


def test_historical_stance_reservations_remain_null(source_only):
    ledger = construct_label_ledger(source_only)
    rows = {row["meeting_date"]: row for row in ledger["meetings"]}
    assert sum(value is None for row in rows.values() for value in row["formal_stance_targets"].values()) == 6
    assert rows["2022-08-05"]["formal_stance_targets"]["jayanth_varma"] is None
    assert rows["2023-12-08"]["formal_stance_targets"]["jayanth_varma"] is None
    assert rows["2021-08-06"]["formal_stance_targets"]["jayanth_varma"] is True
    assert rows["2020-10-09"]["formal_stance_targets"]["jayanth_varma"] is False
    assert rows["2020-10-09"]["guidance_disagreements"] == ["jayanth_varma"]
    assert rows["2022-05-04"]["actual_rate_bps"] == 40
    assert rows["2022-05-04"]["literal_rate_ballots"]["jayanth_varma"] == "Yes"
    assert rows["2022-05-04"]["exact_rate_disagreement_targets"]["jayanth_varma"] is False


def test_changed_primary_source_fails_before_publication(source_only, tmp_path):
    path = source_only / "data/raw/minutes_html/mpc_minutes_prid_50560.html"
    path.write_bytes(path.read_bytes() + b"corruption")
    output = tmp_path / "corrupt_source_rebuild"
    with pytest.raises(ValueError, match="Scientific input hash mismatch"):
        rebuild_scientific_inputs(source_only, output)
    assert not output.exists()


def test_missing_source_fails_before_publication(source_only, tmp_path):
    # The temporary fixture is the only deleted file; current scientific inputs stay intact.
    (source_only / "data/raw/minutes_html/mpc_minutes_prid_50560.html").unlink()
    output = tmp_path / "missing_source_rebuild"
    with pytest.raises(ValueError, match="Missing or outside-source-root"):
        rebuild_scientific_inputs(source_only, output)
    assert not output.exists()


@pytest.mark.parametrize("ledger,column,value", [
    ("research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv", "documented_release_timestamp_ist", "2020-10-08T17:30:00+05:30"),
    ("research/source_ledgers/gdp_fed_vintages/meeting_gdp_ledger.csv", "documented_release_timestamp_ist", "2020-10-08T17:30:00+05:30"),
    ("research/source_ledgers/gdp_fed_vintages/meeting_fed_ledger.csv", "documented_release_timestamp_utc", "2020-10-08T18:00:00+00:00"),
])
def test_future_release_fails_even_when_catalogue_is_reanchored(source_only, tmp_path, ledger, column, value):
    change_csv(source_only, ledger, column, value)
    output = tmp_path / "future_rebuild"
    with pytest.raises(ValueError, match="Future or unavailable release"):
        rebuild_scientific_inputs(source_only, output)
    assert not output.exists()


def test_duplicate_meeting_join_fails(source_only, tmp_path):
    name = "research/source_ledgers/gdp_fed_vintages/meeting_fed_ledger.csv"
    change_csv(source_only, name, "value", "0.25", duplicate=True)
    output = tmp_path / "duplicate_rebuild"
    with pytest.raises(ValueError, match="Duplicate meeting date"):
        rebuild_scientific_inputs(source_only, output)
    assert not output.exists()


def test_unavailable_effective_policy_fails(source_only, tmp_path):
    name = "research/source_ledgers/gdp_fed_vintages/meeting_fed_ledger.csv"
    change_csv(source_only, name, "policy_effective_date", "2020-10-08")
    output = tmp_path / "future_effective_policy"
    with pytest.raises(ValueError, match="Future or unavailable effective Fed policy"):
        rebuild_scientific_inputs(source_only, output)
    assert not output.exists()


def test_changed_label_ledger_fails_primary_reconstruction(source_only, tmp_path):
    name = str(LABEL_DIRECTORY / "label_ledger.json")
    path = source_only / name
    ledger = read_json(path)
    ledger["meetings"][0]["actual_rate_bps"] = 25
    path.write_text(json.dumps(ledger, indent=2) + "\n")
    reanchor(source_only, name)
    output = tmp_path / "wrong_label_rebuild"
    with pytest.raises(ValueError, match="differs from its primary-source reconstruction"):
        rebuild_scientific_inputs(source_only, output)
    assert not output.exists()


def test_unattributed_statement_vote_fails(source_only):
    path = source_only / LABEL_DIRECTORY / "label_annotations.json"
    annotations = read_json(path)
    row = next(row for row in annotations["meetings"] if row["meeting_date"] == "2021-08-06")
    row["member_stance_evidence"]["jayanth_varma"] = row["resolution_evidence"]
    path.write_text(json.dumps(annotations, indent=2) + "\n")
    with pytest.raises(ValueError, match="attributed explicit vote"):
        construct_label_ledger(source_only)


def test_false_stance_annotation_cannot_be_saved_by_rewriting_its_known_positive_list(source_only):
    path = source_only / LABEL_DIRECTORY / "label_annotations.json"
    annotations = read_json(path)
    row = annotations["meetings"][0]
    row["formal_stance_targets"]["ashima_goyal"] = True
    row["stance_dissenters"] = ["ashima_goyal"]
    path.write_text(json.dumps(annotations, indent=2) + "\n")
    with pytest.raises(ValueError, match="differ from the primary-source votes"):
        construct_label_ledger(source_only)


def test_changed_observed_targets_cannot_hide_behind_reanchored_catalogue(source_only, tmp_path):
    name = str(LABEL_DIRECTORY / "observed_targets.json")
    path = source_only / name
    targets = read_json(path)
    targets["channels"]["formal_stance_dissent"][0]["member_targets"]["ashima_goyal"] = True
    path.write_text(json.dumps(targets, indent=2) + "\n")
    reanchor(source_only, name)
    output = tmp_path / "wrong_observed_targets"
    with pytest.raises(ValueError, match="Observed member targets differ"):
        rebuild_scientific_inputs(source_only, output)
    assert not output.exists()


def test_external_catalogue_anchor_fails(source_only, tmp_path):
    output = tmp_path / "anchor_failure"
    with pytest.raises(ValueError, match="Separately supplied.*anchor"):
        rebuild_scientific_inputs(source_only, output, expected_input_manifest_sha256="0" * 64)
    assert not output.exists()


def test_existing_output_root_and_panel_are_never_overwritten(source_only, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "preserved.txt"
    marker.write_text("immutable existing result")
    with pytest.raises(FileExistsError, match="new output root"):
        rebuild_scientific_inputs(source_only, output)
    with pytest.raises(FileExistsError, match="new immutable output"):
        build_vintage_panel(output, source_root=source_only)
    assert marker.read_text() == "immutable existing result"
