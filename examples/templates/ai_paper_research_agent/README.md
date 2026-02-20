# AI Paper Research Agent

A template agent for deep research on difficult machine learning papers.

It is designed to help researchers process large, recent AI literature by:
- defining a clear research objective,
- discovering relevant papers,
- extracting technical insights from arXiv/paper pages and optional local PDFs,
- synthesizing cross-paper understanding,
- delivering a structured learning brief.

## Why This Template

This template directly implements the following requirements:
- Use Hive/Aden framework under `examples/templates/`
- Have an MCP client path for reading arXiv paper material (`web_scrape`, optional `pdf_read`)
- Have an MCP client path for academic-related search (`scholar_search`, `web_search`)
- Build an autonomous agent with explicit research objectives

## Architecture

Flow:

`intake -> discover-papers -> analyze-papers -> build-learning-brief -> deliver-brief`

### Node Summary

1. `intake` (client-facing)
- Clarifies scope and expected technical depth.
- Outputs: `research_objective`, `target_topics`, `difficulty_profile`

2. `discover-papers`
- Uses `scholar_search`, `web_search`, `web_scrape` to build candidate list.
- Outputs: `paper_candidates`, `selection_rationale`

3. `analyze-papers`
- Uses `web_scrape` and optional `pdf_read` (for local PDF paths) for deep extraction.
- Outputs: `paper_breakdowns`, `cross_paper_map`, `open_questions`

4. `build-learning-brief`
- Translates analysis into teachable technical understanding.
- Outputs: `teaching_note`, `study_plan`, `recommended_next_papers`

5. `deliver-brief` (client-facing)
- Writes and serves an HTML research brief.
- Uses `save_data`, `serve_file_to_user`
- Output: `delivery_status`

## Usage

### Linux / macOS

```bash
PYTHONPATH=core:examples/templates python -m ai_paper_research_agent run \
  --objective "Understand retrieval-augmented generation methods for long-context QA" \
  --paper-pdf ~/papers/paper1.pdf \
  --paper-pdf ~/papers/paper2.pdf
```

### Windows (PowerShell)

```powershell
$env:PYTHONPATH="core;examples\templates"
python -m ai_paper_research_agent run --objective "Understand diffusion model scaling laws"
```

## Commands

- `python -m ai_paper_research_agent info`
- `python -m ai_paper_research_agent validate`
- `python -m ai_paper_research_agent run --objective "..."`
- `python -m ai_paper_research_agent shell`

## Notes

- `scholar_search` requires SerpAPI credentials in your tools environment.
- `pdf_read` operates on local PDF paths. For online arXiv pages without local PDFs, the agent uses `web_scrape`.
