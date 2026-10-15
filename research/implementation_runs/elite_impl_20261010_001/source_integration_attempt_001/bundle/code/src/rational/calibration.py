"""Calibration-only bounded Taylor comparator with explicit reduced-input status."""
from dataclasses import dataclass, asdict
import hashlib
import json
from datetime import date
import numpy as np
from scipy.optimize import lsq_linear
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.decision_space import RATE_ACTIONS_BPS


@dataclass(frozen=True)
class FittedTaylorComparator:
    r_star: float
    alpha: float
    beta: float
    gamma: float
    rho: float
    calibration_cutoff: str
    calibration_dates: tuple[str, ...]
    calibration_hash: str
    fit_objective: str
    input_scope: str
    coefficient_bounds: tuple[tuple[float, ...], tuple[float, ...]]
    bootstrap_coefficients: tuple[tuple[float, ...], ...]
    bootstrap_seed: int
    bootstrap_method: str
    bootstrap_block_size: int
    feature_names: tuple[str, ...]
    design_rank: int
    noise_basis: str = "No fitted observation-noise process; deterministic comparator"

    def predict(self, snapshot):
        if snapshot.meeting_date <= self.calibration_cutoff:
            # This is allowed as a fitted diagnostic, never interpreted as heldout accuracy.
            pass
        rule = SmoothedTaylorRule(r_star_pct=self.r_star, smoothing_rho=self.rho)
        params = MemberTaylorParameters("fitted_committee", self.alpha, self.beta, self.gamma)
        return rule.compute_discrete_action(snapshot, params)

    def to_dict(self):
        return asdict(self)


def fit_taylor_comparator(snapshots, actual_rate_actions, *, calibration_cutoff="2023-04-06",
                          reduced_input=False, rho=.75, bootstrap_draws=500, seed=42, bootstrap_block_size=2):
    """Fit a predeclared rho and bounded coefficients using calibration meetings only.

    This fits committee rates, not individual preferences or dissent. Stance mapping
    is a stated Taylor heuristic and has not been fitted to committee stance labels.
    """
    cutoff = date.fromisoformat(calibration_cutoff).isoformat()
    if len(snapshots) != len(actual_rate_actions) or len(snapshots) < 8:
        raise ValueError("Taylor calibration needs >=8 aligned meetings")
    dates = [s.meeting_date for s in snapshots]
    if len(set(dates)) != len(dates) or dates != sorted(dates) or any(d > cutoff for d in dates):
        raise ValueError("Duplicate, unsorted or heldout meeting in calibration")
    if (type(reduced_input) is not bool or type(rho) not in (int, float) or not np.isfinite(rho)
            or not 0 <= rho < 1 or type(bootstrap_draws) is not int or bootstrap_draws < 1
            or type(bootstrap_block_size) is not int or not 1 <= bootstrap_block_size <= len(snapshots)
            or type(seed) is not int):
        raise ValueError("Invalid calibration settings")
    if any(type(action) is not int or action not in RATE_ACTIONS_BPS for action in actual_rate_actions):
        raise ValueError('Calibration actions must be exact integer members of the shared action domain')
    use_gap = not reduced_input
    use_fed = all(s.us_fed_funds_rate_pct is not None for s in snapshots)
    if not reduced_input and (not use_fed or any(s.output_gap_pct is None for s in snapshots)):
        raise ValueError("Full open-economy comparator cannot be fitted without actual available gap and Fed inputs")
    features = ["r_star", "alpha"] + (["beta"] if use_gap else []) + (["gamma"] if use_fed else [])
    X = np.asarray([[1, s.cpi_headline_yoy_pct - 4]
                    + ([s.output_gap_pct] if use_gap else [])
                    + ([s.us_fed_funds_rate_pct - 2.5] if use_fed else []) for s in snapshots], dtype=float)
    # Implied unsmoothed target after removing the observed CPI level.
    y = np.asarray([(s.current_repo_rate_pct + int(action) / 100 - rho * s.current_repo_rate_pct) / (1-rho)
                    - s.cpi_headline_yoy_pct for s, action in zip(snapshots, actual_rate_actions)])
    if not np.isfinite(X).all() or not np.isfinite(y).all():
        raise ValueError("Nonfinite comparator calibration")
    lower = np.zeros(X.shape[1])
    upper = np.asarray([5.0, 3.0] + ([2.0] if use_gap else []) + ([2.0] if use_fed else []))
    def fit(rows):
        result = lsq_linear(X[rows], y[rows], bounds=(lower, upper))
        if not result.success or not np.isfinite(result.x).all():
            raise ValueError("Comparator optimizer failed")
        return tuple(float(v) for v in result.x)
    coefficients = dict(zip(features, fit(np.arange(len(snapshots)))))
    rng = np.random.default_rng(seed)
    def block_rows():
        starts = rng.integers(0, len(snapshots), int(np.ceil(len(snapshots)/bootstrap_block_size)))
        return ((starts[:,None]+np.arange(bootstrap_block_size)) % len(snapshots)).ravel()[:len(snapshots)]
    boot = tuple(fit(block_rows()) for _ in range(bootstrap_draws))
    payload = {"snapshots": [s.model_dump(mode="json") for s in snapshots],
               "actions": list(actual_rate_actions), "features": features, "rho": rho,
               "bounds": [lower.tolist(), upper.tolist()], 'bootstrap_block_size':bootstrap_block_size,
               'bootstrap_draws':bootstrap_draws, 'bootstrap_seed':seed}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return FittedTaylorComparator(coefficients["r_star"], coefficients["alpha"], coefficients.get("beta", 0),
        coefficients.get("gamma", 0), rho, cutoff, tuple(dates), digest,
        "bounded least squares of next policy repo rate; rho fixed before evaluation",
        "reduced-input sensitivity; original output-gap scope remains unresolved" if reduced_input else "full open-economy",
        (tuple(lower.tolist()), tuple(upper.tolist())), boot, seed,
        'circular temporal-block sensitivity; small calibration sample, not identified structural uncertainty',
        bootstrap_block_size, tuple(features), int(np.linalg.matrix_rank(X)))
