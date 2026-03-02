# Contributing to Aden Agent Framework

Thank you for your interest in contributing to the Aden Agent Framework! This document provides guidelines and information for contributors. We’re especially looking for help building tools, integrations ([check #2805](https://github.com/adenhq/hive/issues/2805)), and example agents for the framework. If you’re interested in extending its functionality, this is the perfect place to start. 

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](docs/CODE_OF_CONDUCT.md).

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

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/hive.git`
3. Add the upstream repository: `git remote add upstream https://github.com/adenhq/hive.git`
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
   make check    # Lint and format checks (ruff check + ruff format --check on core/ and tools/)
   make test     # Core tests (cd core && pytest tests/ -v)
   ```
8. Commit your changes following our commit conventions
9. Push to your fork and submit a Pull Request

## Development Setup

```bash
# Install Python packages and verify setup
./quickstart.sh
```

> **Windows Users:**  
> If you are on native Windows, it is recommended to use **WSL (Windows Subsystem for Linux)**.  
> Alternatively, make sure to run PowerShell or Git Bash with Python 3.11+ installed, and disable "App Execution Aliases" in Windows settings.

> **Tip:** Installing Claude Code skills is optional for running existing agents, but required if you plan to **build new agents**.

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

**Examples:**
```
feat(auth): add OAuth2 login support
fix(api): handle null response from external service
docs(readme): update installation instructions
```

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

## Project Structure

- `core/` - Core framework (agent runtime, graph executor, protocols)
- `tools/` - MCP Tools Package (tools for agent capabilities)
- `exports/` - Agent packages and examples
- `docs/` - Documentation
- `scripts/` - Build and utility scripts
- `.claude/` - Claude Code skills for building/testing agents

## Code Style

- Use Python 3.11+ for all new code
- Follow PEP 8 style guide
- Add type hints to function signatures
- Write docstrings for classes and public functions
- Use meaningful variable and function names
- Keep functions focused and small

For linting and formatting (Ruff, pre-commit hooks), see [Linting & Formatting Setup](docs/contributing-lint-setup.md).

## Testing

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
```

> **CI also validates** that all exported agent JSON files (`exports/*/agent.json`) are well-formed JSON. Ensure your agent exports are valid before submitting.

## Contributor License Agreement

By submitting a Pull Request, you agree that your contributions will be licensed under the Aden Agent Framework license.

## Questions?

Feel free to open an issue for questions or join our [Discord community](https://discord.com/invite/MXE49hrKDk).

Thank you for contributing!
