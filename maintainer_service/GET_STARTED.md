## 🚦 Getting Started

To spin up the new agent, follow this execution order:

### 1. Backfill Historical Data
First, populate the Vector Memory with past issues so the agent has context.
```bash
# Run backfill for the last 7 days (or any custom range)
uv run python scripts/backfill.py --days 7
```
*   `--days`: Number of days to look back and ingest.

### 2. Start the Agent
Run the main service with custom scheduling intervals.
```bash
# Example: Check issues from the last 1 hours, running every 30 minutes
uv run python -m app.main --check 1 --schedule 0.5
```
OR using fractions:
```bash
# Check last 2 hours, run every 1 minute
uv run python -m app.main --check 2 --schedule 1/60
```
OR using hours as it is:
```bash
# Check last 24 hours, run every 24 hours (1 day)
uv run python -m app.main --check 24 --schedule 24
```

**CLI Variables Explained:**
*   `--check`: **Lookback Window (in hours)**. How far back in time the agent looks for "new" issues to analyze during each run.
*   `--schedule`: **Analysis Interval (in hours)**. How often the agent wakes up to perform its analysis loop. Supports decimals (`0.5` = 30m) or fractions (`1/60` = 1m).