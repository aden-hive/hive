"""Node definitions for RSS-to-Twitter Agent - simple function nodes."""

from framework.graph import NodeSpec

fetch_node = NodeSpec(
    id="fetch",
    name="Fetch RSS",
    description="Fetch and parse RSS feeds",
    node_type="function",
    client_facing=False,
    input_keys=[],
    output_keys=["articles_json"],
)

process_node = NodeSpec(
    id="process",
    name="Summarize",
    description="Summarize articles into key points",
    node_type="function",
    client_facing=False,
    input_keys=["articles_json"],
    output_keys=["processed_json"],
)

generate_node = NodeSpec(
    id="generate",
    name="Generate Tweets",
    description="Generate tweet drafts",
    node_type="function",
    client_facing=False,
    input_keys=["processed_json"],
    output_keys=["threads_json"],
)

approve_node = NodeSpec(
    id="approve",
    name="Approve Threads",
    description="Show threads and get user approval",
    node_type="function",
    client_facing=False,
    input_keys=["threads_json"],
    output_keys=["approved_json"],
)

post_node = NodeSpec(
    id="post",
    name="Post to Twitter",
    description="Post approved threads via Playwright",
    node_type="function",
    client_facing=False,
    input_keys=["approved_json"],
    output_keys=["results_json"],
)

__all__ = [
    "fetch_node",
    "process_node",
    "generate_node",
    "approve_node",
    "post_node",
]
