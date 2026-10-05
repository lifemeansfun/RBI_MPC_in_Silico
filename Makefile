# RBI MPC In Silico — Master Makefile
# Validated Multi-Agent Simulation of India's Monetary Policy Committee

.PHONY: help test verify figures scenarios reproduce clean

VENV = .venv
PYTHON = $(VENV)/bin/python
PYTEST = $(VENV)/bin/pytest

help:
	@echo "=============================================================================="
	@echo "                   RBI MPC IN SILICO: MASTER COMMANDS                         "
	@echo "=============================================================================="
	@echo "  make test        - Run pytest unit and integration test suite"
	@echo "  make verify      - Run both deep academic & code verification batteries"
	@echo "  make figures     - Generate publication vector figures (PDF & PNG)"
	@echo "  make scenarios   - Execute counterfactual scenarios & attribution experiments"
	@echo "  make verify_contamination - Run the entity-masked data leakage audit"
	@echo "  make reproduce   - Execute full end-to-end reproducibility harness"
	@echo "=============================================================================="

test:
	$(PYTEST) tests/

verify:
	$(PYTHON) scripts/deep_verification_battery.py
	$(PYTHON) scripts/intensive_academic_verification.py
	$(PYTHON) scripts/academic_integrity_guard.py

verify_contamination:
	$(PYTHON) scripts/verify_contamination_audit.py

figures:
	$(PYTHON) src/reporting/plot_figures.py

scenarios:
	$(PYTHON) src/scenarios/run_counterfactual_experiments.py

reproduce:
	$(PYTHON) scripts/reproduce.py
