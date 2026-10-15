"""Voting under RBI Act §45ZI(5),(7),(8), with explicit simulator assumptions.

Primary source: https://dea.gov.in/files/acts_documents/Chapter_IIIF_RBI_Act.pdf
§45ZL concerns publication of minutes, not casting votes. A six-voter simulation
is stricter than legal quorum. Multiaction fragmentation resolution is synthetic,
because a categorical menu is not the Act's vote on a specified question.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence, Optional

from src.schemas.decision_space import RATE_ACTIONS_BPS, STANCE_ACTIONS, validate_rate_action


@dataclass(frozen=True)
class AggregationResult:
    winning_action: Any
    vote_tally: dict[Any, int]
    tie_broken_by_governor: bool
    majority_achieved: bool
    dissenting_members: list[str]
    synthetic_resolution: bool = False
    resolution_policy: str = "majority"
    full_roster_simulation: bool = True
    members_present: int = 6


class InstitutionalRuleEngine:
    """Stateless voting; authority and synthetic choices remain separately labeled."""

    @staticmethod
    def validate_attendance(
        member_votes: dict[str, Any], governor_id: str, *, full_roster: bool = True,
        deputy_governor_id: Optional[str] = None,
        attending_member_ids: Optional[Sequence[str]] = None,
    ) -> None:
        if full_roster and len(member_votes) != 6:
            raise ValueError(f"Full-roster simulation requires exactly 6 member votes; received {len(member_votes)}")
        attendees = list(attending_member_ids) if attending_member_ids is not None else list(member_votes)
        if any(not isinstance(m, str) or not m for m in attendees) or len(set(attendees)) != len(attendees):
            raise ValueError("Attending member identities must be distinct nonempty strings")
        if any(not isinstance(m, str) or not m for m in member_votes):
            raise ValueError("Voter identities must be nonempty strings")
        if not set(member_votes).issubset(attendees):
            raise ValueError("A vote cannot be cast by an absent member")
        if not 4 <= len(attendees) <= 6:
            raise ValueError("RBI Act §45ZI(5) quorum requires 4 to 6 attending members")
        if full_roster and set(attendees) != set(member_votes):
            raise ValueError("Full-roster simulation requires all six attendees to vote")
        if governor_id not in attendees:
            if full_roster:
                raise ValueError(f"Governor {governor_id} must be present in member votes")
            if deputy_governor_id is None or deputy_governor_id not in attendees:
                raise ValueError("Quorum must include Governor, or Deputy Governor in Governor's absence")
        if not member_votes:
            raise ValueError("At least one member present must vote")

    @classmethod
    def _aggregate(
        cls, member_votes: dict[str, Any], governor_id: str, valid_actions: Sequence[Any], *,
        kind: str, full_roster: bool, deputy_governor_id: Optional[str],
        attending_member_ids: Optional[Sequence[str]], fragmentation_policy: str, prior_action: Any,
    ) -> AggregationResult:
        cls.validate_attendance(member_votes, governor_id, full_roster=full_roster,
                                deputy_governor_id=deputy_governor_id,
                                attending_member_ids=attending_member_ids)
        if fragmentation_policy not in ("reject", "legacy_synthetic", "status_quo"):
            raise ValueError("Unknown fragmentation policy")
        for member, vote in member_votes.items():
            if kind == "rate":
                try:
                    validate_rate_action(vote)
                except ValueError as exc:
                    raise ValueError(f"Vote {vote!r} by {member} is outside valid action set: {valid_actions}") from exc
            if vote not in valid_actions:
                raise ValueError(f"Vote {vote!r} by {member} is outside valid action set: {valid_actions}")
        tally = dict(Counter(member_votes.values()))
        top_action, top_count = max(tally.items(), key=lambda item: item[1])
        majority = top_count > len(member_votes) / 2
        casting = False
        synthetic = False
        policy = "majority"
        if majority:
            winner = top_action
        elif len(tally) == 2 and len(set(tally.values())) == 1 and governor_id in member_votes:
            winner = member_votes[governor_id]
            casting = True
            policy = "governor_casting_vote_45ZI_8"
        else:
            if fragmentation_policy == "reject":
                raise ValueError("No majority or Governor-resolvable binary equality; declare a synthetic resolution policy")
            synthetic = True
            policy = fragmentation_policy
            if fragmentation_policy == "status_quo":
                if prior_action not in valid_actions:
                    raise ValueError("Status-quo resolution requires a valid prior action")
                winner = prior_action
            else:
                if governor_id not in member_votes:
                    raise ValueError("Legacy synthetic fragmentation requires a Governor ballot")
                gov_action = member_votes[governor_id]
                if kind == "rate":
                    weighted = sorted([*member_votes.values(), gov_action])
                    winner = weighted[len(weighted) // 2]
                    policy = "synthetic_governor_weighted_median"
                else:
                    winner = top_action if list(tally.values()).count(top_count) == 1 else gov_action
                    policy = "synthetic_plurality_governor_priority"
        return AggregationResult(
            winning_action=winner, vote_tally=tally, tie_broken_by_governor=casting,
            majority_achieved=majority,
            dissenting_members=[m for m, action in member_votes.items() if action != winner],
            synthetic_resolution=synthetic, resolution_policy=policy,
            full_roster_simulation=full_roster,
            members_present=len(attending_member_ids) if attending_member_ids is not None else len(member_votes),
        )

    @classmethod
    def aggregate_rate_votes(
        cls, member_votes: dict[str, int], governor_id: str,
        valid_actions: Sequence[int] = RATE_ACTIONS_BPS, *, full_roster: bool = True,
        deputy_governor_id: Optional[str] = None, attending_member_ids: Optional[Sequence[str]] = None,
        fragmentation_policy: str = "reject", prior_action: int = 0,
    ) -> AggregationResult:
        return cls._aggregate(member_votes, governor_id, valid_actions, kind="rate",
                              full_roster=full_roster, deputy_governor_id=deputy_governor_id,
                              attending_member_ids=attending_member_ids,
                              fragmentation_policy=fragmentation_policy, prior_action=prior_action)

    @classmethod
    def aggregate_stance_votes(
        cls, member_votes: dict[str, str], governor_id: str,
        valid_stances: Sequence[str] = STANCE_ACTIONS, *, full_roster: bool = True,
        deputy_governor_id: Optional[str] = None, attending_member_ids: Optional[Sequence[str]] = None,
        fragmentation_policy: str = "reject", prior_action: Optional[str] = None,
    ) -> AggregationResult:
        return cls._aggregate(member_votes, governor_id, valid_stances, kind="stance",
                              full_roster=full_roster, deputy_governor_id=deputy_governor_id,
                              attending_member_ids=attending_member_ids,
                              fragmentation_policy=fragmentation_policy, prior_action=prior_action)
