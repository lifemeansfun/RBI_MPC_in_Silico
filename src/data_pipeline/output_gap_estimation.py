"""Causal statistical GDP proxies with a separate, strict vintage-evidence gate.

The numerical helper is deliberately usable for ex-post diagnostics. It does not
certify that a downloaded historical table existed at an earlier policy cutoff.
Only ``estimate_output_gap`` can return a historical candidate, and that path
requires explicit evidence tied to the particular source version. Neither path
measures potential output or produces a calibrated uncertainty interval.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Literal

import numpy as np

from src.schemas.macro_schema import ObservationEvidence

PRICE_BASIS = "GDP at market prices, constant 2011-12 prices, INR crore"
GDP_FIELD = "gdp_constant_2011_12_crore"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quarter_period(fiscal_year: int, quarter: int) -> tuple[str, date, date]:
    """Return an Indian fiscal quarter label and its actual calendar bounds."""
    if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int) or not 1900 <= fiscal_year <= 9998:
        raise ValueError("Invalid fiscal year")
    if isinstance(quarter, bool) or not isinstance(quarter, int) or quarter not in (1, 2, 3, 4):
        raise ValueError("Invalid fiscal quarter")
    month = {1: 4, 2: 7, 3: 10, 4: 1}[quarter]
    year = fiscal_year + (quarter == 4)
    start = date(year, month, 1)
    end = date(year + (month == 10), (month + 2) % 12 + 1, 1) - timedelta(days=1)
    return f"FY{fiscal_year}-{str(fiscal_year + 1)[-2:]}Q{quarter}", start, end


@dataclass(frozen=True)
class QuarterlyGDPInput:
    fiscal_year: int
    quarter: int
    evidence: ObservationEvidence

    def validate(self) -> None:
        label, _, end = quarter_period(self.fiscal_year, self.quarter)
        value = self.evidence.value
        if self.evidence.field != GDP_FIELD or self.evidence.reference_period != label:
            raise ValueError("GDP field or reference-quarter evidence mismatch")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("GDP levels must be finite and strictly positive")
        if end >= self.evidence.released_at.date():
            raise ValueError("Observed quarter must end before its availability bound")


@dataclass(frozen=True)
class GDPVintage:
    vintage_id: str
    inputs: tuple[QuarterlyGDPInput, ...]
    price_basis: str = PRICE_BASIS
    availability_state: Literal["documented_version", "retrieval_only", "unverified_edition"] = "unverified_edition"
    availability_evidence: tuple[ObservationEvidence, ...] = ()
    availability_note: str = ""


@dataclass(frozen=True)
class OutputGapProtocol:
    version: str = "rbi-output-gap-proxy-v1"
    minimum_quarters: int = 28
    hp_lambda: float = 1600.0
    protocol_sha256: str = ""

    def __post_init__(self):
        if self.version != "rbi-output-gap-proxy-v1" or self.minimum_quarters != 28 or self.hp_lambda != 1600:
            raise ValueError("Unsupported or altered version1 estimator parameters")
        if self.protocol_sha256 and not re.fullmatch(r"[a-f0-9]{64}", self.protocol_sha256):
            raise ValueError("Invalid protocol digest")

    @classmethod
    def from_file(cls, path: Path | str, expected_sha256: str) -> "OutputGapProtocol":
        path = Path(path)
        if _sha(path) != expected_sha256:
            raise ValueError("Frozen output-gap protocol hash mismatch")
        data = json.loads(path.read_text())
        if data["version"] != "rbi-output-gap-proxy-v1":
            raise ValueError("Unsupported output-gap protocol")
        primary = data["primary"]
        if primary["minimum_consecutive_quarters"] != 28 or primary["hp_lambda"] != 1600:
            raise ValueError("Version1 primary parameters differ from frozen specification")
        return cls(protocol_sha256=expected_sha256)


@dataclass(frozen=True)
class OutputGapResult:
    status: Literal["estimated", "missing"]
    reasons: tuple[str, ...]
    cutoff_exclusive: str
    vintage_id: str
    history_quarters: int
    reference_period: str | None
    output_gap_pct: float | None
    output_gap_log_percentage_points: float | None
    protocol_version: str
    protocol_sha256: str
    implementation_sha256: str
    input_sha256: str
    input_evidence: tuple[ObservationEvidence, ...]
    diagnostics: dict

    def to_dict(self) -> dict:
        return {
            "status": self.status, "reasons": list(self.reasons),
            "cutoff_exclusive": self.cutoff_exclusive, "vintage_id": self.vintage_id,
            "history_quarters": self.history_quarters, "reference_period": self.reference_period,
            "output_gap_pct": self.output_gap_pct,
            "output_gap_log_percentage_points": self.output_gap_log_percentage_points,
            "protocol_version": self.protocol_version, "protocol_sha256": self.protocol_sha256,
            "implementation_sha256": self.implementation_sha256, "input_sha256": self.input_sha256,
            "input_evidence": [item.model_dump(mode="json") for item in self.input_evidence],
            "diagnostics": self.diagnostics,
        }


def _fit_proxy(levels, quarters, hp_lambda: float, seasonal_training_length: int | None = None) -> dict:
    values = np.asarray(levels, dtype=float)
    q = np.asarray(quarters, dtype=int)
    if values.ndim != 1 or q.shape != values.shape or len(values) < 3:
        raise ValueError("Expected at least three aligned one-dimensional observations")
    if not np.all(np.isfinite(values)) or np.any(values <= 0) or np.any((q < 1) | (q > 4)):
        raise ValueError("Invalid GDP level or quarter")
    if isinstance(hp_lambda, bool) or not math.isfinite(hp_lambda) or hp_lambda <= 0:
        raise ValueError("HP lambda must be finite and positive")
    # Centering avoids dependence on the arbitrary level/units of GDP.
    x = np.log(values)
    center = float(np.mean(x))
    x_centered = x - center
    t = np.arange(len(values), dtype=float)
    t -= float(np.mean(t))
    # The fourth quarter effect is minus the first three: sum(s_q) = 0.
    seasonal_design = np.column_stack([(q == k).astype(float) - (q == 4).astype(float) for k in (1, 2, 3)])
    design = np.column_stack([np.ones(len(values)), t, seasonal_design])
    training = len(values) if seasonal_training_length is None else seasonal_training_length
    if isinstance(training, bool) or not isinstance(training, int) or not 3 <= training <= len(values):
        raise ValueError("Invalid seasonal training prefix")
    if np.linalg.matrix_rank(design[:training]) != 5:
        raise ValueError("Seasonal design is not identified")
    coefficients, _, _, _ = np.linalg.lstsq(design[:training], x_centered[:training], rcond=None)
    seasonal = seasonal_design @ coefficients[2:]
    adjusted = x_centered - seasonal
    difference = np.diff(np.eye(len(values)), n=2, axis=0)
    system = np.eye(len(values)) + float(hp_lambda) * difference.T @ difference
    trend = np.linalg.solve(system, adjusted)
    cycle = adjusted - trend
    if not np.all(np.isfinite(trend)) or not np.all(np.isfinite(cycle)):
        raise ValueError("Nonfinite statistical trend/cycle")
    exact = 100.0 * math.expm1(float(cycle[-1]))
    if not math.isfinite(exact):
        raise ValueError("Nonfinite output-gap transformation")
    effects = [*map(float, coefficients[2:]), -float(np.sum(coefficients[2:]))]
    return {
        "provenance_scope": "Numerical proxy only; vintage eligibility requires the separate evidence gate",
        "output_gap_pct": exact, "output_gap_log_percentage_points": 100.0 * float(cycle[-1]),
        "hp_lambda": float(hp_lambda), "history_quarters": len(values),
        "seasonal_training_quarters": training, "seasonal_effects_log": effects,
        "ols_coefficients_centered_log": list(map(float, coefficients)),
        "log_center": center, "seasonally_adjusted_log_gdp": list(map(float, adjusted + center)),
        "statistical_log_trend": list(map(float, trend + center)),
        "log_cycle": list(map(float, cycle)),
        "normal_equation_max_absolute_residual": float(np.max(np.abs(system @ trend - adjusted))),
    }


def numerical_proxy_diagnostics(levels, quarters, fiscal_years, protocol: OutputGapProtocol) -> dict:
    """Compute frozen ex-post sensitivities without certifying vintage availability.

    Each prefix endpoint is causal conditional on the supplied GDP vector. Interior
    points of a longer fit are explicitly ex-post revision diagnostics, not inputs
    for earlier decisions.
    """
    levels, quarters, fiscal_years = tuple(levels), tuple(quarters), tuple(fiscal_years)
    if not (len(levels) == len(quarters) == len(fiscal_years)):
        raise ValueError("Misaligned GDP metadata")
    ordinals = [4 * y + q - 1 for y, q in zip(fiscal_years, quarters)]
    for y, q in zip(fiscal_years, quarters):
        quarter_period(y, q)
    if any(right != left + 1 for left, right in zip(ordinals, ordinals[1:])):
        raise ValueError("GDP history must be consecutive and ordered")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in levels):
        raise ValueError("GDP levels must be finite and strictly positive")
    counts = {q: quarters.count(q) for q in (1, 2, 3, 4)}
    if len(levels) < protocol.minimum_quarters or min(counts.values()) < 7:
        return {"status": "missing", "reason": "insufficient_consecutive_history", "history_quarters": len(levels)}
    primary = _fit_proxy(levels, quarters, protocol.hp_lambda)
    sensitivities = {f"hp_lambda_{n}": _fit_proxy(levels, quarters, n) for n in (400, 6400)}
    sensitivities["minimum_40_expanding_coverage"] = (
        {"status": "eligible", "output_gap_pct": primary["output_gap_pct"]} if len(levels) >= 40
        else {"status": "missing", "reason": "fewer_than_40_quarters"})
    sensitivities["trailing_40"] = (
        _fit_proxy(levels[-40:], quarters[-40:], protocol.hp_lambda) if len(levels) >= 40
        else {"status": "missing", "reason": "fewer_than_40_quarters"})
    # Calendar 2019Q4 is fiscal2019-20Q3. Jan-Mar2020 is not part of this sensitivity's training prefix.
    pre_covid = sum(quarter_period(y, q)[2] <= date(2019, 12, 31) for y, q in zip(fiscal_years, quarters))
    sensitivities["fixed_pre_covid_seasonality"] = (
        _fit_proxy(levels, quarters, protocol.hp_lambda, pre_covid) if pre_covid >= 28
        else {"status": "missing", "reason": "fewer_than_28_pre_covid_quarters"})
    return {"status": "computed_numerical_diagnostic", "historical_availability_certified": False,
            "primary": primary, "sensitivities": sensitivities,
            "uncertainty_interpretation": "Estimator sensitivity, not a fitted confidence interval"}


def estimate_output_gap(vintage: GDPVintage, cutoff: datetime, protocol: OutputGapProtocol,
                        source_root: Path) -> OutputGapResult:
    """Fail closed on unknown version availability; verify all raw/proof hashes."""
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Information cutoff must be timezone-aware")
    if not protocol.protocol_sha256:
        raise ValueError("Strict estimation requires an identified frozen protocol")
    if vintage.price_basis != PRICE_BASIS or not vintage.vintage_id:
        raise ValueError("Unknown GDP price basis or empty vintage identity")
    if vintage.availability_state not in ("documented_version", "retrieval_only", "unverified_edition"):
        raise ValueError("Unknown version-availability state")
    records = tuple(vintage.inputs)
    for record in records:
        record.validate()
        if record.evidence.vintage != vintage.vintage_id:
            raise ValueError("Mixed source vintages are excluded by version1")
        record.evidence.verify_source(source_root)
    for proof in vintage.availability_evidence:
        if (proof.field != "gdp_version_availability" or proof.value != vintage.vintage_id
                or proof.vintage != vintage.vintage_id):
            raise ValueError("Publication evidence does not identify this GDP source version")
        proof.verify_source(source_root)
    inputs = tuple(record.evidence for record in records) + tuple(vintage.availability_evidence)
    payload = json.dumps([item.model_dump(mode="json") for item in inputs], sort_keys=True, allow_nan=False).encode()
    # Validate contiguity and positivity even if the scientific evidence gate is missing.
    numbers = numerical_proxy_diagnostics if records else None
    ordinals = [4 * record.fiscal_year + record.quarter - 1 for record in records]
    if any(right != left + 1 for left, right in zip(ordinals, ordinals[1:])):
        raise ValueError("GDP history must be consecutive and ordered")
    reasons = []
    if vintage.availability_state != "documented_version" or not vintage.availability_evidence:
        reasons.append("retained_version_availability_not_documented")
    def unavailable(item):
        return item.released_at >= cutoff or any(unavailable(child) for child in item.input_evidence)
    if any(unavailable(item) for item in inputs):
        reasons.append("input_or_publication_proof_unavailable_at_cutoff")
    counts = [sum(record.quarter == q for record in records) for q in (1, 2, 3, 4)]
    if len(records) < protocol.minimum_quarters or min(counts) < 7:
        reasons.append("insufficient_consecutive_history")
    diagnostic = {"availability_state": vintage.availability_state,
        "availability_note": vintage.availability_note, "price_basis": vintage.price_basis,
        "source_ready": bool(records), "historical_input_ready": not reasons,
        "proxy_is_measured_potential_output": False, "exhaustive_revision_completeness_claimed": False}
    result = None
    if not reasons:
        result = numbers([r.evidence.value for r in records], [r.quarter for r in records],
                         [r.fiscal_year for r in records], protocol)
        diagnostic.update(result)
        diagnostic["historical_availability_certified"] = True
    return OutputGapResult(status="missing" if reasons else "estimated", reasons=tuple(reasons),
        cutoff_exclusive=cutoff.isoformat(), vintage_id=vintage.vintage_id, history_quarters=len(records),
        reference_period=records[-1].evidence.reference_period if records else None,
        output_gap_pct=result["primary"]["output_gap_pct"] if result else None,
        output_gap_log_percentage_points=result["primary"]["output_gap_log_percentage_points"] if result else None,
        protocol_version=protocol.version, protocol_sha256=protocol.protocol_sha256,
        implementation_sha256=_sha(Path(__file__)), input_sha256=hashlib.sha256(payload).hexdigest(),
        input_evidence=inputs, diagnostics=diagnostic)


def observation_from_result(result: OutputGapResult, artifact_file: Path | str,
                            source_root: Path) -> ObservationEvidence:
    """Export only a successful candidate after its numerical artifact is saved."""
    if result.status != "estimated" or result.output_gap_pct is None:
        raise ValueError("A missing output gap cannot become observation evidence")
    root = Path(source_root).resolve()
    path = (root / artifact_file).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Missing or outside-root derived artifact")
    if json.loads(path.read_text()).get("result") != result.to_dict():
        raise ValueError("Saved numerical artifact does not agree with output-gap result")
    release = max(item.released_at for item in result.input_evidence)
    return ObservationEvidence(field="output_gap_pct", value=result.output_gap_pct,
        units="Percent deviation from one-sided statistical log trend; not measured potential output",
        reference_period=result.reference_period, vintage=result.vintage_id,
        released_at=release, source_url=result.input_evidence[0].source_url,
        source_file=str(path.relative_to(root)), source_sha256=_sha(path),
        source_pointer="Saved result.primary endpoint, full GDP vector and publication/version evidence",
        availability_basis="Retrospective derived proxy; released_at is the latest documented input availability bound, not a historical official publication of the gap",
        transformation=f"{result.protocol_version}; protocol_sha256={result.protocol_sha256}; implementation_sha256={result.implementation_sha256}; log quarter-dummy OLS, endpoint HP1600, 100*expm1(log_cycle)",
        input_evidence=result.input_evidence)
