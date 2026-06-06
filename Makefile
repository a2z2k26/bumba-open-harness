# Bumba Open Harness public developer commands.

PYTHON ?= .venv/bin/python
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= .venv/bin/ruff

.PHONY: setup
setup:
	cd agent && uv sync --extra dev

.PHONY: test test-offline
test test-offline:
	cd agent && $(PYTEST) tests/ job_search/tests/ -m "not live and not socket" -q

.PHONY: test-socket
test-socket:
	cd agent && $(PYTEST) tests/ job_search/tests/ -m "not live" -q

.PHONY: lint
lint:
	cd agent && $(RUFF) check . --select E,F,W --ignore E501,E402

.PHONY: coverage
coverage:
	cd agent && $(PYTEST) tests/ job_search/tests/ -m "not live and not perf" \
		--deselect tests/test_integration_performance.py \
		--cov=bridge --cov=teams --cov=job_search \
		--cov-report=term-missing \
		--cov-fail-under=80

.PHONY: validate-services
validate-services:
	cd agent && $(PYTHON) -m bridge.services.runner --validate

.PHONY: secrets-scan
secrets-scan:
	gitleaks detect --no-git --source . --config .gitleaks.toml --redact --verbose
