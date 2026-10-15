import json, sys, hashlib, re
from pathlib import Path
from collections import Counter
from datetime import datetime
from bs4 import BeautifulSoup
root=Path(sys.argv[1]); out=Path(sys.argv[2])
def read(p): return json.loads((root/p).read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def norm(x): return ' '.join(x.split())
report={'scope':'Source/hash/history check and receipt-contract reconciliation; no model calls, scientific changes or first-script rerun'}
manifest=read('research/source_ledgers/historical_labels_round002/input_manifest.json')
report['input_manifest']={'files':len(manifest['files']),'mismatches':[p for p,h in manifest['files'].items() if sha(root/p)!=h]}
ledger=read('research/source_ledgers/historical_labels_round002/label_ledger.json')['meetings']
checks=[]; ballotcounts=Counter(); source_failures=[]
for row in ledger:
 soup=BeautifulSoup((root/row['source_file']).read_bytes(),'html.parser'); text=norm(soup.get_text(' ',strip=True))
 tables=[]
 for table in soup.find_all('table'):
  votes=[]
  for tr in table.find_all('tr'):
   cells=[norm(td.get_text(' ',strip=True)) for td in tr.find_all(['td','th'],recursive=False)]
   if len(cells)==2 and cells[1] in ('Yes','No'): votes.append(cells)
  if len(votes)==6: tables.append(votes)
 if len(tables)!=1: source_failures.append([row['meeting_date'],'six-vote table count',len(tables)])
 else:
  ballotcounts.update(c[1] for c in tables[0])
  if Counter(c[1] for c in tables[0])!=Counter(row['literal_rate_ballots'].values()): source_failures.append([row['meeting_date'],'ballot tally differs'])
 for excerpt in row['resolution_evidence']:
  if norm(excerpt) not in text: source_failures.append([row['meeting_date'],'resolution excerpt absent'])
 checks.append({'meeting':row['meeting_date'],'source_hash_matches':sha(root/row['source_file'])==row['source_sha256'],'published_after_start':row['publication_date']>row['meeting_start_date'],'rate_from_levels_bps':round((row['repo_after_pct']-row['repo_before_pct'])*100),'reported_rate_bps':row['actual_rate_bps']})
report['original_source_checks']={'meetings':len(checks),'literal_ballots_from_raw_tables':dict(ballotcounts),'failures':source_failures,'rows':checks}
manifests=[(p,json.loads(p.read_text())) for p in sorted((root/'data/processed/statements_v2').glob('*/source_manifest.json'))]
missing=[]; hashfails=[]; history=[]
for p,m in manifests:
 if m['decision_date'] not in {r['meeting_date'] for r in ledger}: continue
 counts={member:0 for member in m['statement_sha256']}
 for prior_path,prior in manifests:
  if prior['publication_date']<m['meeting_start_date']:
   for member in counts:
    if member in prior['statement_sha256']:
     sp=prior_path.parent/(member+'.txt')
     if sha(sp)!=prior['statement_sha256'][member]: hashfails.append(str(sp.relative_to(root)))
     counts[member]+=1
 zero=[member for member,n in counts.items() if n==0]
 if zero: missing.append({'meeting':m['decision_date'],'members':zero})
 history.append({'meeting':m['decision_date'],'prior_statement_counts':counts})
report['history']={'manifest_count':len(manifests),'eligible_within_supplied_corpus':len(history)-len(missing),'missing':missing,'prior_statement_hash_failures':sorted(set(hashfails)),'rows':history,'limitation':'Membership taken from retrospective manifest only; not pre-cutoff appointment verification'}
snapshots=read('data/processed/vintage_v3/snapshots.json'); obschecks=[]; missingfields=Counter()
for s in snapshots:
 for k,v in s.items():
  if v is None: missingfields[k]+=1
 for obs in s['observation_evidence']:
  obschecks.append({'meeting':s['meeting_date'],'field':obs['field'],'precutoff':datetime.fromisoformat(obs['released_at'])<datetime.fromisoformat(s['information_cutoff']),'hash_matches':sha(root/obs['source_file'])==obs['source_sha256'],'snapshot_value_matches':s.get(obs['field'])==obs['value']})
report['observations']={'count':len(obschecks),'failed':[r for r in obschecks if not all(r[k] for k in ('precutoff','hash_matches','snapshot_value_matches'))],'null_field_counts':dict(missingfields),'limit':'Checks ledger timestamps and retained hashes; not first-availability authentication or all raw numerical transcription'}
study=root/'results/upgrade_validation_round_001/root_oct08_20261008/full_mock_diagnostic_attempt_001'
receiptcounts=Counter(); examples={}; bad=[]; rationale=0
for p in sorted(study.glob('evidence/**/round_*.json')):
 d=json.loads(p.read_text()); g=d['generation']; m=g['metadata']; request=json.loads(m['request_payload_json']); raw=json.loads(g['raw_text']); parsed=g['parsed']
 receiptcounts['records']+=1
 if digest(request)!=m['request_hash']: bad.append([str(p.relative_to(root)),'request_hash'])
 if request['request_identity']!=g['request_identity']: bad.append([str(p.relative_to(root)),'request_identity'])
 delta={k:{'raw':raw.get(k),'parsed':parsed.get(k)} for k in raw.keys()|parsed.keys() if raw.get(k)!=parsed.get(k)}
 key=','.join(sorted(delta))
 receiptcounts['raw_parsed_difference_fields:'+key]+=1
 if key not in examples: examples[key]={'path':str(p.relative_to(root)),'differences':delta}
 identity_delta={k:{'generation':g['request_identity'].get(k),'artifact':d['artifact_identity'].get(k)} for k in g['request_identity'].keys()|d['artifact_identity'].keys() if g['request_identity'].get(k)!=d['artifact_identity'].get(k)}
 ikey=','.join(sorted(identity_delta)); receiptcounts['identity_difference_fields:'+ikey]+=1
 if 'identity:'+ikey not in examples: examples['identity:'+ikey]={'path':str(p.relative_to(root)),'differences':identity_delta}
 prompt=d['prompt']['user_prompt']
 if 'VISIBLE NON-GOVERNOR BINDING BALLOTS' in prompt:
  receiptcounts['governor_ballot_contexts']+=1
  part=prompt.split('VISIBLE NON-GOVERNOR BINDING BALLOTS',1)[1].split('TASK:',1)[0]
  if 'official_statement_rationale' in part: rationale+=1
report['receipt_contract']={'counts':dict(receiptcounts),'correct_utf8_hash_or_request_identity_failures':bad,'difference_examples':examples,'visible_ballot_contexts_with_new_rationales':rationale,'first_probe_limitation':'First script used ASCII escaping for hashes and full-object equality before schema defaults/alias normalization. Its integrity_errors are provisional mismatches, not established corruption; preserved unmodified.'}
(out/'source_and_contract_checks.json').write_text(json.dumps(report,indent=2)+'\n')
summary={k:v for k,v in report.items()}
summary['original_source_checks']={k:v for k,v in summary['original_source_checks'].items() if k!='rows'}
summary['history']={k:v for k,v in summary['history'].items() if k!='rows'}
print(json.dumps(summary,indent=2))

