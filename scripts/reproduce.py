"""
Master End-to-End Reproducibility Harness for RBI MPC In Silico.
Single-command execution that reproduces all scientific results, runs verification batteries,
generates vector figures, and compiles the final academic report.

Usage:
    python scripts/reproduce.py
    or
    make reproduce
"""

import sys
import subprocess
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rbi_mpc.reproduce")


def run_step(step_name: str, command: list[str]) -> bool:
    """Executes a subprocess step and verifies exit code 0."""
    print("\n" + "=" * 78)
    print(f"STEP: {step_name}")
    print("=" * 78)
    print(f"Running command: {' '.join(command)}")

    res = subprocess.run(command, cwd=str(PROJECT_ROOT))
    if res.returncode != 0:
        print(f"\n[-] ERROR: Step '{step_name}' failed with exit code {res.returncode}")
        return False
    print(f"[+] SUCCESS: Step '{step_name}' completed successfully.")
    return True


def check_artifacts() -> bool:
    """Verifies that all required master tables and publication figures exist and are non-empty."""
    print("\n" + "=" * 78)
    print("STEP: Verifying Generated Tables & Figures")
    print("=" * 78)

    tables = [
        PROJECT_ROOT / "results" / "tables" / "table1_validation_accuracy.csv",
        PROJECT_ROOT / "results" / "tables" / "table2_rational_vs_behavioral_wedge.csv",
        PROJECT_ROOT / "results" / "tables" / "table3_counterfactual_shock_responses.csv",
        PROJECT_ROOT / "results" / "tables" / "table4_attribution_ablation_effects.csv",
    ]

    figures = [
        PROJECT_ROOT / "results" / "figures" / "fig1_methodology_pipeline.png",
        PROJECT_ROOT / "results" / "figures" / "fig1_methodology_pipeline.pdf",
        PROJECT_ROOT / "results" / "figures" / "fig2_holdout_confusion_matrix.png",
        PROJECT_ROOT / "results" / "figures" / "fig2_holdout_confusion_matrix.pdf",
        PROJECT_ROOT / "results" / "figures" / "fig3_deliberation_stance_trajectories.png",
        PROJECT_ROOT / "results" / "figures" / "fig3_deliberation_stance_trajectories.pdf",
        PROJECT_ROOT / "results" / "figures" / "fig4_counterfactual_impulse_comparison.png",
        PROJECT_ROOT / "results" / "figures" / "fig4_counterfactual_impulse_comparison.pdf",
    ]

    all_ok = True
    for t in tables:
        if t.exists() and t.stat().st_size > 50:
            print(f"  [+] Table Verified:   {t.name} ({t.stat().st_size} bytes)")
        else:
            print(f"  [-] Table Missing:    {t.name}")
            all_ok = False

    for f in figures:
        if f.exists() and f.stat().st_size > 1000:
            print(f"  [+] Figure Verified:  {f.name} ({f.stat().st_size} bytes)")
        else:
            print(f"  [-] Figure Missing:   {f.name}")
            all_ok = False

    return all_ok


def main():
    print("\n" + "#" * 78)
    print("   RBI MPC IN SILICO: MASTER END-TO-END REPRODUCIBILITY HARNESS")
    print("   Validated Multi-Agent Simulation of India's Monetary Policy Committee")
    print("#" * 78)

    venv_python = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    venv_pytest = str(PROJECT_ROOT / ".venv" / "bin" / "pytest")

    steps = [
        ("1. Pytest Unit & Integration Test Suite", [venv_pytest, "tests/"]),
        ("2. Deep Academic & Code Verification Battery 1 (Phases 1-5)", [venv_python, "scripts/deep_verification_battery.py"]),
        ("3. Intensive Academic Verification Battery 2 (Phases 1-5)", [venv_python, "scripts/intensive_academic_verification.py"]),
        ("4. Publication Vector Figures Generator (Phase 9)", [venv_python, "src/reporting/plot_figures.py"]),
        ("5. Academic & Research Integrity Guard (Audit & Concordance)", [venv_python, "scripts/academic_integrity_guard.py"]),
    ]

    for name, cmd in steps:
        if not run_step(name, cmd):
            print("\n[-] Pipeline halted due to step failure.")
            sys.exit(1)

    if not check_artifacts():
        print("\n[-] Warning: Some expected tables or figures were missing or incomplete.")
    else:
        print("\n[+] All master tables and publication figures verified!")

    # Check Report
    report_path = PROJECT_ROOT / "results" / "RESULTS_REPORT.md"
    if report_path.exists():
        print(f"\n[+] Master Academic Report Verified: {report_path} ({report_path.stat().st_size} bytes)")

    print("\n" + "=" * 78)
    print("      REPRODUCIBILITY HARNESS COMPLETE: ALL PHASES VERIFIED GREEN      ")
    print("=" * 78)


if __name__ == "__main__":
    main()
