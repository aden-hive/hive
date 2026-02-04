"""
Stripe Tool
Allows agents to interact with Stripe for customer and billing data.
"""
from typing import Dict, Any, Optional
import os
import stripe

def _setup_api(api_key: Optional[str] = None):
    """Helper to configure the Stripe API key."""
    key = api_key or os.environ.get("STRIPE_API_KEY")
    if not key:
        raise ValueError("Missing STRIPE_API_KEY. Please check your credentials.")
    stripe.api_key = key

def get_customer_by_email(
    email: str, 
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Finds a Stripe customer by their email address.

    Args:
        email (str): The email address to search for.
        api_key (str, optional): Stripe Secret Key.

    Returns:
        Dict[str, Any]: Customer details or result 'not_found'.
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

    Args:
        customer_id (str): The Stripe Customer ID (e.g., cus_123).
        api_key (str, optional): Stripe Secret Key.

    Returns:
        Dict[str, Any]: List of subscriptions and their status.
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

    Args:
        name (str): Name of the product or service (e.g. "Consultation Fee").
        amount_cents (int): Amount in cents (e.g. 1000 = $10.00).
        currency (str): Currency code (default: usd).
        quantity (int): Quantity.
        api_key (str, optional): Stripe Secret Key.

    Returns:
        Dict[str, Any]: The payment URL.
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