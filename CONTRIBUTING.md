# Contributing to Hive

Thank you for your interest in contributing to Hive! This document provides guidelines and information for contributors.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/hive.git`
3. Create a feature branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Run tests: `npm run test`
6. Commit your changes following our commit conventions
7. Push to your fork and submit a Pull Request

## Development Setup

```bash
# Install dependencies
npm install

# Copy configuration
cp config.yaml.example config.yaml

# Generate environment files
npm run setup

# Start development environment
docker compose up
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

- `honeycomb/` - React frontend application
- `hive/` - Node.js backend API
- `docs/` - Documentation
- `scripts/` - Build and utility scripts

## Code Style

- Use TypeScript for all new code
- Follow existing code patterns
- Use meaningful variable and function names
- Add comments for complex logic
- Keep functions focused and small

## Testing

```bash
# Run all tests
npm run test

# Run tests for a specific package
npm run test --workspace=honeycomb
npm run test --workspace=hive
```

## Questions?

Feel free to open an issue for questions or join our [Discord community](https://discord.com/invite/MXE49hrKDk).

Thank you for contributing!
