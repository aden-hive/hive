# Contributing to Aden Agent Framework

Thank you for your interest in contributing to the Aden Agent Framework! This document provides guidelines and information for contributors.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

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

1. Update documentation if needed
2. Add tests for new functionality
3. Ensure all tests pass
4. Update the CHANGELOG.md if applicable
5. Request review from maintainers

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
