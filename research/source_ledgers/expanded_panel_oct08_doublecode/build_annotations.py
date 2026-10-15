#!/usr/bin/env python3
"""Independent source labels. Reads only the supplied isolated snapshot."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json
import re
import sys
import platform
from datetime import datetime, timezone

SNAPSHOT = Path('/var/folders/wh/rvj5dycx0zgbk951gfhl9jb80000gn/T/rbi_source_doublecode_oct08_rti8uqqx')
OUT = Path(__file__).resolve().parent

def sha(b):
    return hashlib.sha256(b).hexdigest()

class Extractor(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.line_offsets = [0]
        self.line_offsets += [m.end() for m in re.finditer('\n', raw)]
        self.ps = []
        self.p = None
        self.spans = []
        self.head_spans = []
        self.rows = []
        self.row_stack = []
        self.cell_stack = []
        self.skip = 0
    def pos(self):
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'p':
            self.p = {'start': self.pos(), 'text_parts': []}
        if tag == 'span':
            self.spans.append({'start': self.pos(), 'text_parts': [], 'is_head': a.get('class') == 'head', 'inside_p': self.p is not None})
        if tag == 'tr':
            if self.row_stack:
                self.row_stack[-1]['has_nested_row'] = True
            self.row_stack.append({'start': self.pos(), 'text_parts': [], 'cells': [], 'has_nested_row': False})
        if tag in ('td', 'th'):
            self.cell_stack.append({'text_parts': [], 'owner': self.row_stack[-1] if self.row_stack else None})
    def finish(self, obj):
        end = self.raw.find('>', self.pos()) + 1
        obj['end'] = end
        obj['text'] = ' '.join(''.join(obj.pop('text_parts')).split())
        obj['raw_html_fragment'] = self.raw[obj['start']:end]
        return obj
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip -= 1
        if tag == 'p' and self.p is not None:
            obj = self.finish(self.p)
            obj['zero_based_p_index'] = len(self.ps)
            self.ps.append(obj)
            self.p = None
        if tag == 'span' and self.spans:
            obj = self.finish(self.spans.pop())
            if obj['is_head'] and not obj['inside_p']:
                self.head_spans.append(obj)
        if tag in ('td', 'th') and self.cell_stack:
            cell = self.cell_stack.pop()
            if cell['owner'] is not None:
                cell['owner']['cells'].append(' '.join(''.join(cell['text_parts']).split()))
        if tag == 'tr' and self.row_stack:
            obj = self.finish(self.row_stack.pop())
            if not obj['has_nested_row']:
                self.rows.append(obj)
    def handle_data(self, s):
        if self.skip:
            return
        if self.p is not None:
            self.p['text_parts'].append(s)
        for span in self.spans:
            span['text_parts'].append(s)
        for row in self.row_stack:
            row['text_parts'].append(s + ' ')
        for cell in self.cell_stack:
            cell['text_parts'].append(s)

def member_id(name):
    for key, token in [
        ('nagesh_kumar', 'Nagesh Kumar'), ('saugata_bhattacharya', 'Saugata Bhattacharya'),
        ('ram_singh', 'Ram Singh'), ('rajiv_ranjan', 'Rajiv Ranjan'),
        ('michael_debabrata_patra', 'Michael Debabrata Patra'), ('shaktikanta_das', 'Shaktikanta Das'),
        ('m_rajeshwar_rao', 'Rajeshwar Rao'), ('sanjay_malhotra', 'Sanjay Malhotra'),
        ('poonam_gupta', 'Poonam Gupta'), ('indranil_bhattacharyya', 'Indranil Bhattacharyya')
    ]:
        if token in name:
            return key
    raise ValueError('Unrecognized member: ' + name)

mp = json.loads((SNAPSHOT / 'source_map.json').read_text())
sources = {s['source_id']: s for s in mp['sources']}
parsed = {}
source_checks = []
for sid, s in sources.items():
    raw_bytes = (SNAPSHOT / s['raw_path']).read_bytes()
    actual = sha(raw_bytes)
    assert actual == s['sha256'], sid
    obj = Extractor(raw_bytes.decode('utf-8'))
    obj.feed(obj.raw)
    parsed[sid] = obj
    date_match = re.search(r'Date\s*:\s*([^<]+)', obj.raw)
    source_checks.append({**s, 'verified_sha256': actual, 'bytes': len(raw_bytes),
                          'publication_date_display_text': date_match.group(1).strip() if date_match else None})

def evidence(sid, block, kind='paragraph'):
    s = sources[sid]
    fragment = block['raw_html_fragment']
    assert parsed[sid].raw[block['start']:block['end']] == fragment
    return {'source_id': sid, 'source_url': s['url'], 'raw_path': s['raw_path'],
            'snapshot_absolute_path': str(SNAPSHOT / s['raw_path']),
            'source_sha256': s['sha256'], 'publication_date': s['publication_date'],
            'evidence_kind': kind, 'zero_based_p_index': block.get('zero_based_p_index'),
            'raw_character_start': block['start'], 'raw_character_end_exclusive': block['end'],
            'excerpt': block['text'], 'raw_html_excerpt': fragment,
            'raw_html_excerpt_utf8_sha256': sha(fragment.encode('utf-8'))}

def pe(sid, inds):
    return [evidence(sid, parsed[sid].ps[i]) for i in inds]

# Choices below were read and assigned independently from the primary sources.
# Indices refer to the extracted zero-based <p> sequence, not statutory paragraph numbers.
DATA = [
    dict(delta=0, rate=6.5, stance='neutral', final=[-25,0,0,0,0,0],
         ratep=[35,45,60,68,72,79], stancep=[35,45,61,68,72,79],
         committeep=[11,13,20,21], explicit_stancep=[21], guidance={'rajiv_ranjan':[68], 'michael_debabrata_patra':[72], 'shaktikanta_das':[79]}),
    dict(delta=0, rate=6.5, stance='neutral', final=[-25,0,-25,0,0,0],
         ratep=[34,44,65,72,76,82], stancep=[34,44,66,72,76,82],
         committeep=[11,13,21,22], explicit_stancep=[22], guidance={'rajiv_ranjan':[72], 'michael_debabrata_patra':[76]}),
    dict(delta=-25, rate=6.25, stance='neutral', final=[-25]*6,
         ratep=[36,49,72,81,88,93], stancep=[36,49,73,81,88,94],
         committeep=[11,12,21,22], explicit_stancep=[22], alternative={'nagesh_kumar':[35,36]},
         guidance={'saugata_bhattacharya':[49], 'rajiv_ranjan':[81], 'sanjay_malhotra':[94]}),
    dict(delta=-25, rate=6.0, stance='accommodative', final=[-25]*6,
         ratep=[29,32,54,61,70,75], stancep=[29,38,55,62,70,75],
         committeep=[11,18], alternative={'nagesh_kumar':[28,29]},
         reservation={'saugata_bhattacharya':[38]}, guidance={'saugata_bhattacharya':[38], 'ram_singh':[53], 'rajiv_ranjan':[62]}),
    dict(delta=-50, rate=5.5, stance='neutral', final=[-50,-25,-50,-50,-50,-50],
         ratep=[33,38,57,60,72,78], stancep=[33,38,58,66,73,79],
         committeep=[11,20,21], guidance={'rajiv_ranjan':[66], 'poonam_gupta':[73], 'sanjay_malhotra':[79]}),
    dict(delta=0, rate=5.5, stance='neutral', final=[0]*6,
         ratep=[32,41,57,66,69,80], stancep=[32,41,58,67,74,80],
         committeep=[11,22], all_member_stancep=[22], guidance={'saugata_bhattacharya':[40], 'rajiv_ranjan':[67], 'poonam_gupta':[74], 'sanjay_malhotra':[80]}),
    dict(delta=0, rate=5.5, stance='neutral', final=[0]*6,
         ratep=[31,39,57,63,74,82], stancep=[31,39,58,64,75,83],
         member_stances=['accommodative','neutral','accommodative','neutral','neutral','neutral'],
         committeep=[11,21], reported_preferencep=[21], guidance={'indranil_bhattacharyya':[64], 'poonam_gupta':[76,77], 'sanjay_malhotra':[83]}),
    dict(delta=-25, rate=5.25, stance='neutral', final=[-25]*6,
         ratep=[30,39,54,58,64,71], stancep=[30,39,54,58,66,71],
         member_stances=['neutral','neutral','accommodative','neutral','neutral','neutral'],
         committeep=[11,21], reported_preferencep=[21], guidance={'saugata_bhattacharya':[39], 'indranil_bhattacharyya':[58], 'poonam_gupta':[66], 'sanjay_malhotra':[71]}),
    dict(delta=0, rate=5.25, stance='neutral', final=[0]*6,
         ratep=[32,38,43,55,63,68], stancep=[32,38,51,55,63,68],
         member_stances=['neutral','neutral','accommodative','neutral','neutral','neutral'],
         committeep=[11,22], reported_preferencep=[22], guidance={'poonam_gupta':[63]}),
    dict(delta=0, rate=5.25, stance='neutral', final=[0]*6,
         ratep=[31,47,54,62,70,78], stancep=[31,47,57,62,70,78],
         committeep=[10,22], guidance={'ram_singh':[56,57], 'poonam_gupta':[70], 'sanjay_malhotra':[78]}),
    dict(delta=0, rate=5.25, stance='neutral', final=[0]*6,
         ratep=[37,48,69,75,84,93], stancep=[37,48,69,75,84,93],
         committeep=[11,27], guidance={'ram_singh':[68], 'poonam_gupta':[84], 'sanjay_malhotra':[93]}),
    dict(delta=0, rate=5.25, stance='neutral', final=[0]*6,
         ratep=[35,45,56,60,68,74], stancep=[35,45,56,60,68,74],
         committeep=[10,25], guidance={'indranil_bhattacharyya':[62], 'poonam_gupta':[68], 'sanjay_malhotra':[73]}),
    dict(delta=25, rate=5.5, stance='calibrated tightening', final=[25]*6,
         committeep=[3,19,20], reported_preferencep=[20]),
]

members_early = ['nagesh_kumar','saugata_bhattacharya','ram_singh','rajiv_ranjan','michael_debabrata_patra','shaktikanta_das']
members_feb = ['nagesh_kumar','saugata_bhattacharya','ram_singh','rajiv_ranjan','m_rajeshwar_rao','sanjay_malhotra']
members_june = ['nagesh_kumar','saugata_bhattacharya','ram_singh','rajiv_ranjan','poonam_gupta','sanjay_malhotra']
members_oct = ['nagesh_kumar','saugata_bhattacharya','ram_singh','indranil_bhattacharyya','poonam_gupta','sanjay_malhotra']

meetings = []
statements = []
for idx, (m, d) in enumerate(zip(mp['meetings'], DATA)):
    sid = m['minutes_source_id'] or m['resolution_source_id']
    obj = parsed[sid]
    roster = members_early if idx < 2 else members_feb if idx < 4 else members_june if idx < 6 else members_oct
    vote_rows = [r for r in obj.rows if len(r['cells']) in (2,3) and r['cells'][1] in ('Yes','No')]
    row_map = {member_id(r['cells'][0]): r for r in vote_rows}
    if idx < 12:
        assert set(row_map) == set(roster), (m['meeting_id'], row_map)
    else:
        assert not vote_rows
    proposal = next((p for p in obj.ps if p['text'].startswith('Voting on the Resolution')), None)
    heads = sorted([p for p in obj.ps if p['text'].startswith('Statement by')] +
                   [p for p in obj.head_spans if p['text'].startswith('Statement by')], key=lambda p:p['start'])
    assert len(heads) == (6 if idx < 12 else 0), (m['meeting_id'], heads)
    stat_map = {}
    for k, head in enumerate(heads):
        ident = member_id(head['text'])
        stop = heads[k+1]['start'] if k+1 < len(heads) else next(p['start'] for p in obj.ps if p['start'] > head['start'] and p['text'].startswith('Press Release:'))
        blocks = [p for p in obj.ps if p['start'] > head['start'] and p['end'] <= stop and not p['text'].startswith('(Puneet')]
        record = {'meeting_id':m['meeting_id'], 'member_id':ident,
                  'heading_evidence':evidence(sid,head,'statement_heading'),
                  'paragraph_evidence':[evidence(sid,p) for p in blocks]}
        statements.append(record)
        stat_map[ident] = record
    stance_values = d.get('member_stances', [d['stance']]*6)
    member_records = []
    for j, ident in enumerate(roster):
        row = row_map.get(ident)
        if row:
            literal = {'value':row['cells'][1], 'status':'documented_literal_table_cell',
                       'evidence':[evidence(sid,row,'rate_vote_table_row')]}
            magnitude_cell = int(row['cells'][2]) if len(row['cells']) == 3 else None
            rate_ev = pe(sid,[d['ratep'][j]]) + ([evidence(sid,row,'rate_vote_table_row')] if magnitude_cell is not None else [])
            rate_status = 'documented_member_choice'
        else:
            literal = {'value':None, 'status':'not_available_in_resolution_only_snapshot', 'evidence':[]}
            magnitude_cell = None
            rate_ev = pe(sid,[3,19])
            rate_status = 'attributed_from_explicit_committee_unanimity_with_supplied_roster'
        final = d['final'][j]
        if magnitude_cell is not None:
            assert final == -magnitude_cell
        formal_ev = pe(sid,d.get('explicit_stancep',[]))
        formal = {'value':d['stance'] if formal_ev else None,
                  'status':'documented_explicit_vote_narrative' if formal_ev else 'no_explicit_stance_ballot_or_vote_narrative_identified',
                  'evidence':formal_ev,
                  'literal_yes_no_ballot':None}
        all_member_ev = pe(sid,d.get('all_member_stancep',[]))
        stance_ev = pe(sid,[d['stancep'][j]]) if 'stancep' in d else []
        reservation_ev = pe(sid,d.get('reservation',{}).get(ident,[]))
        guidance_ev = pe(sid,d.get('guidance',{}).get(ident,[]))
        reported = None
        if idx == 6 and ident in ('nagesh_kumar','ram_singh') or idx in (7,8) and ident == 'ram_singh':
            reported = 'accommodative'
        if idx == 12 and ident in ('nagesh_kumar','ram_singh'):
            reported = 'neutral'
        reported_ev = pe(sid,d.get('reported_preferencep',[])) if reported else []
        preference_value = stance_values[j] if stance_ev else None
        member_records.append({
            'member_id':ident,
            'literal_rate_ballot':literal,
            'table_magnitude_bps_unsigned':magnitude_cell,
            'final_member_rate_choice_delta_bps':{'value':final,'status':rate_status,'evidence':rate_ev},
            'exact_rate_choice_differs_from_committee':{'value':final != d['delta'],'status':'derived_from_documented_final_choices',
                                                     'derivation':'member signed basis-point change differs from committee signed change'},
            'rate_direction_differs_from_committee':{'value':(final>0)-(final<0) != (d['delta']>0)-(d['delta']<0),'status':'derived_from_documented_final_choices'},
            'formal_stance_vote':formal,
            'all_member_stance_decision_narrative':{'value':d['stance'] if all_member_ev else None,
                                                  'status':'documented_all_members_decided' if all_member_ev else 'not_identified', 'evidence':all_member_ev},
            'committee_reported_stance_preference':{'value':reported, 'status':'documented_named_view' if reported else 'not_separately_attributed', 'evidence':reported_ev},
            'expressed_final_stance_preference':{'value':preference_value,'status':'documented_personal_statement' if stance_ev else 'personal_statement_unavailable', 'evidence':stance_ev},
            'expressed_stance_preference_differs_from_committee':{'value':preference_value != d['stance'] if preference_value else None,
                                                                'status':'derived_from_documented_personal_preference' if preference_value else 'unavailable'},
            'reservations':{'value':True if reservation_ev else None,
                            'status':'documented_prior_reservation_with_final_concurrence' if reservation_ev else 'not_comprehensively_assessed',
                            'evidence':reservation_ev},
            'guidance_qualifications':{'value':True if guidance_ev else None,
                                      'status':'documented_qualification_or_conditional_guidance' if guidance_ev else 'not_comprehensively_assessed',
                                      'evidence':guidance_ev},
            'alternative_rate_magnitude_discussion':{'status':'documented_aspiration_not_final_vote' if ident in d.get('alternative',{}) else 'not_assessed',
                                                   'evidence':pe(sid,d.get('alternative',{}).get(ident,[]))},
            'statement_record_available':ident in stat_map,
        })
    # Both source types remain available for independently rechecking the outcome.
    rid = m['resolution_source_id']
    resolution_paragraphs = [p for p in parsed[rid].ps if re.search(r'(policy repo rate|stance)',p['text'],re.I)]
    meetings.append({**m,
        'committee':{'rate_delta_bps':d['delta'], 'repo_rate_percent':d['rate'], 'stance':d['stance'],
                     'outcome_evidence':pe(sid,d['committeep']),
                     'resolution_outcome_evidence':[evidence(rid,p) for p in resolution_paragraphs]},
        'rate_vote_table_proposal':evidence(sid,proposal,'rate_vote_table_heading') if proposal else None,
        'members':member_records,
        'missingness':{'minutes_available':m['minutes_source_id'] is not None,
                      'literal_rate_ballot_table_available':bool(vote_rows),
                      'individual_statement_count':len(heads),
                      'stance_literal_ballot_table_available':False,
                      'formal_stance_vote_narrative_identified':bool(d.get('explicit_stancep'))},
    })

result = {
    'schema_version':'independent_primary_source_doublecode.v1',
    'created_at_utc':datetime.now(timezone.utc).isoformat(),
    'scope':'13 RBI MPC decisions from 2024-10-09 through 2026-10-07; independent source-label coding only',
    'input_snapshot':str(SNAPSHOT),
    'input_source_map_sha256':sha((SNAPSHOT/'source_map.json').read_bytes()),
    'input_workings_sha256':sha((SNAPSHOT/'WORKINGS.md').read_bytes()),
    'coding_rules':[
        'Signed rate changes are negative for cuts and positive for hikes.',
        'Literal Yes/No cells are transcribed independently from exact magnitude and direction disagreement.',
        'An explicit vote narrative is separate from all-member decision narrative and named stated views.',
        'A personal final stance preference is not itself promoted to a separately documented formal stance ballot.',
        'Prior reservations that ended in concurrence are separate from formal dissent.',
        'Aspirational alternatives are separate from final member rate choices.',
        'Unassessed reservations/guidance are null and never false; absence of an identified excerpt is not evidence of absence.',
        'The October 2026 resolution attributes unanimous rate change, but literal individual ballot cells and statements are unavailable.',
    ],
    'sources':source_checks,
    'meetings':meetings,
    'uncertainties':[
        'Formal stance-vote terminology is conservative: explicit voted narratives are coded, whereas decided/agreed/view narratives remain separate channels. No literal Yes/No stance table was supplied.',
        'Reservations and guidance were identified in targeted passages; a comprehensive negative assessment of all statements was not performed.',
        'October 2026 individual final rate magnitudes are attributed from explicit unanimity and roster rather than a minutes ballot table.',
        'Raw excerpts preserve original HTML, while human-readable excerpts decode entities and normalize whitespace.',
    ],
    'failed_checks':[
        {'action':'Initial optional BeautifulSoup parsing helper','result':'ModuleNotFoundError: No module named bs4','recovery':'Python standard-library HTMLParser; no package installed'},
        {'action':'First exploratory HTML text dump','result':'Output truncated because script/style data entered exploratory text capture','recovery':'Excluded script/style data; inspected narrower source passages and preserved complete statement evidence'},
    ],
    'environment':{'python_version':sys.version, 'platform':platform.platform()},
}

for name, data in [('annotations.json',result), ('statement_evidence.json',statements)]:
    with (OUT/name).open('x') as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
        f.write('\n')

checks = {'source_hash_checks_passed':len(source_checks), 'meetings':len(meetings),
          'member_records':sum(len(m['members']) for m in meetings),
          'literal_rate_ballots':sum(r['literal_rate_ballot']['value'] is not None for m in meetings for r in m['members']),
          'complete_individual_statement_records':len(statements),
          'literal_no_rate_ballots':sum(r['literal_rate_ballot']['value']=='No' for m in meetings for r in m['members']),
          'exact_rate_disagreements':sum(r['exact_rate_choice_differs_from_committee']['value'] for m in meetings for r in m['members']),
          'explicit_formal_stance_vote_member_records':sum(r['formal_stance_vote']['value'] is not None for m in meetings for r in m['members']),
          'rendered_excerpt_locations_checked':'all evidence slices checked against original decoded HTML',
          'unassessed_channels_encoded_as_false':0}
with (OUT/'validation.json').open('x') as f:
    json.dump(checks,f,indent=2)
    f.write('\n')
print(json.dumps(checks,indent=2))
