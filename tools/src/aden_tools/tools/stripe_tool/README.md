# Stripe Tool

Integration with Stripe for payment processing, subscription management, invoicing, and refund handling.

## Overview

This tool enables Hive agents to interact with Stripe's payment infrastructure for:
- Managing customers and subscriptions
- Creating and confirming payment intents
- Listing and capturing charges
- Creating and managing invoices and invoice items
- Managing products and prices
- Creating payment links
- Processing refunds
- Managing coupons
- Inspecting account balance and transactions
- Listing webhook endpoints
- Managing payment methods

## Available Tools

This integration provides 51 MCP tools for comprehensive payment operations:

**Customers**
- `stripe_create_customer` - Create a new customer
- `stripe_get_customer` - Retrieve a customer by ID
- `stripe_get_customer_by_email` - Look up a customer by email address
- `stripe_update_customer` - Update an existing customer
- `stripe_list_customers` - List customers with optional filters

**Subscriptions**
- `stripe_get_subscription` - Retrieve a subscription by ID
- `stripe_get_subscription_status` - Check active/past_due status for a customer
- `stripe_list_subscriptions` - List subscriptions with optional filters
- `stripe_create_subscription` - Create a new subscription
- `stripe_update_subscription` - Update price, quantity, or schedule cancellation
- `stripe_cancel_subscription` - Cancel immediately or at period end

**Payment Intents**
- `stripe_create_payment_intent` - Create a PaymentIntent to collect payment
- `stripe_get_payment_intent` - Retrieve a PaymentIntent by ID
- `stripe_confirm_payment_intent` - Confirm a PaymentIntent to attempt collection
- `stripe_cancel_payment_intent` - Cancel a PaymentIntent
- `stripe_list_payment_intents` - List PaymentIntents with optional filters

**Charges**
- `stripe_list_charges` - List charges with optional filters
- `stripe_get_charge` - Retrieve a charge by ID
- `stripe_capture_charge` - Capture an uncaptured charge

**Refunds**
- `stripe_create_refund` - Create a full or partial refund
- `stripe_get_refund` - Retrieve a refund by ID
- `stripe_list_refunds` - List refunds with optional filters

**Invoices**
- `stripe_list_invoices` - List invoices with optional filters
- `stripe_get_invoice` - Retrieve an invoice by ID
- `stripe_create_invoice` - Create a new invoice for a customer
- `stripe_finalize_invoice` - Finalize a draft invoice
- `stripe_pay_invoice` - Attempt to pay an open invoice immediately
- `stripe_void_invoice` - Void an open invoice

**Invoice Items**
- `stripe_create_invoice_item` - Add a line item to an invoice (supports negative amounts for credits)
- `stripe_list_invoice_items` - List invoice items with optional filters
- `stripe_delete_invoice_item` - Delete a pending invoice item

**Products**
- `stripe_create_product` - Create a new product
- `stripe_get_product` - Retrieve a product by ID
- `stripe_list_products` - List products with optional filters
- `stripe_update_product` - Update an existing product

**Prices**
- `stripe_create_price` - Create a price for a product
- `stripe_get_price` - Retrieve a price by ID
- `stripe_list_prices` - List prices with optional filters
- `stripe_update_price` - Update active status, nickname, or metadata

**Payment Links**
- `stripe_create_payment_link` - Create a shareable payment link
- `stripe_get_payment_link` - Retrieve a payment link by ID
- `stripe_list_payment_links` - List payment links with optional filters

**Coupons**
- `stripe_create_coupon` - Create a discount coupon (percent or fixed amount off)
- `stripe_list_coupons` - List all coupons
- `stripe_delete_coupon` - Delete a coupon

**Balance**
- `stripe_get_balance` - Retrieve the current account balance
- `stripe_list_balance_transactions` - List balance transactions

**Webhook Endpoints**
- `stripe_list_webhook_endpoints` - List all configured webhook endpoints

**Payment Methods**
- `stripe_list_payment_methods` - List payment methods attached to a customer
- `stripe_get_payment_method` - Retrieve a payment method by ID
- `stripe_detach_payment_method` - Detach a payment method from its customer

## Setup

### 1. Get Stripe API Credentials

1. Log in to the [Stripe Dashboard](https://dashboard.stripe.com)
2. Navigate to **Developers -> API keys**
3. Copy the **Secret key** (starts with `sk_test_` for test mode or `sk_live_` for live mode)

### 2. Configure Environment Variables

```bash
export STRIPE_API_KEY="sk_test_your_secret_key"
```

**Important:** Use test keys (`sk_test_*`) for development. Never commit live keys to version control.

## Usage

### stripe_get_customer_by_email

```python
stripe_get_customer_by_email(email="alice@example.com")
```

### stripe_get_subscription_status

```python
stripe_get_subscription_status(customer_id="cus_AbcDefGhijkLmn")
```

### stripe_update_subscription

```python
# Change price only
stripe_update_subscription("sub_AbcDefGhijkLmn", price_id="price_NewPlan")

# Change quantity only
stripe_update_subscription("sub_AbcDefGhijkLmn", quantity=5)

# Schedule cancellation at period end
stripe_update_subscription("sub_AbcDefGhijkLmn", cancel_at_period_end=True)
```

### stripe_create_payment_link

```python
# First create a product and price, then create the link
stripe_create_payment_link(price_id="price_AbcDefGhijkLmn", quantity=1)
```

### stripe_create_invoice_item

```python
# Standard charge
stripe_create_invoice_item("cus_AbcDefGhijkLmn", amount=1500, currency="usd", description="Setup fee")

# Credit or discount (negative amount)
stripe_create_invoice_item("cus_AbcDefGhijkLmn", amount=-500, currency="usd", description="Loyalty credit")
```

### stripe_list_invoices

```python
stripe_list_invoices(status="open", limit=20)
```

### stripe_create_refund

```python
# Full refund via payment intent
stripe_create_refund(payment_intent_id="pi_AbcDefGhijkLmn")

# Partial refund via charge with reason
stripe_create_refund(
    charge_id="ch_AbcDefGhijkLmn",
    amount=1000,
    reason="customer_request"
)
```

## Authentication

Stripe uses Bearer token authentication. The tool passes your `STRIPE_API_KEY` to the official `stripe` Python library on initialisation. A single `StripeClient` instance is created and stored per `_StripeClient` object, reused across all API calls rather than recreated on each request.

## Error Handling

All tools return error dicts on failure so agents can handle errors without raising exceptions:

```json
{
  "error": "No such customer: cus_AbcDefGhijkLmn"
}
```

Common errors:
- Invalid API key - check `STRIPE_API_KEY` is set correctly
- Resource not found - verify the ID exists in your Stripe account
- Invalid request - check parameter values and types
- Rate limit exceeded - reduce request frequency

ID prefix validation is enforced before any API call is made:

| Resource | Expected prefix |
|---|---|
| Customer | `cus_` |
| Subscription | `sub_` |
| Payment Intent | `pi_` |
| Charge | `ch_` |
| Refund | `re_` |
| Invoice | `in_` |
| Invoice Item | `ii_` |
| Product | `prod_` |
| Price | `price_` |
| Payment Link | `plink_` |
| Payment Method | `pm_` |

## Testing

Use Stripe test mode to avoid real charges:
1. Generate test API keys (they start with `sk_test_`)
2. Use test payment methods from [Stripe Testing Docs](https://stripe.com/docs/testing)

## API Reference

- [Stripe API Docs](https://stripe.com/docs/api)
- [Authentication](https://stripe.com/docs/keys)
- [Customers API](https://stripe.com/docs/api/customers)
- [Subscriptions API](https://stripe.com/docs/api/subscriptions)
- [Payment Intents API](https://stripe.com/docs/api/payment_intents)
- [Invoices API](https://stripe.com/docs/api/invoices)
- [Refunds API](https://stripe.com/docs/api/refunds)