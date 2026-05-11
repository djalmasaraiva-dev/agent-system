SHELL := /bin/bash
.DEFAULT_GOAL := help

PROJECT_ID ?= $(shell gcloud config get-value project 2>/dev/null)
LOCATION   ?= us-central1
SERVICE    ?= agent-system
IMAGE      ?= $(LOCATION)-docker.pkg.dev/$(PROJECT_ID)/$(SERVICE)/$(SERVICE):latest

.PHONY: help install lint format type test test-cov backend playground load-test \
        docker-build docker-run deploy-cloudrun deploy-agent-engine clean

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies (uv sync).
	uv sync --all-extras

lint: ## Run ruff lint.
	uv run ruff check app tests

format: ## Run ruff format and import-sort.
	uv run ruff format app tests
	uv run ruff check --fix --select I app tests

type: ## Run mypy.
	uv run mypy app

test: ## Run pytest unit tests.
	uv run pytest tests/unit -v

test-cov: ## Run tests with coverage.
	uv run pytest tests/unit --cov=app --cov-report=term-missing

backend: ## Run FastAPI server with hot reload (dev).
	uv run uvicorn app.server:app --host 0.0.0.0 --port 8080 --reload

playground: ## Launch ADK web playground for the coordinator agent.
	uv run adk web app/agent.py

load-test: ## Run locust load test (requires backend running).
	uv run locust -f tests/load_test/load_test.py --host http://localhost:8080

docker-build: ## Build container image.
	docker build -t $(IMAGE) -f Dockerfile .

docker-run: ## Run the container locally with .env file.
	docker run --rm -p 8080:8080 --env-file .env $(IMAGE)

deploy-cloudrun: ## Deploy to Cloud Run (sets up IAP, Agent Identity).
	bash deployment/cloudrun_deploy.sh

deploy-agent-engine: ## Deploy coordinator to Vertex AI Agent Engine.
	uv run python deployment/agent_engine_deploy.py

clean: ## Remove caches and build artefacts.
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
