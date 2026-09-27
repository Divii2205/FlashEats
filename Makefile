.DEFAULT_GOAL := help
RUN_DATE ?= 2026-08-29
CHAOS ?=

# Every recipe below has to run unchanged under bash, cmd.exe and PowerShell, because `make` on
# Windows shells out to cmd.exe. That rules out three things people reach for by reflex:
# a `VAR=value cmd` prefix, `rm -rf` / `mkdir -p`, and a grep|awk pipeline. Hence the root-level
# entry script and the small python one-liners.
PY ?= python run_pipeline.py

help:  ## Show available targets
	@python -c "import re,sys; [print('  {:<12} {}'.format(*m)) for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open('Makefile').read(), re.M)]"

install:  ## Install dependencies
	python -m pip install -e ".[dev]"

up:  ## Start the Postgres warehouse and mock Dispatch API
	docker compose up -d --wait warehouse dispatch_api

down:  ## Stop containers (keeps the warehouse volume)
	docker compose down

nuke:  ## Stop containers AND destroy the warehouse volume
	docker compose down -v

init:  ## Create warehouse schemas and tables (safe to rerun)
	$(PY) init

run:  ## Run the pipeline. Optional: RUN_DATE=YYYY-MM-DD CHAOS=<mode>
	$(PY) run --run-date $(RUN_DATE) $(if $(CHAOS),--chaos $(CHAOS),)

docker-run:  ## Run the pipeline fully containerised (no local Python needed)
	docker compose --profile tools run --rm pipeline run --run-date $(RUN_DATE)

test:  ## Run the test suite
	python -m pytest -q

psql:  ## Open a psql shell on the warehouse
	docker compose exec warehouse psql -U flasheats -d flasheats_wh

clean:  ## Remove generated artefacts (raw zone, logs, outputs)
	@python -c "import shutil,pathlib; [shutil.rmtree(p,ignore_errors=True) for p in ['data/raw','logs','out']]; [pathlib.Path(p).mkdir(parents=True,exist_ok=True) for p in ['data/raw','logs','out']]"

.PHONY: help install up down nuke init run docker-run test psql clean
