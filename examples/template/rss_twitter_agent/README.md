# RSS-to-Twitter Agent

Automatically turns Hacker News RSS articles into engaging Twitter threads using a **free local LLM** (Ollama). No paid APIs, no Twitter developer account required.

## Overview

The agent fetches the latest articles from Hacker News, uses Ollama (llama3.1:8b running locally on your machine) to summarize and generate engaging tweet threads, then lets you approve and auto-post each thread one at a time via Playwright browser automation.

## Features

- 📡 **RSS fetching** — pulls latest articles from Hacker News
- 🧠 **Free local LLM** — uses Ollama (llama3.1:8b), no API keys needed
- 🐦 **Thread generation** — hooks, numbered points, hashtags, and CTAs
- ✅ **Interactive approval** — review and approve one thread at a time
- 🤖 **Auto-posting** — Playwright posts directly to Twitter (login once, reuse session)

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai) installed
- `llama3.1:8b` model pulled
- Playwright Chromium browser

## Installation

```bash
# 1. Install Ollama (macOS)
brew install ollama

# 2. Start Ollama server
ollama serve

# 3. Pull the model (in a new terminal, ~4.7 GB one-time download)
ollama pull llama3.1:8b

# 4. Install Playwright browser
python -m playwright install chromium
```

## Usage

From the root of the `hive` repo:

```bash
PYTHONPATH=core python examples/template/rss_twitter_agent/run.py
```

Other commands:

```bash
# Validate agent structure
PYTHONPATH=core python -m examples.template.rss_twitter_agent validate

# Show agent info
PYTHONPATH=core python -m examples.template.rss_twitter_agent info
```

## How It Works

For each article, the agent runs this loop:

```
Fetch RSS → Summarize all articles
  └─ For each article:
       Generate thread → Show thread → Ask "Post? (y/n/q)"
         └─ If yes: Post via Playwright → "Press Enter for next..."
```

1. Fetches the latest 3 articles from Hacker News RSS
2. Summarizes all articles (hook, key points, hashtags) in one Ollama call
3. For each article — generates a 4-tweet thread, displays it, asks for approval
4. If approved — posts immediately via Playwright, then waits before moving on
5. Repeats for the next article

## First Run (Twitter Login)

On the very first run, a browser window opens so you can log in to Twitter manually:

1. Browser opens → log in to X/Twitter
2. Press **Enter** in the terminal when done
3. Session saved to `~/.hive/twitter_session/`
4. All future runs log in automatically — no manual steps

To force a re-login:
```bash
rm -rf ~/.hive/twitter_session/
```

## Configuration

Edit `config.py` to change LLM settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `model` | `ollama/llama3.1:8b` | Ollama model to use |
| `temperature` | `0.7` | Creativity (0 = deterministic, 1 = creative) |
| `max_tokens` | `8000` | Max output length |

To change the RSS feed, edit `fetch_rss()` in `fetch.py`:
```python
url = "https://news.ycombinator.com/rss"  # change this
```

## Session Storage

| Path | `~/.hive/twitter_session/` |
|------|---------------------------|
| Created | First run after manual login |
| Reused | All subsequent runs automatically |
| Reset | `rm -rf ~/.hive/twitter_session/` |

## Troubleshooting

**"Ollama is not running"**
```bash
ollama serve
```

**"Model not found"**
```bash
ollama pull llama3.1:8b
```

**Twitter login issues / session expired**
```bash
rm -rf ~/.hive/twitter_session/
PYTHONPATH=core python examples/template/rss_twitter_agent/run.py
```

**Tweet over 280 characters**  
The approval step shows a ⚠️ warning. Skip that thread or the LLM will vary on the next run.
