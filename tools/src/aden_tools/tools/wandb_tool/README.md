# Weights & Biases Tool

Query ML experiment runs, metrics, and artifacts from Weights & Biases using the W&B GraphQL API.

## Tools

| Tool | Description |
|------|-------------|
| `wandb_list_projects` | List all projects for a W&B entity (user or organization) |
| `wandb_list_runs` | List runs in a project with optional filters |
| `wandb_get_run` | Get full details of a specific run (config, state, summary) |
| `wandb_get_run_metrics` | Get sampled metric history for a run |
| `wandb_list_artifacts` | List output artifacts logged by a run |
| `wandb_get_summary` | Get final summary metrics for a run |

## Setup

Requires a W&B account and API key.

1. Create a W&B account at [wandb.ai](https://wandb.ai)
2. Get your API key at [wandb.ai/authorize](https://wandb.ai/authorize)
3. Set the environment variable:

```bash
export WANDB_API_KEY=your-api-key
```

Or configure via the Aden credential store as `wandb_api_key`.

## Usage Examples

### List projects for an entity

```python
wandb_list_projects(entity="my-team")
```

### List recent runs in a project

```python
wandb_list_runs(entity="my-team", project="my-project", per_page=10)
```

### Filter runs by state

```python
wandb_list_runs(
    entity="my-team",
    project="my-project",
    filters='{"state": "finished"}',
)
```

### Get details of a specific run

```python
wandb_get_run(entity="my-team", project="my-project", run_id="abc123")
```

### Get training metrics for a run

```python
wandb_get_run_metrics(
    entity="my-team",
    project="my-project",
    run_id="abc123",
    metric_keys="loss,accuracy",
)
```

### Get final summary metrics

```python
wandb_get_summary(entity="my-team", project="my-project", run_id="abc123")
```

### List artifacts produced by a run

```python
wandb_list_artifacts(entity="my-team", project="my-project", run_id="abc123")
```

## Error Handling

All tools return error dicts on failure:

```python
{"error": "Weights & Biases credentials not configured", "help": "Set WANDB_API_KEY..."}
{"error": "Invalid Weights & Biases API key"}
{"error": "Weights & Biases resource not found"}
{"error": "Request timed out"}
{"error": "filters must be a valid JSON string"}
{"error": "metric_keys is required (comma-separated, e.g. 'loss,accuracy')"}
```
