.DEFAULT_GOAL := help
RUN_DATE ?= 2026-08-29

# The pipeline is invoked through the module path rather than an installed console script so it
# runs identically whether or not a virtualenv could be built on this machine.
PY ?= PYTHONPATH=src python -m flasheats.cli

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

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

run:  ## Run the pipeline for RUN_DATE
	$(PY) run --run-date $(RUN_DATE)

docker-run:  ## Run the pipeline fully containerised (no local Python needed)
	docker compose --profile tools run --rm pipeline run --run-date $(RUN_DATE)

test:  ## Run the test suite
	PYTHONPATH=src python -m pytest tests/ -q

psql:  ## Open a psql shell on the warehouse
	docker compose exec warehouse psql -U flasheats -d flasheats_wh

clean:  ## Remove generated artefacts (raw zone, logs, outputs)
	rm -rf data/raw logs out && mkdir -p data/raw logs out

.PHONY: help install up down nuke init run docker-run test psql clean
