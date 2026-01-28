# Developer Guide

This guide covers everything you need to know to develop with the Aden Agent Framework.

## Table of Contents

1. [Repository Overview](#repository-overview)
2. [Initial Setup](#initial-setup)
3. [Project Structure](#project-structure)
4. [Building Agents](#building-agents)
5. [Testing Agents](#testing-agents)
6. [Code Style & Conventions](#code-style--conventions)
7. [Git Workflow](#git-workflow)
8. [Common Tasks](#common-tasks)
9. [Troubleshooting](#troubleshooting)

---

## Repository Overview

Aden Agent Framework is a Python-based system for building goal-driven, self-improving AI agents.

| Package       | Directory  | Description                             | Tech Stack   |
| ------------- | ---------- | --------------------------------------- | ------------ |
| **framework** | `/core`    | Core runtime, graph executor, protocols | Python 3.11+ |
| **tools**     | `/tools`   | 19 MCP tools for agent capabilities     | Python 3.11+ |
| **exports**   | `/exports` | Agent packages and examples             | Python 3.11+ |
| **skills**    | `.claude`  | Claude Code skills for building/testing | Markdown     |

### Key Principles

- **Goal-Driven Development**: Define objectives, framework generates agent graphs
- **Self-Improving**: Agents adapt and evolve based on failures
- **SDK-Wrapped Nodes**: Built-in memory, monitoring, and tool access
- **Human-in-the-Loop**: Intervention points for human oversight
- **Production-Ready**: Evaluation, testing, and deployment infrastructure

---

## Initial Setup

### Prerequisites

Ensure you have installed:

- **Python 3.11+** - [Download](https://www.python.org/downloads/) (3.12 or 3.13 recommended)
- **pip** - Package installer for Python (comes with Python)
- **git** - Version control
- **Claude Code** - [Install](https://docs.anthropic.com/claude/docs/claude-code) (optional, for using building skills)

Verify installation:

```bash
python --version    # Should be 3.11+
pip --version       # Should be latest
git --version       # Any recent version
```

### Step-by-Step Setup

```bash
# 1. Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# 2. Run automated Python setup
./scripts/setup-python.sh
```

The setup script performs these actions:

1. Checks Python version (3.11+)
2. Installs `framework` package from `/core` (editable mode)
3. Installs `aden_tools` package from `/tools` (editable mode)
4. Fixes package compatibility (upgrades openai for litellm)
5. Verifies all installations

### API Keys (Optional)

For running agents with real LLMs:

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"        # Optional
export BRAVE_SEARCH_API_KEY="your-key-here"  # Optional, for web search tool
```

Get API keys:

- **Anthropic**: [console.anthropic.com](https://console.anthropic.com/)
- **OpenAI**: [platform.openai.com](https://platform.openai.com/)
- **Brave Search**: [brave.com/search/api](https://brave.com/search/api/)

### Install Claude Code Skills

```bash
# Install building-agents and testing-agent skills
./quickstart.sh
```

This installs:

- `/building-agents` - Build new goal-driven agents
- `/testing-agent` - Test agents with evaluation framework

### Verify Setup

```bash
# Verify package imports
python -c "import framework; print('✓ framework OK')"
python -c "import aden_tools; print('✓ aden_tools OK')"
python -c "import litellm; print('✓ litellm OK')"

# Run an example agent
PYTHONPATH=core:exports python -m support_ticket_agent validate
```

---

## Project Structure

```
hive/                                    # Repository root
│
├── .github/                             # GitHub configuration
│   ├── workflows/
│   │   ├── ci.yml                       # Runs on every PR
│   │   └── release.yml                  # Runs on tags
│   ├── ISSUE_TEMPLATE/                  # Bug report & feature request templates
│   ├── PULL_REQUEST_TEMPLATE.md         # PR description template
│   └── CODEOWNERS                       # Auto-assign reviewers
│
├── .claude/                             # Claude Code Skills
│   └── skills/
│       ├── building-agents/             # Skills for building agents
│       │   ├── SKILL.md                 # Main skill definition
│       │   ├── building-agents-core/
│       │   ├── building-agents-patterns/
│       │   └── building-agents-construction/
│       ├── testing-agent/               # Skills for testing agents
│       │   └── SKILL.md
│       └── agent-workflow/              # Complete workflow orchestration
│
├── core/                                # CORE FRAMEWORK PACKAGE
│   ├── framework/                       # Main package code
│   │   ├── runner/                      # AgentRunner - loads and runs agents
│   │   ├── executor/                    # GraphExecutor - executes node graphs
│   │   ├── protocols/                   # Standard protocols (hooks, tracing, etc.)
│   │   ├── llm/                         # LLM provider integrations (Anthropic, OpenAI, etc.)
│   │   ├── memory/                      # Memory systems (STM, LTM/RLM)
│   │   ├── tools/                       # Tool registry and management
│   │   └── __init__.py
│   ├── pyproject.toml                   # Package metadata and dependencies
│   ├── requirements.txt                 # Python dependencies
│   ├── README.md                        # Framework documentation
│   ├── MCP_INTEGRATION_GUIDE.md         # MCP server integration guide
│   └── docs/                            # Protocol documentation
│
├── tools/                               # TOOLS PACKAGE (19 MCP tools)
│   ├── src/
│   │   └── aden_tools/
│   │       ├── tools/                   # Individual tool implementations
│   │       │   ├── web_search_tool/
│   │       │   ├── web_scrape_tool/
│   │       │   ├── file_system_toolkits/
│   │       │   └── ...                  # 19 tools total
│   │       ├── mcp_server.py            # HTTP MCP server
│   │       └── __init__.py
│   ├── pyproject.toml                   # Package metadata
│   ├── requirements.txt                 # Python dependencies
│   └── README.md                        # Tools documentation
│
├── exports/                             # AGENT PACKAGES
│   ├── support_ticket_agent/            # Example: Support ticket handler
│   ├── market_research_agent/           # Example: Market research
│   ├── outbound_sales_agent/            # Example: Sales outreach
│   ├── personal_assistant_agent/        # Example: Personal assistant
│   └── ...                              # More agent examples
│
├── docs/                                # Documentation
│   ├── getting-started.md               # Quick start guide
│   ├── configuration.md                 # Configuration reference
│   ├── architecture.md                  # System architecture
│   └── articles/                        # Technical articles
│
├── scripts/                             # Build & utility scripts
│   ├── setup-python.sh                  # Python environment setup
│   └── setup.sh                         # Legacy setup script
│
├── quickstart.sh                        # Install Claude Code skills
├── ENVIRONMENT_SETUP.md                 # Complete Python setup guide
├── README.md                            # Project overview
├── DEVELOPER.md                         # This file
├── CONTRIBUTING.md                      # Contribution guidelines
├── CHANGELOG.md                         # Version history
├── ROADMAP.md                           # Product roadmap
├── LICENSE                              # Apache 2.0 License
├── CODE_OF_CONDUCT.md                   # Community guidelines
└── SECURITY.md                          # Security policy
```

---

## Building Agents

### Using Claude Code Skills

The fastest way to build agents is using the Claude Code skills:

```bash
# Install skills (one-time)
./quickstart.sh

# Build a new agent
claude> /building-agents-construction

# Test the agent
claude> /testing-agent
```

### Agent Development Workflow

1. **Define Your Goal**

   ```
   claude> /building-agents-construction
   Enter goal: "Build an agent that processes customer support tickets"
   ```

2. **Design the Workflow**

   - The skill guides you through defining nodes
   - Each node is a unit of work (LLM call, function, router)
   - Edges define how execution flows

3. **Generate the Agent**

   - The skill generates a complete Python package in `exports/`
   - Includes: `agent.json`, `tools.py`, `README.md`

4. **Validate the Agent**

   ```bash
   PYTHONPATH=core:exports python -m your_agent_name validate
   ```

5. **Test the Agent**
   ```
   claude> /testing-agent
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
      "node_type": "llm_generate",
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

### Running Agents

```bash
# Validate agent structure
PYTHONPATH=core:exports python -m agent_name validate

# Show agent information
PYTHONPATH=core:exports python -m agent_name info

# Run agent with input
PYTHONPATH=core:exports python -m agent_name run --input '{
  "ticket_content": "My login is broken",
  "customer_id": "CUST-123"
}'

# Run in mock mode (no LLM calls)
PYTHONPATH=core:exports python -m agent_name run --mock --input '{...}'
```

---

## Testing Agents

### Using the Testing Agent Skill

```bash
# Run tests for an agent
claude> /testing-agent
```

This generates and runs:

- **Constraint tests** - Verify agent respects constraints
- **Success tests** - Verify agent achieves success criteria
- **Integration tests** - End-to-end workflows

### Manual Testing

```bash
# Run all tests for an agent
PYTHONPATH=core:exports python -m agent_name test

# Run specific test type
PYTHONPATH=core:exports python -m agent_name test --type constraint
PYTHONPATH=core:exports python -m agent_name test --type success

# Run with parallel execution
PYTHONPATH=core:exports python -m agent_name test --parallel 4

# Fail fast (stop on first failure)
PYTHONPATH=core:exports python -m agent_name test --fail-fast
```

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
- **Black** - Code formatter (run with `black .`)

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
3. Run tests locally: `npm run test`
4. Run linting: `npm run lint`
5. Push and create a PR
6. Fill out the PR template
7. Request review from CODEOWNERS
8. Address feedback
9. Squash and merge when approved

---

## Debugging

### Frontend Debugging

**React Developer Tools:**

1. Install the [React DevTools browser extension](https://react.dev/learn/react-developer-tools)
2. Open browser DevTools → React tab
3. Inspect component tree, props, state, and hooks

**VS Code Debugging:**

1. Add Chrome debug configuration to `.vscode/launch.json`:

```json
{
  "type": "chrome",
  "request": "launch",
  "name": "Debug Frontend",
  "url": "http://localhost:3000",
  "webRoot": "${workspaceFolder}/honeycomb/src"
}
```

2. Start the dev server: `npm run dev -w honeycomb`
3. Press F5 in VS Code

### Backend Debugging

**VS Code Debugging:**

1. Add Node debug configuration:

```json
{
  "type": "node",
  "request": "launch",
  "name": "Debug Backend",
  "runtimeExecutable": "npm",
  "runtimeArgs": ["run", "dev"],
  "cwd": "${workspaceFolder}/hive",
  "console": "integratedTerminal"
}
```

2. Set breakpoints in your code
3. Press F5 to start debugging

**Logging:**

```typescript
import { logger } from "../utils/logger";

// Add debug logs
logger.debug("Processing request", {
  userId: req.user.id,
  body: req.body,
});
```

---

## Common Tasks

### Adding Python Dependencies

```bash
# Add to core framework
cd core
pip install <package>
# Then add to requirements.txt or pyproject.toml

# Add to tools package
cd tools
pip install <package>
# Then add to requirements.txt or pyproject.toml

# Reinstall in editable mode
pip install -e .
```

### Creating a New Agent

```bash
# Option 1: Use Claude Code skill (recommended)
claude> /building-agents-construction

# Option 2: Create manually
# Note: exports/ is initially empty (gitignored). Create your agent directory:
mkdir -p exports/my_new_agent
cd exports/my_new_agent
# Create agent.json, tools.py, README.md (see Agent Package Structure below)

# Option 3: Use the agent builder MCP tools (advanced)
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
      "node_type": "function",
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
export BRAVE_SEARCH_API_KEY="your-key-here"

# Or create .env file (not committed to git)
echo 'ANTHROPIC_API_KEY=your-key-here' >> .env
```

### Debugging Agent Execution

```python
# Add debug logging to your agent
import logging
logging.basicConfig(level=logging.DEBUG)

# Run with verbose output
PYTHONPATH=core:exports python -m agent_name run --input '{...}' --verbose

# Use mock mode to test without LLM calls
PYTHONPATH=core:exports python -m agent_name run --mock --input '{...}'
```

---

## Troubleshooting

### Port Already in Use

```bash
# Find process using port
lsof -i :3000
lsof -i :4000

# Kill process
kill -9 <PID>

# Or change ports in config.yaml and regenerate
```

### Node Modules Issues

```bash
# Clean everything and reinstall
npm run clean
rm -rf node_modules package-lock.json
npm install
```

### Docker Issues

```bash
# Reset Docker state
docker compose down -v
docker system prune -f
docker compose build --no-cache
docker compose up
```

### TypeScript Errors After Pull

```bash
# Rebuild TypeScript
npm run build

# Or restart TS server in VS Code
# Cmd/Ctrl + Shift + P → "TypeScript: Restart TS Server"
```

### Environment Variables Not Loading

```bash
# Regenerate from config.yaml
npm run generate:env

# Verify files exist
cat .env
cat honeycomb/.env
cat hive/.env

# Restart dev servers after changing env
```

### Tests Failing

```bash
# Run with verbose output
npm run test -w honeycomb -- --reporter=verbose

# Run single test file
npm run test -w honeycomb -- src/components/Button.test.tsx

# Clear test cache
npm run test -w honeycomb -- --clearCache
```

---

## Getting Help

- **Documentation**: Check the `/docs` folder
- **Issues**: Search [existing issues](https://github.com/adenhq/hive/issues)
- **Discord**: Join our [community](https://discord.com/invite/MXE49hrKDk)
- **Code Review**: Tag a maintainer on your PR

---

_Happy coding!_ 🐝
