# =============================================================================
# QuantBot — Developer Makefile
# -----------------------------------------------------------------------------
# Snelle commando's voor development, testen, kwaliteit en deployment.
# Gebruik `make help` voor een overzicht.
# =============================================================================

.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
COMPOSE ?= docker compose
PKG := src/quantbot
TESTS := tests

.PHONY: help
help: ## Toon dit hulpoverzicht
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
.PHONY: install
install: ## Installeer runtime + dev dependencies (editable)
	$(PIP) install -e ".[dev]"

.PHONY: install-all
install-all: ## Installeer alle optionele extras (api, ai, optimize, ...)
	$(PIP) install -e ".[all,dev]"

.PHONY: env
env: ## Maak een .env aan vanaf het voorbeeld (als die nog niet bestaat)
	@test -f .env || (cp .env.example .env && echo "Created .env — vul de waarden in.")

# -----------------------------------------------------------------------------
# Kwaliteit
# -----------------------------------------------------------------------------
.PHONY: lint
lint: ## Lint met ruff
	$(PYTHON) -m ruff check $(PKG) $(TESTS)

.PHONY: format
format: ## Formatteer code met ruff
	$(PYTHON) -m ruff format $(PKG) $(TESTS)
	$(PYTHON) -m ruff check --fix $(PKG) $(TESTS)

.PHONY: typecheck
typecheck: ## Statische type-controle met mypy
	$(PYTHON) -m mypy $(PKG)

.PHONY: check
check: lint typecheck ## Lint + typecheck (geen tests)

# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------
.PHONY: test
test: ## Draai alle tests
	$(PYTHON) -m pytest

.PHONY: test-unit
test-unit: ## Alleen unit tests
	$(PYTHON) -m pytest -m unit

.PHONY: test-integration
test-integration: ## Alleen integratietests
	$(PYTHON) -m pytest -m integration

.PHONY: cov
cov: ## Tests met coverage-rapport
	$(PYTHON) -m pytest --cov=$(PKG) --cov-report=term-missing --cov-report=html

.PHONY: ci
ci: check test ## Volledige CI-poort lokaal (lint + types + tests)

# -----------------------------------------------------------------------------
# Applicatie draaien
# -----------------------------------------------------------------------------
.PHONY: run
run: ## Start de trading engine (modus uit .env)
	$(PYTHON) -m quantbot run

.PHONY: api
api: ## Start de FastAPI monitoring-backend
	$(PYTHON) -m quantbot api

.PHONY: backtest
backtest: ## Draai een backtest (gebruik ARGS="--strategy ...")
	$(PYTHON) -m quantbot backtest $(ARGS)

.PHONY: scan
scan: ## Draai de markt-scanners (gebruik ARGS="--scanner ...")
	$(PYTHON) -m quantbot scan $(ARGS)

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
.PHONY: migrate
migrate: ## Pas de nieuwste DB-migraties toe
	$(PYTHON) -m alembic upgrade head

.PHONY: migration
migration: ## Genereer een nieuwe migratie (gebruik MSG="omschrijving")
	$(PYTHON) -m alembic revision --autogenerate -m "$(MSG)"

.PHONY: downgrade
downgrade: ## Rol één migratie terug
	$(PYTHON) -m alembic downgrade -1

# -----------------------------------------------------------------------------
# Docker
# -----------------------------------------------------------------------------
.PHONY: up
up: ## Start de volledige stack (docker compose)
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop de stack
	$(COMPOSE) down

.PHONY: logs
logs: ## Volg container-logs
	$(COMPOSE) logs -f

.PHONY: ps
ps: ## Toon container-status
	$(COMPOSE) ps

# -----------------------------------------------------------------------------
# Schoonmaken
# -----------------------------------------------------------------------------
.PHONY: clean
clean: ## Verwijder caches en build-artefacten
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml build dist *.egg-info
