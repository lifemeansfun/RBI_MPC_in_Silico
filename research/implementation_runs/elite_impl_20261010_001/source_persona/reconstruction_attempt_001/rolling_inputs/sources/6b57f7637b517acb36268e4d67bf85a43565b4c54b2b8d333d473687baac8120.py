"""Additive retrospective roster and dated-persona contracts.

These contracts do not change the simulator's existing three-stance menu.  A
source ontology and a simulator action ontology must be selected explicitly.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SOURCE_STANCE_ACTIONS_V2 = (
    "withdrawal_of_accommodation", "neutral", "accommodative", "calibrated_tightening"
)
LEGACY_STANCE_ACTIONS_V1 = SOURCE_STANCE_ACTIONS_V2[:3]
SourceStance = Literal[
    "withdrawal_of_accommodation", "neutral", "accommodative", "calibrated_tightening"
]
StanceOntology = Literal["simulator_v1", "expanded_source_v2"]


def validate_temporal_stance(value: str, *, ontology: StanceOntology) -> str:
    """Never substitute a different stance for an unsupported source category."""
    choices = {"simulator_v1": LEGACY_STANCE_ACTIONS_V1,
               "expanded_source_v2": SOURCE_STANCE_ACTIONS_V2}
    if ontology not in choices or value not in choices[ontology]:
        raise ValueError(f"Unsupported stance {value!r} in explicit ontology {ontology!r}")
    return value


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Expected an exact YYYY-MM-DD calendar day")
    return value


class TemporalContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class DatedSourceRef(TemporalContract):
    source_id: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str = Field(min_length=1)
    publication_date: str | None
    publication_status: Literal["verified_retained_header", "unresolved"]
    availability_precision: Literal["calendar_day_only"] = "calendar_day_only"
    publication_time: None = None
    historical_first_availability_verified: Literal[False] = False

    @field_validator("source_file")
    @classmethod
    def confined_path(cls, value):
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("Source paths must be relative and confined")
        return value

    @field_validator("publication_date")
    @classmethod
    def publication_day(cls, value):
        return None if value is None else _day(value)

    @model_validator(mode="after")
    def publication_contract(self):
        if (self.publication_status == "verified_retained_header") != (self.publication_date is not None):
            raise ValueError("Unknown publication timing must remain unresolved")
        return self


class TemporalMember(TemporalContract):
    member_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    role: Literal["Governor", "Deputy Governor", "Executive Director", "External Member"]
    is_internal: bool
    role_evidence_source: DatedSourceRef
    role_evidence_excerpt: str = Field(min_length=1)
    role_evidence_status: Literal["documented_role_at_observed_meeting"] = "documented_role_at_observed_meeting"

    @field_validator("is_internal", mode="before")
    @classmethod
    def actual_bool(cls, value):
        if type(value) is not bool:
            raise ValueError("Institutional affiliation requires an actual boolean")
        return value

    @model_validator(mode="after")
    def institutional_role(self):
        if self.is_internal != (self.role != "External Member"):
            raise ValueError("Role and institutional affiliation disagree")
        return self


class TemporalMeetingRoster(TemporalContract):
    meeting_id: str
    meeting_start_date: str
    decision_date: str
    information_cutoff: datetime
    members: tuple[TemporalMember, ...]
    governor_id: str
    roster_source: DatedSourceRef
    roster_source_excerpt: str = Field(min_length=1)
    roster_evidence_status: Literal["retrospective_oracle_attendance"] = "retrospective_oracle_attendance"
    roster_available_at_cutoff: Literal[False] = False
    appointment_dates: None = None
    predictive_roster_readiness: Literal["unverified_pre_cutoff_membership"] = "unverified_pre_cutoff_membership"
    panel_status: Literal["exposed_retrospective"] = "exposed_retrospective"

    @field_validator("meeting_start_date", "decision_date")
    @classmethod
    def real_day(cls, value):
        return _day(value)

    @model_validator(mode="after")
    def chronology_and_roster(self):
        if self.meeting_start_date > self.decision_date:
            raise ValueError("Meeting starts after its decision")
        cutoff = self.information_cutoff
        if (cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(hours=5, minutes=30)
                or cutoff.date().isoformat() != self.meeting_start_date
                or (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond) != (0, 0, 0, 0)):
            raise ValueError("Cutoff must be exclusive midnight IST on the first meeting day")
        ids = tuple(m.member_id for m in self.members)
        if len(ids) != 6 or len(set(ids)) != 6:
            raise ValueError("A realized roster requires six distinct canonical identities")
        governors = [m.member_id for m in self.members if m.role == "Governor"]
        if governors != [self.governor_id]:
            raise ValueError("Governor must be the unique Governor in the exact roster")
        if self.roster_source.publication_date is not None and self.roster_source.publication_date < self.decision_date:
            raise ValueError("Attendance source cannot be relabeled as a prior appointment announcement")
        if self.meeting_id != "rbi_mpc_" + self.decision_date:
            raise ValueError("Meeting identity must match the decision date")
        return self


class PersonalStatementRef(TemporalContract):
    statement_id: str
    member_id: str
    original_member_id: str
    meeting_id: str
    decision_date: str
    source: DatedSourceRef
    statement_file: str
    statement_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attribution_heading: str = Field(min_length=1)
    attribution_status: Literal["personal_heading_and_raw_bytes_verified"] = "personal_heading_and_raw_bytes_verified"

    @field_validator("decision_date")
    @classmethod
    def real_day(cls, value):
        return _day(value)

    @model_validator(mode="after")
    def chronology(self):
        if self.meeting_id != "rbi_mpc_" + self.decision_date:
            raise ValueError("Statement meeting and decision differ")
        if self.source.publication_date is not None and self.source.publication_date < self.decision_date:
            raise ValueError("A personal meeting statement cannot be published before its decision")
        path = PurePosixPath(self.statement_file)
        if path.is_absolute() or ".." in path.parts or "\\" in self.statement_file:
            raise ValueError("Statement path must be confined and relative")
        return self


class RollingPersonaPacket(TemporalContract):
    meeting_id: str
    member_id: str
    information_cutoff: datetime
    statements: tuple[PersonalStatementRef, ...]
    history_status: Literal["available_personal_history", "missing_personal_history"]
    lexical_orientation: float | None = Field(default=None, ge=-1, le=1)
    lexical_hawk_hits: int = Field(default=0, ge=0)
    lexical_dove_hits: int = Field(default=0, ge=0)
    construct_validated: Literal[False] = False
    missing_history_policy: Literal["explicit_missing_no_identity_substitution"] = "explicit_missing_no_identity_substitution"

    @model_validator(mode="after")
    def rolling_firewall(self):
        cutoff = self.information_cutoff
        if (cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(hours=5, minutes=30)
                or (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond) != (0, 0, 0, 0)):
            raise ValueError("Persona cutoff needs exclusive midnight IST")
        if not self.meeting_id.startswith("rbi_mpc_") or _day(self.meeting_id[8:]) < cutoff.date().isoformat():
            raise ValueError("Persona prediction meeting cannot predate the cutoff")
        present = bool(self.statements)
        if present != (self.history_status == "available_personal_history"):
            raise ValueError("History status must reflect actual source availability")
        if not present and (self.lexical_orientation is not None or self.lexical_hawk_hits or self.lexical_dove_hits):
            raise ValueError("Missing personal history cannot receive a fitted lexical score")
        if present and self.lexical_orientation != ((self.lexical_hawk_hits - self.lexical_dove_hits)
                                                   / max(self.lexical_hawk_hits + self.lexical_dove_hits, 1)):
            raise ValueError("Lexical statistic must equal its registered deterministic formula")
        identities = set()
        days = []
        for statement in self.statements:
            publication = statement.source.publication_date
            if (statement.member_id != self.member_id or statement.meeting_id == self.meeting_id
                    or publication is None or publication >= self.information_cutoff.date().isoformat()
                    or statement.decision_date >= self.information_cutoff.date().isoformat()):
                raise ValueError("Persona source is unavailable, same-meeting, future or belongs to another identity")
            if statement.meeting_id in identities:
                raise ValueError("Duplicate source meeting in one person's rolling corpus")
            identities.add(statement.meeting_id)
            days.append(statement.decision_date)
        if days != sorted(days):
            raise ValueError("Persona source order must be chronological")
        return self
