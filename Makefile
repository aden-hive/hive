.PHONY: lint format check test install-hooks help frontend-install frontend-dev frontend-build

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

lint: ## Run ruff linter and formatter (with auto-fix)
	cd core && ruff check --fix .
	cd tools && ruff check --fix .
	cd core && ruff format .
	cd tools && ruff format .

format: ## Run ruff formatter
	cd core && ruff format .
	cd tools && ruff format .

check: ## Run all checks without modifying files (CI-safe)
	cd core && ruff check .
	cd tools && ruff check .
	cd core && ruff format --check .
	cd tools && ruff format --check .

test: ## Run all tests (core + tools, excludes live)
	cd core && uv run python -m pytest tests/ -v
	cd tools && uv run python -m pytest -v

test-tools: ## Run tool tests only (mocked, no credentials needed)
	cd tools && uv run python -m pytest -v

test-live: ## Run live integration tests (requires real API credentials)
	cd tools && uv run python -m pytest -m live -s -o "addopts=" --log-cli-level=INFO

test-all: ## Run everything including live tests
	cd core && uv run python -m pytest tests/ -v
	cd tools && uv run python -m pytest -v
	cd tools && uv run python -m pytest -m live -s -o "addopts=" --log-cli-level=INFO

install-hooks: ## Install pre-commit hooks
	uv pip install pre-commit
	pre-commit install

frontend-install: ## Install frontend npm packages
	cd core/frontend && npm install

frontend-dev: ## Start frontend dev server
	cd core/frontend && npm run dev

frontend-build: ## Build frontend for production
	cd core/frontend && npm run build
