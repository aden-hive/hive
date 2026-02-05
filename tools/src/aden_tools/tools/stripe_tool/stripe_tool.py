"""
Stripe Tool
Allows agents to interact with Stripe for customer, billing, checkout, and webhook data.
"""
from typing import Dict, Any, Optional, List, Union
import os
import stripe

def _setup_api(api_key: Optional[str] = None):
    """Helper to configure the Stripe API key."""
    key = api_key or os.environ.get("STRIPE_API_KEY")
    if not key:
        raise ValueError("Missing STRIPE_API_KEY. Please check your credentials.")
    stripe.api_key = key

# ==========================================
# EXISTING FUNCTIONALITY (Unchanged)
# ==========================================

def get_customer_by_email(
    email: str, 
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Finds a Stripe customer by their email address.
    """
    try:
        _setup_api(api_key)
        # Search provides a list, we take the first match
        customers = stripe.Customer.search(
            query=f"email:'{email}'",
            limit=1
        )
        if not customers.data:
            return {"result": "not_found", "message": f"No customer found with email {email}"}
        
        cust = customers.data[0]
        return {
            "result": "success",
            "id": cust.id,
            "name": cust.name,
            "balance": cust.balance,
            "created": cust.created,
            "currency": cust.currency
        }
    except Exception as e:
        return {"error": str(e)}

def get_subscription_status(
    customer_id: str, 
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retrieves the active subscription status for a customer.
    """
    try:
        _setup_api(api_key)
        # Fetch all subscriptions for this customer
        subs = stripe.Subscription.list(customer=customer_id, status='all', limit=5)
        
        data = []
        for sub in subs.data:
            product_name = "Unknown Product"
            # Try to resolve product name if expanded (simplified here)
            if hasattr(sub, 'plan') and hasattr(sub.plan, 'product'):
                 product_name = sub.plan.product

            data.append({
                "id": sub.id,
                "status": sub.status,
                "current_period_end": sub.current_period_end,
                "amount": sub.plan.amount if sub.plan else 0,
                "interval": sub.plan.interval if sub.plan else "N/A"
            })
            
        return {
            "result": "success", 
            "customer_id": customer_id,
            "subscriptions": data
        }
    except Exception as e:
        return {"error": str(e)}

def create_payment_link(
    name: str,
    amount_cents: int,
    currency: str = "usd",
    quantity: int = 1,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a Stripe Payment Link for a specific product/amount.
    """
    try:
        _setup_api(api_key)
        
        # 1. Create a Price (This creates a product on the fly or you could reuse one)
        price = stripe.Price.create(
            currency=currency,
            unit_amount=amount_cents,
            product_data={"name": name},
        )
        
        # 2. Create the Payment Link
        link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": quantity}]
        )
        
        return {"result": "success", "url": link.url}
    except Exception as e:
        return {"error": str(e)}

# ==========================================
# NEW: CUSTOMER MANAGEMENT


def create_customer(
    email: str, 
    name: Optional[str] = None, 
    metadata: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a new customer in Stripe."""
    try:
        _setup_api(api_key)
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata=metadata or {}
        )
        return {"result": "success", "customer": customer}
    except Exception as e:
        return {"error": str(e)}

def update_customer(
    customer_id: str, 
    email: Optional[str] = None, 
    name: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Updates an existing customer's details."""
    try:
        _setup_api(api_key)
        params = {}
        if email: params['email'] = email
        if name: params['name'] = name
        if metadata: params['metadata'] = metadata
        
        customer = stripe.Customer.modify(customer_id, **params)
        return {"result": "success", "customer": customer}
    except Exception as e:
        return {"error": str(e)}

def list_customers(
    limit: int = 10,
    email: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Lists customers, optionally filtering by email."""
    try:
        _setup_api(api_key)
        params = {'limit': limit}
        if email:
            params['email'] = email
        
        customers = stripe.Customer.list(**params)
        return {"result": "success", "customers": customers.data}
    except Exception as e:
        return {"error": str(e)}

def get_customer_by_id(
    customer_id: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves a customer by their Stripe ID (cus_...)."""
    try:
        _setup_api(api_key)
        customer = stripe.Customer.retrieve(customer_id)
        return {"result": "success", "customer": customer}
    except Exception as e:
        return {"error": str(e)}


# NEW: SUBSCRIPTION LIFECYCLE


def create_subscription(
    customer_id: str, 
    price_id: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Starts a new subscription for a customer."""
    try:
        _setup_api(api_key)
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id}],
            expand=['latest_invoice.payment_intent'] 
        )
        return {"result": "success", "subscription": subscription}
    except Exception as e:
        return {"error": str(e)}

def update_subscription(
    subscription_id: str,
    price_id: Optional[str] = None,
    cancel_at_period_end: Optional[bool] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Updates a subscription (e.g. switch plan or set to cancel)."""
    try:
        _setup_api(api_key)
        params = {}
        if cancel_at_period_end is not None:
            params['cancel_at_period_end'] = cancel_at_period_end
        
        if price_id:
            # Updating a plan requires getting the item ID first
            sub = stripe.Subscription.retrieve(subscription_id)
            item_id = sub['items']['data'][0].id
            params['items'] = [{"id": item_id, "price": price_id}]

        subscription = stripe.Subscription.modify(subscription_id, **params)
        return {"result": "success", "subscription": subscription}
    except Exception as e:
        return {"error": str(e)}

def cancel_subscription(
    subscription_id: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Cancels a subscription immediately."""
    try:
        _setup_api(api_key)
        subscription = stripe.Subscription.delete(subscription_id)
        return {"result": "success", "subscription": subscription}
    except Exception as e:
        return {"error": str(e)}

def list_subscriptions(
    customer_id: Optional[str] = None,
    status: str = 'all',
    limit: int = 10,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Lists subscriptions, optionally filtered by customer."""
    try:
        _setup_api(api_key)
        params = {'limit': limit, 'status': status}
        if customer_id:
            params['customer'] = customer_id
            
        subs = stripe.Subscription.list(**params)
        return {"result": "success", "subscriptions": subs.data}
    except Exception as e:
        return {"error": str(e)}


# NEW: INVOICES & PAYMENTS


def list_invoices(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 5,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Lists invoices."""
    try:
        _setup_api(api_key)
        params = {'limit': limit}
        if customer_id: params['customer'] = customer_id
        if status: params['status'] = status
        
        invoices = stripe.Invoice.list(**params)
        return {"result": "success", "invoices": invoices.data}
    except Exception as e:
        return {"error": str(e)}

def retrieve_invoice(
    invoice_id: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves a specific invoice details."""
    try:
        _setup_api(api_key)
        invoice = stripe.Invoice.retrieve(invoice_id)
        return {"result": "success", "invoice": invoice}
    except Exception as e:
        return {"error": str(e)}

def pay_invoice(
    invoice_id: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Attempt to pay an open invoice immediately."""
    try:
        _setup_api(api_key)
        invoice = stripe.Invoice.pay(invoice_id)
        return {"result": "success", "invoice": invoice}
    except Exception as e:
        return {"error": str(e)}

def list_payment_intents(
    customer_id: Optional[str] = None,
    limit: int = 5,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Lists recent payment intents (transactions)."""
    try:
        _setup_api(api_key)
        params = {'limit': limit}
        if customer_id: params['customer'] = customer_id
        
        intents = stripe.PaymentIntent.list(**params)
        return {"result": "success", "payment_intents": intents.data}
    except Exception as e:
        return {"error": str(e)}

# NEW: CHECKOUT & BILLING


def create_checkout_session(
    price_id: str,
    success_url: str,
    cancel_url: str,
    mode: str = "subscription",
    customer_id: Optional[str] = None,
    quantity: int = 1,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a Checkout Session for hosting a payment page.
    """
    try:
        _setup_api(api_key)
        params = {
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items": [{"price": price_id, "quantity": quantity}],
            "mode": mode,
        }
        if customer_id:
            params["customer"] = customer_id
            
        session = stripe.checkout.Session.create(**params)
        return {"result": "success", "session_url": session.url, "id": session.id}
    except Exception as e:
        return {"error": str(e)}

# ==========================================
# NEW: WEBHOOKS UTILITIES
# ==========================================

def verify_webhook_signature(
    payload: Union[str, bytes],
    sig_header: str,
    webhook_secret: str,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Verifies a webhook signature and constructs the event.
    Useful for agents verifying that incoming data is truly from Stripe.
    """
    try:
        _setup_api(api_key)
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        return {"result": "success", "event": event}
    except ValueError:
        return {"error": "Invalid payload"}
    except stripe.error.SignatureVerificationError:
        return {"error": "Invalid signature"}
    except Exception as e:
        return {"error": str(e)}