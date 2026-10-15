"""Strict simulator outputs. Invalid provider decisions are never silently repaired."""

from typing import Literal, Optional, Any
from collections import Counter
from datetime import date
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from src.schemas.decision_space import RATE_ACTIONS_BPS, STANCE_ACTIONS, RateActionBps, StanceType, validate_rate_action

VALID_ACTIONS_BPS = RATE_ACTIONS_BPS


class StrictRoundOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)
    member_id: str = Field(min_length=1)
    fallback_triggered: bool = False

    @field_validator("*", mode="after")
    @classmethod
    def nonempty_text(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Identity and rationale text cannot be whitespace only")
        return value


class InitialStanceOutput(StrictRoundOutput):
    member_name: str = Field(min_length=1)
    proposed_rate_change_bps: RateActionBps
    proposed_stance: StanceType
    key_rationale: str = Field(min_length=1)
    _rate_domain = field_validator("proposed_rate_change_bps", mode="before")(validate_rate_action)


class DeliberationOutput(StrictRoundOutput):
    round_number: Literal[2, 3]
    current_rate_preference_bps: RateActionBps
    current_stance_preference: StanceType
    rebuttal_or_critique: str = Field(min_length=1)
    open_to_compromise: bool = False
    _rate_domain = field_validator("current_rate_preference_bps", mode="before")(validate_rate_action)

    @field_validator("round_number", mode="before")
    @classmethod
    def strict_round(cls, value: object) -> int:
        if type(value) is not int or value not in (2, 3):
            raise ValueError("Deliberation round must be integer 2 or 3")
        return value


class FinalVoteOutput(StrictRoundOutput):
    member_name: str = Field(min_length=1)
    is_internal: bool = True
    final_rate_vote_bps: RateActionBps
    final_stance_vote: StanceType
    dissenting_on_rate: bool = False
    dissenting_on_stance: bool = False
    official_statement_rationale: str = Field(min_length=1)
    _rate_domain = field_validator("final_rate_vote_bps", mode="before")(validate_rate_action)


def validate_member_output(
    output: StrictRoundOutput, *, member_id: str, round_number: int,
    member_name: Optional[str] = None, is_internal: Optional[bool] = None,
) -> StrictRoundOutput:
    """Bind output to its expected request; revalidate even manually mutated models."""
    schema = {1: InitialStanceOutput, 2: DeliberationOutput, 3: DeliberationOutput, 4: FinalVoteOutput}.get(round_number)
    if schema is None or not isinstance(output, schema):
        raise ValueError(f"Unexpected output schema for Round {round_number}")
    validated = schema.model_validate(output.model_dump())
    if validated.member_id != member_id:
        raise ValueError(f"Output member_id {validated.member_id!r} differs from requested {member_id!r}")
    if isinstance(validated, DeliberationOutput) and validated.round_number != round_number:
        raise ValueError(f"Output round differs from requested Round {round_number}")
    if member_name is not None and getattr(validated, "member_name", member_name) != member_name:
        raise ValueError("Output member_name differs from the requested member")
    if is_internal is not None and getattr(validated, "is_internal", is_internal) != is_internal:
        raise ValueError("Output institutional role differs from the requested member")
    if validated.fallback_triggered:
        raise ValueError("Heuristic fallback is not permitted as research generation")
    return validated


class MeetingCommitteeDecision(BaseModel):
    """Simulator outcome and declared information/voting assumptions and evidence labels."""
    model_config = ConfigDict(extra="forbid", validate_assignment=True, strict=True)
    meeting_date: str
    replicate_id: int = Field(ge=1)
    rate_decision_bps: RateActionBps
    stance_decision: StanceType
    rate_vote_tally: dict[int, int]
    stance_vote_tally: dict[str, int]
    tie_broken_by_governor_rate: bool
    tie_broken_by_governor_stance: bool
    dissenting_members_rate: list[str]
    dissenting_members_stance: list[str]
    member_votes: list[FinalVoteOutput]
    fallbacks_count: int = Field(default=0, ge=0)
    prior_stance: Optional[StanceType] = None
    experiment_id: str = "legacy"
    condition_id: str = "full"
    control_mode: Literal["full", "earlier_rounds", "independent"] = "full"
    visibility: dict[str, Any] = Field(default_factory=dict)
    seed_schedule: dict[str, int] = Field(default_factory=dict)
    seed_schedule_version: str = "paired-member-round-v1"
    seed_base: int = 42
    governor_id: Optional[str] = None
    snapshot_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    persona_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generation_settings: dict[str, Any] = Field(default_factory=dict)
    generation_count: int = Field(default=0, ge=0)
    evidence_types: list[str] = Field(default_factory=list)
    input_track: str = "legacy_unverified"
    full_roster_simulation: bool = True
    rate_resolution_policy: str = "unspecified_legacy"
    stance_resolution_policy: str = "unspecified_legacy"
    synthetic_resolution_rate: bool = False
    synthetic_resolution_stance: bool = False
    fragmentation_policy: Literal["reject", "legacy_synthetic", "status_quo"] = "reject"
    _rate_domain = field_validator("rate_decision_bps", mode="before")(validate_rate_action)

    @field_validator("meeting_date")
    @classmethod
    def real_date(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Meeting date must be a real ISO calendar day")
        return value

    @field_validator("replicate_id", mode="before")
    @classmethod
    def strict_replicate(cls, value):
        if type(value) is not int or value < 1:
            raise ValueError("Replicate must be a positive integer")
        return value

    @field_validator("rate_vote_tally", "stance_vote_tally", mode="before")
    @classmethod
    def strict_tally(cls, value, info):
        if not isinstance(value, dict) or not value:
            raise ValueError("Vote tally must be a nonempty dictionary")
        normalized = {}
        for action, count in value.items():
            if type(count) is not int or count < 1:
                raise ValueError("Tally counts must be positive integers")
            if info.field_name == "rate_vote_tally":
                # JSON object keys are strings; only canonical action spellings are accepted.
                if isinstance(action, str):
                    try:
                        parsed = int(action)
                    except ValueError as exc:
                        raise ValueError("Unknown rate tally action") from exc
                    if str(parsed) != action:
                        raise ValueError("Noncanonical rate tally action")
                    validate_rate_action(parsed)
                    action = parsed
                else:
                    validate_rate_action(action)
            elif action not in STANCE_ACTIONS:
                raise ValueError("Unknown stance tally action")
            if action in normalized:
                raise ValueError("Duplicate canonical vote-tally action")
            normalized[action] = count
        return normalized

    @model_validator(mode="after")
    def reconcile_ballots(self):
        if sum(self.rate_vote_tally.values()) != sum(self.stance_vote_tally.values()):
            raise ValueError("Rate and stance tally voter counts differ")
        for winner, synthetic, tally in (
            (self.rate_decision_bps, self.synthetic_resolution_rate, self.rate_vote_tally),
            (self.stance_decision, self.synthetic_resolution_stance, self.stance_vote_tally),
        ):
            if not synthetic and winner not in tally:
                raise ValueError("Nonsynthetic decision must be one of the supplied ballots")
        if (len(self.dissenting_members_rate) != len(set(self.dissenting_members_rate))
                or len(self.dissenting_members_stance) != len(set(self.dissenting_members_stance))):
            raise ValueError("Duplicate dissent labels")
        for tied, synthetic, tally in (
            (self.tie_broken_by_governor_rate, self.synthetic_resolution_rate, self.rate_vote_tally),
            (self.tie_broken_by_governor_stance, self.synthetic_resolution_stance, self.stance_vote_tally),
        ):
            if tied and (synthetic or len(tally) != 2 or len(set(tally.values())) != 1):
                raise ValueError("Casting flag must represent binary equality, not synthetic fragmentation")
        if self.member_votes:
            if self.full_roster_simulation and len(self.member_votes) != 6:
                raise ValueError("Full-roster decision requires six member ballots")
            if len({v.member_id for v in self.member_votes}) != len(self.member_votes):
                raise ValueError("Duplicate member ballots")
            rates = dict(Counter(v.final_rate_vote_bps for v in self.member_votes))
            stances = dict(Counter(v.final_stance_vote for v in self.member_votes))
            if rates != self.rate_vote_tally or stances != self.stance_vote_tally:
                raise ValueError("Tallies do not match supplied member ballots")
            rate_dissent = {v.member_id for v in self.member_votes if v.final_rate_vote_bps != self.rate_decision_bps}
            stance_dissent = {v.member_id for v in self.member_votes if v.final_stance_vote != self.stance_decision}
            if rate_dissent != set(self.dissenting_members_rate) or stance_dissent != set(self.dissenting_members_stance):
                raise ValueError("Dissent labels do not match supplied member ballots")
            if any(v.dissenting_on_rate != (v.member_id in rate_dissent)
                   or v.dissenting_on_stance != (v.member_id in stance_dissent) for v in self.member_votes):
                raise ValueError("Member dissent flags do not match supplied ballots")
            if self.governor_id is not None:
                from src.rule_engine.engine import InstitutionalRuleEngine
                rate = InstitutionalRuleEngine.aggregate_rate_votes(
                    {v.member_id: v.final_rate_vote_bps for v in self.member_votes}, self.governor_id,
                    full_roster=self.full_roster_simulation, fragmentation_policy=self.fragmentation_policy, prior_action=0)
                stance = InstitutionalRuleEngine.aggregate_stance_votes(
                    {v.member_id: v.final_stance_vote for v in self.member_votes}, self.governor_id,
                    full_roster=self.full_roster_simulation, fragmentation_policy=self.fragmentation_policy, prior_action=self.prior_stance)
                for result, winner, casting, synthetic, policy in (
                    (rate, self.rate_decision_bps, self.tie_broken_by_governor_rate, self.synthetic_resolution_rate, self.rate_resolution_policy),
                    (stance, self.stance_decision, self.tie_broken_by_governor_stance, self.synthetic_resolution_stance, self.stance_resolution_policy),
                ):
                    if (result.winning_action != winner or result.tie_broken_by_governor != casting
                            or result.synthetic_resolution != synthetic or result.resolution_policy != policy):
                        raise ValueError("Committee decision or resolution metadata differs from declared voting rule")
            if self.generation_count or self.seed_schedule:
                rounds = (1, 4) if self.control_mode == "independent" else (1, 2, 3, 4)
                expected_seeds = {f"{v.member_id}:round_{r}" for v in self.member_votes for r in rounds}
                if self.generation_count != len(expected_seeds) or set(self.seed_schedule) != expected_seeds:
                    raise ValueError("Generation count or seed keys differ from declared protocol")
        return self
