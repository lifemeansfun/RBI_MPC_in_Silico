"""
Reserve Bank of India Monetary Policy Committee (RBI MPC) Statutory Rule Engine.
Implements the voting and decision aggregation rules mandated under Section 45ZL
of the Reserve Bank of India Act, 1934:
- 6-member committee (3 internal RBI officials, 3 external government appointees).
- Decision determined by majority of members present and voting (>= 4 votes).
- In case of equality of votes (3-3 tie), Governor exercises a second / casting vote.
- Median-compromise fallback for fragmented non-binary splits.
- Independent dual aggregation for Policy Repo Rate and Policy Stance.
"""

from typing import Any, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AggregationResult:
    winning_action: Any
    vote_tally: dict[Any, int]
    tie_broken_by_governor: bool
    majority_achieved: bool
    dissenting_members: list[str]


class InstitutionalRuleEngine:
    """Pure, stateless implementation of the RBI MPC institutional voting mechanism."""

    @classmethod
    def aggregate_rate_votes(
        cls,
        member_votes: dict[str, int],
        governor_id: str,
        valid_actions: Sequence[int] = (-50, -25, 0, 25, 50),
    ) -> AggregationResult:
        """
        Aggregates policy repo rate votes in basis points.
        member_votes: mapping of member_id -> vote_bps (e.g. {'shaktikanta_das': 0, 'jayanth_varma': -25, ...})
        governor_id: member_id of the Governor holding the statutory casting vote
        """
        if len(member_votes) != 6:
            raise ValueError(f"RBI MPC requires exactly 6 member votes; received {len(member_votes)}")

        for member, vote in member_votes.items():
            if vote not in valid_actions:
                raise ValueError(f"Vote {vote} by {member} is outside valid action set: {valid_actions}")

        if governor_id not in member_votes:
            raise ValueError(f"Governor {governor_id} must be present in member votes")

        # Tally votes
        tally: dict[int, int] = {}
        for action in valid_actions:
            tally[action] = 0
        for vote in member_votes.values():
            tally[vote] += 1

        # Remove zero counts for cleaner representation
        active_tally = {k: v for k, v in tally.items() if v > 0}
        sorted_counts = sorted(active_tally.items(), key=lambda x: x[1], reverse=True)

        top_action, top_count = sorted_counts[0]
        governor_vote = member_votes[governor_id]

        # Case 1: Absolute majority (>= 4 votes)
        if top_count >= 4:
            winning_action = top_action
            tie_broken = False
            majority = True

        # Case 2: Exact binary 3-3 tie
        elif len(sorted_counts) == 2 and sorted_counts[0][1] == 3 and sorted_counts[1][1] == 3:
            # Under RBI Act Section 45ZL(2), Governor's casting vote decides
            winning_action = governor_vote
            tie_broken = True
            majority = False

        # Case 3: Fragmented non-binary split (e.g. 2-2-2, 3-2-1, 2-2-1-1)
        else:
            # Fallback: Vote-weighted median with Governor's vote weighted x2 (7 effective votes)
            weighted_votes = list(member_votes.values()) + [governor_vote]
            weighted_votes.sort()
            median_val = weighted_votes[len(weighted_votes) // 2]
            # Select discrete action closest to median
            winning_action = min(valid_actions, key=lambda a: abs(a - median_val))
            tie_broken = (winning_action == governor_vote)
            majority = False

        # Identify dissenters
        dissenting_members = [
            member for member, vote in member_votes.items() if vote != winning_action
        ]

        return AggregationResult(
            winning_action=winning_action,
            vote_tally=active_tally,
            tie_broken_by_governor=tie_broken,
            majority_achieved=majority,
            dissenting_members=dissenting_members,
        )

    @classmethod
    def aggregate_stance_votes(
        cls,
        member_votes: dict[str, str],
        governor_id: str,
        valid_stances: Sequence[str] = ("withdrawal_of_accommodation", "neutral", "accommodative"),
    ) -> AggregationResult:
        """
        Aggregates policy stance votes.
        member_votes: mapping of member_id -> stance string
        """
        if len(member_votes) != 6:
            raise ValueError(f"RBI MPC requires exactly 6 member votes; received {len(member_votes)}")

        for member, stance in member_votes.items():
            if stance not in valid_stances:
                raise ValueError(f"Stance '{stance}' by {member} is outside valid set: {valid_stances}")

        if governor_id not in member_votes:
            raise ValueError(f"Governor {governor_id} must be present in member votes")

        # Tally votes
        tally: dict[str, int] = {}
        for stance in valid_stances:
            tally[stance] = 0
        for stance in member_votes.values():
            tally[stance] += 1

        active_tally = {k: v for k, v in tally.items() if v > 0}
        sorted_counts = sorted(active_tally.items(), key=lambda x: x[1], reverse=True)

        top_stance, top_count = sorted_counts[0]
        governor_stance = member_votes[governor_id]

        # Case 1: Absolute majority (>= 4 votes)
        if top_count >= 4:
            winning_stance = top_stance
            tie_broken = False
            majority = True

        # Case 2: Exact binary 3-3 tie
        elif len(sorted_counts) == 2 and sorted_counts[0][1] == 3 and sorted_counts[1][1] == 3:
            winning_stance = governor_stance
            tie_broken = True
            majority = False

        # Case 3: Fragmented non-binary split (e.g. 2-2-2 or 3-2-1)
        else:
            # Plurality with Governor's proposal given casting weight
            governor_count = active_tally.get(governor_stance, 0)
            if top_count == 3 and top_stance == governor_stance:
                winning_stance = governor_stance
                tie_broken = False
            elif top_count == 3 and top_stance != governor_stance:
                # 3 non-gov vs (2+1) or (3 non-gov vs 3 gov-side)
                winning_stance = top_stance
                tie_broken = False
            else:
                # 2-2-2 split: Governor's stance prevails
                winning_stance = governor_stance
                tie_broken = True
            majority = False

        dissenting_members = [
            member for member, stance in member_votes.items() if stance != winning_stance
        ]

        return AggregationResult(
            winning_action=winning_stance,
            vote_tally=active_tally,
            tie_broken_by_governor=tie_broken,
            majority_achieved=majority,
            dissenting_members=dissenting_members,
        )
