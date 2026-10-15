import guard
import json,hashlib,sys,platform,collections,traceback
from pathlib import Path
root=Path.cwd(); out=root/'peer_review_output'
def j(p): return json.loads(Path(p).read_text())
def emit(name,value): print(name,json.dumps(value,default=str,sort_keys=True))
manifest=j('SNAPSHOT_SHA256.json'); bad=[]
for p,h in manifest.items():
    f=Path(p)
    if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=h: bad.append(p)
emit('integrity',{'files':len(manifest),'mismatches':bad})
emit('environment',{'executable':sys.executable,'python':sys.version,'platform':platform.platform()})
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona
from src.persona_engine.provenance import verify_personas
import yaml
snapshots=[MacroMeetingSnapshot.model_validate(s) for s in j('data/processed/vintage_v3/snapshots.json')]
for s in snapshots:s.verify_sources(root)
emit('snapshot_checks',{'count':len(snapshots),'dates':[s.meeting_date for s in snapshots],'missing':{k:sum(getattr(s,k) is None for s in snapshots) for k in ['output_gap_pct','gdp_growth_yoy_pct','us_fed_funds_rate_pct','cpi_food_yoy_pct']}})
personas=[MemberPersona.model_validate(yaml.safe_load(p.read_text())) for p in Path('personas/calibration_2023-04-30_v2').glob('*.yaml')]
verify_personas(personas,'2023-06-06',source_root=root)
emit('persona_validation',{'count':len(personas),'scores':{p.member_id:p.hawk_dove_score for p in personas}})
from src.validation.study_replay import replay_study
for anchor in sorted(Path('results/current_mock/anchors').glob('*.json')):
    a=j(anchor);emit('anchor',a)
    try:
        candidates=list(Path('results/current_mock').rglob('study_manifest.json'))
        study=next(p.parent for p in candidates if p.parent.name==anchor.stem)
        h=a.get('study_manifest_hash') or a.get('manifest_hash')
        emit('replay_'+anchor.stem,replay_study(study,out/('replay_'+anchor.stem),expected_manifest_hash=h))
    except Exception: traceback.print_exc()
# Independently score generated final ballots, without repository metric helpers.
counts=collections.Counter(); ballots={}; types=collections.Counter()
for p in Path('results/current_mock').rglob('round_4_*.json'):
    d=j(p); ident=d['artifact_identity']; key=(ident['condition_id'],ident['replicate_id'],ident['meeting_date'])
    ballots.setdefault(key,[]).append(d)
for p in Path('results/current_mock').rglob('round_[1234]_*.json'):
    d=j(p); types[d['generation']['metadata']['evidence_type']]+=1
truth={t['meeting_date']:t for t in j('data/processed/vintage_v3/truth.json')}
metrics={}
for cond,rep in sorted({k[:2] for k in ballots}):
    tp=fp=fn=rtp=rfp=rfn=stp=sfp=sfn=0;rateok=stanceok=0;preds=[]
    for key,rows in sorted(ballots.items()):
        if key[:2]!=(cond,rep):continue
        day=key[2]; t=truth[day]
        assert len(rows)==6
        rate=collections.Counter(r['final_rate_vote_bps'] for r in rows).most_common(1)[0][0]
        stance=collections.Counter(r['final_stance_vote'] for r in rows).most_common(1)[0][0]
        pr={r['member_id'] for r in rows if r['final_rate_vote_bps']!=rate}; ps={r['member_id'] for r in rows if r['final_stance_vote']!=stance}
        tr=set(t['rate_dissenters']);ts=set(t['stance_dissenters']);p=pr|ps; actual=tr|ts
        tp+=len(p&actual);fp+=len(p-actual);fn+=len(actual-p)
        rtp+=len(pr&tr);rfp+=len(pr-tr);rfn+=len(tr-pr)
        stp+=len(ps&ts);sfp+=len(ps-ts);sfn+=len(ts-ps)
        rateok+=rate==t['actual_rate_bps'];stanceok+=stance==t['actual_stance'];preds.append([day,rate,stance,sorted(pr),sorted(ps)])
    metrics[f'{cond}/{rep}']={'n':len(preds),'rate_correct':rateok,'stance_correct':stanceok,'union_counts':[tp,fp,fn],'union_f1':2*tp/(2*tp+fp+fn),'rate_counts':[rtp,rfp,rfn],'stance_counts':[stp,sfp,sfn],'predictions':preds}
emit('generation_types',types);emit('independent_ballot_metrics',metrics)
(out/'independent_metrics.json').write_text(json.dumps(metrics,indent=2))
# Exhaust all 3-category full-roster vote profiles under strict institutional policy.
from itertools import product
from src.rule_engine.engine import InstitutionalRuleEngine as E
n=collections.Counter()
for values in product([-25,0,25],repeat=6):
    tally=collections.Counter(values);top,c=tally.most_common(1)[0];expected=top if c>3 else values[0] if len(tally)==2 and c==3 else None
    try:
        got=E.aggregate_rate_votes(dict(zip(['g','a','b','c','d','e'],values)),'g',fragmentation_policy='reject')
        assert expected is not None and got.winning_action==expected
        n['accepted']+=1
    except ValueError:
        assert expected is None;n['rejected_fragmented']+=1
emit('exhaustive_rule_probe',n)
# Full benchmark must reject missing sourced gap; zero-size Fed intervention should be examined.
from src.rational.taylor_rule import SmoothedTaylorRule,MemberTaylorParameters
try: SmoothedTaylorRule().compute_continuous_rate(snapshots[-1],MemberTaylorParameters('x'))
except ValueError as e:emit('full_taylor_expected_rejection',str(e))
from src.scenarios.scenario_runner import ScenarioRunner
shock=ScenarioRunner.build_us_fed_spillover_snapshot(snapshots[-1],fed_hike_bps=0,inr_depreciation=0)
emit('zero_fed_shock_changes',{k:[getattr(snapshots[-1],k),getattr(shock,k)] for k in snapshots[-1].observable_values() if getattr(snapshots[-1],k)!=getattr(shock,k)})
