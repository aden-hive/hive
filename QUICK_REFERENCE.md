# Quick Reference Guide

Quick commands and tips for working with the Aden Agent Framework.

## Common Commands

### Setup & Installation
```bash
# Initial setup
./quickstart.sh

# Manual setup
cd core && pip install -e .
cd tools && pip install -e .

# Verify installation
python -c "import framework; import aden_tools; print('✓ Setup complete')"
```

### Running Agents
```bash
# Run agent with real LLM
PYTHONPATH=core:exports python -m agent_name run --input '{"key": "value"}'

# Run with mock mode (no API costs)
PYTHONPATH=core:exports python -m agent_name run --input '{"key": "value"}' --mock

# Validate agent structure
PYTHONPATH=core:exports python -m agent_name validate

# Show agent info
PYTHONPATH=core:exports python -m agent_name info
```

### Testing Agents
```bash
# Run all tests
PYTHONPATH=core:exports python -m agent_name test

# Run with mock LLM
PYTHONPATH=core:exports python -m agent_name test --mock

# Debug specific test
PYTHONPATH=core:exports python -m agent_name debug --goal-id "goal_id" --test-name "test_name"
```

### Framework Development
```bash
# Run core framework tests
cd core && python -m pytest tests/

# Run tools tests
cd tools && python -m pytest tests/

# Lint and format checks
make check

# Format code
make format
```

## Environment Variables

### Required for LLM Usage
```bash
export ANTHROPIC_API_KEY="your-key"      # Claude models
export OPENAI_API_KEY="your-key"         # GPT models
export GOOGLE_API_KEY="your-key"         # Gemini models
```

### Optional
```bash
export BRAVE_SEARCH_API_KEY="your-key"   # Web search tool
export PYTHONPATH=core:exports           # For running agents
```

## Project Structure Quick Reference

```
hive/
├── core/                    # Core framework
│   ├── framework/           # Main package
│   │   ├── graph/           # Node & graph system
│   │   ├── runner/          # Agent execution
│   │   ├── llm/             # LLM providers
│   │   └── testing/         # Test framework
│   └── tests/               # Framework tests
│
├── tools/                   # MCP tools package
│   └── src/aden_tools/
│       ├── tools/           # 19 MCP tools
│       └── credentials/     # Credential management
│
├── exports/                 # Agent examples
├── docs/                    # Documentation
└── scripts/                 # Setup scripts
```

## Common Workflows

### Building an Agent
1. Use Claude Code: `claude> /building-agents`
2. Define goal and success criteria
3. Coding agent generates graph
4. Export to package
5. Test with mock mode first
6. Run with real LLM

### Contributing Code
1. Find/create issue
2. Comment to request assignment
3. Wait for assignment (24h)
4. Create branch: `git checkout -b type/description`
5. Make changes
6. Run `make check`
7. Commit with conventional format
8. Push and create PR

### Debugging Agent Issues
1. Check logs in `agent_logs/`
2. Use `--mock` to isolate graph issues
3. Run `validate` to check structure
4. Use `debug` command for specific tests
5. Check PYTHONPATH is set correctly

## Troubleshooting

### Import Errors
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH=core:exports

# Reinstall packages
cd core && pip install -e .
cd tools && pip install -e .
```

### Windows Issues
```bash
# Use WSL for best experience
wsl

# Or disable Python App Execution Aliases
# Settings → Apps → App Execution Aliases → Turn off Python
```

### Test Failures
```bash
# Run specific test
cd core && python -m pytest tests/test_name.py -v

# Run with verbose output
cd core && python -m pytest tests/ -vv
```

## Useful Links

- **Documentation**: https://docs.adenhq.com/
- **GitHub Issues**: https://github.com/adenhq/hive/issues
- **Discord Community**: https://discord.com/invite/MXE49hrKDk
- **Contributing Guide**: [CONTRIBUTING.md](CONTRIBUTING.md)
- **Setup Guide**: [ENVIRONMENT_SETUP.md](ENVIRONMENT_SETUP.md)

## Quick Tips

✅ Always use `PYTHONPATH=core:exports` when running agents  
✅ Test with `--mock` first to save API costs  
✅ Run `make check` before committing  
✅ Use conventional commit format  
✅ Request assignment before working on issues  
✅ Keep PRs focused and small  

## Getting Help

- Check [ENVIRONMENT_SETUP.md](ENVIRONMENT_SETUP.md) for detailed setup
- Read [DEVELOPER.md](DEVELOPER.md) for development guidelines
- Search [existing issues](https://github.com/adenhq/hive/issues)
- Ask on [Discord](https://discord.com/invite/MXE49hrKDk)
