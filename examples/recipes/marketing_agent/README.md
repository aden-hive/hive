# Recipe: Marketing Content Agent

A multi-channel marketing content generator. Given a product description and target audience, this agent analyzes the audience, generates tailored copy for multiple channels, and produces A/B variants.

## Goal

```
Name:        Marketing Content Generator
Description: Generate targeted marketing content across multiple channels
             for a given product and audience.

Success criteria:
  - Audience analysis is produced with demographics and pain points
  - At least 2 channel-specific content pieces are generated
  - A/B variants are provided for each piece
  - All content aligns with the specified brand voice

Constraints:
  - (hard) No competitor brand names in generated content
  - (soft) Content should be under 280 characters for social media channels
```

## Input / Output

**Input:**
- `product_description` (str) — What the product is and does
- `target_audience` (str) — Who the content is for
- `brand_voice` (str) — Tone and style guidelines (e.g., "professional but approachable")
- `channels` (list[str]) — Target channels, e.g. `["email", "twitter", "linkedin"]`

**Output:**
- `audience_analysis` (dict) — Demographics, pain points, motivations
- `content` (list[dict]) — Per-channel content with A/B variants

## Workflow

```
[analyze_audience] → [generate_content] → [review_and_refine]
                                               |
                                          (conditional)
                                               |
                              needs_revision == True → [generate_content]
                              needs_revision == False → (done)
```

## Nodes

### 1. analyze_audience

| Field | Value |
|-------|-------|
| Type | `llm_generate` |
| Input keys | `product_description`, `target_audience` |
| Output keys | `audience_analysis` |
| Tools | None |

**System prompt:**
```
You are a marketing strategist. Analyze the target audience for a product.

Product: {product_description}
Target audience: {target_audience}

Produce a structured analysis in JSON:
{{
  "audience_analysis": {{
    "demographics": "...",
    "pain_points": ["..."],
    "motivations": ["..."],
    "preferred_channels": ["..."],
    "messaging_angle": "..."
  }}
}}
```

### 2. generate_content

| Field | Value |
|-------|-------|
| Type | `llm_generate` |
| Input keys | `product_description`, `audience_analysis`, `brand_voice`, `channels` |
| Output keys | `content` |
| Tools | None |

**System prompt:**
```
You are a marketing copywriter. Generate content for each channel.

Product: {product_description}
Audience analysis: {audience_analysis}
Brand voice: {brand_voice}
Channels: {channels}

For each channel, produce two variants (A and B).

Output as JSON:
{{
  "content": [
    {{
      "channel": "twitter",
      "variant_a": "...",
      "variant_b": "..."
    }}
  ]
}}
```

### 3. review_and_refine

| Field | Value |
|-------|-------|
| Type | `llm_generate` |
| Input keys | `content`, `brand_voice` |
| Output keys | `content`, `needs_revision` |
| Tools | None |

**System prompt:**
```
You are a senior marketing editor. Review the following content for brand
voice alignment, clarity, and channel appropriateness.

Content: {content}
Brand voice: {brand_voice}

If any piece needs revision, fix it and set needs_revision to true.
If everything looks good, return the content unchanged with needs_revision false.

Output as JSON:
{{
  "content": [...],
  "needs_revision": false
}}
```

## Edges

| Source | Target | Condition | Priority |
|--------|--------|-----------|----------|
| analyze_audience | generate_content | `on_success` | 0 |
| generate_content | review_and_refine | `on_success` | 0 |
| review_and_refine | generate_content | `conditional: needs_revision == True` | 10 |

The `review_and_refine → generate_content` loop has higher priority so it's checked first. If `needs_revision` is false, execution ends at `review_and_refine` (terminal node).

## Tools

This recipe uses no external tools — all nodes are `llm_generate`. To extend it, consider adding:
- A web search tool for competitive analysis in the `analyze_audience` node
- A URL shortener tool for social media content
- An image generation tool for visual content variants

## Variations

- **Single-channel mode**: Remove the `channels` input and hardcode to one channel for simpler output
- **With approval gate**: Add a `human_input` node between `review_and_refine` and the terminal to require human sign-off
- **With analytics**: Add a `function` node that logs generated content to a tracking system
