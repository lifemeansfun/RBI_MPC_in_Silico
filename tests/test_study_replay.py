"""Complete offline evidence paths and adversarial scientific-input corruption.

Real retained sources are used to test evidence plumbing. All generation is mock;
passing these tests is neither a live experiment nor evidence of forecast skill.
"""
import asyncio
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from src.backtest.backtest_runner import BacktestRunner, load_snapshots, PROJECT_ROOT
from src.backtest.study_artifacts import strict_json
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.infra.config_loader import AppConfig
from src.infra.evidence import content_hash, file_hash
from src.infra.exceptions import ArtifactIntegrityError, GenerationProvenanceError
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger
from src.persona_engine.extractor import PersonaExtractor
from src.rational.calibration import fit_taylor_comparator
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.validation.baselines import fit_dissent_baseline, baseline_predictions
from src.validation.metrics import MetricsEvaluator, aligned_prediction_join, paired_meeting_uncertainty
from src.validation.study_replay import replay_study


@pytest.fixture(scope='module')
def completed_study(tmp_path_factory):
    root = tmp_path_factory.mktemp('complete_source_linked_mock_study')
    async def run():
        orchestrator = DebateOrchestrator(LLMClient(provider='mock', cache_enabled=False),
                                        TranscriptLogger(output_root=root/'logger'))
        runner = BacktestRunner(results_dir=root/'evidence', orchestrator=orchestrator,
                                n_replicates=2, experiment_id='mock_integrity_test')
        await runner.run_panel_backtest(max_meetings=2, resume=False)
    asyncio.run(run())
    study = root/'evidence'/'mock_integrity_test'/'full'
    anchor = content_hash(strict_json(study/'study_manifest.json'))
    return study, anchor


def test_complete_portable_replay_and_replicate_separation(completed_study, tmp_path):
    source, anchor = completed_study
    copied_root = tmp_path/'copied'
    shutil.copytree(source.parents[1], copied_root)
    copied = copied_root/'mock_integrity_test'/'full'
    summary = replay_study(copied, tmp_path/'rebuilt', expected_manifest_hash=anchor)
    assert summary['n_meetings'] == 2 and summary['n_replicates'] == 2
    assert summary['generation_evidence_counts'] == {'mock':96}
    assert summary['replay_provider_calls'] == 0
    assert summary['independent_live_replication'] is False
    assert (tmp_path/'rebuilt'/'predictions.json').read_bytes() == (source/'predictions.json').read_bytes()
    predictions = strict_json(source/'predictions.json')
    assert predictions[0]['identity']['replicate_id'] != predictions[1]['identity']['replicate_id']
    artifacts = [strict_json(p) for p in source.parents[1].rglob('round_1_shaktikanta_das.json')]
    assert len({a['generation']['metadata']['seed'] for a in artifacts}) == 4


@pytest.mark.parametrize('corruption', ['missing_round', 'raw_action', 'metric', 'prediction', 'truth',
                                      'source_bytes', 'roster', 'checkpoint_track', 'outcome'])
def test_corrupt_study_fails_before_publishing(completed_study, tmp_path, corruption):
    source, anchor = completed_study
    # Checkpoints reference run directories outside the condition's own directory.
    root = tmp_path/'evidence'
    shutil.copytree(source.parents[1], root)
    study = root/'mock_integrity_test'/'full'
    if corruption == 'missing_round':
        next(root.rglob('round_3_shaktikanta_das.json')).unlink()
    else:
        if corruption == 'raw_action':
            path = next(root.rglob('round_4_shaktikanta_das.json'))
            data = strict_json(path)
            raw = json.loads(data['generation']['raw_text']); raw['final_rate_vote_bps'] = True
            data['generation']['raw_text'] = json.dumps(raw)
        elif corruption == 'metric':
            path = study/'metrics_by_replicate.json'; data = strict_json(path)
            data['1']['rate_mae_bps'] += 1
        elif corruption == 'prediction':
            path = study/'predictions.json'; data = strict_json(path); data[0]['sim_rate_bps'] = 50
        elif corruption == 'truth':
            path = study/'inputs/truth.json'; data = strict_json(path); data[0]['actual_rate_bps'] = -25
        elif corruption == 'source_bytes':
            path = study/'inputs/raw_sources.json'; data = strict_json(path)
            data[next(iter(data))]['bytes'] = 'Y29ycnVwdGlvbg=='
        elif corruption == 'roster':
            path = study/'inputs/personas.json'; data = strict_json(path)
            data['shaktikanta_das']['member_id'] = 'an_unplanned_member'
        elif corruption == 'checkpoint_track':
            path = next((study/'checkpoints').glob('*.json')); data = strict_json(path)
            data['payload']['evidence_types'] = ['live_model']
        else:
            path = next(root.rglob('meeting_outcome.json')); data = strict_json(path)
            data['rate_decision_bps'] = 50
        # Rehash these mutated envelopes too: semantic checks must not rely only on
        # detecting changed bytes in a self-reported content hash.
        if corruption in ('raw_action','outcome'):
            data.pop('artifact_content_hash')
            data['artifact_content_hash'] = content_hash(data)
        elif corruption == 'checkpoint_track':
            data.pop('content_hash')
            data['content_hash'] = content_hash(data)
        path.write_text(json.dumps(data))
        if corruption in ('raw_action','outcome'):
            relative = str(path.relative_to(root))
            for checkpoint in (study/'checkpoints').glob('*.json'):
                document = strict_json(checkpoint)
                matching = [a for a in document['artifacts'].values() if a['path']==relative]
                if matching:
                    matching[0]['sha256'] = file_hash(path)
                    document.pop('content_hash')
                    document['content_hash'] = content_hash(document)
                    checkpoint.write_text(json.dumps(document))
    with pytest.raises((ArtifactIntegrityError, ValueError, ValidationError)):
        replay_study(study, tmp_path/'rebuilt', expected_manifest_hash=anchor)
    assert not (tmp_path/'rebuilt').exists()


def test_changed_manifest_needs_new_anchor(completed_study, tmp_path):
    source, anchor = completed_study
    root = tmp_path/'evidence'; shutil.copytree(source.parents[1], root)
    study = root/'mock_integrity_test'/'full'
    manifest = strict_json(study/'study_manifest.json'); manifest['seed_base'] += 1
    (study/'study_manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ArtifactIntegrityError, match='anchor'):
        replay_study(study, tmp_path/'rebuilt', expected_manifest_hash=anchor)


@pytest.mark.parametrize('mode,masked,expected_calls', [('earlier_rounds',False,24), ('independent',False,12), ('full',True,24)])
def test_control_and_masked_paths_replay(tmp_path, mode, masked, expected_calls):
    async def run():
        orchestrator = DebateOrchestrator(LLMClient(provider='mock',cache_enabled=False),
                                         TranscriptLogger(output_root=tmp_path/'initial'))
        runner = BacktestRunner(results_dir=tmp_path/'evidence',orchestrator=orchestrator,n_replicates=1,
            experiment_id='controls',condition_id=mode,control_mode=mode,mask_identity=masked,mask_date=masked)
        await runner.run_panel_backtest(max_meetings=1,resume=False)
    asyncio.run(run())
    study = tmp_path/'evidence'/'controls'/mode
    summary = replay_study(study,tmp_path/'rebuilt',expected_manifest_hash=content_hash(strict_json(study/'study_manifest.json')))
    assert summary['generation_evidence_counts'] == {'mock':expected_calls}


def test_credentials_never_enter_frozen_configuration():
    cfg = AppConfig(gemini_api_key='fixture_sensitive_value', openai_api_key='fixture_other_value')
    assert cfg.gemini_api_key == 'fixture_sensitive_value'
    assert 'fixture_sensitive_value' not in repr(cfg)
    assert not any(name.endswith('_api_key') for name in cfg.model_dump())


def test_future_statement_injection_cannot_change_calibration(tmp_path):
    statements = tmp_path/'statements'; statements.mkdir()
    def add(meeting, publication, text):
        directory = statements/meeting; directory.mkdir()
        path = directory/'shaktikanta_das.txt'; path.write_text(text)
        raw = tmp_path/f'{meeting}.html'; raw.write_text(text)
        metadata = {'decision_date':meeting, 'publication_date':publication,
            'source_file':raw.name, 'source_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),
            'statement_sha256':{'shaktikanta_das':hashlib.sha256(path.read_bytes()).hexdigest()},
            'availability_basis':'synthetic fixture publication day'}
        (directory/'source_manifest.json').write_text(json.dumps(metadata))
    add('2023-04-06','2023-04-20','Inflation persistence requires vigilance and a firm target commitment.')
    extractor = PersonaExtractor(statements_dir=statements,output_dir=tmp_path/'profiles',source_root=tmp_path)
    before = extractor.analyze_member('shaktikanta_das')
    add('2023-06-08','2023-06-22','Growth slack recovery neutral real rate lag soften downturn.')
    assert extractor.analyze_member('shaktikanta_das') == before


def test_future_and_changed_input_evidence_rejected():
    snapshot = load_snapshots(PROJECT_ROOT/'data/processed/vintage_v3/snapshots.json')[-1]
    payload = snapshot.model_dump(mode='json')
    payload['observations'][0]['released_at'] = payload['information_cutoff']
    with pytest.raises(ValidationError,match='Future'):
        MacroMeetingSnapshot.model_validate(payload)
    payload = snapshot.model_dump(mode='json'); payload['cpi_headline_yoy_pct'] += .1
    with pytest.raises(ValidationError,match='mismatch'):
        MacroMeetingSnapshot.model_validate(payload)


def test_metrics_truth_positives_are_not_model_true_positives():
    score = MetricsEvaluator.evaluate_panel([0,25],[0,40],['neutral']*2,['neutral']*2,
        [[],[]],[['a'],['a','b']],predicted_rate_dissenters=[[],[]],true_rate_dissenters=[['a'],['a','b']])
    assert score.true_positive_dissent_events == 0 and score.observed_positive_dissent_events == 3
    assert score.directional_rate_accuracy_pct == 100 and score.exact_rate_accuracy_pct == 50
    assert score.rate_mae_bps == 7.5 and score.dissent_f1 == 0
    no_positive = MetricsEvaluator.compute_dissent_f1([[],[]],[[],[]])
    assert no_positive[2] is None
    with pytest.raises(ValueError):
        aligned_prediction_join(pd.DataFrame({'meeting_date':['2023-01-01','2023-01-01']}),
                                pd.DataFrame({'meeting_date':['2023-01-01']}))
    paired = paired_meeting_uncertainty(['2023-01-01','2023-02-01'],[0,0],[0,0],n_resamples=100)
    assert not paired['superiority_supported'] and paired['sign_flip_pvalue'] == 1


def test_baseline_release_cutoff_and_full_comparator_missing_input():
    truth = strict_json(PROJECT_ROOT/'data/processed/vintage_v3/truth.json')
    snapshots = load_snapshots(PROJECT_ROOT/'data/processed/vintage_v3/snapshots.json')
    calibration = truth[:17]
    fitted = fit_dissent_baseline(calibration)
    rows = baseline_predictions(snapshots[17:],truth,fitted)
    assert len(rows) == 24 and all(row['source_prior_meeting'] < row['meeting_date'] for row in rows)
    delayed = copy.deepcopy(calibration); delayed[-1]['publication_date'] = '2023-05-01'
    with pytest.raises(ValueError,match='unavailable'):
        fit_dissent_baseline(delayed)
    with pytest.raises(ValueError,match='Full open-economy'):
        fit_taylor_comparator(snapshots[:17],[r['actual_rate_bps'] for r in calibration],bootstrap_draws=10)
    comparator = fit_taylor_comparator(snapshots[:17],[r['actual_rate_bps'] for r in calibration],
                                       reduced_input=True,bootstrap_draws=10)
    assert comparator.beta == 0 and comparator.bootstrap_block_size == 2
    assert 'unresolved' in comparator.input_scope and 'temporal-block' in comparator.bootstrap_method
    bad_actions = [r['actual_rate_bps'] for r in calibration]; bad_actions[0] = '0'
    with pytest.raises(ValueError,match='exact integer'):
        fit_taylor_comparator(snapshots[:17],bad_actions,reduced_input=True,bootstrap_draws=10)
