# Shortcuts for the common tasks. Run `make help` to list them.
FROM ?= 2026-01-01
# macOS ships Python 3.9; this project needs 3.10+. With Homebrew: brew install python@3.12, then make setup PYTHON=python3.12
PYTHON ?= python3

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

setup: ## create the Python venv and install everything
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ needed: brew install python@3.12, then make setup PYTHON=python3.12")'
	cd backend && $(PYTHON) -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm install

master: ## refresh the IPO list from NSE into backend/data/ipo_master.csv
	cd backend && .venv/bin/python -m pipeline collect-master --from $(FROM)

load: ## load the IPO list and corporate actions into the database
	cd backend && .venv/bin/python -m pipeline load

backfill: load ## download daily prices since FROM (default 2026-01-01)
	cd backend && .venv/bin/python -m pipeline prices --from $(FROM)
	cd backend && .venv/bin/python -m pipeline yahoo-gaps

daily: load ## download the last 10 days (what the scheduler runs)
	cd backend && .venv/bin/python -m pipeline daily && .venv/bin/python -m pipeline yahoo-gaps

validate: ## run the data checks
	cd backend && .venv/bin/python -m pipeline validate

api: ## run the API on http://localhost:8000 (docs at /docs)
	cd backend && .venv/bin/uvicorn app.main:app --reload

web: ## run the site on http://localhost:5173
	cd frontend && npm run dev

test: ## run every test
	cd backend && .venv/bin/pytest -q
	cd frontend && npm test

.PHONY: help setup master load backfill daily validate api web test
