"""
Validation metrics engine for RBI MPC In Silico.
Computes:
1. Directional Rate Accuracy (% matching committee repo rate action)
2. Stance Accuracy (% matching committee policy stance)
3. Member-Level Dissent Detection (Precision, Recall, F1 Score, Exact Match Rate)
"""

from typing import Sequence, Any
from pydantic import BaseModel


class ValidationMetricsSummary(BaseModel):
    total_meetings_evaluated: int
    directional_rate_accuracy_pct: float
    stance_accuracy_pct: float
    dissent_exact_match_rate_pct: float
    dissent_precision: float
    dissent_recall: float
    dissent_f1: float
    passed_validation_gate: bool


class MetricsEvaluator:
    """Computes academic validation metrics against held-out historical panels."""

    @staticmethod
    def compute_dissent_f1(
        predicted_dissenters_list: Sequence[Sequence[str]],
        ground_truth_dissenters_list: Sequence[Sequence[str]],
    ) -> tuple[float, float, float, float]:
        """
        Computes member-level Precision, Recall, F1, and Exact Match Rate.
        """
        tp = 0
        fp = 0
        fn = 0
        exact_matches = 0
        n_meetings = len(predicted_dissenters_list)

        for pred_set_raw, true_set_raw in zip(predicted_dissenters_list, ground_truth_dissenters_list):
            pred = set(pred_set_raw)
            true = set(true_set_raw)

            if pred == true:
                exact_matches += 1

            tp += len(pred.intersection(true))
            fp += len(pred - true)
            fn += len(true - pred)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        exact_rate = (exact_matches / n_meetings * 100.0) if n_meetings > 0 else 0.0

        return round(precision, 4), round(recall, 4), round(f1, 4), round(exact_rate, 2)

    @classmethod
    def evaluate_panel(
        cls,
        simulated_rate_actions: Sequence[int],
        ground_truth_rate_actions: Sequence[int],
        simulated_stances: Sequence[str],
        ground_truth_stances: Sequence[str],
        predicted_dissenters: Sequence[Sequence[str]],
        ground_truth_dissenters: Sequence[Sequence[str]],
        directional_threshold: float = 0.75,
        dissent_f1_threshold: float = 0.50,
    ) -> ValidationMetricsSummary:
        """Evaluates all metrics across a panel of meetings and checks the Validation Gate."""
        n = len(simulated_rate_actions)
        if n == 0:
            raise ValueError("Evaluation requires at least 1 meeting")

        # Rate Accuracy
        matching_rates = sum(
            1 for sim, true in zip(simulated_rate_actions, ground_truth_rate_actions) if sim == true
        )
        rate_accuracy_pct = round(matching_rates / n * 100.0, 2)

        # Stance Accuracy
        matching_stances = sum(
            1 for sim, true in zip(simulated_stances, ground_truth_stances) if sim == true
        )
        stance_accuracy_pct = round(matching_stances / n * 100.0, 2)

        # Dissent Metrics
        precision, recall, f1, exact_rate = cls.compute_dissent_f1(
            predicted_dissenters, ground_truth_dissenters
        )

        passed = (
            (rate_accuracy_pct / 100.0 >= directional_threshold)
            and (f1 >= dissent_f1_threshold)
        )

        return ValidationMetricsSummary(
            total_meetings_evaluated=n,
            directional_rate_accuracy_pct=rate_accuracy_pct,
            stance_accuracy_pct=stance_accuracy_pct,
            dissent_exact_match_rate_pct=exact_rate,
            dissent_precision=precision,
            dissent_recall=recall,
            dissent_f1=f1,
            passed_validation_gate=passed,
        )
