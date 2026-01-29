# LLM Streaming Guide

This guide explains how to use real-time token streaming with the Aden Agent Framework.

## Overview

Streaming allows you to receive AI responses token-by-token as they are generated. This is essential for:
- Improving perceived performance and user experience (UX).
- Real-time monitoring of agent thought processes.
- Building interactive chat interfaces.

## Enabling Streaming in Agents

Streaming is enabled at the node level in your `agent.json` definition by setting the `streaming_enabled` flag to `true`.

### Example `agent.json`

```json
{
  "nodes": [
    {
      "node_id": "process_request",
      "name": "Process User Request",
      "node_type": "llm_generate",
      "streaming_enabled": true,
      "system_prompt": "You are a helpful assistant.",
      "input_keys": ["user_input"],
      "output_keys": ["assistant_response"]
    }
  ]
}
```

When `streaming_enabled` is `true`, the `GraphExecutor` will use the `stream_complete` method of the configured LLM provider.

## Programmatic Usage

If you are using the `LLMProvider` directly in your code, you can use the `stream_complete` async iterator.

### Basic Async Iteration

```python
from framework.llm.litellm import LiteLLMProvider

async def main():
    llm = LiteLLMProvider(model="gpt-4o-mini")
    messages = [{"role": "user", "content": "Write a short poem about bees."}]
    
    async for chunk in llm.stream_complete(messages):
        print(chunk.content, end="", flush=True)
        
        if chunk.is_complete:
            print(f"\n\nStop reason: {chunk.stop_reason}")
            print(f"Tokens: {chunk.input_tokens} in, {chunk.output_tokens} out")
```

### Using Callbacks

You can also provide a callback that will be triggered for every new token chunk:

```python
def on_token(chunk):
    print(f"Received: {chunk.content}")

# Pass the callback to the provider
async for chunk in llm.stream_complete(messages, callback=on_token):
    # Process normally...
    pass
```

## How It Works

1.  **Aggregation**: Even when streaming is enabled, the framework automatically aggregates all tokens into a single string.
2.  **Validation**: After the stream finishes, the aggregated content is passed to any configured Pydantic validators or JSON parsers.
3.  **Metadata**: The final `StreamChunk` contains the total token counts and stop reason for the entire generation.

## Supported Providers

- **LiteLLMProvider**: Supports all mainstream models (OpenAI, Anthropic, Gemini, etc.) using `litellm`.
- **AnthropicProvider**: Supported via delegation to LiteLLM.
- **MockLLMProvider**: Simulates streaming for local testing without API costs.

## Current Limitations

- **Tool Calls**: When an LLM triggers a tool call (function calling), the stream is currently buffered until the tool call is complete. This is because tools require the complete argument set to execute reliably.
- **JSON Mode**: If the model is in JSON mode, streaming still works, but the intermediate chunks will be partial JSON parts until completion.

## Testing with Mock Streaming

To test your UI or logic without hitting real APIs, use the `MockLLMProvider`. It split its mock response into words and yields them with a 50ms delay:

```bash
# Run your agent in mock mode
PYTHONPATH=core:exports python -m your_agent run --mock --input '{"key": "value"}'
```
