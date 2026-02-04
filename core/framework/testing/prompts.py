"""
Pytest templates for test file generation.

These templates provide headers and fixtures for pytest-compatible async tests.
Tests are written to exports/{agent}/tests/ as Python files and run with pytest.
"""

# Template for the test file header (imports and fixtures)
PYTEST_TEST_FILE_HEADER = '''"""
{test_type} tests for {agent_name}.

{description}

REQUIRES: API_KEY (OpenAI or Anthropic) for real testing.
"""

import os
import pytest
from {agent_module} import default_agent


def _get_api_key():
    """Get API key from CredentialStoreAdapter or environment."""
    # 1. Try CredentialStoreAdapter for Anthropic
    try:
        from aden_tools.credentials import CredentialStoreAdapter
        creds = CredentialStoreAdapter.default()
        if creds.is_available("anthropic"):
            return creds.get("anthropic")
    except (ImportError, KeyError):
        pass

    # 2. Fallback to standard environment variables for OpenAI and others
    return (
        os.environ.get("OPENAI_API_KEY") or
        os.environ.get("ANTHROPIC_API_KEY") or
        os.environ.get("CEREBRAS_API_KEY") or
        os.environ.get("GROQ_API_KEY")
    )


# Skip all tests if no API key and not in mock mode
pytestmark = pytest.mark.skipif(
    not _get_api_key() and not os.environ.get("MOCK_MODE"),
    reason="API key required. Please set OPENAI_API_KEY, ANTHROPIC_API_KEY, or use MOCK_MODE=1."
)
'''

# Template for conftest.py with shared fixtures
PYTEST_CONFTEST_TEMPLATE = '''"""Shared test fixtures for {agent_name} tests."""

import os
import pytest


def _get_api_key():
    """Get API key from CredentialStoreAdapter or environment."""
    try:
        from aden_tools.credentials import CredentialStoreAdapter
        creds = CredentialStoreAdapter.default()
        if creds.is_available("anthropic"):
            return creds.get("anthropic")
    except (ImportError, KeyError):
        pass

    return (
        os.environ.get("OPENAI_API_KEY") or
        os.environ.get("ANTHROPIC_API_KEY") or
        os.environ.get("CEREBRAS_API_KEY") or
        os.environ.get("GROQ_API_KEY")
    )


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
            print("   Set OPENAI_API_KEY or ANTHROPIC_API_KEY for real testing\\n")
        else:
            pytest.fail(
                "\\n❌ No API key found!\\n\\n"
                "Real testing requires an API key. Choose one:\\n"
                "1. Set OpenAI key:\\n"
                "   export OPENAI_API_KEY='your-key-here'\\n"
                "2. Set Anthropic key:\\n"
                "   export ANTHROPIC_API_KEY='your-key-here'\\n"
                "3. Run structure validation only:\\n"
                "   MOCK_MODE=1 pytest exports/{agent_name}/tests/\\n\\n"
                "Note: Mock mode does NOT validate agent behavior or quality."
            )
'''
