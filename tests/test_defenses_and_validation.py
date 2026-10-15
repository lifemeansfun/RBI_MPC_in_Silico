"""Research outputs fail closed; prompts disclose evidence scope and missing inputs."""
import pytest
from pydantic import ValidationError
from src.schemas.debate_schema import InitialStanceOutput, FinalVoteOutput
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.schemas.persona_schema import MemberPersona


@pytest.mark.parametrize('rate', ['+25 bps', '48', 48, True, float('nan'), float('inf')])
def test_invalid_rates_cannot_be_silently_repaired(rate):
    with pytest.raises(ValidationError):
        InitialStanceOutput(member_id='member', member_name='Member', proposed_rate_change_bps=rate,
                            proposed_stance='neutral', key_rationale='Supplied evidence')


def test_unknown_stance_cannot_be_normalized_into_a_vote():
    with pytest.raises(ValidationError):
        FinalVoteOutput(member_id='member',member_name='Member',final_rate_vote_bps=35,
                        final_stance_vote='WITHDRAWAL OF ACCOMMODATION',official_statement_rationale='Evidence')


def test_anti_hallucination_macro_prompt_constraints():
    snapshot=MacroMeetingSnapshot(meeting_date='2023-08-10',current_repo_rate_pct=6.5,cpi_headline_yoy_pct=4.81,
        real_rate_decision_bps=0,real_dissenters=['secret_truth_member'])
    prompt=snapshot.to_prompt_text()
    assert 'legacy_unverified' in prompt and 'SIMULATED MPC MEETING' in prompt
    assert '4.81' in prompt and '6.50' in prompt
    assert 'Unlisted observations are unavailable' in prompt
    assert '- Core CPI' not in prompt and '- US federal funds' not in prompt
    assert 'Unavailable observations: Core CPI' in prompt
    assert 'secret_truth_member' not in prompt
    assert '2023-08-10' not in snapshot.to_prompt_text(mask_date=True)


def test_persona_prompt_menu_and_legacy_scope():
    persona=MemberPersona(member_id='shashanka_bhide',name='Dr. Shashanka Bhide',role='External Member',
        is_internal=False,tenure='2020-2024',hawk_dove_score=.2,voting_priority='Assess supplied evidence')
    prompt=persona.build_system_prompt()
    assert 'Dr. Shashanka Bhide' in prompt
    assert 'External Academic / Expert Appointee' in prompt
    assert 'legacy_unverified' in prompt
    assert 'Rate Change: -50, -25, 0, +25, +35, +40, +50 bps' in prompt
    assert 'simulation' in prompt
