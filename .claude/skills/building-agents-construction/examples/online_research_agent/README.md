# Online Research Agent

Deep-dive research agent that searches 10+ sources and produces comprehensive narrative reports with citations.

> **Note:** This is a reference example located in `.claude/skills/building-agents-construction/examples/online_research_agent/`. 
> To run this agent, either:
> 1. Copy it to `exports/online_research_agent/` (recommended for production use)
> 2. Or use the alternative PYTHONPATH shown in Option 2 below
> 
> **Prerequisite:** Ensure `PYTHONPATH` includes `core:exports` (set in your environment or shell profile).

## Features

- Generates multiple search queries from a topic
- Searches and fetches 15+ web sources
- Evaluates and ranks sources by relevance
- Synthesizes findings into themes
- Writes narrative report with numbered citations
- Quality checks for uncited claims
- Saves report to local markdown file

## Usage

### CLI

**Option 1: Copy to exports/ (Recommended)**

```bash
# First, ensure dependencies are installed
./scripts/setup-python.sh

# Copy the example to exports directory (creates exports/online_research_agent/)
cp -r .claude/skills/building-agents-construction/examples/online_research_agent exports/

# Option A: Set PYTHONPATH and run (recommended)
export PYTHONPATH="core:exports"
python3 -m online_research_agent info
python3 -m online_research_agent validate

# Run with API key (requires GROQ_API_KEY environment variable)
python3 -m online_research_agent run --topic "impact of AI on healthcare"

# Or test in mock mode (no API key needed)
python3 -m online_research_agent run --topic "impact of AI on healthcare" --mock

# Option B: Use helper script (no PYTHONPATH needed)
./exports/online_research_agent/run.sh info
./exports/online_research_agent/run.sh validate
./exports/online_research_agent/run.sh run --topic "impact of AI on healthcare"

# Option C: Inline PYTHONPATH (one-time use)
PYTHONPATH=core:exports python3 -m online_research_agent info
```

**Troubleshooting:** 
- **"No module named online_research_agent"**: Set PYTHONPATH first: `export PYTHONPATH="core:exports"` (or use the quick fix command below)
- **"No module named 'pydantic'"**: Run `./scripts/setup-python.sh` first to install dependencies
- **"Invalid API Key"**: Set your API key: `export GROQ_API_KEY="your-key"` or use `--mock` flag for testing
- **Verify structure**: `ls exports/online_research_agent/` should show `__init__.py`, `__main__.py`, `agent.py`, etc.

**Option 2: Run from examples directory**

```bash
# From project root, include examples directory in PYTHONPATH
PYTHONPATH=core:exports:.claude/skills/building-agents-construction/examples python3 -m online_research_agent info
PYTHONPATH=core:exports:.claude/skills/building-agents-construction/examples python3 -m online_research_agent validate
PYTHONPATH=core:exports:.claude/skills/building-agents-construction/examples python3 -m online_research_agent run --topic "impact of AI on healthcare"
```

**Note:** If you see "No module named online_research_agent", you need to set PYTHONPATH. See Option 1 above for solutions.

**CLI Options:**
- `--topic, -t`: Research topic (required)
- `--mock`: Run in mock mode (no LLM calls, no API key needed) - **Use this for testing!**
- `--quiet, -q`: Only output result JSON
- `--verbose, -v`: Show execution details
- `--debug`: Show debug logging

**Important:** 
- For real execution, you need a valid `GROQ_API_KEY` environment variable
- Use `--mock` flag to test the agent structure without API calls
- Mock mode simulates LLM responses for testing purposes

### Python API

**If copied to exports/:**

```python
from exports.online_research_agent import default_agent

# Simple usage
result = await default_agent.run({"topic": "climate change solutions"})

# Check output
if result.success:
    print(f"Report saved to: {result.output['file_path']}")
    print(result.output['final_report'])

# Advanced usage with AgentRuntime
from exports.online_research_agent import OnlineResearchAgent

agent = OnlineResearchAgent()
await agent.start()
try:
    result = await agent.trigger_and_wait("start", {"topic": "AI trends"})
    if result and result.success:
        print(result.output)
finally:
    await agent.stop()
```

**If running from examples directory, adjust import path accordingly.**

## Workflow

The agent follows a linear 8-node workflow:

```
parse-query → search-sources → fetch-content → evaluate-sources
                                                      ↓
                                write-report ← synthesize-findings
                                      ↓
                               quality-check → save-report
```

**Node Details:**
1. **parse-query**: Analyzes topic and generates 3-5 search queries
2. **search-sources**: Executes web searches to find 15+ source URLs
3. **fetch-content**: Fetches and extracts content from URLs
4. **evaluate-sources**: Scores and ranks sources, selects top 10
5. **synthesize-findings**: Extracts key facts and identifies themes
6. **write-report**: Generates narrative report with citations
7. **quality-check**: Verifies all claims have citations
8. **save-report**: Writes final report to markdown file

## Output

Reports are saved to `./research_reports/` as markdown files with:

1. Executive Summary
2. Introduction
3. Key Findings (by theme)
4. Analysis
5. Conclusion
6. References

## Requirements

- Python 3.11+
- **LLM provider API key** (Groq recommended) - set `GROQ_API_KEY` environment variable
- Internet access for web search/fetch
- MCP server configured (see `mcp_servers.json`)

**Get API Key:**
- Groq: https://console.groq.com/ (free tier available)

## Setup

1. **Install dependencies:**
   ```bash
   ./scripts/setup-python.sh
   ```

2. **Set PYTHONPATH:**

   **Quick fix (current session only):**
   ```bash
   # From project root
   export PYTHONPATH="core:exports"
   python3 -m online_research_agent info
   ```

   **For virtualenv (recommended):**
   ```bash
   # Activate venv and set PYTHONPATH
   source venv/bin/activate
   export PYTHONPATH="core:exports"
   
   # Or add to venv activation script (permanent for this venv):
   echo 'export PYTHONPATH="core:exports"' >> venv/bin/activate
   ```

   **For permanent setup (add to `~/.zshrc` or `~/.bashrc`):**
   ```bash
   # Add these lines (adjust path to your project root)
   export PYTHONPATH="${PYTHONPATH}:/Users/yourname/hive/core:/Users/yourname/hive/exports"
   export GROQ_API_KEY="your-groq-api-key-here"  # Optional: set API key permanently
   ```

3. **Configure API key:**

   The agent uses Groq by default (configured in `config.py`). Set your API key:
   ```bash
   export GROQ_API_KEY="your-groq-api-key-here"
   ```
   
   **Get a Groq API key:**
   - Sign up at https://console.groq.com/
   - Create an API key
   - Copy and export it
   
   **Verify your API key is set:**
   ```bash
   echo $GROQ_API_KEY  # Should show your key (first few characters)
   ```

   **Alternative LLM providers:**
   ```bash
   # Use Anthropic instead of Groq
   export ANTHROPIC_API_KEY="your-key-here"
   # Then edit config.py to change model to "anthropic/claude-3-5-sonnet-20241022"
   ```

   **Security Note:** Never commit API keys to git. Consider using a `.env` file or your shell profile (`~/.zshrc` or `~/.bashrc`) for permanent setup.

   **Test without API keys (mock mode):**
   ```bash
   python3 -m online_research_agent run --topic "test" --mock
   ```

4. **MCP Server:** The agent uses `mcp_servers.json` to configure the hive-tools MCP server for web search, web scraping, and file operations.

## Configuration

Edit `config.py` to change:

- `model`: LLM model (default: `groq/moonshotai/kimi-k2-instruct-0905`)
- `temperature`: Generation temperature (default: `0.7`)
- `max_tokens`: Max tokens per response (default: `16384`)

The agent uses `AgentRuntime` with multi-entrypoint support and pause/resume capabilities. MCP servers are configured via `mcp_servers.json`.
