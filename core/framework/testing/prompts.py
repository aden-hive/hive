"""
Pytest templates for test file generation.

These templates provide headers and fixtures for pytest-compatible async tests.
Tests are written to exports/{agent}/tests/ as Python files and run with pytest.

Tests use AgentRunner.load() — the canonical runtime path — which creates
AgentRuntime, ExecutionStream, and proper session/log storage. For agents
with client-facing nodes, an auto_responder fixture handles input injection.
"""

# Template for the test file header (imports and fixtures)
PYTEST_TEST_FILE_HEADER = '''"""
{test_type} tests for {agent_name}.

{description}

REQUIRES: API_KEY for execution tests. Structure tests run without keys.
"""

import os
import pytest
from pathlib import Path

# Agent path resolved from this test file's location
AGENT_PATH = Path(__file__).resolve().parents[1]


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
        os.environ.get("GROQ_API_KEY") or
        os.environ.get("GEMINI_API_KEY")
    )


# Skip all tests if no API key and not in mock mode
pytestmark = pytest.mark.skipif(
    not _get_api_key() and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY or use MOCK_MODE=1 for structure tests."
)
'''

# Template for conftest.py with shared fixtures
PYTEST_CONFTEST_TEMPLATE = '''"""Shared test fixtures for {agent_name} tests."""

import json
import os
import re
import sys
from pathlib import Path

# Add exports/ and core/ to sys.path so the agent package and framework are importable
_repo_root = Path(__file__).resolve().parents[3]
for _p in ["exports", "core"]:
    _path = str(_repo_root / _p)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest
from framework.runner.runner import AgentRunner
from framework.runtime.event_bus import EventType

AGENT_PATH = Path(__file__).resolve().parents[1]


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
        os.environ.get("GROQ_API_KEY") or
        os.environ.get("GEMINI_API_KEY")
    )


@pytest.fixture(scope="session")
def mock_mode():
    """Return True if running in mock mode (no API key or MOCK_MODE=1)."""
    if os.environ.get("MOCK_MODE"):
        return True
    return not bool(_get_api_key())


@pytest.fixture(scope="session")
async def runner(tmp_path_factory, mock_mode):
    """Create an AgentRunner using the canonical runtime path.

    Uses tmp_path_factory for storage so tests don't pollute ~/.hive/agents/.
    Goes through AgentRunner.load() -> _setup() -> AgentRuntime, the same
    path as ``hive run``.
    """
    storage = tmp_path_factory.mktemp("agent_storage")
    r = AgentRunner.load(
        AGENT_PATH,
        mock_mode=mock_mode,
        storage_path=storage,
    )
    r._setup()
    yield r
    await r.cleanup_async()


@pytest.fixture
def auto_responder(runner):
    """Auto-respond to client-facing node input requests.

    Subscribes to CLIENT_INPUT_REQUESTED events and injects a response
    to unblock the node. Customize the response before calling start():

        auto_responder.response = "approve the report"
        await auto_responder.start()
    """
    class AutoResponder:
        def __init__(self, runner_instance):
            self._runner = runner_instance
            self.response = "yes, proceed"
            self.interactions = []
            self._sub_id = None

        async def start(self):
            runtime = self._runner._agent_runtime
            if runtime is None:
                return

            async def _handle(event):
                self.interactions.append(event.node_id)
                await runtime.inject_input(event.node_id, self.response)

            self._sub_id = runtime.subscribe_to_events(
                event_types=[EventType.CLIENT_INPUT_REQUESTED],
                handler=_handle,
            )

        async def stop(self):
            runtime = self._runner._agent_runtime
            if self._sub_id and runtime:
                runtime.unsubscribe_from_events(self._sub_id)
                self._sub_id = None

    return AutoResponder(runner)


@pytest.fixture(scope="session", autouse=True)
def check_api_key():
    """Ensure API key is set for real testing."""
    if not _get_api_key():
        if os.environ.get("MOCK_MODE"):
            print("\\n  Running in MOCK MODE - structure validation only")
            print("  Set ANTHROPIC_API_KEY for real testing\\n")
        else:
            pytest.fail(
                "\\nNo API key found!\\n"
                "Set ANTHROPIC_API_KEY or use MOCK_MODE=1 for structure tests.\\n"
            )


def parse_json_from_output(result, key):
    """Parse JSON from agent output (framework may store full LLM response as string)."""
    val = result.output.get(key, "")
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        json_text = re.sub(r"```json\\s*|\\s*```", "", val).strip()
        try:
            return json.loads(json_text)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def safe_get_nested(result, key_path, default=None):
    """Safely get nested value from result.output."""
    output = result.output or {{}}
    current = output
    for key in key_path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, str):
            try:
                json_text = re.sub(r"```json\\s*|\\s*```", "", current).strip()
                parsed = json.loads(json_text)
                if isinstance(parsed, dict):
                    current = parsed.get(key)
                else:
                    return default
            except json.JSONDecodeError:
                return default
        else:
            return default
    return current if current is not None else default


pytest.parse_json_from_output = parse_json_from_output
pytest.safe_get_nested = safe_get_nested
'''
