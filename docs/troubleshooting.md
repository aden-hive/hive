# Troubleshooting Guide

This guide helps you resolve common issues when setting up and using the Aden Hive Framework.

## Setup Issues

### Problem: Python 3.11+ Not Found

**Error Message:**
```
python: command not found
or
python is not version 3.11+
```

**Solutions:**

1. **Install Python 3.11+**
   - Visit [python.org](https://www.python.org/downloads/)
   - Download Python 3.12 or later (recommended)
   - Add Python to your system PATH during installation

2. **Verify Installation**
   ```bash
   python --version
   # Should show: Python 3.11.x or higher
   ```

3. **Use Python 3.11 Explicitly**
   ```bash
   python3.11 --version
   # If available, use python3.11 instead of python in commands
   ```

---

### Problem: Failed to Install Framework Package

**Error Message:**
```
Failed to install framework package
or
pip install -e . failed
```

**Solutions:**

1. **Ensure pip is Updated**
   ```bash
   python -m pip install --upgrade pip
   ```

2. **Check for Permission Issues**
   ```bash
   # On macOS/Linux
   python -m pip install -e . --user
   
   # On Windows, ensure you're running as Administrator
   ```

3. **Clean Previous Installation**
   ```bash
   pip uninstall framework
   rm -rf core/build core/dist *.egg-info
   python -m pip install -e .
   ```

4. **Check Dependencies**
   ```bash
   pip install -r core/requirements.txt
   python -m pip install -e core/
   ```

---

### Problem: MCP Dependencies Installation Fails

**Error Message:**
```
Failed to install MCP dependencies
or
pip install mcp fastmcp failed
```

**Solutions:**

1. **Install Dependencies Manually**
   ```bash
   pip install mcp
   pip install fastmcp
   ```

2. **Use Specific Versions**
   ```bash
   pip install mcp==0.5.0
   pip install fastmcp==0.1.0
   ```

3. **Check for Conflicts**
   ```bash
   pip list | grep -i mcp
   pip install --upgrade mcp fastmcp
   ```

---

### Problem: .mcp.json Configuration Not Found

**Error Message:**
```
No .mcp.json found
```

**Solutions:**

1. **Run Setup Script**
   ```bash
   cd core
   python setup_mcp.py
   ```

2. **Create Configuration Manually**
   ```bash
   cat > core/.mcp.json << 'EOF'
   {
     "mcpServers": {
       "agent-builder": {
         "command": "python",
         "args": ["-m", "framework.mcp.agent_builder_server"],
         "cwd": "."
       }
     }
   }
   EOF
   ```

3. **Verify Configuration**
   ```bash
   cat core/.mcp.json
   ```

---

## Runtime Issues

### Problem: ImportError - No module named 'framework'

**Error Message:**
```
ModuleNotFoundError: No module named 'framework'
```

**Solutions:**

1. **Set PYTHONPATH**
   ```bash
   export PYTHONPATH=core:exports:$PYTHONPATH
   python your_script.py
   
   # Or on Windows:
   set PYTHONPATH=core;exports;%PYTHONPATH%
   python your_script.py
   ```

2. **Install Framework in Development Mode**
   ```bash
   cd core
   pip install -e .
   ```

3. **Verify Installation**
   ```bash
   python -c "import framework; print('✓ Framework installed')"
   ```

---

### Problem: ImportError - No module named 'aden_tools'

**Error Message:**
```
ModuleNotFoundError: No module named 'aden_tools'
```

**Solutions:**

1. **Install aden_tools**
   ```bash
   cd tools
   pip install -e .
   ```

2. **Set PYTHONPATH**
   ```bash
   export PYTHONPATH=core:tools:exports:$PYTHONPATH
   python your_script.py
   ```

3. **Verify Installation**
   ```bash
   python -c "import aden_tools; print('✓ aden_tools installed')"
   ```

---

### Problem: Agent Run Fails with "No agent found"

**Error Message:**
```
Error: Agent 'my_agent' not found in exports/
```

**Solutions:**

1. **Check Agent Path**
   ```bash
   ls -la exports/
   # Should see your agent directory
   ```

2. **Verify Agent Structure**
   ```bash
   ls exports/my_agent/
   # Should contain: agent.json, agent.py, tools.py, etc.
   ```

3. **Use Correct Module Name**
   ```bash
   # Command should match the folder name in exports/
   PYTHONPATH=core:exports python -m my_agent run --input '{...}'
   ```

4. **Validate Agent Configuration**
   ```bash
   python -c "
   import json
   with open('exports/my_agent/agent.json') as f:
       config = json.load(f)
       print('Agent name:', config.get('name'))
       print('Agent version:', config.get('version'))
   "
   ```

---

### Problem: LLM API Key Errors

**Error Message:**
```
"API key required. Set ANTHROPIC_API_KEY env var"
or
"OpenAI API key not found"
```

**Solutions:**

1. **Set API Key**
   ```bash
   # For Anthropic
   export ANTHROPIC_API_KEY=your_key_here
   
   # For OpenAI
   export OPENAI_API_KEY=your_key_here
   
   # For other providers, check their documentation
   ```

2. **Use .env File**
   ```bash
   # Create .env file in project root
   echo "ANTHROPIC_API_KEY=your_key_here" > .env
   
   # Load environment
   source .env
   ```

3. **Verify Key is Set**
   ```bash
   echo $ANTHROPIC_API_KEY
   # Should display your key (first few characters)
   ```

---

### Problem: Test Generation Tools Not Working

**Error Message:**
```
"Failed to initialize LLM: Anthropic API key required"
when using generate_constraint_tests or generate_success_tests
```

**Solution:**

This has been fixed in recent versions. The MCP server no longer requires LLM initialization for test generation.

1. **Update Framework**
   ```bash
   cd core
   pip install -e . --upgrade
   ```

2. **Use Returned Guidelines**
   - The tools now return test guidelines and templates
   - Use these to write tests directly with the Write tool
   - No LLM API key required

---

## Testing Issues

### Problem: Tests Fail with "pytest not found"

**Error Message:**
```
bash: pytest: command not found
```

**Solutions:**

1. **Install pytest**
   ```bash
   pip install pytest pytest-asyncio
   ```

2. **Run Tests with Python Module**
   ```bash
   python -m pytest core/tests/
   ```

3. **Set PYTHONPATH for Tests**
   ```bash
   PYTHONPATH=core:exports python -m pytest core/tests/
   ```

---

### Problem: Async Tests Fail

**Error Message:**
```
RuntimeError: no running event loop
or
Event loop is closed
```

**Solutions:**

1. **Install pytest-asyncio**
   ```bash
   pip install pytest-asyncio
   ```

2. **Ensure Async Marker**
   - Tests must have `@pytest.mark.asyncio` decorator
   - Verify this is present in test files

3. **Run Tests Correctly**
   ```bash
   PYTHONPATH=core:exports python -m pytest core/tests/ --asyncio-mode=auto
   ```

---

## Docker Issues

### Problem: Docker Image Not Found

**Error Message:**
```
Error response from daemon: image adenhq/hive not found
```

**Solutions:**

1. **Pull the Latest Image**
   ```bash
   docker pull adenhq/hive:latest
   ```

2. **Build Image Locally**
   ```bash
   docker build -t adenhq/hive:latest .
   ```

3. **Check Available Images**
   ```bash
   docker images | grep hive
   ```

---

### Problem: Docker Permission Denied

**Error Message:**
```
Got permission denied while trying to connect to Docker daemon
```

**Solutions:**

1. **Add User to Docker Group (Linux)**
   ```bash
   sudo usermod -aG docker $USER
   newgrp docker
   ```

2. **Run with Sudo**
   ```bash
   sudo docker run adenhq/hive:latest
   ```

---

## Getting Help

### Resources

- **Documentation**: https://docs.adenhq.com/
- **GitHub Issues**: https://github.com/adenhq/hive/issues
- **Discord Community**: https://discord.com/invite/MXE49hrKDk
- **Discussions**: https://github.com/adenhq/hive/discussions

### When Reporting Issues

1. **Include System Information**
   ```bash
   python --version
   pip --version
   docker --version  # if using Docker
   ```

2. **Provide Full Error Messages**
   - Include the complete error traceback
   - Show the command that failed
   - Include relevant environment variables

3. **Share Reproduction Steps**
   - Exact commands you ran
   - Configuration files (without sensitive data)
   - Expected vs actual behavior

4. **Check Existing Issues**
   - Search GitHub issues before creating a new one
   - Add comments if you encounter the same issue

---

## Contributing to This Guide

If you encounter an issue not covered here:

1. **Document the Solution**: Create a detailed explanation
2. **Submit a PR**: Add it to this troubleshooting guide
3. **Help Others**: Your solution might help future contributors

Follow the [Contribution Guidelines](CONTRIBUTING.md) for the process.

---

**Last Updated**: January 26, 2026
