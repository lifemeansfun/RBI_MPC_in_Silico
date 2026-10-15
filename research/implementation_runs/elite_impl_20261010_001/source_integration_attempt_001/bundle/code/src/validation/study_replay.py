"""Reconstruct tables from complete saved evidence without any model generation.

Hashes are consistency checks, not source signatures. Replaying an experiment is
not an independent replication of its provider calls or empirical performance.
"""
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import base64
import json
import tempfile

import pandas as pd

from src.backtest.backtest_runner import BacktestRunner
from src.backtest.study_artifacts import strict_json, read_inputs, verify_observation_bundle
from src.behavioral.debate_orchestrator import planned_seed
from src.infra.checkpoint import CheckpointStore
from src.infra.evidence import content_hash, file_hash, safe_component, write_immutable
from src.infra.exceptions import ArtifactIntegrityError
from src.infra.transcript_logger import read_transcript
from src.persona_engine.provenance import verify_personas
from src.rule_engine.engine import InstitutionalRuleEngine
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.schemas.debate_schema import (InitialStanceOutput, DeliberationOutput,
                                      FinalVoteOutput, MeetingCommitteeDecision)

ROUND_SCHEMAS = {1: InitialStanceOutput, 2: DeliberationOutput, 3: DeliberationOutput, 4: FinalVoteOutput}
ENVELOPE = {'artifact_identity', 'artifact_content_hash', 'generation', 'prompt'}


def require(condition, message):
    if not condition:
        raise ArtifactIntegrityError(message)


@contextmanager
def portable_sources(sources):
    with tempfile.TemporaryDirectory(prefix='rbi-replay-sources-') as directory:
        root = Path(directory)
        for name, record in sources.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(record['bytes'], validate=True))
        yield root


def replay_study(study_dir, output_dir, *, expected_manifest_hash):
    """Require a separately retained manifest anchor; output must be a fresh directory."""
    study_dir, output_dir = Path(study_dir).resolve(), Path(output_dir).resolve()
    require(not output_dir.exists(), 'Replay output must be an unused directory')
    manifest = strict_json(study_dir / 'study_manifest.json')
    require(content_hash(manifest) == expected_manifest_hash, 'Study manifest differs from supplied anchor')
    version = manifest.get('study_manifest_version')
    require(type(version) is int and version in (2,3), 'Unsupported or incomplete study manifest')
    threshold_contract = 'union_v1' if version == 2 else manifest.get('metric_threshold_contract')
    require(threshold_contract == ('union_v1' if version == 2 else 'channel_v2'),
            'Study metric threshold contract is unsupported')
    experiment, condition = study_dir.parent.name, study_dir.name
    safe_component(experiment); safe_component(condition)
    require(condition == manifest['condition'], 'Condition directory differs from manifest')
    inputs = read_inputs(study_dir / 'inputs', manifest['frozen_inputs_hashes'])
    snapshots = [MacroMeetingSnapshot.model_validate(row) for row in inputs['snapshots.json']]
    dates = [s.meeting_date for s in snapshots]
    require(dates and dates == sorted(set(dates)) and dates == manifest['meetings'], 'Invalid chronological snapshot join')
    truths = inputs['truth.json']
    require([t['meeting_date'] for t in truths] == dates, 'Truth and snapshot joins differ')
    truth_by_date = {t['meeting_date']: t for t in truths}
    persona_map = {m: MemberPersona.model_validate(p) for m, p in inputs['personas.json'].items()}
    require(all(m == p.member_id for m, p in persona_map.items()), 'Frozen persona mapping impersonates members')
    roster = manifest['roster_by_meeting']
    require(set(roster) == set(dates), 'Incomplete dated roster')
    with portable_sources(inputs['raw_sources.json']) as sources:
        for snapshot in snapshots:
            require(len(roster[snapshot.meeting_date]) == 6 and len(set(roster[snapshot.meeting_date])) == 6,
                    'Each simulator roster requires six distinct members')
            verify_observation_bundle(snapshot, inputs['raw_sources.json'])
            if manifest['source_validation_required']:
                snapshot.verify_sources(sources)
                verify_personas([persona_map[m] for m in roster[snapshot.meeting_date]],
                                snapshot.information_cutoff, source_root=sources)
                truth = truth_by_date[snapshot.meeting_date]
                require(truth['source_file'] in inputs['raw_sources.json'] and
                        inputs['raw_sources.json'][truth['source_file']]['sha256'] == truth['source_sha256'],
                        'Historical truth lacks its retained source bytes')
    nrep = manifest['n_replicates']
    require(type(nrep) is int and nrep > 0, 'Invalid planned replicate count')
    pairs = {(day, rep) for day in dates for rep in range(1, nrep + 1)}
    settings = manifest['generation_settings']
    interventions = {'control_mode':manifest['control'], 'mask_identity':manifest['mask_identity'],
                     'mask_date':manifest['mask_date'], 'fragmentation_policy':manifest['fragmentation_policy']}
    checkpoints = {}
    checkpoint_store = CheckpointStore(study_dir.parents[1])
    for path in sorted((study_dir / 'checkpoints').glob('*.json')):
        preliminary = strict_json(path)
        identity = preliminary['identity']
        pair = identity['meeting_date'], identity['replicate_id']
        require(pair in pairs and pair not in checkpoints, 'Duplicate, stale or unexpected checkpoint')
        day, rep = pair
        snapshot = snapshots[dates.index(day)]
        members = [persona_map[m] for m in roster[day]]
        expected = {'experiment_id':experiment, 'condition_id':condition, 'meeting_date':day, 'replicate_id':rep,
            'code_hash':manifest['code_hash'], 'config_hash':content_hash(inputs['config.json']),
            'data_hash':content_hash(snapshot.model_dump(mode='json')), 'persona_hash':content_hash([p.model_dump() for p in members]),
            'intervention_hash':content_hash(interventions), 'seed_schedule_version':'paired-member-round-v1',
            'seed_base':manifest['seed_base'], 'requested_model':manifest['model'], 'provider':manifest['provider'],
            'temperature':manifest['temperature'], 'model_epoch':inputs['config.json']['run']['model_epoch'],
            'max_output_tokens':inputs['config.json']['run']['max_output_tokens'], 'truth_hash':manifest['truth_hash'],
            'generation_settings_hash':content_hash(settings), 'snapshot_hash':content_hash(snapshot.model_dump(mode='json')),
            'study_manifest_hash':expected_manifest_hash}
        require(identity == expected, 'Checkpoint scientific identity differs from frozen inputs')
        require(path == checkpoint_store.path_for(expected), 'Checkpoint filename does not encode its identity')
        saved = checkpoint_store.load(expected)
        require(saved is not None, 'Missing expected checkpoint')
        checkpoints[pair] = saved
    require(set(checkpoints) == pairs, 'Incomplete meeting or replicate evidence')
    records, evidence_counts, cost = [], Counter(), 0.0
    for day in dates:
        snapshot = snapshots[dates.index(day)]
        member_ids = roster[day]
        for rep in range(1, nrep + 1):
            saved = checkpoints[day, rep]
            identity = saved['identity']
            rounds = [1, 4] if manifest['control'] == 'independent' else [1, 2, 3, 4]
            required = {f'round_{r}_{m}.json' for r in rounds for m in member_ids} | {'meeting_outcome.json'}
            require(set(saved['artifacts']) == required, 'Missing, extra or mismatched round artifacts')
            outputs, local_types, seeds = {}, set(), {}
            for r in rounds:
                for member in member_ids:
                    key = f'round_{r}_{member}.json'
                    artifact = saved['artifacts'][key]
                    document = read_transcript(checkpoint_store.output_root / artifact['path'],
                                               {**identity, 'round_number':r, 'member_id':member})
                    generation = document['generation']
                    parsed = ROUND_SCHEMAS[r].model_validate(generation['parsed']).model_dump(mode='json')
                    aliases = document['prompt'].get('identity_aliases', {})
                    if manifest['mask_identity']:
                        require(parsed['member_id'] == aliases.get(member), 'Masked member alias differs from plan')
                        parsed['member_id'] = member
                        if 'member_name' in parsed:
                            require(parsed['member_name'] == aliases.get(persona_map[member].name), 'Masked name alias differs')
                            parsed['member_name'] = persona_map[member].name
                    payload = {k:v for k,v in document.items() if k not in ENVELOPE}
                    require(payload == parsed, 'Transcript payload differs from validated raw/alias output')
                    require(payload['member_id'] == member, 'Round member differs from planned roster')
                    metadata = generation['metadata']
                    seed = planned_seed(manifest['seed_base'], day, rep, member, r)
                    require(metadata['seed'] == seed, 'Generation seed schedule differs from frozen plan')
                    require(metadata['schema_hash'] == settings['round_schema_hashes'][str(r)], 'Recorded schema differs from frozen condition')
                    for frozen, recorded in [('provider','provider'), ('model','requested_model'), ('temperature','temperature'),
                                            ('model_epoch','model_epoch'), ('max_output_tokens','max_output_tokens'),
                                            ('parser_version','parser_version')]:
                        require(settings[frozen] == metadata[recorded], 'Generation settings differ from frozen condition')
                    require(generation['request_identity']['generation_settings_hash'] == content_hash(settings), 'Generation settings hash differs')
                    local_types.add(metadata['evidence_type'])
                    evidence_counts[metadata['evidence_type']] += 1
                    cost += metadata['estimated_cost_usd']
                    seeds[f'{member}:round_{r}'] = seed
                    outputs[r, member] = ROUND_SCHEMAS[r].model_validate(payload)
            outcome_artifact = saved['artifacts']['meeting_outcome.json']
            document = read_transcript(checkpoint_store.output_root / outcome_artifact['path'], identity)
            outcome = MeetingCommitteeDecision.model_validate({k:v for k,v in document.items() if k not in ENVELOPE})
            require(outcome.snapshot_hash == identity['snapshot_hash'] and outcome.persona_hash == identity['persona_hash'],
                    'Outcome inputs differ from checkpoint')
            require(outcome.generation_settings == settings and outcome.governor_id == manifest['governor_id'],
                    'Outcome model settings or Governor differ')
            require(outcome.seed_schedule == seeds and outcome.generation_count == len(seeds) and
                    outcome.evidence_types == sorted(local_types) and outcome.fallbacks_count == 0,
                    'Outcome evidence count/type/seed or fallback mismatch')
            votes = {m:outputs[4,m] for m in member_ids}
            rate = InstitutionalRuleEngine.aggregate_rate_votes({m:v.final_rate_vote_bps for m,v in votes.items()},
                      manifest['governor_id'], fragmentation_policy=manifest['fragmentation_policy'], prior_action=0)
            stance = InstitutionalRuleEngine.aggregate_stance_votes({m:v.final_stance_vote for m,v in votes.items()},
                      manifest['governor_id'], fragmentation_policy=manifest['fragmentation_policy'], prior_action=snapshot.prev_stance)
            require((outcome.rate_decision_bps, outcome.stance_decision) == (rate.winning_action, stance.winning_action),
                    'Saved decision contradicts reaggregated ballots')
            for vote in outcome.member_votes:
                expected_vote = votes[vote.member_id].model_dump()
                expected_vote.update(dissenting_on_rate=vote.member_id in rate.dissenting_members,
                                     dissenting_on_stance=vote.member_id in stance.dissenting_members)
                require(vote.model_dump() == expected_vote, 'Outcome ballot differs from its generation artifact')
            require(set(v.member_id for v in outcome.member_votes) == set(member_ids), 'Missing outcome ballots')
            record = saved['payload']
            require(record['identity'] == identity and record['meeting_date'] == day and record['replicate_id'] == rep and
                    record['condition_id'] == condition and record['sim_rate_bps'] == rate.winning_action and
                    record['sim_stance'] == stance.winning_action and
                    set(record['sim_rate_dissenters']) == set(rate.dissenting_members) and
                    set(record['sim_stance_dissenters']) == set(stance.dissenting_members) and
                    record['evidence_types'] == sorted(local_types) and record['fallbacks_used'] == 0,
                    'Checkpoint prediction contradicts reaggregated evidence')
            truth = truth_by_date[day]
            records.append({**record, 'actual_rate_bps':truth['actual_rate_bps'], 'actual_stance':truth['actual_stance'],
                            'actual_rate_dissenters':truth['rate_dissenters'], 'actual_stance_dissenters':truth['stance_dissenters']})
    require(strict_json(study_dir/'predictions.json') == records, 'Saved predictions differ from rebuilt evidence')
    metrics = {str(rep):BacktestRunner.compute_aggregate_metrics(pd.DataFrame([r for r in records if r['replicate_id']==rep]),
                threshold_contract=threshold_contract,
                validation_config=inputs['config.json']['validation'] if version==3 else None)
               for rep in range(1, nrep+1)}
    require(strict_json(study_dir/'metrics_by_replicate.json') == metrics, 'Saved metrics differ from rebuilt evidence')
    summary = {'replay_version':1, 'study_manifest_hash':expected_manifest_hash, 'producer_code_hash':manifest['code_hash'],
               'evidence_scope':manifest['evidence_scope'], 'n_meetings':len(dates), 'n_replicates':nrep,
               'generation_evidence_counts':dict(evidence_counts), 'recorded_estimated_cost_usd':cost,
               'replay_provider_calls':0, 'independent_live_replication':False,
               'metric_threshold_contract':threshold_contract,
               'qualification':'Recomputed saved evidence; neither provider invoices nor uncontaminated forecasting are authenticated'}
    # Only publish after all integrity and semantic checks succeed.
    write_immutable(output_dir/'predictions.json', records)
    write_immutable(output_dir/'metrics_by_replicate.json', metrics)
    write_immutable(output_dir/'replay_summary.json', summary)
    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--expected-manifest-hash', required=True)
    args = parser.parse_args()
    print(json.dumps(replay_study(args.study_dir, args.output_dir,
                                 expected_manifest_hash=args.expected_manifest_hash), indent=2))
