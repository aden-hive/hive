.PHONY: lint format check test test-core test-tools install-hooks help

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

test: test-core test-tools ## Run all Python test suites

test-core: ## Run core framework tests
	cd core && uv run python -m pytest tests/ -v

test-tools: ## Run tools package tests
	cd tools && uv run pytest tests/ -v

install-hooks: ## Install pre-commit hooks
	uv pip install pre-commit
	pre-commit install
