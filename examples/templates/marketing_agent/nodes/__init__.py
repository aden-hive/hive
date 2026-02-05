"""Node definitions for Marketing Content Agent."""

from framework.graph import NodeSpec

# ---------------------------------------------------------------------------
# Node 1: Analyze the target audience
# ---------------------------------------------------------------------------
analyze_audience_node = NodeSpec(
    id="analyze-audience",
    name="Analyze Audience",
    description="Produce a structured audience analysis from the product and target audience description.",
    node_type="llm_generate",
    input_keys=["product_description", "target_audience"],
    output_keys=["audience_analysis"],
    system_prompt="""\
You are a marketing strategist. Analyze the target audience for a product.

Product: {product_description}
Target audience: {target_audience}

Produce a structured analysis as raw JSON (no markdown):
{{
  "audience_analysis": {{
    "demographics": "...",
    "pain_points": ["..."],
    "motivations": ["..."],
    "preferred_channels": ["..."],
    "messaging_angle": "..."
  }}
}}
""",
    tools=[],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 2: Generate channel-specific content with A/B variants
# ---------------------------------------------------------------------------
generate_content_node = NodeSpec(
    id="generate-content",
    name="Generate Content",
    description="Create marketing copy for each requested channel with two variants per channel.",
    node_type="llm_generate",
    input_keys=["product_description", "audience_analysis", "brand_voice", "channels"],
    output_keys=["content"],
    system_prompt="""\
You are a marketing copywriter. Generate content for each channel.

Product: {product_description}
Audience analysis: {audience_analysis}
Brand voice: {brand_voice}
Channels: {channels}

For each channel, produce two variants (A and B).

Output as raw JSON (no markdown):
{{
  "content": [
    {{
      "channel": "twitter",
      "variant_a": "...",
      "variant_b": "..."
    }}
  ]
}}
""",
    tools=[],
    max_retries=2,
)

# ---------------------------------------------------------------------------
# Node 3: Review and refine content
# ---------------------------------------------------------------------------
review_and_refine_node = NodeSpec(
    id="review-and-refine",
    name="Review and Refine",
    description="Review generated content for brand voice alignment and channel fit. Revise if needed.",
    node_type="llm_generate",
    input_keys=["content", "brand_voice"],
    output_keys=["content", "needs_revision"],
    system_prompt="""\
You are a senior marketing editor. Review the following content for brand
voice alignment, clarity, and channel appropriateness.

Content: {content}
Brand voice: {brand_voice}

If any piece needs revision, fix it and set needs_revision to true.
If everything looks good, return the content unchanged with needs_revision false.

Output as raw JSON (no markdown):
{{
  "content": [...],
  "needs_revision": false
}}
""",
    tools=[],
    max_retries=2,
)

# All nodes for easy import
all_nodes = [
    analyze_audience_node,
    generate_content_node,
    review_and_refine_node,
]
