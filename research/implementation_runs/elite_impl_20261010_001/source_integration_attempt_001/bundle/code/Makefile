# RBI MPC In Silico — evidence-preserving research commands
.PHONY: help test verify reproduce study-validate study-fixture study-mock study-replay verify_contamination figures scenarios
PYTHON = .venv/bin/python

help:
	@echo 'make test OUT=<unused-directory>       Run tests in a copied checkout'
	@echo 'make reproduce OUT=<unused-directory>  Rebuild source inputs and verify saved evidence offline'
	@echo 'make verify OUT=<unused-directory>     Reproduce offline and run the isolated full suite'
	@echo 'make study-validate PROTOCOL=<json> OUT=<unused>  Validate a portable freeze; zero generation'
	@echo 'make study-fixture OUT=<unused>        Create an explicitly artificial frozen fixture'
	@echo 'make study-mock PROTOCOL=<json> OUT=<unused>      Execute explicit engineering mock evidence'
	@echo 'make study-replay PROTOCOL=<json> SAVED=<run> OUT=<unused>  Independently reconstruct retained outputs'
	@echo 'Offline checks do not establish independent live replication or scientific readiness.'

test:
	@test -n "$(OUT)" || (echo 'Set OUT to an unused output directory'; exit 2)
	$(PYTHON) research/verification/run_isolated_pytest.py "$(OUT)"

reproduce:
	@test -n "$(OUT)" || (echo 'Set OUT to an unused output directory'; exit 2)
	$(PYTHON) scripts/reproduce_offline.py --output-root "$(OUT)"

verify:
	@test -n "$(OUT)" || (echo 'Set OUT to an unused output directory'; exit 2)
	$(PYTHON) scripts/reproduce_offline.py --output-root "$(OUT)" --run-tests

study-validate study-mock:
	@test -n "$(OUT)" -a -n "$(PROTOCOL)" || (echo 'Set PROTOCOL and unused OUT'; exit 2)
	$(PYTHON) -m src.backtest.run_frozen_study --protocol "$(PROTOCOL)" --output-root "$(OUT)" --execution $(if $(filter study-mock,$@),mock,validate)

study-fixture:
	@test -n "$(OUT)" || (echo 'Set OUT to an unused directory'; exit 2)
	$(PYTHON) -m src.backtest.run_frozen_study --create-fixture --output-root "$(OUT)"

study-replay:
	@test -n "$(OUT)" -a -n "$(PROTOCOL)" -a -n "$(SAVED)" || (echo 'Set PROTOCOL, SAVED and unused OUT'; exit 2)
	$(PYTHON) -m src.backtest.run_frozen_study --protocol "$(PROTOCOL)" --retained-root "$(SAVED)" --output-root "$(OUT)" --execution replay

verify_contamination figures scenarios:
	@echo 'This legacy target is retired. Freeze an explicit current study protocol and new output destination for this analysis.'
	@exit 2
