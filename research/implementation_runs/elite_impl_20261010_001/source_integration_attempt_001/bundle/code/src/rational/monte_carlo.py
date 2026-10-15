"""
Monte Carlo Simulation Engine for the Rational Benchmark Track.
Perturbs macroeconomic observations with assumed Gaussian noise across N=1,000 draws.
The noise and fragmented-vote resolver are sensitivity assumptions, not fitted truth.
Incorporates defensive numerical guards, NaN/None handling, and bounds checking.
"""

import hashlib
import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from math import fsum
from numbers import Real
from typing import Callable, Sequence

import numpy as np

from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.decision_space import STANCE_ACTIONS, validate_rate_action
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.rule_engine.engine import AggregationResult, InstitutionalRuleEngine

logger = logging.getLogger("rbi_mpc.monte_carlo")


@dataclass
class MonteCarloResult:
    meeting_date: str
    mean_implied_rate: float
    modal_rate_decision_bps: int | None
    modal_stance_decision: str | None
    rate_distribution_pct: dict[int, float]
    stance_distribution_pct: dict[str, float]
    dissent_probability_by_member: dict[str, float | None]
    rate_dissent_probability_by_member: dict[str, float | None]
    stance_dissent_probability_by_member: dict[str, float | None]
    noise_basis: str = "assumed Gaussian sensitivity, not estimated forecast errors"
    fragmentation_policy: str = "reject"
    n_draws: int = 0
    seed: int = 42
    noise_std_pct: float = 0.20
    input_snapshot_hash: str = ""
    input_observables: dict = field(default_factory=dict)
    rule_settings: dict = field(default_factory=dict)
    member_parameters: dict[str, dict] = field(default_factory=dict)
    rate_accepted_draws: int = 0
    stance_accepted_draws: int = 0
    jointly_accepted_draws: int = 0
    rate_unresolved_draws: int = 0
    stance_unresolved_draws: int = 0
    rate_synthetic_resolution_draws: int = 0
    stance_synthetic_resolution_draws: int = 0
    rate_unresolved_probability: float = 0.0
    stance_unresolved_probability: float = 0.0
    rate_synthetic_resolution_probability: float = 0.0
    stance_synthetic_resolution_probability: float = 0.0
    rate_resolution_method_counts: dict[str, int] = field(default_factory=dict)
    stance_resolution_method_counts: dict[str, int] = field(default_factory=dict)
    probability_denominators: dict[str, int] = field(default_factory=dict)
    resolution_status: str = "unspecified_legacy"
    probability_basis: str = (
        "Distributions and dissent are conditional on accepted draws in their named channel; "
        "union dissent requires both channels. Unresolved draws remain recorded and counted."
    )
    member_parameter_basis: str = "caller-supplied coefficients; fitting provenance is not inferred"
    modal_tie_policy: str = "smallest rate action; lexicographically first stance"
    continuous_rate_summary_by_member: dict[str, dict[str, float]] = field(default_factory=dict)
    action_saturation_by_member: dict[str, dict[str, int | float]] = field(default_factory=dict)
    action_saturation_summary: dict[str, int | float | str] = field(default_factory=dict)
    draw_records: list[dict] = field(default_factory=list)


def _resolve_channel(
    aggregate: Callable[[], AggregationResult], votes: dict, fragmentation_policy: str,
) -> AggregationResult | None:
    """Keep declared rejection as an unresolved draw; all other failures propagate.

    The caller has already validated identities and ballot domains. Only the
    known fragmented-ballot rejection may become missing, never an invalid vote,
    arithmetic failure or synthetic policy failure.
    """
    try:
        return aggregate()
    except ValueError as exc:
        tally = Counter(votes.values())
        fragmented = max(tally.values()) <= len(votes) / 2 and not (
            len(tally) == 2 and len(set(tally.values())) == 1
        )
        expected = "No majority or Governor-resolvable binary equality; declare a synthetic resolution policy"
        if fragmentation_policy == "reject" and fragmented and str(exc) == expected:
            return None
        raise


def _conditional_probabilities(counts: dict[str, int], denominator: int) -> dict[str, float | None]:
    return {member: count / denominator if denominator else None for member, count in counts.items()}


def _finite_mean(values: list[float]) -> float:
    # Divide before summation so a finite target mean does not overflow from N draws.
    try:
        mean = fsum(value / len(values) for value in values)
    except OverflowError as exc:
        raise ValueError("Monte Carlo means must be finite") from exc
    if not np.isfinite(mean):
        raise ValueError("Monte Carlo means must be finite")
    return mean


def _outcome_distribution(decisions: list) -> tuple[dict, int | str | None]:
    tally = dict(sorted(Counter(decisions).items()))
    if not tally:
        return {}, None
    distribution = {action: count / len(decisions) * 100.0 for action, count in tally.items()}
    return distribution, max(tally, key=tally.get)


class MonteCarloEngine:
    """Orchestrates noisy Monte Carlo draws and statistical aggregation with defensive validation."""

    def __init__(
        self,
        taylor_rule: SmoothedTaylorRule,
        n_draws: int = 1000,
        noise_std_pct: float = 0.20,
        seed: int = 42,
        *,
        fragmentation_policy: str = "reject",
    ):
        if (type(n_draws) is not int or n_draws < 1 or isinstance(noise_std_pct, bool)
                or not isinstance(noise_std_pct, Real) or not np.isfinite(noise_std_pct) or noise_std_pct < 0):
            raise ValueError("Monte Carlo needs positive integer draws and finite nonnegative noise")
        if type(seed) is not int or seed < 0:
            raise ValueError("Monte Carlo seed must be a nonnegative integer")
        if fragmentation_policy not in ("reject", "legacy_synthetic", "status_quo"):
            raise ValueError("Unknown Monte Carlo fragmentation policy")
        self.rule = taylor_rule
        self.n_draws = n_draws
        self.noise_std = float(noise_std_pct)
        self.seed = seed
        self.fragmentation_policy = fragmentation_policy

    def simulate(
        self,
        snapshot: MacroMeetingSnapshot,
        member_params: Sequence[MemberTaylorParameters],
        governor_id: str = "shaktikanta_das",
    ) -> MonteCarloResult:
        """
        Simulate assumed noise with a declared resolver shared by both channels.

        Under ``reject``, a fragmented channel has no decision for that draw.
        Rejection is counted and preserved; it never becomes a hold or a zero
        dissent. Other generation/validation failures still fail closed.
        """
        if len(member_params) != 6:
            raise ValueError(f"Monte Carlo simulation requires exactly 6 members; got {len(member_params)}")
        if len({p.member_id for p in member_params}) != 6 or governor_id not in {p.member_id for p in member_params}:
            raise ValueError("Member parameters need unique IDs including Governor")
        for params in member_params:
            target = self.rule.compute_continuous_rate(snapshot, params)
            if not np.isfinite(target):
                raise ValueError("Monte Carlo continuous targets must be finite")
        # Reject required missing inputs and invalid attendance before any draws.
        InstitutionalRuleEngine.validate_attendance({p.member_id: 0 for p in member_params}, governor_id)

        rng = np.random.default_rng(self.seed)

        base_cpi, base_gap, base_us = snapshot.cpi_headline_yoy_pct, snapshot.output_gap_pct, snapshot.us_fed_funds_rate_pct
        parent_hash = hashlib.sha256(json.dumps(snapshot.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()

        # Generate perturbation vectors
        cpi_noise = rng.normal(0.0, self.noise_std, self.n_draws)
        gap_noise = rng.normal(0.0, self.noise_std * 1.5, self.n_draws)
        us_noise = rng.normal(0.0, self.noise_std * 0.5, self.n_draws)

        rate_decisions: list[int] = []
        stance_decisions: list[str] = []
        member_dissents: dict[str, int] = {p.member_id: 0 for p in member_params}
        rate_dissents = {p.member_id: 0 for p in member_params}
        stance_dissents = {p.member_id: 0 for p in member_params}
        continuous_rates: list[float] = []
        targets_by_member = {p.member_id: [] for p in member_params}
        raw_changes_by_member = {p.member_id: [] for p in member_params}
        saturation_counts = {p.member_id: Counter() for p in member_params}
        rate_methods: Counter = Counter()
        stance_methods: Counter = Counter()
        rate_synthetic = stance_synthetic = jointly_accepted = 0
        records: list[dict] = []
        lower_action, upper_action = min(self.rule.action_set_bps), max(self.rule.action_set_bps)

        for i in range(self.n_draws):
            # Noisy snapshot with clamped bounds
            perturbed_cpi = float(base_cpi + cpi_noise[i])
            perturbed_gap = float(base_gap + gap_noise[i]) if base_gap is not None else None
            perturbed_us = float(np.clip(base_us + us_noise[i], 0, 20)) if base_us is not None else None
            noisy_snap = MacroMeetingSnapshot.model_validate({**snapshot.model_dump(),
                "input_track": "counterfactual", "parent_snapshot_hash": parent_hash,
                "intervention": {"type": "assumed_monte_carlo_noise", "draw": i, "seed": self.seed,
                                 "std_pct": self.noise_std, "fed_bounds": [0, 20]},
                "cpi_headline_yoy_pct": perturbed_cpi, "output_gap_pct": perturbed_gap,
                "us_fed_funds_rate_pct": perturbed_us})

            member_rate_votes: dict[str, int] = {}
            member_stance_votes: dict[str, str] = {}
            draw_targets, draw_changes, draw_saturation = {}, {}, {}

            for p in member_params:
                r_vote, s_vote = self.rule.compute_discrete_action(noisy_snap, p)
                validate_rate_action(r_vote)
                if r_vote not in self.rule.action_set_bps or s_vote not in STANCE_ACTIONS:
                    raise ValueError("Monte Carlo ballots must belong to the declared action domains")
                member_rate_votes[p.member_id] = r_vote
                member_stance_votes[p.member_id] = s_vote
                target = float(self.rule.compute_continuous_rate(noisy_snap, p))
                if not np.isfinite(target):
                    raise ValueError("Monte Carlo continuous targets must be finite")
                raw_change = (target - noisy_snap.current_repo_rate_pct) * 100.0
                if not np.isfinite(raw_change):
                    raise ValueError("Monte Carlo raw rate changes must be finite")
                saturation = "below_menu" if raw_change < lower_action else (
                    "above_menu" if raw_change > upper_action else "within_menu"
                )
                draw_targets[p.member_id], draw_changes[p.member_id] = target, raw_change
                draw_saturation[p.member_id] = saturation
                targets_by_member[p.member_id].append(target)
                raw_changes_by_member[p.member_id].append(raw_change)
                continuous_rates.append(target)
                saturation_counts[p.member_id][saturation] += 1
                saturation_counts[p.member_id]["lower_endpoint_vote"] += int(r_vote == lower_action)
                saturation_counts[p.member_id]["upper_endpoint_vote"] += int(r_vote == upper_action)

            # Full roster and menu fragmentation remain simulator choices.
            rate_res = _resolve_channel(
                lambda: InstitutionalRuleEngine.aggregate_rate_votes(
                    member_rate_votes, governor_id=governor_id, valid_actions=self.rule.action_set_bps,
                    fragmentation_policy=self.fragmentation_policy, prior_action=0,
                ), member_rate_votes, self.fragmentation_policy,
            )
            stance_res = _resolve_channel(
                lambda: InstitutionalRuleEngine.aggregate_stance_votes(
                    member_stance_votes, governor_id=governor_id,
                    fragmentation_policy=self.fragmentation_policy, prior_action=snapshot.prev_stance,
                ), member_stance_votes, self.fragmentation_policy,
            )

            rate_method = rate_res.resolution_policy if rate_res else "unresolved_reject"
            stance_method = stance_res.resolution_policy if stance_res else "unresolved_reject"
            rate_methods[rate_method] += 1
            stance_methods[stance_method] += 1
            if rate_res:
                rate_decisions.append(rate_res.winning_action)
                rate_synthetic += int(rate_res.synthetic_resolution)
                for dissenter in rate_res.dissenting_members:
                    rate_dissents[dissenter] += 1
            if stance_res:
                stance_decisions.append(stance_res.winning_action)
                stance_synthetic += int(stance_res.synthetic_resolution)
                for dissenter in stance_res.dissenting_members:
                    stance_dissents[dissenter] += 1
            if rate_res and stance_res:
                jointly_accepted += 1
                for dissenter in set(rate_res.dissenting_members) | set(stance_res.dissenting_members):
                    member_dissents[dissenter] += 1
            records.append({
                "draw_index": i,
                "perturbed_cpi_pct": perturbed_cpi, "perturbed_output_gap_pct": perturbed_gap,
                "perturbed_fed_pct": perturbed_us,
                "member_continuous_rates_pct": draw_targets,
                "member_raw_changes_bps": draw_changes,
                "member_action_saturation": draw_saturation,
                "member_rate_votes": member_rate_votes, "member_stance_votes": member_stance_votes,
                "rate_decision_bps": rate_res.winning_action if rate_res else None,
                "stance_decision": stance_res.winning_action if stance_res else None,
                "rate_resolution_method": rate_method, "stance_resolution_method": stance_method,
                "rate_synthetic_resolution": rate_res.synthetic_resolution if rate_res else False,
                "stance_synthetic_resolution": stance_res.synthetic_resolution if stance_res else False,
                "rate_dissenters": rate_res.dissenting_members if rate_res else None,
                "stance_dissenters": stance_res.dissenting_members if stance_res else None,
            })

        rate_dist, modal_rate = _outcome_distribution(rate_decisions)
        stance_dist, modal_stance = _outcome_distribution(stance_decisions)
        rate_n, stance_n = len(rate_decisions), len(stance_decisions)
        all_saturation = sum(saturation_counts.values(), Counter())
        member_draws = self.n_draws * len(member_params)
        saturated = all_saturation["below_menu"] + all_saturation["above_menu"]
        resolution_status = "complete" if jointly_accepted == self.n_draws else (
            "unresolved" if rate_n == stance_n == 0 else "partial"
        )

        return MonteCarloResult(
            meeting_date=snapshot.meeting_date,
            mean_implied_rate=_finite_mean(continuous_rates),
            modal_rate_decision_bps=modal_rate,
            modal_stance_decision=modal_stance,
            rate_distribution_pct=rate_dist,
            stance_distribution_pct=stance_dist,
            dissent_probability_by_member=_conditional_probabilities(member_dissents, jointly_accepted),
            rate_dissent_probability_by_member=_conditional_probabilities(rate_dissents, rate_n),
            stance_dissent_probability_by_member=_conditional_probabilities(stance_dissents, stance_n),
            fragmentation_policy=self.fragmentation_policy, n_draws=self.n_draws,
            seed=self.seed, noise_std_pct=self.noise_std, input_snapshot_hash=parent_hash,
            input_observables=snapshot.observable_values(),
            rule_settings={
                "class": f"{type(self.rule).__module__}.{type(self.rule).__qualname__}",
                "action_set_bps": list(self.rule.action_set_bps),
                **{name: getattr(self.rule, name) for name in ("r_star", "pi_star", "rho", "us_neutral_rate")
                   if hasattr(self.rule, name)},
            },
            member_parameters={p.member_id: asdict(p) for p in member_params},
            rate_accepted_draws=rate_n, stance_accepted_draws=stance_n,
            jointly_accepted_draws=jointly_accepted,
            rate_unresolved_draws=self.n_draws - rate_n,
            stance_unresolved_draws=self.n_draws - stance_n,
            rate_synthetic_resolution_draws=rate_synthetic,
            stance_synthetic_resolution_draws=stance_synthetic,
            rate_unresolved_probability=(self.n_draws - rate_n) / self.n_draws,
            stance_unresolved_probability=(self.n_draws - stance_n) / self.n_draws,
            rate_synthetic_resolution_probability=rate_synthetic / self.n_draws,
            stance_synthetic_resolution_probability=stance_synthetic / self.n_draws,
            rate_resolution_method_counts=dict(sorted(rate_methods.items())),
            stance_resolution_method_counts=dict(sorted(stance_methods.items())),
            probability_denominators={
                "rate_distribution_pct": rate_n, "stance_distribution_pct": stance_n,
                "rate_dissent_probability_by_member": rate_n,
                "stance_dissent_probability_by_member": stance_n,
                "dissent_probability_by_member": jointly_accepted,
                "rate_unresolved_probability": self.n_draws,
                "stance_unresolved_probability": self.n_draws,
                "rate_synthetic_resolution_probability": self.n_draws,
                "stance_synthetic_resolution_probability": self.n_draws,
            },
            resolution_status=resolution_status,
            continuous_rate_summary_by_member={member: {
                "mean_rate_pct": _finite_mean(values), "min_rate_pct": min(values), "max_rate_pct": max(values),
                "mean_raw_change_bps": _finite_mean(raw_changes_by_member[member]),
                "min_raw_change_bps": min(raw_changes_by_member[member]),
                "max_raw_change_bps": max(raw_changes_by_member[member]),
            } for member, values in targets_by_member.items()},
            action_saturation_by_member={member: {
                "draws": self.n_draws, "below_menu_draws": counts["below_menu"],
                "above_menu_draws": counts["above_menu"], "within_menu_draws": counts["within_menu"],
                "lower_endpoint_votes": counts["lower_endpoint_vote"],
                "upper_endpoint_votes": counts["upper_endpoint_vote"],
                "saturated_fraction": (counts["below_menu"] + counts["above_menu"]) / self.n_draws,
            } for member, counts in saturation_counts.items()},
            action_saturation_summary={
                "basis": "continuous raw change strictly outside the declared action-menu endpoints",
                "lower_action_bps": lower_action, "upper_action_bps": upper_action,
                "member_draws": member_draws, "below_menu_member_draws": all_saturation["below_menu"],
                "above_menu_member_draws": all_saturation["above_menu"],
                "saturated_member_draws": saturated, "saturated_fraction": saturated / member_draws,
            },
            draw_records=records,
        )
