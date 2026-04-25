# Sales Ops Agent

An automated sales territory rebalancing agent for [Hive](https://github.com/aden-hive/hive).

Runs monthly on the 1st to analyze sales performance metrics, detect under-allocated territories, and rebalance accounts from unassigned pools to ensure fair opportunity distribution across the sales team.

## Overview

The Sales Ops Agent automates territory management:

```
Trigger → Monitor → Analyze → Rebalance → Log
```

1. **Trigger** — Check if today is the 1st of the month
2. **Monitor** — Fetch sales data from CRM (reps, accounts, pipeline, unassigned pool)
3. **Analyze** — Compute coverage metrics and flag reps with <20% untouched accounts
4. **Rebalance** — Reassign accounts from unassigned pool to under-allocated reps
5. **Log** — Update CRM and present summary report

## Quickstart

```bash
cd examples/templates/sales_ops_agent

# Run with Demo mode (mock data, no CRM required)
python -m sales_ops_agent run --crm-type demo

# Run with Salesforce (requires SALESFORCE_ACCESS_TOKEN)
python -m sales_ops_agent run --crm-type salesforce

# Run with HubSpot (requires HUBSPOT_ACCESS_TOKEN)
python -m sales_ops_agent run --crm-type hubspot

# Run for a specific date (testing)
python -m sales_ops_agent run --crm-type demo --date 2026-04-01

# Validate agent structure
python -m sales_ops_agent validate

# Interactive TUI
python -m sales_ops_agent tui

# Interactive shell
python -m sales_ops_agent shell --crm-type demo
```

## Demo Mode

The agent includes a **demo mode** that uses mock data instead of requiring a live CRM connection. This is useful for:

- Testing the agent logic without external dependencies
- Demonstrating the workflow
- Development and debugging

```bash
python -m sales_ops_agent run --crm-type demo
```

Demo mode uses `demo_data.json` which contains:
- 4 sales representatives with varying metrics
- 10 unassigned accounts across different territories
- Realistic pipeline and win rate data

Demo output:
- Sales data written to `demo_sales_reps.jsonl`
- Unassigned accounts written to `demo_unassigned_accounts.jsonl`
- Rebalance actions logged to `demo_rebalance_log.jsonl`

## Configuration

The agent supports CRM selection via the `--crm-type` flag:

| CRM | Value | Required Credentials |
|-----|-------|---------------------|
| Demo (mock data) | `demo` | None (uses local `demo_data.json`) |
| Salesforce | `salesforce` | `SALESFORCE_ACCESS_TOKEN`, `SALESFORCE_INSTANCE_URL` |
| HubSpot | `hubspot` | `HUBSPOT_ACCESS_TOKEN` |

### Setting Up Credentials

**Demo Mode:** No credentials required - uses mock data from `demo_data.json`.

**Salesforce:** Set environment variables:
```bash
export SALESFORCE_ACCESS_TOKEN="your_token_here"
export SALESFORCE_INSTANCE_URL="https://yourinstance.my.salesforce.com"
```

**HubSpot:** Set environment variable:
```bash
export HUBSPOT_ACCESS_TOKEN="your_token_here"
```

Or use the Hive credential store (`~/.hive/credentials.json`) to manage credentials securely.

## Metrics Calculated

Per sales representative:

| Metric | Formula | Purpose |
|--------|---------|---------|
| `untouched_ratio` | `untouched_accounts / total_accounts` | Detect territory exhaustion |
| `win_rate` | `won_deals / total_deals` | Prioritize struggling reps |
| `pipeline_size` | `sum(open_deal_amounts)` | Prioritize low pipeline reps |

## Rebalancing Logic

A sales rep is flagged for rebalancing when:
- `untouched_ratio < 0.20` (less than 20% of accounts remain untouched)

Rebalancing priority:
1. Lowest `pipeline_size` first
2. Lowest `win_rate` as tiebreaker

Territory constraints:
- Accounts only reassigned within matching territory/region
- No duplicate assignments
- Max 50 accounts per rebalance cycle

## Data Flow

```
current_date
    ↓
trigger → is_first_of_month, month_year
    ↓
monitor → sales_data.jsonl, unassigned_pool.jsonl
    ↓
analyze → rep_analysis.jsonl, rebalance_candidates.jsonl
    ↓
rebalance → rebalance_actions.jsonl
    ↓
log → summary_report (presented to user)
```

## Files Written to Session

Each run writes to `~/.hive/agents/sales_ops_agent/data/`:

| File | Contents |
|------|----------|
| `sales_data.jsonl` | Reps with accounts, metrics, pipeline data |
| `unassigned_pool.jsonl` | Available unassigned accounts |
| `rep_analysis.jsonl` | All reps with calculated metrics |
| `rebalance_candidates.jsonl` | Flagged reps needing accounts |
| `rebalance_actions.jsonl` | Actions taken (account reassignments) |

## Edge Cases Handled

| Edge Case | Behavior |
|-----------|----------|
| Not the 1st of month | Agent exits early after trigger check |
| No unassigned accounts | Logs "No unassigned accounts available" |
| No matching territory accounts | Skips rep, logs incompatibility |
| Rep at capacity | Skips rep, logs capacity message |
| Zero accounts (division by zero) | Sets metric to "N/A", skips rep |
| CRM connection failure | Halts execution, returns error |
| Partial rebalancing | Documents partial success in summary |

## Constraints

- **Respect Territory:** Accounts only reassigned within matching territories
- **No Duplicates:** Same account never assigned to multiple reps
- **Audit Trail:** All reassignments logged to CRM
- **First of Month:** Rebalancing only on the 1st (soft constraint)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Sales Ops Agent                         │
│                                                               │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐      │
│  │ Trigger │──▶│ Monitor │──▶│ Analyze │──▶│Rebalance│      │
│  └─────────┘   └─────────┘   └─────────┘   └────┬────┘      │
│                                                  │           │
│                                                  ▼           │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐     │
│  │         │◀──│         │◀──│         │◀──│   Log   │     │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘     │
│                                                               │
│  ● client_facing node: log                                    │
│  ● automated nodes: trigger, monitor, analyze, rebalance     │
└─────────────────────────────────────────────────────────────┘
```

## Scheduled Execution

The agent includes a monthly trigger configured in `triggers.json`:

```json
{
  "id": "monthly-sales-ops-rebalance",
  "name": "Monthly Sales Territory Rebalance",
  "trigger_type": "timer",
  "trigger_config": {
    "cron": "0 9 1 * *"
  },
  "task": "Run on the 1st of each month at 9 AM"
}
```

## Tools Required

**Salesforce:**
- `salesforce_soql_query` — Fetch users, accounts, opportunities
- `salesforce_update_record` — Reassign account ownership
- `salesforce_create_record` — Log rebalance actions

**HubSpot:**
- `hubspot_search_contacts` — Find sales reps
- `hubspot_search_companies` — Fetch companies and owners
- `hubspot_search_deals` — Get pipeline data
- `hubspot_update_company` — Reassign ownership
- `hubspot_create_deal` — Create audit trail

**Data Management:**
- `load_data` — Read JSONL data files
- `append_data` — Write to JSONL data files

## CRM Logging

### Salesforce

Account ownership update:
```python
salesforce_update_record(
    object_type="Account",
    record_id="<account_id>",
    fields={"OwnerId": "<rep_id>", "Territory_Assigned_Date__c": "<timestamp>"}
)
```

Audit log creation:
```python
salesforce_create_record(
    object_type="Rebalance_Log__c",
    fields={
        "Date__c": "<timestamp>",
        "Action_Type__c": "Territory_Rebalance",
        "Affected_Accounts__c": <count>,
        "New_Owner__c": "<rep_id>"
    }
)
```

### HubSpot

Company ownership update:
```python
hubspot_update_company(
    object_id="<company_id>",
    properties={
        "hubspot_owner_id": "<rep_id>",
        "territory_assigned_date": "<timestamp>"
    }
)
```

Audit deal creation:
```python
hubspot_create_deal(
    properties={
        "dealname": "Territory Rebalance - <month_year>",
        "amount": "0",
        "dealstage": "closedwon",
        "rebalance_type": "territory_adjustment"
    }
)
```

## Inspiration

This template is inspired by real-world sales operations automation patterns, including:
- Territory health monitoring
- Fair opportunity distribution
- Audit trail compliance
- Multi-CRM support (Salesforce, HubSpot)
