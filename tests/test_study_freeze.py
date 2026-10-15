"""No submission may follow a change to already frozen scientific settings."""
import asyncio

import pytest

import src.backtest.backtest_runner as backtest_module
from src.backtest.backtest_runner import BacktestRunner, load_snapshots, PROJECT_ROOT
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.infra.exceptions import GenerationProvenanceError
from src.infra.llm_client import LLMClient
from src.infra.transcript_logger import TranscriptLogger


class FrozenOnly(Exception):
    pass


@pytest.fixture
def frozen_runner(monkeypatch,tmp_path):
    client = LLMClient(provider='mock',cache_enabled=False)
    runner = BacktestRunner(results_dir=tmp_path/'evidence',n_replicates=1,experiment_id='freeze_boundary',
        orchestrator=DebateOrchestrator(client,TranscriptLogger(output_root=tmp_path/'logs')))
    async def stop(*args,**kwargs):
        raise FrozenOnly()
    monkeypatch.setattr(runner,'run_meeting_backtest',stop)
    with pytest.raises(FrozenOnly):
        asyncio.run(runner.run_panel_backtest(max_meetings=1,resume=False))
    snapshot = load_snapshots(PROJECT_ROOT/'data/processed/vintage_v3/snapshots.json')[17]
    personas = runner.load_roster_for_date(snapshot.meeting_date)
    return runner,snapshot,personas


@pytest.mark.parametrize('change',['config','seed','replicates','experiment','condition','control','mask',
    'fragmentation','model','temperature','snapshot','persona','roster','macro_bytes','truth_bytes','persona_bytes','provider'])
def test_frozen_scientific_identity_change_is_rejected_before_generation(frozen_runner,monkeypatch,change):
    runner,snapshot,personas = frozen_runner
    kwargs = {}
    if change=='config': monkeypatch.setattr(runner.config.run,'max_output_tokens',runner.config.run.max_output_tokens+1)
    if change=='seed': runner.seed_base += 1
    if change=='replicates': runner.n_replicates += 1
    if change=='experiment': runner.experiment_id='different'
    if change=='condition': runner.condition_id='different'
    if change=='control': runner.control_mode='independent'
    if change=='mask': runner.mask_date=True
    if change=='fragmentation': runner.fragmentation_policy='legacy_synthetic'
    if change=='model': kwargs['model']='different'
    if change=='temperature': kwargs['temperature']=.123
    if change=='snapshot': snapshot=snapshot.model_copy(update={'cpi_headline_yoy_pct':snapshot.cpi_headline_yoy_pct+.01})
    if change=='persona': personas[0]=personas[0].model_copy(update={'name':'Changed name'})
    if change=='roster': personas=personas[::-1]
    if change=='provider': monkeypatch.setattr(runner.orchestrator.client,'provider','different')
    if change in ('macro_bytes','truth_bytes','persona_bytes'):
        target = runner.macro_panel_path if change=='macro_bytes' else runner.truth_path if change=='truth_bytes' else next(runner.personas_dir.glob('*.yaml'))
        original = backtest_module.file_hash
        monkeypatch.setattr(backtest_module,'file_hash',lambda path: '0'*64 if path==target else original(path))
    with pytest.raises(GenerationProvenanceError,match='after study freeze'):
        runner._identity(snapshot,personas,1,kwargs.get('model'),kwargs.get('temperature'))


def test_unchanged_frozen_identity_is_allowed(frozen_runner):
    runner,snapshot,personas = frozen_runner
    identity = runner._identity(snapshot,personas,1,None,None)
    assert identity['study_manifest_hash'] and identity['replicate_id']==1
