"""Node definitions for the Q&A Agent.

This module contains the node specifications that define the steps in the agent's graph.
"""

from framework.graph import NodeSpec

# Node for generating an answer to a question
generate_answer_node = NodeSpec(
    id="generate_answer",
    name="Generate Answer",
    description="Generates a clear and understandable answer to the user's question.",
    node_type="event_loop",
    client_facing=True,
    input_keys=["question"],
    output_keys=["answer"],
    system_prompt="""
You are a helpful and knowledgeable assistant.
Your goal is to answer the user's question as clearly and understandably as possible.
Avoid jargon unless necessary, and explain complex concepts simply.
Focus on providing a direct and accurate response.

Input:
The user's question will be in the `question` input key.

Output:
Provide the answer in the `answer` output key.
""",
    tools=[],
)

__all__ = [
    "generate_answer_node",
]
