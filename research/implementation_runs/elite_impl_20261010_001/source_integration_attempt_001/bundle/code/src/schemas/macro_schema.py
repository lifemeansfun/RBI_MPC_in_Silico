"""Release-aware observables and separately labeled historical truth.
Legacy inputs remain readable and unverified; missing observations are never zero.
"""
from datetime import date, datetime
import hashlib
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from src.schemas.decision_space import StanceType

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def iso_day(value: str) -> str:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Expected a real calendar date in YYYY-MM-DD format")
    return value


class ObservationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    field: str
    value: float | str
    units: str
    reference_period: str
    vintage: str
    released_at: datetime
    source_url: str
    source_file: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_pointer: str = Field(min_length=1)
    availability_basis: str = Field(min_length=1)
    transformation: str | None = None
    input_evidence: tuple["ObservationEvidence", ...] = ()

    @field_validator("released_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Release timestamps need a timezone")
        return value

    def verify_source(self, root: Path = PROJECT_ROOT) -> None:
        path = (root / self.source_file).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError(f"Missing or outside-project source for {self.field}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.source_sha256:
            raise ValueError(f"Source hash mismatch for {self.field}")
        for item in self.input_evidence:
            item.verify_source(root)


OBSERVABLE_FIELDS = (
    "current_repo_rate_pct", "prev_stance", "cpi_headline_yoy_pct", "cpi_core_yoy_pct",
    "cpi_food_yoy_pct", "cfpi_yoy_pct", "iip_growth_yoy_pct", "gva_growth_yoy_pct",
    "gdp_growth_yoy_pct", "output_gap_pct", "system_liquidity_cr", "usd_inr_exchange_rate",
    "brent_crude_usd_bbl", "us_fed_funds_rate_pct", "monsoon_departure_lpa_pct")


class MacroMeetingSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)
    meeting_date: str
    meeting_start_date: str | None = None
    information_cutoff: datetime | None = None
    input_track: Literal["legacy_unverified", "source_linked", "synthetic", "counterfactual"] = "legacy_unverified"
    parent_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    intervention: dict = Field(default_factory=dict)
    current_repo_rate_pct: float = Field(ge=0, le=20)
    cpi_headline_yoy_pct: float
    cpi_core_yoy_pct: float | None = None
    cpi_food_yoy_pct: float | None = None
    cfpi_yoy_pct: float | None = None
    iip_growth_yoy_pct: float | None = None
    gva_growth_yoy_pct: float | None = None
    gdp_growth_yoy_pct: float | None = None
    output_gap_pct: float | None = None
    system_liquidity_cr: float | None = None
    usd_inr_exchange_rate: float | None = Field(default=None, ge=40, le=150)
    brent_crude_usd_bbl: float | None = Field(default=None, ge=10, le=250)
    us_fed_funds_rate_pct: float | None = Field(default=None, ge=0, le=20)
    monsoon_departure_lpa_pct: float | None = None
    prev_stance: StanceType = "withdrawal_of_accommodation"
    observations: tuple[ObservationEvidence, ...] = ()
    # Historical compatibility fields never enter the prompt.
    real_rate_decision_bps: int | None = None
    real_stance_decision: StanceType | None = None
    real_dissenters: list[str] = Field(default_factory=list)
    real_dissenters_rate: list[str] | None = None
    real_dissenters_stance: list[str] | None = None
    real_reservations: list[str] = Field(default_factory=list)
    real_guidance_disagreements: list[str] = Field(default_factory=list)

    @field_validator("meeting_date", "meeting_start_date")
    @classmethod
    def real_calendar_day(cls, value):
        return iso_day(value) if value is not None else None

    @model_validator(mode="after")
    def validate_information(self):
        if self.meeting_start_date and self.meeting_start_date > self.meeting_date:
            raise ValueError("Meeting start is after decision")
        if self.information_cutoff:
            if self.information_cutoff.tzinfo is None:
                raise ValueError("Information cutoff needs a timezone")
            if self.information_cutoff.date().isoformat() > (self.meeting_start_date or self.meeting_date):
                raise ValueError("Information cutoff is after meeting start")
        if self.input_track == "counterfactual" and (not self.parent_snapshot_hash or not self.intervention):
            raise ValueError("Counterfactual inputs require a parent hash and intervention record")
        if self.input_track != "source_linked":
            return self
        if not self.information_cutoff or not self.meeting_start_date:
            raise ValueError("Source-linked inputs require start and cutoff")
        evidence = {item.field: item for item in self.observations}
        if len(evidence) != len(self.observations):
            raise ValueError("Duplicate observation evidence")
        supplied = self.observable_values()
        if set(evidence) != set(supplied):
            raise ValueError(f"Evidence fields differ from supplied observations: {set(evidence) ^ set(supplied)}")
        def check(item):
            if item.released_at >= self.information_cutoff:
                raise ValueError(f"Future or unavailable release: {item.field}")
            for child in item.input_evidence:
                check(child)
        for name, item in evidence.items():
            if item.value != supplied[name]:
                raise ValueError(f"Observation/evidence value mismatch: {name}")
            check(item)
            if name == "output_gap_pct" and (not item.transformation or not item.input_evidence):
                raise ValueError("Output gap requires a recorded method and input vintages")
        return self

    def observable_values(self) -> dict:
        return {name: getattr(self, name) for name in OBSERVABLE_FIELDS if getattr(self, name) is not None}

    def verify_sources(self, root: Path = PROJECT_ROOT) -> None:
        if self.input_track != "source_linked":
            raise ValueError("Research requires source-linked observations")
        for item in self.observations:
            item.verify_source(root)

    def to_prompt_text(self, mask_date: bool = False) -> str:
        label = "date masked" if mask_date else self.meeting_date
        lines = [f"=== MACROECONOMIC INPUTS FOR SIMULATED MPC MEETING: {label} ===",
                 f"Input evidence track: {self.input_track}."]
        if self.information_cutoff is not None:
            lines.append('Information cutoff: absolute date masked; availability lags retained.' if mask_date else
                         f'Information cutoff (exclusive): {self.information_cutoff.isoformat()}.')
        evidence = {item.field:item for item in self.observations}
        descriptions = {
            "current_repo_rate_pct": "Current policy repo rate (%)", "prev_stance": "Prevailing stance",
            "cpi_headline_yoy_pct": "Combined headline CPI inflation (YoY %)",
            "cpi_core_yoy_pct": "Core CPI inflation (YoY %)",
            "cpi_food_yoy_pct": "CPI food and beverages inflation (YoY %)",
            "cfpi_yoy_pct": "Combined CFPI inflation (YoY %; distinct food index)",
            "iip_growth_yoy_pct": "Industrial production growth (YoY %)",
            "gva_growth_yoy_pct": "Real GVA growth (YoY %)", "gdp_growth_yoy_pct": "Real GDP growth (YoY %)",
            "output_gap_pct": "One-sided estimated output gap (%)", "system_liquidity_cr": "Net liquidity (INR crore)",
            "usd_inr_exchange_rate": "USD/INR exchange rate", "brent_crude_usd_bbl": "Brent crude (USD/barrel)",
            "us_fed_funds_rate_pct": "US federal funds target upper bound (%)",
            "monsoon_departure_lpa_pct": "Monsoon departure from LPA (%)",
        }
        for name, value in self.observable_values().items():
            rendered = f"{value:.2f}" if isinstance(value, float) else value
            lines.append(f"- {descriptions[name]}: {rendered}")
            item = evidence.get(name)
            if item is not None:
                if mask_date:
                    metadata = 'absolute reference, release and vintage labels masked'
                    if self.information_cutoff is not None:
                        lag = (self.information_cutoff-item.released_at).total_seconds()/86400
                        metadata += f'; release available {lag:.2f} days before cutoff'
                else:
                    metadata = (f'reference period={item.reference_period}; release={item.released_at.isoformat()}; '
                                f'vintage={item.vintage}')
                if self.input_track == 'counterfactual' and name in self.intervention.get('changed_fields',{}):
                    metadata = 'hypothetical changed value; evidence describes the parent value; '+metadata
                lines.append('  Observation metadata: '+metadata)
            else:
                lines.append('  Observation metadata: no source-linked release/vintage supplied for this value.')
        missing = [descriptions[name] for name in OBSERVABLE_FIELDS if getattr(self,name) is None]
        if missing:
            lines.append('Unavailable observations: '+', '.join(missing)+'.')
        lines.extend(["RBI inflation target: 4.00%, tolerance band 2.00%-6.00%.",
                      "Unlisted observations are unavailable. Do not impute them from knowledge of this historical meeting.",
                      "CRITICAL GROUNDING CONSTRAINT:",
                      "Ground reasoning ONLY in supplied observations. Do NOT cite fictitious numbers or invent macroeconomic indicators."])
        return "\n".join(lines)


MacroSnapshot = MacroMeetingSnapshot
