"""Dissent evaluation under incomplete member-level observation.

Observed-case scores are descriptive of labeled cells, not estimates for missing
votes. Bounds enumerate logically possible completions without a missing-at-random
assumption. They are identification bounds, not confidence intervals.
"""
from collections import Counter
from datetime import date
from itertools import product
from math import prod


def adjudicated_targets(panel, channel, *, strict_stance=False):
    """Keep literal ballots, rate-choice differences and formal stance separate."""
    if channel not in ('literal_rate_no', 'rate_choice_disagreement', 'formal_stance_disagreement'):
        raise ValueError('Unknown target channel')
    if type(strict_stance) is not bool or (strict_stance and channel != 'formal_stance_disagreement'):
        raise ValueError('Strict stance sensitivity applies only to formal stance')
    targets = []
    for meeting in panel['meetings']:
        members = {}
        for member in meeting['members']:
            identity = member['member_id']
            if identity in members:
                raise ValueError('Duplicate source member')
            if channel == 'literal_rate_no':
                value = member['literal_rate_ballot']['value']
                if value not in (None, 'Yes', 'No'):
                    raise ValueError('Unknown literal rate ballot')
                target = None if value is None else value == 'No'
            elif channel == 'rate_choice_disagreement':
                target = member['rate_magnitude_disagreement']['value']
            else:
                vote = member['formal_stance_vote']
                value = vote.get('strict_narrative_sensitivity_value', vote['value']) if strict_stance else vote['value']
                target = None if value is None else value != meeting['actual_stance']
            if target is not None and type(target) is not bool:
                raise ValueError('Dissent target must be observed boolean or unknown')
            members[identity] = target
        targets.append({'meeting_date':meeting['meeting_date'], 'member_targets':members})
    _truth_index(targets)
    return targets


def _truth_index(truth):
    if not truth:
        raise ValueError('Empty target panel')
    result = {}
    for row in truth:
        day = row['meeting_date']
        if date.fromisoformat(day).isoformat() != day or day in result:
            raise ValueError('Invalid or duplicate meeting')
        targets = row['member_targets']
        if not isinstance(targets, dict) or not targets:
            raise ValueError('A nonempty planned roster is required')
        if any(not isinstance(k, str) or not k.strip() or (v is not None and type(v) is not bool)
               for k,v in targets.items()):
            raise ValueError('Targets require unique member IDs and boolean-or-null values')
        result[day] = targets
    if list(result) != sorted(result):
        raise ValueError('Target meetings must be chronological')
    return result


def _scores(tp, fp, fn, tn):
    positives = tp + fn
    return {'true_positive':tp, 'false_positive':fp, 'false_negative':fn, 'true_negative':tn,
            'observed_positive':positives, 'precision':tp/(tp+fp) if tp+fp else None,
            'recall':tp/positives if positives else None,
            'f1':2*tp/(2*tp+fp+fn) if positives else None}


def _completion_bounds(tp, fp, fn, tn, unknown_predicted_positive, unknown_predicted_negative):
    """Sharp micro-score bounds; undefined completions are reported separately."""
    up, un = unknown_predicted_positive, unknown_predicted_negative
    known_positives = tp + fn
    possible_positives = known_positives + up + un
    precision_bounds = ([tp/(tp+fp+up), (tp+up)/(tp+fp+up)] if tp+fp+up else None)
    if not possible_positives:
        recall_bounds = f1_bounds = None
    else:
        # Over completions with at least one actual positive. If only unknown
        # predicted-positive cells can supply that positive, one must be positive.
        low_tp, low_fp, low_fn = tp, fp+up, fn+un
        if low_tp+low_fn == 0:
            low_tp, low_fp = 1, fp+up-1
        high_tp, high_fp, high_fn = tp+up, fp, fn
        if high_tp+high_fn == 0:
            high_fn = 1
        recall_bounds = [low_tp/(low_tp+low_fn), high_tp/(high_tp+high_fn)]
        f1_bounds = [2*low_tp/(2*low_tp+low_fp+low_fn), 2*high_tp/(2*high_tp+high_fp+high_fn)]
    return {'precision':precision_bounds, 'recall_given_positive_truth':recall_bounds,
            'f1_given_positive_truth':f1_bounds,
            'some_completions_have_no_positive_truth':known_positives==0,
            'all_completions_have_no_positive_truth':possible_positives==0,
            'interpretation':'Sharp logical bounds across missing-label completions; not confidence intervals or an assumption of random missingness'}


def evaluate_observed_dissent(predictions, truth):
    """One prediction per meeting; never pool stochastic replicates as meetings.

    Each prediction has meeting_date and predicted_dissenters. Every known target
    is boolean, every unobserved member target is explicitly None. Extra/missing
    meetings and predicted identities outside the planned roster are errors.
    """
    targets = _truth_index(truth)
    by_day = {}
    for row in predictions:
        day = row['meeting_date']
        if day in by_day or day not in targets:
            raise ValueError('Duplicate or unplanned prediction meeting')
        ids = row['predicted_dissenters']
        if not isinstance(ids, (list, tuple)) or any(not isinstance(m, str) for m in ids):
            raise ValueError('Predicted dissenters must be a member-ID sequence')
        if len(ids) != len(set(ids)) or set(ids)-set(targets[day]):
            raise ValueError('Duplicate or outside-roster predicted dissenter')
        by_day[day] = set(ids)
    if set(by_day) != set(targets):
        raise ValueError('Missing prediction meeting')
    total, complete = Counter(), Counter()
    rows, complete_dates, complete_exact = [], [], 0
    for day, members in targets.items():
        cells = Counter()
        for member, value in members.items():
            predicted = member in by_day[day]
            key = ('unknown_predicted_positive' if predicted else 'unknown_predicted_negative') if value is None else (
                'tp' if predicted and value else 'fp' if predicted else 'fn' if value else 'tn')
            cells[key] += 1
        total.update(cells)
        if not cells['unknown_predicted_positive']+cells['unknown_predicted_negative']:
            complete_dates.append(day)
            complete.update(cells)
            complete_exact += cells['fp']+cells['fn']==0
        rows.append({'meeting_date':day, 'roster_size':len(members), **dict(cells)})
    counts = [total[k] for k in ('tp','fp','fn','tn')]
    observed = sum(counts)
    unknown = total['unknown_predicted_positive']+total['unknown_predicted_negative']
    return {'n_meetings':len(targets), 'n_member_targets':observed+unknown,
            'observed_targets':observed, 'unknown_targets':unknown,
            'observed_fraction':observed/(observed+unknown), 'observed_case':_scores(*counts),
            'complete_meetings':complete_dates,
            'complete_case':_scores(*(complete[k] for k in ('tp','fp','fn','tn'))),
            'complete_meeting_exact_match_pct':100*complete_exact/len(complete_dates) if complete_dates else None,
            'completion_bounds':_completion_bounds(*counts, total['unknown_predicted_positive'], total['unknown_predicted_negative']),
            'meeting_counts':rows,
            'scope':'Observed-case and complete-case descriptive scores with explicit missingness; no population-generalization or empirical-superiority verdict'}


def paired_f1_completion_bounds(first_predictions, second_predictions, truth, *, max_states=250000):
    """Sharp F1 difference bounds under the SAME completions for both predictors.

    Missing cells are grouped by the two prediction bits. Enumerating possible
    positive counts in four groups suffices; enumerating all 2^missing assignment
    vectors is unnecessary. No probability is assigned to these possibilities.
    """
    first = evaluate_observed_dissent(first_predictions,truth)
    second = evaluate_observed_dissent(second_predictions,truth)
    first_sets = {r['meeting_date']:set(r['predicted_dissenters']) for r in first_predictions}
    second_sets = {r['meeting_date']:set(r['predicted_dissenters']) for r in second_predictions}
    unknown = Counter()
    for row in truth:
        for member,value in row['member_targets'].items():
            if value is None:
                unknown[member in first_sets[row['meeting_date']],member in second_sets[row['meeting_date']]] += 1
    groups = [(bits,count) for bits,count in sorted(unknown.items())]
    states = prod(count+1 for _,count in groups)
    if type(max_states) is not int or max_states<1 or states>max_states:
        raise ValueError('Paired missing-label completion state limit exceeded')
    low = high = None
    valid = 0
    for positives in product(*(range(count+1) for _,count in groups)):
        scores = []
        for index,record in enumerate((first['observed_case'],second['observed_case'])):
            tp,fp,fn = (record[k] for k in ('true_positive','false_positive','false_negative'))
            for ((bits,count),amount) in zip(groups,positives):
                if bits[index]:
                    tp += amount;fp += count-amount
                else:
                    fn += amount
            scores.append(2*tp/(2*tp+fp+fn) if tp+fn else None)
        if scores[0] is not None:
            difference = scores[0]-scores[1]
            low = difference if low is None else min(low,difference)
            high = difference if high is None else max(high,difference)
            valid += 1
    observed = (first['observed_case']['f1']-second['observed_case']['f1']
                if first['observed_case']['f1'] is not None else None)
    return {'observed_case_f1_difference':observed,'f1_difference_bounds_given_positive_truth':[low,high] if valid else None,
            'unknown_targets':first['unknown_targets'],'grouped_completion_states':states,
            'positive_truth_completion_states':valid,'some_completions_have_no_positive_truth':valid<states,
            'first_exceeds_second_under_every_positive_truth_completion':low>0 if low is not None else None,
            'scope':'Sharp paired logical bounds with a common target completion; not sampling uncertainty or a hypothesis test'}
