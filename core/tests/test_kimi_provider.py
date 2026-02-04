import pytest
from unittest.mock import MagicMock, patch
from framework.llm.kimi import KimiProvider
from framework.llm.provider import LLMResponse

@pytest.fixture
def mock_litellm():
    with patch("framework.llm.litellm.litellm") as mock:
        yield mock

@patch("framework.llm.kimi._get_api_key_from_credential_manager")
def test_kimi_provider_init(mock_get_key):
    mock_get_key.return_value = "test_key"
    provider = KimiProvider()
    assert provider.model == "moonshot-v1-8k"
    assert provider.api_key == "test_key"

def test_kimi_provider_complete_with_reasoning(mock_litellm):
    # Mock LiteLLM response with reasoning_content
    mock_response = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "Final answer"
    mock_message.reasoning_content = "Thinking about the problem..."
    mock_response.choices = [MagicMock(message=mock_message, finish_reason="stop")]
    mock_response.model = "kimi-k2.5"
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    
    mock_litellm.completion.return_value = mock_response

    provider = KimiProvider(api_key="test_key", model="kimi-k2.5")
    response = provider.complete(messages=[{"role": "user", "content": "Hi"}])

    assert isinstance(response, LLMResponse)
    assert response.content == "Final answer"
    assert response.reasoning_content == "Thinking about the problem..."
    assert response.input_tokens == 10
    assert response.output_tokens == 20

@patch("framework.llm.kimi._get_api_key_from_credential_manager")
def test_kimi_provider_missing_key(mock_get_key):
    mock_get_key.return_value = None
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="Kimi/Moonshot API key required"):
            KimiProvider()

@patch("framework.llm.litellm.litellm")
def test_kimi_provider_multimodal_support(mock_litellm):
    # Verify that KimiProvider passes through extra kwargs (like tools or multimodal data)
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="I see an image"), finish_reason="stop")]
    mock_litellm.completion.return_value = mock_response

    provider = KimiProvider(api_key="test_key")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is in this image?"},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
            ]
        }
    ]
    provider.complete(messages=messages)

    # Verify LiteLLM was called with the multimodal messages
    mock_litellm.completion.assert_called_once()
    args, kwargs = mock_litellm.completion.call_args
    assert kwargs["messages"][-1]["content"][1]["type"] == "image_url"

@patch("framework.llm.litellm.litellm")
def test_kimi_provider_complete_with_tools(mock_litellm):
    # Mock a tool use sequence
    # 1. First response: Tool call
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.function.name = "get_weather"
    mock_tool_call.function.arguments = '{"location": "San Francisco"}'
    
    msg_tool = MagicMock()
    msg_tool.content = None
    msg_tool.tool_calls = [mock_tool_call]
    msg_tool.reasoning_content = "I should check the weather."
    
    resp_tool = MagicMock()
    resp_tool.choices = [MagicMock(message=msg_tool, finish_reason="tool_calls")]
    resp_tool.usage = MagicMock(prompt_tokens=5, completion_tokens=10)
    resp_tool.model = "kimi-k2.5"

    # 2. Second response: Stop
    msg_stop = MagicMock()
    msg_stop.content = "It's sunny in SF."
    msg_stop.tool_calls = []
    
    resp_stop = MagicMock()
    resp_stop.choices = [MagicMock(message=msg_stop, finish_reason="stop")]
    resp_stop.usage = MagicMock(prompt_tokens=15, completion_tokens=5)
    resp_stop.model = "kimi-k2.5"

    mock_litellm.completion.side_effect = [resp_tool, resp_stop]

    from framework.llm.provider import Tool, ToolResult, ToolUse
    
    provider = KimiProvider(api_key="test_key")
    tools = [Tool(name="get_weather", description="Get weather", parameters={"properties": {"location": {"type": "string"}}})]
    
    def executor(tool_use: ToolUse) -> ToolResult:
        return ToolResult(tool_use_id=tool_use.id, content="sunny")

    response = provider.complete_with_tools(
        messages=[{"role": "user", "content": "How is the weather in SF?"}],
        system="Be a helpful assistant.",
        tools=tools,
        tool_executor=executor
    )

    assert response.content == "It's sunny in SF."
    assert response.input_tokens == 20 # 5 + 15
    assert response.output_tokens == 15 # 10 + 5
    assert mock_litellm.completion.call_count == 2

@patch("framework.llm.litellm.litellm")
def test_kimi_provider_json_mode(mock_litellm):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"status": "ok"}'), finish_reason="stop")]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    mock_litellm.completion.return_value = mock_response

    provider = KimiProvider(api_key="test_key")
    provider.complete(messages=[{"role": "user", "content": "Hi"}], json_mode=True)

    kwargs = mock_litellm.completion.call_args[1]
    # Check that system prompt includes JSON instruction
    assert any("JSON" in m["content"] for m in kwargs["messages"] if m["role"] == "system")

@patch("framework.llm.litellm.litellm")
def test_kimi_provider_extra_kwargs(mock_litellm):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Hi"), finish_reason="stop")]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
    mock_litellm.completion.return_value = mock_response

    provider = KimiProvider(api_key="test_key", temperature=0.5, top_p=0.9)
    provider.complete(messages=[{"role": "user", "content": "Hi"}])

    kwargs = mock_litellm.completion.call_args[1]
    assert kwargs["temperature"] == 0.5
    assert kwargs["top_p"] == 0.9

@patch("framework.llm.litellm.litellm")
def test_kimi_provider_api_error(mock_litellm):
    mock_litellm.completion.side_effect = Exception("API Key limit exceeded")
    
    provider = KimiProvider(api_key="test_key")
    with pytest.raises(RuntimeError, match="Kimi generation failed: API Key limit exceeded"):
        provider.complete(messages=[{"role": "user", "content": "Hi"}])

@patch("framework.llm.litellm.litellm")
def test_kimi_provider_empty_response(mock_litellm):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=""), finish_reason="stop")]
    mock_response.usage = MagicMock(prompt_tokens=0, completion_tokens=0)
    mock_litellm.completion.return_value = mock_response

    provider = KimiProvider(api_key="test_key")
    response = provider.complete(messages=[{"role": "user", "content": "Hi"}])
    assert response.content == ""

@patch("framework.llm.litellm.litellm")
def test_kimi_provider_tool_error(mock_litellm):
    mock_litellm.completion.side_effect = Exception("Tool validation error")
    
    from framework.llm.provider import Tool, ToolUse, ToolResult
    provider = KimiProvider(api_key="test_key")
    
    def executor(tu): return ToolResult(tool_use_id=tu.id, content="err")
    
    with pytest.raises(RuntimeError, match="Kimi tool generation failed"):
        provider.complete_with_tools(
            messages=[{"role": "user", "content": "Hi"}],
            system="sys",
            tools=[Tool(name="t", description="d")],
            tool_executor=executor
        )

def test_kimi_provider_custom_base():
    with patch.dict("os.environ", {"KIMI_API_KEY": "test_key"}):
        provider = KimiProvider(api_base="https://custom.kimi.ai/v1")
        assert provider.api_base == "https://custom.kimi.ai/v1"
