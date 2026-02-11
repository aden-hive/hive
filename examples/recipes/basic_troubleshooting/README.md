# Recipe: Basic Troubleshooting

Handling "Level 1" tech support for your platform or website.

## Why

Most support tickets are the same 20 questions over and over: password resets, access issues, "how do I..." questions. You don't need to answer these — but someone does. This agent handles the repetitive tier-1 support so your users get fast answers and you get your time back.

## What

- Handle password resets and account access issues
- Answer common "how do I" questions from the knowledge base
- Walk users through basic setup and configuration
- Collect diagnostic information for complex issues
- Log all support interactions for pattern analysis

## Integrations

| Platform | Purpose |
|----------|---------|
| Intercom / Zendesk / Freshdesk | Support ticket management |
| Notion / Confluence | Knowledge base for answers |
| Slack | Internal escalation channel |
| Your product's API | Account status, password reset triggers |
| LogRocket / FullStory | Session replay for debugging |
| PagerDuty | Urgent escalation routing |

## Escalation Path

| Trigger | Action |
|---------|--------|
| Issue not resolved within 30 minutes | Escalate with full context gathered |
| User expresses frustration or anger | Immediate handoff to human with de-escalation note |
| Security-related issue (account compromise, data concern) | Escalate immediately, do not attempt to resolve |
| Bug discovered during troubleshooting | Create ticket and escalate to engineering |
| VIP or enterprise customer | Flag for priority handling regardless of issue |
| Same issue reported by 3+ users | Alert as potential systemic problem |
