# Blog Writer Agent

SEO-optimized blog post generator that researches topics, creates structured outlines, and produces polished markdown posts with citations.

## Features

- Analyzes topics for keywords, angles, and audience
- Researches 5+ web sources for authoritative content
- Creates structured outlines with H2/H3 sections
- Writes 1500-3000 word blog posts with inline citations
- Optimizes for SEO (meta description, keyword headers, tags)
- Quality checks for citations, readability, and accuracy
- Saves polished markdown with YAML frontmatter

## Usage

### CLI

```bash
# Show agent info
python -m blog_writer_agent info

# Validate structure
python -m blog_writer_agent validate

# Write a blog post
python -m blog_writer_agent run --topic "benefits of remote work in 2026"

# Interactive shell
python -m blog_writer_agent shell
```

### Python API

```python
from blog_writer_agent import default_agent

# Simple usage
result = await default_agent.run({"topic": "how to build a REST API with Python"})

# Check output
if result.success:
    print(f"Blog saved to: {result.output['file_path']}")
    print(result.output['final_content'])
```

## Workflow

```
analyze-topic → research-topic → fetch-sources → create-outline
                                                       ↓
                                  seo-optimize ← write-draft
                                       ↓
                                 quality-check → save-blog
```

## Output

Blog posts are saved to `./blog_posts/` as markdown files with:

- YAML frontmatter (title, description, date, tags, author)
- SEO-optimized title and headers
- Well-structured body with citations
- References section

## Requirements

- Python 3.11+
- LLM provider API key (Anthropic, Groq, Cerebras, etc.)
- Internet access for web search/scrape

## Configuration

Edit `config.py` to change:

- `model`: LLM model (default: loads from `~/.hive/configuration.json`)
- `temperature`: Generation temperature (default: 0.7)
- `max_tokens`: Max tokens per response (default: 8192)
