# Issue Triage Agent

Template agent for cross-channel issue triage across GitHub issues, Discord, and Gmail.

## What It Does

- Collects candidate issue signals from GitHub issues, Discord channels, and Gmail.
- Deduplicates and classifies reports into triage clusters.
- Assigns severity/category with rationale and confidence.
- Applies routing actions:
  - Updates GitHub issue labels for triage status and severity.
  - Posts acknowledgment messages in Discord.
  - Creates Gmail draft replies for follow-up.
- Presents a final triage report to the operator.

## Usage

### Linux / Mac
```bash
PYTHONPATH=core:examples/templates uv run python -m issue_triage_agent run \
  --github-owner my-org \
  --github-repo my-repo \
  --discord-channel-ids 123456789012345678,234567890123456789 \
  --triage-policy "P0 for outages/security, P1 for user-facing regressions, otherwise P2/P3" \
  --lookback-hours 24
```

### Windows
```powershell
$env:PYTHONPATH="core;examples\templates"
uv run python -m issue_triage_agent run `
  --github-owner my-org `
  --github-repo my-repo `
  --discord-channel-ids 123456789012345678,234567890123456789 `
  --triage-policy "P0 for outages/security, P1 for user-facing regressions, otherwise P2/P3" `
  --lookback-hours 24
```

## Options

- `--github-owner`: GitHub owner/org.
- `--github-repo`: GitHub repo name.
- `--discord-channel-ids`: Comma-separated Discord channel IDs.
- `--triage-policy`: Free-text policy for severity and routing.
- `--lookback-hours`: How far back to inspect messages/issues (default `24`).
- `--gmail-query`: Optional Gmail query override.
- `--mock`: Use mock LLM mode.
