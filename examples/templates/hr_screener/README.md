# Automated HR Screener

**Version**: 1.0.0
**Type**: Multi-node agent template

## Overview

Screen PDF resumes against a job description, score and rank candidates 1–100, produce a plain text report, and optionally send response emails via [Resend](https://resend.com). All resume processing runs locally — applicant PII never leaves your machine unless you opt in to email notifications.

## Quick Start

### 1. Configure your LLM provider

Edit `~/.hive/configuration.json` with **any** supported provider:

```json
{
  "llm": {
    "provider": "<provider>",
    "model": "<model>"
  }
}
```

### 2. Set your API key

```bash
# Linux / macOS
export <PROVIDER>_API_KEY=your-key-here
export RESEND_API_KEY=your-key-here   # only if you want email notifications

# Windows CMD
set <PROVIDER>_API_KEY=your-key-here
set RESEND_API_KEY=your-key-here
```

### 3. Run

```bash
python -m examples.templates.hr_screener tui
```

The setup wizard will collect your job description, resume path, and email preference, then the pipeline runs automatically.

---

## Supported LLM Providers

This agent is built on [LiteLLM](https://docs.litellm.ai/) and works with **any provider** it supports. Below are tested configurations.

> [!TIP]
> Models with 70B+ parameters produce the best results for tool calling reliability.

### Cloud Providers

| Provider | Config `provider` | Config `model` | Env Var | Free Tier |
|----------|-------------------|----------------|---------|-----------|
| **Anthropic** | `anthropic` | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` | No |
| **Google Gemini** | `gemini` | `gemini-2.5-flash` | `GEMINI_API_KEY` | Yes |
| **Groq** | `groq` | `llama-3.3-70b-versatile` | `GROQ_API_KEY` | Yes |
| **HuggingFace** | `huggingface` | `meta-llama/Llama-3.3-70B-Instruct` | `HUGGINGFACE_API_KEY` | Limited |
| **Cerebras** | `cerebras` | `llama3.1-8b` | `CEREBRAS_API_KEY` | Yes |
| **DeepSeek** | `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` | Yes |
| **OpenRouter** | `openrouter` | `meta-llama/llama-3-8b-instruct:free` | `OPENROUTER_API_KEY` | Yes |
| **Together AI** | `together_ai` | `meta-llama/Llama-3-8b-chat-hf` | `TOGETHERAI_API_KEY` | Limited |

**Example — Anthropic Claude:**
```json
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514"
  }
}
```
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Example — Groq (Free, Fast):**
```json
{
  "llm": {
    "provider": "groq",
    "model": "llama-3.3-70b-versatile"
  }
}
```
```bash
export GROQ_API_KEY=gsk_...
```

### Local LLMs (Ollama) — Recommended for Privacy

Resumes contain heavy PII. Running local models ensures candidate data never leaves your machine.

1. Install [Ollama](https://ollama.com/)
2. Pull a model: `ollama pull qwen2.5:14b`
3. Configure:
```json
{
  "llm": {
    "provider": "ollama_chat",
    "model": "qwen2.5:14b",
    "api_base": "http://localhost:11434"
  }
}
```

No API key needed for local models.

---

## Architecture

### Pipeline Flow

```
intake → scan-resumes → rank-candidates → generate-report → notify-candidates
```

### Nodes (5 total)

| Node | Type | Client-Facing | Tools | Description |
|------|------|---------------|-------|-------------|
| **intake** | event_loop | No | — | Pass pre-collected inputs (job description, resume path, email pref) into the pipeline |
| **scan-resumes** | event_loop | No | `pdf_read`, `list_dir` | Read each PDF resume and extract text |
| **rank-candidates** | event_loop | No | — | Score candidates 0–100 against the job description |
| **generate-report** | event_loop | No | `save_data` | Write a plain text screening report |
| **notify-candidates** | event_loop | Yes | `send_email` | Send response emails (requires user approval) |

### Scoring Criteria

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Skills Match | 40% | Technical skills vs. job requirements |
| Experience | 25% | Level and type of relevant experience |
| Education | 15% | Degrees, certifications |
| Communication | 10% | Resume clarity and professionalism |
| Bonus Factors | 10% | Projects, leadership, publications |

---

## CLI Commands

```bash
# Interactive TUI dashboard (recommended)
python -m examples.templates.hr_screener tui

# Interactive CLI shell
python -m examples.templates.hr_screener shell

# Headless mode (outputs JSON)
python -m examples.templates.hr_screener run

# Show agent info
python -m examples.templates.hr_screener info

# Validate graph structure
python -m examples.templates.hr_screener validate
```

---

## Required Tools

These tools must be available via the MCP server configuration (`mcp_servers.json`):

- `pdf_read` — Extract text from PDF files
- `list_dir` — List directory contents
- `save_data` — Save report to file
- `send_email` — Send emails via Resend API

---

## Constraints

| Constraint | Type | Category |
|------------|------|----------|
| Never fabricate resume content or scores | Hard | Quality |
| Never transmit raw resume content externally | Hard | Privacy |
| Never send emails without user approval | Hard | Safety |
| Apply scoring criteria consistently | Hard | Quality |

---

## Version History

- **1.0.0** (2026-02-21): Initial release — 5 nodes, 4 edges, multi-provider LLM support, privacy-focused design
