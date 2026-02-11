# Blog Writer Agent (Template)

A business-focused blog writing agent that researches sources, builds a strong thesis, drafts a post with citations, and publishes a Markdown artifact with SEO metadata. It demonstrates event-loop nodes, HITL checkpoints, and MCP tool integrations.

## What It Demonstrates
- Goal-driven agent design with success criteria and constraints
- Event-loop nodes for iterative, user-centered workflows
- Human-in-the-loop checkpoints (outline approval + quality gate)
- Web research via MCP tools (`web_search`, `web_scrape`)
- Artifact publishing via `save_data` + `serve_file_to_user`

## Flow
1. Intake (define audience, angle, CTA)
2. Research (web search + scrape)
3. Positioning (thesis + outline)
4. Outline Review (HITL approval)
5. Draft (business tone + citations)
6. SEO Optimize (title/meta/keywords)
7. Quality Gate (HITL approval or revisions)
8. Publish (save Markdown + metadata)

## How To Use

### Option 1: Build from template (recommended)
Use `/hive-create` and select this template.

### Option 2: Manual copy
```bash
cp -r examples/templates/blog_writer_agent exports/blog_writer_agent
```

Then run:
```bash
PYTHONPATH=exports uv run python -m blog_writer_agent --input '{"topic":"..."}'
```

## Required Tools
- web_search
- web_scrape
- save_data
- serve_file_to_user
- load_data
- list_data_files

## Notes
- This template is designed to show framework architecture patterns, not just output text.
- For best results, run with a business-focused LLM model and real API keys.
