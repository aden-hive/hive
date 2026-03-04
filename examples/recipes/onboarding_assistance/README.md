# Recipe: Onboarding Assistance

Helping new clients set up their accounts or sending out "Welcome" kits.

## Why

First impressions stick. A smooth onboarding experience sets the tone for the entire customer relationship — but walking each new client through setup manually does not scale.

An onboarding assistant automates guidance, reminders, and follow-ups while escalating issues to humans only when necessary.

## What

- Send personalized welcome emails and kits
- Guide clients through account setup step-by-step
- Answer common "getting started" questions
- Track onboarding completion and milestone progress
- Follow up on incomplete setups

## Integrations

| Platform | Purpose |
|----------|---------|
| Intercom / Customer.io | Onboarding email sequences |
| Notion / Loom | Tutorial content and documentation |
| Calendly | Onboarding call scheduling |
| Slack / Email | Progress updates and escalations |
| Your product's API | Track setup completion status |
| Typeform / Tally | Onboarding surveys and data collection |

## Escalation Path

| Trigger | Action |
|---------|--------|
| Client stuck on setup >48 hours | Alert with where they're stuck and offer to schedule a call |
| Technical blocker during setup | Route to support with context already gathered |
| High-value client starts onboarding | Notify so you can send a personal welcome |
| Client expresses frustration | Immediate flag for human intervention |
| Onboarding incomplete after 7 days | Escalate with churn risk assessment |

---

# Example Agents

## Vendor Onboarding Policy Agent

A **policy-aware vendor onboarding workflow** demonstrating how Hive-style agents can automate compliance-heavy onboarding processes.

Instead of a simple automation, this example models a **real business workflow** with validation, risk scoring, deterministic rules, and human escalation.

### Capabilities

- Validate vendor onboarding requests from structured JSON
- Classify vendor type (software, consultant, data provider, etc.)
- Run a deterministic compliance checklist
- Compute vendor risk scores with explanations
- Route decisions automatically:
  - `approved`
  - `needs_more_info`
  - `human_review`
- Escalate high-risk vendors to **human-in-the-loop review**
- Produce a final **structured decision with a full audit trail**

### Example Location
examples/recipes/onboarding_assistance/vendor_onboarding_policy/


### Demo Scenarios

| Scenario | Result |
|--------|--------|
| Low-risk vendor | Approved |
| Missing documents | Needs more information |
| High-risk jurisdiction | Human review → Reject |

### What This Demonstrates

This example highlights Hive’s strengths for real-world business workflows:

- branching decision graphs
- deterministic guardrails
- auditable decision trails
- human-in-the-loop escalation
- structured outputs suitable for downstream systems
