"""
Representative majority/casting and explicitly synthetic fragmentation controls.
Voting provisions are in RBI Act §45ZI; publication provisions are in §45ZL.
"""

import pytest
from src.rule_engine.engine import InstitutionalRuleEngine, AggregationResult

GOVERNOR = "shaktikanta_das"
MEMBERS = [
    "shaktikanta_das",
    "michael_patra",
    "rajiv_ranjan",
    "jayanth_varma",
    "ashima_goyal",
    "shashanka_bhide",
]


def test_unanimous_rate_vote():
    votes = {m: 0 for m in MEMBERS}
    result = InstitutionalRuleEngine.aggregate_rate_votes(votes, governor_id=GOVERNOR)
    assert result.winning_action == 0
    assert result.majority_achieved is True
    assert result.tie_broken_by_governor is False
    assert result.dissenting_members == []
    assert result.vote_tally == {0: 6}


def test_super_majority_5_1_rate_vote():
    # 5 vote 0, Varma dissents with -25
    votes = {m: 0 for m in MEMBERS}
    votes["jayanth_varma"] = -25

    result = InstitutionalRuleEngine.aggregate_rate_votes(votes, governor_id=GOVERNOR)
    assert result.winning_action == 0
    assert result.majority_achieved is True
    assert result.tie_broken_by_governor is False
    assert result.dissenting_members == ["jayanth_varma"]
    assert result.vote_tally == {0: 5, -25: 1}


def test_clear_majority_4_2_rate_vote():
    # 4 vote +25 (Das, Patra, Ranjan, Bhide), 2 vote 0 (Varma, Goyal)
    votes = {
        "shaktikanta_das": 25,
        "michael_patra": 25,
        "rajiv_ranjan": 25,
        "shashanka_bhide": 25,
        "jayanth_varma": 0,
        "ashima_goyal": 0,
    }
    result = InstitutionalRuleEngine.aggregate_rate_votes(votes, governor_id=GOVERNOR)
    assert result.winning_action == 25
    assert result.majority_achieved is True
    assert result.tie_broken_by_governor is False
    assert sorted(result.dissenting_members) == ["ashima_goyal", "jayanth_varma"]


def test_binary_3_3_tie_governor_casting_vote():
    # 3 internal members vote +25; 3 external members vote 0
    votes = {
        "shaktikanta_das": 25,
        "michael_patra": 25,
        "rajiv_ranjan": 25,
        "jayanth_varma": 0,
        "ashima_goyal": 0,
        "shashanka_bhide": 0,
    }
    result = InstitutionalRuleEngine.aggregate_rate_votes(votes, governor_id=GOVERNOR)
    # Governor voted +25, so +25 wins via §45ZI casting vote.
    assert result.winning_action == 25
    assert result.tie_broken_by_governor is True
    assert result.majority_achieved is False
    assert sorted(result.dissenting_members) == ["ashima_goyal", "jayanth_varma", "shashanka_bhide"]


def test_binary_3_3_tie_governor_votes_with_externals():
    # Governor + 2 externals vote -25; 2 internals + 1 external vote 0
    votes = {
        "shaktikanta_das": -25,
        "jayanth_varma": -25,
        "ashima_goyal": -25,
        "michael_patra": 0,
        "rajiv_ranjan": 0,
        "shashanka_bhide": 0,
    }
    result = InstitutionalRuleEngine.aggregate_rate_votes(votes, governor_id=GOVERNOR)
    assert result.winning_action == -25
    assert result.tie_broken_by_governor is True
    assert sorted(result.dissenting_members) == ["michael_patra", "rajiv_ranjan", "shashanka_bhide"]


def test_fragmented_rate_vote_fallback():
    # 2-2-2 split: 2 vote -25, 2 vote 0 (including Governor), 2 vote +25
    votes = {
        "jayanth_varma": -25,
        "ashima_goyal": -25,
        "shaktikanta_das": 0,
        "shashanka_bhide": 0,
        "michael_patra": 25,
        "rajiv_ranjan": 25,
    }
    with pytest.raises(ValueError,match='No majority'):
        InstitutionalRuleEngine.aggregate_rate_votes(votes, governor_id=GOVERNOR)
    result = InstitutionalRuleEngine.aggregate_rate_votes(votes, governor_id=GOVERNOR,
                                                         fragmentation_policy='legacy_synthetic')
    # The explicitly requested synthetic weighted median is 0.
    assert result.winning_action == 0
    assert result.majority_achieved is False
    assert sorted(result.dissenting_members) == ["ashima_goyal", "jayanth_varma", "michael_patra", "rajiv_ranjan"]


def test_stance_voting_majority():
    # 4 withdrawal_of_accommodation, 2 neutral
    votes = {
        "shaktikanta_das": "withdrawal_of_accommodation",
        "michael_patra": "withdrawal_of_accommodation",
        "rajiv_ranjan": "withdrawal_of_accommodation",
        "shashanka_bhide": "withdrawal_of_accommodation",
        "jayanth_varma": "neutral",
        "ashima_goyal": "neutral",
    }
    result = InstitutionalRuleEngine.aggregate_stance_votes(votes, governor_id=GOVERNOR)
    assert result.winning_action == "withdrawal_of_accommodation"
    assert result.majority_achieved is True
    assert sorted(result.dissenting_members) == ["ashima_goyal", "jayanth_varma"]


def test_stance_voting_3_3_tie():
    # 3 withdrawal_of_accommodation (internals including Governor), 3 neutral (externals)
    votes = {
        "shaktikanta_das": "withdrawal_of_accommodation",
        "michael_patra": "withdrawal_of_accommodation",
        "rajiv_ranjan": "withdrawal_of_accommodation",
        "jayanth_varma": "neutral",
        "ashima_goyal": "neutral",
        "shashanka_bhide": "neutral",
    }
    result = InstitutionalRuleEngine.aggregate_stance_votes(votes, governor_id=GOVERNOR)
    assert result.winning_action == "withdrawal_of_accommodation"
    assert result.tie_broken_by_governor is True
    assert sorted(result.dissenting_members) == ["ashima_goyal", "jayanth_varma", "shashanka_bhide"]


def test_rule_engine_validation_errors():
    # Less than 6 members
    with pytest.raises(ValueError, match="requires exactly 6"):
        InstitutionalRuleEngine.aggregate_rate_votes({"shaktikanta_das": 0}, governor_id=GOVERNOR)

    # Invalid action
    votes = {m: 0 for m in MEMBERS}
    votes["jayanth_varma"] = 99  # not in [-50, -25, 0, 25, 50]
    with pytest.raises(ValueError, match="outside valid action set"):
        InstitutionalRuleEngine.aggregate_rate_votes(votes, governor_id=GOVERNOR)

    # Governor missing
    votes_no_gov = {f"member_{i}": 0 for i in range(6)}
    with pytest.raises(ValueError, match="Governor.*must be present"):
        InstitutionalRuleEngine.aggregate_rate_votes(votes_no_gov, governor_id=GOVERNOR)
