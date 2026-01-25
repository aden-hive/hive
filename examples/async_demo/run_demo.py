"""
Async Demo Agent Runner - Demonstrates parallel execution capabilities.
Uses a MockLLMProvider to run without requiring API keys.
"""

import asyncio
import sys
from pathlib import Path

# Add core to path
sys.path.append(str(Path(__file__).parent.parent.parent / "core"))

from framework.runner.runner import AgentRunner
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolUse, ToolResult


class MockLLMProvider(LLMProvider):
    """Mock LLM provider that simulates responses for demo purposes."""
    
    def complete(
        self,
        messages: list,
        system: str = "",
        tools: list = None,
        max_tokens: int = 1024,
        response_format: dict = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Return a mock response based on the context."""
        last_msg = messages[-1]["content"] if messages else ""
        
        # Simulate different responses based on node context
        if "topic" in last_msg.lower() or "research" in last_msg.lower():
            content = '{"topic_list": ["Physics", "Biology", "Chemistry"]}'
        elif "aggregate" in last_msg.lower() or "combine" in last_msg.lower():
            content = '{"final_report": "Combined analysis of all topics completed successfully."}'
        else:
            content = '{"result": "Mock LLM response for demo"}'
        
        return LLMResponse(
            content=content,
            model="mock-model",
            input_tokens=10,
            output_tokens=20,
        )
    
    def complete_with_tools(
        self,
        messages: list,
        system: str,
        tools: list,
        tool_executor: callable,
        max_iterations: int = 10,
    ) -> LLMResponse:
        """Execute tools and return mock response."""
        # Simulate calling each registered tool once
        results = []
        for tool in tools[:3]:  # Limit to 3 for demo
            tool_use = ToolUse(
                id=f"call_{tool.name}",
                name=tool.name,
                input={"topic": f"Topic for {tool.name}", "duration_ms": 500}
            )
            result = tool_executor(tool_use)
            results.append(result.content)
        
        return LLMResponse(
            content=f'{{"results": {results}}}',
            model="mock-model",
            input_tokens=50,
            output_tokens=100,
        )


async def main():
    agent_path = Path(__file__).parent
    print(f"Loading agent from {agent_path}...")
    
    # Create runner with mock LLM
    runner = AgentRunner.load(agent_path, mock_mode=True)
    
    # Inject our mock LLM provider
    runner._llm = MockLLMProvider()
    
    # Force setup to use our mock LLM
    runner._setup()
    runner._executor._llm = runner._llm
    
    print("Starting concurrent execution with MockLLM...")
    result = await runner.run({
        "topic_list": "Physics, Biology, Chemistry"
    })
    
    print("\n" + "="*50)
    print("EXECUTION COMPLETE")
    print("="*50)
    print(f"Success: {result.success}")
    print(f"Total Latency: {result.total_latency_ms}ms")
    print(f"Steps Executed: {result.steps_executed}")
    print(f"Path: {' -> '.join(result.path)}")
    print(f"Output: {result.output}")

if __name__ == "__main__":
    asyncio.run(main())
