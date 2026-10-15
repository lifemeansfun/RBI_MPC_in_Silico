"""Retrospective reconciliation; preserve both independently written annotations.

No model output is consulted. Literal ballots, magnitude disagreements, explicit
personal votes and committee-reported preferences remain distinct channels.
"""
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
COLLECTOR = ROOT/'research/source_ledgers/expanded_panel_oct08'
INDEPENDENT = ROOT/'research/source_ledgers/expanded_panel_oct08_doublecode'


def read(path):
    return json.loads(path.read_bytes().decode('utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(name, payload):
    with (HERE/name).open('x') as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def stance(value):
    return value.replace(' ', '_') if isinstance(value, str) else value


def main():
    collector = read(COLLECTOR/'meeting_label_ledger.json')
    independent = read(INDEPENDENT/'annotations.json')
    sources = {r['source_id']:r for r in read(COLLECTOR/'source_catalog.json')['records']}
    for record in independent['sources']:
        left = sources[record['source_id']]
        assert record['sha256'] == left['sha256']
        assert digest(COLLECTOR/left['raw_path']) == record['sha256']
        assert digest(INDEPENDENT/'source_snapshot'/record['raw_path']) == record['sha256']
    evidence_checks = 0
    def verify_evidence(value):
        nonlocal evidence_checks
        if isinstance(value, dict):
            if 'raw_html_excerpt' in value:
                source = sources[value['source_id']]
                assert value['source_sha256'] == source['sha256']
                raw = (COLLECTOR/source['raw_path']).read_bytes().decode('utf-8',errors='replace')
                assert raw[value['raw_character_start']:value['raw_character_end_exclusive']] == value['raw_html_excerpt']
                evidence_checks += 1
            for child in value.values():
                verify_evidence(child)
        elif isinstance(value, list):
            for child in value:
                verify_evidence(child)
    verify_evidence(independent)
    cm = {r['decision_date']:r for r in collector['meetings']}
    cb = {(r['decision_date'],r['member_id']):r for r in collector['member_ballots']}
    agreement, discrepancies, adjudicated = {}, [], []
    seen = set()
    for meeting in independent['meetings']:
        day = meeting['decision_date']; original = cm[day]
        assert date.fromisoformat(day).isoformat() == day and day not in seen
        seen.add(day)
        assert meeting['meeting_start_date'] == original['meeting_start_date']
        assert meeting['committee']['rate_delta_bps'] == original['policy_change_bps']
        assert stance(meeting['committee']['stance']) == original['committee_stance']
        members = []
        for member in meeting['members']:
            first = cb[day,member['member_id']]
            comparisons = {
                'literal_rate_ballot':(first['published_rate_vote_cell'],member['literal_rate_ballot']['value']),
                'exact_rate_choice':(first['preferred_rate_change_bps'],member['final_member_rate_choice_delta_bps']['value']),
                'rate_choice_disagreement':(first['rate_choice_disagrees_with_resolution'],member['exact_rate_choice_differs_from_committee']['value']),
                'formal_stance_vote':(first['explicit_formal_stance_vote'],member['formal_stance_vote']['value']),
                'personal_stance_preference':(first['stated_stance_preference'],member['expressed_final_stance_preference']['value']),
            }
            resolved_vote = member['formal_stance_vote']
            for field,(left,right) in comparisons.items():
                count = agreement.setdefault(field,{'entries':0,'equal_including_missing':0,'both_observed_equal':0,'differences':0})
                count['entries'] += 1; count['equal_including_missing'] += left==right
                count['both_observed_equal'] += left==right and left is not None
                count['differences'] += left!=right
                if left != right:
                    record = {'meeting_date':day,'member_id':member['member_id'],'field':field,
                              'collector_value':left,'independent_value':right,
                              'collector_evidence':first['formal_stance_excerpts'] if field=='formal_stance_vote' else first['stance_position_source_excerpts']}
                    if field == 'formal_stance_vote':
                        # Both text passages explicitly connect a vote for status
                        # quo to the stance. This is contextual vote evidence, not
                        # a literal Yes/No cell or mere collective agreement.
                        passages = first['formal_stance_excerpts']
                        assert len(passages)==1 and 'stance' in passages[0]['text'].lower()
                        assert 'i vote for' in passages[0]['text'].lower() and 'status quo' in passages[0]['text'].lower()
                        assert left == original['committee_stance'] == 'neutral'
                        prior = [r for r in collector['meetings'] if r['decision_date']<day]
                        assert prior and prior[-1]['committee_stance']=='neutral'
                        resolved_vote = {'value':'neutral','status':'adjudicated_explicit_contextual_personal_vote',
                                         'literal_yes_no_ballot':None,'evidence':passages,
                                         'referent_prior_meeting':prior[-1]['decision_date'],
                                         'strict_narrative_sensitivity_value':None}
                        record.update(adjudicated_value='neutral',resolution='Explicit personal status-quo vote names the stance; retain an alternative strict-narrative value of null and the preceding stance referent')
                    else:
                        assert day=='2026-10-07' and member['committee_reported_stance_preference']['value']==left
                        record.update(adjudicated_value=None,resolution='Resolution-reported named preference remains in its own channel; a personal statement is unavailable')
                    discrepancies.append(record)
            members.append({
                'member_id':member['member_id'],'member_name':first['member_name'],
                'literal_rate_ballot':member['literal_rate_ballot'],
                'final_rate_choice_bps':member['final_member_rate_choice_delta_bps'],
                'rate_magnitude_disagreement':member['exact_rate_choice_differs_from_committee'],
                'rate_direction_disagreement':member['rate_direction_differs_from_committee'],
                'formal_stance_vote':resolved_vote,
                'collective_stance_decision_narrative':member['all_member_stance_decision_narrative'],
                'committee_reported_stance_preference':member['committee_reported_stance_preference'],
                'personal_stance_preference':member['expressed_final_stance_preference'],
                'prior_reservations':member['reservations'],'guidance_qualifications':member['guidance_qualifications'],
                'personal_statement_available':member['statement_record_available'],
            })
        assert len(members)==6 and len({r['member_id'] for r in members})==6
        adjudicated.append({'meeting_date':day,'meeting_start_date':meeting['meeting_start_date'],
                            'information_cutoff':original['information_cutoff_exclusive_ist'],
                            'actual_rate_bps':original['policy_change_bps'],
                            'actual_stance':original['committee_stance'],
                            'minutes_source_id':meeting['minutes_source_id'],
                            'minutes_publication_date':original['minutes_publication_date'],
                            'resolution_source_id':meeting['resolution_source_id'],
                            'members':members,'outcome_evidence':meeting['committee']['outcome_evidence']})
    assert set(seen)==set(cm) and len(adjudicated)==13
    flat = [r for m in adjudicated for r in m['members']]
    counts = {'meetings':len(adjudicated),'member_meetings':len(flat),
              'literal_rate_ballots_observed':sum(r['literal_rate_ballot']['value'] is not None for r in flat),
              'literal_no_rate_ballots':sum(r['literal_rate_ballot']['value']=='No' for r in flat),
              'exact_rate_choice_disagreements':sum(r['rate_magnitude_disagreement']['value'] is True for r in flat),
              'formal_stance_votes_observed':sum(r['formal_stance_vote']['value'] is not None for r in flat),
              'formal_stance_votes_observed_strict_sensitivity':sum(r['formal_stance_vote']['value'] is not None and r['formal_stance_vote']['status']!='adjudicated_explicit_contextual_personal_vote' for r in flat),
              'formal_stance_meetings_with_all_six_observed':sum(all(r['formal_stance_vote']['value'] is not None for r in m['members']) for m in adjudicated),
              'stance_menu_not_supported_by_current_simulator':sorted({m['actual_stance'] for m in adjudicated}-{'neutral','accommodative','withdrawal_of_accommodation'}),
              'rate_direction_counts':dict(Counter('hold' if m['actual_rate_bps']==0 else 'cut' if m['actual_rate_bps']<0 else 'hike' for m in adjudicated))}
    provenance = {'collector_annotation_sha256':digest(COLLECTOR/'meeting_label_ledger.json'),
                  'independent_annotation_sha256':digest(INDEPENDENT/'annotations.json'),
                  'source_catalog_sha256':digest(COLLECTOR/'source_catalog.json'),
                  'generator_sha256':digest(Path(__file__)),
                  'same_primary_source_hashes_checked':len(independent['sources']),
                  'exact_independent_raw_fragments_rechecked':evidence_checks}
    write_new('comparison.json',{'agreement':agreement,'discrepancies':discrepancies,'provenance':provenance})
    write_new('adjudicated_labels.json',{'schema_version':1,'panel_role':'exposed retrospective source-label evidence',
              'annotation_status':'two source passes plus parent adjudication; not an independent consensus gold standard',
              'primary_stance_definition':'Explicit named or personal vote narrative, including an explicit status-quo vote naming stance',
              'sensitivity_stance_definition':'Independent strict narrative annotation excluding the two contextual status-quo votes',
              'unknown_policy':'Null remains unobserved; never convert unknown votes, reservations or guidance to negative labels',
              'source_availability_limit':'Current retained source bytes; not authenticated historical first availability',
              'counts':counts,'provenance':provenance,'meetings':adjudicated})
    write_new('verification.json',{'status':'passed','counts':counts,'provenance':provenance,
                                  'empirical_model_validation':False,'live_model_calls':0})
    print(json.dumps({'counts':counts,'provenance':provenance},indent=2))


if __name__=='__main__':
    main()
