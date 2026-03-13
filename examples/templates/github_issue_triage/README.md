# GitHub Issue Triage Agent

Automated issue classification and routing for GitHub repositories.

## What It Does

This agent monitors a GitHub repository for open issues and automatically:

1. **Fetches** un-triaged issues (filters out already-processed ones)
2. **Classifies** each issue: bug, enhancement, question, duplicate, invalid, or needs-triage
3. **Applies labels** via the GitHub API
4. **Posts triage comments** acknowledging the reporter and requesting missing info
5. **Sends notifications** to Slack and/or Discord with a triage summary

## Architecture

```
fetch_issues → triage → notify → (loop)
```

| Node | Tools Used | Purpose |
|------|-----------|---------|
| `fetch_issues` | `github_list_issues`, `github_get_issue`, `load_data`, `save_data` | Poll for new issues, skip already-triaged |
| `triage` | `github_update_issue`, `github_get_issue`, `load_data`, `save_data`, `append_data` | Classify, label, comment, persist triage state |
| `notify` | `slack_send_message`, `discord_send_message` | Send summary to team channels |

## Prerequisites

### Required Credentials

| Variable | Purpose | Get it at |
|----------|---------|-----------|
| `GITHUB_TOKEN` | GitHub API access (needs `repo` scope) | [github.com/settings/tokens](https://github.com/settings/tokens) |

### Optional Credentials

| Variable | Purpose | Get it at |
|----------|---------|-----------|
| `SLACK_BOT_TOKEN` | Send notifications to Slack | [api.slack.com/apps](https://api.slack.com/apps) |
| `DISCORD_BOT_TOKEN` | Send notifications to Discord | [discord.com/developers](https://discord.com/developers/applications) |

## Quick Start

```bash
# Set your GitHub token
export GITHUB_TOKEN=ghp_your_token_here

# Run once on a specific repo
PYTHONPATH=examples python -m github_issue_triage run --owner adenhq --repo hive

# Interactive shell
PYTHONPATH=examples python -m github_issue_triage shell

# Launch the TUI
PYTHONPATH=examples python -m github_issue_triage tui

# Validate agent structure
PYTHONPATH=examples python -m github_issue_triage validate

# Show agent info
PYTHONPATH=examples python -m github_issue_triage info --json
```

## Configuration

Edit `config.py` to customize:

```python
@dataclass
class AgentConfig:
    owner: str = ""                    # GitHub org or user
    repo: str = ""                     # Repository name
    slack_channel: str = "#eng-issues" # Slack notification channel
    discord_channel_id: str = ""       # Discord notification channel
    interval_minutes: int = 30         # Polling interval
    max_issues_per_run: int = 50       # Rate limit cap
    triage_label: str = "needs-triage" # Un-triaged issue marker
```

## Triage Categories

| Category | Label | Agent Action |
|----------|-------|-------------|
| Bug report | `bug` | Acknowledges, asks for repro steps if missing |
| Feature request | `enhancement` | Acknowledges, notes for team review |
| Question | `question` | Acknowledges, suggests docs |
| Duplicate | `duplicate` | References original, closes |
| Invalid | `invalid` | Explains why, closes |
| Needs more info | `needs-triage` | Asks for missing details |

## How Idempotency Works

The agent maintains `triaged_issues.json` in its data directory (`~/.hive/agents/github_issue_triage/`). Each processed issue number is appended to this list, so subsequent runs skip issues that have already been triaged.

## Entry Points

| Entry Point | Trigger | Use Case |
|-------------|---------|----------|
| `default` | Manual | `hive run` / `hive tui` |
| `timer` | Cron (30 min) | Continuous background monitoring |
| `webhook` | GitHub webhook | Instant triage on issue creation |

### Webhook Setup

To trigger the agent instantly when issues are created:

1. Set up a tunnel: `ngrok http 4001`
2. In your GitHub repo → Settings → Webhooks → Add webhook
3. Payload URL: `https://your-ngrok-url/webhook/issues`
4. Content type: `application/json`
5. Events: Select "Issues"
