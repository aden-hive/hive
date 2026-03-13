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


class TestGetApiKeyUrl:
    """Tests for the _get_api_key_url helper method."""

    def test_anthropic_provider_returns_anthropic_console(self):
        url = AgentRunner._get_api_key_url("anthropic/claude-sonnet-4")
        assert url == "https://console.anthropic.com/"

    def test_claude_model_returns_anthropic_console(self):
        url = AgentRunner._get_api_key_url("claude-sonnet-4-20250514")
        assert url == "https://console.anthropic.com/"

    def test_openai_provider_returns_openai_platform(self):
        url = AgentRunner._get_api_key_url("openai/gpt-4o")
        assert url == "https://platform.openai.com/api-keys"

    def test_gpt_model_returns_openai_platform(self):
        url = AgentRunner._get_api_key_url("gpt-4o-mini")
        assert url == "https://platform.openai.com/api-keys"

    def test_gemini_provider_returns_google_ai_studio(self):
        url = AgentRunner._get_api_key_url("gemini/gemini-pro")
        assert url == "https://aistudio.google.com/apikey"

    def test_google_provider_returns_google_ai_studio(self):
        url = AgentRunner._get_api_key_url("google/gemini-pro")
        assert url == "https://aistudio.google.com/apikey"

    def test_mistral_provider_returns_mistral_console(self):
        url = AgentRunner._get_api_key_url("mistral/mistral-large")
        assert url == "https://console.mistral.ai/api-keys/"

    def test_groq_provider_returns_groq_console(self):
        url = AgentRunner._get_api_key_url("groq/llama-3-70b")
        assert url == "https://console.groq.com/keys"

    def test_cerebras_provider_returns_cerebras_cloud(self):
        url = AgentRunner._get_api_key_url("cerebras/llama-3.3-70b")
        assert url == "https://cloud.cerebras.ai/"

    def test_azure_provider_returns_azure_portal(self):
        url = AgentRunner._get_api_key_url("azure/gpt-4")
        assert url == "https://portal.azure.com/"

    def test_cohere_provider_returns_cohere_dashboard(self):
        url = AgentRunner._get_api_key_url("cohere/command-r")
        assert url == "https://dashboard.cohere.com/api-keys"

    def test_replicate_provider_returns_replicate_tokens(self):
        url = AgentRunner._get_api_key_url("replicate/llama-70b")
        assert url == "https://replicate.com/account/api-tokens"

    def test_together_provider_returns_together_api_keys(self):
        url = AgentRunner._get_api_key_url("together/llama-70b")
        assert url == "https://api.together.xyz/settings/api-keys"

    def test_minimax_provider_returns_minimax_interface_key(self):
        url = AgentRunner._get_api_key_url("minimax/minimax-text-01")
        assert url == "https://www.minimaxi.com/user-center/basic-information/interface-key"

    def test_minimax_model_prefix_returns_minimax_interface_key(self):
        url = AgentRunner._get_api_key_url("minimax-chat")
        assert url == "https://www.minimaxi.com/user-center/basic-information/interface-key"

    def test_kimi_provider_returns_moonshot_api_keys(self):
        url = AgentRunner._get_api_key_url("kimi/kimi-chat")
        assert url == "https://platform.moonshot.cn/console/api-keys"

    def test_unknown_provider_returns_litellm_docs(self):
        url = AgentRunner._get_api_key_url("unknown-model")
        assert url == "https://docs.litellm.ai/docs/providers"

    def test_case_insensitive_model_name(self):
        url = AgentRunner._get_api_key_url("CLAUDE-SONNET-4")
        assert url == "https://console.anthropic.com/"
