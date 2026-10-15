"""Declared synthetic sensitivity scenarios; numerical wedges are simulator-local."""

import hashlib
import json
import math
from typing import Any
from dataclasses import dataclass, field

from src.schemas.macro_schema import MacroMeetingSnapshot, OBSERVABLE_FIELDS
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.rule_engine.engine import InstitutionalRuleEngine
from src.infra.evidence import content_hash


def apply_snapshot_intervention(
    baseline: MacroMeetingSnapshot, updates: dict[str, Any], name: str,
    assumptions: dict[str, Any] | None = None,
) -> MacroMeetingSnapshot:
    """Preserve every unrelated validated field, and validate changed fields afresh.

    Existing observation records describe the parent snapshot, not the synthetic
    values. The counterfactual track and intervention manifest make that explicit.
    """
    # Revalidate to reject bypassed/model_construct inputs before preserving their evidence.
    baseline = type(baseline).model_validate(baseline.model_dump())
    if baseline.input_track == "source_linked":
        baseline.verify_sources()
    payload = baseline.model_dump(mode="json")
    unknown = set(updates) - set(OBSERVABLE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown intervention fields: {sorted(unknown)}")
    for key, value in updates.items():
        if isinstance(value, (int, float)) and (isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError(f"Intervention field {key} must be finite")
    try:
        json.dumps(assumptions or {}, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("Intervention assumptions must contain finite JSON values") from error
    fields = type(baseline).model_fields
    parent_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    payload.update(updates)
    if "input_track" in fields:
        payload["input_track"] = "counterfactual"
    if "parent_snapshot_hash" in fields:
        payload["parent_snapshot_hash"] = parent_hash
    if "intervention" in fields:
        payload["intervention"] = {"name": name, "changed_fields": updates, "assumptions": assumptions or {},
                                   "estimand_scope": "simulator_local", "parent_snapshot_hash": parent_hash,
                                   "parent_snapshot": baseline.model_dump(mode="json")}
    return type(baseline).model_validate(payload)


def _add_if_observed(value: float | None, delta: float) -> float | None:
    # Missingness must not conceal overflow in a declared synthetic component.
    _finite_parameter(delta, "derived intervention delta")
    # Returning the parent also preserves signed zero for an identity intervention.
    return value if value is None or delta == 0 else value + delta


def _finite_parameter(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _nonnegative_parameter(value: float, name: str) -> None:
    _finite_parameter(value, name)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _endpoint_if_observed(value: float | None, endpoint: float, dose: float) -> float | None:
    """Interpolate/extrapolate an assumed endpoint without supplying a missing value."""
    _finite_parameter(dose, "derived rainfall interpolation dose")
    if value is None:
        return None
    if dose == 0:
        return value
    return value + dose * (endpoint - value)


@dataclass
class ScenarioOutcome:
    scenario_name: str
    baseline_repo_rate_change_bps: int
    shocked_repo_rate_change_bps: int
    baseline_stance: str
    shocked_stance: str
    rate_wedge_bps: int
    stance_changed: bool
    dissenting_members_shocked: list[str]
    estimand_scope: str = "simulator_local"
    scenario_evidence_type: str = "synthetic_sensitivity"
    dissenting_members_stance_shocked: list[str] = field(default_factory=list)
    baseline_snapshot_hash: str = ""
    shocked_snapshot_hash: str = ""
    resolution_policies: dict[str, str] = field(default_factory=dict)
    synthetic_resolutions: dict[str, bool] = field(default_factory=dict)
    intervention_assumptions: dict[str, Any] = field(default_factory=dict)
    continuous_diagnostics_available: bool = False
    continuous_targets_pct: dict[str, dict[str, float]] = field(default_factory=dict)
    continuous_rate_changes_bps: dict[str, dict[str, float]] = field(default_factory=dict)
    menu_saturation: dict[str, dict[str, str]] = field(default_factory=dict)
    action_menu_bps: list[int] = field(default_factory=list)
    fragmentation_policy: str = "reject"


class ScenarioRunner:
    """Apply declared shocks to a fitted or explicitly assumed rational comparator."""
    def __init__(self, taylor_rule: SmoothedTaylorRule, fragmentation_policy: str = "reject"):
        self.rule = taylor_rule
        if fragmentation_policy not in ("reject", "legacy_synthetic", "status_quo"):
            raise ValueError("Unknown scenario fragmentation policy")
        self.fragmentation_policy = fragmentation_policy

    def _run(self, name, baseline, shocked, member_params, governor_id):
        member_params = tuple(member_params)
        if len({p.member_id for p in member_params}) != len(member_params):
            raise ValueError("Comparator members must have unique identities")
        baseline_votes = {p.member_id: self.rule.compute_discrete_action(baseline, p) for p in member_params}
        shock_votes = {p.member_id: self.rule.compute_discrete_action(shocked, p) for p in member_params}
        settings = {"fragmentation_policy": self.fragmentation_policy}
        base_r = InstitutionalRuleEngine.aggregate_rate_votes({m: v[0] for m, v in baseline_votes.items()}, governor_id, prior_action=0, **settings)
        base_s = InstitutionalRuleEngine.aggregate_stance_votes({m: v[1] for m, v in baseline_votes.items()}, governor_id, prior_action=baseline.prev_stance, **settings)
        shock_r = InstitutionalRuleEngine.aggregate_rate_votes({m: v[0] for m, v in shock_votes.items()}, governor_id, prior_action=0, **settings)
        shock_s = InstitutionalRuleEngine.aggregate_stance_votes({m: v[1] for m, v in shock_votes.items()}, governor_id, prior_action=shocked.prev_stance, **settings)
        targets, continuous_changes, saturation, menu = self._continuous_diagnostics(
            baseline, shocked, member_params
        )
        return ScenarioOutcome(name, base_r.winning_action, shock_r.winning_action,
                               base_s.winning_action, shock_s.winning_action,
                               shock_r.winning_action - base_r.winning_action,
                               shock_s.winning_action != base_s.winning_action, shock_r.dissenting_members,
                               dissenting_members_stance_shocked=shock_s.dissenting_members,
                               baseline_snapshot_hash=content_hash(baseline.model_dump(mode="json")),
                               shocked_snapshot_hash=content_hash(shocked.model_dump(mode="json")),
                               resolution_policies={"baseline_rate": base_r.resolution_policy, "baseline_stance": base_s.resolution_policy,
                                                    "shocked_rate": shock_r.resolution_policy, "shocked_stance": shock_s.resolution_policy},
                               synthetic_resolutions={"baseline_rate": base_r.synthetic_resolution, "baseline_stance": base_s.synthetic_resolution,
                                                      "shocked_rate": shock_r.synthetic_resolution, "shocked_stance": shock_s.synthetic_resolution},
                               intervention_assumptions=shocked.intervention.get("assumptions", {}),
                               continuous_diagnostics_available=bool(targets),
                               continuous_targets_pct=targets, continuous_rate_changes_bps=continuous_changes,
                               menu_saturation=saturation, action_menu_bps=menu,
                               fragmentation_policy=self.fragmentation_policy)

    def _continuous_diagnostics(self, baseline, shocked, member_params):
        """Expose individual continuous targets that a finite action menu can conceal.

        A discrete-only comparator retains compatibility and explicitly has no such
        diagnostics. Boundary actions alone are not evidence of menu saturation:
        saturation means the continuous change lies strictly outside menu bounds.
        """
        compute = getattr(self.rule, "compute_continuous_rate", None)
        action_menu = getattr(self.rule, "action_set_bps", None)
        if not callable(compute):
            return {}, {}, {}, []
        if not action_menu or any(type(action) is not int for action in action_menu):
            raise ValueError("Continuous scenario diagnostics require a finite integer action menu")
        menu = sorted(set(action_menu))
        targets, changes, saturation = {}, {}, {}
        for condition, snapshot in (("baseline", baseline), ("shocked", shocked)):
            targets[condition], changes[condition], saturation[condition] = {}, {}, {}
            for params in member_params:
                target = compute(snapshot, params)
                _finite_parameter(target, "continuous policy target")
                change = (target - snapshot.current_repo_rate_pct) * 100.0
                _finite_parameter(change, "continuous policy rate change")
                targets[condition][params.member_id] = target
                changes[condition][params.member_id] = change
                saturation[condition][params.member_id] = (
                    "below_menu" if change < menu[0] else "above_menu" if change > menu[-1] else "within_menu"
                )
        return targets, changes, saturation, menu

    def run_monsoon_food_shock(self, baseline_snapshot, member_params, governor_id,
                               food_cpi_shock_pct=4.0, monsoon_departure_pct=None, *, dose=1.0,
                               food_headline_weight=0.458, iip_drag_pct_per_4pct=0.5,
                               output_gap_drag_pct_per_4pct=0.2, monsoon_failure_endpoint_pct=-20.0):
        shock = self.build_monsoon_food_shock_snapshot(
            baseline_snapshot, food_cpi_shock_pct, monsoon_departure_pct, dose=dose,
            food_headline_weight=food_headline_weight, iip_drag_pct_per_4pct=iip_drag_pct_per_4pct,
            output_gap_drag_pct_per_4pct=output_gap_drag_pct_per_4pct,
            monsoon_failure_endpoint_pct=monsoon_failure_endpoint_pct,
        )
        return self._run("Monsoon Failure & Food Inflation Shock", baseline_snapshot, shock, member_params, governor_id)

    def run_us_fed_spillover_shock(self, baseline_snapshot, member_params, governor_id,
                                  fed_hike_bps=75, inr_depreciation=None, *, dose=1.0,
                                  headline_delta_pct_per_75bps=0.30, core_delta_pct_per_75bps=0.20,
                                  liquidity_drain_cr_per_75bps=30000.0, inr_depreciation_per_75bps=1.50):
        shock = self.build_us_fed_spillover_snapshot(
            baseline_snapshot, fed_hike_bps, inr_depreciation, dose=dose,
            headline_delta_pct_per_75bps=headline_delta_pct_per_75bps,
            core_delta_pct_per_75bps=core_delta_pct_per_75bps,
            liquidity_drain_cr_per_75bps=liquidity_drain_cr_per_75bps,
            inr_depreciation_per_75bps=inr_depreciation_per_75bps,
        )
        return self._run(f"US Federal Reserve Spillover Shock ({dose * fed_hike_bps:+g} bps)", baseline_snapshot, shock, member_params, governor_id)

    def run_pandemic_easing_shock(self, baseline_snapshot, member_params, governor_id):
        return self._run("2020 Pandemic Easing Cycle", baseline_snapshot,
                         self.build_pandemic_easing_snapshot(baseline_snapshot), member_params, governor_id)

    def run_taper_tantrum_shock(self, baseline_snapshot, member_params, governor_id):
        return self._run("2013 Taper Tantrum Crisis", baseline_snapshot,
                         self.build_taper_tantrum_snapshot(baseline_snapshot), member_params, governor_id)

    @staticmethod
    def build_monsoon_food_shock_snapshot(
        baseline_snapshot, food_cpi_shock_pct=4.0, monsoon_departure_pct=None, *, dose=1.0,
        food_headline_weight=0.458, iip_drag_pct_per_4pct=0.5,
        output_gap_drag_pct_per_4pct=0.2, monsoon_failure_endpoint_pct=-20.0,
    ):
        """Assumed compound food/rainfall bundle, with signed linear dose.

        Food inflation changes are percentage points, despite the legacy ``pct``
        argument name. The 4-point reference dose retains the legacy -20% rainfall
        endpoint, -0.5-point IIP and -0.2-point output-gap assumptions. These drags
        scale with food_cpi_shock_pct / 4. An unspecified rainfall endpoint moves
        from the observed parent toward -20% by the same fraction; an explicitly
        supplied monsoon_departure_pct is an absolute hypothetical endpoint,
        independent of the food component, interpolated by dose. Thus food=0 and
        an explicit different rainfall endpoint is a compound intervention.
        dose=0 universally preserves every observable, including rainfall.
        Negative dose reverses the assumed bundle. Missing inputs stay missing.
        """
        _finite_parameter(food_cpi_shock_pct, "food_cpi_shock_pct")
        _finite_parameter(dose, "dose")
        _finite_parameter(monsoon_failure_endpoint_pct, "monsoon_failure_endpoint_pct")
        for value, name in ((food_headline_weight, "food_headline_weight"),
                            (iip_drag_pct_per_4pct, "iip_drag_pct_per_4pct"),
                            (output_gap_drag_pct_per_4pct, "output_gap_drag_pct_per_4pct")):
            _nonnegative_parameter(value, name)
        if food_headline_weight > 1:
            raise ValueError("food_headline_weight must be between zero and one")
        reference_fraction = food_cpi_shock_pct / 4.0
        rainfall_mode = "food_scaled_reference_endpoint" if monsoon_departure_pct is None else "explicit_absolute_endpoint"
        rainfall_endpoint = monsoon_failure_endpoint_pct if monsoon_departure_pct is None else monsoon_departure_pct
        _finite_parameter(rainfall_endpoint, "monsoon_departure_pct")
        rainfall_dose = dose * reference_fraction if monsoon_departure_pct is None else dose
        return apply_snapshot_intervention(baseline_snapshot, {
            "cpi_headline_yoy_pct": _add_if_observed(baseline_snapshot.cpi_headline_yoy_pct, dose * food_cpi_shock_pct * food_headline_weight),
            "cpi_food_yoy_pct": _add_if_observed(baseline_snapshot.cpi_food_yoy_pct, dose * food_cpi_shock_pct),
            "iip_growth_yoy_pct": _add_if_observed(baseline_snapshot.iip_growth_yoy_pct, -dose * reference_fraction * iip_drag_pct_per_4pct),
            "output_gap_pct": _add_if_observed(baseline_snapshot.output_gap_pct, -dose * reference_fraction * output_gap_drag_pct_per_4pct),
            "monsoon_departure_lpa_pct": _endpoint_if_observed(baseline_snapshot.monsoon_departure_lpa_pct, rainfall_endpoint, rainfall_dose),
        }, "monsoon_food_shock", {
            "dose_contract_version": 2, "dose": dose, "food_cpi_shock_pct": food_cpi_shock_pct,
            "food_change_units": "percentage_points", "reference_food_change_pct": 4.0,
            "food_headline_weight": food_headline_weight,
            "iip_drag_pct_per_4pct": iip_drag_pct_per_4pct,
            "output_gap_drag_pct_per_4pct": output_gap_drag_pct_per_4pct,
            "rainfall_mode": rainfall_mode, "rainfall_endpoint_pct": rainfall_endpoint,
            "rainfall_interpolation_dose": rainfall_dose,
            "iip_drag_pct": -dose * reference_fraction * iip_drag_pct_per_4pct,
            "output_gap_drag_pct": -dose * reference_fraction * output_gap_drag_pct_per_4pct,
            "component_basis": "assumed_linear_bundle_not_estimated_transmission",
            "missing_input_policy": "preserve_unknown", "historical_reconstruction": False,
        })

    @staticmethod
    def build_us_fed_spillover_snapshot(
        baseline_snapshot, fed_hike_bps=75, inr_depreciation=None, *, dose=1.0,
        headline_delta_pct_per_75bps=0.30, core_delta_pct_per_75bps=0.20,
        liquidity_drain_cr_per_75bps=30000.0, inr_depreciation_per_75bps=1.50,
    ):
        """Assumed signed Fed bundle, retaining values at the 75-bps reference dose.

        CPI/core/liquidity offsets scale with fed_hike_bps / 75, rather than being
        fixed at every dose. An unspecified INR component also scales with that
        fraction; explicit inr_depreciation is an independent absolute change in
        rupees per USD (not a percentage depreciation). dose multiplies all
        components, and dose=0 universally preserves observable values. Positive
        Fed dose raises assumed inflation, drains liquidity and raises USD/INR;
        negative dose reverses those assumptions. No transmission is estimated.
        Missing inputs remain missing, with parent evidence retained separately.
        """
        _finite_parameter(fed_hike_bps, "fed_hike_bps")
        _finite_parameter(dose, "dose")
        for value, name in ((headline_delta_pct_per_75bps, "headline_delta_pct_per_75bps"),
                            (core_delta_pct_per_75bps, "core_delta_pct_per_75bps"),
                            (liquidity_drain_cr_per_75bps, "liquidity_drain_cr_per_75bps"),
                            (inr_depreciation_per_75bps, "inr_depreciation_per_75bps")):
            _nonnegative_parameter(value, name)
        reference_fraction = fed_hike_bps / 75.0
        inr_mode = "fed_scaled_reference_delta" if inr_depreciation is None else "explicit_independent_delta"
        inr_delta = reference_fraction * inr_depreciation_per_75bps if inr_depreciation is None else inr_depreciation
        _finite_parameter(inr_delta, "inr_depreciation")
        headline_delta = dose * reference_fraction * headline_delta_pct_per_75bps
        core_delta = dose * reference_fraction * core_delta_pct_per_75bps
        liquidity_delta = -dose * reference_fraction * liquidity_drain_cr_per_75bps
        return apply_snapshot_intervention(baseline_snapshot, {
            "cpi_headline_yoy_pct": _add_if_observed(baseline_snapshot.cpi_headline_yoy_pct, headline_delta),
            "cpi_core_yoy_pct": _add_if_observed(baseline_snapshot.cpi_core_yoy_pct, core_delta),
            "system_liquidity_cr": _add_if_observed(baseline_snapshot.system_liquidity_cr, liquidity_delta),
            "usd_inr_exchange_rate": _add_if_observed(baseline_snapshot.usd_inr_exchange_rate, dose * inr_delta),
            "us_fed_funds_rate_pct": _add_if_observed(baseline_snapshot.us_fed_funds_rate_pct, dose * fed_hike_bps / 100.0),
        }, "us_fed_spillover", {"fed_hike_bps": fed_hike_bps, "inr_depreciation": inr_depreciation,
                                "dose_contract_version": 2, "dose": dose, "reference_fed_hike_bps": 75.0,
                                "headline_delta_pct_per_75bps": headline_delta_pct_per_75bps,
                                "core_delta_pct_per_75bps": core_delta_pct_per_75bps,
                                "liquidity_drain_cr_per_75bps": liquidity_drain_cr_per_75bps,
                                "inr_depreciation_per_75bps": inr_depreciation_per_75bps,
                                "inr_mode": inr_mode, "inr_delta_units": "rupees_per_USD",
                                "headline_delta_pct": headline_delta, "core_delta_pct": core_delta,
                                "liquidity_drain_cr": -liquidity_delta,
                                "applied_fed_hike_bps": dose * fed_hike_bps, "applied_inr_delta": dose * inr_delta,
                                "component_basis": "assumed_linear_bundle_not_estimated_transmission",
                                "missing_input_policy": "preserve_unknown", "historical_reconstruction": False})

    @staticmethod
    def build_pandemic_easing_snapshot(baseline_snapshot):
        return apply_snapshot_intervention(baseline_snapshot, {
            "cpi_headline_yoy_pct": 4.50, "cpi_core_yoy_pct": 3.50, "cpi_food_yoy_pct": 5.50,
            "iip_growth_yoy_pct": -16.7, "output_gap_pct": -4.0,
            "system_liquidity_cr": _add_if_observed(baseline_snapshot.system_liquidity_cr, 150000.0),
            "usd_inr_exchange_rate": 76.0, "brent_crude_usd_bbl": 25.0,
            "us_fed_funds_rate_pct": 0.25, "prev_stance": "accommodative",
        }, "pandemic_easing_sensitivity", {"historical_reconstruction": False})

    @staticmethod
    def build_taper_tantrum_snapshot(baseline_snapshot):
        return apply_snapshot_intervention(baseline_snapshot, {
            "cpi_headline_yoy_pct": 9.84, "cpi_core_yoy_pct": 8.00, "cpi_food_yoy_pct": 13.00,
            "iip_growth_yoy_pct": 1.0, "output_gap_pct": 0.5, "system_liquidity_cr": -80000.0,
            "usd_inr_exchange_rate": 68.80, "brent_crude_usd_bbl": 110.0,
            "us_fed_funds_rate_pct": 0.25, "prev_stance": "withdrawal_of_accommodation",
        }, "taper_tantrum_sensitivity", {"historical_reconstruction": False})
