.PHONY: lint format check test test-tools test-live test-all install-hooks help frontend-install frontend-dev frontend-build

# ── Ensure uv is findable in Git Bash on Windows ──────────────────────────────
# uv installs to ~/.local/bin on Windows/Linux/macOS. Git Bash may not include
# this in PATH by default, so we prepend it here.
export PATH := $(HOME)/.local/bin:$(PATH)

# ── Targets ───────────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

lint: ## Run ruff linter and formatter (with auto-fix)
	cd core && uv run ruff check --fix .
	cd tools && uv run ruff check --fix .
	cd core && uv run ruff format .
	cd tools && uv run ruff format .

format: ## Run ruff formatter
	cd core && uv run ruff format .
	cd tools && uv run ruff format .

check: ## Run all checks without modifying files (CI-safe)
	cd core && uv run ruff check .
	cd tools && uv run ruff check .
	cd core && uv run ruff format --check .
	cd tools && uv run ruff format --check .

test: ## Run all tests (core + tools, excludes live)
	cd core && uv run python -m pytest tests/ -v -n auto
	cd tools && uv run python -m pytest -v -n auto

test-tools: ## Run tool tests only (mocked, no credentials needed)
	cd tools && uv run python -m pytest -v -n auto

test-live: ## Run live integration tests (requires real API credentials)
	cd tools && uv run python -m pytest -m live -s -o "addopts=" --log-cli-level=INFO

test-all: ## Run everything including live tests
	cd core && uv run python -m pytest tests/ -v -n auto
	cd tools && uv run python -m pytest -v -n auto
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