"""Comparator resolution and diagnostic contracts; these are synthetic controls."""

from dataclasses import asdict
from collections import Counter
from itertools import combinations_with_replacement
import json

import pytest

from src.rational.monte_carlo import MonteCarloEngine
from src.rational.taylor_rule import MemberTaylorParameters, SmoothedTaylorRule
from src.schemas.decision_space import RATE_ACTIONS_BPS
from src.schemas.macro_schema import MacroMeetingSnapshot


NEUTRAL = "neutral"
ACCOMMODATIVE = "accommodative"
WITHDRAWAL = "withdrawal_of_accommodation"
FRAGMENTED_RATES = [-50, -25, 0, 25, 35, 50]
FRAGMENTED_STANCES = [NEUTRAL, NEUTRAL, ACCOMMODATIVE, ACCOMMODATIVE, WITHDRAWAL, WITHDRAWAL]


@pytest.fixture
def snapshot():
    return MacroMeetingSnapshot(
        meeting_date="2023-08-10", current_repo_rate_pct=6.0,
        cpi_headline_yoy_pct=4.0, output_gap_pct=0.0,
        us_fed_funds_rate_pct=2.5, prev_stance=NEUTRAL, input_track="synthetic",
    )


@pytest.fixture
def members():
    return [MemberTaylorParameters(f"m{i}", alpha=0.0, beta=0.0, gamma=0.0) for i in range(6)]


class ScriptedRule:
    """Controlled ballot patterns with targets equal to their exact actions."""

    action_set_bps = RATE_ACTIONS_BPS

    def __init__(self, rows):
        self.rows = rows

    def _ballot(self, snapshot, params):
        rates, stances = self.rows[snapshot.intervention.get("draw", 0)]
        index = int(params.member_id[1:])
        return rates[index], stances[index]

    def compute_discrete_action(self, snapshot, params):
        return self._ballot(snapshot, params)

    def compute_continuous_rate(self, snapshot, params):
        rate, _ = self._ballot(snapshot, params)
        return snapshot.current_repo_rate_pct + rate / 100.0


def test_default_reject_retains_all_fragmented_draws_as_missing(snapshot, members):
    rule = ScriptedRule([(FRAGMENTED_RATES, FRAGMENTED_STANCES)] * 3)
    result = MonteCarloEngine(rule, n_draws=3, noise_std_pct=0.0).simulate(snapshot, members, "m0")

    assert result.fragmentation_policy == "reject"
    assert result.resolution_status == "unresolved"
    assert result.n_draws == result.rate_unresolved_draws == result.stance_unresolved_draws == 3
    assert result.rate_accepted_draws == result.stance_accepted_draws == result.jointly_accepted_draws == 0
    assert result.modal_rate_decision_bps is None and result.modal_stance_decision is None
    assert result.rate_distribution_pct == result.stance_distribution_pct == {}
    assert set(result.rate_dissent_probability_by_member.values()) == {None}
    assert set(result.stance_dissent_probability_by_member.values()) == {None}
    assert set(result.dissent_probability_by_member.values()) == {None}
    assert result.probability_denominators["rate_distribution_pct"] == 0
    assert result.probability_denominators["rate_unresolved_probability"] == 3
    assert result.rate_unresolved_probability == result.stance_unresolved_probability == 1.0
    assert result.rate_synthetic_resolution_probability == result.stance_synthetic_resolution_probability == 0.0
    assert result.rate_resolution_method_counts == result.stance_resolution_method_counts == {"unresolved_reject": 3}
    assert result.rate_synthetic_resolution_draws == result.stance_synthetic_resolution_draws == 0
    assert len(result.draw_records) == 3
    assert all(row["rate_dissenters"] is None and row["stance_dissenters"] is None for row in result.draw_records)
    assert result.mean_implied_rate == pytest.approx(6.058333333333333)
    # Missing outcomes remain JSON null, not silently rewritten to a hold or no dissent.
    saved = json.loads(json.dumps(asdict(result), allow_nan=False))
    assert saved["draw_records"][0]["rate_decision_bps"] is None


@pytest.mark.parametrize(
    "policy,expected_rate,expected_stance,rate_method,stance_method",
    [
        ("legacy_synthetic", 0, NEUTRAL, "synthetic_governor_weighted_median", "synthetic_plurality_governor_priority"),
        ("status_quo", 0, WITHDRAWAL, "status_quo", "status_quo"),
    ],
)
def test_fragmented_draws_require_declared_synthetic_policy(
    snapshot, members, policy, expected_rate, expected_stance, rate_method, stance_method,
):
    snapshot.prev_stance = WITHDRAWAL
    rule = ScriptedRule([(FRAGMENTED_RATES, FRAGMENTED_STANCES)] * 2)
    result = MonteCarloEngine(rule, n_draws=2, noise_std_pct=0.0, fragmentation_policy=policy).simulate(snapshot, members, "m0")

    assert result.modal_rate_decision_bps == expected_rate
    assert result.modal_stance_decision == expected_stance
    assert result.resolution_status == "complete"
    assert result.rate_synthetic_resolution_draws == result.stance_synthetic_resolution_draws == 2
    assert result.rate_synthetic_resolution_probability == result.stance_synthetic_resolution_probability == 1.0
    assert result.rate_unresolved_probability == result.stance_unresolved_probability == 0.0
    assert result.rate_unresolved_draws == result.stance_unresolved_draws == 0
    assert result.rate_resolution_method_counts == {rate_method: 2}
    assert result.stance_resolution_method_counts == {stance_method: 2}
    assert result.rate_distribution_pct == {expected_rate: 100.0}
    assert result.stance_distribution_pct == {expected_stance: 100.0}
    assert set(result.probability_denominators.values()) == {2}
    assert all(row["rate_synthetic_resolution"] and row["stance_synthetic_resolution"] for row in result.draw_records)


def test_majority_and_binary_casting_are_accepted_without_synthetic_resolver(snapshot, members):
    rows = [
        ([-25, -25, -25, 25, 25, 25], [NEUTRAL] * 6),
        ([0, 0, 0, 0, 25, 25], [NEUTRAL, NEUTRAL, NEUTRAL, ACCOMMODATIVE, ACCOMMODATIVE, ACCOMMODATIVE]),
    ]
    result = MonteCarloEngine(ScriptedRule(rows), n_draws=2, noise_std_pct=0.0).simulate(snapshot, members, "m0")

    assert result.rate_resolution_method_counts == {"governor_casting_vote_45ZI_8": 1, "majority": 1}
    assert result.stance_resolution_method_counts == {"governor_casting_vote_45ZI_8": 1, "majority": 1}
    assert result.rate_synthetic_resolution_draws == result.stance_synthetic_resolution_draws == 0
    assert result.rate_accepted_draws == result.stance_accepted_draws == result.jointly_accepted_draws == 2
    assert result.rate_distribution_pct == {-25: 50.0, 0: 50.0}
    assert result.modal_rate_decision_bps == -25  # Declared modal tie rule.
    assert result.modal_stance_decision == NEUTRAL
    assert result.rate_dissent_probability_by_member["m4"] == 1.0
    assert result.stance_dissent_probability_by_member["m4"] == 0.5
    assert result.dissent_probability_by_member["m4"] == 1.0


def test_channel_denominators_do_not_count_unknown_as_no_dissent(snapshot, members):
    rows = [
        ([0, 0, 0, 0, 25, 25], FRAGMENTED_STANCES),
        (FRAGMENTED_RATES, [NEUTRAL] * 5 + [ACCOMMODATIVE]),
        ([0, 0, 0, 25, 0, 0], [NEUTRAL] * 4 + [ACCOMMODATIVE] * 2),
        (FRAGMENTED_RATES, FRAGMENTED_STANCES),
    ]
    result = MonteCarloEngine(ScriptedRule(rows), n_draws=4, noise_std_pct=0.0).simulate(snapshot, members, "m0")

    assert result.resolution_status == "partial"
    assert result.rate_accepted_draws == result.stance_accepted_draws == 2
    assert result.rate_unresolved_draws == result.stance_unresolved_draws == 2
    assert result.jointly_accepted_draws == 1
    assert result.probability_denominators == {
        "rate_distribution_pct": 2, "stance_distribution_pct": 2,
        "rate_dissent_probability_by_member": 2, "stance_dissent_probability_by_member": 2,
        "dissent_probability_by_member": 1,
        "rate_unresolved_probability": 4, "stance_unresolved_probability": 4,
        "rate_synthetic_resolution_probability": 4, "stance_synthetic_resolution_probability": 4,
    }
    assert result.rate_unresolved_probability == result.stance_unresolved_probability == 0.5
    assert result.rate_dissent_probability_by_member["m3"] == 0.5
    assert result.rate_dissent_probability_by_member["m4"] == 0.5
    assert result.stance_dissent_probability_by_member["m4"] == 0.5
    assert result.stance_dissent_probability_by_member["m5"] == 1.0
    assert result.dissent_probability_by_member["m3"] == 1.0
    assert result.dissent_probability_by_member["m4"] == 1.0
    assert result.dissent_probability_by_member["m5"] == 1.0
    assert result.rate_distribution_pct == {0: 100.0}  # 100% among two accepted draws only.
    assert result.draw_records[0]["stance_decision"] is None
    assert result.draw_records[1]["rate_decision_bps"] is None
    assert result.draw_records[2]["rate_decision_bps"] == 0
    assert result.draw_records[3]["rate_decision_bps"] is None


def test_resolved_single_channel_keeps_union_unknown(snapshot, members):
    rows = [(FRAGMENTED_RATES, [NEUTRAL] * 6)] * 2
    result = MonteCarloEngine(ScriptedRule(rows), n_draws=2, noise_std_pct=0.0).simulate(snapshot, members, "m0")
    assert result.rate_accepted_draws == result.jointly_accepted_draws == 0
    assert result.stance_accepted_draws == 2
    assert result.modal_rate_decision_bps is None
    assert result.modal_stance_decision == NEUTRAL
    assert set(result.stance_dissent_probability_by_member.values()) == {0.0}
    assert set(result.dissent_probability_by_member.values()) == {None}


@pytest.mark.parametrize(
    "r_star,raw_change,action,saturation", [(1.0, -100.0, -50, "below_menu"),
    (2.0, 0.0, 0, "within_menu"), (2.5, 50.0, 50, "within_menu"), (3.0, 100.0, 50, "above_menu")],
)
def test_real_taylor_targets_and_menu_saturation(snapshot, members, r_star, raw_change, action, saturation):
    rule = SmoothedTaylorRule(r_star_pct=r_star, smoothing_rho=0.0)
    result = MonteCarloEngine(rule, n_draws=3, noise_std_pct=0.0).simulate(snapshot, members, "m0")

    assert result.modal_rate_decision_bps == action
    assert result.mean_implied_rate == pytest.approx(snapshot.current_repo_rate_pct + raw_change / 100.0)
    assert result.continuous_rate_summary_by_member["m0"]["mean_raw_change_bps"] == pytest.approx(raw_change)
    assert result.draw_records[0]["member_raw_changes_bps"]["m0"] == pytest.approx(raw_change)
    assert result.draw_records[0]["member_action_saturation"]["m0"] == saturation
    counts = result.action_saturation_by_member["m0"]
    assert counts[f"{saturation}_draws"] == 3
    assert counts["upper_endpoint_votes"] == (3 if action == 50 else 0)
    assert result.action_saturation_summary["member_draws"] == 18
    assert result.action_saturation_summary["saturated_member_draws"] == (0 if saturation == "within_menu" else 18)
    assert result.noise_basis == "assumed Gaussian sensitivity, not estimated forecast errors"
    assert "fitting provenance is not inferred" in result.member_parameter_basis
    assert result.member_parameters["m0"] == {"member_id": "m0", "alpha": 0.0, "beta": 0.0, "gamma": 0.0}
    assert result.rule_settings["r_star"] == r_star
    assert result.input_observables["current_repo_rate_pct"] == 6.0


def test_seeded_noise_is_reproducible_but_not_fitted_uncertainty(snapshot, members):
    rule = SmoothedTaylorRule(r_star_pct=2.0, smoothing_rho=0.0)
    first = MonteCarloEngine(rule, n_draws=5, noise_std_pct=0.05, seed=12).simulate(snapshot, members, "m0")
    second = MonteCarloEngine(rule, n_draws=5, noise_std_pct=0.05, seed=12).simulate(snapshot, members, "m0")
    other = MonteCarloEngine(rule, n_draws=5, noise_std_pct=0.05, seed=13).simulate(snapshot, members, "m0")
    assert asdict(first) == asdict(second)
    assert first.draw_records != other.draw_records
    assert first.seed == 12 and first.noise_std_pct == 0.05
    assert first.rate_accepted_draws == first.stance_accepted_draws == 5
    assert first.input_snapshot_hash == other.input_snapshot_hash


def test_missing_required_macro_input_fails_before_draws(snapshot):
    snapshot.output_gap_pct = None
    members = [MemberTaylorParameters(f"m{i}") for i in range(6)]
    with pytest.raises(ValueError, match="requires a sourced output gap"):
        MonteCarloEngine(SmoothedTaylorRule(), n_draws=3).simulate(snapshot, members, "m0")


def test_finite_target_summary_does_not_overflow_when_draws_are_summed(snapshot, members):
    class LargeTargetRule:
        action_set_bps = RATE_ACTIONS_BPS

        def compute_continuous_rate(self, snapshot, params):
            return 1e306

        def compute_discrete_action(self, snapshot, params):
            return 50, WITHDRAWAL

    result = MonteCarloEngine(LargeTargetRule(), n_draws=100, noise_std_pct=0.0).simulate(snapshot, members, "m0")
    assert result.mean_implied_rate == pytest.approx(1e306)
    assert result.action_saturation_summary["saturated_member_draws"] == 600
    json.dumps(asdict(result), allow_nan=False)


def test_nonfinite_or_overflowed_continuous_targets_fail_closed(snapshot, members):
    class InvalidTargetRule:
        action_set_bps = RATE_ACTIONS_BPS

        def __init__(self, value):
            self.value = value

        def compute_continuous_rate(self, snapshot, params):
            return self.value

        def compute_discrete_action(self, snapshot, params):
            return 50, WITHDRAWAL

    with pytest.raises(ValueError, match="continuous targets must be finite"):
        MonteCarloEngine(InvalidTargetRule(float("inf")), n_draws=1).simulate(snapshot, members, "m0")
    with pytest.raises(ValueError, match="raw rate changes must be finite"):
        MonteCarloEngine(InvalidTargetRule(1e308), n_draws=1).simulate(snapshot, members, "m0")


def test_invalid_ballots_and_unexpected_aggregation_errors_fail_closed(snapshot, members, monkeypatch):
    invalid = ScriptedRule([([0, 0, 0, 0, 25, 55], FRAGMENTED_STANCES)])
    with pytest.raises(ValueError, match="Rate action must"):
        MonteCarloEngine(invalid, n_draws=1).simulate(snapshot, members, "m0")

    valid = ScriptedRule([(FRAGMENTED_RATES, FRAGMENTED_STANCES)])
    def broken_aggregation(*args, **kwargs):
        raise ValueError("unexpected aggregation failure")
    monkeypatch.setattr("src.rational.monte_carlo.InstitutionalRuleEngine.aggregate_rate_votes", broken_aggregation)
    with pytest.raises(ValueError, match="unexpected aggregation failure"):
        MonteCarloEngine(valid, n_draws=1).simulate(snapshot, members, "m0")


@pytest.mark.parametrize("policy", ["reject", "legacy_synthetic"])
def test_all_rate_tally_classes_and_governor_ballots_match_independent_oracle(snapshot, members, policy):
    # Every tally with a distinguished Governor is represented. Permuting the
    # other five identities cannot change this resolver's committee decision.
    rows, expected, methods = [], [], Counter()
    for governor_vote in RATE_ACTIONS_BPS:
        for other_votes in combinations_with_replacement(RATE_ACTIONS_BPS, 5):
            rates = [governor_vote, *other_votes]
            rows.append((rates, [NEUTRAL] * 6))
            tally = Counter(rates)
            majority = next((action for action, count in tally.items() if count > 3), None)
            if majority is not None:
                winner, method = majority, "majority"
            elif len(tally) == 2 and set(tally.values()) == {3}:
                winner, method = governor_vote, "governor_casting_vote_45ZI_8"
            elif policy == "reject":
                winner, method = None, "unresolved_reject"
            else:
                winner, method = sorted([*rates, governor_vote])[3], "synthetic_governor_weighted_median"
            expected.append(winner)
            methods[method] += 1

    result = MonteCarloEngine(ScriptedRule(rows), n_draws=len(rows), noise_std_pct=0.0,
                             fragmentation_policy=policy).simulate(snapshot, members, "m0")
    assert len(rows) == 3234
    assert [draw["rate_decision_bps"] for draw in result.draw_records] == expected
    assert result.rate_resolution_method_counts == dict(sorted(methods.items()))
    assert result.rate_unresolved_draws == expected.count(None)
    assert result.rate_accepted_draws + result.rate_unresolved_draws == len(rows)
    assert result.stance_accepted_draws == len(rows)
    assert result.jointly_accepted_draws == result.rate_accepted_draws
    assert result.rate_synthetic_resolution_draws == methods["synthetic_governor_weighted_median"]
    for row, expected_winner in zip(result.draw_records, expected):
        if expected_winner is None:
            assert row["rate_dissenters"] is None
        else:
            assert row["rate_dissenters"] == [member for member, vote in row["member_rate_votes"].items()
                                              if vote != expected_winner]


@pytest.mark.parametrize("policy", ["reject", "legacy_synthetic", "status_quo"])
def test_all_stance_tally_classes_and_governor_ballots_match_independent_oracle(snapshot, members, policy):
    rows, expected, methods = [], [], Counter()
    stances = (NEUTRAL, ACCOMMODATIVE, WITHDRAWAL)
    for governor_vote in stances:
        for other_votes in combinations_with_replacement(stances, 5):
            votes = [governor_vote, *other_votes]
            rows.append(([0] * 6, votes))
            tally = Counter(votes)
            majority = next((action for action, count in tally.items() if count > 3), None)
            if majority is not None:
                winner, method = majority, "majority"
            elif len(tally) == 2 and set(tally.values()) == {3}:
                winner, method = governor_vote, "governor_casting_vote_45ZI_8"
            elif policy == "reject":
                winner, method = None, "unresolved_reject"
            elif policy == "status_quo":
                winner, method = snapshot.prev_stance, "status_quo"
            else:
                top_count = max(tally.values())
                top_choices = [action for action, count in tally.items() if count == top_count]
                winner = top_choices[0] if len(top_choices) == 1 else governor_vote
                method = "synthetic_plurality_governor_priority"
            expected.append(winner)
            methods[method] += 1

    result = MonteCarloEngine(ScriptedRule(rows), n_draws=len(rows), noise_std_pct=0.0,
                             fragmentation_policy=policy).simulate(snapshot, members, "m0")
    assert len(rows) == 63
    assert [draw["stance_decision"] for draw in result.draw_records] == expected
    assert result.stance_resolution_method_counts == dict(sorted(methods.items()))
    assert result.stance_unresolved_draws == expected.count(None)
    assert result.stance_accepted_draws + result.stance_unresolved_draws == len(rows)
    assert result.rate_accepted_draws == len(rows)
    assert result.jointly_accepted_draws == result.stance_accepted_draws
    assert result.stance_synthetic_resolution_draws == sum(count for method, count in methods.items()
                                                         if method not in ("majority", "governor_casting_vote_45ZI_8", "unresolved_reject"))


@pytest.mark.parametrize("kwargs", [{"fragmentation_policy": "implicit"}, {"n_draws": 0},
    {"noise_std_pct": float("nan")}, {"noise_std_pct": True}, {"seed": True}, {"seed": -1}])
def test_invalid_simulation_contract_is_rejected(kwargs):
    with pytest.raises(ValueError):
        MonteCarloEngine(SmoothedTaylorRule(), **kwargs)
