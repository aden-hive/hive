"""
Pytest templates for test file generation.

These templates provide headers and fixtures for pytest-compatible async tests.
Tests are written to exports/{agent}/tests/ as Python files and run with pytest.
"""

# Template for the test file header (imports and fixtures)
PYTEST_TEST_FILE_HEADER = '''"""
{test_type} tests for {agent_name}.

{description}

REQUIRES: An LLM API key (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) for real testing.
"""

import os
import pytest
from exports.{agent_module} import default_agent


# Supported LLM providers and their environment variable names
_SUPPORTED_PROVIDERS = [
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("cerebras", "CEREBRAS_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("together", "TOGETHER_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
]


def _get_api_key():
    """Get API key from CredentialManager or environment.
    
    Checks multiple providers in order of preference, returning the first
    available key. This allows tests to run with any supported LLM provider.
    """
    # First, try CredentialManager for managed credentials
    try:
        from aden_tools.credentials import CredentialManager
        creds = CredentialManager()
        for provider, _ in _SUPPORTED_PROVIDERS:
            if creds.is_available(provider):
                return creds.get(provider)
    except (ImportError, Exception):
        pass
    
    # Fallback: check environment variables for any supported provider
    for _, env_var in _SUPPORTED_PROVIDERS:
        key = os.environ.get(env_var)
        if key:
            return key
    
    return None


# Skip all tests if no API key and not in mock mode
pytestmark = pytest.mark.skipif(
    not _get_api_key() and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or another provider key. Or use MOCK_MODE=1."
)


'''


# Template for conftest.py with shared fixtures
PYTEST_CONFTEST_TEMPLATE = '''"""Shared test fixtures for {agent_name} tests."""

import os
import pytest


# Supported LLM providers and their environment variable names
_SUPPORTED_PROVIDERS = [
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("cerebras", "CEREBRAS_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("together", "TOGETHER_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
]


def _get_api_key():
    """Get API key from CredentialManager or environment.
    
    Checks multiple providers in order of preference, returning the first
    available key. This allows tests to run with any supported LLM provider.
    """
    # First, try CredentialManager for managed credentials
    try:
        from aden_tools.credentials import CredentialManager
        creds = CredentialManager()
        for provider, _ in _SUPPORTED_PROVIDERS:
            if creds.is_available(provider):
                return creds.get(provider)
    except (ImportError, Exception):
        pass
    
    # Fallback: check environment variables for any supported provider
    for _, env_var in _SUPPORTED_PROVIDERS:
        key = os.environ.get(env_var)
        if key:
            return key
    
    return None


def _get_available_provider():
    """Return the name of the first available provider, or None."""
    try:
        from aden_tools.credentials import CredentialManager
        creds = CredentialManager()
        for provider, _ in _SUPPORTED_PROVIDERS:
            if creds.is_available(provider):
                return provider
    except (ImportError, Exception):
        pass
    
    for provider, env_var in _SUPPORTED_PROVIDERS:
        if os.environ.get(env_var):
            return provider
    
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
            print("   Set an LLM provider API key for real testing\\n")
        else:
            pytest.fail(
                "\\n❌ No LLM API key found!\\n\\n"
                "Real testing requires an API key. Choose one:\\n"
                "1. Set an API key (RECOMMENDED):\\n"
                "   export ANTHROPIC_API_KEY='your-key-here'\\n"
                "   export OPENAI_API_KEY='your-key-here'\\n"
                "   (or any other supported provider)\\n"
                "2. Run structure validation only:\\n"
                "   MOCK_MODE=1 pytest exports/{agent_name}/tests/\\n\\n"
                "Note: Mock mode does NOT validate agent behavior or quality."
            )
    else:
        provider = _get_available_provider()
        print(f"\\n✓ Using {{provider}} for LLM testing\\n")


@pytest.fixture
def sample_inputs():
    """Sample inputs for testing."""
    return {{
        "simple": {{"query": "test"}},
        "complex": {{"query": "detailed multi-step query", "depth": 3}},
        "edge_case": {{"query": ""}},
    }}
'''

