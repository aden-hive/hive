"""Tests for the model → API-key-env-var mapping on AgentLoader."""

from framework.loader.agent_loader import AgentLoader


class _NoopRegistry:
    def cleanup(self) -> None:
        pass


def _loader_for_unit_test() -> AgentLoader:
    loader = AgentLoader.__new__(AgentLoader)
    loader._tool_registry = _NoopRegistry()
    loader._temp_dir = None
    return loader


def test_minimax_provider_prefix_maps_to_minimax_api_key():
    loader = _loader_for_unit_test()
    assert loader._get_api_key_env_var("minimax/minimax-text-01") == "MINIMAX_API_KEY"


def test_minimax_model_name_prefix_maps_to_minimax_api_key():
    loader = _loader_for_unit_test()
    assert loader._get_api_key_env_var("minimax-chat") == "MINIMAX_API_KEY"


def test_openrouter_provider_prefix_maps_to_openrouter_api_key():
    loader = _loader_for_unit_test()
    assert loader._get_api_key_env_var("openrouter/x-ai/grok-4.20-beta") == "OPENROUTER_API_KEY"
