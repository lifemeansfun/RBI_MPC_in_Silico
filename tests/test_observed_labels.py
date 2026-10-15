"""Exhaustive completion oracle and invalid-join controls for missing labels."""
from itertools import product

import pytest

from src.validation.observed_labels import evaluate_observed_dissent, adjudicated_targets, paired_f1_completion_bounds


def panel(values, predicted):
    ids = [f'm{i}' for i in range(len(values))]
    return ([{'meeting_date':'2026-01-01','predicted_dissenters':[ids[i] for i,p in enumerate(predicted) if p]}],
            [{'meeting_date':'2026-01-01','member_targets':dict(zip(ids,values))}])


def test_completion_bounds_match_exhaustive_binary_oracle():
    # All 3^4 observation patterns and 2^4 predictions, then every completion.
    for values in product((True,False,None), repeat=4):
        for predicted in product((True,False), repeat=4):
            result = evaluate_observed_dissent(*panel(values,predicted))
            possibilities = []
            for filling in product((True,False), repeat=values.count(None)):
                missing = iter(filling)
                completed = [next(missing) if v is None else v for v in values]
                possibilities.append(evaluate_observed_dissent(*panel(completed,predicted))['observed_case'])
            bounds = result['completion_bounds']
            for field,key in [('precision','precision'),('recall','recall_given_positive_truth'),('f1','f1_given_positive_truth')]:
                observed = [r[field] for r in possibilities if r[field] is not None]
                assert bounds[key] == ([min(observed),max(observed)] if observed else None)
            assert bounds['some_completions_have_no_positive_truth'] == any(r['observed_positive']==0 for r in possibilities)
            assert bounds['all_completions_have_no_positive_truth'] == all(r['observed_positive']==0 for r in possibilities)


def test_unknown_is_never_a_negative_and_complete_case_is_separate():
    predictions, truth = panel([True,None,False],[True,True,False])
    result = evaluate_observed_dissent(predictions,truth)
    assert result['observed_case']['f1']==1
    assert result['observed_case']['false_positive']==0
    assert result['completion_bounds']['f1_given_positive_truth']==[2/3,1]
    assert result['unknown_targets']==1 and result['complete_meetings']==[]
    assert result['complete_meeting_exact_match_pct'] is None


@pytest.mark.parametrize('fault',['extra_member','duplicate_member','duplicate_meeting','missing_meeting','coerced_label'])
def test_invalid_evaluation_is_rejected(fault):
    predictions,truth = panel([True,None],[False,False])
    if fault=='extra_member': predictions[0]['predicted_dissenters']=['outside']
    if fault=='duplicate_member': predictions[0]['predicted_dissenters']=['m0','m0']
    if fault=='duplicate_meeting': predictions *= 2
    if fault=='missing_meeting': predictions.clear()
    if fault=='coerced_label': truth[0]['member_targets']['m0']=0
    with pytest.raises(ValueError):
        evaluate_observed_dissent(predictions,truth)


def test_literal_yes_and_smaller_cut_are_distinct_targets():
    member = {'member_id':'member','literal_rate_ballot':{'value':'Yes'},
              'rate_magnitude_disagreement':{'value':True},
              'formal_stance_vote':{'value':'neutral','strict_narrative_sensitivity_value':None}}
    source = {'meetings':[{'meeting_date':'2026-01-01','actual_stance':'neutral','members':[member]}]}
    assert adjudicated_targets(source,'literal_rate_no')[0]['member_targets']=={'member':False}
    assert adjudicated_targets(source,'rate_choice_disagreement')[0]['member_targets']=={'member':True}
    assert adjudicated_targets(source,'formal_stance_disagreement')[0]['member_targets']=={'member':False}
    assert adjudicated_targets(source,'formal_stance_disagreement',strict_stance=True)[0]['member_targets']=={'member':None}


def test_paired_bounds_match_exhaustive_common_target_completions():
    for values in product((True,False,None),repeat=3):
        for one in product((True,False),repeat=3):
            for two in product((True,False),repeat=3):
                first,truth = panel(values,one);second,_ = panel(values,two)
                result = paired_f1_completion_bounds(first,second,truth)
                differences = []
                for filling in product((True,False),repeat=values.count(None)):
                    missing = iter(filling)
                    completed = [next(missing) if v is None else v for v in values]
                    a = evaluate_observed_dissent(*panel(completed,one))['observed_case']['f1']
                    b = evaluate_observed_dissent(*panel(completed,two))['observed_case']['f1']
                    if a is not None: differences.append(a-b)
                assert result['f1_difference_bounds_given_positive_truth'] == ([min(differences),max(differences)] if differences else None)


def test_paired_state_limit_is_explicit():
    first,truth = panel([None]*3,[False,False,False]);second,_=panel([None]*3,[True,True,True])
    with pytest.raises(ValueError,match='state limit'):
        paired_f1_completion_bounds(first,second,truth,max_states=1)
