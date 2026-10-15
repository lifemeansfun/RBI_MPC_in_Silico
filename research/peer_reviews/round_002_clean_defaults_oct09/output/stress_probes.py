import guard
import json,traceback,importlib.metadata,collections
from pathlib import Path
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.debate_schema import FinalVoteOutput
from src.infra.llm_client import LLMClient
from src.reporting.report_builder import ReportBuilder
from src.validation.metrics import MetricsEvaluator
from src.rational.calibration import fit_taylor_comparator
from src.persona_engine.extractor import PersonaExtractor
out=Path('peer_review_output')
def j(p):return json.loads(Path(p).read_text())
def emit(k,v):print(k,json.dumps(v,default=str))
# Pure mock helper: no provider generate call.
s=MacroMeetingSnapshot.model_validate(j('data/processed/vintage_v3/snapshots.json')[0])
raw,_,_=LLMClient._generate_mock(None,s.to_prompt_text(),None,'mock',FinalVoteOutput,{'member_id':'shashanka_bhide','member_name':'Bhide','is_internal':False})
emit('mock_prev_stance_prompt_mismatch',{'supplied':s.prev_stance,'prompt':s.to_prompt_text(),'generated':json.loads(raw)['final_stance_vote']})
# Swapping dissent channel still passes combined gate.
m=MetricsEvaluator.evaluate_panel([0],[0],['neutral'],['neutral'],[['x']],[['x']],predicted_rate_dissenters=[[]],true_rate_dissenters=[['x']],predicted_stance_dissenters=[['x']],true_stance_dissenters=[[]])
emit('wrong_channel_gate',m.model_dump())
# Existing reporter cannot format a valid undefined precision statistic.
summary=j('results/current_mock/diagnostic_summary.json')['condition_metrics']['masked']['1']
try:
    ReportBuilder(out/'report_probe').generate_markdown_report(summary,[],[])
except Exception as e:emit('report_with_valid_null_metric',{'error':repr(e)});traceback.print_exc()
# Regenerate all lexical statistics and compare to frozen corpus manifest without overwriting personas.
ex=PersonaExtractor(output_dir=out/'persona_probe');manifest=j('personas/calibration_2023-04-30_v2/corpus_manifest.json')
comparison={}
for member,saved in manifest['members'].items():
    generated=ex.analyze_member(member);comparison[member]=[k for k in generated if generated[k]!=saved.get(k)]
emit('persona_recomputation_differing_fields',comparison)
# Refit reduced-input comparator; this is a reviewer diagnostic, not new project evidence.
snaps=[MacroMeetingSnapshot.model_validate(s) for s in j('data/processed/vintage_v3/snapshots.json')]
truth={t['meeting_date']:t for t in j('data/processed/vintage_v3/truth.json')}
cal=[s for s in snaps if s.meeting_date<='2023-04-06'];ev=[s for s in snaps if s.meeting_date>'2023-04-06']
fitted=fit_taylor_comparator(cal,[truth[s.meeting_date]['actual_rate_bps'] for s in cal],reduced_input=True,bootstrap_draws=100,seed=17)
(out/'reviewer_fitted_taylor.json').write_text(json.dumps(fitted.to_dict(),indent=2))
pred=[(s.meeting_date,*fitted.predict(s)) for s in ev]
emit('reduced_taylor_diagnostic',{'coefficients':{k:getattr(fitted,k) for k in ['r_star','alpha','beta','gamma','rho','design_rank']},'predictions':pred,'mae':sum(abs(p[1]-truth[p[0]]['actual_rate_bps']) for p in pred)/len(pred)})
emit('package_versions',{p:importlib.metadata.version(p) for p in ['pydantic','numpy','pandas','scipy','pytest','pytest-asyncio','pdfplumber','jsonschema','beautifulsoup4']})
# Frozen generation code match, without history.
from src.backtest.backtest_runner import code_identity
emit('code_identity',code_identity())
