# Contributing to Aden Hive - Getting Started

Welcome! This guide helps new contributors get started with the Aden Hive Framework project.

## Quick Start for Contributors

### 1. Fork & Clone

```bash
# Fork the repository on GitHub
# Then clone your fork
git clone https://github.com/YOUR_USERNAME/hive.git
cd hive
```

### 2. Setup Development Environment

```bash
# Unix/macOS/Linux
./dev-help.sh setup

# Or Windows
dev-help.bat setup
```

This will:
- Install Python packages
- Setup MCP server
- Verify installation

### 3. Run Tests

```bash
# Unix/macOS/Linux
./dev-help.sh test

# Or Windows
dev-help.bat test
```

All tests should pass ✓

---

## Understanding the Project Structure

```
hive/
├── core/               # Framework code
│   ├── framework/      # Core runtime
│   ├── setup_mcp.py    # MCP setup
│   └── tests/          # Framework tests
│
├── tools/              # MCP tools (19 available)
│   └── src/aden_tools/
│
├── exports/            # User-created agents (not in repo)
│
├── .claude/            # Claude Code skills
│   └── skills/         # Agent building skills
│
├── docs/               # Documentation
│   ├── api.md         # API reference
│   ├── getting-started.md
│   ├── quick-reference.md
│   └── troubleshooting.md
│
└── dev-help.sh/bat     # Development helper scripts
```

---

## Finding Good First Issues

### Start With

1. **Documentation Issues**
   - Typos and grammar fixes
   - Clarifying instructions
   - Adding examples
   - Updating outdated info

2. **Small Improvements**
   - Better error messages
   - Code comments
   - Small refactors
   - Test coverage

3. **Feature Requests**
   - Check GitHub issues for labels:
     - `good first issue`
     - `help wanted`
     - `documentation`

### How to Find Issues

```bash
# List issues with label
# Good starting points:
# - https://github.com/adenhq/hive/labels/good%20first%20issue
# - https://github.com/adenhq/hive/labels/documentation
```

---

## The Contribution Process

### Step 1: Claim the Issue

1. Find an issue you want to work on
2. Leave a comment: *"I'd like to work on this"*
3. Wait for a maintainer to assign you (within 24 hours)
4. You're ready to start!

**Note**: Some issues don't need assignment:
- Documentation fixes (typos, clarity)
- Small refactors
- Code comments
- Micro-improvements

### Step 2: Create a Feature Branch

```bash
# Create a branch with a descriptive name
git checkout -b feature/description-of-change
# or
git checkout -b docs/fix-typo-in-readme
# or
git checkout -b fix/issue-123-agent-runner-crash
```

### Step 3: Make Your Changes

Follow the conventions:

**For Code Changes**:
```python
# Add docstrings
def my_function():
    """
    What this function does.
    
    Parameters:
    - param1: description
    
    Returns:
    - return value description
    """
    pass

# Add type hints
def validate(data: Dict[str, Any]) -> bool:
    pass
```

**For Documentation**:
```markdown
# Use clear headings
## Subheading
- Use bullet points
- For lists

### Code examples
\`\`\`python
# Include language identifier
print("example")
\`\`\`
```

### Step 4: Test Your Changes

```bash
# Run tests
./dev-help.sh test

# Run specific test
PYTHONPATH=core:exports python -m pytest core/tests/test_file.py -v

# Check code style
./dev-help.sh lint

# Format code
./dev-help.sh format
```

### Step 5: Commit with Clear Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```bash
# Feature
git commit -m "feat(component): add new functionality"

# Bug fix
git commit -m "fix(component): resolve issue with x"

# Documentation
git commit -m "docs(readme): clarify installation steps"

# Tests
git commit -m "test(executor): add tests for edge cases"

# Code style
git commit -m "style(formatting): apply black formatting"

# Refactor
git commit -m "refactor(runner): simplify agent loading logic"
```

**Examples**:
```
feat(mcp): add provider-agnostic test generation
fix(runtime): handle async context correctly
docs(api): document new memory API methods
test(graph): improve node execution tests
refactor(llm): simplify provider initialization
```

### Step 6: Push and Create Pull Request

```bash
# Push your branch
git push origin feature/description-of-change

# Go to GitHub and create a pull request
# Use the PR template to describe:
# - What changes you made
# - Why you made them
# - How to test the changes
```

### Step 7: Respond to Feedback

- Reviewers might request changes
- Update your branch and push again
- Your PR will be automatically updated

### Step 8: Merge!

Once approved, a maintainer will merge your PR. Congratulations! 🎉

---

## Contribution Types

### 📝 Documentation

**Easy to contribute**:
- Fix typos
- Clarify confusing sections
- Add examples
- Improve formatting
- Link to resources
- Update outdated info

**How to help**:
```markdown
## Better examples section

Instead of:
"Use the API to create agents"

Write:
"Use the AgentRunner API:
\`\`\`python
runner = AgentRunner("exports/my_agent")
result = await runner.run({"input": "data"})
\`\`\`"
```

### 💻 Code

**Types of contributions**:
- Bug fixes
- Performance improvements
- New features
- Code refactoring
- Better error messages
- Improved comments

**Example**:
```python
# Before: Poor error message
if not path:
    raise Exception("Invalid")

# After: Clear error message
if not path:
    raise ValueError(
        "Agent path required (e.g., 'exports/my_agent')"
    )
```

### 🧪 Tests

**Add tests for**:
- New features
- Bug fixes
- Edge cases
- Error handling
- Async operations

**Example**:
```python
@pytest.mark.asyncio
async def test_agent_run_with_invalid_input():
    """Test that agent handles invalid input gracefully."""
    runner = AgentRunner("exports/test_agent")
    result = await runner.run({})  # Empty input
    assert not result.success
    assert "invalid" in result.error.lower()
```

---

## Helpful Commands

```bash
# Setup
./dev-help.sh setup          # Complete setup

# Testing
./dev-help.sh test           # All tests
./dev-help.sh test:core      # Framework tests
./dev-help.sh test:coverage  # With coverage report

# Code quality
./dev-help.sh lint           # Check style
./dev-help.sh format         # Format code
./dev-help.sh clean          # Clean artifacts

# Development
./dev-help.sh validate       # Check agents
./dev-help.sh validate:agent my_agent
./dev-help.sh run:agent my_agent

# MCP
./dev-help.sh mcp:setup      # Setup MCP server
./dev-help.sh mcp:test       # Test MCP server
```

---

## Common Issues

### Issue: Tests fail with ModuleNotFoundError

**Solution**:
```bash
# Reinstall packages
cd core && pip install -e .
cd ../tools && pip install -e .
```

### Issue: Changes not reflected in tests

**Solution**:
```bash
# Clear cache and reinstall
./dev-help.sh clean
./dev-help.sh install
./dev-help.sh test
```

### Issue: Can't find agent in exports/

**Solution**:
```bash
# Create agents directory
mkdir -p exports
# Verify agent structure
PYTHONPATH=core:exports python -m my_agent validate
```

### Issue: Import errors

**Solution**:
```bash
# Set PYTHONPATH
export PYTHONPATH=core:exports:$PYTHONPATH
# Or on Windows
set PYTHONPATH=core;exports;%PYTHONPATH%
```

---

## Code Review Tips

### What Reviewers Look For

1. **Clarity**: Is the code easy to understand?
2. **Testing**: Are there adequate tests?
3. **Documentation**: Is it well-documented?
4. **Style**: Does it follow project conventions?
5. **Efficiency**: Is it performant?
6. **Safety**: Does it handle errors properly?

### How to Make Reviews Easier

✅ **Do**:
- Write clear commit messages
- Add docstrings and comments
- Include tests
- Keep changes focused
- Link to related issues

❌ **Don't**:
- Make giant changes
- Change code style unrelated to feature
- Remove functionality without discussion
- Skip tests or documentation

---

## Questions?

1. **Check Documentation**:
   - [Getting Started](docs/getting-started.md)
   - [API Reference](docs/api.md)
   - [Troubleshooting](docs/troubleshooting.md)
   - [Quick Reference](docs/quick-reference.md)

2. **GitHub Issues**:
   - Search existing issues
   - Ask questions in discussions

3. **Discord**:
   - Join the community
   - Ask for help
   - Discuss ideas

4. **CONTRIBUTING.md**:
   - Review full guidelines
   - Check commit conventions
   - Understand PR process

---

## Recognition

Contributors are valued and recognized:
- Added to CONTRIBUTORS file
- Mentioned in CHANGELOG
- Recognition in releases

---

## Your First Contribution Checklist

- [ ] Forked and cloned the repo
- [ ] Ran setup successfully
- [ ] All tests pass
- [ ] Found an issue to work on
- [ ] Claimed the issue (if needed)
- [ ] Created a feature branch
- [ ] Made your changes
- [ ] Tests pass
- [ ] Code formatted
- [ ] Commit messages clear
- [ ] Created a pull request
- [ ] Responded to feedback
- [ ] PR merged! 🎉

---

## Next Steps After Your First PR

1. **Celebrate!** You're now a contributor 🎉
2. **Explore More**: Look for your next issue
3. **Help Others**: Review PRs from other contributors
4. **Share Feedback**: Tell us what could be better

---

## Resources

- **GitHub**: https://github.com/adenhq/hive
- **Docs**: https://docs.adenhq.com/
- **Discord**: https://discord.com/invite/MXE49hrKDk
- **Issues**: https://github.com/adenhq/hive/issues
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)

---

## Code of Conduct

- Be respectful
- Welcome feedback
- Focus on constructive criticism
- Respect others' time and effort

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for details.

---

**Happy Contributing! 🚀**

Welcome to the Aden Hive community!
