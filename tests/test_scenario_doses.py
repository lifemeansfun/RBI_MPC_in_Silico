"""Counterexamples for declared compound doses, missingness and menu saturation."""

import math

import pytest

from src.rational.taylor_rule import MemberTaylorParameters, SmoothedTaylorRule
from src.scenarios.scenario_runner import ScenarioRunner, apply_snapshot_intervention
from src.schemas.macro_schema import MacroMeetingSnapshot, OBSERVABLE_FIELDS


@pytest.fixture
def observed_snapshot():
    return MacroMeetingSnapshot(
        meeting_date="2023-08-10", current_repo_rate_pct=6.5,
        cpi_headline_yoy_pct=4.8, cpi_core_yoy_pct=4.2, cpi_food_yoy_pct=5.5,
        cfpi_yoy_pct=5.1, iip_growth_yoy_pct=4.5, output_gap_pct=0.2,
        gva_growth_yoy_pct=6.2, gdp_growth_yoy_pct=6.4,
        system_liquidity_cr=-20000.0, usd_inr_exchange_rate=82.8,
        brent_crude_usd_bbl=85.0, us_fed_funds_rate_pct=5.5,
        monsoon_departure_lpa_pct=-3.5, prev_stance="withdrawal_of_accommodation",
        real_rate_decision_bps=0, real_dissenters=["legacy_annotation"],
    )


def assert_observables_identical(parent, treated):
    assert {field: getattr(treated, field) for field in OBSERVABLE_FIELDS} == {
        field: getattr(parent, field) for field in OBSERVABLE_FIELDS
    }


@pytest.mark.parametrize("builder,kwargs", [
    (ScenarioRunner.build_us_fed_spillover_snapshot, {}),
    (ScenarioRunner.build_us_fed_spillover_snapshot, {"fed_hike_bps": -75, "inr_depreciation": 7.0}),
    (ScenarioRunner.build_monsoon_food_shock_snapshot, {}),
    (ScenarioRunner.build_monsoon_food_shock_snapshot, {"food_cpi_shock_pct": -4, "monsoon_departure_pct": 15}),
])
def test_zero_compound_dose_is_observable_identity(observed_snapshot, builder, kwargs):
    original = observed_snapshot.model_dump()
    treated = builder(observed_snapshot, dose=0.0, **kwargs)
    assert_observables_identical(observed_snapshot, treated)
    assert observed_snapshot.model_dump() == original
    assert treated.input_track == "counterfactual"
    assert treated.intervention["assumptions"]["dose"] == 0
    assert treated.intervention["parent_snapshot"] == observed_snapshot.model_dump(mode="json")


def test_zero_dose_preserves_signed_zero_values(observed_snapshot):
    fields = ("cpi_headline_yoy_pct", "cpi_core_yoy_pct", "cpi_food_yoy_pct",
              "iip_growth_yoy_pct", "output_gap_pct", "system_liquidity_cr",
              "us_fed_funds_rate_pct", "monsoon_departure_lpa_pct")
    parent = observed_snapshot.model_copy(update={field: -0.0 for field in fields})
    for builder in (ScenarioRunner.build_us_fed_spillover_snapshot, ScenarioRunner.build_monsoon_food_shock_snapshot):
        treated = builder(parent, dose=0)
        assert_observables_identical(parent, treated)
        for field in fields:
            assert math.copysign(1, getattr(treated, field)) == -1


def test_zero_fed_component_has_no_hidden_offsets(observed_snapshot):
    assert_observables_identical(
        observed_snapshot, ScenarioRunner.build_us_fed_spillover_snapshot(observed_snapshot, fed_hike_bps=0)
    )
    assert_observables_identical(
        observed_snapshot,
        ScenarioRunner.build_us_fed_spillover_snapshot(observed_snapshot, fed_hike_bps=0, inr_depreciation=0),
    )
    independent_fx = ScenarioRunner.build_us_fed_spillover_snapshot(
        observed_snapshot, fed_hike_bps=0, inr_depreciation=1.5
    )
    assert independent_fx.usd_inr_exchange_rate == observed_snapshot.usd_inr_exchange_rate + 1.5
    for field in OBSERVABLE_FIELDS:
        if field != "usd_inr_exchange_rate":
            assert getattr(independent_fx, field) == getattr(observed_snapshot, field)
    assert independent_fx.intervention["assumptions"]["inr_mode"] == "explicit_independent_delta"


def test_zero_food_component_has_no_default_drags_or_rainfall_replacement(observed_snapshot):
    treated = ScenarioRunner.build_monsoon_food_shock_snapshot(observed_snapshot, food_cpi_shock_pct=0)
    assert_observables_identical(observed_snapshot, treated)
    rain_only = ScenarioRunner.build_monsoon_food_shock_snapshot(
        observed_snapshot, food_cpi_shock_pct=0, monsoon_departure_pct=-20
    )
    assert rain_only.monsoon_departure_lpa_pct == -20
    for field in OBSERVABLE_FIELDS:
        if field != "monsoon_departure_lpa_pct":
            assert getattr(rain_only, field) == getattr(observed_snapshot, field)
    assert rain_only.intervention["assumptions"]["rainfall_mode"] == "explicit_absolute_endpoint"


@pytest.mark.parametrize("builder,kwargs,fields", [
    (ScenarioRunner.build_us_fed_spillover_snapshot, {},
     {"cpi_headline_yoy_pct", "cpi_core_yoy_pct", "system_liquidity_cr", "usd_inr_exchange_rate", "us_fed_funds_rate_pct"}),
    (ScenarioRunner.build_monsoon_food_shock_snapshot, {},
     {"cpi_headline_yoy_pct", "cpi_food_yoy_pct", "iip_growth_yoy_pct", "output_gap_pct", "monsoon_departure_lpa_pct"}),
])
def test_signed_linear_dose_preserves_unrelated_fields(observed_snapshot, builder, kwargs, fields):
    full = builder(observed_snapshot, dose=1, **kwargs)
    half = builder(observed_snapshot, dose=0.5, **kwargs)
    reverse = builder(observed_snapshot, dose=-1, **kwargs)
    for field in fields:
        initial = getattr(observed_snapshot, field)
        full_delta = getattr(full, field) - initial
        assert getattr(half, field) - initial == pytest.approx(full_delta / 2)
        assert getattr(reverse, field) - initial == pytest.approx(-full_delta)
    for field in OBSERVABLE_FIELDS:
        if field not in fields:
            assert getattr(full, field) == getattr(half, field) == getattr(reverse, field) == getattr(observed_snapshot, field)
    for field in ("observations", "meeting_date", "real_dissenters", "real_rate_decision_bps"):
        assert getattr(full, field) == getattr(observed_snapshot, field)


def test_reference_doses_retain_legacy_values_and_component_units(observed_snapshot):
    fed = ScenarioRunner.build_us_fed_spillover_snapshot(observed_snapshot)
    assert fed.cpi_headline_yoy_pct == pytest.approx(5.1)
    assert fed.cpi_core_yoy_pct == pytest.approx(4.4)
    assert fed.system_liquidity_cr == -50000
    assert fed.usd_inr_exchange_rate == pytest.approx(84.3)
    assert fed.us_fed_funds_rate_pct == 6.25
    monsoon = ScenarioRunner.build_monsoon_food_shock_snapshot(observed_snapshot)
    assert monsoon.cpi_headline_yoy_pct == pytest.approx(4.8 + 4 * 0.458)
    assert monsoon.cpi_food_yoy_pct == 9.5
    assert monsoon.iip_growth_yoy_pct == 4.0
    assert monsoon.output_gap_pct == pytest.approx(0.0)
    assert monsoon.monsoon_departure_lpa_pct == -20
    assert fed.intervention["assumptions"]["inr_delta_units"] == "rupees_per_USD"
    assert monsoon.intervention["assumptions"]["food_change_units"] == "percentage_points"
    for treated in (fed, monsoon):
        assert treated.intervention["assumptions"]["component_basis"] == "assumed_linear_bundle_not_estimated_transmission"
        assert treated.intervention["assumptions"]["historical_reconstruction"] is False


def test_requested_primary_dose_scales_ancillary_components(observed_snapshot):
    fed = ScenarioRunner.build_us_fed_spillover_snapshot(observed_snapshot, fed_hike_bps=37.5)
    assert fed.cpi_headline_yoy_pct - 4.8 == pytest.approx(0.15)
    assert fed.cpi_core_yoy_pct - 4.2 == pytest.approx(0.1)
    assert fed.system_liquidity_cr == -35000
    assert fed.usd_inr_exchange_rate - 82.8 == pytest.approx(0.75)
    rain = ScenarioRunner.build_monsoon_food_shock_snapshot(observed_snapshot, food_cpi_shock_pct=2)
    assert rain.iip_growth_yoy_pct == 4.25
    assert rain.output_gap_pct == pytest.approx(0.1)
    assert rain.monsoon_departure_lpa_pct == pytest.approx((-3.5 - 20) / 2)


@pytest.mark.parametrize("builder,optional_fields", [
    (ScenarioRunner.build_us_fed_spillover_snapshot,
     {"cpi_core_yoy_pct", "system_liquidity_cr", "usd_inr_exchange_rate", "us_fed_funds_rate_pct"}),
    (ScenarioRunner.build_monsoon_food_shock_snapshot,
     {"cpi_food_yoy_pct", "iip_growth_yoy_pct", "output_gap_pct", "monsoon_departure_lpa_pct"}),
])
def test_all_unknown_component_observations_remain_unknown(observed_snapshot, builder, optional_fields):
    missing = observed_snapshot.model_copy(update={field: None for field in optional_fields})
    for dose in (-1, 0, 0.5, 1):
        treated = builder(missing, dose=dose)
        for field in optional_fields:
            assert getattr(treated, field) is None
        assert treated.intervention["assumptions"]["missing_input_policy"] == "preserve_unknown"


def test_custom_assumptions_are_explicit_and_can_remove_ancillary_channels(observed_snapshot):
    fed = ScenarioRunner.build_us_fed_spillover_snapshot(
        observed_snapshot, headline_delta_pct_per_75bps=0, core_delta_pct_per_75bps=0,
        liquidity_drain_cr_per_75bps=0, inr_depreciation_per_75bps=0,
    )
    for field in OBSERVABLE_FIELDS:
        if field != "us_fed_funds_rate_pct":
            assert getattr(fed, field) == getattr(observed_snapshot, field)
    monsoon = ScenarioRunner.build_monsoon_food_shock_snapshot(
        observed_snapshot, food_headline_weight=0, iip_drag_pct_per_4pct=0,
        output_gap_drag_pct_per_4pct=0, monsoon_departure_pct=-3.5,
    )
    for field in OBSERVABLE_FIELDS:
        if field != "cpi_food_yoy_pct":
            assert getattr(monsoon, field) == getattr(observed_snapshot, field)


@pytest.mark.parametrize("builder,kwargs", [
    (ScenarioRunner.build_us_fed_spillover_snapshot, {"dose": math.nan}),
    (ScenarioRunner.build_us_fed_spillover_snapshot, {"dose": True}),
    (ScenarioRunner.build_us_fed_spillover_snapshot, {"headline_delta_pct_per_75bps": math.inf}),
    (ScenarioRunner.build_us_fed_spillover_snapshot, {"liquidity_drain_cr_per_75bps": -1}),
    (ScenarioRunner.build_us_fed_spillover_snapshot, {"fed_hike_bps": 1e308, "dose": 1e308}),
    (ScenarioRunner.build_monsoon_food_shock_snapshot, {"dose": math.inf}),
    (ScenarioRunner.build_monsoon_food_shock_snapshot, {"food_headline_weight": 1.1}),
    (ScenarioRunner.build_monsoon_food_shock_snapshot, {"iip_drag_pct_per_4pct": -0.5}),
    (ScenarioRunner.build_monsoon_food_shock_snapshot, {"monsoon_departure_pct": False}),
])
def test_invalid_component_parameters_fail_closed(observed_snapshot, builder, kwargs):
    with pytest.raises(ValueError):
        builder(observed_snapshot, **kwargs)


def test_unknown_baseline_cannot_conceal_overflowing_component_assumptions():
    missing = MacroMeetingSnapshot(meeting_date="2023-08-10", current_repo_rate_pct=6.5,
                                   cpi_headline_yoy_pct=5.2)
    with pytest.raises(ValueError, match="derived intervention delta"):
        ScenarioRunner.build_us_fed_spillover_snapshot(
            missing, dose=1e308, headline_delta_pct_per_75bps=0,
            core_delta_pct_per_75bps=0, inr_depreciation_per_75bps=0,
            liquidity_drain_cr_per_75bps=1e308,
        )


def test_nested_nonfinite_intervention_assumptions_are_rejected(observed_snapshot):
    with pytest.raises(ValueError, match="finite JSON"):
        apply_snapshot_intervention(observed_snapshot, {}, "corrupt_assumption", {"component": {"delta": math.inf}})


def test_saturation_is_visible_even_when_discrete_rate_wedge_is_zero(observed_snapshot):
    observed_snapshot = observed_snapshot.model_copy(update={"cpi_headline_yoy_pct": 5.2})
    members = [MemberTaylorParameters(f"m{i}") for i in range(6)]
    runner = ScenarioRunner(SmoothedTaylorRule())
    result = runner.run_us_fed_spillover_shock(observed_snapshot, members, "m0", dose=3)
    assert result.baseline_repo_rate_change_bps == result.shocked_repo_rate_change_bps == 50
    assert result.rate_wedge_bps == 0
    assert result.continuous_diagnostics_available
    for member in members:
        assert result.continuous_rate_changes_bps["shocked"][member.member_id] > result.continuous_rate_changes_bps["baseline"][member.member_id]
        assert result.menu_saturation["baseline"][member.member_id] == "above_menu"
        assert result.menu_saturation["shocked"][member.member_id] == "above_menu"
    assert result.intervention_assumptions["dose"] == 3
    assert result.action_menu_bps == [-50, -25, 0, 25, 35, 40, 50]


def test_zero_dose_full_outcomes_and_continuous_targets_match(observed_snapshot):
    members = [MemberTaylorParameters(f"m{i}") for i in range(6)]
    runner = ScenarioRunner(SmoothedTaylorRule())
    for run in (runner.run_us_fed_spillover_shock, runner.run_monsoon_food_shock):
        result = run(observed_snapshot, members, "m0", dose=0)
        assert result.rate_wedge_bps == 0 and not result.stance_changed
        assert result.continuous_targets_pct["baseline"] == result.continuous_targets_pct["shocked"]
        assert result.menu_saturation["baseline"] == result.menu_saturation["shocked"]


def test_discrete_only_comparator_diagnostics_are_explicitly_unavailable(observed_snapshot):
    class DiscreteOnlyRule:
        def compute_discrete_action(self, snapshot, params):
            return 0, "neutral"

    members = [MemberTaylorParameters(f"m{i}") for i in range(6)]
    result = ScenarioRunner(DiscreteOnlyRule()).run_us_fed_spillover_shock(observed_snapshot, members, "m0")
    assert not result.continuous_diagnostics_available
    assert result.continuous_targets_pct == result.menu_saturation == {}
    assert result.action_menu_bps == []


def test_nonfinite_continuous_interface_fails_before_result(observed_snapshot):
    class CorruptContinuousRule:
        action_set_bps = (0, 25)

        def compute_discrete_action(self, snapshot, params):
            return 0, "neutral"

        def compute_continuous_rate(self, snapshot, params):
            return math.nan

    members = [MemberTaylorParameters(f"m{i}") for i in range(6)]
    with pytest.raises(ValueError, match="continuous policy target"):
        ScenarioRunner(CorruptContinuousRule()).run_us_fed_spillover_shock(observed_snapshot, members, "m0")


def test_exact_menu_boundary_is_not_outside_menu_saturation(observed_snapshot):
    class BoundaryRule:
        action_set_bps = (-50, 0, 50)

        def compute_discrete_action(self, snapshot, params):
            return 50, "neutral"

        def compute_continuous_rate(self, snapshot, params):
            return snapshot.current_repo_rate_pct + 0.5

    members = [MemberTaylorParameters(f"m{i}") for i in range(6)]
    result = ScenarioRunner(BoundaryRule()).run_us_fed_spillover_shock(observed_snapshot, members, "m0")
    assert result.menu_saturation["baseline"] == result.menu_saturation["shocked"] == {
        member.member_id: "within_menu" for member in members
    }
