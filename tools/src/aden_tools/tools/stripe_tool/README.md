# Stripe Tool for Hive Framework

Production-ready Stripe payment processing and billing automation for Hive agents.

## Overview

The Stripe Tool provides comprehensive integration with the Stripe payment API, enabling automated billing operations, subscription management, payment processing, and customer relationship management through Hive agents.

## What It Does

This tool enables Hive agents to programmatically manage the complete billing lifecycle:

- **Customer Management**: Create, retrieve, update, and delete customer records. Search customers by email and manage contact information.
- **Subscription Lifecycle**: Handle subscription creation, updates, pauses, resumptions, and cancellations with support for trial periods.
- **Invoice Operations**: Generate, finalize, send, pay, and void invoices. Track invoice status and payment history.
- **Payment Processing**: Process one-time and recurring payments through payment intents, checkout sessions, and payment links.
- **Product Catalog**: Manage products and pricing models including one-time and recurring prices.
- **Refund Management**: Process full or partial refunds and track refund status.
- **Webhook Verification**: Securely verify and process Stripe webhook events.

## Use Cases

**Support Operations**: Automatically verify customer subscription status, process refund requests, and retrieve payment history.

**Sales Automation**: Generate instant payment links during conversations, create checkout sessions for prospects, and track conversions.

**Operations Management**: Send automated reminders for overdue invoices, manage failed payment retries, and handle subscription changes.

**Analytics & Reporting**: Calculate Monthly Recurring Revenue (MRR), track churn rates, analyze payment trends, and generate revenue reports.

## File Structure

```
tools/
├── src/
│   └── aden_tools/
│       ├── credentials/
│       │   ├── __init__.py                      # Registry of all credentials
│       │   └── stripe.py                        # Stripe API key specifications
│       │
│       └── tools/
│           ├── __init__.py                      # Tool registration
│           └── stripe_tool/
│               ├── __init__.py                  # Package exports
│               ├── stripe_tool.py               # Core implementation (1,500+ lines, 45+ methods)
│               ├── stripe_tool_registration.py  # FastMCP integration
│               └── README.md                    # This file
│
└── tests/
    └── tools/
        └── test_stripe_tool.py                  # Comprehensive test suite (51 tests)
```

## Configuration

Set the Stripe API key as an environment variable:

```bash
export STRIPE_API_KEY="sk_test_..."  # Development
export STRIPE_API_KEY="sk_live_..."  # Production
```

API keys can be obtained from https://dashboard.stripe.com/apikeys

## Capabilities

**45+ API Methods** covering:
- Customer CRUD operations
- Subscription lifecycle management
- Invoice creation and processing
- Payment intent handling
- Checkout session generation
- Product and price management
- Payment method operations
- Refund processing
- Webhook signature verification

**Production Features**:
- Comprehensive error handling with retry logic
- Full type safety with Pydantic validation
- Pagination support for large datasets
- Idempotency key handling
- Rate limit compliance

## Testing

The tool includes 51 comprehensive test cases covering all functionality with complete mocking of Stripe API calls.

Run tests: `pytest tools/tests/tools/test_stripe_tool.py -v`

## Security

- API keys stored in environment variables only
- Webhook signature verification enforced
- Support for separate test and live mode keys
- No sensitive data in code or version control

## Dependencies

- stripe (v11.0.0+)
- pydantic (v2.0.0+)

## Documentation

- Stripe API: https://stripe.com/docs/api
- Stripe Dashboard: https://dashboard.stripe.com

