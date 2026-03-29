# Razorpay Tool

Integration with Razorpay for payment processing, invoicing, and refund management.

## Overview

This tool enables Hive agents to interact with Razorpay's payment infrastructure for:
- Listing and filtering payments
- Fetching payment details
- Creating payment links
- Managing invoices
- Processing refunds

## Available Tools

This integration provides 6 MCP tools for comprehensive payment operations:

- `razorpay_list_payments` - List recent payments with filters (pagination, date range)
- `razorpay_get_payment` - Fetch detailed payment information by ID
- `razorpay_create_payment_link` - Create one-time payment links with shareable URLs
- `razorpay_list_invoices` - List invoices with status and type filtering
- `razorpay_get_invoice` - Fetch invoice details including line items
- `razorpay_create_refund` - Create full or partial refunds for payments

## Setup

### 1. Get Razorpay API Credentials

1. Log in to [Razorpay Dashboard](https://dashboard.razorpay.com)
2. Navigate to **Settings → API Keys**
3. Click **Generate Key** (or use existing test/live key)
4. Copy the **Key ID** and **Key Secret**

### 2. Configure Environment Variables

```bash
export RAZORPAY_API_KEY="rzp_test_your_key_id"
export RAZORPAY_API_SECRET="your_key_secret"
```

**Important:** Use test keys (`rzp_test_*`) for development. Never commit live keys to version control.

## Usage

### razorpay_list_payments

List recent payments with optional filters for pagination and date ranges.

**Arguments:**
- `count` (int, default: 10) - Number of payments to fetch (1-100)
- `skip` (int, default: 0) - Number of payments to skip for pagination
- `from_timestamp` (int, optional) - Unix timestamp to filter payments from
- `to_timestamp` (int, optional) - Unix timestamp to filter payments to

**Example:**
```python
# List last 20 payments
razorpay_list_payments(count=20)

# List payments from a specific date range
razorpay_list_payments(count=50, from_timestamp=1640995200, to_timestamp=1643673600)
```

### razorpay_get_payment

Fetch detailed information for a specific payment by ID.

**Arguments:**
- `payment_id` (str, required) - Razorpay payment ID (starts with `pay_`)

**Example:**
```python
razorpay_get_payment(payment_id="pay_AbcDefGhijkLmn")
```

### razorpay_create_payment_link

Create a one-time payment link that can be shared with customers.

**Arguments:**
- `amount` (int, required) - Amount in smallest currency unit (e.g., paise for INR)
- `currency` (str, required) - ISO 4217 currency code (e.g., "INR", "USD")
- `description` (str, required) - Description of the payment
- `customer_name` (str, optional) - Customer's name
- `customer_email` (str, optional) - Customer's email address
- `customer_contact` (str, optional) - Customer's phone number

**Example:**
```python
razorpay_create_payment_link(
    amount=50000,  # Rs. 500.00
    currency="INR",
    description="Payment for order #123",
    customer_email="customer@example.com"
)
```

### razorpay_list_invoices

List invoices with optional filtering by type and status.

**Arguments:**
- `count` (int, default: 10) - Number of invoices to fetch (1-100)
- `skip` (int, default: 0) - Number of invoices to skip for pagination
- `type_filter` (str, optional) - Filter by invoice type (e.g., "invoice", "link")

**Example:**
```python
razorpay_list_invoices(count=20, type_filter="invoice")
```

### razorpay_get_invoice

Fetch detailed information for a specific invoice including line items.

**Arguments:**
- `invoice_id` (str, required) - Razorpay invoice ID (starts with `inv_`)

**Example:**
```python
razorpay_get_invoice(invoice_id="inv_AbcDefGhijkLmn")
```

### razorpay_create_refund

Create a full or partial refund for a captured payment.

**Arguments:**
- `payment_id` (str, required) - Razorpay payment ID (starts with `pay_`)
- `amount` (int, optional) - Refund amount in smallest currency unit (omit for full refund)
- `notes` (dict, optional) - Key-value pairs for additional refund information

**Example:**
```python
# Full refund
razorpay_create_refund(payment_id="pay_AbcDefGhijkLmn")

# Partial refund with notes
razorpay_create_refund(
    payment_id="pay_AbcDefGhijkLmn",
    amount=10000,  # Rs. 100.00
    notes={"reason": "Customer request"}
)
```

## Authentication

Razorpay uses HTTP Basic Authentication:
- **Username:** RAZORPAY_API_KEY (Key ID)
- **Password:** RAZORPAY_API_SECRET (Key Secret)

The tool automatically constructs the auth tuple from your environment variables.

## Error Handling

All tools return error dicts for failures:

```json
{
  "error": "Invalid Razorpay API credentials"
}
```

Common errors:
- `401` - Invalid API credentials
- `403` - Insufficient permissions
- `404` - Resource not found
- `429` - Rate limit exceeded

## Testing

Use Razorpay's test mode to avoid real charges:
1. Generate test API keys (they start with `rzp_test_`)
2. Use test payment methods from [Razorpay Test Cards](https://razorpay.com/docs/payments/payments/test-card-details/)

## API Reference

- [Razorpay API Docs](https://razorpay.com/docs/api/)
- [Authentication](https://razorpay.com/docs/api/authentication)
- [Payments API](https://razorpay.com/docs/api/payments/)
- [Payment Links API](https://razorpay.com/docs/api/payment-links/)
- [Invoices API](https://razorpay.com/docs/api/invoices/)
- [Refunds API](https://razorpay.com/docs/api/refunds/)
