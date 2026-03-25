# Developer Guide

This guide covers everything you need to know to develop with the Aden Agent Framework.

## Table of Contents

1. [Repository Overview](#repository-overview)
2. [Initial Setup](#initial-setup)
3. [Project Structure](#project-structure)
4. [Building Agents](#building-agents)
5. [Running Agents](#running-agents)
6. [Testing Agents](#testing-agents)
7. [Code Style & Conventions](#code-style--conventions)
8. [Git Workflow](#git-workflow)
9. [Common Tasks](#common-tasks)
10. [Troubleshooting](#troubleshooting)

---

## Repository Overview

Aden Agent Framework is a Python-based system for building goal-driven, self-improving AI agents.

| Package       | Directory  | Description                               | Tech Stack   |
| ------------- | ---------- | ----------------------------------------- | ------------ |
| **framework** | `/core`    | Core runtime, graph executor, protocols   | Python 3.11+ |
| **tools**     | `/tools`   | MCP tools for agent capabilities          | Python 3.11+ |
| **exports**   | `/exports` | Agent packages (user-created, gitignored) | Python 3.11+ |
| **skills**    | `.claude`, `.agents`, `.agent` | Shared skills for Claude/Codex/other coding agents | Markdown     |
| **codex**     | `.codex`   | Codex CLI project configuration (MCP servers) | TOML         |

### Key Principles

- **Goal-Driven Development**: Define objectives, framework generates agent graphs
- **Self-Improving**: Agents adapt and evolve based on failures
- **SDK-Wrapped Nodes**: Built-in memory, monitoring, and tool access
- **Human-in-the-Loop**: Intervention points for human oversight
- **Production-Ready**: Evaluation, testing, and deployment infrastructure

---

## Initial Setup

See [environment-setup.md](./environment-setup.md) for the full setup guide, including Windows, Alpine Linux, and troubleshooting.

### Quick Start

```bash
git clone https://github.com/adenhq/hive.git
cd hive
./quickstart.sh
```

### Verify Setup

```bash
uv run python -c "import framework; print('OK')"
uv run python -c "import aden_tools; print('OK')"
uv run python -c "import litellm; print('OK')"
```

---

## Project Structure

```
hive/                                    # Repository root
│
├── .github/                             # GitHub configuration
│   ├── workflows/
│   │   ├── ci.yml                       # Lint, test, validate on every PR
│   │   ├── release.yml                  # Runs on tags
│   │   ├── pr-requirements.yml          # PR requirement checks
│   │   ├── pr-check-command.yml         # PR check commands
│   │   ├── claude-issue-triage.yml      # Automated issue triage
│   │   └── auto-close-duplicates.yml    # Close duplicate issues
│   ├── ISSUE_TEMPLATE/                  # Bug report & feature request templates
│   ├── PULL_REQUEST_TEMPLATE.md         # PR description template
│   └── CODEOWNERS                       # Auto-assign reviewers
│
├── .codex/                              # Codex CLI project config
│   └── config.toml                      # Codex MCP server definitions
│
├── core/                                # CORE FRAMEWORK PACKAGE
│   ├── framework/                       # Main package code
│   │   ├── agents/                      # Agent definitions and helpers
│   │   ├── builder/                     # Agent builder utilities
│   │   ├── credentials/                 # Credential management
│   │   ├── debugger/                    # Debugging tools
│   │   ├── graph/                       # GraphExecutor - executes node graphs
│   │   ├── llm/                         # LLM provider integrations (Anthropic, OpenAI, OpenRouter, Hive, etc.)
│   │   ├── mcp/                         # MCP server integration
│   │   ├── monitoring/                  # Runtime monitoring
│   │   ├── observability/               # Structured logging - human-readable and machine-parseable tracing
│   │   ├── runner/                      # AgentRunner - loads and runs agents
│   │   ├── runtime/                     # Runtime environment
│   │   ├── schemas/                     # Data schemas
│   │   ├── server/                      # HTTP API server
│   │   ├── skills/                      # Skill definitions
│   │   ├── storage/                     # File-based persistence
│   │   ├── testing/                     # Testing utilities
│   │   ├── tools/                       # Built-in tool implementations
│   │   ├── tui/                         # Terminal UI dashboard
│   │   └── utils/                       # Shared utilities
│   ├── tests/                           # Unit and E2E tests (including dummy agents)
│   ├── pyproject.toml                   # Package metadata and dependencies
│   ├── README.md                        # Framework documentation
│   └── MCP_INTEGRATION_GUIDE.md         # MCP server integration guide
│
├── tools/                               # TOOLS PACKAGE (MCP tools)
│   ├── src/
│   │   └── aden_tools/
│   │       ├── tools/                   # Individual tool implementations
│   │       │   ├── web_search_tool/
│   │       │   ├── web_scrape_tool/
│   │       │   ├── file_system_toolkits/
│   │       │   └── ...                  # Additional tools
│   │       ├── mcp_server.py            # HTTP MCP server
│   │       └── __init__.py
│   ├── pyproject.toml                   # Package metadata
│   └── README.md                        # Tools documentation
│
├── exports/                             # AGENT PACKAGES (user-created, gitignored)
│   └── your_agent_name/                 # Created via coder-tools workflow
│
├── examples/                            # Example agents
│   └── templates/                       # Pre-built template agents
│
├── docs/                                # Documentation
│   ├── getting-started.md               # Quick start guide
│   ├── configuration.md                 # Configuration reference
│   ├── architecture/                    # System architecture
│   ├── articles/                        # Technical articles
│   ├── quizzes/                         # Developer quizzes
│   └── i18n/                            # Translations
│
├── scripts/                             # Utility scripts
│   └── auto-close-duplicates.ts         # GitHub duplicate issue closer
│
├── .agent/                        # Antigravity IDE: mcp_config.json + skills (symlinks)
├── quickstart.sh                        # Interactive setup wizard
├── README.md                            # Project overview
├── CONTRIBUTING.md                      # Contribution guidelines
├── LICENSE                              # Apache 2.0 License
├── docs/CODE_OF_CONDUCT.md              # Community guidelines
└── SECURITY.md                          # Security policy
```

---

## Building Agents

### Using Coder Tools Workflow

The fastest way to build agents is with the configured MCP workflow:

```bash
# Install dependencies (one-time)
./quickstart.sh

# Build a new agent
Use the coder-tools MCP tools from your IDE agent chat (e.g., initialize_and_build_agent)
```

### Agent Development Workflow

1. **Define Your Goal**

   ```
   Use the coder-tools initialize_and_build_agent tool
   Enter goal: "Build an agent that processes customer support tickets"
   ```

2. **Design the Workflow**

   - The workflow guides you through defining nodes
   - Each node is a unit of work (LLM call with event_loop)
   - Edges define how execution flows

3. **Generate the Agent**

   - The workflow generates a complete Python package in `exports/`
   - Includes: `agent.json`, `tools.py`, `README.md`

4. **Validate the Agent**

   ```bash
   PYTHONPATH=exports uv run python -m your_agent_name validate
   ```

5. **Test the Agent**
   Run tests with:
   ```bash
   PYTHONPATH=exports uv run python -m your_agent_name test
   ```

### Manual Agent Development

If you prefer to build agents manually:

```python
# exports/my_agent/agent.json
{
  "goal": {
    "goal_id": "support_ticket",
    "name": "Support Ticket Handler",
    "description": "Process customer support tickets",
    "success_criteria": "Ticket is categorized, prioritized, and routed correctly"
  },
  "nodes": [
    {
      "node_id": "analyze",
      "name": "Analyze Ticket",
      "node_type": "event_loop",
      "system_prompt": "Analyze this support ticket...",
      "input_keys": ["ticket_content"],
      "output_keys": ["category", "priority"]
    }
  ],
  "edges": [
    {
      "edge_id": "start_to_analyze",
      "source": "START",
      "target": "analyze",
      "condition": "on_success"
    }
  ]
}
```

---

## Running Agents

### Using the `hive` CLI

```bash
# Browse and run agents interactively (Recommended)
hive tui

# Run a specific agent
hive run exports/my_agent --input '{"ticket_content": "My login is broken", "customer_id": "CUST-123"}'

# Run with TUI dashboard
hive run exports/my_agent --tui
```

### CLI Command Reference

| Command                | Description                                                             |
| ---------------------- | ----------------------------------------------------------------------- |
| `hive tui`             | Browse agents and launch TUI dashboard                                  |
| `hive run <path>`      | Execute an agent (`--tui`, `--model`, `--mock`, `--quiet`, `--verbose`) |
| `hive shell [path]`    | Interactive REPL (`--multi`, `--no-approve`)                            |
| `hive info <path>`     | Show agent details                                                      |
| `hive validate <path>` | Validate agent structure                                                |
| `hive list [dir]`      | List available agents                                                   |
| `hive dispatch [dir]`  | Multi-agent orchestration                                               |

### Using Python Directly

```bash
PYTHONPATH=exports uv run python -m agent_name run --input '{...}'
```

---

## Testing Agents

### Agent Tests

```bash
# Run tests for an agent
PYTHONPATH=exports uv run python -m agent_name test

# Run specific test type
PYTHONPATH=exports uv run python -m agent_name test --type constraint
PYTHONPATH=exports uv run python -m agent_name test --type success

# Run with parallel execution
PYTHONPATH=exports uv run python -m agent_name test --parallel 4

# Fail fast (stop on first failure)
PYTHONPATH=exports uv run python -m agent_name test --fail-fast
```

### Framework Tests

```bash
# Run all unit tests (core + tools)
make test

# Run linting and format checks
make check
```

### Dummy Agent Tests (E2E)

The repository includes end-to-end dummy agent tests under `core/tests/dummy_agents/` that run real LLM calls against deterministic graph structures. These are **not** part of CI — run them manually to verify the executor works with real providers.

```bash
cd core && uv run python tests/dummy_agents/run_all.py
```

The script detects available LLM credentials and prompts you to pick a provider. For verbose output:

```bash
cd core && uv run python tests/dummy_agents/run_all.py --verbose
```

See [environment-setup.md](./environment-setup.md#testing-with-dummy-agents) for the full list of covered agents and details.

### Writing Custom Tests

```python
# exports/my_agent/tests/test_custom.py
import pytest
from framework.runner import AgentRunner

def test_ticket_categorization():
    """Test that tickets are categorized correctly"""
    runner = AgentRunner.from_file("exports/my_agent/agent.json")

    result = runner.run({
        "ticket_content": "I can't log in to my account"
    })

    assert result["category"] == "authentication"
    assert result["priority"] in ["high", "medium", "low"]
```

---

## Code Style & Conventions

### Python Code Style

- **PEP 8** - Follow Python style guide
- **Type hints** - Use for function signatures and class attributes
- **Docstrings** - Document classes and public functions
- **Ruff** - Linter and formatter (run with `make check`)

```python
# Good
from typing import Optional, Dict, Any

def process_ticket(
    ticket_content: str,
    customer_id: str,
    priority: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process a customer support ticket.

    Args:
        ticket_content: The content of the ticket
        customer_id: The customer's ID
        priority: Optional priority override

    Returns:
        Dictionary with processing results
    """
    # Implementation
    return {"status": "processed", "id": ticket_id}

# Avoid
def process_ticket(ticket_content, customer_id, priority=None):
    # No types, no docstring
    return {"status": "processed", "id": ticket_id}
```

### Agent Package Structure

```
my_agent/
├── __init__.py              # Package initialization
├── __main__.py              # CLI entry point
├── agent.json               # Agent definition (nodes, edges, goal)
├── tools.py                 # Custom tools (optional)
├── mcp_servers.json         # MCP server config (optional)
├── README.md                # Agent documentation
└── tests/                   # Test files
    ├── __init__.py
    ├── test_constraint.py   # Constraint tests
    └── test_success.py      # Success criteria tests
```

### File Naming

| Type                | Convention       | Example                  |
| ------------------- | ---------------- | ------------------------ |
| Modules             | snake_case       | `ticket_handler.py`      |
| Classes             | PascalCase       | `TicketHandler`          |
| Functions/Variables | snake_case       | `process_ticket()`       |
| Constants           | UPPER_SNAKE_CASE | `MAX_RETRIES = 3`        |
| Test files          | `test_` prefix   | `test_ticket_handler.py` |
| Agent packages      | snake_case       | `support_ticket_agent/`  |

### Import Order

1. Standard library
2. Third-party packages
3. Framework imports
4. Local imports

```python
# Standard library
import json
from typing import Dict, Any

# Third-party
import litellm
from pydantic import BaseModel

# Framework
from framework.runner import AgentRunner
from framework.context import NodeContext

# Local
from .tools import custom_tool
```

---

## Git Workflow

### Branch Naming

```
feature/add-user-authentication
bugfix/fix-login-redirect
hotfix/security-patch
chore/update-dependencies
docs/improve-readme
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**

- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation only
- `style` - Formatting, missing semicolons, etc.
- `refactor` - Code change that neither fixes a bug nor adds a feature
- `test` - Adding or updating tests
- `chore` - Maintenance tasks

**Examples:**

```
feat(auth): add JWT authentication

fix(api): handle null response from external service

docs(readme): update installation instructions

chore(deps): update React to 18.2.0
```

### Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with clear commits
3. Run tests locally: `make test`
4. Run linting: `make check`
5. Push and create a PR
6. Fill out the PR template
7. Request review from CODEOWNERS
8. Address feedback
9. Squash and merge when approved

---

## Common Tasks

### Adding Python Dependencies

```bash
# Add to core framework
cd core
uv add <package>

# Add to tools package
cd tools
uv add <package>
```

### Creating a New Agent

```bash
# Option 1: Use Claude Code skill (recommended)
Use the coder-tools initialize_and_build_agent tool

# Option 2: Create manually
# Note: exports/ is initially empty (gitignored). Create your agent directory:
mkdir -p exports/my_new_agent
cd exports/my_new_agent
# Create agent.json, tools.py, README.md (see Agent Package Structure below)

# Option 3: Use the coder-tools MCP tools (advanced)
# See core/MCP_BUILDER_TOOLS_GUIDE.md
```

### Adding Custom Tools to an Agent

```python
# exports/my_agent/tools.py
from typing import Dict, Any

def my_custom_tool(param1: str, param2: int) -> Dict[str, Any]:
    """
    Description of what this tool does.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Dictionary with tool results
    """
    # Implementation
    return {"result": "success", "data": ...}

# Register tool in agent.json
{
  "nodes": [
    {
      "node_id": "use_tool",
      "node_type": "event_loop",
      "tools": ["my_custom_tool"],
      ...
    }
  ]
}
```

### Adding MCP Server Integration

```bash
# 1. Create mcp_servers.json in your agent package
# exports/my_agent/mcp_servers.json
{
  "tools": {
    "transport": "stdio",
    "command": "python",
    "args": ["-m", "aden_tools.mcp_server"],
    "cwd": "tools/",
    "description": "File system and web tools"
  }
}

# 2. Reference tools in agent.json
{
  "nodes": [
    {
      "node_id": "search",
      "tools": ["web_search", "web_scrape"],
      ...
    }
  ]
}
```

### Setting Environment Variables

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"
export OPENROUTER_API_KEY="your-key-here"
export HIVE_API_KEY="your-key-here"
export BRAVE_SEARCH_API_KEY="your-key-here"

# Or create .env file (not committed to git)
echo 'ANTHROPIC_API_KEY=your-key-here' >> .env
```

### Debugging Agent Execution

```bash
# Run with verbose output
hive run exports/my_agent --verbose --input '{"task": "..."}'

```

---

## Troubleshooting

See [environment-setup.md](./environment-setup.md#troubleshooting) for common setup issues (module not found errors, broken installations, PEP 668, etc.).

---

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: Search [existing issues](https://github.com/adenhq/hive/issues)
- **Discord**: Join our [community](https://discord.com/invite/MXE49hrKDk)
- **Code Review**: Tag a maintainer on your PR
