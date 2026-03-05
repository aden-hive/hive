# SaaS Renewal & Upsell Agent

Proactive revenue expansion through usage intelligence. Monitor subscription data, classify accounts by opportunity type, draft personalized outreach for account manager review, and generate NRR reports.

## Overview

This agent helps SaaS companies maximize Net Revenue Retention (NRR) by:

1. **Monitoring subscription data** for upcoming renewals and usage patterns
2. **Classifying accounts** into three categories:
   - **Renewal Risk**: Contract expiring soon with declining usage
   - **Expansion Ready**: High usage, near limits, primed for upsell
   - **Healthy/Monitor**: Stable, no immediate action needed
3. **Drafting personalized outreach** emails for account manager review
4. **Generating NRR digest reports** with actionable recommendations

## Key Features

- **Data-driven classification**: Uses configurable thresholds for renewal windows, usage drops, and seat utilization
- **Personalized email drafting**: References specific usage stats, plan details, and upgrade benefits
- **Human-in-the-loop approval**: All outreach requires explicit account manager approval before sending
- **Comprehensive reporting**: Weekly NRR digest with risk analysis, expansion pipeline, and recommendations

## Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AGENT: SaaS Renewal & Upsell Agent                       │
│                                                                             │
│  Goal: Maximize NRR through proactive renewal and upsell outreach          │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌───────────────────────┐
    │       INTAKE          │
    │  (client-facing)      │
    │                       │
    │  in:  -               │
    │  out: data_source_    │
    │       config,         │
    │       analysis_config │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │     DATA_LOAD         │
    │                       │
    │  tools: csv_read,     │
    │         excel_read    │
    │                       │
    │  in:  data_source_    │
    │       config          │
    │  out: subscription_   │
    │       data, usage_    │
    │       data            │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │     CLASSIFY          │
    │                       │
    │  in:  subscription,   │
    │       usage, config   │
    │  out: classified_     │
    │       accounts        │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │     PLAYBOOK          │
    │                       │
    │  in:  classified_     │
    │       accounts        │
    │  out: playbook_       │
    │       assignments     │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │       DRAFT           │
    │                       │
    │  in:  accounts,       │
    │       playbooks,      │
    │       data            │
    │  out: email_drafts    │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │       REVIEW          │
    │  (client-facing)      │
    │                       │
    │  in:  drafts, summary │
    │  out: approved_drafts │
    │       OR feedback     │
    └───────┬───────┬───────┘
            │       │
   approved │       │ feedback
            │       │
            ▼       └──────────────────┐
    ┌───────────────────────┐          │
    │     SEND_LOG          │          │
    │                       │          │
    │  in:  approved_drafts │          │
    │  out: outreach_log    │          │
    └───────────┬───────────┘          │
                │                      │
                ▼                      │
    ┌───────────────────────┐          │
    │       DIGEST          │          │
    │  (client-facing)      │          │
    │                       │          │
    │  in:  classification, │          │
    │       send_summary    │          │
    │  out: nrr_report,     │          │
    │       next_action     │          │
    └───────┬───────────────┘          │
            │                          │
            └──────────────────────────┘
              (loops back to CLASSIFY or INTAKE)
```

## Installation

```bash
# Ensure you're in the hive project directory
cd /path/to/hive

# The agent is available at exports/saas_renewal_agent/
```

## Usage

### Via TUI (Recommended)

```bash
# Start the Hive TUI
hive tui

# Select "SaaS Renewal & Upsell Agent" from the agent list
```

### Via CLI

```bash
# Validate the agent structure
cd core && PYTHONPATH=../exports uv run python -m saas_renewal_agent validate

# Get agent info
cd core && PYTHONPATH=../exports uv run python -m saas_renewal_agent info

# Run with data files
cd core && PYTHONPATH=../exports uv run python -m saas_renewal_agent run \
  --subscription-file /path/to/subscriptions.csv \
  --usage-file /path/to/usage.csv
```

### Interactive Shell

```bash
cd core && PYTHONPATH=../exports uv run python -m saas_renewal_agent shell
```

## Data Requirements

### Subscription Data (CSV or Excel)

Required columns:
| Column | Description |
|--------|-------------|
| `account_id` | Unique account identifier |
| `plan_tier` | Current subscription tier |
| `mrr` or `arr` | Monthly/Annual Recurring Revenue |
| `contract_start` | Contract start date |
| `contract_end` | Contract end date |
| `account_manager` | Assigned account manager |
| `billing_status` | Payment status (active, past_due, etc.) |

### Usage Data (CSV or Excel)

Required columns:
| Column | Description |
|--------|-------------|
| `account_id` | Unique account identifier (matches subscription) |
| `active_users` | Number of active users |
| `feature_adoption_rate` | Percentage of features used (0-100) |
| `session_frequency` | Login frequency (per week/month) |
| `api_call_volume` | API usage count |
| `seat_utilization` | Percentage of seats used (0-100) |

## Classification Rules

### Renewal Risk (High Priority)
- Contract ends within 60 days (configurable)
- AND usage is declining (>20% drop, configurable)
- OR billing_status is past_due

### Expansion Ready (Medium Priority)
- Seat utilization >80% (configurable)
- OR feature adoption rate >80%
- OR API call volume trending up
- AND contract not expiring within 30 days

### Healthy/Monitor (Low Priority)
- All other accounts
- Stable usage patterns
- No immediate action required

## Playbook Types

1. **renewal_save_play**: Urgent tone, focus on value, address concerns, offer incentives
2. **upsell_pitch_play**: Celebrate success, present upgrade benefits, offer expansion discount
3. **checkin_play**: Warm touchpoint, request feedback, share resources

## Success Criteria

| Criterion | Target | Weight |
|-----------|--------|--------|
| Data loaded and validated | 100% | 15% |
| Accounts classified | 100% | 20% |
| Drafts generated | >=1 | 20% |
| User approval | Required | 25% |
| NRR report generated | Required | 20% |

## Constraints

- **Human approval required**: No outreach without explicit approval
- **Data privacy**: Subscription data handled securely
- **Accurate classification**: Based on actual data, not assumptions
- **Personalized outreach**: Account-specific customization required

## Configuration

Default thresholds can be customized:
- `renewal_window_days`: 60 (accounts expiring within this window are flagged)
- `usage_drop_threshold`: 20% (usage decline percentage for risk flagging)
- `seat_utilization_trigger`: 80% (seat usage percentage for upsell trigger)

## Output Files

The agent generates:
- `outreach_log.csv`: Log of all approved outreach messages
- `nrr_digest_report.html`: Comprehensive NRR report with recommendations
- Draft emails ready for email system integration

## Integration Notes

This agent prepares messages for sending but does not send emails directly. To send emails:

1. Export the `approved_drafts` output
2. Integrate with your email provider (Gmail, Outlook, SendGrid, etc.)
3. Use the email subject and body from each draft

## License

Part of the Hive framework. See main repository for license details.
