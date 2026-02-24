.PHONY: lint format check test install-hooks help

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

test: ## Run all tests
	cd core && uv run python -m pytest tests/ -v

install-hooks: ## Install pre-commit hooks
	uv pip install pre-commit
	pre-commit install

setup-venv: ## Create venv, install deps, and set PYTHONPATH (VENV=./.venv)
	@VENV=$${VENV:-.venv}; \
	python3 -m venv $$VENV; \
	$$VENV/bin/pip install --upgrade pip; \
	$$VENV/bin/pip install -r core/requirements.txt; \
	$$VENV/bin/pip install -e core -e tools; \
	PYTHONPATH_LINE='export PYTHONPATH="$(PWD)/core:$(PWD)/exports"'; \
	ACTIVATE_FILE="$$VENV/bin/activate"; \
	if ! grep -Fq "$$PYTHONPATH_LINE" "$$ACTIVATE_FILE"; then \
		printf '\n# Added by make setup-venv\n%s\n' "$$PYTHONPATH_LINE" >> "$$ACTIVATE_FILE"; \
	fi; \
	echo "Venv ready: $$VENV"; \
	echo "Activate with: source $$VENV/bin/activate"