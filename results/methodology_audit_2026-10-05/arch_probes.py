"""Offline adversarial architecture probes. Never queries providers or writes old artifacts.

Run: .venv/bin/python results/methodology_audit_2026-10-05/arch_probes.py
All production output paths are replaced with in-memory loggers or temporary directories.
Expected failures are recorded as observed implementation behavior, not test passes.
"""
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
import platform
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.behavioral.debate_orchestrator import DebateOrchestrator
from src.infra.cache import LLMCache
from src.infra.llm_client import LLMClient
from src.schemas.debate_schema import InitialStanceOutput, DeliberationOutput, FinalVoteOutput
from src.rule_engine.engine import InstitutionalRuleEngine
from src.scenarios.run_counterfactual_experiments import load_all_personas, load_meeting_snapshot
from src.attribution.attribution_runner import AttributionRunner


class MemoryLogger:
    def __init__(self):
        self.records = []
    def save_round_transcript(self, **kwargs):
        self.records.append(kwargs)
    def save_meeting_summary(self, **kwargs):
        self.records.append(kwargs)


class CaptureClient:
    def __init__(self, r3_action=0, poison_identity=False):
        self.calls = []
        self.r3_action = r3_action
        self.poison_identity = poison_identity
    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs['user_prompt']
        schema = kwargs['response_schema']
        member = re.search(r'"member_id":\s*"([^"]+)"', prompt).group(1)
        name_match = re.search(r'"member_name":\s*"([^"]+)"', prompt)
        name = name_match.group(1) if name_match else member
        if schema is InitialStanceOutput:
            data = dict(member_id=member, member_name=name, proposed_rate_change_bps=0,
                        proposed_stance='withdrawal_of_accommodation', key_rationale='R1_MARKER_'+member)
        elif schema is DeliberationOutput:
            round_number = 3 if 'TASK: Round 3' in prompt else 2
            data = dict(member_id=member, round_number=round_number,
                        current_rate_preference_bps=self.r3_action if round_number==3 else 0,
                        current_stance_preference='neutral' if round_number==3 else 'withdrawal_of_accommodation',
                        rebuttal_or_critique=f'R{round_number}_MARKER_'+member, open_to_compromise=True)
        else:
            data = dict(member_id='intruder' if self.poison_identity and member=='jayanth_varma' else member,
                        member_name=name, is_internal=member in ['shaktikanta_das','michael_patra','rajiv_ranjan'],
                        final_rate_vote_bps=0, final_stance_vote='withdrawal_of_accommodation',
                        official_statement_rationale='FINAL_MARKER_'+member)
        return json.dumps(data), schema(**data)


class FailureClient:
    async def generate(self, **kwargs):
        raise RuntimeError('OFFLINE_INJECTED_PROVIDER_OUTAGE')


def import_script(name):
    spec = importlib.util.spec_from_file_location('audit_'+name, ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def probes():
    findings = {'environment': {'python':sys.version, 'platform':platform.platform()}, 'probes':{}}
    out = findings['probes']
    personas = load_all_personas()
    snap = load_meeting_snapshot('2023-08-10')
    gov = 'shaktikanta_das'

    clients = [CaptureClient(r3_action=-50), CaptureClient(r3_action=50)]
    decisions = []
    for client in clients:
        decisions.append(await DebateOrchestrator(client, MemoryLogger()).run_meeting(snap, personas, gov))
    final_prompts = [[c['user_prompt'] for c in cl.calls if c['response_schema'] is FinalVoteOutput] for cl in clients]
    out['round3_disconnected'] = {
        'round3_actions_injected':[-50,50],
        'all_six_final_prompts_byte_identical':final_prompts[0]==final_prompts[1],
        'round3_markers_present_in_final_prompts':any('R3_MARKER_' in p for p in final_prompts[0]),
        'decisions': [d.rate_decision_bps for d in decisions],
        'final_prompt_sha256': [hashlib.sha256(p.encode()).hexdigest() for p in final_prompts[0]],
    }

    client = CaptureClient()
    await DebateOrchestrator(client, MemoryLogger()).run_meeting(snap, personas, gov, ablated_member_id='jayanth_varma')
    gov_prompt = next(c['user_prompt'] for c in client.calls if c['response_schema'] is FinalVoteOutput and '"member_id": "shaktikanta_das"' in c['user_prompt'])
    out['ablation_visibility'] = {
        'ablated_r1_rationale_visible_to_governor':'R1_MARKER_jayanth_varma' in gov_prompt,
        'ablated_r2_rationale_visible_to_governor':'R2_MARKER_jayanth_varma' in gov_prompt,
        'ablated_final_vote_rationale_visible_to_governor':'FINAL_MARKER_jayanth_varma' in gov_prompt,
        'ablated_member_casts_final_vote':any(c['response_schema'] is FinalVoteOutput and '"member_id": "jayanth_varma"' in c['user_prompt'] for c in client.calls),
    }

    with tempfile.TemporaryDirectory(prefix='mpc_arch_audit_') as tmp:
        cache_path = Path(tmp)/'replicates.sqlite'
        client = LLMClient(provider='mock', cache_enabled=False)
        client.cache_enabled = True
        client.cache = LLMCache(cache_path)
        generator_calls = []
        original = client._generate_mock
        def counted_mock(*args, **kwargs):
            generator_calls.append(1)
            return original(*args, **kwargs)
        client._generate_mock = counted_mock
        logger = MemoryLogger()
        orch = DebateOrchestrator(client, logger)
        first = await orch.run_meeting(snap, personas, gov, replicate_id=1, model='mock', temperature=0.6)
        count_first = len(generator_calls)
        second = await orch.run_meeting(snap, personas, gov, replicate_id=2, model='mock', temperature=0.6)
        with sqlite3.connect(cache_path) as conn:
            seeds = conn.execute('select distinct seed from response_cache').fetchall()
        a,b = first.model_dump(), second.model_dump()
        a.pop('replicate_id'); b.pop('replicate_id')
        out['replicate_cache_replay'] = {'replicate1_generator_calls':count_first,
            'replicate2_new_generator_calls':len(generator_calls)-count_first,
            'replicate_outputs_equal_except_id':a==b, 'cache_seeds':seeds}

        client = LLMClient(provider='mock', cache_enabled=False)
        client.provider = 'gemini'
        client.cache_enabled = True
        client.cache = LLMCache(Path(tmp)/'rotation.sqlite')
        client._min_interval = 0
        client.cfg = SimpleNamespace(run=SimpleNamespace(dev_model='requested-model', temperature=0.6,
                                    seed_base=42, fallback_models=['fallback-model']))
        attempted_models = []
        recorded_models = []
        class FakeGovernor:
            def record_usage(self, **kwargs):
                recorded_models.append(kwargs['model'])
        client.governor = FakeGovernor()
        async def fake_call(user_prompt, system_prompt, model, temperature, seed):
            attempted_models.append(model)
            if len(attempted_models) < 3:
                raise RuntimeError('429 RESOURCE_EXHAUSTED')
            return json.dumps({'served_by':'fallback-model'}), 5, 3
        client._call_gemini = fake_call
        async def no_sleep(*args, **kwargs):
            return None
        with patch('src.infra.llm_client.asyncio.sleep', new=no_sleep):
            raw,_ = await client.generate(user_prompt='offline rotation probe', model='requested-model')
        with sqlite3.connect(client.cache.db_path) as conn:
            stored = conn.execute('select model,response_text from response_cache').fetchall()
        out['model_rotation_mislabeled'] = {'attempted_models':attempted_models,
            'cost_recorded_models':recorded_models, 'cache_records':stored, 'returned':raw}

        # Transcript integrity guard adversary: create filenames only, all contents invalid.
        guard_mod = import_script('academic_integrity_guard')
        guard = guard_mod.AcademicIntegrityGuard()
        guard.runs_dir = Path(tmp)/'fake_runs'
        dates = ['2023-06-08','2023-08-10','2023-10-06','2023-12-08',
                 '2024-02-08','2024-04-05','2024-06-07','2024-08-08','2022-08-05']
        for date in dates:
            repdir = guard.runs_dir/'mock_untrusted'/'transcripts'/date/'rep_1'
            repdir.mkdir(parents=True)
            (repdir/'meeting_outcome.json').write_text('INVALID JSON; NO LIVE PROVIDER')
            for p in personas:
                for round_number in [1,2,3,4]:
                    (repdir/f'round_{round_number}_{p.member_id}.json').write_text('INVALID JSON')
        with contextlib.redirect_stdout(io.StringIO()):
            accepts_invalid = guard.check_invariant_2_transcript_provenance()
        guard.tables_dir = Path(tmp)/'fake_tables'
        guard.tables_dir.mkdir()
        (guard.tables_dir/'holdout_validation_live_metrics.csv').write_text('dissent_f1\n0.10\n')
        guard.report_path = Path(tmp)/'fake_report.md'
        guard.report_path.write_text('Report says dissent F1 0.83. This intentionally contradicts CSV 0.10.')
        with contextlib.redirect_stdout(io.StringIO()):
            accepts_wrong_f1 = guard.check_invariant_3_table_report_concordance()
        out['integrity_guard_false_positives'] = {
            'accepts_225_invalid_json_files_as_nine_verified_live_transcript_chains':accepts_invalid,
            'accepts_report_f1_0_83_when_csv_f1_0_10':accepts_wrong_f1,
            'violations_recorded':guard.violations,
        }

        # Entire reproduce orchestration mocked; observe status when every expected artifact is absent.
        reproduce = import_script('reproduce')
        reproduce.PROJECT_ROOT = Path(tmp)/'empty_root'
        reproduce.PROJECT_ROOT.mkdir()
        step_commands = []
        reproduce.run_step = lambda name, command: (step_commands.append(command) or True)
        captured = io.StringIO()
        exited = None
        with contextlib.redirect_stdout(captured):
            try:
                reproduce.main()
            except SystemExit as exc:
                exited = exc.code
        out['reproduce_missing_artifacts'] = {
            'system_exit':exited,
            'all_phases_verified_green_printed':'ALL PHASES VERIFIED GREEN' in captured.getvalue(),
            'step_commands':step_commands,
            'empirical_execution_steps_present':any('run_holdout_live.py' in str(c) or 'run_counterfactual_experiments.py' in str(c) for c in step_commands),
        }

        # Execute the repository's actual two-model stress test, injecting outages only.
        cross_model = import_script('stress_test_multi_model')
        outage_orch = DebateOrchestrator(FailureClient(), MemoryLogger())
        cross_model.DebateOrchestrator = lambda: outage_orch
        real_open = open
        cross_model_evidence = Path(tmp)/'cross_model.md'
        def redirected_open(path, *args, **kwargs):
            if str(path)=='results/stress_test_results.md':
                path = cross_model_evidence
            return real_open(path, *args, **kwargs)
        cross_model.open = redirected_open
        await cross_model.run_multi_model_test()
        out['actual_cross_model_outage_false_positive'] = {
            'evidence_text':cross_model_evidence.read_text(),
            'script_claims_pass': '**PASSED.' in cross_model_evidence.read_text(),
            'provider_calls':0,
        }

        # Low budget with mock generation shows caller swallows budget exception.
        from src.infra.cost_governor import CostGovernor
        client=LLMClient(provider='mock',cache_enabled=False)
        client.governor=CostGovernor(budget_cap_usd=0.000001)
        budget_outcome=await DebateOrchestrator(client,MemoryLogger()).run_meeting(snap,personas,gov,model='unpriced_model')
        out['budget_cap_does_not_halt_meeting'] = {
            'governor_summary':client.governor.get_summary(),
            'fallbacks_count':budget_outcome.fallbacks_count,
            'meeting_returned_despite_budget_exceptions':True,
        }

        # Exercise real logger only after redirecting project root to temporary storage.
        import src.infra.transcript_logger as transcript_module
        with patch.object(transcript_module,'PROJECT_ROOT',Path(tmp)/'logger_root'):
            disk_logger=transcript_module.TranscriptLogger(run_id='same_run')
            disk_orch=DebateOrchestrator(CaptureClient(),disk_logger)
            await disk_orch.run_meeting(snap,personas,gov,replicate_id=1)
            files_first=set(p.relative_to(disk_logger.run_dir) for p in disk_logger.run_dir.rglob('*.json'))
            outcome_file=disk_logger.transcripts_dir/snap.meeting_date/'rep_1'/'meeting_outcome.json'
            first_mtime=outcome_file.stat().st_mtime_ns
            shock=snap.model_copy(update={'cpi_headline_yoy_pct':snap.cpi_headline_yoy_pct+2.0})
            await disk_orch.run_meeting(shock,personas,gov,replicate_id=1)
            files_second=set(p.relative_to(disk_logger.run_dir) for p in disk_logger.run_dir.rglob('*.json'))
            out['experiment_transcript_path_collision'] = {
                'files_after_baseline':len(files_first),'files_after_shock':len(files_second),
                'same_file_paths':files_first==files_second,
                'outcome_file_overwritten':outcome_file.stat().st_mtime_ns!=first_mtime,
            }

    poisoned = await DebateOrchestrator(CaptureClient(poison_identity=True), MemoryLogger()).run_meeting(snap, personas, gov)
    out['identity_not_bound_to_caller'] = {'requested_member':'jayanth_varma',
        'accepted_final_member_ids':[v.member_id for v in poisoned.member_votes],
        'decision_successful':True}

    out['schema_silent_repairs_and_action_mismatch'] = {}
    for action in ['not a number',35,40]:
        vote = FinalVoteOutput(member_id='x',member_name='X',final_rate_vote_bps=action,
            final_stance_vote='mysterious_unknown_stance',official_statement_rationale='OFFLINE PROBE')
        rate_votes = {p.member_id:vote.final_rate_vote_bps for p in personas}
        try:
            InstitutionalRuleEngine.aggregate_rate_votes(rate_votes,gov)
            exception=None
        except ValueError as exc:
            exception=str(exc)
        out['schema_silent_repairs_and_action_mismatch'][str(action)] = {
            'coerced_rate':vote.final_rate_vote_bps, 'fallback_flag':vote.fallback_triggered,
            'unknown_stance_accepted':vote.final_stance_vote, 'aggregation_error':exception}

    fallback = await DebateOrchestrator(FailureClient(),MemoryLogger()).run_meeting(snap,personas,gov)
    recession=snap.model_copy(update={'cpi_headline_yoy_pct':1.0,'output_gap_pct':-5.0})
    gov_persona=next(p for p in personas if p.member_id==gov)
    out['fallback_only_pipeline'] = {
        'fallbacks_count':fallback.fallbacks_count, 'rate_decision_bps':fallback.rate_decision_bps,
        'stance_decision':fallback.stance_decision,
        'recession_governor_heuristic_rate':DebateOrchestrator._compute_defensive_rate_heuristic(gov_persona,recession),
        'cross_model_equality_would_pass_when_both_models_outage':True,
    }
    out['casting_ablation_statusquo'] = AttributionRunner.ablate_casting_vote(
        fallback.model_copy(update={'tie_broken_by_governor_stance':True}),gov).__dict__

    out['cache_temperature_collision'] = {
        'temperature_a':0.6001,'temperature_b':0.6004,
        'equal_cache_keys':LLMCache.compute_key('gemini','m',None,'p',0.6001,42)==LLMCache.compute_key('gemini','m',None,'p',0.6004,42)}

    from src.scenarios.scenario_runner import ScenarioRunner
    fed_base=load_meeting_snapshot('2022-08-05')
    fed=ScenarioRunner.build_us_fed_spillover_snapshot(fed_base)
    out['counterfactual_extra_field_loss'] = {
        'anchor_date':fed_base.meeting_date,
        'baseline_gva_growth_yoy_pct':fed_base.gva_growth_yoy_pct,
        'fed_shock_gva_growth_yoy_pct':fed.gva_growth_yoy_pct,
        'gva_present_in_baseline_prompt':'Gross Value Added' in fed_base.to_prompt_text(),
        'gva_present_in_fed_shock_prompt':'Gross Value Added' in fed.to_prompt_text(),
    }

    # Read-only evidence inventory, without exposing prompts or any API credentials.
    inventory=[]
    for path in sorted((ROOT/'runs').glob('*/transcripts/*/rep_*/meeting_outcome.json')):
        data=json.loads(path.read_text())
        inventory.append({'path':str(path.relative_to(ROOT)), 'meeting_date':data.get('meeting_date'),
            'fallbacks_count':data.get('fallbacks_count'),
            'metadata_present':{k:k in data for k in ['provider','model','seed','temperature','prompt_hash','scenario_id']}})
    findings['existing_outcome_inventory']=inventory
    db=ROOT/'.cache'/'llm_cache.sqlite'
    if db.exists():
        with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
            findings['existing_cache_inventory']=conn.execute('select provider,model,seed,temperature,count(*) from response_cache group by provider,model,seed,temperature').fetchall()
    files=['src/behavioral/debate_orchestrator.py','src/infra/llm_client.py','src/infra/cache.py',
           'src/infra/transcript_logger.py','src/schemas/debate_schema.py','src/schemas/persona_schema.py',
           'src/attribution/attribution_runner.py','src/scenarios/scenario_runner.py',
           'src/scenarios/run_counterfactual_experiments.py','src/rule_engine/engine.py',
           'src/backtest/backtest_runner.py','src/backtest/run_holdout_live.py',
           'scripts/academic_integrity_guard.py','scripts/reproduce.py','scripts/stress_test_multi_model.py',
           'scripts/stress_test_ablation.py','config/config.yaml','requirements.txt','results/RESULTS_REPORT.md']
    findings['source_sha256']={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}
    return findings


if __name__=='__main__':
    evidence=asyncio.run(probes())
    destination=Path(__file__).with_name('arch_probe_results.json')
    destination.write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence['probes'],indent=2))
