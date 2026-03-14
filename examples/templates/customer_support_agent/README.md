# Customer Support Agent

An autonomous agent that classifies customer queries, generates empathetic replies, and logs support tickets automatically.

## Built by
https://github.com/yakshmakadia

## Flow
intake → classify → reply → log-and-close

| Node | Purpose | Client-Facing |
|------|---------|:---:|
| **intake** | Collect user's support query | ✓ |
| **classify** | Classify into Billing/Shipping/Technical/General | |
| **reply** | Generate empathetic reply | |
| **log-and-close** | Save ticket and show reply to user | ✓ |

## Quick Start
cd examples/templates
uv run python -m customer_support_agent shell

## Categories Supported
- Billing — charge disputes, invoices, refunds
- Shipping — delivery issues, missing orders, tracking
- Technical — bugs, crashes, app issues
- General — policies, hours, general questions