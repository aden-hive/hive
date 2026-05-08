"""Node definitions for the OpenRouter agent.

Follows the exact same pattern as credential_tester/nodes/__init__.py:
- build_chat_node() returns a NodeSpec (declarative only)
- The framework's EventLoopNode drives the actual LLM call
- Tools are declared here; conversation history is managed by the framework
- System prompt includes memory injection from session_memory.py

Features wired in via NodeSpec:
  Feature 3: web_search, read_file, write_file in tools list
  Feature 4: system prompt structured for note-taking + task decomposition skills
  Feature 1: memory injected via format_for_injection() in system prompt
"""

from __future__ import annotations

from framework.graph import NodeSpec

from .session_memory import format_for_injection

# System prompt template


_SYSTEM_PROMPT_TEMPLATE = """\
You are a helpful AI assistant running on a free open-source model via OpenRouter.

{memory_block}

# Your capabilities

You can:
- Answer questions clearly and accurately
- Help with analysis, writing, and coding tasks
- Search the web for current information (use the web_search tool)
- Read files the user provides (use the read_file tool)
- Write output to files when asked (use the write_file tool)

# How to handle tasks

For multi-step tasks:
1. Use _working_notes to track your progress (maintained by hive.note-taking skill)
2. Break complex requests into clear steps before executing
3. Confirm with the user before making any writes or destructive actions

# Rules

- Be concise unless depth is explicitly requested
- If you don't know something, say so — then search for it
- Never fabricate facts; use web_search to verify
- No emojis
"""


def build_chat_node(memory: bool = True) -> NodeSpec:
    """Build the main chat NodeSpec.

    Args:
        memory: If True, inject session memory into the system prompt.
                Set to False in tests to avoid reading ~/.hive files.

    Returns:
        NodeSpec with web search, file tools, and memory in system prompt.
    """
    memory_block = format_for_injection() if memory else ""

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        memory_block=memory_block,
    ).strip()

    return NodeSpec(
        id="chat",
        name="OpenRouter Chat",
        description=(
            "General-purpose chat node powered by a free open-source model. "
            "Has web search, file read/write, and persistent session memory."
        ),
        node_type="event_loop",
        client_facing=True,
        max_node_visits=0,  # 0 = unlimited (continuous conversation)
        input_keys=[],
        output_keys=["response"],
        nullable_output_keys=["response"],
        tools=[
            # Feature 3: web search + file tools (same as queen's shared tool set)
            "web_search",
            "read_file",
            "write_file",
        ],
        system_prompt=system_prompt,
    )
