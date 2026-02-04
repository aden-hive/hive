import pytest
from unittest.mock import patch, MagicMock
from aden_tools.tools.stripe_tool import get_customer_by_email, create_payment_link

# FIX: Added .stripe_tool to the patch path to target the specific file
@patch("aden_tools.tools.stripe_tool.stripe_tool.stripe")
def test_get_customer_found(mock_stripe):
    # Setup the mock to look like a Stripe response
    mock_customer = MagicMock()
    mock_customer.id = "cus_123"
    mock_customer.name = "John Doe"
    mock_customer.balance = 0
    mock_customer.created = 1600000000
    mock_customer.currency = "usd"
    
    # Configure search return
    mock_stripe.Customer.search.return_value.data = [mock_customer]

    # Run the tool
    result = get_customer_by_email("john@example.com", api_key="sk_test_mock")

    # Verify
    assert result["result"] == "success"
    assert result["id"] == "cus_123"
    mock_stripe.Customer.search.assert_called_once()

# FIX: Added .stripe_tool to the patch path here too
@patch("aden_tools.tools.stripe_tool.stripe_tool.stripe")
def test_create_payment_link(mock_stripe):
    # Setup mock
    mock_price = MagicMock()
    mock_price.id = "price_123"
    mock_stripe.Price.create.return_value = mock_price

    mock_link = MagicMock()
    mock_link.url = "https://stripe.com/pay/test"
    mock_stripe.PaymentLink.create.return_value = mock_link

    # Run tool
    result = create_payment_link("Test Item", 1000, api_key="sk_test_mock")

    # Verify
    assert result["result"] == "success"
    assert result["url"] == "https://stripe.com/pay/test"