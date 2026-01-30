"""
Pytest templates for test file generation.

These templates provide headers and fixtures for pytest-compatible async tests.
Tests are written to exports/{agent}/tests/ as Python files and run with pytest.
"""

# Template for the test file header (imports and fixtures)
PYTEST_TEST_FILE_HEADER = '''"""
{test_type} tests for {agent_name}.

{description}

REQUIRES: Valid LLM API key (e.g., ANTHROPIC_API_KEY, OPENAI_API_KEY) for real testing.
"""

import os
import pytest
from exports.{agent_module} import default_agent


def _get_api_key():
    """Get API key from CredentialManager or environment."""
    # Check common API keys
    keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "AZURE_API_KEY"]
    for key in keys:
        if os.environ.get(key):
            return os.environ.get(key)
            
    try:
        from aden_tools.credentials import CredentialManager
        creds = CredentialManager()
        # Check if any provider is available
        if any(creds.is_available(p) for p in ["anthropic", "openai", "gemini"]):
            return "found_in_creds"
    except ImportError:
        pass
        
    return None


# Skip all tests if no API key and not in mock mode
pytestmark = pytest.mark.skipif(
    not _get_api_key() and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY/OPENAI_API_KEY or use MOCK_MODE=1."
)


'''

# Template for conftest.py with shared fixtures
PYTEST_CONFTEST_TEMPLATE = '''"""Shared test fixtures for {agent_name} tests."""

import os
import pytest


def _get_api_key():
    """Get API key from CredentialManager or environment."""
    # Check common API keys
    keys = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "AZURE_API_KEY"]
    for key in keys:
        if os.environ.get(key):
            return os.environ.get(key)
            
    try:
        from aden_tools.credentials import CredentialManager
        creds = CredentialManager()
        # Check if any provider is available
        if any(creds.is_available(p) for p in ["anthropic", "openai", "gemini"]):
            return "found_in_creds"
    except ImportError:
        pass
        
    return None


@pytest.fixture
def mock_mode():
    """Check if running in mock mode."""
    return bool(os.environ.get("MOCK_MODE"))


@pytest.fixture(scope="session", autouse=True)
def check_api_key():
    """Ensure API key is set for real testing."""
    if not _get_api_key():
        if os.environ.get("MOCK_MODE"):
            print("\\n⚠️  Running in MOCK MODE - structure validation only")
            print("   This does NOT test LLM behavior or agent quality")
            print("   Set ANTHROPIC_API_KEY (or other provider key) for real testing\\n")
        else:
            pytest.fail(
                "\\n❌ No LLM API key set!\\n\\n"
                "Real testing requires an API key. Choose one:\\n"
                "1. Set API key (RECOMMENDED):\\n"
                "   export ANTHROPIC_API_KEY='your-key' OR export OPENAI_API_KEY='your-key'\\n"
                "2. Run structure validation only:\\n"
                "   MOCK_MODE=1 pytest exports/{agent_name}/tests/\\n\\n"
                "Note: Mock mode does NOT validate agent behavior or quality."
            )


@pytest.fixture
def sample_inputs():
    """Sample inputs for testing."""
    return {{
        "simple": {{"query": "test"}},
        "complex": {{"query": "detailed multi-step query", "depth": 3}},
        "edge_case": {{"query": ""}},
    }}
'''
