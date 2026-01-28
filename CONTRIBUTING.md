# Contributing to Aden Agent Framework

Thank you for your interest in contributing to the Aden Agent Framework! This document provides guidelines and information for contributors.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Contributor License Agreement

By submitting a Pull Request, you agree that your contributions will be licensed under the Aden Agent Framework license.

## Issue Assignment Policy

To prevent duplicate work and respect contributors' time, we require issue assignment before submitting PRs.

### How to Claim an Issue

1. **Find an Issue:** Browse existing issues or create a new one
2. **Claim It:** Leave a comment (e.g., *"I'd like to work on this!"*)
3. **Wait for Assignment:** A maintainer will assign you within 24 hours
4. **Submit Your PR:** Once assigned, you're ready to contribute

> **Note:** PRs for unassigned issues may be delayed or closed if someone else was already assigned.

### The 5-Day Momentum Rule

To keep the project moving, issues with **no activity for 5 days** (no PR or status update) will be unassigned. If you need more time, just drop a quick comment!

### Exceptions (No Assignment Needed)

You may submit PRs without prior assignment for:
- **Documentation:** Fixing typos or clarifying instructions — add the `documentation` label or include `doc`/`docs` in your PR title to bypass the linked issue requirement
- **Micro-fixes:** Minor tweaks or obvious linting errors — add the `micro-fix` label or include `micro-fix` in your PR title to bypass the linked issue requirement
- **Small Refactors:** Tiny improvements that don't change core logic

If a high-quality PR is submitted for a "stale" assigned issue (no activity for 7+ days), we may proceed with the submitted code.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/hive.git`
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Run tests: `PYTHONPATH=core:exports python -m pytest`
6. Commit your changes following our commit conventions
7. Push to your fork and submit a Pull Request

## Development Setup

```bash
# Install Python packages
./scripts/setup-python.sh

# Verify installation
python -c "import framework; import aden_tools; print('✓ Setup complete')"

# Install Claude Code skills (optional)
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
4. Ensure all tests pass
5. Update the CHANGELOG.md if applicable
6. Request review from maintainers

### PR Title Format

Follow the same convention as commits:
```
feat(component): add new feature description
```

## Project Structure

- `core/` - Core framework (agent runtime, graph executor, protocols)
- `tools/` - MCP Tools Package (19 tools for agent capabilities)
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

## Testing

> **Note:** When testing agents in `exports/`, always set PYTHONPATH:
>
> ```bash
> PYTHONPATH=core:exports python -m agent_name test
> ```

```bash
# Run all tests for the framework
cd core && python -m pytest

# Run all tests for tools
cd tools && python -m pytest

# Run tests for a specific agent
PYTHONPATH=core:exports python -m agent_name test
```

## Questions?

Feel free to open an issue for questions or join our [Discord community](https://discord.com/invite/MXE49hrKDk).

Thank you for contributing!