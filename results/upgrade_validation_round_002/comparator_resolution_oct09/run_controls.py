"""Small saved control artifacts; no authentic forecast or live model evidence."""
import hashlib, json, sys
from dataclasses import asdict
from pathlib import Path
from src.rational.monte_carlo import MonteCarloEngine
from src.rational.taylor_rule import SmoothedTaylorRule, MemberTaylorParameters
from src.schemas.decision_space import RATE_ACTIONS_BPS
from src.schemas.macro_schema import MacroMeetingSnapshot
import src.rational.monte_carlo as implementation

out = Path(sys.argv[1])
out.mkdir(exist_ok=False)
snapshot = MacroMeetingSnapshot(meeting_date='2023-08-10', current_repo_rate_pct=6.0,
    cpi_headline_yoy_pct=4.0, output_gap_pct=0.0, us_fed_funds_rate_pct=2.5,
    prev_stance='withdrawal_of_accommodation', input_track='synthetic')
members = [MemberTaylorParameters(f'm{i}', alpha=0.0, beta=0.0, gamma=0.0) for i in range(6)]
fragmented_rates = [-50, -25, 0, 25, 35, 50]
fragmented_stances = ['neutral'] * 2 + ['accommodative'] * 2 + ['withdrawal_of_accommodation'] * 2

class ScriptedRule:
    action_set_bps = RATE_ACTIONS_BPS
    def __init__(self, rows): self.rows = rows
    def compute_discrete_action(self, snapshot, params):
        rates, stances = self.rows[snapshot.intervention.get('draw', 0)]
        i = int(params.member_id[1:])
        return rates[i], stances[i]
    def compute_continuous_rate(self, snapshot, params):
        rate, _ = self.compute_discrete_action(snapshot, params)
        return snapshot.current_repo_rate_pct + rate / 100.0

cases = {}
for policy in ('reject', 'legacy_synthetic', 'status_quo'):
    rule = ScriptedRule([(fragmented_rates, fragmented_stances)] * 3)
    cases['fragmented_' + policy] = MonteCarloEngine(rule, n_draws=3, noise_std_pct=0.0,
        fragmentation_policy=policy).simulate(snapshot, members, 'm0')
rows = [
    ([0,0,0,0,25,25], fragmented_stances),
    (fragmented_rates, ['neutral'] * 5 + ['accommodative']),
    ([0,0,0,25,0,0], ['neutral'] * 4 + ['accommodative'] * 2),
    (fragmented_rates, fragmented_stances),
]
cases['mixed_channel_rejection'] = MonteCarloEngine(ScriptedRule(rows), n_draws=4,
    noise_std_pct=0.0).simulate(snapshot, members, 'm0')
for name, r_star in [('upper_saturated', 3.0), ('exact_upper_endpoint', 2.5), ('lower_saturated', 1.0)]:
    cases[name] = MonteCarloEngine(SmoothedTaylorRule(r_star_pct=r_star, smoothing_rho=0.0),
        n_draws=3, noise_std_pct=0.0).simulate(snapshot, members, 'm0')
for name, result in cases.items():
    (out / (name + '.json')).write_text(json.dumps(asdict(result), indent=2, allow_nan=False) + '\n')
(out / 'input_snapshot.json').write_text(snapshot.model_dump_json(indent=2) + '\n')
(out / 'receipt.json').write_text(json.dumps({
    'scope': 'synthetic procedural controls; no fitted noise, authentic forecasts or empirical advantage',
    'case_count': len(cases), 'provider_calls': 0,
    'loaded_implementation': str(Path(implementation.__file__)),
    'implementation_sha256': hashlib.sha256(Path(implementation.__file__).read_bytes()).hexdigest(),
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'files': {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(out.glob('*.json'))},
}, indent=2) + '\n')
print(json.dumps({name: {
    'rate_unresolved': result.rate_unresolved_draws,
    'stance_unresolved': result.stance_unresolved_draws,
    'rate_synthetic': result.rate_synthetic_resolution_draws,
    'stance_synthetic': result.stance_synthetic_resolution_draws,
    'rate_denominator': result.probability_denominators['rate_distribution_pct'],
    'stance_denominator': result.probability_denominators['stance_distribution_pct'],
    'union_denominator': result.probability_denominators['dissent_probability_by_member'],
    'saturated_fraction': result.action_saturation_summary['saturated_fraction'],
} for name, result in cases.items()}, indent=2))
