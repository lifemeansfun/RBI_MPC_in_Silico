import guard
import json,collections,hashlib
from pathlib import Path
from bs4 import BeautifulSoup
import pdfplumber
out=Path('peer_review_output')
def j(p):return json.loads(Path(p).read_text())
snaps=j('data/processed/vintage_v3/snapshots.json')
for s in [snaps[0],snaps[-1]]:
    for o in s['observations']:
        if o['field'] not in ['gdp_growth_yoy_pct','us_fed_funds_rate_pct']:continue
        p=Path(o['source_file'])
        if p.suffix=='.pdf':
            with pdfplumber.open(p) as pdf:text='\n'.join(page.extract_text() or '' for page in pdf.pages)
        else:text=BeautifulSoup(p.read_bytes(),'html.parser').get_text(' ',strip=True)
        name=s['meeting_date']+'_'+o['field']
        (out/(name+'_source.txt')).write_text(text)
        print(name,json.dumps(o))
# Compare genuinely compatible fields from the separate annotation passes.
a=j('research/source_ledgers/expanded_panel_oct08/meeting_label_ledger.json')['meetings']; b=j('research/source_ledgers/expanded_panel_oct08_doublecode/annotations.json')['meetings']
bmap={r['meeting_id']:r for r in b};agreements=[]
for r in a:
    q=bmap[r['meeting_id']]
    agreements.append({'meeting':r['meeting_id'],'rate_equal':r['policy_change_bps']==q['committee']['rate_delta_bps'],'repo_equal':r['policy_repo_after_pct']==q['committee']['repo_rate_percent'],'stance_first':r['committee_stance'],'stance_second':q['committee']['stance']})
print('committee_coding_comparison',json.dumps(agreements))
print('second_member_keys',list(b[0]['members'][0]))
print('first_meeting_keys',list(a[0]))
from src.schemas.decision_space import STANCE_ACTIONS
print('unsupported_expanded_stances',[r['committee']['stance'] for r in b if r['committee']['stance'].replace(' ','_') not in STANCE_ACTIONS])
# Scoring baselines independently against the current declared labels.
truth={r['meeting_date']:r for r in j('data/processed/vintage_v3/truth.json')}
rows=j('results/current_mock/baseline_predictions.json')
print('baseline_format',type(rows).__name__)
for name in sorted(set(r['baseline'] for r in rows)):
    pred=[r for r in rows if r['baseline']==name];tp=fp=fn=0
    for r in pred:
        t=truth[r['meeting_date']];p=set(r['rate_dissenters'])|set(r['stance_dissenters']);z=set(t['rate_dissenters'])|set(t['stance_dissenters']);tp+=len(p&z);fp+=len(p-z);fn+=len(z-p)
    print('baseline_counts',name,{'tp':tp,'fp':fp,'fn':fn,'f1':2*tp/(2*tp+fp+fn),'n':len(pred)})
# Check stale Makefile targets without executing pipelines.
print('missing_make_targets',[str(p) for p in map(Path,['scripts/deep_verification_battery.py','scripts/intensive_academic_verification.py','scripts/academic_integrity_guard.py','scripts/verify_contamination_audit.py','scripts/reproduce.py']) if not p.exists()])
