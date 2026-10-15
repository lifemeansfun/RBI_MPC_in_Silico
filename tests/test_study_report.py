"""A report must neither promote mock scores nor publish corrupted evidence."""
import json
import shutil

import pytest

from test_study_replay import completed_study
from src.backtest.study_artifacts import strict_json
from src.infra.exceptions import ArtifactIntegrityError
from src.reporting.report_builder import ReportBuilder
from src.reporting.study_report import build_study_report


def test_report_reconstructs_evidence_and_preserves_mock_scope(completed_study,tmp_path):
    study,anchor = completed_study
    out = tmp_path/'verified_report'
    summary = build_study_report({'full':study},{'full':anchor},out)
    assert summary['evidence_scope']=='Mock procedural diagnostic'
    assert summary['generation_evidence_counts']=={'mock':96}
    assert summary['n_meetings']==2 and summary['n_replicates']==2
    assert summary['replay_provider_calls']==0
    assert summary['independent_live_replication'] is False
    assert summary['observed_rate_class_counts']=={0:2}
    observed = summary['observability_aware_dissent']['full']['1']['formal_stance_dissent']
    assert observed['n_member_targets']==12
    assert observed['observed_targets']==10 and observed['unknown_targets']==2
    assert observed['complete_meetings']==[]
    assert summary['baseline_metrics']['hold_previous_stance']['rate_mae_bps']==0
    assert not summary['paired_rate_mae_comparisons']['full']['hold_previous_stance']['superiority_supported']
    text = (out/'RESULTS_REPORT.md').read_text()
    assert 'Mock procedural diagnostic: 2 meetings' in text
    assert 'PASSED' not in text and 'REQUIRES RECALIBRATION' not in text
    assert 'Section 45ZI' in text
    assert strict_json(out/'summary.json')['scientific_readiness'].startswith('Not established')


def test_report_corruption_cannot_publish_a_scientific_summary(completed_study,tmp_path):
    original,anchor = completed_study
    copied = tmp_path/'evidence';shutil.copytree(original.parents[1],copied)
    study = copied/original.parent.name/original.name
    path = study/'metrics_by_replicate.json';metrics = strict_json(path)
    metrics['1']['exact_rate_accuracy_pct']=12.5
    path.write_text(json.dumps(metrics))
    output = tmp_path/'report'
    with pytest.raises(ArtifactIntegrityError):
        build_study_report({'full':study},{'full':anchor},output)
    assert not output.exists()


def test_legacy_exporter_handles_undefined_f1_without_promoting_thresholds(tmp_path):
    metrics = {'directional_rate_accuracy_pct':100.,'stance_accuracy_pct':100.,
               'dissent_precision':None,'dissent_recall':None,'dissent_f1':None,
               'passed_validation_gate':True}
    report = ReportBuilder(tmp_path).generate_markdown_report(metrics,[],[],evidence_types=['mock'])
    text = report.read_text()
    assert 'undefined or not supplied' in text
    assert 'evidence types supplied by the caller: mock' in text
    assert 'PASSED' not in text and 'successfully captures' not in text
    assert '§45ZI' in text and 'under Section 45ZL' not in text
