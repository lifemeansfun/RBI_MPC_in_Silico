"""Offline sensitivity diagnostics. Never overwrite production artifacts or call an LLM."""
from pathlib import Path
import sys
import json
import re
from dataclasses import asdict
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from src.schemas.macro_schema import MacroMeetingSnapshot
from src.rational.taylor_rule import SmoothedTaylorRule
from src.rational.rational_panel_runner import MEMBER_TAYLOR_PARAMS
from src.rational.monte_carlo import MonteCarloEngine
from src.rule_engine.engine import InstitutionalRuleEngine
from src.persona_engine.extractor import ROSTER_META, HAWK_LEXICON, DOVE_LEXICON

panel = pd.read_parquet(ROOT / "data/processed/macro_panel.parquet")
saved = pd.read_csv(ROOT / "results/tables/rational_taylor_panel_results.csv")
rows = []
original = []
for rho in [.75, .85, .90, .95, .975, .99]:
    rule = SmoothedTaylorRule(smoothing_rho=rho)
    mc = MonteCarloEngine(rule, n_draws=1000, noise_std_pct=.2, seed=42)
    for row in panel.to_dict(orient="records"):
        snap = MacroMeetingSnapshot(**row)
        ids = ["shaktikanta_das", "michael_patra", "mridul_saggar" if row["meeting_date"] < "2022-05-01" else "rajiv_ranjan", "shashanka_bhide", "ashima_goyal", "jayanth_varma"]
        params = [MEMBER_TAYLOR_PARAMS[m] for m in ids]
        # Identical common random draws across rho values reduce Monte Carlo confounding.
        res = mc.simulate(snap, params)
        records = dict(rho=rho, meeting_date=row["meeting_date"],
            subset="calibration" if row["meeting_date"] <= "2023-04-06" else "holdout",
            rate=res.modal_rate_decision_bps, stance=res.modal_stance_decision,
            truth_rate=row["real_rate_decision_bps"], truth_stance=row["real_stance_decision"],
            directional_match=np.sign(res.modal_rate_decision_bps) == np.sign(row["real_rate_decision_bps"]),
            exact_match=res.modal_rate_decision_bps == row["real_rate_decision_bps"],
            stance_match=res.modal_stance_decision == row["real_stance_decision"],
            rate_mae_bps=abs(res.modal_rate_decision_bps-row["real_rate_decision_bps"]),
            continuous_rate_mean=res.mean_implied_rate)
        rows.append(records)
        if rho == .75:
            original.append(asdict(res))
results = pd.DataFrame(rows)
results.to_csv(OUT / "stat_taylor_rho_meeting_results.csv", index=False)
agg = results.groupby(["rho", "subset"])[["directional_match", "exact_match", "stance_match", "rate_mae_bps"]].mean().reset_index()
agg.to_csv(OUT / "stat_taylor_rho_metrics.csv", index=False)
original_df = results[results.rho == .75].reset_index(drop=True)
reproduction = dict(n=25, draws_per_meeting=1000, seed=42, noise_std_pct=.2,
    exact_rate_matches_to_saved=int(np.sum(original_df.rate.to_numpy() == saved.taylor_modal_rate_bps.to_numpy())),
    exact_stance_matches_to_saved=int(np.sum(original_df.stance.to_numpy() == saved.taylor_modal_stance.to_numpy())),
    mean_rate_rounded_matches=int(np.sum(original_df.continuous_rate_mean.round(2).to_numpy() == saved.taylor_mean_implied_rate_pct.to_numpy())))

# Select rho only on calibration MAE; this is an exploratory admissible baseline, not a frozen independent benchmark.
cal = agg[agg.subset == "calibration"].sort_values(["rate_mae_bps", "rho"])
selected = float(cal.iloc[0].rho)
summary = dict(original_taylor_reproduction=reproduction,
    exploratory_rho_only_selection=dict(criterion="Minimum calibration rate MAE, rho ascending as tie breaker; six prespecified grid values for this audit.",
        rho=selected, calibration_metrics=cal.iloc[0].to_dict(), holdout_metrics=agg[(agg.rho == selected) & (agg.subset == "holdout")].iloc[0].to_dict(),
        limitation="Selected after seeing the repository for diagnosis. Not an unbiased new confirmatory result; use nested time-ordered calibration and a new untouched test for claims."),
    persona_corpus_sensitivity=[])
for m, meta in ROSTER_META.items():
    subsets = {}
    for subset in ["calibration", "holdout", "all"]:
        statements = [p for p in sorted((ROOT / "data/processed/statements").glob(f"*/{m}.txt"))
                      if subset == "all" or ((p.parent.name <= "2023-04-06") == (subset == "calibration"))]
        text = "\n".join(p.read_text() for p in statements)
        hawk = sum(len(re.findall(r"\b" + re.escape(w) + r"\b", text, re.I)) for w in HAWK_LEXICON)
        dove = sum(len(re.findall(r"\b" + re.escape(w) + r"\b", text, re.I)) for w in DOVE_LEXICON)
        lexical = (hawk-dove)/max(hawk+dove, 1)
        score = round(.6*meta["default_hawk_dove"]+.4*lexical, 2)
        subsets[subset] = dict(n_statements=len(statements), hawk_hits=hawk, dove_hits=dove, lexical_score=lexical, calibrated_score=score)
    summary["persona_corpus_sensitivity"].append(dict(member=m, subsets=subsets))
(OUT / "stat_sensitivity.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
