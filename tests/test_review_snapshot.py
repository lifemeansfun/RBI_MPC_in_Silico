"""Adversarial checks for supplied-context isolation, not proof of agent blindness."""
import hashlib
import json
from pathlib import Path

import pytest
from scripts import create_review_snapshot as builder


def put(root, relative, data='scientific input'):
    path=root/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(data)
    return path


def test_positive_allowlist_and_blind_manifest(tmp_path):
    source=tmp_path/'source'
    for relative in (
        'src/module.py','tests/test_science.py','config/config.yaml',
        'research/verification/rebuild_scientific_inputs.py',
        'research/source_ledgers/historical_labels_round002/README.md',
        'personas/calibration_2023-04-30_v2/person.yaml',
        'data/raw/minutes_html/source.html','results/tables/measurements.csv',
        'Makefile','scripts/reproduce_offline.py',
    ): put(source,relative)
    for relative in (
        'outputs/main_paper/artifact.docx','research/peer_reviews/round_001/REVIEW.md',
        'research/implementation_plans/round_002.md','personas/PERSONA_REVIEW.md',
        'personas/calibration_2023-04-30_v2/PERSONA_REVIEW.md','AGENTS.md',
        'research/source_ledgers/cpi_vintages/.env','src/.env.local',
        'src/credentials.json','src/__pycache__/old.py',
        'tests/checkout/old_result.json','src/manuscript.py',
        'results/unrelated_output/result.json','results/RESULTS_REPORT.md',
        '.git/history.json','MEMORY.md',
    ): put(source,relative,'FORBIDDEN CONTEXT')
    record=builder.create_snapshot(tmp_path/'record',source,
                                  snapshot_dir=tmp_path/'snapshot',study_root=None,share_runtime=False)
    snapshot=Path(record['snapshot'])
    assert record['source_files_unchanged']
    assert record['input_count']==11
    for path in snapshot.rglob('*'):
        if path.is_file(): assert 'FORBIDDEN CONTEXT' not in path.read_text()
    manifest=json.loads((snapshot/'INPUT_MANIFEST.json').read_text())
    assert 'source_commit' not in manifest and 'source_branch' not in manifest
    assert set(manifest['input_hashes'])==set(record['input_hashes'])
    for relative,expected in manifest['input_hashes'].items():
        assert hashlib.sha256((snapshot/relative).read_bytes()).hexdigest()==expected
    assert not (snapshot/'.venv').exists()


def test_only_explicit_anchored_study_data_is_copied(tmp_path):
    source=tmp_path/'source'; study=Path('results/frozen_study')
    for relative in ('protocol.json','anchors/full.json','evidence/experiment/full/study_manifest.json',
                     'baseline_predictions.json','baseline_selection.json'):
        put(source,study/relative)
    put(source,study/'diagnostic_summary.json','prior synthesis excluded')
    put(source,study/'checkout/src/old.py','excluded')
    selected=builder.selected_inputs(source,study)
    assert len(selected)==5
    assert study/'diagnostic_summary.json' not in selected
    with pytest.raises(ValueError,match='requires protocol'):
        builder.selected_inputs(source,Path('results/unrelated'))


@pytest.mark.parametrize('relative',[
    'research/peer_reviews/round_001','../results/study',
    'results/peer_reviews/study','results/implementation_plans/study',
])
def test_study_escape_and_forbidden_context_reject(tmp_path,relative):
    with pytest.raises(ValueError):
        builder.selected_inputs(tmp_path,Path(relative))


def test_source_symlinks_do_not_import_external_context(tmp_path):
    source=tmp_path/'source'; source.mkdir()
    outside=put(tmp_path,'outside/memory.json','forbidden')
    (source/'src').mkdir(); (source/'src/hidden.json').symlink_to(outside)
    assert builder.selected_inputs(source,None)==[]
    (source/'src/external').symlink_to(outside.parent,target_is_directory=True)
    assert builder.selected_inputs(source,None)==[]
    (source/'config').symlink_to(outside.parent,target_is_directory=True)
    with pytest.raises(ValueError,match='root is a symlink'):
        builder.selected_inputs(source,None)


def test_exact_file_allowlist_does_not_cross_parent_symlink(tmp_path):
    source=tmp_path/'source';source.mkdir()
    outside=put(tmp_path,'outside/reproduce_offline.py','outside context')
    (source/'scripts').symlink_to(outside.parent,target_is_directory=True)
    assert builder.selected_inputs(source,None)==[]


def test_copy_race_is_preserved_and_rejected(tmp_path,monkeypatch):
    source=tmp_path/'source'; input_file=put(source,'src/module.py','before')
    original=builder.shutil.copy2
    def racing_copy(*args,**kwargs):
        result=original(*args,**kwargs)
        input_file.write_text('after')
        return result
    monkeypatch.setattr(builder.shutil,'copy2',racing_copy)
    with pytest.raises(RuntimeError,match='Snapshot rejected'):
        builder.create_snapshot(tmp_path/'record',source,
                                snapshot_dir=tmp_path/'snapshot',study_root=None,share_runtime=False)
    receipt=json.loads((tmp_path/'record/snapshot_manifest.json').read_text())
    assert receipt['status']=='failed' and receipt['error_type']=='RuntimeError'
    assert (tmp_path/'snapshot/src/module.py').read_text()=='before'
    assert input_file.read_text()=='after'


def test_existing_records_and_snapshot_are_never_overwritten(tmp_path):
    source=tmp_path/'source';put(source,'src/module.py')
    record=tmp_path/'record';record.mkdir();put(record,'keep.txt','existing')
    with pytest.raises(FileExistsError):
        builder.create_snapshot(record,source,study_root=None,share_runtime=False)
    assert (record/'keep.txt').read_text()=='existing'
    snapshot=tmp_path/'snapshot';snapshot.mkdir();put(snapshot,'keep.txt','existing')
    with pytest.raises(RuntimeError,match='Snapshot rejected'):
        builder.create_snapshot(tmp_path/'other_record',source,
                                snapshot_dir=snapshot,study_root=None,share_runtime=False)
    assert (snapshot/'keep.txt').read_text()=='existing'
