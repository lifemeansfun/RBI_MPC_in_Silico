import guard
import json,csv,hashlib,re,collections
from pathlib import Path
from bs4 import BeautifulSoup
import pdfplumber
out=Path('peer_review_output')
def j(p):return json.loads(Path(p).read_text())
def norm(t):return ' '.join(t.split())
# Independently inspect publication headings and decisive paragraphs from retained truth sources.
truth=j('data/processed/vintage_v3/truth.json'); records=[]
for t in truth:
    p=Path(t['source_file']);soup=BeautifulSoup(p.read_bytes(),'html.parser');text=norm(soup.get_text(' ',strip=True))
    assert hashlib.sha256(p.read_bytes()).hexdigest()==t['source_sha256']
    assert all(norm(e) in text for e in t['resolution_evidence'])
    paragraphs=[norm(p.get_text(' ',strip=True)) for p in soup.find_all('p')]
    excerpts=[s for s in paragraphs if ('voted' in s.lower() or 'vote against' in s.lower() or 'vote to' in s.lower()) and len(s)<1800]
    records.append({'date':t['meeting_date'],'rate':t['actual_rate_bps'],'rate_dissenters':t['rate_dissenters'],'stance_dissenters':t['stance_dissenters'],'source':str(p),'excerpts':excerpts})
(out/'truth_source_excerpts.json').write_text(json.dumps(records,indent=2))
print('Truth source hashes and all declared resolution excerpts verified:',len(records))
for rec in records:
    if rec['date'] in ['2021-08-06','2022-05-04','2023-06-08','2024-06-07']:print(json.dumps(rec))
# Extract selected CPI source tables directly, retaining text for visual/numeric inspection.
rows=list(csv.DictReader(open('research/source_ledgers/cpi_vintages/meeting_cpi_ledger.csv')))
for row in rows:
    if row['decision_date'] not in ['2020-10-09','2022-05-04','2023-08-10','2024-08-08']:continue
    p=Path('research/source_ledgers/cpi_vintages')/row['local_source_file']
    if p.suffix=='.pdf':
        with pdfplumber.open(p) as pdf:text='\n'.join(page.extract_text() or '' for page in pdf.pages)
    else:text=BeautifulSoup(p.read_bytes(),'html.parser').get_text(' ',strip=True)
    (out/('cpi_source_'+row['decision_date']+'.txt')).write_text(text)
    print('CPI',json.dumps({k:row[k] for k in ['decision_date','reference_month','headline_cpi_yoy_pct','cfpi_yoy_pct','documented_release_timestamp_ist','local_source_file']}))
# Independent raw annotation checks; do not run output-mutating annotation generators.
base=Path('research/source_ledgers/expanded_panel_oct08_doublecode');a=j(base/'annotations.json');statements=j(base/'statement_evidence.json');counts=collections.Counter()
def tree(v):
    if isinstance(v,dict):
        if 'raw_html_excerpt' in v:
            raw=(base/'source_snapshot'/v['raw_path']).read_text()
            assert raw[v['raw_character_start']:v['raw_character_end_exclusive']]==v['raw_html_excerpt']
            counts['raw_excerpt_matches']+=1
        for x in v.values():tree(x)
    elif isinstance(v,list):
        for x in v:tree(x)
tree(a);tree(statements)
for m in a['meetings']:
    print('annotation_meeting',m['meeting_id'],'keys',list(m))
    for member in m['members']:
        counts['members']+=1
        for channel in ['reservations','guidance_qualifications']:
            counts[channel+'_'+str(member[channel]['value'])]+=1
print('annotation_counts',json.dumps(counts))
for m in a['meetings']:
    if '2025-06-06' in m['meeting_id'] or '2026-10-07' in m['meeting_id']:
        (out/('annotation_sample_'+m['meeting_id']+'.json')).write_text(json.dumps(m,indent=2))
        print('sample',m['meeting_id'],json.dumps({k:v for k,v in m.items() if k!='members'})[:2500])
# Source-dependent build cannot reproduce from snapshot if required label input was excluded.
print('vintage_builder_required_label_file_exists',Path('results/methodology_audit_2026-10-05/data_adjudicated_truth.json').exists())
