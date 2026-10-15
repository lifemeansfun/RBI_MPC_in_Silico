import guard
import csv,json,collections
from pathlib import Path
rows=list(csv.DictReader(open('research/source_ledgers/expanded_panel_oct08/member_ballot_ledger.csv')))
a=json.loads(Path('research/source_ledgers/expanded_panel_oct08_doublecode/annotations.json').read_text())
print('first_columns',list(rows[0]));print('first_row',rows[0])
print('second_row',{k:v for k,v in a['meetings'][0]['members'][0].items() if k in ['final_member_rate_choice_delta_bps','formal_stance_vote','literal_rate_ballot']})
by={(m['meeting_id'],r['member_id']):r for m in a['meetings'] for r in m['members']}
comparisons=[]
for r in rows:
    b=by[(r['meeting_id'],r['member_id'])]
    comparisons.append({'meeting':r['meeting_id'],'member':r['member_id'],'first':{k:v for k,v in r.items() if 'rate' in k or 'formal_stance' in k},'second':{k:b[k] for k in ['literal_rate_ballot','final_member_rate_choice_delta_bps','formal_stance_vote']}})
Path('peer_review_output/annotation_comparison.json').write_text(json.dumps(comparisons,indent=2))
counts=collections.Counter();disagreements=[]
for r in rows:
    b=by[r['meeting_id'],r['member_id']]
    for left,right,numeric in [('preferred_rate_change_bps','final_member_rate_choice_delta_bps',True),('published_rate_vote_cell','literal_rate_ballot',False),('explicit_formal_stance_vote','formal_stance_vote',False)]:
        x=r[left] or None;y=b[right]['value'];x=int(x) if numeric and x is not None else x
        counts[left+'_equal' if x==y else left+'_different']+=1
        if x!=y:disagreements.append([r['meeting_id'],r['member_id'],left,x,y])
print('compatible_field_agreement',dict(counts));print('disagreements',disagreements)
