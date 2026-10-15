"""Engineering controls for the frozen proxy; fixtures are not empirical evidence."""
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import json
import math

import numpy as np
import pytest

from src.data_pipeline.output_gap_estimation import (
    GDP_FIELD, GDPVintage, OutputGapProtocol, QuarterlyGDPInput,
    estimate_output_gap, numerical_proxy_diagnostics, observation_from_result, quarter_period,
)
from src.schemas.macro_schema import ObservationEvidence


def periods(n):
    return [(2011 + i // 4, i % 4 + 1) for i in range(n)]


def signal(n=40, shock=0.0):
    seasons = np.array([0.02, -0.03, -0.01, 0.02])
    x = np.arange(n)
    values = np.exp(12 + 0.014 * x + seasons[x % 4] + 0.035 * np.sin(x / 4))
    if shock:
        values[-4] *= math.exp(shock)
    return values.tolist()


@pytest.fixture
def protocol():
    return OutputGapProtocol(protocol_sha256="a" * 64)


@pytest.fixture
def scientific_fixture(tmp_path):
    raw = tmp_path / "synthetic_gdp.json"
    values = signal()
    raw.write_text(json.dumps(values))
    proof_file = tmp_path / "synthetic_publication_proof.txt"
    proof_file.write_text("Synthetic test fixture: exact GDP version fixture-v1 was available on 2021-07-01")
    stamp = datetime(2021, 7, 1, tzinfo=timezone.utc)
    records = tuple(QuarterlyGDPInput(year, q, ObservationEvidence(
        field=GDP_FIELD, value=value, units="INR crore at constant2011-12 prices",
        reference_period=quarter_period(year, q)[0], vintage="fixture-v1", released_at=stamp,
        source_url="https://example.invalid/synthetic-fixture", source_file=raw.name,
        source_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(), source_pointer=f"Synthetic row{i}",
        availability_basis="Synthetic fixture; no authentic government publication"))
        for i, ((year, q), value) in enumerate(zip(periods(40), values)))
    proof = ObservationEvidence(field="gdp_version_availability", value="fixture-v1",
        units="version identity", reference_period="fixture publication", vintage="fixture-v1",
        released_at=stamp, source_url="https://example.invalid/synthetic-fixture-proof",
        source_file=proof_file.name, source_sha256=hashlib.sha256(proof_file.read_bytes()).hexdigest(),
        source_pointer="Synthetic exact-version link", availability_basis="Test fixture only")
    vintage = GDPVintage("fixture-v1", records, availability_state="documented_version",
                         availability_evidence=(proof,), availability_note="Synthetic evidence gate control")
    return tmp_path, vintage, datetime(2021, 10, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("year,q,start,end", [
    (2019, 1, "2019-04-01", "2019-06-30"), (2019, 2, "2019-07-01", "2019-09-30"),
    (2019, 3, "2019-10-01", "2019-12-31"), (2019, 4, "2020-01-01", "2020-03-31"),
])
def test_fiscal_quarter_calendar_bounds(year, q, start, end):
    _, first, last = quarter_period(year, q)
    assert first.isoformat() == start and last.isoformat() == end


def test_log_linear_seasonal_control_has_zero_cycle(protocol):
    n = 32
    season = [-0.04, 0.01, 0.02, 0.01]
    values = [math.exp(8 + 0.01 * i + season[i % 4]) for i in range(n)]
    result = numerical_proxy_diagnostics(values, [q for _, q in periods(n)],
                                        [y for y, _ in periods(n)], protocol)
    assert abs(result["primary"]["output_gap_pct"]) < 1e-9
    assert sum(result["primary"]["seasonal_effects_log"]) == pytest.approx(0, abs=1e-15)
    assert result["primary"]["normal_equation_max_absolute_residual"] < 1e-10


def test_matches_independent_dense_normal_equation(protocol):
    values = signal()
    x = np.log(values)
    # Independent reference coding uses treatment dummies rather than the implementation's zero-sum coding.
    design = np.column_stack([np.ones(40), np.arange(40), *[(np.arange(40) % 4 == k).astype(float) for k in (0, 1, 2)]])
    coef = np.linalg.lstsq(design, x, rcond=None)[0]
    seasonal = design[:, 2:] @ coef[2:]
    z = x - seasonal
    d = np.zeros((38, 40))
    for i in range(38):
        d[i, i:i + 3] = [1, -2, 1]
    trend = np.linalg.solve(np.eye(40) + 1600 * d.T @ d, z)
    expected = 100 * math.expm1(float(z[-1] - trend[-1]))
    result = numerical_proxy_diagnostics(values, [q for _, q in periods(40)], [y for y, _ in periods(40)], protocol)
    assert result["primary"]["output_gap_pct"] == pytest.approx(expected, abs=2e-10)


def test_rescaling_does_not_change_proxy(protocol):
    p = periods(40)
    first = numerical_proxy_diagnostics(signal(), [q for _, q in p], [y for y, _ in p], protocol)
    second = numerical_proxy_diagnostics([v * 1e7 for v in signal()], [q for _, q in p], [y for y, _ in p], protocol)
    assert first["primary"]["output_gap_pct"] == pytest.approx(second["primary"]["output_gap_pct"], abs=1e-9)


def test_prefix_endpoint_has_no_dependence_on_future_values(protocol):
    p = periods(40)
    values = signal()
    first = numerical_proxy_diagnostics(values[:28], [q for _, q in p[:28]], [y for y, _ in p[:28]], protocol)
    values[28:] = [1e9] * 12
    second = numerical_proxy_diagnostics(values[:28], [q for _, q in p[:28]], [y for y, _ in p[:28]], protocol)
    assert first == second


def test_minimum_and_window_are_distinct_sensitivities(protocol):
    p = periods(36)
    result = numerical_proxy_diagnostics(signal(36), [q for _, q in p], [y for y, _ in p], protocol)
    assert result["status"] == "computed_numerical_diagnostic"
    assert result["sensitivities"]["minimum_40_expanding_coverage"]["status"] == "missing"
    assert result["sensitivities"]["trailing_40"]["status"] == "missing"
    assert result["sensitivities"]["fixed_pre_covid_seasonality"]["seasonal_training_quarters"] == 35
    p = periods(44)
    result = numerical_proxy_diagnostics(signal(44), [q for _, q in p], [y for y, _ in p], protocol)
    assert result["sensitivities"]["minimum_40_expanding_coverage"]["output_gap_pct"] == result["primary"]["output_gap_pct"]
    assert result["sensitivities"]["trailing_40"]["history_quarters"] == 40


def test_large_shock_retains_estimator_dependence_and_unit_distinction(protocol):
    p = periods(44)
    result = numerical_proxy_diagnostics(signal(44, -0.4), [q for _, q in p], [y for y, _ in p], protocol)
    primary = result["primary"]
    assert primary["output_gap_pct"] == pytest.approx(100 * math.expm1(primary["output_gap_log_percentage_points"] / 100))
    assert primary["output_gap_pct"] != pytest.approx(primary["output_gap_log_percentage_points"], abs=1e-4)
    assert result["sensitivities"]["hp_lambda_400"]["output_gap_pct"] != pytest.approx(primary["output_gap_pct"])
    assert result["historical_availability_certified"] is False


@pytest.mark.parametrize("n", [0, 8, 27])
def test_short_histories_return_missing_not_zero(n, protocol):
    p = periods(n)
    result = numerical_proxy_diagnostics(signal(n), [q for _, q in p], [y for y, _ in p], protocol)
    assert result == {"status": "missing", "reason": "insufficient_consecutive_history", "history_quarters": n}


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True])
def test_invalid_levels_fail_instead_of_becoming_missing(bad, protocol):
    values = signal(); values[3] = bad
    p = periods(40)
    with pytest.raises(ValueError, match="finite and strictly positive"):
        numerical_proxy_diagnostics(values, [q for _, q in p], [y for y, _ in p], protocol)


def test_duplicate_missing_out_of_order_or_misaligned_quarters_fail(protocol):
    p = periods(40)
    for altered in (p[:10] + p[11:], p[:10] + [p[9]] + p[11:], list(reversed(p))):
        with pytest.raises(ValueError, match="consecutive and ordered"):
            numerical_proxy_diagnostics(signal(len(altered)), [q for _, q in altered], [y for y, _ in altered], protocol)
    with pytest.raises(ValueError, match="Misaligned"):
        numerical_proxy_diagnostics(signal(), [1], [2011], protocol)


def test_documented_version_exports_complete_saved_evidence(scientific_fixture, protocol):
    root, vintage, cutoff = scientific_fixture
    result = estimate_output_gap(vintage, cutoff, protocol, root)
    assert result.status == "estimated" and result.history_quarters == 40
    assert len(result.input_evidence) == 41
    artifact = root / "endpoint.json"
    artifact.write_text(json.dumps({"result": result.to_dict()}))
    observation = observation_from_result(result, artifact.name, root)
    observation.verify_source(root)
    assert observation.field == "output_gap_pct"
    assert "100*expm1" in observation.transformation
    assert len(observation.input_evidence) == 41
    assert observation.released_at < cutoff


@pytest.mark.parametrize("state", ["unverified_edition", "retrieval_only"])
def test_edition_or_retrieval_is_not_historical_version_evidence(state, scientific_fixture, protocol):
    root, vintage, cutoff = scientific_fixture
    result = estimate_output_gap(replace(vintage, availability_state=state), cutoff, protocol, root)
    assert result.status == "missing" and result.output_gap_pct is None
    assert "retained_version_availability_not_documented" in result.reasons
    with pytest.raises(ValueError, match="missing output gap"):
        observation_from_result(result, "unused.json", root)


def test_proof_required_and_correct_source_version_required(scientific_fixture, protocol):
    root, vintage, cutoff = scientific_fixture
    missing = estimate_output_gap(replace(vintage, availability_evidence=()), cutoff, protocol, root)
    assert missing.status == "missing"
    wrong = vintage.availability_evidence[0].model_copy(update={"value": "another-vintage"})
    with pytest.raises(ValueError, match="does not identify"):
        estimate_output_gap(replace(vintage, availability_evidence=(wrong,)), cutoff, protocol, root)


def test_cutoff_equality_and_future_nested_release_fail_closed(scientific_fixture, protocol):
    root, vintage, cutoff = scientific_fixture
    at_release = vintage.inputs[0].evidence.released_at
    assert estimate_output_gap(vintage, at_release, protocol, root).status == "missing"
    child = vintage.availability_evidence[0].model_copy(update={"released_at": cutoff})
    nested = vintage.availability_evidence[0].model_copy(update={"input_evidence": (child,)})
    result = estimate_output_gap(replace(vintage, availability_evidence=(nested,)), cutoff, protocol, root)
    assert result.status == "missing" and "input_or_publication_proof_unavailable_at_cutoff" in result.reasons


def test_corruption_propagates_even_when_availability_is_missing(scientific_fixture, protocol):
    root, vintage, cutoff = scientific_fixture
    (root / vintage.inputs[0].evidence.source_file).write_text("corruption")
    with pytest.raises(ValueError, match="Source hash mismatch"):
        estimate_output_gap(replace(vintage, availability_state="unverified_edition"), cutoff, protocol, root)


def test_mixed_price_basis_vintages_and_invalid_quarter_fail(scientific_fixture, protocol):
    root, vintage, cutoff = scientific_fixture
    with pytest.raises(ValueError, match="price basis"):
        estimate_output_gap(replace(vintage, price_basis="GVA at basic prices"), cutoff, protocol, root)
    bad_evidence = vintage.inputs[1].evidence.model_copy(update={"vintage": "later-final-vintage"})
    inputs = (vintage.inputs[0], replace(vintage.inputs[1], evidence=bad_evidence), *vintage.inputs[2:])
    with pytest.raises(ValueError, match="Mixed source vintages"):
        estimate_output_gap(replace(vintage, inputs=inputs), cutoff, protocol, root)
    with pytest.raises(ValueError, match="fiscal quarter"):
        quarter_period(2020, True)


def test_naive_cutoff_unknown_protocol_and_saved_artifact_mismatch_fail(scientific_fixture, protocol, tmp_path):
    root, vintage, cutoff = scientific_fixture
    with pytest.raises(ValueError, match="timezone-aware"):
        estimate_output_gap(vintage, datetime(2021, 10, 1), protocol, root)
    with pytest.raises(ValueError, match="identified frozen protocol"):
        estimate_output_gap(vintage, cutoff, OutputGapProtocol(), root)
    with pytest.raises(ValueError, match="altered version1"):
        OutputGapProtocol(hp_lambda=400)
    result = estimate_output_gap(vintage, cutoff, protocol, root)
    artifact = root / "wrong.json"; artifact.write_text('{"result": {}}')
    with pytest.raises(ValueError, match="does not agree"):
        observation_from_result(result, artifact.name, root)
    with pytest.raises(ValueError, match="protocol hash mismatch"):
        OutputGapProtocol.from_file(artifact, "a" * 64)
