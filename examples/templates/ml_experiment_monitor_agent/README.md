# ML Experiment Monitor Agent

Watches one or more MLflow experiments, flags any runs where `metrics.accuracy` dropped below a configurable threshold, and delivers a Slack alert — or an all-clear message — to a channel you specify.

## What problem it solves

Teams running continuous training pipelines often miss silent regressions: a new model version trains to completion, MLflow records a lower accuracy, but nobody notices until the model is already serving. This agent closes that gap by querying MLflow on demand and immediately routing the signal to Slack.

## Prerequisites

| Requirement | Notes |
|---|---|
| **MLflow Tracking Server** | Local (`http://localhost:5000`) or remote. Set `MLFLOW_TRACKING_URI` to override the default. |
| **MLFLOW_TRACKING_TOKEN** | Only required when your server has authentication enabled (e.g., Databricks). |
| **Slack Bot Token** | A Slack app with `chat:write` scope. Set `SLACK_BOT_TOKEN`. |
| **Slack Channel** | The channel name (`#ml-alerts`) or channel ID where notifications should be posted. |
| **ANTHROPIC_API_KEY** | Required for the LLM nodes. |

## How to run it

```bash
# 1. Set credentials
export MLFLOW_TRACKING_URI=http://your-mlflow-server:5000
export MLFLOW_TRACKING_TOKEN=your-token   # omit for unauthenticated servers
export SLACK_BOT_TOKEN=xoxb-your-bot-token
export ANTHROPIC_API_KEY=sk-ant-...

# 2. Copy the template into your workspace
cp -r examples/templates/ml_experiment_monitor_agent exports/my_monitor

# 3. Run the agent
cd exports
uv run python -m my_monitor run \
  --experiment-id 1 \
  --accuracy-threshold 0.85 \
  --slack-channel "#ml-alerts" \
  --max-results 20
```

### Input parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `experiment_id` | str | — | MLflow experiment ID to monitor (required) |
| `accuracy_threshold` | float | `0.8` | Minimum acceptable accuracy — runs below this trigger an alert |
| `max_results` | int | `50` | Maximum number of recent runs to inspect per execution |
| `slack_channel` | str | — | Slack channel name or ID for notifications (required) |

## Agent graph

```text
query_experiments  →  evaluate_results  →  send_alert
```

| Node | Purpose | Tools | Client-Facing |
|---|---|---|:---:|
| **query_experiments** | Calls `mlflow_list_runs` to fetch recent runs for the given experiment | `mlflow_list_runs` | |
| **evaluate_results** | LLM reads the runs, identifies those where `metrics.accuracy < threshold`, formats a summary | — | |
| **send_alert** | Posts the summary to Slack — alert with run details, or all-clear | `slack_send_message` | ✅ |

## Example output

**When a regression is detected:**

```text
🚨 MLflow Alert

The following runs in experiment #1 fell below the accuracy threshold of 0.85:

• run-abc123 (eager-hawk-42) — accuracy: 0.71 — status: FINISHED
• run-def456 (bold-eagle-7)  — accuracy: 0.79 — status: FINISHED

2 of 15 recent runs failed the threshold. Investigate before promoting to production.
```

**When all runs pass:**

```text
✅ MLflow OK

All 15 recent runs in experiment #1 met or exceeded the accuracy threshold of 0.85.
Highest: 0.97 (run-xyz789). No action needed.
```
