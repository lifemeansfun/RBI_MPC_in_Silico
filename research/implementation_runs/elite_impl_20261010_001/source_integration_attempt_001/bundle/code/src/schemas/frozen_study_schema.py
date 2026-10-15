"""Explicit ex ante specification for the paired, simulator-local experiment.

Engineering fixtures and exposed retrospective data never become untouched
evaluation through a readiness flag. Paths are portable locators, hashes are
identities; readiness receipts still require substantive external assessment.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.infra.evidence import safe_component


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, strict=True)


class FileRef(FrozenModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def portable(cls, value):
        from pathlib import PurePosixPath
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or "\\" in value or str(path) != value:
            raise ValueError("Frozen paths must be normalized relative POSIX paths")
        return value


class MeetingPacket(FrozenModel):
    meeting_date: str
    information_cutoff: str
    snapshot: FileRef
    personas: FileRef
    corpus_manifest: FileRef | None = None
    # Both roots resolve relative to the portable protocol directory.
    macro_source_root: str = "."
    persona_source_root: str = "."
    governor_id: str
    roster_ids: tuple[str, ...]
    exposure: Literal["exposed_retrospective", "development", "prospective", "engineering_fixture"]
    roster_basis: Literal["retrospective_oracle_attendance", "precutoff_appointment", "engineering_fixture"]
    history_policy: Literal["complete_dated_history", "engineering_fixture"]

    @field_validator("meeting_date")
    @classmethod
    def real_day(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Noncanonical meeting date")
        return value

    @model_validator(mode="after")
    def identities(self):
        cutoff = datetime.fromisoformat(self.information_cutoff)
        if cutoff.tzinfo is None or cutoff.date().isoformat() > self.meeting_date:
            raise ValueError("Cutoff must be timezone-aware and precede decision")
        if len(self.roster_ids) != 6 or len(set(self.roster_ids)) != 6 or self.governor_id not in self.roster_ids:
            raise ValueError("Exactly six distinct members and a declared Governor required")
        for value in (self.governor_id, *self.roster_ids):
            safe_component(value)
        for root in (self.macro_source_root, self.persona_source_root):
            if root != ".":
                FileRef(path=root, sha256="0" * 64)
        if self.history_policy == "complete_dated_history" and self.corpus_manifest is None:
            raise ValueError("Dated histories require a retained manifest")
        if self.exposure == "prospective" and self.roster_basis != "precutoff_appointment":
            raise ValueError("Prospective prediction cannot use oracle attendance")
        return self


class Resources(FrozenModel):
    max_live_calls: int = Field(ge=0)
    max_token_count_requests: int = Field(default=0, ge=0)
    max_provider_requests: int = Field(default=0, ge=0)
    max_spend_usd: float = Field(ge=0)
    input_token_bound: int = Field(gt=0)
    output_token_bound: int = Field(gt=0)
    max_elapsed_seconds: int = Field(gt=0)
    rate_limit_rpm: int = Field(gt=0)
    max_scientific_retries: Literal[0] = 0
    ledger_path: str | None = None
    ledger_cap_usd: float | None = Field(default=None, ge=0)
    accounting_receipt: FileRef | None = None


class GenerationSettings(FrozenModel):
    provider: Literal["mock", "gemini"]
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    model_epoch: str = Field(min_length=1)
    max_output_tokens: int = Field(gt=0)
    parser_version: Literal["strict-json-v1"] = "strict-json-v1"
    round_schema_hashes: dict[str, str]
    # A provider-reported identifier is observable; this does not certify weights.
    allowed_served_models: tuple[str, ...] = ()

    @field_validator("round_schema_hashes")
    @classmethod
    def schemas(cls, value):
        import re
        if set(value) != {"1", "2", "3", "4"} or any(not re.fullmatch(r"[0-9a-f]{64}", v) for v in value.values()):
            raise ValueError("Exact four-round schema hashes required")
        return value


class StudySpec(FrozenModel):
    version: Literal["paired-frozen-study-v1"] = "paired-frozen-study-v1"
    experiment_id: str
    evidence_track: Literal["engineering_mock", "registered_simulator_study"]
    estimand: Literal["mean_meeting_B_minus_H_joint_pair_agreement"] = "mean_meeting_B_minus_H_joint_pair_agreement"
    claim_scope: Literal["simulator_local_final_information_effect"] = "simulator_local_final_information_effect"
    conditions: tuple[Literal["H", "B", "N"], ...] = ("H", "B", "N")
    prefix_replicates: int = Field(gt=0)
    governor_draws: int = Field(gt=0)
    seed_base: int = Field(ge=0)
    settings: GenerationSettings
    resources: Resources
    meetings: tuple[MeetingPacket, ...]
    files: tuple[FileRef, ...]
    code_files: tuple[FileRef, ...]
    readiness_receipts: dict[str, FileRef] = Field(default_factory=dict)
    exclusions: tuple[dict, ...] = ()
    failure_policy: Literal["retain_planned_denominators_and_stop_on_error"] = "retain_planned_denominators_and_stop_on_error"
    condition_order: Literal["counterbalanced_six_permutations"] = "counterbalanced_six_permutations"
    artifact_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete_schedule(self):
        safe_component(self.experiment_id)
        if self.conditions != ("H", "B", "N") or not self.meetings:
            raise ValueError("Nonempty cohort and exact H/B/N design required")
        if len({m.meeting_date for m in self.meetings}) != len(self.meetings):
            raise ValueError("Duplicate meeting identity")
        for refs in (self.files, self.code_files):
            if not refs or len({r.path for r in refs}) != len(refs):
                raise ValueError("Nonempty unique input/code manifests required")
        files = {r.path: r.sha256 for r in self.files}
        for packet in self.meetings:
            for ref in (packet.snapshot, packet.personas, packet.corpus_manifest):
                if ref and files.get(ref.path) != ref.sha256:
                    raise ValueError("Meeting input differs from portable file manifest")
        for ref in (*self.readiness_receipts.values(), self.resources.accounting_receipt):
            if ref and files.get(ref.path) != ref.sha256:
                raise ValueError("Readiness/accounting receipt missing from file manifest")
        if self.evidence_track == "engineering_mock" and self.settings.provider != "mock":
            raise ValueError("Engineering fixture must explicitly use mock provider")
        if self.evidence_track == "registered_simulator_study":
            if self.settings.provider == "mock" or any(m.exposure == "engineering_fixture" for m in self.meetings):
                raise ValueError("Research cannot relabel engineering inputs/provider")
            if any(m.history_policy != "complete_dated_history" for m in self.meetings):
                raise ValueError("Research requires complete dated histories")
        if self.settings.max_output_tokens != self.resources.output_token_bound:
            raise ValueError("Output token freeze and resource bound differ")
        return self

    @property
    def planned_generation_calls(self):
        return len(self.meetings) * self.prefix_replicates * (23 + 3 * self.governor_draws)
