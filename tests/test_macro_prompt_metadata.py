"""Information-age presentation and the actual macro-to-mock prompt contract."""
import json

from src.backtest.backtest_runner import PROJECT_ROOT, load_snapshots
from src.infra.llm_client import LLMClient
from src.schemas.debate_schema import InitialStanceOutput


def test_supplied_vintages_and_missing_fields_reach_prompt():
    snapshot = load_snapshots(PROJECT_ROOT/'data/processed/vintage_v3/snapshots.json')[-1]
    text = snapshot.to_prompt_text()
    assert snapshot.information_cutoff.isoformat() in text
    for item in snapshot.observations:
        assert f'reference period={item.reference_period}' in text
        assert f'release={item.released_at.isoformat()}' in text
        assert f'vintage={item.vintage}' in text
    assert 'Unavailable observations:' in text and 'estimated output gap' in text
    assert snapshot.output_gap_pct is None


def test_date_mask_keeps_availability_lags_without_absolute_labels():
    snapshot = load_snapshots(PROJECT_ROOT/'data/processed/vintage_v3/snapshots.json')[-1]
    text = snapshot.to_prompt_text(mask_date=True)
    assert snapshot.meeting_date not in text
    for item in snapshot.observations:
        assert item.released_at.isoformat() not in text
        assert 'reference period='+item.reference_period not in text
        assert 'vintage='+item.vintage not in text
    assert 'days before cutoff' in text


def test_mock_reads_accommodative_stance_from_actual_prompt():
    snapshot = load_snapshots(PROJECT_ROOT/'data/processed/vintage_v3/snapshots.json')[0]
    assert snapshot.prev_stance=='accommodative'
    client = LLMClient(provider='mock',cache_enabled=False)
    raw,_,_ = client._generate_mock(snapshot.to_prompt_text(),None,'mock',InitialStanceOutput,
        {'member_id':'shashanka_bhide','member_name':'Shashanka Bhide','is_internal':False})
    assert json.loads(raw)['proposed_stance']=='accommodative'
