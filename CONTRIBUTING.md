# Contributing to Aden Hive

> **"The best way to predict the future is to invent it."** — Alan Kay

Welcome to Aden Hive, an open-source AI agent framework built for developers who demand production-grade reliability, cross-platform support, and real-world performance. This guide will help you contribute effectively, whether you're fixing bugs, adding features, improving documentation, or building new tools.

Thank you for your interest in contributing! We're especially looking for help building tools, integrations ([check #2805](https://github.com/adenhq/hive/issues/2805)), and example agents for the framework.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Philosophy: Why We Build in the Open](#philosophy-why-we-build-in-the-open)
3. [Issue Assignment Policy](#issue-assignment-policy)
4. [Getting Started](#getting-started)
5. [OS Support: Write Once, Run Everywhere](#os-support-write-once-run-everywhere)
6. [Development Setup & Tooling](#development-setup--tooling)
7. [Tooling & Skills Required](#tooling--skills-required)
8. [LLM Models & Providers](#llm-models--providers)
9. [Sample Prompts & Agent Examples](#sample-prompts--agent-examples)
10. [Performance Metrics & Benchmarking](#performance-metrics--benchmarking)
11. [Commit Convention](#commit-convention)
12. [Pull Request Process](#pull-request-process)
13. [Code Style & Standards](#code-style--standards)
14. [Testing Philosophy](#testing-philosophy)
15. [Priority Contribution Areas](#priority-contribution-areas)
16. [Troubleshooting](#troubleshooting)
17. [Questions & Community](#questions--community)

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](docs/CODE_OF_CONDUCT.md).

We follow the [Contributor Covenant](https://www.contributor-covenant.org/). In short:
- Be welcoming and inclusive
- Respect differing viewpoints
- Accept constructive criticism gracefully
- Focus on what's best for the community
- Show empathy towards others

---

## Philosophy: Why We Build in the Open

Like Linux, TypeScript, and PSPDFKit, **Aden Hive is built by practitioners for practitioners**. We believe:

- **Quality over speed**: A well-tested feature beats a rushed release
- **Transparency over mystery**: Every decision is documented and reviewable
- **Community over ego**: The best idea wins, regardless of who suggests it
- **Performance matters**: Agents should be fast, efficient, and measurable
- **Cross-platform is non-negotiable**: If it doesn't work on Windows, macOS, and Linux, it's not done

Our goal is to deliver **developer success** through:
1. **Reliability** — Agents that work consistently across platforms
2. **Observability** — Clear insights into what agents are doing and why
3. **Extensibility** — Easy to add new tools, models, and capabilities
4. **Performance** — Fast execution with measurable metrics

---

## Issue Assignment Policy

To prevent duplicate work and respect contributors' time, we require issue assignment before submitting PRs.

### How to Claim an Issue

1. **Find an Issue:** Browse existing issues or create a new one
2. **Claim It:** Leave a comment (e.g., *"I'd like to work on this!"*)
3. **Wait for Assignment:** A maintainer will assign you within 24 hours. Issues with reproducible steps or proposals are prioritized.
4. **Submit Your PR:** Once assigned, you're ready to contribute

> **Note:** PRs for unassigned issues may be delayed or closed if someone else was already assigned.

### Exceptions (No Assignment Needed)

You may submit PRs without prior assignment for:
- **Documentation:** Fixing typos or clarifying instructions — add the `documentation` label or include `doc`/`docs` in your PR title to bypass the linked issue requirement
- **Micro-fixes:** Add the `micro-fix` label or include `micro-fix` in your PR title to bypass the linked issue requirement. Micro-fixes must meet **all** qualification criteria:

  | Qualifies | Disqualifies |
  |-----------|--------------|
  | < 20 lines changed | Any functional bug fix |
  | Typos & Documentation & Linting | Refactoring for "clean code" |
  | No logic/API/DB changes | New features (even tiny ones) |

---

## Getting Started

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/aden-hive/hive.git
cd hive

# Automated setup (installs uv, dependencies, and runs tests)
./quickstart.sh

# Or manual setup
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync
```

### Fork and Branch Workflow

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/hive.git`
3. Add the upstream repository: `git remote add upstream https://github.com/aden-hive/hive.git`
4. Sync with upstream to ensure you're starting from the latest code:
   ```bash
   git fetch upstream
   git checkout main
   git merge upstream/main
   ```
5. Create a feature branch: `git checkout -b feature/your-feature-name`
6. Make your changes
7. Run checks and tests:
   ```bash
   make check    # Lint and format checks
   make test     # Core tests
   ```
   On Windows (no make), run directly:
   ```powershell
   uv run ruff check core/ tools/
   uv run ruff format --check core/ tools/
   uv run pytest core/tests/
   ```
8. Commit your changes following our commit conventions
9. Push to your fork and submit a Pull Request

### Verify Installation

```bash
# Run core tests
uv run pytest core/tests/

# Run tool tests (mocked, no real API calls)
uv run pytest tools/tests/

# Run linter
uv run ruff check .

# Run formatter
uv run ruff format .
```

---

## OS Support: Write Once, Run Everywhere

Aden Hive runs on **macOS, Windows, and Linux** with platform-specific optimizations.

### Current OS Support Matrix

| Feature | macOS | Windows | Linux | Notes |
|---------|-------|---------|-------|-------|
| Core Framework | ✅ | ✅ | ✅ | Fully tested |
| CLI Runner | ✅ | ✅ | ✅ | Platform-aware terminal handling |
| File Operations | ✅ | ✅ | ✅ | Atomic writes with ACL preservation (Windows) |
| Browser Automation | ✅ | ✅ | ✅ | Playwright-based |
| Process Spawning | ✅ | ✅ | ✅ | subprocess + asyncio |
| Credential Storage | ✅ | ✅ | ✅ | `~/.hive/credentials` |
| Web Dashboard | ✅ | ✅ | ✅ | React + FastAPI |

### Platform-Specific Code

**Windows Support** (`core/framework/credentials/_win32_atomic.py`)
- Uses `ReplaceFileW` API for atomic file replacement
- Preserves NTFS DACL (Discretionary Access Control Lists)
- Handles FAT32 vs NTFS volume detection

**macOS Support**
- Uses `open` command for browser launching
- Native terminal support with ANSI colors

**Linux Support**
- Uses `xdg-open` for browser launching
- Full systemd integration for daemon mode (future)

### Cross-Platform Best Practices

Use `pathlib.Path` for all file operations:

```python
from pathlib import Path

# ✅ Good: Cross-platform
config_path = Path.home() / ".hive" / "config.json"

# ❌ Bad: Unix-only
config_path = "~/.hive/config.json"
```

Use platform checks when needed:

```python
import sys
if sys.platform == "win32":
    # Windows-specific code
elif sys.platform == "darwin":
    # macOS-specific code
else:  # linux
    # Linux-specific code
```

### Priority Areas for OS Contributions

- [ ] **Windows WSL2 optimization** — Better detection and native integration
- [ ] **Linux systemd service** — Daemon mode for long-running agents
- [ ] **macOS app bundle** — `.app` distribution with proper sandboxing
- [ ] **Windows installer** — `.msi` or `.exe` installer with PATH setup
- [ ] **Docker images** — Official multi-arch images (amd64, arm64)

---

## Development Setup & Tooling

### Prerequisites

- **Python 3.11+** (3.12 or 3.13 recommended)
- **Git** for version control
- **uv** for package management (installed automatically by quickstart)
- **Node.js 18+** (optional, for frontend development)

> **Windows Users:**
> Native Windows is supported. Use `.\quickstart.ps1` for setup and `.\hive.ps1` to run (PowerShell 5.1+). Disable "App Execution Aliases" in Windows settings to avoid Python path conflicts. WSL is also an option but not required.

> **Tip:** Installing Claude Code skills is optional for running existing agents, but required if you plan to **build new agents**.

### Package Management with `uv`

`uv` is a fast Python package installer and resolver (replaces pip + venv):

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install/sync dependencies
uv sync

# Add a new dependency
uv add <package>

# Run Python scripts
uv run python -m your_module

# Run pytest
uv run pytest
```

### Code Quality Tools

**ruff** — Fast Python linter and formatter (replaces black, isort, flake8)

```bash
# Format code
uv run ruff format .

# Check linting issues
uv run ruff check .

# Auto-fix linting issues
uv run ruff check . --fix
```

Configuration in `pyproject.toml`:
```toml
[tool.ruff]
line-length = 100
target-version = "py311"
```

### Makefile Targets

```bash
make lint          # Run ruff format + check
make check         # CI-safe checks (no modifications)
make test          # Run all tests
make test-tools    # Run tool tests only
make test-live     # Run live API integration tests (requires credentials)
```

### Recommended IDE Setup

**VS Code** (`.vscode/settings.json`)
```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.ruffEnabled": true,
  "python.formatting.provider": "none",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll": true,
      "source.organizeImports": true
    }
  }
}
```

**PyCharm**
- Enable ruff plugin
- Set Python interpreter to `.venv/bin/python`
- Enable pytest as test runner

---

## Tooling & Skills Required

### Required Skills by Contribution Type

**Core Framework Development**
- **Python 3.11+** with asyncio, type hints, and Pydantic
- **Graph theory** basics (nodes, edges, DAG traversal)
- **LLM fundamentals** (prompting, context windows, streaming)
- **Testing** with pytest, mocking, and async tests

**Tool Development** (99+ tools available)
- **API integration** (REST, GraphQL, WebSocket)
- **OAuth flows** (OAuth2, PKCE, refresh tokens)
- **MCP (Model Context Protocol)** for tool registration
- **Error handling** and retry logic

**Frontend Development** (Optional)
- **React 18+** with TypeScript
- **WebSocket** for real-time updates
- **Tailwind CSS** for styling

### Useful Development Commands

```bash
# Run tests with coverage
uv run pytest --cov=core --cov-report=html

# Run tests in parallel
uv run pytest -n auto

# Run only fast tests (skip live API tests)
uv run pytest -m "not live"

# Run linter with auto-fix
uv run ruff check . --fix

# Format code
uv run ruff format .

# Type checking (if using mypy)
uv run mypy core/

# Run a specific agent
uv run python -m exports.ai_outreach_architect
```

### Skills by Contribution Level

**Beginner-Friendly**
- Writing sample prompts (see `/examples/recipes/`)
- Fixing documentation typos
- Adding tool integrations (use existing tools as templates)
- Writing unit tests for existing code

**Intermediate**
- Building custom agents
- Adding new LLM provider support
- Improving error messages
- Adding new node types

**Advanced**
- Optimizing graph execution performance
- Building new judge evaluation methods
- Implementing cross-agent memory sharing
- Adding distributed execution support

---

## LLM Models & Providers

Aden Hive supports **100+ LLM providers** via LiteLLM, giving users maximum flexibility.

### Supported Providers

| Provider | Models | Notes |
|----------|--------|-------|
| **Anthropic** | Claude 3.5 Sonnet, Haiku, Opus | Default provider, best for reasoning |
| **OpenAI** | GPT-4, GPT-4 Turbo, GPT-4o | Function calling, vision |
| **OpenRouter** | Any OpenRouter catalog model | Uses `OPENROUTER_API_KEY` and `https://openrouter.ai/api/v1` |
| **Hive LLM** | `queen`, `kimi-2.5`, `GLM-5` | Uses `HIVE_API_KEY` and the Hive-managed endpoint |
| **Google** | Gemini 1.5 Pro, Flash | Long context windows |
| **DeepSeek** | DeepSeek V3 | Cost-effective, strong reasoning |
| **Mistral** | Mistral Large, Medium, Small | Open weights, EU hosting |
| **Groq** | Llama 3, Mixtral | Ultra-fast inference |
| **Ollama** | Any local model | Privacy-first, no API costs |
| **Azure OpenAI** | GPT-4, GPT-3.5 | Enterprise SSO, compliance |
| **Cohere** | Command, Command Light | Strong embeddings |
| **Together AI** | Open-source models | Flexible hosting |
| **Bedrock** | AWS-hosted models | Enterprise integration |

### Default Configuration

```python
# core/framework/llm/provider.py
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
```

### Model Selection Guidelines

**For Production Agents**
- **Reliability**: Claude 3.5 Sonnet (best reasoning)
- **Speed**: Claude Haiku or GPT-4o-mini (fast responses)
- **Cost**: DeepSeek or Gemini Flash (budget-conscious)
- **Privacy**: Ollama with local models (no data leaves server)

**Provider-Specific Notes**
- **OpenRouter**: store `provider` as `openrouter`, use the raw OpenRouter model ID in `model` (for example `x-ai/grok-4.20-beta`), and use `OPENROUTER_API_KEY`
- **Hive LLM**: store `provider` as `hive`, use Hive model names such as `queen`, `kimi-2.5`, or `GLM-5`, and use `HIVE_API_KEY`

**For Development**
- Use cheaper/faster models (Haiku, GPT-4o-mini)
- Test with multiple providers to catch provider-specific issues
- Mock LLM calls in unit tests

### How to Add a New LLM Provider

1. **Check if LiteLLM supports it** (most providers already work out of the box)
2. **Add credential handling** in `core/framework/credentials/`
3. **Add provider-specific configuration** in `core/framework/llm/`
4. **Write tests** in `core/tests/test_llm_provider.py`
5. **Update documentation** in `README.md`, `docs/configuration.md`, and any setup guides that mention provider configuration

**Example: Testing LLM Integration**

```python
# core/tests/test_llm_provider.py
import pytest
from framework.llm.anthropic import AnthropicProvider

@pytest.mark.asyncio
async def test_anthropic_provider_basic():
    provider = AnthropicProvider(api_key="test_key", model="claude-3-5-sonnet-20241022")
    response = await provider.generate([{"role": "user", "content": "Hello"}])
    assert response.content
    assert response.model == "claude-3-5-sonnet-20241022"

@pytest.mark.live
@pytest.mark.asyncio
async def test_anthropic_provider_real(anthropic_api_key):
    """Live test with real API (requires credentials)"""
    provider = AnthropicProvider(api_key=anthropic_api_key)
    response = await provider.generate([{"role": "user", "content": "What is 2+2?"}])
    assert "4" in response.content
```

### Priority Areas for LLM Contributions

- [ ] **Cost tracking per agent** — Track spend by agent/workflow
- [ ] **Model degradation policies** — Auto-fallback to cheaper models
- [ ] **Context window optimization** — Smart truncation strategies
- [ ] **Streaming improvements** — Better UX for long-running tasks
- [ ] **Vision model support** — Standardized image input handling
- [ ] **Local model fine-tuning** — Tools for fine-tuning Llama/Mistral models
- [ ] **Provider benchmarks** — Speed, quality, cost comparison dashboard

---

## Sample Prompts & Agent Examples

We provide **100+ sample prompts** covering real-world use cases.

### Where to Find Sample Prompts

**1. Recipe Prompts** (`/examples/recipes/sample_prompts_for_use_cases.md`)
- 100 production-ready agent prompts
- Categories: Marketing, Sales, Operations, Engineering, Finance
- Copy-paste ready for quick experimentation

**2. Template Agents** (`/examples/templates/`)
- Competitive Intelligence Agent
- Deep Research Agent
- Tech News Reporter
- Vulnerability Assessment
- Email Inbox Management
- Job Hunter

**3. Exported Agents** (`/exports/`)
- 17+ production agents built by the community
- AI Outreach Architect
- Financial AI Auditor
- Gmail Star Drafter
- GitHub Reply Agent

### Agent Prompt Structure

Every agent prompt should include:

1. **Role definition** — "You are a [role]..."
2. **Goal statement** — "Your job is to..."
3. **Step-by-step process** — Clear, numbered instructions
4. **Output format** — JSON schema or structured format
5. **Edge cases** — How to handle failures, missing data, etc.

**Example: High-Quality Agent Prompt**

```markdown
You are an elite Competitive Intelligence Analyst.

Your job is to monitor competitor websites, extract pricing and feature updates,
and produce a weekly intelligence report.

**STEP 1 — Discovery**
1. Use web_search to find the competitor's pricing page, changelog, and blog
2. Try queries like: "{competitor_name} pricing 2025"
3. If no results, navigate directly to their known domain

**STEP 2 — Extraction**
1. Use web_scrape on each relevant URL
2. Extract: pricing tiers, feature changes, announcement dates
3. Format as JSON: {competitor, category, update, source, date}

**STEP 3 — Analysis**
1. Compare current data with last week's snapshot (load_data)
2. Flag significant changes (>10% price change, new features)
3. Save current snapshot (save_data)

**STEP 4 — Reporting**
1. Generate HTML report with key highlights
2. Include comparison table and trend analysis
3. Call serve_file_to_user to deliver the report

**Important:**
- Be factual — only report what you actually see
- Skip URLs that fail to load
- Prioritize recent content (last 7 days)
```

### How to Contribute Sample Prompts

1. **Test your prompt** with a real agent first
2. **Document the use case** clearly
3. **Include expected tools** needed (web_search, save_data, etc.)
4. **Add to the appropriate category** in `/examples/recipes/sample_prompts_for_use_cases.md`
5. **Submit a PR** with title: `docs: add sample prompt for [use case]`

### Prompt Quality Checklist

- [ ] Role is clearly defined
- [ ] Steps are numbered and actionable
- [ ] Output format is specified (JSON schema preferred)
- [ ] Edge cases are handled (failures, missing data, rate limits)
- [ ] Tools are explicitly mentioned
- [ ] Tested with at least one real execution

### Priority Areas for Prompt Contributions

- [ ] **Industry-specific agents** — Healthcare, Legal, Finance, Education
- [ ] **Multilingual prompts** — Non-English agent templates
- [ ] **Error recovery patterns** — How agents should handle failures
- [ ] **Human-in-the-loop prompts** — When to ask for approval
- [ ] **Multi-agent coordination** — How agents delegate to sub-agents

---

## Performance Metrics & Benchmarking

**Performance is a feature.** Slow agents frustrate users. We measure everything.

### Key Performance Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Agent Latency** | <30s for simple tasks | `RuntimeLogger.log_execution_time()` |
| **LLM Token Usage** | <10K tokens/task | `LiteLLM.track_cost()` |
| **Tool Call Success Rate** | >95% | `ToolExecutor.success_rate()` |
| **Judge Accuracy** | >90% agreement with human | Manual evaluation |
| **Memory Usage** | <500MB per agent | `psutil.Process().memory_info()` |
| **Concurrent Agents** | 10+ agents on 4-core CPU | Load testing |

### Current Monitoring Tools

**Runtime Performance**
```python
# core/framework/runtime/runtime_logger.py
class RuntimeLogger:
    def log_node_execution(self, node_id: str, duration: float, tokens: int):
        # Tracks per-node performance
        pass

    def log_tool_call(self, tool_name: str, duration: float, success: bool):
        # Tracks tool latency and reliability
        pass
```

**LLM Cost Tracking**
```python
# LiteLLM automatically tracks cost per request
from litellm import completion_cost
cost = completion_cost(model="claude-3-5-sonnet-20241022", messages=[...])
```

**Monitoring Dashboard** (`/core/framework/monitoring/`)
- WebSocket-based real-time monitoring
- Displays: active agents, tool calls, token usage, errors
- Access at: `http://localhost:8000/monitor`

### How to Add Performance Metrics

**1. Instrument your code**
```python
import time
from framework.runtime.runtime_logger import RuntimeLogger

logger = RuntimeLogger()

start = time.time()
result = await expensive_operation()
duration = time.time() - start

logger.log_execution_time("expensive_operation", duration)
```

**2. Add tests with performance assertions**
```python
@pytest.mark.asyncio
async def test_agent_performance():
    start = time.time()
    result = await run_agent(...)
    duration = time.time() - start

    assert duration < 30.0, f"Agent took {duration}s (expected <30s)"
    assert result.total_tokens < 10000, f"Used {result.total_tokens} tokens (expected <10K)"
```

**3. Create benchmark scripts** (`/benchmarks/`)
```python
# benchmarks/bench_agent_latency.py
import asyncio
import statistics
from exports.my_agent import MyAgent

async def benchmark_agent(iterations: int = 100):
    durations = []
    for i in range(iterations):
        start = time.time()
        await MyAgent().run("test input")
        durations.append(time.time() - start)

    print(f"Mean: {statistics.mean(durations):.2f}s")
    print(f"P50: {statistics.median(durations):.2f}s")
    print(f"P99: {statistics.quantiles(durations, n=100)[98]:.2f}s")

asyncio.run(benchmark_agent())
```

### Performance Optimization Tips

**1. Reduce LLM Calls**
- Cache repetitive responses
- Use cheaper models for simple tasks (Haiku vs Sonnet)
- Batch multiple questions into one prompt

**2. Optimize Tool Calls**
- Run independent tool calls in parallel (`asyncio.gather`)
- Cache API responses when appropriate
- Use webhooks instead of polling

**3. Memory Management**
- Use streaming for large files (don't load entire file into memory)
- Clear conversation history periodically
- Use database for large datasets (not in-memory)

**4. Graph Execution**
- Minimize sequential dependencies (more parallelism)
- Use conditional edges to skip unnecessary nodes
- Set appropriate timeouts

### Priority Areas for Performance Contributions

- [ ] **Comprehensive benchmark suite** — Standard tasks across providers
- [ ] **Real-time performance dashboard** — Live monitoring during execution
- [ ] **Cost tracking per agent/workflow** — Budget management
- [ ] **Provider comparison dashboard** — Speed, quality, cost metrics
- [ ] **Automatic performance regression detection** — CI integration

---

## Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks
- `perf`: Performance improvements

**Examples:**
```
feat(auth): add OAuth2 login support
fix(api): handle null response from external service
docs(readme): update installation instructions
test(graph): add integration tests for graph executor
perf(llm): reduce token usage by 30% with prompt caching
```

---

## Pull Request Process

1. **Get assigned to the issue first** (see [Issue Assignment Policy](#issue-assignment-policy))
2. Update documentation if needed
3. Add tests for new functionality
4. Ensure `make check` and `make test` pass
5. Request review from maintainers

### PR Title Format

Follow the same convention as commits:
```
feat(component): add new feature description
```

### PR Template

```markdown
## Description
Brief description of what this PR does.

## Motivation
Why is this change needed?

## Changes
- Added X
- Fixed Y
- Updated Z

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Tested on macOS
- [ ] Tested on Windows
- [ ] Tested on Linux

## Checklist
- [ ] Code follows style guidelines (ruff)
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No breaking changes (or documented if unavoidable)

Closes #123
```

---

## Code Style & Standards

### Project Structure

- `core/` - Core framework (agent runtime, graph executor, protocols)
- `tools/` - MCP Tools Package (tools for agent capabilities)
- `exports/` - Agent packages and examples
- `docs/` - Documentation
- `scripts/` - Build and utility scripts
- `.claude/` - Claude Code skills for building/testing agents

### Python Style Guidelines

- Use Python 3.11+ for all new code
- Follow PEP 8 style guide
- Add type hints to function signatures
- Write docstrings for classes and public functions
- Use meaningful variable and function names
- Keep functions focused and small
- **Line length**: 100 characters
- **Formatting**: Use `ruff format` (no manual formatting)
- **Linting**: Use `ruff check` (no warnings tolerated)

For linting and formatting (Ruff, pre-commit hooks), see [Linting & Formatting Setup](docs/contributing-lint-setup.md).

### Example: Good Code

```python
from typing import Optional
from pydantic import BaseModel

class AgentConfig(BaseModel):
    """Configuration for agent execution.

    Attributes:
        model: LLM model name (e.g., "claude-3-5-sonnet-20241022")
        max_tokens: Maximum tokens for completion (default: 4096)
        temperature: Sampling temperature 0.0-1.0 (default: 0.7)
    """
    model: str
    max_tokens: int = 4096
    temperature: float = 0.7

async def run_agent(config: AgentConfig, timeout: Optional[float] = None) -> dict:
    """Run an agent with the given configuration.

    Args:
        config: Agent configuration
        timeout: Optional timeout in seconds (default: no timeout)

    Returns:
        Dictionary containing agent results and metadata

    Raises:
        TimeoutError: If execution exceeds timeout
        ValueError: If config is invalid
    """
    # Implementation
    pass
```

### Architecture Principles

1. **Separation of concerns** — One class, one responsibility
2. **Dependency injection** — Pass dependencies explicitly (no global state)
3. **Async by default** — Use `async/await` for I/O operations
4. **Error handling** — Catch specific exceptions, log errors, fail gracefully
5. **Immutability** — Prefer immutable data structures (Pydantic models)

### Code Review Checklist

**For Authors**
- [ ] Self-review your diff before submitting
- [ ] All tests pass locally
- [ ] No commented-out code or debug prints
- [ ] No breaking changes (or documented if unavoidable)
- [ ] Documentation updated
- [ ] Conventional commit format used

**For Reviewers**
- [ ] Does the code solve the stated problem?
- [ ] Is the code readable and maintainable?
- [ ] Are there tests covering the new code?
- [ ] Are edge cases handled?
- [ ] Is performance acceptable?
- [ ] Does it follow existing patterns in the codebase?

---

## Testing Philosophy

> **"If it's not tested, it's broken."** — Linus Torvalds

### Test Pyramid

```
       /\
      /  \     End-to-End Tests (5%)
     /----\    Integration Tests (15%)
    /      \   Unit Tests (80%)
   /________\
```

### Types of Tests

**Unit Tests** (80% of tests)
- Test individual functions/classes in isolation
- Fast (<1ms per test)
- No external dependencies (mock everything)
- Live in `/core/tests/` and `/tools/tests/`

**Integration Tests** (15% of tests)
- Test multiple components together
- Moderate speed (<1s per test)
- May use test databases or mock APIs
- Live in `/core/tests/integration/`

**Live Tests** (5% of tests)
- Test against real external APIs
- Slow (>1s per test)
- Require credentials
- Marked with `@pytest.mark.live` (skipped by default)

### Running Tests

> **Note:** When testing agents in `exports/`, always set PYTHONPATH:
>
> ```bash
> PYTHONPATH=exports uv run python -m agent_name test
> ```

```bash
# Run lint and format checks (mirrors CI lint job)
make check

# Run core framework tests (mirrors CI test job)
make test

# Or run tests directly
cd core && pytest tests/ -v

# Run tools package tests (when contributing to tools/)
cd tools && uv run pytest tests/ -v

# Run tests for a specific agent
PYTHONPATH=exports uv run python -m agent_name test

# Run specific test file
uv run pytest core/tests/test_graph_executor.py

# Run specific test function
uv run pytest core/tests/test_graph_executor.py::test_simple_execution

# Run with coverage
uv run pytest --cov=core --cov-report=html

# Run in parallel
uv run pytest -n auto

# Run live tests (requires credentials)
uv run pytest -m live

# Run only fast tests
uv run pytest -m "not live"
```

> **CI also validates** that all exported agent JSON files (`exports/*/agent.json`) are well-formed JSON. Ensure your agent exports are valid before submitting.

### Test Coverage Goals

- **Core framework**: >90% coverage
- **Tools**: >80% coverage (some tools are hard to mock)
- **Critical paths**: 100% coverage (graph execution, credential handling, LLM calls)

### Example: Writing Tests

**Unit Test**
```python
import pytest
from framework.graph.node import Node

def test_node_creation():
    node = Node(id="test", name="Test Node", node_type="event_loop")
    assert node.id == "test"
    assert node.name == "Test Node"
    assert node.node_type == "event_loop"

@pytest.mark.asyncio
async def test_node_execution():
    node = Node(id="test", name="Test Node", node_type="event_loop")
    result = await node.execute({"input": "test"})
    assert result["status"] == "success"
```

**Integration Test**
```python
import pytest
from framework.graph.executor import GraphExecutor
from framework.graph.node import Node

@pytest.mark.asyncio
async def test_graph_execution_with_multiple_nodes():
    nodes = [
        Node(id="node1", ...),
        Node(id="node2", ...),
    ]
    edges = [...]

    executor = GraphExecutor(nodes, edges)
    result = await executor.run({"input": "test"})

    assert result["status"] == "success"
    assert "node1" in result["executed_nodes"]
    assert "node2" in result["executed_nodes"]
```

**Live Test**
```python
import pytest
import os

@pytest.mark.live
@pytest.mark.asyncio
async def test_anthropic_real_api():
    """Test against real Anthropic API (requires ANTHROPIC_API_KEY)"""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    provider = AnthropicProvider(api_key=api_key)
    response = await provider.generate([{"role": "user", "content": "What is 2+2?"}])

    assert "4" in response.content
```

---

## Priority Contribution Areas

### High-Priority Areas

**1. Cross-Platform Support**
- [ ] Windows installer (`.msi` or `.exe`)
- [ ] Linux systemd service for daemon mode
- [ ] macOS app bundle (`.app` distribution)
- [ ] Docker images (multi-arch: amd64, arm64)

**2. Performance & Monitoring**
- [ ] Comprehensive benchmark suite
- [ ] Real-time performance dashboard
- [ ] Cost tracking per agent/workflow
- [ ] Provider comparison dashboard

**3. Developer Experience**
- [ ] Interactive agent builder CLI
- [ ] Visual graph editor (web-based)
- [ ] Improved error messages with suggestions
- [ ] Auto-generated agent documentation

**4. Tool Ecosystem**
- [ ] More database connectors (ClickHouse, TimescaleDB)
- [ ] More communication tools (WhatsApp, SMS)
- [ ] Cloud platform integrations (GCP, Azure)
- [ ] Developer tools (Figma, Linear, Notion)

**5. LLM & AI**
- [ ] Fine-tuning pipeline for local models
- [ ] Context window optimization strategies
- [ ] Multi-modal support (vision, audio)
- [ ] Embedding-based memory search

**6. Testing & Quality**
- [ ] Increase test coverage to >90%
- [ ] Add property-based testing (Hypothesis)
- [ ] Add mutation testing
- [ ] Add fuzzing for security-critical code

**7. Documentation**
- [ ] Video tutorials for common workflows
- [ ] Interactive playground (try agents in browser)
- [ ] Architecture decision records (ADRs)
- [ ] Case studies from production users

### Beginner-Friendly Contributions

- [ ] Add sample prompts to `/examples/recipes/`
- [ ] Improve error messages with helpful hints
- [ ] Add docstrings to undocumented functions
- [ ] Write tutorial blog posts
- [ ] Fix typos in documentation
- [ ] Add more unit tests to increase coverage
- [ ] Create visual diagrams for architecture docs

### Intermediate Contributions

- [ ] Add new tool integrations
- [ ] Build example agents for specific industries
- [ ] Optimize slow graph execution paths
- [ ] Add new LLM provider support
- [ ] Improve CLI UX with better prompts/colors
- [ ] Add integration tests for critical workflows

### Advanced Contributions

- [ ] Design and implement distributed execution
- [ ] Build advanced judge evaluation methods
- [ ] Add cross-agent memory sharing
- [ ] Implement automatic graph optimization
- [ ] Add support for multi-agent coordination
- [ ] Build real-time collaboration features

---

## Troubleshooting

### `make: command not found`
Install `make` using:

```bash
sudo apt install make
```

### `uv: command not found`
Install `uv` using:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### `ruff: not found`
If linting fails due to a missing `ruff` command, install it with:

```bash
uv tool install ruff
```

### WSL Path Recommendation
When using WSL, it is recommended to clone the repository inside your Linux home directory (e.g., ~/hive) instead of under /mnt/c/... to avoid potential performance and permission issues.

### Test Failures
If tests fail locally but pass in CI:
1. Make sure you're using Python 3.11+
2. Run `uv sync` to ensure dependencies are up-to-date
3. Clear pytest cache: `rm -rf .pytest_cache`
4. Run tests in verbose mode: `pytest -vv`

---

## Questions & Community

### Where to Get Help

- **GitHub Issues** — Bug reports, feature requests
- **GitHub Discussions** — Questions, ideas, showcase
- **Discord** — Real-time chat ([join here](https://discord.com/invite/MXE49hrKDk))
- **Documentation** — `/docs/` and README files
- **Email** — team@adenhq.com (for security issues only)

### Communication Guidelines

1. **Be respectful** — We're all here to build something great
2. **Be patient** — Maintainers are volunteers with day jobs
3. **Be clear** — Provide context, examples, and reproduction steps
4. **Be constructive** — Suggest solutions, not just problems
5. **Be thankful** — Recognize contributions from others

### Recognition

We recognize contributors through:
- **Changelog mentions** — Every PR is credited in releases
- **Leaderboard** — Weekly recognition of top contributors
- **README credits** — Major contributors listed in README
- **Swag** — Stickers, t-shirts for significant contributions

---

## Contributor License Agreement

By submitting a Pull Request, you agree that your contributions will be licensed under the Aden Agent Framework license (Apache 2.0).

---

## Final Thoughts

Building open-source software is a marathon, not a sprint. **Quality beats quantity.** We'd rather merge 10 well-tested, thoughtfully-designed features than 100 rushed, buggy ones.

As Peter Steinberger (PSPDFKit) says: *"The best code is code that doesn't exist."* Before adding a feature, ask:
- Is this really needed?
- Can we solve this with existing tools?
- Will users actually use this?
- Can we make it simpler?

As Linus Torvalds (Linux) says: *"Talk is cheap. Show me the code."* We value:
- Working code over lengthy discussions
- Tests over promises
- Documentation over assumptions
- Benchmarks over claims

As Anders Hejlsberg (TypeScript) says: *"Make it work, make it right, make it fast."* In that order:
- First, get it working (pass tests)
- Then, get it right (clean code, good design)
- Finally, get it fast (optimize hot paths only)

---

**Thank you for contributing to Aden Hive.** Together, we're building the most reliable, performant, and developer-friendly AI agent framework in the world.

Now go build something amazing. 🚀
