"""Generate evidence-qualified tables after complete saved-study verification.

The numerical threshold field in legacy metrics is not a scientific verdict.
Mock observations, cache replays and live provider submissions remain distinct.
"""
from collections import Counter
from pathlib import Path
import tempfile

from src.backtest.backtest_runner import PROJECT_ROOT, BacktestRunner
import pandas as pd
from src.backtest.study_artifacts import strict_json, read_inputs
from src.infra.evidence import file_hash, write_immutable
from src.infra.exceptions import ArtifactIntegrityError
from src.schemas.macro_schema import MacroMeetingSnapshot, OBSERVABLE_FIELDS
from src.validation.baselines import fit_dissent_baseline, baseline_predictions
from src.validation.metrics import MetricsEvaluator, paired_meeting_uncertainty
from src.validation.study_replay import replay_study
from src.validation.observed_labels import evaluate_observed_dissent, paired_f1_completion_bounds
from src.data_pipeline.vintage_panel import verify_input_manifest


def require(condition, message):
    if not condition:
        raise ArtifactIntegrityError(message)


def baseline_metrics(rows, truth):
    observed = {r['meeting_date']:r for r in truth}
    require(len(observed)==len(truth), 'Duplicate baseline truth meeting')
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


def metric_text(value):
    return 'undefined' if value is None else f'{value:.3f}'


def build_study_report(studies, expected_manifest_hashes, output_dir, *,
                       baseline_truth_path=None, source_root=PROJECT_ROOT, observed_targets_path=None):
    """Verify every condition, derive findings, and only then publish a new report.

    Full historical truth is used solely for available-prior/calibration baselines;
    its file hash must match the study's separately anchored manifest. Preserve
    raw sources with the report so the derived baseline can be audited later.
    """
    output_dir, source_root = Path(output_dir), Path(source_root).resolve()
    baseline_truth_path = Path(baseline_truth_path or source_root/'data/processed/vintage_v3/truth.json')
    require(not output_dir.exists(), 'Report output must be an unused directory')
    require(studies and set(studies)==set(expected_manifest_hashes), 'Condition and anchor maps differ')
    manifests, inputs, predictions, metrics, replays = {}, {}, {}, {}, {}
    with tempfile.TemporaryDirectory(prefix='rbi-report-verify-') as scratch:
        for name,path in sorted(studies.items()):
            path = Path(path)
            require(path.name==name, 'Condition key differs from evidence directory')
            replays[name] = replay_study(path, Path(scratch)/name,
                                       expected_manifest_hash=expected_manifest_hashes[name])
            manifests[name] = strict_json(path/'study_manifest.json')
            inputs[name] = read_inputs(path/'inputs',manifests[name]['frozen_inputs_hashes'])
            predictions[name] = strict_json(Path(scratch)/name/'predictions.json')
            metrics[name] = strict_json(Path(scratch)/name/'metrics_by_replicate.json')
        first = sorted(studies)[0]
        reference = manifests[first]
        matched_fields = ('code_hash','config_hash','data_hash','truth_hash','persona_hash',
                          'n_replicates','seed_base','provider','model','temperature','meetings','generation_settings')
        for manifest in manifests.values():
            require(all(manifest[field]==reference[field] for field in matched_fields),
                    'Conditions lack matched code, scientific inputs, settings or seed schedule')
        require(file_hash(baseline_truth_path)==reference['truth_hash'], 'Full baseline truth differs from anchored study truth')
        full_truth = strict_json(baseline_truth_path)
        require(full_truth and len({r['meeting_date'] for r in full_truth})==len(full_truth), 'Missing or duplicate full baseline truth')
        raw_sources = {}
        for row in full_truth:
            path = (source_root/row['source_file']).resolve()
            require(path.is_relative_to(source_root) and path.is_file(), 'Missing or outside-root baseline source')
            require(file_hash(path)==row['source_sha256'], 'Baseline source bytes differ from truth provenance')
            raw_sources[row['source_file']] = {'sha256':row['source_sha256'],
                                              'bytes_hex':path.read_bytes().hex()}
        by_date = {r['meeting_date']:r for r in full_truth}
        require(inputs[first]['truth.json']==[by_date[day] for day in reference['meetings']],
                'Evaluation truth differs from baseline source corpus')
        # New scientific scores use explicit observation status. Old positive-list
        # truth remains unchanged for archival replay, but its omissions cannot be
        # treated as newly authenticated negative formal votes.
        label_catalog = verify_input_manifest(source_root)
        target_path = Path(observed_targets_path or source_root/'research/source_ledgers/historical_labels_round002/observed_targets.json')
        target_relative = str(target_path.resolve().relative_to(source_root))
        require(label_catalog['files'].get(target_relative)==file_hash(target_path),
                'Observed-label input differs from its scientific source manifest')
        observed_targets = strict_json(target_path)
        selected_targets = {}
        for channel, rows in observed_targets['channels'].items():
            if channel not in ('literal_rate_no','exact_rate_disagreement','formal_stance_dissent'):
                continue
            lookup = {r['meeting_date']:r for r in rows}
            require(len(lookup)==len(rows) and set(reference['meetings']).issubset(lookup),
                    'Observed targets lack unique selected meetings')
            selected_targets[channel] = [lookup[day] for day in reference['meetings']]
        require(set(selected_targets)=={'literal_rate_no','exact_rate_disagreement','formal_stance_dissent'},
                'Observed target channels are incomplete')
        observed_scores = {}
        for condition, rows in predictions.items():
            observed_scores[condition] = {}
            for replicate in range(1,reference['n_replicates']+1):
                selected = [r for r in rows if r['replicate_id']==replicate]
                observed_scores[condition][str(replicate)] = {
                    channel:evaluate_observed_dissent(
                        [{'meeting_date':r['meeting_date'],'predicted_dissenters':r[field]} for r in selected],
                        selected_targets[channel])
                    for channel,field in [('exact_rate_disagreement','sim_rate_dissenters'),
                                          ('formal_stance_dissent','sim_stance_dissenters')]}
        selection = fit_dissent_baseline([r for r in full_truth if r['meeting_date']<='2023-04-06'])
        snapshots = [MacroMeetingSnapshot.model_validate(s) for s in inputs[first]['snapshots.json']]
        base_rows = baseline_predictions(snapshots,full_truth,selection)
        base_metrics = {name:baseline_metrics([r for r in base_rows if r['baseline']==name],full_truth)
                        for name in sorted({r['baseline'] for r in base_rows})}
        baseline_observed_scores = {
            name:{channel:evaluate_observed_dissent(
                [{'meeting_date':r['meeting_date'],'predicted_dissenters':r[field]}
                 for r in base_rows if r['baseline']==name],selected_targets[channel])
                for channel,field in [('exact_rate_disagreement','rate_dissenters'),
                                      ('formal_stance_dissent','stance_dissenters')]}
            for name in base_metrics}
        paired_observed_bounds = {}
        for condition,rows in predictions.items():
            paired_observed_bounds[condition] = {}
            for replicate in range(1,reference['n_replicates']+1):
                selected = [r for r in rows if r['replicate_id']==replicate]
                paired_observed_bounds[condition][str(replicate)] = {
                    name:{channel:paired_f1_completion_bounds(
                        [{'meeting_date':r['meeting_date'],'predicted_dissenters':r[field]} for r in selected],
                        [{'meeting_date':r['meeting_date'],'predicted_dissenters':r[base_field]}
                         for r in base_rows if r['baseline']==name],selected_targets[channel])
                        for channel,field,base_field in [
                            ('exact_rate_disagreement','sim_rate_dissenters','rate_dissenters'),
                            ('formal_stance_dissent','sim_stance_dissenters','stance_dissenters')]}
                    for name in base_metrics}
        dates = reference['meetings']
        pairs = {}
        tables = []
        for condition in sorted(predictions):
            rows = predictions[condition]
            losses = [sum(abs(r['sim_rate_bps']-r['actual_rate_bps']) for r in rows if r['meeting_date']==day)
                      /reference['n_replicates'] for day in dates]
            pairs[condition] = {}
            for baseline in base_metrics:
                lookup = {r['meeting_date']:r for r in base_rows if r['baseline']==baseline}
                base_losses = [abs(lookup[day]['rate_bps']-by_date[day]['actual_rate_bps']) for day in dates]
                pairs[condition][baseline] = paired_meeting_uncertainty(dates,losses,base_losses,n_resamples=2000)
            for replicate,result in metrics[condition].items():
                current = BacktestRunner.compute_aggregate_metrics(
                    pd.DataFrame([r for r in rows if r['replicate_id']==int(replicate)]),
                    validation_config=inputs[condition]['config.json']['validation'])
                tables.append({'condition':condition,'replicate':int(replicate),
                               'producer_threshold_contract':manifests[condition].get('metric_threshold_contract','union_v1'),
                               'current_channel_threshold_met':current['passed_validation_gate'],
                               'rate_confusion':[{'actual':a,'predicted':p,'count':count}
                                    for (a,p),count in sorted(Counter((r['actual_rate_bps'],r['sim_rate_bps'])
                                        for r in rows if r['replicate_id']==int(replicate)).items())],
                               'metrics':result})
        counts = dict(sum((Counter(r['generation_evidence_counts']) for r in replays.values()),Counter()))
        scope = ('Mock procedural diagnostic' if set(counts)=={'mock'} else
                 'Saved evidence containing cache replay' if 'cache_replay' in counts else
                 'Saved provider-attributed study' if set(counts)=={'live_model'} else
                 'Saved study with mixed evidence types')
        summary = {'report_version':1,'evidence_scope':scope,'study_anchors':expected_manifest_hashes,
                   'producer_code_hash':reference['code_hash'],'n_meetings':len(dates),'n_replicates':reference['n_replicates'],
                   'generation_evidence_counts':counts,'replay_provider_calls':0,
                   'observed_rate_class_counts':dict(Counter(by_date[day]['actual_rate_bps'] for day in dates)),
                   'condition_tables':tables,'baseline_metrics':base_metrics,'paired_rate_mae_comparisons':pairs,
                   'current_threshold_contract':'channel_v2; distinct size/rate/stance endpoints, descriptive only',
                   'observability_aware_dissent':observed_scores,
                   'baseline_observability_aware_dissent':baseline_observed_scores,
                   'paired_dissent_f1_logical_bounds':paired_observed_bounds,
                   'observed_targets_sha256':file_hash(target_path),
                   'source_missingness':{s.meeting_date:[name for name in OBSERVABLE_FIELDS if getattr(s,name) is None] for s in snapshots},
                   'baseline_selection':selection,'full_baseline_truth_sha256':file_hash(baseline_truth_path),
                   'baseline_source_count':len(raw_sources),'independent_live_replication':False,
                   'scientific_readiness':'Not established by saved-evidence verification or numerical threshold checks',
                   'statistical_scope':'Exploratory meeting-level rate-loss comparisons on exposed history; temporal block size 2; replicate means are not extra independent meetings',
                   'provenance_limit':'Hashes verify retained consistency, not official source signatures, authenticated provider invoices, or absence of model pretraining contamination'}
        lines = ['# Current study evidence and diagnostic results','',
                 f"{scope}: {len(dates)} meetings, {reference['n_replicates']} planned replicates and {len(studies)} conditions. "
                 f"Complete saved evidence was revalidated before deriving these tables; replay made zero provider calls. "
                 'A numerical threshold flag does not certify forecasting skill, persuasion, equilibrium or welfare.','',
                 '## Outcomes','',
                 '| Condition | Replicate | Exact rate percent | Direction percent | MAE bps | Stance percent | Rate dissent F1 | Stance dissent F1 | Union F1 |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for row in tables:
            m = row['metrics']
            lines.append(f"| {row['condition']} | {row['replicate']} | {m['exact_rate_accuracy_pct']:.1f} | {m['directional_rate_accuracy_pct']:.1f} | {m['rate_mae_bps']:.3f} | {m['stance_accuracy_pct']:.1f} | {metric_text(m['rate_dissent_f1'])} | {metric_text(m['stance_dissent_f1'])} | {metric_text(m['dissent_f1'])} |")
        lines += ['','## Available-information baselines','',
                  '| Baseline | Exact rate percent | MAE bps | Union dissent F1 |','|---|---:|---:|---:|']
        for name,m in base_metrics.items():
            lines.append(f"| {name} | {m['exact_rate_accuracy_pct']:.1f} | {m['rate_mae_bps']:.3f} | {metric_text(m['dissent_f1'])} |")
        lines += ['','## Paired rate-loss comparisons','',
                  'Positive advantage means lower model MAE. Intervals use meeting clusters and a circular temporal-block bootstrap. These are exploratory diagnostics on exposed history.','',
                  '| Condition | Baseline | Mean advantage bps | 95 percent interval | Positive interval lower bound |','|---|---|---:|---|---|']
        for condition,comparisons in pairs.items():
            for name,comparison in comparisons.items():
                lines.append(f"| {condition} | {name} | {comparison['mean_advantage']:.3f} | {comparison['ci95']} | {comparison['superiority_supported']} |")
        lines += ['','## Dissent with explicitly observed member targets','',
                  'Observed-case F1 uses only documented targets. Bounds range over all assignments to missing targets with positive truth; they are logical identification bounds, not sampling confidence intervals. An unobserved positive class remains undefined.',
                  '', '| Condition or baseline | Replicate | Channel | Observed / total cells | Observed-case F1 | F1 completion bounds | Complete meetings |',
                  '|---|---:|---|---:|---:|---|---:|']
        for condition,replicates in observed_scores.items():
            for replicate,channels in replicates.items():
                for channel,result in channels.items():
                    lines.append(f"| {condition} | {replicate} | {channel} | {result['observed_targets']} / {result['n_member_targets']} | {metric_text(result['observed_case']['f1'])} | {result['completion_bounds']['f1_given_positive_truth']} | {len(result['complete_meetings'])} |")
        for name,channels in baseline_observed_scores.items():
            for channel,result in channels.items():
                lines.append(f"| {name} | — | {channel} | {result['observed_targets']} / {result['n_member_targets']} | {metric_text(result['observed_case']['f1'])} | {result['completion_bounds']['f1_given_positive_truth']} | {len(result['complete_meetings'])} |")
        lines += ['','## Interpretation and remaining evidence','',
                  f"Observed rate class counts are {summary['observed_rate_class_counts']}. Generation evidence counts are {counts}.",
                  'Original saved threshold flags retain their producer contract. Current channel thresholds are recomputed separately in summary.json; neither contract establishes empirical superiority or scientific readiness.',
                  'Archival positive-list scores above preserve producer semantics. New formal-vote scoring excludes unobserved member targets and reports complete cases and sharp missing-label bounds in summary.json; these bounds are not confidence intervals.',
                  'Paired F1 differences in summary.json use the same missing-label completion for model and baseline. They show whether a ranking is robust to missing targets; no probability or statistical significance is assigned to those completions.',
                  'All null, negative and unchanged effects must remain in the saved records. The comparison tables cannot establish live-model superiority when their generations are mock or replayed.',
                  'The complete input missingness is recorded in summary.json. An unavailable output gap leaves the full intended comparator unresolved.',
                  'Independent live generation, a frozen broader-regime evaluation, comparable controls, model-contamination assessment and appropriate external-validity evidence require separate scientific work.',
                  'Voting majority and casting rules are governed by RBI Act Section 45ZI. Full-roster attendance and declared fragmentation resolution are simulator choices; Section 45ZL concerns minutes publication.',
                  'This report does not supply a peer-review verdict.','']
        report = '\n'.join(lines)
        # No output is published until every condition, baseline and computation
        # succeeds. Reproduction inputs accompany the derived report.
        write_immutable(output_dir/'summary.json',summary)
        write_immutable(output_dir/'baseline_full_truth.json',full_truth)
        write_immutable(output_dir/'baseline_truth_source.json',{
            'sha256':file_hash(baseline_truth_path),'bytes_hex':baseline_truth_path.read_bytes().hex()})
        write_immutable(output_dir/'baseline_raw_sources.json',raw_sources)
        write_immutable(output_dir/'baseline_predictions.json',base_rows)
        write_immutable(output_dir/'observed_target_inputs.json',selected_targets)
        (output_dir/'RESULTS_REPORT.md').write_text(report)
        return summary
