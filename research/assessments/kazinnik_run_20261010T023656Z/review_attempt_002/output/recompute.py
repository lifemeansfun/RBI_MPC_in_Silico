import json, sys, platform, hashlib, itertools
from pathlib import Path
from collections import Counter, defaultdict
root=Path(sys.argv[1]); out=Path(sys.argv[2])
def read(p): return json.loads((root/p).read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
result={'environment':{'python':sys.version,'executable':sys.executable,'platform':platform.platform()},'scope':'Independent standard-library raw receipt recomputation; no project imports or provider calls'}
frozen=read('current_protocol/FROZEN_QUESTION_AND_ANALYSIS.json')
result['freeze_hashes']={p:{'expected':h,'actual':sha(root/p),'match':sha(root/p)==h} for p,h in frozen['freeze_files'].items()}
result['reference_hashes']={p:sha(root/p) for p in ['Kazinnik_paper.pdf','current_protocol/sources/FOMC_In_Silico_2025-08-31.pdf']}
truth={r['meeting_date']:r for r in read('data/processed/vintage_v3/truth.json')}
result['candidate_regimes']=dict(Counter('hike' if r['actual_rate_bps']>0 else 'cut' if r['actual_rate_bps']<0 else 'hold' for r in truth.values()))
result['history_eligible_regimes']=dict(Counter('hike' if r['actual_rate_bps']>0 else 'cut' if r['actual_rate_bps']<0 else 'hold' for d,r in truth.items() if d not in frozen['cohort']['history_exclusions']))
targets=read('research/source_ledgers/historical_labels_round002/observed_targets.json')['channels']
result['labels']={}
for channel,rows in targets.items():
 vals=[v for row in rows for v in row['member_targets'].values()]
 result['labels'][channel]={'meetings':len(rows),'cells':len(vals),'observed':sum(v is not None for v in vals),'positive':sum(v is True for v in vals),'missing':sum(v is None for v in vals),'complete_meetings':sum(all(v is not None for v in r['member_targets'].values()) for r in rows)}
study=root/'results/upgrade_validation_round_001/root_oct08_20261008/full_mock_diagnostic_attempt_001'
records=sorted(study.glob('evidence/**/round_*.json'))
types=Counter(); providers=Counter(); served=Counter(); groups=defaultdict(list); r1=defaultdict(list); errors=[]; costs=0; cache=0
for path in records:
 d=json.loads(path.read_text()); g=d['generation']; m=g['metadata']; raw=json.loads(g['raw_text']); ident=g['request_identity']
 types[m['evidence_type']]+=1; providers[m['provider']]+=1; served[str(m.get('served_model'))]+=1; costs+=m['estimated_cost_usd']; cache+=bool(m['cache_replay'])
 if raw != g['parsed']: errors.append(str(path.relative_to(root))+': raw/parsed differ')
 if ident != d['artifact_identity']: errors.append(str(path.relative_to(root))+': identity differs')
 req=json.loads(m['request_payload_json'])
 # ASCII-only requests here; canonical contract uses default ASCII JSON.
 digest=hashlib.sha256(json.dumps(req,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
 if digest != m['request_hash']: errors.append(str(path.relative_to(root))+': request hash differs')
 key=(ident['condition_id'],ident['meeting_date'],ident['replicate_id'])
 if ident['round_number']==4: groups[key].append(raw)
 if ident['round_number']==1: r1[key].append(raw)
rows=[]
for key,v in sorted(groups.items()):
 assert len(v)==6
 pairs=list(itertools.combinations(v,2))
 rate=sum(a['final_rate_vote_bps']==b['final_rate_vote_bps'] for a,b in pairs)/15
 stance=sum(a['final_stance_vote']==b['final_stance_vote'] for a,b in pairs)/15
 joint=sum((a['final_rate_vote_bps'],a['final_stance_vote'])==(b['final_rate_vote_bps'],b['final_stance_vote']) for a,b in pairs)/15
 rates=Counter(x['final_rate_vote_bps'] for x in v); stances=Counter(x['final_stance_vote'] for x in v)
 pred=rates.most_common(1)[0][0]; spred=stances.most_common(1)[0][0]
 initial=r1[key]; initial_joint=sum((a['proposed_rate_change_bps'],a['proposed_stance'])==(b['proposed_rate_change_bps'],b['proposed_stance']) for a,b in itertools.combinations(initial,2))/15
 rows.append({'condition':key[0],'meeting':key[1],'replicate':key[2],'rate_agreement':rate,'stance_agreement':stance,'joint_agreement':joint,'initial_joint_agreement':initial_joint,'predicted_bps':pred,'predicted_stance':spred,'rate_correct':pred==truth[key[1]]['actual_rate_bps'],'stance_correct':spred==truth[key[1]]['actual_stance']})
result['receipts']={'count':len(records),'evidence_types':dict(types),'providers':dict(providers),'served_models':dict(served),'cache_replays':cache,'total_recorded_cost_usd':costs,'integrity_errors':errors}
result['diagnostic_by_condition']={}
for cond in sorted(set(r['condition'] for r in rows)):
 rs=[r for r in rows if r['condition']==cond]
 result['diagnostic_by_condition'][cond]={'meeting_replicates':len(rs),'meetings':len(set(r['meeting'] for r in rs)),'final_ballots':6*len(rs),'joint_agreement_values':sorted(set(r['joint_agreement'] for r in rs)),'initial_joint_agreement_values':sorted(set(r['initial_joint_agreement'] for r in rs)),'rate_agreement_values':sorted(set(r['rate_agreement'] for r in rs)),'rate_accuracy':sum(r['rate_correct'] for r in rs)/len(rs),'stance_accuracy':sum(r['stance_correct'] for r in rs)/len(rs)}
result['meeting_replicate_rows']=rows
result['resource_arithmetic']={'calls':23*2*(23+2),'generation_minutes_at_5rpm':23*2*25/5,'remaining_of_270_minutes':270-23*2*25/5,'max_conditional_agreement_change':5/15}
(out/'central_recomputation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='meeting_replicate_rows'},indent=2))

