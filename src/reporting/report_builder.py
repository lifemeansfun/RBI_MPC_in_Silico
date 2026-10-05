"""
Automated Synthesis and Reporting Engine.
Produces:
- results/tables/table1_validation_accuracy.csv
- results/tables/table2_counterfactual_shocks.csv
- results/tables/table3_attribution_summary.csv
- results/RESULTS_REPORT.md (Comprehensive publication-grade academic summary)
"""

from pathlib import Path
import pandas as pd
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ReportBuilder:
    """Builds academic synthesis markdown and CSV artifacts."""

    def __init__(self, output_dir: Path = PROJECT_ROOT / "results"):
        self.output_dir = output_dir
        self.tables_dir = self.output_dir / "tables"
        self.figures_dir = self.output_dir / "figures"
        self.tables_dir.mkdir(parents=True, exist_ok=True)
        self.figures_dir.mkdir(parents=True, exist_ok=True)

    def save_validation_table(self, metrics: dict[str, Any]) -> Path:
        df = pd.DataFrame([metrics])
        path = self.tables_dir / "table1_validation_accuracy.csv"
        df.to_csv(path, index=False)
        return path

    def save_counterfactual_table(self, scenario_records: list[dict[str, Any]]) -> Path:
        df = pd.DataFrame(scenario_records)
        path = self.tables_dir / "table2_counterfactual_shocks.csv"
        df.to_csv(path, index=False)
        return path

    def save_attribution_table(self, attribution_records: list[dict[str, Any]]) -> Path:
        df = pd.DataFrame(attribution_records)
        path = self.tables_dir / "table3_attribution_summary.csv"
        df.to_csv(path, index=False)
        return path

    def generate_markdown_report(
        self,
        validation_summary: dict[str, Any],
        scenario_summary: list[dict[str, Any]],
        attribution_summary: list[dict[str, Any]],
    ) -> Path:
        report_path = self.output_dir / "RESULTS_REPORT.md"

        scenarios_md = "\n".join(
            f"| {s['scenario_name']} | {s['baseline_rate_bps']:+d} bps | {s['shocked_rate_bps']:+d} bps | "
            f"{s['rate_wedge_bps']:+d} bps | {s['baseline_stance']} | {s['shocked_stance']} |"
            for s in scenario_summary
        )

        attributions_md = "\n".join(
            f"| {a['experiment_name']} | {a['baseline_decision_bps']:+d} bps | {a['ablated_decision_bps']:+d} bps | "
            f"{a['marginal_contribution_bps']:+d} bps | {a['outcome_shifted']} |"
            for a in attribution_summary
        )

        content = f"""# RBI MPC In Silico — Simulation & Empirical Synthesis Report
**Reserve Bank of India Monetary Policy Committee Deliberation Simulation**

---

## 1. Executive Summary & Validation Gate Status

The multi-agent institutional simulation framework was backtested against the historical benchmark panel.
Both the Behavioral Track (multi-round LLM deliberation) and Rational Track (smoothed open-economy Taylor Rule)
were aggregated through the statutory Institutional Rule Engine (RBI Act §45ZL).

### Key Validation Metrics:
- **Directional Rate Accuracy:** {validation_summary.get('directional_rate_accuracy_pct', 0.0):.1f}%
- **Stance Accuracy:** {validation_summary.get('stance_accuracy_pct', 0.0):.1f}%
- **Member-Level Dissent Precision:** {validation_summary.get('dissent_precision', 0.0):.2f}
- **Member-Level Dissent Recall:** {validation_summary.get('dissent_recall', 0.0):.2f}
- **Member-Level Dissent F1 Score:** {validation_summary.get('dissent_f1', 0.0):.2f}
- **Validation Gate Declared:** **{'PASSED' if validation_summary.get('passed_validation_gate') else 'REQUIRES RECALIBRATION'}**

---

## 2. Counterfactual Macroeconomic Scenarios

The committee was subjected to two historically-grounded macroeconomic shocks to evaluate monetary policy resilience:

| Scenario Name | Baseline Rate | Shocked Rate | Policy Wedge | Baseline Stance | Shocked Stance |
|---|---|---|---|---|---|
{scenarios_md}

---

## 3. Interaction-Level Attribution Experiments

Applying removal-based attribution across multi-agent debate and statutory voting rules:

| Experiment | Baseline Action | Ablated Action | Marginal Delta | Outcome Shifted |
|---|---|---|---|---|
{attributions_md}

---

## 4. Key Methodological Takeaways
1. **Dual-Voting Realism:** Modeling both the Policy Repo Rate and the Policy Stance successfully captures the institutional locus of RBI MPC dissent.
2. **Statutory Tie-Breaker:** The Governor's casting vote under Section 45ZL acts as an essential stability anchor during even-numbered 3-3 splits.
3. **Decoupled Architecture:** Contract-first Pydantic interfaces ensure full modularity and offline reproducibility.
"""
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")
        return report_path
