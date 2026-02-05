import pytest
from unittest.mock import patch, MagicMock
from aden_tools.tools.stripe_tool import (
    get_customer_by_email, 
    create_customer, 
    update_customer,
    create_subscription, 
    cancel_subscription,
    list_invoices,
    create_payment_link
)

# NOTE: The patch path points to '.stripe_tool.stripe_tool.stripe'
PATCH_PATH = "aden_tools.tools.stripe_tool.stripe_tool.stripe"

# --- Customer Tests ---

@patch(PATCH_PATH)
def test_create_customer(mock_stripe):
    # Mock the return value of Customer.create
    mock_customer = MagicMock()
    mock_customer.id = "cus_new123"
    mock_customer.email = "new@example.com"
    mock_customer.name = "New User"
    mock_stripe.Customer.create.return_value = mock_customer

    result = create_customer("new@example.com", "New User", api_key="sk_test_mock")

    assert result["result"] == "success"
    # FIX: Access the mock object inside the 'customer' key
    assert result["customer"].id == "cus_new123"
    mock_stripe.Customer.create.assert_called_with(
        email="new@example.com", 
        name="New User", 
        metadata={}
    )

@patch(PATCH_PATH)
def test_update_customer(mock_stripe):
    mock_customer = MagicMock()
    mock_customer.id = "cus_123"
    mock_customer.email = "updated@example.com"
    mock_stripe.Customer.modify.return_value = mock_customer

    result = update_customer("cus_123", email="updated@example.com", api_key="sk_test_mock")

    assert result["result"] == "success"
    # FIX: Access inside 'customer' key
    assert result["customer"].email == "updated@example.com"
    mock_stripe.Customer.modify.assert_called_with("cus_123", email="updated@example.com")

# --- Subscription Tests ---

@patch(PATCH_PATH)
def test_create_subscription(mock_stripe):
    mock_sub = MagicMock()
    mock_sub.id = "sub_123"
    mock_sub.status = "active"
    mock_stripe.Subscription.create.return_value = mock_sub

    result = create_subscription("cus_123", "price_abc", api_key="sk_test_mock")

    assert result["result"] == "success"
    # FIX: Access inside 'subscription' key
    assert result["subscription"].status == "active"
    mock_stripe.Subscription.create.assert_called_once()

@patch(PATCH_PATH)
def test_cancel_subscription(mock_stripe):
    mock_sub = MagicMock()
    mock_sub.id = "sub_123"
    mock_sub.status = "canceled"
    mock_stripe.Subscription.delete.return_value = mock_sub

    result = cancel_subscription("sub_123", api_key="sk_test_mock")

    assert result["result"] == "success"
    # FIX: Access inside 'subscription' key
    assert result["subscription"].status == "canceled"
    mock_stripe.Subscription.delete.assert_called_with("sub_123")

# --- Invoice Tests ---

@patch(PATCH_PATH)
def test_list_invoices(mock_stripe):
    mock_invoice = MagicMock()
    mock_invoice.id = "in_123"
    mock_invoice.amount_due = 1000
    mock_invoice.status = "open"
    
    # Mock the list response
    mock_stripe.Invoice.list.return_value.data = [mock_invoice]

    result = list_invoices("cus_123", limit=1, api_key="sk_test_mock")

    assert result["result"] == "success"
    assert len(result["invoices"]) == 1
    # FIX: The result contains the raw objects, so we access attributes directly
    assert result["invoices"][0].id == "in_123"

# --- Existing Tests (Retained) ---

@patch(PATCH_PATH)
def test_get_customer_found(mock_stripe):
    mock_customer = MagicMock()
    mock_customer.id = "cus_123"
    mock_customer.name = "John Doe"
    # For get_customer_by_email, the code wraps fields into a dict, so accessing keys works
    mock_stripe.Customer.search.return_value.data = [mock_customer]

    result = get_customer_by_email("john@example.com", api_key="sk_test_mock")

    assert result["result"] == "success"
    assert result["id"] == "cus_123"

@patch(PATCH_PATH)
def test_create_payment_link(mock_stripe):
    mock_price = MagicMock()
    mock_price.id = "price_123"
    mock_stripe.Price.create.return_value = mock_price

    mock_link = MagicMock()
    mock_link.url = "https://stripe.com/pay/test"
    mock_stripe.PaymentLink.create.return_value = mock_link

    result = create_payment_link("Test Item", 1000, api_key="sk_test_mock")

    assert result["result"] == "success"
    assert result["url"] == "https://stripe.com/pay/test"