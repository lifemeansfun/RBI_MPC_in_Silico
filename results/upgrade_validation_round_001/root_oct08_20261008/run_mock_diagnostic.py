"""Source-linked full-path engineering diagnostic; never live-model evidence.

Run with the producer checkout on PYTHONPATH. Conditions and two replicates are
declared below before output generation. Exposed historical outcomes are known.
"""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import pandas as pd

from src.backtest.backtest_runner import BacktestRunner, PROJECT_ROOT, load_snapshots, code_identity
from src.backtest.study_artifacts import strict_json
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.infra.evidence import content_hash, write_immutable
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger
from src.validation.baselines import fit_dissent_baseline, baseline_predictions
from src.validation.metrics import MetricsEvaluator, paired_meeting_uncertainty
from src.validation.study_replay import replay_study
from src.schemas.macro_schema import OBSERVABLE_FIELDS

CONDITIONS = [
    {'name':'full','control':'full','mask_identity':False,'mask_date':False},
    {'name':'earlier_rounds','control':'earlier_rounds','mask_identity':False,'mask_date':False},
    {'name':'independent','control':'independent','mask_identity':False,'mask_date':False},
    {'name':'masked','control':'full','mask_identity':True,'mask_date':True},
]


def evaluate_baseline(rows, truths):
    observed = {r['meeting_date']:r for r in truths}
    aligned = [observed[r['meeting_date']] for r in rows]
    return MetricsEvaluator.evaluate_panel(
        [r['rate_bps'] for r in rows], [r['actual_rate_bps'] for r in aligned],
        [r['stance'] for r in rows], [r['actual_stance'] for r in aligned],
        [sorted(set(r['rate_dissenters'])|set(r['stance_dissenters'])) for r in rows],
        [sorted(set(r['rate_dissenters'])|set(r['stance_dissenters'])) for r in aligned],
        predicted_rate_dissenters=[r['rate_dissenters'] for r in rows],
        true_rate_dissenters=[r['rate_dissenters'] for r in aligned],
        predicted_stance_dissenters=[r['stance_dissenters'] for r in rows],
        true_stance_dissenters=[r['stance_dissenters'] for r in aligned]).model_dump()


async def main(output, finalize_existing=False):
    if output.exists() and not finalize_existing:
        raise ValueError('Use a new diagnostic output directory')
    code_before = code_identity()
    protocol = {'scope':'mock procedural diagnostic on exposed historical evidence',
                'provider':'mock','cache_enabled':False,'conditions':CONDITIONS,
                'n_replicates':2,'seed_base':20261008,'fragmentation_policy':'reject',
                'producer_code_hash':code_before,'experiment_id':'mock_fullpath_oct08_001',
                'selection_status':'fixed engineering controls; historical outcomes already exposed',
                'live_provider_calls_permitted':0}
    if finalize_existing:
        if strict_json(output/'protocol.json') != protocol:
            raise ValueError('Existing diagnostic protocol differs; no finalization permitted')
    else:
        write_immutable(output/'protocol.json', protocol)
    start = time.time()
    condition_rows, replay_summaries, condition_metrics = {}, {}, {}
    for condition in CONDITIONS:
        study = output/'evidence'/protocol['experiment_id']/condition['name']
        if finalize_existing:
            # Revalidate the completed saved evidence. No generation or checkpoint
            # resume occurs when repairing this diagnostic's summary-only failure.
            anchor = strict_json(output/'anchors'/f"{condition['name']}.json")['manifest_hash']
            replay_summaries[condition['name']] = replay_study(study, output/'replayed_finalized'/condition['name'],
                                                             expected_manifest_hash=anchor)
            condition_rows[condition['name']] = strict_json(study/'predictions.json')
            condition_metrics[condition['name']] = strict_json(study/'metrics_by_replicate.json')
            continue
        client = LLMClient(provider='mock', cache_enabled=False)
        orchestrator = DebateOrchestrator(client, TranscriptLogger(output_root=output/'bootstrap_logs'))
        runner = BacktestRunner(results_dir=output/'evidence', orchestrator=orchestrator,
            n_replicates=2, seed_base=protocol['seed_base'], experiment_id=protocol['experiment_id'],
            condition_id=condition['name'], control_mode=condition['control'],
            mask_identity=condition['mask_identity'], mask_date=condition['mask_date'],
            fragmentation_policy=protocol['fragmentation_policy'])
        frame = await runner.run_panel_backtest(subset='holdout', resume=False)
        anchor = content_hash(strict_json(study/'study_manifest.json'))
        write_immutable(output/'anchors'/f"{condition['name']}.json", {'manifest_hash':anchor})
        replay_summaries[condition['name']] = replay_study(study, output/'replayed'/condition['name'],
                                                         expected_manifest_hash=anchor)
        condition_rows[condition['name']] = frame.to_dict('records')
        condition_metrics[condition['name']] = strict_json(study/'metrics_by_replicate.json')
        print(f"Completed {condition['name']}: {len(frame)} meeting-replicate records; replay passed", flush=True)
    all_truth = strict_json(PROJECT_ROOT/'data/processed/vintage_v3/truth.json')
    calibration_truth = [r for r in all_truth if r['meeting_date']<='2023-04-06']
    frozen_baseline = fit_dissent_baseline(calibration_truth)
    snapshots = [s for s in load_snapshots(PROJECT_ROOT/'data/processed/vintage_v3/snapshots.json')
                 if s.meeting_date>'2023-04-06']
    baseline_rows = baseline_predictions(snapshots, all_truth, frozen_baseline)
    baseline_metrics = {}
    for name in sorted({r['baseline'] for r in baseline_rows}):
        rows = [r for r in baseline_rows if r['baseline']==name]
        baseline_metrics[name] = evaluate_baseline(rows, all_truth)
    write_immutable(output/'baseline_selection.json', frozen_baseline, replay=finalize_existing)
    write_immutable(output/'baseline_predictions.json', baseline_rows, replay=finalize_existing)
    full = pd.DataFrame(condition_rows['full'])
    dates = sorted(full['meeting_date'].unique())
    model_losses = [float((abs(full[full.meeting_date==day].sim_rate_bps-full[full.meeting_date==day].actual_rate_bps)).mean())
                    for day in dates]
    comparisons = {}
    truth_by_date = {r['meeting_date']:r for r in all_truth}
    for name in baseline_metrics:
        lookup = {r['meeting_date']:r for r in baseline_rows if r['baseline']==name}
        losses = [abs(lookup[day]['rate_bps']-truth_by_date[day]['actual_rate_bps']) for day in dates]
        comparisons[name] = paired_meeting_uncertainty(dates, model_losses, losses, n_resamples=2000)
    control_effects = {}
    for name in ('earlier_rounds','independent','masked'):
        treated = pd.DataFrame(condition_rows[name]).sort_values(['meeting_date','replicate_id'])
        original = full.sort_values(['meeting_date','replicate_id'])
        if list(zip(treated.meeting_date,treated.replicate_id)) != list(zip(original.meeting_date,original.replicate_id)):
            raise ValueError('Control joins differ')
        control_effects[name] = [{'meeting_date':a['meeting_date'],'replicate_id':a['replicate_id'],
            'rate_effect_bps':b['sim_rate_bps']-a['sim_rate_bps'],
            'stance_changed':b['sim_stance']!=a['sim_stance'],
            'rate_dissent_changed':set(b['sim_rate_dissenters'])!=set(a['sim_rate_dissenters']),
            'stance_dissent_changed':set(b['sim_stance_dissenters'])!=set(a['sim_stance_dissenters'])}
            for a,b in zip(original.to_dict('records'),treated.to_dict('records'))]
    source_missingness = {s.meeting_date:[name for name in OBSERVABLE_FIELDS if getattr(s,name) is None]
                         for s in snapshots}
    code_after = code_identity()
    if code_before != code_after:
        raise ValueError('Producer code changed during diagnostic')
    summary = {'scope':protocol['scope'],'n_meetings':len(dates),'n_replicates':2,
               'meeting_dates':dates,'observed_rate_class_counts':dict(Counter(truth_by_date[d]['actual_rate_bps'] for d in dates)),
               'condition_metrics':condition_metrics,'baseline_metrics':baseline_metrics,
               'paired_rate_mae_comparisons':comparisons,'control_effects':control_effects,
               'replay_summaries':replay_summaries,'source_missingness':source_missingness,
               'producer_code_unchanged':True,'producer_code_hash':code_before,
               'live_provider_calls':0,'empirical_superiority_established':False,
               'prospective_forecasting_validated':False,'elapsed_seconds':time.time()-start,
               'summary_finalized_from_existing_evidence':finalize_existing,
               'python':sys.version,'platform':platform.platform(),
               'qualification':'Mock behavior exercises complete paths. Saved replay is consistency verification. Neither validates live prediction, economic welfare or real-policy causal effects.'}
    write_immutable(output/'diagnostic_summary.json', summary)
    print(json.dumps({'output':str(output),'n_meetings':len(dates),'replay_summaries':replay_summaries,
                      'elapsed_seconds':summary['elapsed_seconds']},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--finalize-existing',action='store_true',help='Revalidate and summarize existing evidence without any generation')
    args = parser.parse_args()
    asyncio.run(main(args.output.resolve(),args.finalize_existing))
