"""Read-only statistical audit; writes only stat_ outputs beside this script.

Run from repository root: .venv/bin/python results/methodology_audit_2026-10-05/stat_recompute.py
No API access, no fixture regeneration, no production result mutation.
"""
from pathlib import Path
from collections import Counter
import ast
import hashlib
import itertools
import json
import platform
import sys
import numpy as np
import pandas as pd
import scipy
from scipy import stats
import yaml

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from src.validation.metrics import MetricsEvaluator
from src.rule_engine.engine import InstitutionalRuleEngine


def ids(value):
    return set(str(value).split(";")) - {"", "nan"}


def dissent_metrics(pred, true):
    tp = sum(len(p & t) for p, t in zip(pred, true))
    fp = sum(len(p - t) for p, t in zip(pred, true))
    fn = sum(len(t - p) for p, t in zip(pred, true))
    return dict(tp=tp, fp=fp, fn=fn,
                precision=tp / (tp + fp) if tp + fp else None,
                recall=tp / (tp + fn) if tp + fn else None,
                f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
                exact_match=sum(p == t for p, t in zip(pred, true)) / len(true))


def metrics(rate, stance, dissent, truth):
    actual = truth.actual_rate_bps.to_numpy()
    rate = np.asarray(rate)
    classes = sorted(set(np.sign(actual)))
    return dict(n=len(actual), exact_rate=float(np.mean(rate == actual)),
                directional_rate=float(np.mean(np.sign(rate) == np.sign(actual))),
                directional_balanced_accuracy=float(np.mean([
                    np.mean(np.sign(rate)[np.sign(actual) == c] == c) for c in classes])),
                rate_mae_bps=float(np.mean(np.abs(rate - actual))),
                stance=float(np.mean(np.asarray(stance) == truth.actual_stance.to_numpy())),
                **{f"dissent_{k}": v for k, v in dissent_metrics(dissent, [ids(v) for v in truth.actual_dissenters]).items()})


def paired(a, b):
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    only_a = int(np.sum(a & ~b))
    only_b = int(np.sum(~a & b))
    return dict(a_only_correct=only_a, b_only_correct=only_b,
                both_correct=int(np.sum(a & b)), both_wrong=int(np.sum(~a & ~b)),
                difference=float(np.mean(a.astype(int) - b.astype(int))),
                exact_two_sided_mcnemar_p=stats.binomtest(only_a, only_a + only_b).pvalue if only_a + only_b else 1.0)


panel = pd.read_csv(ROOT / "results/tables/meeting_by_meeting_comparison.csv").fillna("")
live = pd.read_csv(ROOT / "results/tables/holdout_meeting_by_meeting_comparison.csv").fillna("")
taylor = pd.read_csv(ROOT / "results/tables/rational_taylor_panel_results.csv").fillna("")
macro = pd.read_parquet(ROOT / "data/processed/macro_panel.parquet")
cal = panel[panel.panel_subset == "calibration"]
majority_rate = int(cal.actual_rate_bps.mode().iloc[0])
majority_stance = cal.actual_stance.mode().iloc[0]
freq = Counter(m for value in cal.actual_dissenters for m in ids(value))
frequent_members = {m for m, count in freq.items() if count / len(cal) >= .5}
lag_rate = [0] + panel.actual_rate_bps.to_list()[:-1]
lag_stance = [str(macro.iloc[0].prev_stance)] + panel.actual_stance.to_list()[:-1]
lag_dissent = [set()] + [ids(v) for v in panel.actual_dissenters.to_list()[:-1]]
summary = {
    "environment": dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
                        numpy=np.__version__, pandas=pd.__version__, scipy=scipy.__version__),
    "calibration_definition": dict(cutoff="2023-04-06", n=len(cal), majority_rate_bps=majority_rate,
                                   majority_stance=majority_stance, frequent_members=sorted(frequent_members),
                                   member_counts=dict(freq)),
    "input_files": {}, "subsets": {}, "paired_tests": {}, "metric_edge_probes": {},
}
for path in ["results/tables/meeting_by_meeting_comparison.csv", "results/tables/holdout_meeting_by_meeting_comparison.csv", "results/tables/rational_taylor_panel_results.csv", "data/processed/macro_panel.parquet"]:
    summary["input_files"][path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()

metric_rows = []
for subset in ["all", "calibration", "holdout"]:
    mask = np.ones(len(panel), bool) if subset == "all" else (panel.panel_subset == subset).to_numpy()
    truth = panel.loc[mask].reset_index(drop=True)
    pos = np.flatnonzero(mask)
    t = taylor.loc[mask]
    predictors = {
        "saved_mock_panel": (truth.sim_rate_bps, truth.sim_stance, [ids(v) for v in truth.sim_dissenters]),
        "always_hold_prev_stance_no_dissent": ([0] * len(truth), macro.loc[mask, "prev_stance"], [set()] * len(truth)),
        "calibration_majority_and_frequent_member": ([majority_rate] * len(truth), [majority_stance] * len(truth), [frequent_members] * len(truth)),
        "lag_previous_observed_decision": ([lag_rate[i] for i in pos], [lag_stance[i] for i in pos], [lag_dissent[i] for i in pos]),
        "always_hold_prev_stance_varma": ([0] * len(truth), macro.loc[mask, "prev_stance"], [{"jayanth_varma"}] * len(truth)),
        "taylor_saved_rate_dissent_probability_ge_0_5": (t.taylor_modal_rate_bps, t.taylor_modal_stance,
            [{m for m, p in ast.literal_eval(v).items() if p >= .5} for v in t.taylor_dissent_probs]),
    }
    if subset == "holdout":
        predictors["saved_live_holdout"] = (live.sim_rate_bps, live.sim_stance, [ids(v) for v in live.sim_dissenters])
    summary["subsets"][subset] = dict(n=len(truth), rate_counts=dict(Counter(map(int, truth.actual_rate_bps))),
                                     stance_counts=dict(Counter(truth.actual_stance)), metrics={})
    for name, (rate, stance, diss) in predictors.items():
        res = metrics(rate, stance, diss, truth)
        summary["subsets"][subset]["metrics"][name] = res
        metric_rows.append(dict(subset=subset, predictor=name, **res))
    base_name = "saved_live_holdout" if subset == "holdout" else "saved_mock_panel"
    base = predictors[base_name]
    for name in ["always_hold_prev_stance_varma", "lag_previous_observed_decision", "taylor_saved_rate_dissent_probability_ge_0_5"]:
        other = predictors[name]
        for target in ["directional_rate", "stance", "dissent_exact"]:
            if target == "directional_rate":
                a = np.sign(np.asarray(base[0])) == np.sign(truth.actual_rate_bps.to_numpy())
                b = np.sign(np.asarray(other[0])) == np.sign(truth.actual_rate_bps.to_numpy())
            elif target == "stance":
                a = np.asarray(base[1]) == truth.actual_stance.to_numpy()
                b = np.asarray(other[1]) == truth.actual_stance.to_numpy()
            else:
                actual = [ids(v) for v in truth.actual_dissenters]
                a = [p == q for p, q in zip(base[2], actual)]
                b = [p == q for p, q in zip(other[2], actual)]
            summary["paired_tests"][f"{subset}/{target}/{base_name}_vs_{name}"] = paired(a, b)

# Match CSVs to stored holdout member ballots and summarize independent Round 1.
transcript_rows = []
round_rows = []
r1_rates, r1_stances, r1_diss = [], [], []
dispersions = []
stance_map = {"accommodative": -1.0, "neutral": 0.0, "withdrawal_of_accommodation": 1.0}
members = ["shaktikanta_das", "michael_patra", "rajiv_ranjan", "shashanka_bhide", "ashima_goyal", "jayanth_varma"]
for row in live.itertuples():
    rep = ROOT / "runs/holdout_live_run/transcripts" / row.meeting_date / "rep_1"
    decision = json.loads((rep / "meeting_outcome.json").read_text())
    member_diss_rate = {v["member_id"] for v in decision["member_votes"] if v["final_rate_vote_bps"] != decision["rate_decision_bps"]}
    member_diss_stance = {v["member_id"] for v in decision["member_votes"] if v["final_stance_vote"] != decision["stance_decision"]}
    rate_votes, stance_votes, stances_by_round = {}, {}, {i: [] for i in range(1, 5)}
    for m in members:
        rounds = [json.loads((rep / f"round_{i}_{m}.json").read_text()) for i in range(1, 5)]
        rate_votes[m] = rounds[0]["proposed_rate_change_bps"]
        stance_votes[m] = rounds[0]["proposed_stance"]
        rr = dict(date=row.meeting_date, member=m)
        for i, data in enumerate(rounds, 1):
            rate_key = "proposed_rate_change_bps" if i == 1 else "final_rate_vote_bps" if i == 4 else "current_rate_preference_bps"
            stance_key = "proposed_stance" if i == 1 else "final_stance_vote" if i == 4 else "current_stance_preference"
            rr[f"r{i}_rate"] = data[rate_key]
            rr[f"r{i}_stance"] = data[stance_key]
            stances_by_round[i].append(stance_map[data[stance_key]])
        round_rows.append(rr)
    agg_rate = InstitutionalRuleEngine.aggregate_rate_votes(rate_votes, governor_id="shaktikanta_das")
    agg_stance = InstitutionalRuleEngine.aggregate_stance_votes(stance_votes, governor_id="shaktikanta_das")
    r1_rates.append(agg_rate.winning_action)
    r1_stances.append(agg_stance.winning_action)
    r1_diss.append(set(agg_rate.dissenting_members) | set(agg_stance.dissenting_members))
    d = [float(np.std(stances_by_round[i], ddof=1)) for i in range(1, 5)]
    dispersions.append(d)
    transcript_rows.append(dict(date=row.meeting_date, files=len(list(rep.glob("*.json"))),
        csv_rate_matches=row.sim_rate_bps == decision["rate_decision_bps"],
        csv_stance_matches=row.sim_stance == decision["stance_decision"],
        csv_union_dissent_matches=ids(row.sim_dissenters) == member_diss_rate | member_diss_stance,
        rate_dissenters=";".join(sorted(member_diss_rate)), stance_dissenters=";".join(sorted(member_diss_stance)),
        r1_aggregate_rate_bps=agg_rate.winning_action, r1_aggregate_stance=agg_stance.winning_action,
        **{f"r{i+1}_stance_std": v for i, v in enumerate(d)}))
summary["holdout_transcript_consistency"] = transcript_rows
summary["holdout_round1_aggregate_metrics"] = metrics(r1_rates, r1_stances, r1_diss, live)
disp = np.array(dispersions)
diffs = disp[:, 0] - disp[:, 2]
nonzero = diffs[np.abs(diffs) > 1e-12]
summary["dispersion_r1_vs_r3"] = dict(mean_by_round=disp.mean(axis=0).tolist(), meeting_paired_differences=diffs.tolist(),
    n_nonzero=int(len(nonzero)), exact_two_sided_sign_p=stats.binomtest(int(np.sum(nonzero > 0)), len(nonzero)).pvalue if len(nonzero) else 1.0)

# Cluster bootstrap resamples meetings (and their six ballots together), not 48 independent members.
true_diss = [ids(v) for v in live.actual_dissenters]
pred_diss = [ids(v) for v in live.sim_dissenters]
base_diss = [{"jayanth_varma"}] * len(live)
counts = lambda preds: np.array([[len(p & t), len(p - t), len(t - p)] for p, t in zip(preds, true_diss)])
live_counts, base_counts = counts(pred_diss), counts(base_diss)
rng = np.random.default_rng(20261005)
idx = rng.integers(0, len(live), (100000, len(live)))
f1_of = lambda c: 2 * c[:, 0] / np.maximum(2 * c[:, 0] + c[:, 1] + c[:, 2], 1)
boot_live = f1_of(live_counts[idx].sum(axis=1))
boot_base = f1_of(base_counts[idx].sum(axis=1))
summary["holdout_f1_bootstrap"] = dict(seed=20261005, repetitions=100000,
    live_percentile_95_ci=np.quantile(boot_live, [.025, .975]).tolist(),
    difference_live_minus_fixed_varma_percentile_95_ci=np.quantile(boot_live - boot_base, [.025, .975]).tolist())
ci = stats.binomtest(8, 8).proportion_ci(method="exact")
summary["iid_binomial_diagnostic_only"] = dict(successes=8, n=8, exact_two_sided_95_ci=[ci.low, ci.high],
    all_successes_min_n_for_95_lower_bound_above_0_75=next(n for n in range(1, 100) if stats.binomtest(n, n).proportion_ci(method="exact").low > .75),
    caveat="Meetings are temporally dependent and all eight share one policy regime; the iid bound is optimistic for broad generalization.")
summary["uniform_rate_randomization_null"] = dict(exact_uniform_five_action_probability=5 ** -8,
    zero_pause_probability_fitted_to_calibration=(float(np.mean(cal.actual_rate_bps == 0))) ** 8,
    true_label_permutations_count_unique=len(set(itertools.permutations(live.actual_rate_bps))),
    constant_hold_classifier_label_permutation_match_probability=1.0,
    explanation="Sampling fresh actions from a uniform distribution is not permuting the observed labels; it tests an artificial null, not added predictive value.")

# Same source metric code can pass panels with no stance matches or silently accept wrong lengths.
def evaluate_case(**kwargs):
    return MetricsEvaluator.evaluate_panel(**kwargs).model_dump()
shared = dict(simulated_rate_actions=[0], ground_truth_rate_actions=[0], simulated_stances=["neutral"],
              ground_truth_stances=["accommodative"], predicted_dissenters=[["jayanth_varma"]],
              ground_truth_dissenters=[["jayanth_varma"]])
summary["metric_edge_probes"]["zero_stance_accuracy_passes_gate"] = evaluate_case(**shared)
summary["metric_edge_probes"]["same_direction_different_size_reported_zero_direction_accuracy"] = evaluate_case(
    **(shared | dict(simulated_rate_actions=[25], ground_truth_rate_actions=[50])))
summary["metric_edge_probes"]["extra_true_rate_silently_ignored"] = evaluate_case(
    **(shared | dict(ground_truth_rate_actions=[0, 50])))
summary["metric_edge_probes"]["dissent_no_positive_truth_or_prediction"] = MetricsEvaluator.compute_dissent_f1([[]], [[]])

# Persona rank audit compares hand-coded ranks; recompute from actual repo dissent frequencies instead.
scores = {yaml.safe_load(p.read_text())["member_id"]: yaml.safe_load(p.read_text())["hawk_dove_score"]
          for p in (ROOT / "personas/2020_2024_roster").glob("*.yaml")}
empirical = {"jayanth_varma": -.8, "ashima_goyal": -.4, "shashanka_bhide": .2,
             "shaktikanta_das": .3, "rajiv_ranjan": .5, "michael_patra": .9}
ordered = list(empirical)
actual_frequency = {m: sum(m in ids(v) for v in panel.actual_dissenters) / (15 if m == "rajiv_ranjan" else 25) for m in ordered}
def corr(a, b):
    tau = stats.kendalltau(a, b)
    rho = stats.spearmanr(a, b)
    # Six members permit complete enumeration, including tie multiplicities.
    permutation_rhos = np.array([stats.spearmanr(a, perm).statistic for perm in itertools.permutations(b)])
    exact_rho_p = float(np.mean(np.abs(permutation_rhos) >= abs(rho.statistic) - 1e-12))
    return dict(kendall_tau=float(tau.statistic), kendall_p=float(tau.pvalue),
                spearman_rho=float(rho.statistic), spearman_asymptotic_p=float(rho.pvalue),
                spearman_exact_two_sided_permutation_p=exact_rho_p, enumerated_permutations=len(permutation_rhos))
summary["persona_correlation"] = dict(scores=scores, hardcoded_empirical=empirical, actual_repo_dissent_frequencies=actual_frequency,
    vs_hardcoded_rank=corr([scores[m] for m in ordered], [empirical[m] for m in ordered]),
    vs_actual_frequency=corr([scores[m] for m in ordered], [-actual_frequency[m] for m in ordered]))

# Explicit sensitivity: distinguish formal ballots from expressed reservations, based on local statements.
# No production label is overwritten. The root review separately verifies official resolution votes.
formal_true = [set()] * 4 + [{"jayanth_varma"}] * 2 + [{"jayanth_varma", "ashima_goyal"}] * 2
summary["holdout_formal_ballot_sensitivity"] = dict(
    status="Sensitivity interpretation from local statement text; verify against official resolution roll calls before adopting labels.",
    union=dissent_metrics(pred_diss, formal_true),
    rate=dissent_metrics([set(ids(r["rate_dissenters"])) for r in transcript_rows], formal_true),
    stance=dissent_metrics([set(ids(r["stance_dissenters"])) for r in transcript_rows], formal_true),
    lag_formal=dissent_metrics([set()] + formal_true[:-1], formal_true))
statement_evidence = []
for date in live.meeting_date:
    for m in ["jayanth_varma", "ashima_goyal"]:
        p = ROOT / "data/processed/statements" / date / f"{m}.txt"
        statement_evidence.append(dict(date=date, member=m, path=str(p.relative_to(ROOT)), statement_end=p.read_text()[-1100:]))
summary["local_statement_endings"] = statement_evidence

pd.DataFrame(metric_rows).to_csv(OUT / "stat_baseline_metrics.csv", index=False)
pd.DataFrame(transcript_rows).to_csv(OUT / "stat_holdout_transcript_checks.csv", index=False)
pd.DataFrame(round_rows).to_csv(OUT / "stat_round_preferences.csv", index=False)
(OUT / "stat_results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({k: summary[k] for k in ["calibration_definition", "subsets", "holdout_round1_aggregate_metrics", "dispersion_r1_vs_r3", "holdout_f1_bootstrap", "iid_binomial_diagnostic_only", "uniform_rate_randomization_null", "metric_edge_probes", "persona_correlation", "holdout_formal_ballot_sensitivity"]}, indent=2))
