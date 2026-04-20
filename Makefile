# overnight-saas — root orchestrator (owner: infra-dev)
# Targets: install, dev, test, lint, build, clean
# See vault/ARCHITECTURE.md §4 for the contract.

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND  := backend
FRONTEND := frontend

.PHONY: help install install-backend install-frontend dev dev-backend dev-frontend \
        test test-backend test-frontend lint lint-backend lint-frontend build \
        build-backend build-frontend clean down restart-backend

help:
	@echo "overnight-saas — make targets"
	@echo "  install   uv sync (backend) + npm ci (frontend)"
	@echo "  dev       docker compose up (api + frontend dev server)"
	@echo "  test      pytest (backend) + npm run test (frontend)"
	@echo "  lint      ruff (backend) + tsc --noEmit (frontend)"
	@echo "  build     vite build (frontend) + docker build (api)"
	@echo "  down      docker compose down"
	@echo "  clean     remove .venv, node_modules, dist, __pycache__"

install: install-backend install-frontend

install-backend:
	cd $(BACKEND) && uv sync

install-frontend:
	@if [ -f $(FRONTEND)/package.json ]; then cd $(FRONTEND) && npm ci; \
	else echo "frontend/package.json missing — ui-designer hasn't scaffolded yet"; fi

dev:
	docker compose up --build

dev-backend:
	cd $(BACKEND) && uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

restart-backend:
	@bash scripts/restart-backend.sh

dev-frontend:
	cd $(FRONTEND) && npm run dev

test: test-backend test-frontend

test-backend:
	cd $(BACKEND) && uv run pytest

test-frontend:
	@if [ -f $(FRONTEND)/package.json ] && grep -q '"test"' $(FRONTEND)/package.json; then \
		cd $(FRONTEND) && npm run test; \
	else echo "frontend tests not configured — skipping"; fi

lint: lint-backend lint-frontend

lint-backend:
	cd $(BACKEND) && uv run ruff check .

lint-frontend:
	@if [ -f $(FRONTEND)/tsconfig.json ]; then cd $(FRONTEND) && npx tsc --noEmit; \
	else echo "frontend/tsconfig.json missing — skipping"; fi

build: build-frontend build-backend

build-frontend:
	@if [ -f $(FRONTEND)/package.json ]; then cd $(FRONTEND) && npm run build; \
	else echo "frontend/package.json missing — skipping"; fi

build-backend:
	cd $(BACKEND) && docker build -f docker/image/api/Dockerfile -t overnight-saas-api:dev .

down:
	docker compose down

clean:
	rm -rf $(BACKEND)/.venv $(FRONTEND)/node_modules $(FRONTEND)/dist
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +
	find $(BACKEND) -type f -name '*.pyc' -delete
