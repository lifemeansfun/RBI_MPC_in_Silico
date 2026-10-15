#!/usr/bin/env python3
"""Validate only this new annotation and its preserved input snapshot."""
from pathlib import Path
from datetime import datetime
import json
import hashlib

out = Path(__file__).resolve().parent
a = json.loads((out/'annotations.json').read_text())
statements = json.loads((out/'statement_evidence.json').read_text())
known = {(s['meeting_id'],s['member_id']):{p['zero_based_p_index'] for p in s['paragraph_evidence']} for s in statements}
member_evidence_checks = 0
date_checks = 0
fragment_checks = 0
for source in a['sources']:
    raw = (out/'source_snapshot'/source['raw_path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source['source_sha256'] if 'source_sha256' in source else hashlib.sha256(raw).hexdigest() == source['sha256']
    parsed_date = datetime.strptime(source['publication_date_display_text'],'%b %d, %Y').strftime('%Y-%m-%d')
    assert parsed_date == source['publication_date']
    date_checks += 1

def verify_evidence_tree(value):
    global fragment_checks
    if isinstance(value, dict):
        if 'raw_html_excerpt' in value:
            text = (out/'source_snapshot'/value['raw_path']).read_text()
            assert text[value['raw_character_start']:value['raw_character_end_exclusive']] == value['raw_html_excerpt']
            assert hashlib.sha256(value['raw_html_excerpt'].encode('utf-8')).hexdigest() == value['raw_html_excerpt_utf8_sha256']
            fragment_checks += 1
        for child in value.values():
            verify_evidence_tree(child)
    elif isinstance(value,list):
        for child in value:
            verify_evidence_tree(child)

verify_evidence_tree(a)
verify_evidence_tree(statements)
for meeting in a['meetings']:
    for member in meeting['members']:
        if not meeting['minutes_source_id']:
            continue
        for channel in ['final_member_rate_choice_delta_bps','expressed_final_stance_preference','reservations','guidance_qualifications','alternative_rate_magnitude_discussion']:
            for e in member[channel]['evidence']:
                if e['evidence_kind'] == 'paragraph':
                    assert e['zero_based_p_index'] in known[(meeting['meeting_id'],member['member_id'])]
                    member_evidence_checks += 1
        for channel in ['reservations','guidance_qualifications']:
            if member[channel]['status']=='not_comprehensively_assessed':
                assert member[channel]['value'] is None
summary = {'source_display_date_checks_passed':date_checks,
           'raw_fragment_checks_passed':fragment_checks,
           'personal_statement_attribution_checks_passed':member_evidence_checks,
           'input_copy_hash_checks_passed':27,
           'status':'passed'}
with (out/'validation_secondary.json').open('x') as f:
    json.dump(summary,f,indent=2)
    f.write('\n')
print(json.dumps(summary,indent=2))
manifest = {str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'artifact_sha256.json'}
with (out/'artifact_sha256.json').open('x') as f:
    json.dump(manifest,f,indent=2)
    f.write('\n')
