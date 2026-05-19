from framework.runner.runner import AgentRunner


class _NoopRegistry:
    def cleanup(self) -> None:
        pass


def _runner_for_unit_test() -> AgentRunner:
    runner = AgentRunner.__new__(AgentRunner)
    runner._tool_registry = _NoopRegistry()
    runner._temp_dir = None
    return runner


def test_minimax_provider_prefix_maps_to_minimax_api_key():
    runner = _runner_for_unit_test()
    assert runner._get_api_key_env_var("minimax/minimax-text-01") == "MINIMAX_API_KEY"


def test_minimax_model_name_prefix_maps_to_minimax_api_key():
    runner = _runner_for_unit_test()
    assert runner._get_api_key_env_var("minimax-chat") == "MINIMAX_API_KEY"


def test_openrouter_provider_prefix_maps_to_openrouter_api_key():
    runner = _runner_for_unit_test()
    assert runner._get_api_key_env_var("openrouter/x-ai/grok-4.20-beta") == "OPENROUTER_API_KEY"
