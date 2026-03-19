# SDR Agent

An AI-powered sales development outreach automation template for [Hive](https://github.com/aden-hive/hive).

Score contacts by priority, filter suspicious profiles, generate personalized messages, and create Gmail drafts — all with human review before anything is sent.

## Overview

The SDR Agent automates the full outreach pipeline:

```
Intake → Score Contacts → Filter Contacts → Personalize → Send Outreach → Report
```

1. **Intake** — Accept a contact list and outreach goal; confirm strategy with user
2. **Score Contacts** — Rank contacts 0–100 using priority factors (alumni, degree, domain, etc.)
3. **Filter Contacts** — Detect and skip suspicious/fake profiles (risk score ≥ 7)
4. **Personalize** — Generate an 80–120 word personalized message per contact
5. **Send Outreach** — Create Gmail drafts for human review (never sends automatically)
6. **Report** — Summarize campaign: contacts scored, filtered, drafted

## Quickstart

```bash
cd examples/templates/sdr_agent

# Run interactively via TUI
python -m sdr_agent tui

# Run via CLI with a contacts JSON string
python -m sdr_agent run \
  --contacts '[{"name":"Jane Doe","company":"Acme","title":"Engineer","connection_degree":"2nd","is_alumni":true}]' \
  --goal "coffee chat" \
  --background "Learning Technologist at UWO" \
  --max-contacts 20

# Validate agent structure
python -m sdr_agent validate
```

## Contact Schema

Each contact in your list supports the following fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Contact's full name |
| `email` | string | ❌ | Email address (draft placeholder if missing) |
| `company` | string | ✅ | Current company |
| `title` | string | ✅ | Job title |
| `linkedin_url` | string | ❌ | LinkedIn profile URL |
| `connection_degree` | string | ❌ | `"1st"`, `"2nd"`, or `"3rd"` |
| `is_alumni` | boolean | ❌ | Shares school with user |
| `school_name` | string | ❌ | School name for alumni messaging |
| `connections_count` | integer | ❌ | Number of LinkedIn connections |
| `mutual_connections` | integer | ❌ | Count of mutual connections |
| `has_photo` | boolean | ❌ | Has a profile photo |

## Scoring Model

The `score-contacts` node ranks each contact 0–100:

| Factor | Points |
|--------|--------|
| Alumni | +30 |
| 1st degree | +25 |
| 2nd degree | +20 |
| 3rd degree | +10 |
| Domain verified | +10 |
| Mutual connections (×1, max 10) | +10 |
| Active job posting | +10 |
| Has profile photo | +5 |
| 500+ connections | +5 |

## Scam Detection

The `filter-contacts` node calculates a risk score and excludes contacts with risk ≥ 7:

| Red Flag | Risk |
|----------|------|
| Fewer than 50 connections | +3 |
| No profile photo | +2 |
| Fewer than 2 work positions | +2 |
| Generic title + few connections | +2 |
| Unverifiable company | +2 |
| AI-generated-looking profile | +2 |
| 5000+ connections, 0 mutual | +1 |

## Pipeline Output Files

Each run writes to `~/.hive/agents/sdr_agent/data/`:

| File | Contents |
|------|----------|
| `contacts.jsonl` | Raw contact list |
| `scored_contacts.jsonl` | Contacts with `priority_score` |
| `safe_contacts.jsonl` | Contacts passing scam filter |
| `personalized_contacts.jsonl` | Contacts with `outreach_message` |
| `drafts.jsonl` | Draft creation records |

## Safety Constraints

- **Never sends emails** — only `gmail_create_draft` is called; human must review and send
- **Batch limit** — processes at most `max_contacts` per run (default: 20)
- **Skip suspicious** — contacts with `risk_score ≥ 7` are always excluded

## Tools Required

- `gmail_create_draft` — create Gmail draft for each contact
- `load_data` — read JSONL data files
- `append_data` — write to JSONL data files

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        SDR Agent                             │
│                                                              │
│  ┌────────┐   ┌───────────────┐   ┌────────────────┐        │
│  │ Intake │──▶│ Score Contacts│──▶│ Filter Contacts│        │
│  └────────┘   └───────────────┘   └────────────────┘        │
│       ▲                                    │                 │
│       │                                    ▼                 │
│  ┌────────┐   ┌───────────────┐   ┌─────────────┐           │
│  │ Report │◀──│ Send Outreach │◀──│ Personalize │           │
│  └────────┘   └───────────────┘   └─────────────┘           │
│                                                              │
│  ● client_facing nodes: intake, report                       │
│  ● automated nodes: score-contacts, filter-contacts,         │
│                     personalize, send-outreach               │
└──────────────────────────────────────────────────────────────┘
```

## Inspiration

This template is inspired by real-world SDR automation patterns, including contact ranking, scam detection, and two-step personalization (hook extraction → message generation) — demonstrating how job-search and sales outreach workflows can be modeled as AI agent pipelines in Hive.
