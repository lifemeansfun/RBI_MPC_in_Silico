"""Strong, reproducible historical baselines; only published prior truth is usable."""
from collections import Counter
from datetime import date
import hashlib
import json
from src.validation.metrics import MetricsEvaluator


def fit_dissent_baseline(calibration_truth, cutoff="2023-04-06", *, information_cutoff="2023-04-30"):
    if date.fromisoformat(cutoff).isoformat() != cutoff or date.fromisoformat(information_cutoff).isoformat() != information_cutoff:
        raise ValueError('Baseline cutoffs must be ISO calendar dates')
    if not calibration_truth or any(row['meeting_date'] > cutoff for row in calibration_truth):
        raise ValueError('Holdout or empty truth in calibration')
    if len({row['meeting_date'] for row in calibration_truth}) != len(calibration_truth):
        raise ValueError('Duplicate calibration meeting')
    for row in calibration_truth:
        meeting, publication = date.fromisoformat(row['meeting_date']), date.fromisoformat(row['publication_date'])
        if publication < meeting or row['publication_date'] >= information_cutoff:
            raise ValueError('Calibration labels are unavailable at the declared selection freeze')
    result = {'cutoff': cutoff, 'information_cutoff':information_cutoff,
              'method': 'best constant dissent set per channel by calibration F1 then exact-match',
              'selection_status': 'calibration only; cohort-specific',
              'calibration_hash': hashlib.sha256(json.dumps(calibration_truth, sort_keys=True).encode()).hexdigest()}
    for channel in ('rate_dissenters', 'stance_dissenters'):
        candidates = sorted({tuple(sorted(row[channel])) for row in calibration_truth})
        truth = [row[channel] for row in calibration_truth]
        scored = []
        for candidate in candidates:
            precision, recall, f1, exact = MetricsEvaluator.compute_dissent_f1([candidate] * len(truth), truth)
            scored.append((f1 if f1 is not None else -1, exact, candidate))
        # Lexical tie-break is predetermined and recorded; no evaluation labels used.
        result[channel] = list(max(scored, key=lambda item: (item[0], item[1], tuple(item[2])))[2])
    return result


def baseline_predictions(snapshots, truth, frozen_dissent):
    by_date = {row['meeting_date']: row for row in truth}
    if len(by_date) != len(truth):
        raise ValueError('Duplicate truth meeting')
    rows = []
    for snapshot in snapshots:
        # Entire minutes publication day precedes the meeting-start cutoff.
        cutoff = snapshot.information_cutoff.date().isoformat() if snapshot.information_cutoff else snapshot.meeting_date
        available = sorted([r for r in truth if r['publication_date'] < cutoff], key=lambda r:r['meeting_date'])
        prior = available[-1] if available else None
        for name in ('hold_previous_stance', 'lag_persistence', 'calibration_constant_dissent'):
            rate = prior['actual_rate_bps'] if name == 'lag_persistence' and prior else 0
            stance = prior['actual_stance'] if name == 'lag_persistence' and prior else snapshot.prev_stance
            rate_dissent = prior['rate_dissenters'] if name == 'lag_persistence' and prior else []
            stance_dissent = prior['stance_dissenters'] if name == 'lag_persistence' and prior else []
            if name == 'calibration_constant_dissent':
                if snapshot.meeting_date <= frozen_dissent['cutoff'] or cutoff < frozen_dissent['information_cutoff']:
                    raise ValueError('Fitted baseline evaluated inside calibration')
                rate_dissent, stance_dissent = frozen_dissent['rate_dissenters'], frozen_dissent['stance_dissenters']
            rows.append({'meeting_date':snapshot.meeting_date, 'baseline':name, 'rate_bps':rate,
                         'stance':stance, 'rate_dissenters':list(rate_dissent), 'stance_dissenters':list(stance_dissent),
                         'source_prior_meeting':prior['meeting_date'] if prior else None,
                         'evidence_type':'deterministic_baseline'})
    return rows
