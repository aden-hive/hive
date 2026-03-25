# Repository Guidelines

Shared agent instructions for this workspace.

## Coding Agent Notes

- When working on a GitHub Issue or PR, print the full URL at the end of the task.
- When answering questions, respond with high-confidence answers only: verify in code; do not guess.
- Do not update dependencies casually. Version bumps, patched dependencies, overrides, or vendored dependency changes require explicit approval.
- Add brief comments for tricky logic. Keep files reasonably small when practical; split or refactor large files instead of growing them indefinitely.
- If shared guardrails are available locally, review them; otherwise follow this repo's guidance.
- Use `uv` for Python execution and package management. Do not use `python` or `python3` directly unless the user explicitly asks for it.
- Prefer `uv run` for scripts and tests, and `uv pip` for package operations.

## Multi-Agent Safety

- Do not create, apply, or drop `git stash` entries unless explicitly requested.
- Do not create, remove, or modify `git worktree` checkouts unless explicitly requested.
- Do not switch branches or check out a different branch unless explicitly requested.
- When the user says `push`, you may `git pull --rebase` to integrate latest changes, but never discard other in-progress work.
- When the user says `commit`, commit only your changes. When the user says `commit all`, commit everything in grouped chunks.
- When you see unrecognized files or unrelated changes, keep going and focus on your scoped changes.

## Change Hygiene

- If staged and unstaged diffs are formatting-only, resolve them without asking.
- If a commit or push was already requested, include formatting-only follow-up changes in that same commit when practical.
- Only stop to ask for confirmation when changes are semantic and may alter behavior.

---

## Project Overview

**Hive** is an open-source AI agent framework (Apache 2.0) for building goal-driven, self-improving agents. It supports multi-agent systems, human-in-the-loop controls, real-time observability, and 100+ tool integrations.

- **Framework package**: `core/` — Python agent runtime, CLI, graph execution, LLM integration
- **Tools package**: `tools/` — MCP-compatible tool library (`aden_tools`)
- **Frontend**: `core/frontend/` — React + TypeScript + Vite web UI
- **CLI entry point**: `hive` (maps to `framework.cli:main`)

---

## Repository Structure

```
hive/
├── core/                    # Agent runtime (Python package: "framework" v0.7.1)
│   ├── framework/           # Main source directory
│   │   ├── agents/          # Agent definitions and lifecycle management
│   │   ├── cli.py           # CLI interface (hive command)
│   │   ├── config.py        # Configuration management
│   │   ├── credentials/     # Credential encryption and storage
│   │   ├── debugger/        # Debugging utilities
│   │   ├── graph/           # Agent graph execution engine
│   │   ├── llm/             # LLM integrations (Anthropic, LiteLLM)
│   │   ├── monitoring/      # Metrics and cost tracking
│   │   ├── observability/   # Real-time agent observability
│   │   ├── runner/          # Agent runner logic
│   │   ├── runtime/         # Core agent runtime execution
│   │   ├── schemas/         # Pydantic data models and validation
│   │   ├── server/          # aiohttp web server
│   │   ├── skills/          # Agent skills registry
│   │   ├── storage/         # Persistent state storage
│   │   ├── testing/         # Testing utilities
│   │   ├── tools/           # Tool integration layer
│   │   └── utils/           # Shared utilities
│   ├── frontend/            # Web UI (React + TypeScript + Vite)
│   │   └── src/             # UI components
│   ├── tests/               # Framework tests (pytest)
│   ├── examples/            # Example agent definitions
│   └── pyproject.toml       # Package config (Python >=3.11, hatchling build)
│
├── tools/                   # MCP tools library (Python package: "tools" v0.1.0)
│   ├── src/aden_tools/      # Tool implementations (100+ tools)
│   │   ├── credentials/     # API key management
│   │   └── tools/           # Tool categories: files, web, comms, CRM, cloud, etc.
│   ├── tests/               # Tool tests
│   ├── mcp_server.py        # MCP server entry point
│   ├── Dockerfile           # Container for MCP tools server
│   └── pyproject.toml       # Package config
│
├── docs/                    # Documentation
│   ├── architecture/        # System design documents
│   └── key_concepts/        # Goals, evolution, graph concepts
├── examples/                # Template agents
├── scripts/                 # Utility scripts
├── .github/workflows/       # CI/CD (lint, test, release, PR checks)
├── Makefile                 # Development targets
├── pyproject.toml           # UV workspace root (members: core, tools)
├── package.json             # Root npm config (Node >=20.0.0, npm >=10.2.0)
└── quickstart.sh            # Setup script
```

---

## Development Workflows

### Python (uv workspace)

The repo is a UV workspace with two members: `core` and `tools`.

```bash
# Install all dependencies
uv sync

# Run framework tests
cd core && uv run python -m pytest tests/ -v

# Run tool tests (mocked, no credentials needed)
cd tools && uv run python -m pytest -v

# Run live integration tests (requires real API credentials)
cd tools && uv run python -m pytest -m live -s -o "addopts=" --log-cli-level=INFO
```

### Makefile Targets

```bash
make lint          # Ruff linter + formatter with auto-fix (core + tools)
make format        # Ruff formatter only (core + tools)
make check         # CI-safe checks, no file modifications
make test          # Core + tools tests (excludes live)
make test-tools    # Tools tests only
make test-live     # Live integration tests
make test-all      # Everything including live tests
make install-hooks # Install pre-commit hooks
make frontend-install  # npm install for frontend
make frontend-dev      # Start Vite dev server
make frontend-build    # Production frontend build
```

### Frontend (React + Vite)

```bash
cd core/frontend
npm install
npm run dev      # Development server
npm run build    # Production build
```

---

## Code Style & Linting

Both `core` and `tools` use **Ruff** with identical configuration:

- **Python target**: 3.11
- **Line length**: 100
- **Enabled rules**: `B` (bugbear), `C4` (comprehensions), `E`/`W` (pycodestyle), `F` (pyflakes), `I` (isort), `Q` (quotes), `UP` (py-upgrade)
- **Import order**: future → stdlib → third-party → first-party → local
- First-party packages: `framework` (core), `aden_tools` (tools)

Run `make lint` before committing. CI runs `make check` (no auto-fix).

---

## Testing Conventions

- Tests live in `core/tests/` (framework) and `tools/tests/` (tools)
- Use `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"` in tools)
- Live tests require real API credentials and are marked `@pytest.mark.live`
- Live tests are excluded by default (`addopts = "-m 'not live'"` in tools)
- CI never runs live tests
- Use `pytest-xdist` for parallel test execution where needed

---

## Key Dependencies

**Framework (`core`)**:
- `anthropic>=0.40.0` — Primary LLM provider
- `litellm>=1.81.0` — Multi-provider LLM abstraction
- `mcp>=1.0.0`, `fastmcp>=2.0.0` — Model Context Protocol
- `pydantic>=2.0` — Data validation and schemas
- `aiohttp>=3.9.0` — Web server (optional: `server`, `webhook` extras)
- `croniter>=1.4.0` — Scheduled agent execution

**Tools (`tools`)**:
- `playwright>=1.40.0` + `playwright-stealth` — Browser automation
- `beautifulsoup4`, `pypdf`, `pandas` — Data processing
- `resend`, `asana`, `stripe`, `arxiv` — Service integrations
- `psycopg2-binary` — PostgreSQL
- Optional extras: `ocr`, `excel`, `sql` (duckdb), `bigquery`, `databricks`, `sandbox`

---

## CI/CD

GitHub Actions workflows in `.github/workflows/`:

| Workflow | Purpose |
|---|---|
| `ci.yml` | Main CI: lint → test → test-tools → validate (Python 3.11, Ubuntu + Windows) |
| `release.yml` | Package release automation |
| `pr-check-command.yml` | PR validation and slash commands |
| `pr-requirements.yml` | PR requirement enforcement |
| `auto-close-duplicates.yml` | Duplicate issue management |
| `bounty-completed.yml` | Contributor bounty tracking |
| `claude-issue-triage.yml` | AI-powered issue triage |
| `weekly-leaderboard.yml` | Community contributor leaderboard |

CI matrix: **ubuntu-latest** and **windows-latest**.

---

## Adding Tools

New tools go in `tools/src/aden_tools/tools/<category>/`. Each tool should:
1. Implement the tool function with proper type annotations
2. Include a `tests/` subdirectory with mocked tests
3. Register the tool in the appropriate category `__init__.py`
4. Not add credentials directly to code — use the credential store

---

## Credentials & Storage

- Credentials are stored encrypted at `~/.hive/credentials`
- Use the credential management API in `core/framework/credentials/`
- Never commit API keys or secrets
- Live test credentials must be set as environment variables or in the credential store
