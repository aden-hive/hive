# Stripe Tool

Enables agents to interact with Stripe for billing inquiries and payment generation.

## Setup
1. Log in to [Stripe Dashboard](https://dashboard.stripe.com/).
2. Go to **Developers** > **API keys**.
3. Copy your **Secret key**.
4. Set environment variable: `STRIPE_API_KEY=sk_test_...`

## Functions
- `get_customer_by_email(email)`: Find customer ID and balance.
- `get_subscription_status(customer_id)`: Check active subscriptions.
- `create_payment_link(amount, currency, name)`: Generate a checkout URL.