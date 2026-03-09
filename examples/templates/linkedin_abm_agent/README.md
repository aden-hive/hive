# LinkedIn ABM Agent

Multi-Channel Account-Based Marketing automation for Hive.

## Overview

This agent orchestrates complete ABM campaigns across LinkedIn, email, and direct mail channels. It Features:

- LinkedIn profile scraping and validation
- Apollo.io data enrichment (email, phone)
- Skip Trace for mailing addresses
- Personalized message generation
- Human-in-the-loop approval workflow
- Multi-channel outreach execution
- Campaign tracking and reporting

## Use Case

B2B sales teams running Account-Based Marketing campaigns:

### Before
- Manual prospecting is 10-20 hours per campaign
- Data scattered across LinkedIn, Apollo, Email, and Direct Mail platforms
- Error-prone with data sync issues

### After
- 10x faster campaign execution
- $1,500+ cost savings per 100-lead campaign
- Automated data validation

## Features

- **LinkedIn Prospecting**: Scrape profiles from URLs or Sales Navigator
- **Data Enrichment**: Email, phone via Apollo; mailing address via Skip Trace
- **Message Generation**: Personalized templates for email, LinkedIn, direct mail
- **Human Approval**: Review messages before sending
- **Multi-Channel Outreach**: Coordinated timing (Day 1, 3, 7)
- **Campaign Tracking**: Export reports and track outcomes

## Prerequisites

### Required API Keys
- `APOLLO_API_KEY` - Get from [Apollo.io](https://app.apollo.io/#/settings/integrations/api)
- `LINKEDIN_COOKIE` - Session cookie from browser DevTools (li_at value)
- `SCRIBELESS_API_KEY` - Get from [Scribeless](https://scribeless.org/dashboard/api)
- `SKIPTRACE_API_KEY` - Get from [Skip Trace](https://skiptrace.io) (optional)

### Optional
- `SMTP credentials` for email sending (configure in email tool)

- CRM integration (HubSpot, Salesforce) for tracking

## Quick Start

1. Configure credentials:
   ```bash
   hive credentials add apollo
   hive credentials add scribeless
   hive credentials add skiptrace
   ```

2. Run the agent:
   ```bash
   cd core
   hive run examples/templates/linkedin_abm_agent
   ```

3. Interact with the agent through the TUI:
   ```bash
   hive open
   ```

## Architecture

The agent follows a 7-node pipeline:

```
intake -> prospect -> enrich -> message -> review -> outreach -> tracking
                      |                              +-- feedback loop
                      |                              +-- restart cycle
```

### Nodes

1. **intake** - Accept LinkedIn URLs, clarify campaign goals
2. **prospect** - Scrape LinkedIn profiles, validate criteria
3. **enrich** - Enrich with Apollo and Skip Trace
4. **message** - Generate personalized messages
5. **review** - Human approval checkpoint
6. **outreach** - Execute multi-channel outreach
7. **tracking** - Track outcomes, export reports

### Edges

- `intake -> prospect`
- `prospect -> enrich`
- `enrich -> message`
- `message -> review`
- `review -> message` (feedback loop if not approved)
- `review -> outreach` (if approved)
- `outreach -> tracking`
- `tracking -> intake` (start new campaign)

## Configuration

Edit `examples/templates/linkedin_abm_agent/config.py` to customize behavior.
Edit `examples/templates/linkedin_abm_agent/nodes/__init__.py` to modify node prompts or desired.
Edit `examples/templates/linkedin_abm_agent/agent.py` to adjust success criteria and edge conditions.

