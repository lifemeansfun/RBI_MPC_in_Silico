"""Retain raw synthetic signed-dose values from an explicitly copied source root."""

from pathlib import Path
import argparse
from dataclasses import asdict
import hashlib
import json
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.absolute()
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(source_root))
    from src.rational.taylor_rule import MemberTaylorParameters, SmoothedTaylorRule
    from src.scenarios import scenario_runner
    from src.schemas.macro_schema import MacroMeetingSnapshot, OBSERVABLE_FIELDS

    if not Path(scenario_runner.__file__).absolute().is_relative_to(source_root):
        raise ValueError("Scenario code did not load from the declared source snapshot")
    baseline = MacroMeetingSnapshot(
        meeting_date="2023-08-10", input_track="synthetic", current_repo_rate_pct=6.5,
        cpi_headline_yoy_pct=5.2, cpi_core_yoy_pct=4.2, cpi_food_yoy_pct=5.5,
        iip_growth_yoy_pct=4.5, output_gap_pct=0.2, system_liquidity_cr=-20000,
        usd_inr_exchange_rate=82.8, brent_crude_usd_bbl=85, us_fed_funds_rate_pct=5.5,
        monsoon_departure_lpa_pct=-3.5, prev_stance="withdrawal_of_accommodation",
    )
    members = [MemberTaylorParameters(f"m{i}") for i in range(6)]
    runner = scenario_runner.ScenarioRunner(SmoothedTaylorRule())
    parent_values = {field: getattr(baseline, field) for field in OBSERVABLE_FIELDS}
    rows = []
    for scenario, build, run in (
        ("fed", runner.build_us_fed_spillover_snapshot, runner.run_us_fed_spillover_shock),
        ("monsoon", runner.build_monsoon_food_shock_snapshot, runner.run_monsoon_food_shock),
    ):
        for dose in (-1, 0, 0.5, 1, 2):
            treated = build(baseline, dose=dose)
            values = {field: getattr(treated, field) for field in OBSERVABLE_FIELDS}
            delta = {field: values[field] - parent_values[field]
                     if isinstance(values[field], (int, float)) and isinstance(parent_values[field], (int, float))
                     else None for field in OBSERVABLE_FIELDS}
            if dose == 0 and values != parent_values:
                raise ValueError(f"Zero-dose identity failed for {scenario}")
            rows.append({"scenario": scenario, "dose": dose, "observable_values": values,
                         "observable_deltas": delta, "intervention": treated.intervention,
                         "outcome": asdict(run(baseline, members, "m0", dose=dose))})
    payload = {
        "evidence_type": "synthetic_sensitivity", "provider_calls": 0,
        "scope": "simulator_local_assumed_linear_bundle",
        "interpretation": "Arithmetic and menu sensitivity only; no estimated real-MPC transmission, forecasting or welfare effect",
        "source_root": str(source_root),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_hashes": {str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (source_root / "src").rglob("*.py")},
        "synthetic_parent": baseline.model_dump(mode="json"), "rows": rows,
    }
    with (args.output / "raw_dose_probe.json").open("x") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    lines = ["| Scenario | Dose | Committee rate change (bps) | Continuous change for m0 (bps) | Menu position |",
             "|---|---:|---:|---:|---|"]
    for row in rows:
        outcome = row["outcome"]
        lines.append(f"| {row['scenario']} | {row['dose']} | {outcome['shocked_repo_rate_change_bps']} | "
                     f"{outcome['continuous_rate_changes_bps']['shocked']['m0']:.3f} | "
                     f"{outcome['menu_saturation']['shocked']['m0']} |")
    with (args.output / "dose_table.md").open("x") as handle:
        handle.write("Synthetic assumed-coefficient probe; baseline continuous change is 65 bps and menu maximum is 50 bps.\n\n")
        handle.write("\n".join(lines) + "\n")
    print(json.dumps({"rows": len(rows), "zero_dose_checks": 2, "provider_calls": 0}))


if __name__ == "__main__":
    main()
