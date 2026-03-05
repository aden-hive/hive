# Lead Qualification Agent

Automatically scores, enriches, and routes inbound leads based on Ideal Customer Profile (ICP) criteria — eliminating manual triage and ensuring hot leads never slip through the cracks.

## Overview

This agent handles the complete lead qualification workflow:
1. **Intake** — Receives lead data (name, email, company, role)
2. **Enrichment** — Looks up company details via web search (industry, size, funding, location)
3. **Scoring** — Scores lead 0-100 based on configurable ICP criteria
4. **Routing** — Routes to appropriate pipeline based on score
5. **Output** — Logs final decision and updates CRM

## Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LEAD QUALIFICATION AGENT                                 │
│                                                                             │
│  Goal: Score, enrich, and route inbound leads based on ICP criteria        │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌───────────────────────┐
    │       INTAKE          │
    │  (client-facing)      │
    │                       │
    │  in:  lead_data       │
    │  out: lead_brief      │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │     ENRICHMENT        │
    │                       │
    │  tools: web_search,   │
    │         web_scrape    │
    │                       │
    │  in:  lead_brief      │
    │  out: enriched_lead   │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │       SCORING         │
    │                       │
    │  in:  enriched_lead   │
    │  out: score,          │
    │       score_breakdown │
    └───────────┬───────────┘
                │ on_success
                ▼
    ┌───────────────────────┐
    │  ROUTING_DECISION     │
    │                       │
    │  in:  score           │
    │  out: route           │
    └───────┬───────┬───────┘
            │       │
    score>=70│       │score 40-69
            │       │
            ▼       ▼
    ┌───────────┐ ┌───────────┐
    │ HOT_LEAD  │ │  REVIEW   │ (client-facing)
    │           │ │           │
    │ tools:    │ │ in: score │
    │ hubspot   │ │ out:      │
    │           │ │ override  │
    └─────┬─────┘ └─────┬─────┘
          │             │
          │    ┌────────┴────────┐
          │    │                 │
          │  hot│               nurture
          │    │                 │
          │    ▼                 ▼
          │  ┌───────────┐ ┌───────────┐
          │  │ HOT_LEAD  │ │  NURTURE  │
          │  │ (again)   │ │           │
          │  └─────┬─────┘ │ tools:    │
          │        │       │ hubspot   │
          │        │       └─────┬─────┘
          │        │             │
          │        ▼             ▼
          │      ┌───────────────────┐
          └─────►│      OUTPUT       │
                 │  (client-facing)  │
                 │                   │
                 │ out: final_status │
                 └─────────┬─────────┘
                           │
                           │ loops to INTAKE
                           ▼

    EDGES:
    ──────
    1. intake → enrichment              [on_success, priority: 1]
    2. enrichment → scoring            [on_success, priority: 1]
    3. scoring → routing_decision      [on_success, priority: 1]
    4. routing_decision → hot_lead     [conditional: route == 'hot', priority: 3]
    5. routing_decision → review       [conditional: route == 'review', priority: 2]
    6. routing_decision → nurture      [conditional: route == 'nurture', priority: 1]
    7. hot_lead → output               [on_success, priority: 1]
    8. review → hot_lead               [conditional: override_route == 'hot', priority: 2]
    9. review → nurture                [conditional: override_route == 'nurture', priority: 1]
    10. nurture → output               [on_success, priority: 1]
    11. output → intake                [conditional: qualification_complete, priority: 1]
```

## ICP Scoring Framework

The agent uses a configurable ICP scoring framework:

| Category | Max Points | Criteria |
|----------|------------|----------|
| Industry Fit | 25 | SaaS/Software (25), Tech Services (20), Finance/Healthcare (15), Other B2B (10) |
| Company Size | 25 | 10-200 employees (25), 200-500 (20), 500-1000 (15), <10 or >1000 (5-10) |
| Role Seniority | 25 | C-level/VP (25), Director (20), Manager (15), IC (5-10) |
| Role Relevance | 25 | Engineering/Product (25), Operations/IT (20), Sales/Marketing (10-15) |

**Modifiers:** +5 for recent funding, +5 for target geography, -10 for bad fit signals

## Routing Thresholds

- **Score >= 70**: Hot Lead → Immediate SDR follow-up
- **Score 40-69**: Review → Human-in-the-loop review before routing
- **Score < 40**: Nurture → Automated email sequence

## Usage

### CLI Commands

```bash
# Validate agent structure
PYTHONPATH=exports uv run python -m lead_qualification_agent validate

# Show agent info
PYTHONPATH=exports uv run python -m lead_qualification_agent info

# Run with lead data
PYTHONPATH=exports uv run python -m lead_qualification_agent run \
  --name "Jane Smith" \
  --email "jane@techstartup.io" \
  --company "TechStartup Inc" \
  --role "VP of Engineering"

# Interactive shell
PYTHONPATH=exports uv run python -m lead_qualification_agent shell

# Launch TUI (deprecated - use hive open instead)
PYTHONPATH=exports uv run python -m lead_qualification_agent tui
```

### Browser Interface (Recommended)

```bash
# Start the browser-based interface
hive open

# Then select "Lead Qualification Agent" from the agent list
```

## Requirements

### Credentials

The agent requires the following credentials:

1. **LLM API Key** — Set via `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
2. **HubSpot Access Token** — Set via `HUBSPOT_ACCESS_TOKEN` or configure via credential store

```bash
# Set up credentials
/hive-credentials --agent lead_qualification_agent
```

### MCP Tools

The agent uses these tools from the Hive tools MCP server:
- `web_search` — For company enrichment
- `web_scrape` — For fetching company information
- `hubspot_search_contacts` — Find existing contacts
- `hubspot_create_contact` — Create new contacts
- `hubspot_update_contact` — Update contact with routing tags
- `hubspot_create_company` — Create company records
- `hubspot_update_company` — Update company data

## Success Criteria

1. ✅ Lead is enriched with firmographic data from web search
2. ✅ Lead score is calculated with clear ICP-based breakdown
3. ✅ Lead is routed to correct pipeline based on score
4. ✅ Lead data is written to CRM with routing tags
5. ✅ Agent runs end-to-end in under 30 seconds per lead

## Target Users

- B2B SaaS founders and sales teams
- Growth/RevOps teams managing HubSpot or similar CRMs
- SDRs who want to focus on closing, not triaging

## Related

- Issue: #5700 — Lead Qualification Agent — Score, Enrich, and Route Inbound Leads
- HubSpot Integration: #2848 (completed)
- Related recipes: `crm_update`, `inquiry_triaging`
