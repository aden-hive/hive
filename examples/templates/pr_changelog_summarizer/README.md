# PR Changelog Summarizer

Summarize recent pull requests from a GitHub repository into a changelog or release notes document.

## Overview

This agent fetches PRs from a GitHub repo, summarizes them, and produces a formatted changelog (Markdown) that you can use for release notes or project documentation.

**Flow:** Intake → Fetch PRs → Generate Report

## Prerequisites

- **GitHub credentials**: The agent uses `github_list_pull_requests` and `github_get_pull_request`. Configure GitHub OAuth or a personal access token via:

  ```bash
  hive setup-credentials examples/templates/pr_changelog_summarizer
  ```

- **LLM API key**: For the LLM. Supports Anthropic, Groq, and others. See [Using Groq](#using-groq) below for free-tier setup.

## Usage

### TUI (Interactive)

```bash
cd /path/to/hive
PYTHONPATH=core uv run python -m examples.templates.pr_changelog_summarizer tui
```

Or via the main Hive TUI — select "PR Changelog Summarizer" from the Examples section.

### CLI

```bash
# Generate changelog for a repo
PYTHONPATH=core uv run python -m examples.templates.pr_changelog_summarizer run -r owner/repo

# Options
PYTHONPATH=core uv run python -m examples.templates.pr_changelog_summarizer run \
  -r https://github.com/owner/repo \
  -s closed \
  -l 30
```

### Validate

```bash
PYTHONPATH=core uv run python -m examples.templates.pr_changelog_summarizer validate
```

## Nodes

| Node   | Description                                      | Tools                                      |
|--------|--------------------------------------------------|--------------------------------------------|
| intake | Collect repo URL and optional PR scope           | —                                          |
| fetch  | List and fetch PR details from GitHub            | github_list_pull_requests, github_get_pull_request |
| report | Generate changelog and deliver file to user      | save_data, serve_file_to_user              |

## Output

The agent produces a `CHANGELOG.md` file with:

- Title and date
- PRs grouped by category (features, fixes, docs, etc.)
- Each entry: `- [#N] Title (by @author) — summary`
- Links to source PRs

## Using Groq

Groq offers a generous free tier with fast inference. To use it with this agent:

1. **Get an API key** from [https://console.groq.com](https://console.groq.com)
2. **Set the environment variable**:
   ```bash
   export GROQ_API_KEY="your-api-key"
   ```
3. **Run with Groq**:
   ```bash
   hive run examples/templates/pr_changelog_summarizer --model groq/llama-3.3-70b-versatile
   ```
   Or set it as your default in `~/.hive/configuration.json`:
   ```json
   {
     "llm": {
       "provider": "groq",
       "model": "llama-3.3-70b-versatile"
     }
   }
   ```

Recommended models: `groq/llama-3.3-70b-versatile`, `groq/llama-3.1-8b-instant`, `groq/mixtral-8x7b-32768`.

## Open Source Contribution

This agent is a simple, self-contained example suitable for:

- Learning the Hive agent framework
- Contributing a useful template to the ecosystem
- Extending with labels, date ranges, or custom formatting
