import json, sys, math
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.scenarios.scenario_runner import ScenarioRunner
baseline=MacroMeetingSnapshot(meeting_date="2023-08-10", current_repo_rate_pct=6.5, cpi_headline_yoy_pct=5.2)
try:
    result=ScenarioRunner.build_us_fed_spillover_snapshot(baseline, dose=1e308, headline_delta_pct_per_75bps=0, core_delta_pct_per_75bps=0, inr_depreciation_per_75bps=0, liquidity_drain_cr_per_75bps=1e308)
except ValueError as error:
    print(json.dumps({"rejected":True,"error":str(error)}))
else:
    assumptions=result.intervention["assumptions"]
    print(json.dumps({"rejected":False,"unknown_liquidity":result.system_liquidity_cr,"nonfinite_liquidity_assumption":not math.isfinite(assumptions["liquidity_drain_cr"]),"nonfinite_applied_fed_assumption":not math.isfinite(assumptions["applied_fed_hike_bps"])}))
