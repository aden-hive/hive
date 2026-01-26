# Support Ticket Agent

## Overview
The Support Ticket Handler processes incoming customer support tickets. It analyzes the content to determine the category and priority level using LLM generation.

## Goal
**Goal ID:** `support_ticket`
**Success Criteria:** Ticket is categorized, prioritized, and routed correctly.

## Architecture
This agent consists of a single node:
- **Analyze Ticket:** Extracts category (billing/tech/account) and priority (high/medium/low).

## Usage
To validate the agent structure and logic:
```bash
python -m exports.support_ticket_agent validate