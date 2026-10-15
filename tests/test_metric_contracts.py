"""Wrong-channel counterexamples and explicitly versioned legacy replay semantics."""
import pytest

from src.validation.metrics import MetricsEvaluator


def evaluate(**overrides):
    args = dict(simulated_rate_actions=[0,25],ground_truth_rate_actions=[0,25],
        simulated_stances=['neutral']*2,ground_truth_stances=['neutral']*2,
        predicted_dissenters=[['a'],['b']],ground_truth_dissenters=[['a'],['b']],
        predicted_rate_dissenters=[['a'],[]],true_rate_dissenters=[['a'],[]],
        predicted_stance_dissenters=[[],['b']],true_stance_dissenters=[[],['b']])
    args.update(overrides)
    return MetricsEvaluator.evaluate_panel(**args)


def test_wrong_channel_cannot_pass_current_thresholds():
    args = dict(predicted_rate_dissenters=[[],[]],predicted_stance_dissenters=[['a'],['b']])
    score = evaluate(**args)
    assert score.dissent_f1==1 and score.rate_dissent_f1==0
    assert not score.passed_validation_gate
    assert evaluate(**args,threshold_contract='union_v1').passed_validation_gate


def test_size_error_and_missing_channel_do_not_pass_descriptive_thresholds():
    assert evaluate().passed_validation_gate
    assert not evaluate(simulated_rate_actions=[0,40]).passed_validation_gate
    assert not evaluate(predicted_rate_dissenters=None,true_rate_dissenters=None).passed_validation_gate
    assert not evaluate(stance_dissent_f1_threshold=1.0,
        predicted_dissenters=[['a'],[]],predicted_stance_dissenters=[[],[]]).passed_validation_gate


def test_no_positive_channel_is_unverified_instead_of_perfect():
    score = evaluate(predicted_dissenters=[['a'],[]],ground_truth_dissenters=[['a'],[]],
                     predicted_stance_dissenters=[[],[]],true_stance_dissenters=[[],[]])
    assert score.stance_dissent_f1 is None
    assert not score.passed_validation_gate


def test_union_must_equal_channel_union():
    with pytest.raises(ValueError,match='contradicts'):
        evaluate(predicted_dissenters=[[],[]])


@pytest.mark.parametrize('contract',['unsupported','',None])
def test_unknown_semantic_contract_is_rejected(contract):
    with pytest.raises(ValueError,match='contract'):
        evaluate(threshold_contract=contract)
