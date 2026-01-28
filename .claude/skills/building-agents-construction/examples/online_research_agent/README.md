# Online Research Agent

Deep-dive research agent that searches 10+ sources and produces comprehensive narrative reports with citations.

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

```bash
# Show agent info
python -m online_research_agent info

# Validate structure
python -m online_research_agent validate

# Run research on a topic
python -m online_research_agent run --topic "impact of AI on healthcare"

# Interactive shell
python -m online_research_agent shell
```

### Python API

```python
from online_research_agent import default_agent

# Simple usage
result = await default_agent.run({"topic": "climate change solutions"})

# Check output
if result.success:
    print(f"Report saved to: {result.output['file_path']}")
    print(result.output['final_report'])
```

## Workflow

```
parse-query → search-sources → fetch-content → evaluate-sources
                                                      ↓
                                write-report ← synthesize-findings
                                      ↓
                               quality-check → save-report
```

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
- LLM provider API key (Groq, Cerebras, etc.)
- Internet access for web search/fetch

## Configuration

Edit `config.py` to change:

- `model`: LLM model (default: groq/moonshotai/kimi-k2-instruct-0905)
- `temperature`: Generation temperature (default: 0.7)
- `max_tokens`: Max tokens per response (default: 16384)
