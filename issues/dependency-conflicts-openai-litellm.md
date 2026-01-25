# 
## Issue Type

🐛 Bug / 🔧 Maintenance

## Priority

🔴 High - Blocks clean installation

## Description

The framework has a known dependency conflict between `openai` and `litellm` packages that requires manual intervention during setup. This issue causes installation failures and requires users to manually run an upgrade command after installation.

## Current Behavior

1. When installing the framework via `pip install -e core/`, the default `openai` package version may be incompatible with `litellm`
2. Users must manually run `pip install --upgrade "openai>=1.0.0"` after installation
3. The `setup-python.sh` script includes a workaround but it's not foolproof
4. This creates a poor developer experience and can cause confusion for new contributors

**Evidence in codebase:**

```bash
# From scripts/setup-python.sh (lines 67-71)
echo "⚙️  Fixing package compatibility..."
# litellm requires openai >= 1.0.0, but sometimes gets an older version
pip install --upgrade "openai>=1.0.0" > /dev/null 2>&1 || {
    echo "⚠️  Warning: Could not upgrade openai package"
}
```

## Expected Behavior

- Framework should install cleanly without manual intervention
- All dependencies should be properly constrained to avoid conflicts
- No post-installation upgrade steps should be required

## Steps to Reproduce

1. Create a fresh virtual environment: `python -m venv test_env`
2. Activate it: `source test_env/bin/activate` (or `test_env\Scripts\activate` on Windows)
3. Install framework: `pip install -e core/`
4. Try to use LiteLLM: `python -c "import litellm; print('OK')"`
5. May fail with compatibility errors

## Root Cause

The issue stems from `core/requirements.txt` and `core/pyproject.toml` not properly constraining the `openai` package version:

**Current requirements.txt:**

```txt
litellm>=1.81.0
```

**Missing constraint:**

```txt
openai>=1.0.0  # Required by litellm but not explicitly declared
```

## Proposed Solution

### Option 1: Explicit Version Pinning (Recommended)

Update `core/requirements.txt` to explicitly declare the OpenAI version:

```txt
# Core dependencies
pydantic>=2.0
anthropic>=0.40.0
httpx>=0.27.0

# LLM integration (litellm requires openai>=1.0.0)
openai>=1.0.0
litellm>=1.81.0

# MCP server dependencies
mcp
fastmcp

# Testing (required for test framework)
pytest>=8.0
pytest-asyncio>=0.23
pytest-xdist>=3.0
```

### Option 2: Update pyproject.toml

Add explicit dependency in `core/pyproject.toml`:

```toml
dependencies = [
    "pydantic>=2.0",
    "anthropic>=0.40.0",
    "httpx>=0.27.0",
    "openai>=1.0.0",      # Add this line
    "litellm>=1.81.0",
    "mcp>=1.0.0",
    "fastmcp>=2.0.0",
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-xdist>=3.0",
]
```

## Implementation Checklist

- [ ] Add `openai>=1.0.0` to `core/requirements.txt`
- [ ] Add `openai>=1.0.0` to `core/pyproject.toml` dependencies
- [ ] Remove or update workaround in `scripts/setup-python.sh`
- [ ] Test clean installation in fresh virtual environment
- [ ] Test on Python 3.11, 3.12, and 3.13
- [ ] Test on Windows, macOS, and Linux
- [ ] Update `ENVIRONMENT_SETUP.md` if necessary
- [ ] Add note to `CHANGELOG.md`

## Files to Modify

1. `core/requirements.txt` - Add explicit openai version
2. `core/pyproject.toml` - Add explicit openai dependency
3. `scripts/setup-python.sh` - Remove workaround or add comment
4. `CHANGELOG.md` - Document the fix

## Testing Instructions

After implementing the fix:

```bash
# Test 1: Fresh installation
python -m venv test_clean
source test_clean/bin/activate  # or test_clean\Scripts\activate on Windows
pip install -e core/
python -c "import litellm; import openai; print(f'openai: {openai.__version__}'); print('✓ OK')"

# Test 2: Verify all imports work
python -c "from framework import Runtime, AgentRunner; print('✓ Framework imports OK')"

# Test 3: Run basic LLM test
python -c "
from framework.llm.litellm import LiteLLMProvider
llm = LiteLLMProvider(model='gpt-3.5-turbo')
print('✓ LiteLLM provider created successfully')
"

# Test 4: Run existing tests
cd core
pytest tests/test_litellm_provider.py -v
```

## Related Issues

- Related to setup issues in `ENVIRONMENT_SETUP.md`
- May affect MCP server startup
- Could impact tools package if it depends on framework

## Additional Context

**Current workaround users are experiencing:**

From community reports and code comments:

- Users get cryptic error messages about missing attributes in openai module
- The error typically manifests when trying to use LiteLLM
- Current manual fix: `pip install --upgrade openai>=1.0.0`

