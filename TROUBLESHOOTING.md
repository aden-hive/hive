# Troubleshooting Guide

Common issues and solutions when working with the Aden Agent Framework.

## Table of Contents

- [Installation Issues](#installation-issues)
- [Import Errors](#import-errors)
- [Agent Execution Problems](#agent-execution-problems)
- [LLM Provider Issues](#llm-provider-issues)
- [Test Failures](#test-failures)
- [Windows-Specific Issues](#windows-specific-issues)
- [Performance Issues](#performance-issues)
- [Common Error Messages](#common-error-messages)

---

## Installation Issues

### Problem: `pip install -e .` fails with permission errors

**Solution:**
```bash
# Use virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e .

# Or use user installation
pip install --user -e .
```

### Problem: Python version mismatch

**Error:** `Python 3.11+ required, but you have 3.10`

**Solution:**
```bash
# Check Python version
python --version

# Install Python 3.11 or 3.12
# Download from: https://www.python.org/downloads/

# On Ubuntu/Debian
sudo apt-get install python3.12

# Use specific version
python3.12 -m venv venv
```

### Problem: `./quickstart.sh` fails on Windows

**Solution:**
```bash
# Option 1: Use WSL (recommended)
wsl
cd /mnt/d/HIVE
./quickstart.sh

# Option 2: Use Git Bash
bash quickstart.sh

# Option 3: Manual setup
cd core && pip install -e .
cd ../tools && pip install -e .
```

---

## Import Errors

### Problem: `ModuleNotFoundError: No module named 'framework'`

**Solution:**
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH=core:exports  # On Windows: set PYTHONPATH=core;exports

# Verify installation
python -c "import framework; print('✓ framework OK')"

# Reinstall if needed
cd core && pip install -e .
```

### Problem: `ImportError: cannot import name 'LLMProvider'`

**Solution:**
```bash
# Reinstall with dependencies
cd core
pip install --upgrade -e .

# Check for conflicting packages
pip list | grep framework
```

### Problem: `No module named 'aden_tools'`

**Solution:**
```bash
# Install tools package
cd tools
pip install -e .

# Verify
python -c "import aden_tools; print('✓ aden_tools OK')"
```

---

## Agent Execution Problems

### Problem: `PYTHONPATH not set correctly`

**Error:** `ModuleNotFoundError` when running agent

**Solution:**
```bash
# Always set PYTHONPATH from project root
cd /path/to/hive
export PYTHONPATH=core:exports

# Add to .bashrc/.zshrc for persistence
echo 'export PYTHONPATH=/path/to/hive/core:/path/to/hive/exports' >> ~/.bashrc

# On Windows (PowerShell)
$env:PYTHONPATH="D:\HIVE\core;D:\HIVE\exports"
```

### Problem: Agent validation fails

**Error:** `Invalid node reference in edge`

**Solution:**
```bash
# Validate agent structure
PYTHONPATH=core:exports python -m agent_name validate

# Check agent.json:
# - All node IDs referenced in edges exist
# - Required fields are present (id, name, description, node_type)
# - Edge targets are valid node IDs
```

### Problem: Agent runs but produces no output

**Debugging steps:**
```bash
# 1. Check if agent is in mock mode
PYTHONPATH=core:exports python -m agent_name info

# 2. Enable verbose logging
import logging
logging.basicConfig(level=logging.DEBUG)

# 3. Check node execution
# Look for "Executing node: <node_id>" in logs

# 4. Verify input format matches expected schema
```

---

## LLM Provider Issues

### Problem: `API key not found`

**Error:** `ANTHROPIC_API_KEY not set`

**Solution:**
```bash
# Set API key
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"

# Or use .env file (in project root)
echo "ANTHROPIC_API_KEY=your-key" > .env

# Or test without API keys
PYTHONPATH=core:exports python -m agent_name run --input '{}' --mock
```

### Problem: Rate limit errors

**Error:** `429 Too Many Requests`

**Solution:**
```bash
# Use mock mode for testing
python -m agent_name test --mock

# Implement retry logic in your code
# Use cost controls in agent configuration

# Switch to different model tier
# Check your API usage dashboard
```

### Problem: LiteLLM import error

**Error:** `ImportError: litellm requires openai>=1.0.0`

**Solution:**
```bash
# Upgrade OpenAI package
pip install --upgrade "openai>=1.0.0"

# Reinstall dependencies
cd core
pip install --upgrade -e .
```

---

## Test Failures

### Problem: Tests fail with `PYTHONPATH` error

**Solution:**
```bash
# Always set PYTHONPATH when running tests
PYTHONPATH=core:exports python -m pytest

# For specific agent tests
PYTHONPATH=core:exports python -m agent_name test
```

### Problem: `No tests found` error

**Solution:**
```bash
# Ensure test files start with "test_"
# Ensure test functions start with "test_"
# Check tests/ directory exists

# Run specific test file
cd core && python -m pytest tests/test_file.py -v
```

### Problem: Goal-based tests fail unexpectedly

**Debugging:**
```bash
# Use debug command
PYTHONPATH=core:exports python -m agent_name debug \
  --goal-id "goal_id" \
  --test-name "test_name"

# Check test definition in tests/test_goals.py
# Verify expected outputs match actual outputs
# Run with mock mode to isolate issues
```

---

## Windows-Specific Issues

### Problem: Python App Execution Aliases interfere

**Error:** `Python command not found` or opens Microsoft Store

**Solution:**
```
1. Open Windows Settings
2. Go to Apps → App Execution Aliases
3. Turn OFF both Python aliases
4. Restart terminal
5. Verify: python --version
```

### Problem: Path issues in tests

**Error:** Tests fail with path-related errors

**Solution:**
```python
# Use pathlib instead of os.path
from pathlib import Path
path = Path("relative/path")

# Use os.path.join for cross-platform paths
import os
path = os.path.join("dir", "file.txt")
```

### Problem: ANSI color codes showing as raw text

**Solution:**
```bash
# Use Windows Terminal (not CMD)
# Or install colorama
pip install colorama

# In your code:
import colorama
colorama.init()
```

### Problem: Line endings cause git issues

**Solution:**
```bash
# Configure git
git config --global core.autocrlf true

# Fix existing files
git add --renormalize .
```

---

## Performance Issues

### Problem: Agent execution is slow

**Optimization tips:**
```bash
# 1. Use mock mode for development
python -m agent_name run --input '{}' --mock

# 2. Reduce model size
# Use cheaper models for non-critical nodes

# 3. Cache LLM responses
# Implement caching in your nodes

# 4. Parallelize independent nodes
# Use fanout patterns where possible
```

### Problem: High memory usage

**Solutions:**
```python
# 1. Clear memory between runs
memory.clear()

# 2. Limit conversation history
# Keep only recent messages

# 3. Use generators instead of loading all data
def process_large_file():
    with open(file) as f:
        for line in f:
            yield process(line)
```

---

## Common Error Messages

### `RuntimeError: Event loop is closed`

**Cause:** Async/await issues in synchronous context

**Solution:**
```python
# Use asyncio.run() for top-level async
import asyncio
asyncio.run(agent.execute())

# Or use nest_asyncio
import nest_asyncio
nest_asyncio.apply()
```

### `ValidationError: Invalid output schema`

**Cause:** Node output doesn't match expected schema

**Solution:**
```python
# Check node output keys match edge mapping
# Verify Pydantic models if used
# Use .dict() to convert Pydantic to dict
```

### `FileNotFoundError: agent.json not found`

**Solution:**
```bash
# Run from correct directory
cd /path/to/hive
PYTHONPATH=core:exports python -m agent_name run

# Or specify agent path
python -m framework.runner --agent-path exports/agent_name
```

### `ToolExecutionError: Tool 'xxx' not found`

**Solution:**
```bash
# Verify tool is registered
# Check mcp_servers.json
# Ensure tool name matches exactly (case-sensitive)

# List available tools
python -c "from aden_tools import TOOLS; print([t.name for t in TOOLS])"
```

---

## Getting Help

If you're still stuck after trying these solutions:

1. **Check Documentation:**
   - [ENVIRONMENT_SETUP.md](ENVIRONMENT_SETUP.md) - Setup guide
   - [DEVELOPER.md](DEVELOPER.md) - Development guidelines
   - [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Common commands

2. **Search Issues:**
   - [GitHub Issues](https://github.com/adenhq/hive/issues)
   - Someone may have encountered the same problem

3. **Ask for Help:**
   - [Discord Community](https://discord.com/invite/MXE49hrKDk)
   - Open a new GitHub issue with:
     - Error message (full stack trace)
     - Steps to reproduce
     - Your environment (OS, Python version)
     - What you've tried

4. **Enable Debug Logging:**
   ```python
   import logging
   logging.basicConfig(
       level=logging.DEBUG,
       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
   )
   ```

---

## Contributing Fixes

Found a solution not listed here? Please contribute!

1. Fork the repository
2. Add your solution to this guide
3. Submit a pull request with the `documentation` label

We appreciate your help making this guide more comprehensive!
