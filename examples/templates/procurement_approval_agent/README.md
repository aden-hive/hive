# Procurement Approval Agent

Continuous procurement workflow agent with adaptive QuickBooks routing and first-run onboarding.

## Features

- First-run setup wizard (`setup-wizard`) to choose preferred sync mode
- Adaptive integration routing:
- API path when QuickBooks credentials exist
- CSV fallback path when credentials are missing
- Continuous monitoring mode for auto-trigger from JSON request files
- Optional background operation (`--daemon`) and launchd deployment on macOS
- Optional Slack/SMTP notifications on request completion

## Installation

From repository root (`/Users/vasu/Desktop/hive`):

```bash
export PYTHONPATH=core:examples/templates
export HIVE_AGENT_STORAGE_ROOT=/tmp/hive_agents
```

## Running Single Request (Mock)

```bash
python -m procurement_approval_agent run \
  --mock \
  --item "Laptop" \
  --cost 1200 \
  --department "engineering" \
  --requester "alice@company.com" \
  --justification "Need new laptop for ML development work"
```

## Real QuickBooks Credential Configuration

Set all three env vars to enable API mode:

```bash
export QUICKBOOKS_CLIENT_ID=...
export QUICKBOOKS_CLIENT_SECRET=...
export QUICKBOOKS_REALM_ID=...
export QUICKBOOKS_REFRESH_TOKEN=...
```

Hive v0.6 credential namespace support:
- You can reference stored credentials using `{name}/{alias}`.
- Example: `quickbooks/default`
- CLI/monitor flag: `--qb-credential-ref quickbooks/default`
- Env fallback: `QUICKBOOKS_CREDENTIAL_REF=quickbooks/default`
- Env vars above still work and take precedence if set.

Detection logic:
- If all vars exist -> `sync_method="api"`
- Else -> `sync_method="csv"`

Current template supports mock API sync + CSV fallback generation for safe testing.
For real API mode (`--no-mock-qb`), the refresh token is required and access tokens are cached at:
- `${HIVE_AGENT_STORAGE_ROOT}/procurement_approval_agent/quickbooks_token_cache.json`

## Adaptive Workflow

Flow:
1. `setup-wizard` (first run only)
2. `intake`
3. `budget-check`
4. `manager-approval` (when needed) and `vendor-check`
5. `po-generator`
6. `integration-setup-check` (client-facing yes/no)
7. `integration-check`
8. `pre-sync-confirmation` (client-facing yes/no)
9. Branch A: `quickbooks-sync`
10. Branch B: `csv-export`
11. `notifications`

Setup state is persisted at:
- `${HIVE_AGENT_STORAGE_ROOT}/procurement_approval_agent/setup_config.json`

## Continuous Monitoring (Auto-Trigger)

Watch for incoming request files and process forever:

```bash
python -m procurement_approval_agent monitor \
  --watch-dir /watched_requests \
  --poll-interval 2.0 \
  --mock
```

Duplicate guard:
- request fingerprint = `item + cost + department + requester`
- checked against last 24 hours
- duplicate requests are skipped with warning
- use `--force` to override

Runtime control flags:
- `--interactive` prompts per request:
- process now?
- API credentials available this run?
- proceed with final sync/export?
- `--sync-method api|csv` forces routing without prompts
- `--skip-process` exits early to `request-cancelled`
- `--sync-cancel` exits after PO to `sync-cancelled`
- `--qb-available yes|no` declares credential availability for this run
- `--qb-credential-ref quickbooks/default` resolves QuickBooks creds from Hive credential store

Request file format (`/watched_requests/*.json`):

```json
{
  "item": "Laptop",
  "cost": 1200,
  "department": "engineering",
  "requester": "alice@company.com",
  "justification": "Need new laptop for ML development work",
  "vendor": "TechSource LLC"
}
```

Folder behavior:
- New files: `/watched_requests/*.json`
- In-flight: `/watched_requests/processing/`
- Success archive: `/watched_requests/done/`
- Failure archive: `/watched_requests/failed/`
- Result JSON: `/watched_requests/results/<request>.result.json`

## Auto-Execution Hooks

After request completion:
- If API mode -> mock QuickBooks sync writes `data/qb_mock_responses.json`
- If CSV mode -> creates:
- `data/po/<PO>_qb_manual_import.csv`
- `data/po/<PO>_qb_import_instructions.md`

Optional file-manager reveal for CSV fallback:

```bash
python -m procurement_approval_agent monitor --watch-dir /watched_requests --mock --auto-open-csv
```

## Notifications

Slack (optional):
- Set `SLACK_WEBHOOK_URL`

SMTP email (optional):
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_TO`
- Optional auth: `SMTP_USERNAME`, `SMTP_PASSWORD`

## Background Service

### Daemon Mode

```bash
python -m procurement_approval_agent monitor \
  --watch-dir /watched_requests \
  --mock \
  --force \
  --daemon \
  --log-file /tmp/procurement_approval_agent_monitor.log
```

Reset setup wizard state:

```bash
python -m procurement_approval_agent reset-setup
```

### macOS launchd

Template files:
- `examples/templates/procurement_approval_agent/deploy/com.hive.procurement-approval-agent.plist`
- `examples/templates/procurement_approval_agent/deploy/install_launchd.sh`

Install:

```bash
bash examples/templates/procurement_approval_agent/deploy/install_launchd.sh
```

Or generate a custom plist:

```bash
python -m procurement_approval_agent write-launchd
```

## Demo Script

Run both adaptive paths end-to-end:

```bash
bash examples/templates/procurement_approval_agent/demo_workflows.sh
```

## Validation

```bash
python -m procurement_approval_agent validate
python -m procurement_approval_agent info
```

## Phase 2 (Planned)

- Metrics/observability pipeline (counters, latency, dashboards)
- Daemon hardening (PID files, health checks, stronger lifecycle management)
