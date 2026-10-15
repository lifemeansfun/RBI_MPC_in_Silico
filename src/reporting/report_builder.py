"""
Legacy numeric-table exporter and descriptive diagnostic report.
Produces:
- results/tables/table1_validation_accuracy.csv
- results/tables/table2_counterfactual_shocks.csv
- results/tables/table3_attribution_summary.csv
- results/RESULTS_REPORT.md (provenance-unspecified diagnostic summary)

Use study_report.build_study_report for complete saved-evidence verification.
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
        *, evidence_types: list[str] | None = None,
        evaluation_scope: str = "Unspecified retrospective diagnostic",
    ) -> Path:
        report_path = self.output_dir / "RESULTS_REPORT.md"
        def display(key, digits=2):
            value = validation_summary.get(key)
            return "undefined or not supplied" if value is None else f"{value:.{digits}f}"
        evidence_label = ", ".join(evidence_types) if evidence_types else "not supplied"

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

        content = f"""# RBI MPC In Silico — Computational Diagnostic Report
**Reserve Bank of India Monetary Policy Committee Deliberation Simulation**

---

## 1. Executive Summary & Validation Gate Status

Evaluation scope: {evaluation_scope}.
Generation evidence types supplied by the caller: {evidence_label}.
This legacy exporter formats caller-supplied numbers; it does not authenticate
inputs, provider execution, or an independent empirical replication. Numerical
threshold checks do not establish forecasting skill, persuasion or welfare.
Voting majority and casting provisions are in RBI Act §45ZI; full-roster and
fragmentation choices are additional simulator assumptions.

### Key Validation Metrics:
- **Exact Rate Accuracy:** {display('exact_rate_accuracy_pct', 1)}
- **Directional Rate Accuracy:** {display('directional_rate_accuracy_pct', 1)}
- **Rate MAE in basis points:** {display('rate_mae_bps')}
- **Stance Accuracy:** {display('stance_accuracy_pct', 1)}
- **Union Dissent Precision:** {display('dissent_precision')}
- **Union Dissent Recall:** {display('dissent_recall')}
- **Union Dissent F1:** {display('dissent_f1')}
- **Rate Dissent F1:** {display('rate_dissent_f1')}
- **Stance Dissent F1:** {display('stance_dissent_f1')}
- **Configured numerical thresholds:** {'met' if validation_summary.get('passed_validation_gate') else 'not met or not supplied'}

---

## 2. Counterfactual Macroeconomic Scenarios

The supplied rows describe changes inside the specified simulator. They do not
identify effects on the real MPC, the economy, or monetary policy resilience.

| Scenario Name | Baseline Rate | Shocked Rate | Policy Wedge | Baseline Stance | Shocked Stance |
|---|---|---|---|---|---|
{scenarios_md}

---

## 3. Interaction-Level Attribution Experiments

The supplied rows describe removal-based simulator contrasts. A null or changed
output requires its recorded intervention path and matched inputs for interpretation.

| Experiment | Baseline Action | Ablated Action | Marginal Delta | Outcome Shifted |
|---|---|---|---|---|
{attributions_md}

---

## 4. Evidence Boundaries
Formal rate and stance ballots, reservations and guidance disagreement require
separate source-linked targets. Passing a software invariant is not proof of
empirical superiority, realistic preferences, an equilibrium or policy welfare.
Mock or heuristic generation and cache replay must retain those evidence labels.
Use the verified study-report path for reconstructed tables, provenance and
available-information baseline comparisons. No scientific verdict is issued here.
"""
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")
        return report_path
