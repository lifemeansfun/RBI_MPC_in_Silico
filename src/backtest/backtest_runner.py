"""Immutable source-aware historical backtests; exposed panels stay retrospective."""
import asyncio
import json
from pathlib import Path
import pandas as pd
import yaml
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.validation.metrics import MetricsEvaluator
from src.infra.config_loader import load_config
from src.infra.checkpoint import CheckpointStore
from src.infra.evidence import content_hash, file_hash, write_immutable
from src.infra.evidence import safe_component
from src.infra.transcript_logger import TranscriptLogger
from src.infra.exceptions import GenerationProvenanceError
from src.persona_engine.provenance import verify_personas
from src.backtest.study_artifacts import prepare_inputs, persist_inputs

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRE_MAY_2022_ED = 'mridul_saggar'
POST_MAY_2022_ED = 'rajiv_ranjan'


def code_identity(root=PROJECT_ROOT):
    return content_hash({str(p.relative_to(root)): file_hash(p) for p in sorted((root/'src').rglob('*.py'))})


def load_snapshots(path):
    path = Path(path)
    if path.suffix != '.json':
        raise GenerationProvenanceError('Corrected research reads typed snapshots.json; legacy Parquet requires an explicitly labeled diagnostic')
    rows = json.loads(path.read_text())
    snapshots = [MacroMeetingSnapshot.model_validate(row) for row in rows]
    if not snapshots or len({s.meeting_date for s in snapshots}) != len(snapshots):
        raise ValueError('Missing or duplicate macro meeting')
    if [s.meeting_date for s in snapshots] != sorted(s.meeting_date for s in snapshots):
        raise ValueError('Macro meetings must be chronological')
    return snapshots


class BacktestRunner:
    def __init__(self, macro_panel_path=None, personas_dir=None, results_dir=None, orchestrator=None,
                 *, truth_path=None, experiment_id=None, condition_id='full', n_replicates=None,
                 seed_base=None, research_mode=True, control_mode='full', mask_identity=False,
                 mask_date=False, fragmentation_policy='reject'):
        self.macro_panel_path = Path(macro_panel_path or PROJECT_ROOT/'data/processed/vintage_v3/snapshots.json').resolve()
        self.truth_path = Path(truth_path or self.macro_panel_path.with_name('truth.json')).resolve()
        self.personas_dir = Path(personas_dir or PROJECT_ROOT/'personas/calibration_2023-04-30_v2').resolve()
        self.results_dir = Path(results_dir or PROJECT_ROOT/'results/corrected_studies').resolve()
        self.config = load_config()
        self.n_replicates = n_replicates if n_replicates is not None else self.config.run.n_replicates
        if type(self.n_replicates) is not int or self.n_replicates < 1:
            raise ValueError('Positive integer replicates required')
        self.seed_base = seed_base if seed_base is not None else self.config.run.seed_base
        self.research_mode = research_mode
        self.condition_id, self.control_mode = condition_id, control_mode
        self.mask_identity, self.mask_date, self.fragmentation_policy = mask_identity, mask_date, fragmentation_policy
        self.orchestrator = orchestrator or DebateOrchestrator()
        self.experiment_id = experiment_id
        self.checkpoints = CheckpointStore(self.results_dir)

    def load_panel(self):
        return pd.DataFrame([s.model_dump(mode='json') for s in load_snapshots(self.macro_panel_path)])

    def load_roster_for_date(self, meeting_date_str):
        ed_id = PRE_MAY_2022_ED if meeting_date_str < '2022-05-01' else POST_MAY_2022_ED
        ids = ['shaktikanta_das','michael_patra',ed_id,'shashanka_bhide','ashima_goyal','jayanth_varma']
        personas = [MemberPersona.model_validate(yaml.safe_load((self.personas_dir/f'{m}.yaml').read_text())) for m in ids]
        if self.research_mode:
            if not hasattr(self, '_snapshot_by_date'):
                self._snapshot_by_date = {s.meeting_date:s for s in load_snapshots(self.macro_panel_path)}
            verify_personas(personas, self._snapshot_by_date[meeting_date_str].information_cutoff,
                            source_root=PROJECT_ROOT, corpus_manifest_path=self.personas_dir/'corpus_manifest.json')
        return personas

    def _identity(self, snapshot, personas, replicate_id, model, temperature):
        if not isinstance(self.experiment_id, str) or not self.experiment_id:
            raise GenerationProvenanceError('Freeze an explicit experiment identity before direct meeting generation')
        safe_component(self.experiment_id)
        safe_component(self.condition_id)
        if type(replicate_id) is not int or replicate_id < 1 or type(self.seed_base) is not int:
            raise GenerationProvenanceError('Invalid experiment replicate or seed')
        if hasattr(self, '_study_manifest') and code_identity() != self._study_manifest['code_hash']:
            raise GenerationProvenanceError('Code changed after study freeze; no further generation is permitted')
        if hasattr(self, '_study_manifest'):
            frozen = self._study_manifest
            current_persona_hash = content_hash({p.name:file_hash(p) for p in sorted(self.personas_dir.glob('*.yaml'))})
            unchanged = (content_hash(self.config.model_dump()) == frozen['config_hash']
                and file_hash(self.macro_panel_path) == frozen['data_hash']
                and file_hash(self.truth_path) == frozen['truth_hash']
                and current_persona_hash == frozen['persona_hash']
                and self.seed_base == frozen['seed_base'] and self.n_replicates == frozen['n_replicates']
                and replicate_id <= frozen['n_replicates']
                and self.experiment_id == self._frozen_experiment_id
                and self.condition_id == frozen['condition'] and self.control_mode == frozen['control']
                and self.mask_identity == frozen['mask_identity'] and self.mask_date == frozen['mask_date']
                and self.fragmentation_policy == frozen['fragmentation_policy']
                and self.orchestrator.client.provider == frozen['provider']
                and (model or self.config.run.dev_model) == frozen['model']
                and (temperature if temperature is not None else self.config.run.temperature) == frozen['temperature']
                and self.orchestrator.generation_settings(model=model,temperature=temperature) == frozen['generation_settings'])
            frozen_snapshots = {s['meeting_date']:s for s in self._frozen_inputs['snapshots.json']}
            unchanged = unchanged and snapshot.model_dump(mode='json') == frozen_snapshots.get(snapshot.meeting_date)
            expected_roster = frozen['roster_by_meeting'].get(snapshot.meeting_date)
            unchanged = unchanged and [p.member_id for p in personas] == expected_roster
            if expected_roster is not None:
                unchanged = unchanged and [p.model_dump() for p in personas] == [
                    MemberPersona.model_validate(self._frozen_inputs['personas.json'][m]).model_dump() for m in expected_roster]
            if not unchanged:
                raise GenerationProvenanceError('Scientific inputs, roster, conditions or generation settings changed after study freeze; no further generation is permitted')
        intervention = {'control_mode':self.control_mode, 'mask_identity':self.mask_identity,
                        'mask_date':self.mask_date,'fragmentation_policy':self.fragmentation_policy}
        identity = {'experiment_id':self.experiment_id, 'condition_id':self.condition_id,
                    'meeting_date':snapshot.meeting_date,'replicate_id':replicate_id,
                    'code_hash':code_identity(), 'config_hash':content_hash(self.config.model_dump()),
                    'data_hash':content_hash(snapshot.model_dump(mode='json')),
                    'persona_hash':content_hash([p.model_dump() for p in personas]),
                    'intervention_hash':content_hash(intervention),'seed_schedule_version':'paired-member-round-v1',
                    'seed_base':self.seed_base,'requested_model':model or self.config.run.dev_model,
                    'provider':self.orchestrator.client.provider,'temperature':temperature if temperature is not None else self.config.run.temperature,
                    'model_epoch':self.config.run.model_epoch,'max_output_tokens':self.config.run.max_output_tokens,
                    'truth_hash':file_hash(self.truth_path)}
        settings = self.orchestrator.generation_settings(model=model, temperature=temperature)
        identity.update(generation_settings_hash=content_hash(settings), snapshot_hash=identity['data_hash'])
        if hasattr(self, '_study_manifest'):
            identity['study_manifest_hash'] = content_hash(self._study_manifest)
        return identity

    async def run_meeting_backtest(self, row, model=None, temperature=None, *, replicate_id=1):
        snapshot = row if isinstance(row, MacroMeetingSnapshot) else MacroMeetingSnapshot.model_validate(row)
        personas = self.load_roster_for_date(snapshot.meeting_date)
        identity = self._identity(snapshot, personas, replicate_id, model, temperature)
        logger = TranscriptLogger(run_id=f'meeting_{snapshot.meeting_date}_rep_{replicate_id}', output_root=self.results_dir,
                                  condition_id=self.condition_id, identity=identity)
        self.orchestrator.logger = logger
        decision = await self.orchestrator.run_meeting(snapshot=snapshot, personas=personas,
            governor_id='shaktikanta_das', replicate_id=replicate_id, model=model, temperature=temperature,
            experiment_id=self.experiment_id, condition_id=self.condition_id, seed=self.seed_base,
            control_mode=self.control_mode, mask_identity=self.mask_identity, mask_date=self.mask_date,
            fragmentation_policy=self.fragmentation_policy)
        record = {'meeting_date':snapshot.meeting_date,'replicate_id':replicate_id,
                  'condition_id':self.condition_id,'sim_rate_bps':decision.rate_decision_bps,
                  'sim_stance':decision.stance_decision,'sim_rate_dissenters':decision.dissenting_members_rate,
                  'sim_stance_dissenters':decision.dissenting_members_stance,
                  'evidence_types':decision.evidence_types,'fallbacks_used':decision.fallbacks_count,
                  'panel_subset':'calibration_diagnostic' if snapshot.meeting_date <= '2023-04-06' else 'exposed_retrospective',
                  'identity':identity}
        directory = logger._directory(snapshot.meeting_date, replicate_id, self.experiment_id, self.condition_id)
        artifacts = {p.name:p for p in directory.glob('*.json')}
        self.checkpoints.save(identity, record, artifacts)
        return record

    async def run_panel_backtest(self, subset='holdout', max_meetings=None, model=None, temperature=None, resume=True):
        if subset not in ('all','calibration','holdout'):
            raise ValueError('Unknown panel subset')
        snapshots = load_snapshots(self.macro_panel_path)
        self._snapshot_by_date = {s.meeting_date:s for s in snapshots}
        self.truth = json.loads(self.truth_path.read_text())
        self._truth_by_date = {r['meeting_date']:r for r in self.truth}
        if len(self._truth_by_date) != len(self.truth) or set(self._truth_by_date) != set(self._snapshot_by_date):
            raise ValueError('Truth and snapshots must have exactly matching unique meetings')
        if self.research_mode:
            for snapshot in snapshots:
                snapshot.verify_sources(PROJECT_ROOT)
            if subset in ('all','calibration'):
                raise GenerationProvenanceError('Frozen calibration personas cannot be evaluated on earlier meetings as available information. Use an explicitly labeled diagnostic or dated rolling fit.')
        selected = [s for s in snapshots if subset == 'all' or (s.meeting_date <= '2023-04-06') == (subset == 'calibration')]
        if max_meetings is not None:
            if type(max_meetings) is not int or max_meetings < 1:
                raise ValueError('Invalid meeting limit')
            selected = selected[:max_meetings]
        provider = self.orchestrator.client.provider
        roster_by_meeting = {s.meeting_date:[p.member_id for p in self.load_roster_for_date(s.meeting_date)] for s in selected}
        inputs = prepare_inputs(selected, [self._truth_by_date[s.meeting_date] for s in selected],
                    self.config.model_dump(), {p.stem:yaml.safe_load(p.read_text()) for p in sorted(self.personas_dir.glob('*.yaml'))},
                    self.personas_dir/'corpus_manifest.json', PROJECT_ROOT, research_mode=self.research_mode)
        study_settings = {'study_manifest_version':3, 'metric_threshold_contract':'channel_v2',
                          'data_hash':file_hash(self.macro_panel_path),'truth_hash':file_hash(self.truth_path),
                          'persona_hash':content_hash({p.name:file_hash(p) for p in sorted(self.personas_dir.glob('*.yaml'))}),
                          'config_hash':content_hash(self.config.model_dump()),'code_hash':code_identity(),
                          'n_replicates':self.n_replicates,'seed_base':self.seed_base,'provider':provider,
                          'model':model or self.config.run.dev_model,'temperature':temperature if temperature is not None else self.config.run.temperature,
                          'meetings':[s.meeting_date for s in selected],'condition':self.condition_id,
                          'control':self.control_mode,'mask_identity':self.mask_identity,'mask_date':self.mask_date,
                          'fragmentation_policy':self.fragmentation_policy,'evidence_scope':'exposed retrospective study',
                          'source_validation_required':self.research_mode, 'roster_by_meeting':roster_by_meeting,
                          'governor_id':'shaktikanta_das',
                          'generation_settings':self.orchestrator.generation_settings(model=model, temperature=temperature),
                          'frozen_inputs_hashes':{name:content_hash(payload) for name,payload in inputs.items()}}
        self.experiment_id = self.experiment_id or 'study_'+content_hash(study_settings)[:20]
        # A provider smoke/mock run cannot acquire a live label.
        write_immutable(self.results_dir/self.experiment_id/self.condition_id/'study_manifest.json', study_settings, replay=resume)
        self._study_manifest = study_settings
        self._frozen_inputs = inputs
        self._frozen_experiment_id = self.experiment_id
        inputs_dir = self.results_dir/self.experiment_id/self.condition_id/'inputs'
        persist_inputs(inputs_dir, inputs, replay=resume)
        records = []
        for snapshot in selected:
            personas = self.load_roster_for_date(snapshot.meeting_date)
            for replicate in range(1,self.n_replicates+1):
                identity = self._identity(snapshot, personas, replicate, model, temperature)
                saved = self.checkpoints.load(identity) if resume else None
                if saved is not None:
                    record = saved['payload']
                else:
                    record = await self.run_meeting_backtest(snapshot, model, temperature, replicate_id=replicate)
                records.append(record)
        joined = []
        for record in records:
            truth = self._truth_by_date[record['meeting_date']]
            joined.append({**record,'actual_rate_bps':truth['actual_rate_bps'],'actual_stance':truth['actual_stance'],
                           'actual_rate_dissenters':truth['rate_dissenters'],'actual_stance_dissenters':truth['stance_dissenters']})
        path = self.results_dir/self.experiment_id/self.condition_id
        write_immutable(path/'predictions.json',joined,replay=resume)
        metrics = {str(rep):self.compute_aggregate_metrics(pd.DataFrame([r for r in joined if r['replicate_id']==rep]),
                                                         validation_config=self.config.validation.model_dump())
                   for rep in range(1,self.n_replicates+1)}
        write_immutable(path/'metrics_by_replicate.json',metrics,replay=resume)
        return pd.DataFrame(joined)

    @staticmethod
    def compute_aggregate_metrics(df, *, threshold_contract='channel_v2', validation_config=None):
        if df.empty or df['meeting_date'].duplicated().any():
            raise ValueError('Metrics require one aligned row per meeting, not pooled pseudo-replicates')
        pred_rate = list(df['sim_rate_dissenters']); true_rate = list(df['actual_rate_dissenters'])
        pred_stance = list(df['sim_stance_dissenters']); true_stance = list(df['actual_stance_dissenters'])
        thresholds = validation_config or {}
        summary = MetricsEvaluator.evaluate_panel([int(x) for x in df['sim_rate_bps']], [int(x) for x in df['actual_rate_bps']],
            list(df['sim_stance']),list(df['actual_stance']),
            [sorted(set(a)|set(b)) for a,b in zip(pred_rate,pred_stance)],
            [sorted(set(a)|set(b)) for a,b in zip(true_rate,true_stance)],
            predicted_rate_dissenters=pred_rate,true_rate_dissenters=true_rate,
            predicted_stance_dissenters=pred_stance,true_stance_dissenters=true_stance,
            directional_threshold=thresholds.get('directional_accuracy_threshold',.75),
            stance_threshold=thresholds.get('stance_accuracy_threshold',.70),
            dissent_f1_threshold=thresholds.get('dissent_f1_threshold',.50),
            exact_rate_threshold=thresholds.get('exact_rate_accuracy_threshold',.75),
            rate_dissent_f1_threshold=thresholds.get('rate_dissent_f1_threshold',.50),
            stance_dissent_f1_threshold=thresholds.get('stance_dissent_f1_threshold',.50),
            threshold_contract=threshold_contract)
        return summary.model_dump()


if __name__ == '__main__':
    raise SystemExit('Choose a frozen study protocol and explicit provider; no implicit paid panel run.')
