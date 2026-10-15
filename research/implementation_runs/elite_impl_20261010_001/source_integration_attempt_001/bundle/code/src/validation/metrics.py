"""Aligned, channel-specific predictive metrics and meeting-level paired uncertainty."""
from itertools import product
from typing import Sequence
import math
import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from src.schemas.decision_space import RATE_ACTIONS_BPS, STANCE_ACTIONS


class ValidationMetricsSummary(BaseModel):
    """Descriptive scores; the legacy-named flag is never a scientific verdict."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    total_meetings_evaluated: int = Field(gt=0)
    directional_rate_accuracy_pct: float = Field(ge=0, le=100)
    exact_rate_accuracy_pct: float = Field(ge=0, le=100)
    rate_mae_bps: float = Field(ge=0)
    stance_accuracy_pct: float = Field(ge=0, le=100)
    dissent_exact_match_rate_pct: float = Field(ge=0, le=100)
    dissent_precision: float | None = Field(ge=0, le=1)
    dissent_recall: float | None = Field(ge=0, le=1)
    dissent_f1: float | None = Field(ge=0, le=1)
    rate_dissent_f1: float | None = Field(default=None, ge=0, le=1)
    stance_dissent_f1: float | None = Field(default=None, ge=0, le=1)
    true_positive_dissent_events: int = Field(ge=0)
    observed_positive_dissent_events: int = Field(ge=0)
    rate_class_counts: dict[str, int]
    passed_validation_gate: bool


def _aligned(*sequences):
    lengths = [len(x) for x in sequences]
    if not lengths or not lengths[0] or len(set(lengths)) != 1:
        raise ValueError(f"Evaluation requires nonempty, equal-length aligned inputs: {lengths}")


def _dissent_set(values):
    if isinstance(values, (str, bytes)) or any(not isinstance(x, str) or not x for x in values):
        raise ValueError("Dissent labels must be sequences of nonempty member IDs")
    if len(set(values)) != len(values):
        raise ValueError("Duplicate dissent member ID")
    return set(values)


class MetricsEvaluator:
    @staticmethod
    def compute_dissent_f1(predicted_dissenters_list, ground_truth_dissenters_list):
        _aligned(predicted_dissenters_list, ground_truth_dissenters_list)
        tp = fp = fn = exact = 0
        for pred_values, true_values in zip(predicted_dissenters_list, ground_truth_dissenters_list):
            pred, true = _dissent_set(pred_values), _dissent_set(true_values)
            tp += len(pred & true)
            fp += len(pred - true)
            fn += len(true - pred)
            exact += pred == true
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        # No observed positives: recall/F1 cannot establish detection performance.
        f1 = 2 * tp / (2 * tp + fp + fn) if tp + fn else None
        return precision, recall, f1, exact / len(predicted_dissenters_list) * 100

    @classmethod
    def evaluate_panel(cls, simulated_rate_actions, ground_truth_rate_actions,
                       simulated_stances, ground_truth_stances, predicted_dissenters,
                       ground_truth_dissenters, directional_threshold=.75, dissent_f1_threshold=.50,
                       stance_threshold=.70, *, predicted_rate_dissenters=None, true_rate_dissenters=None,
                       predicted_stance_dissenters=None, true_stance_dissenters=None,
                       exact_rate_threshold=.75, rate_dissent_f1_threshold=.50,
                       stance_dissent_f1_threshold=.50, threshold_contract='channel_v2'):
        _aligned(simulated_rate_actions, ground_truth_rate_actions, simulated_stances,
                 ground_truth_stances, predicted_dissenters, ground_truth_dissenters)
        for rate in [*simulated_rate_actions, *ground_truth_rate_actions]:
            if type(rate) is not int or rate not in RATE_ACTIONS_BPS:
                raise ValueError(f"Invalid rate action {rate}")
        if any(stance not in STANCE_ACTIONS for stance in [*simulated_stances, *ground_truth_stances]):
            raise ValueError("Unknown stance")
        if threshold_contract not in ('union_v1', 'channel_v2'):
            raise ValueError('Unknown descriptive threshold contract')
        if any(type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= 1 for t in
               (directional_threshold, dissent_f1_threshold, stance_threshold, exact_rate_threshold,
                rate_dissent_f1_threshold, stance_dissent_f1_threshold)):
            raise ValueError("Metric thresholds must be finite proportions")
        n = len(simulated_rate_actions)
        sign = lambda x: (x > 0) - (x < 0)
        direction = sum(sign(a) == sign(b) for a, b in zip(simulated_rate_actions, ground_truth_rate_actions)) / n
        exact = sum(a == b for a, b in zip(simulated_rate_actions, ground_truth_rate_actions)) / n
        mae = sum(abs(a - b) for a, b in zip(simulated_rate_actions, ground_truth_rate_actions)) / n
        stance = sum(a == b for a, b in zip(simulated_stances, ground_truth_stances)) / n
        precision, recall, f1, exact_dissent = cls.compute_dissent_f1(predicted_dissenters, ground_truth_dissenters)
        channels = []
        for pred, truth in ((predicted_rate_dissenters, true_rate_dissenters),
                            (predicted_stance_dissenters, true_stance_dissenters)):
            if (pred is None) != (truth is None):
                raise ValueError("Both prediction and truth are required for each dissent channel")
            if pred is not None:
                _aligned(simulated_rate_actions, pred, truth)
            channels.append(cls.compute_dissent_f1(pred, truth)[2] if pred is not None else None)
        if predicted_rate_dissenters is not None and predicted_stance_dissenters is not None:
            for rate, stance_votes, union in (
                (predicted_rate_dissenters, predicted_stance_dissenters, predicted_dissenters),
                (true_rate_dissenters, true_stance_dissenters, ground_truth_dissenters)):
                if any(set(a)|set(b) != set(u) for a,b,u in zip(rate,stance_votes,union)):
                    raise ValueError('Union dissent contradicts its channel labels')
        common = direction >= directional_threshold and stance >= stance_threshold
        if threshold_contract == 'union_v1':
            # Historical version-2 saved studies retain their original descriptive
            # semantics during replay; this contract is not used for new studies.
            threshold_met = common and f1 is not None and f1 >= dissent_f1_threshold
        else:
            threshold_met = common and exact >= exact_rate_threshold and all(
                value is not None and value >= threshold for value,threshold in
                zip(channels,(rate_dissent_f1_threshold,stance_dissent_f1_threshold)))
        return ValidationMetricsSummary(
            total_meetings_evaluated=n, directional_rate_accuracy_pct=100 * direction,
            exact_rate_accuracy_pct=100 * exact, rate_mae_bps=mae, stance_accuracy_pct=100 * stance,
            dissent_exact_match_rate_pct=exact_dissent, dissent_precision=precision,
            dissent_recall=recall, dissent_f1=f1, rate_dissent_f1=channels[0], stance_dissent_f1=channels[1],
            true_positive_dissent_events=sum(len(set(a) & set(b)) for a, b in zip(predicted_dissenters, ground_truth_dissenters)),
            observed_positive_dissent_events=sum(len(x) for x in ground_truth_dissenters),
            rate_class_counts={str(action): sum(x == action for x in ground_truth_rate_actions) for action in RATE_ACTIONS_BPS},
            passed_validation_gate=threshold_met)


def aligned_prediction_join(predictions, truth, keys=("meeting_date",)):
    """Reject duplicates, missing or extra outcomes before computing metrics."""
    if predictions.empty or truth.empty:
        raise ValueError("Empty prediction or truth panel")
    if predictions.duplicated(list(keys)).any() or truth.duplicated(list(keys)).any():
        raise ValueError("Duplicate outcome join key")
    merged = predictions.merge(truth, on=list(keys), how="outer", validate="one_to_one", indicator=True,
                               suffixes=("_prediction", "_truth"))
    if not (merged["_merge"] == "both").all():
        raise ValueError("Missing or extra outcome join keys")
    return merged.drop(columns="_merge")


def paired_meeting_uncertainty(meeting_dates: Sequence[str], model_losses: Sequence[float],
                               baseline_losses: Sequence[float], *, block_size=2, n_resamples=10000, seed=42):
    """Positive difference favors model. One row per meeting; no pseudo-replicate N.

    Circular moving-block bootstrap preserves short temporal dependence. The exact
    sign-flip test additionally assumes symmetric independent meeting differences;
    it is labeled separately and cannot remove serial dependence.
    """
    _aligned(meeting_dates, model_losses, baseline_losses)
    if len(set(meeting_dates)) != len(meeting_dates) or list(meeting_dates) != sorted(meeting_dates):
        raise ValueError("Paired losses must have unique chronological meeting keys")
    delta = np.asarray(baseline_losses, dtype=float) - np.asarray(model_losses, dtype=float)
    if not np.isfinite(delta).all() or block_size < 1 or n_resamples < 100:
        raise ValueError("Invalid uncertainty inputs")
    n = len(delta)
    if n < 2:
        return {"n_meetings": n, "mean_advantage": float(delta.mean()), "ci95": None,
                "sign_flip_pvalue": None, "superiority_supported": False, "reason": "Insufficient meeting clusters"}
    block_size = min(block_size, n)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(n_resamples, math.ceil(n / block_size)))
    indices = (starts[..., None] + np.arange(block_size)) % n
    means = delta[indices.reshape(n_resamples, -1)[:, :n]].mean(axis=1)
    interval = np.quantile(means, [.025, .975]).tolist()
    observed = abs(float(delta.mean()))
    if n <= 18:
        statistics = np.asarray([abs(np.mean(delta * signs)) for signs in product((-1, 1), repeat=n)])
        pvalue = float(np.mean(statistics >= observed - 1e-12))
        test = "exact meeting sign flip (requires exchangeability/symmetry)"
    else:
        statistics = abs((rng.choice((-1, 1), (n_resamples, n)) * delta).mean(axis=1))
        pvalue = float((1 + np.sum(statistics >= observed - 1e-12)) / (n_resamples + 1))
        test = "Monte Carlo meeting sign flip (requires exchangeability/symmetry)"
    return {"n_meetings": n, "mean_advantage": float(delta.mean()), "ci95": interval,
            "bootstrap": "circular temporal-block", "block_size": block_size, "resamples": n_resamples,
            "seed": seed, "sign_flip_pvalue": pvalue, "sign_flip_assumption": test,
            "superiority_supported": interval[0] > 0, "difference_by_meeting": delta.tolist()}


def holm_adjust(pvalues):
    values = np.asarray(pvalues, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
        raise ValueError("Invalid p-values")
    order = np.argsort(values)
    adjusted = np.empty(len(values))
    previous = 0.0
    for rank, index in enumerate(order):
        previous = max(previous, min(1.0, (len(values) - rank) * values[index]))
        adjusted[index] = previous
    return adjusted.tolist()
