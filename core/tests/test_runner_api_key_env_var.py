from types import SimpleNamespace

from framework.runner.runner import AgentRunner


class _NoopRegistry:
    def set_session_context(self, **kwargs) -> None:
        self.session_context = kwargs

    def get_server_tool_names(self, _name):
        return []

    def register_mcp_server(self, _config) -> None:
        return None

    def get_tools(self):
        return {}

    def get_executor(self):
        return None

    def cleanup(self) -> None:
        pass


def _runner_for_unit_test() -> AgentRunner:
    runner = AgentRunner.__new__(AgentRunner)
    runner._tool_registry = _NoopRegistry()
    runner._temp_dir = None
    return runner


def _runner_for_setup_unit_test() -> AgentRunner:
    runner = _runner_for_unit_test()
    runner.graph = SimpleNamespace(id="test_graph", nodes=[])
    runner.mock_mode = False
    runner.model = "openai/gpt-4.1"
    runner._llm = None
    runner._credential_store = None
    runner._setup_agent_runtime = lambda *args, **kwargs: None
    return runner


def _raise_credential_store_fallback() -> None:
    raise AssertionError("credential store fallback should not run")


def test_minimax_provider_prefix_maps_to_minimax_api_key():
    runner = _runner_for_unit_test()
    assert runner._get_api_key_env_var("minimax/minimax-text-01") == "MINIMAX_API_KEY"


def test_minimax_model_name_prefix_maps_to_minimax_api_key():
    runner = _runner_for_unit_test()
    assert runner._get_api_key_env_var("minimax-chat") == "MINIMAX_API_KEY"


def test_setup_does_not_fallback_to_api_key_for_missing_subscription_token(monkeypatch):
    runner = _runner_for_setup_unit_test()
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-be-used")
    monkeypatch.setattr("framework.observability.configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(
        "framework.runner.runner.get_hive_config",
        lambda: {"llm": {"auth_mode": "codex"}},
    )
    monkeypatch.setattr(
        "framework.runner.runner.resolve_llm_auth_mode",
        lambda llm: "codex",
    )
    monkeypatch.setattr(
        "framework.runner.runner.get_api_base",
        lambda llm: "https://chatgpt.com/backend-api/codex",
    )
    monkeypatch.setattr(
        "framework.runner.runner.get_llm_extra_kwargs",
        lambda llm: {},
    )
    monkeypatch.setattr("framework.runner.runner.get_api_key", lambda llm: None)

    calls = []

    class _DummyLLM:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("framework.llm.litellm.LiteLLMProvider", _DummyLLM)
    runner._get_api_key_from_credential_store = _raise_credential_store_fallback

    runner._setup()

    assert runner._llm is None
    assert calls == []
