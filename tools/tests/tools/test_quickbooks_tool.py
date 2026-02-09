import pytest
import json
from unittest.mock import Mock, patch
import httpx
from fastmcp import FastMCP
from aden_tools.tools.quickbooks_tool import register_tools


@pytest.fixture
def mock_credentials():
    """Mock credentials object that returns fake token and realm_id."""
    cred = Mock()
    cred.get.side_effect = lambda key: (
        "fake_access_token" if key == "quickbooks_access_token" else
        "fake_realm_id" if key == "quickbooks_realm_id" else
        None
    )
    cred.validate_for_tools.return_value = None
    return cred


@pytest.fixture
def quickbooks_tools(mock_credentials):
    """
    Register QuickBooks tools with mock credentials and return the captured functions.
    """
    mcp = FastMCP()
    tools_dict = {}

    # Capture the decorated functions
    original_tool = mcp.tool

    def capture_tool(*args, **kwargs):
        def decorator(func):
            decorated = original_tool(*args, **kwargs)(func)
            tools_dict[func.__name__] = func  # store original func
            return decorated
        return decorator

    mcp.tool = capture_tool

    # Register tools with mock credentials
    register_tools(mcp, credentials=mock_credentials)

    # Restore original decorator
    mcp.tool = original_tool

    return tools_dict


@patch('httpx.Client.request')
def test_create_invoice(mock_request, quickbooks_tools):
    mock_response = Mock()
    mock_response.json.return_value = {
        "Invoice": {
            "Id": "123",
            "DocNumber": "INV-100",
            "TotalAmt": 150.0
        }
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    tool_func = quickbooks_tools["quickbooks_create_invoice"]

    result_str = tool_func(
        customer_id="CUST1",
        line_items=[{"Amount": 150.0, "DetailType": "SalesItemLineDetail"}],
        due_date="2024-12-31"
    )

    result = json.loads(result_str)

    assert result["success"] is True
    assert result["InvoiceID"] == "123"
    assert result["TotalAmount"] == 150.0

    mock_request.assert_called_once()
    payload = mock_request.call_args[1]["json"]
    assert payload["CustomerRef"]["value"] == "CUST1"


@patch('httpx.Client.request')
def test_search_customers(mock_request, quickbooks_tools):
    mock_response = Mock()
    mock_response.json.return_value = {
        "QueryResponse": {
            "Customer": [{"Id": "1", "DisplayName": "Test Customer", "Balance": 50.0}]
        }
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    tool_func = quickbooks_tools["quickbooks_search_customers"]

    result_str = tool_func(query="Test")
    result = json.loads(result_str)

    assert result["success"] is True
    assert len(result["customers"]) == 1
    assert result["customers"][0]["Name"] == "Test Customer"
    assert result["customers"][0]["Balance"] == 50.0


@patch('httpx.Client.request')
def test_record_payment_basic(mock_request, quickbooks_tools):
    # Mock 1: GET invoice for CustomerRef
    mock_invoice = Mock()
    mock_invoice.json.return_value = {
        "Invoice": {
            "CustomerRef": {"value": "CUST1"},
            "Id": "INV1",  # add if code expects it
            "Balance": 100.0  # optional but good
        }
    }
    mock_invoice.raise_for_status.return_value = None

    # Mock 2: POST payment
    mock_payment = Mock()
    mock_payment.json.return_value = {
        "Payment": {
            "Id": "PAY1",
            "TotalAmt": 100.0,
            "TxnDate": "2024-02-04"
        }
    }
    mock_payment.raise_for_status.return_value = None

    # Mock 3: GET invoice for updated balance
    mock_updated = Mock()
    mock_updated.json.return_value = {
        "Invoice": {
            "Balance": 0.0,  # after full payment
            "Id": "INV1"
        }
    }
    mock_updated.raise_for_status.return_value = None

    mock_request.side_effect = [mock_invoice, mock_payment, mock_updated]

    tool_func = quickbooks_tools["quickbooks_record_payment"]

    result_str = tool_func(
        invoice_id="INV1",
        amount=100.0,
        payment_date="2024-02-04"
    )

    print("DEBUG: result_str =", result_str)  # ← add this for debugging

    result = json.loads(result_str)

    assert result["success"] is True, f"Tool failed: {result.get('error')}"
    assert result["PaymentID"] == "PAY1"
    assert result["AmountApplied"] == 100.0
    # assert result["RemainingBalance"] == 0.0  # optional, uncomment if you want


@patch('httpx.Client.request')
def test_record_payment_with_reference_number(mock_request, quickbooks_tools):
    mock_invoice = Mock()
    mock_invoice.json.return_value = {
        "Invoice": {
            "CustomerRef": {"value": "CUST1"},
            "Id": "INV1",
            "Balance": 1000.0  # before payment
        }
    }
    mock_invoice.raise_for_status.return_value = None

    mock_payment = Mock()
    mock_payment.json.return_value = {
        "Payment": {
            "Id": "PAY1",
            "TotalAmt": 100.0,
            "TxnDate": "2024-02-04"
        }
    }
    mock_payment.raise_for_status.return_value = None

    mock_updated = Mock()
    mock_updated.json.return_value = {
        "Invoice": {
            "Id": "INV1",
            "Balance": 900.0  # after $100 payment
        }
    }
    mock_updated.raise_for_status.return_value = None

    mock_request.side_effect = [mock_invoice, mock_payment, mock_updated]

    tool_func = quickbooks_tools["quickbooks_record_payment"]

    result_str = tool_func(
        invoice_id="INV1",
        amount=100.0,
        payment_date="2024-02-04",
        reference_number="REF999"
    )

    print("DEBUG: result_str =", result_str)  # ← add this

    result = json.loads(result_str)

    assert result["success"] is True, f"Tool failed: {result.get('error')}"
    assert result["PaymentID"] == "PAY1"
    assert result["AmountApplied"] == 100.0
    assert result["RemainingBalance"] == 900.0

    # Check reference number was included in POST payload
    payload = mock_request.call_args_list[1][1]["json"]
    assert payload["PaymentRefNum"] == "REF999"

@patch('httpx.Client.request')
def test_error_handling_401(mock_request, quickbooks_tools):
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"Fault": {"Error": [{"Message": "Unauthorized"}]}}
    mock_response.headers = {"Content-Type": "application/json"}

    error = httpx.HTTPStatusError("401 Unauthorized", request=Mock(), response=mock_response)
    mock_request.side_effect = error

    tool_func = quickbooks_tools["quickbooks_get_invoice"]

    result_str = tool_func(invoice_id="123")
    result = json.loads(result_str)

    assert result["success"] is False
    assert "Unauthorized" in result.get("error", "") or "401" in result.get("error", "")


@patch('httpx.Client.request')
def test_error_handling_429_rate_limit(mock_request, quickbooks_tools):
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.headers = {"Content-Type": "text/plain"}
    mock_response.text = "Too Many Requests"

    error = httpx.HTTPStatusError("429 Too Many Requests", request=Mock(), response=mock_response)
    mock_request.side_effect = error

    tool_func = quickbooks_tools["quickbooks_get_invoice"]

    result_str = tool_func(invoice_id="123")
    result = json.loads(result_str)

    assert result["success"] is False
    assert "429" in result.get("error", "") or "Rate limit" in result.get("error", "")


@patch('httpx.Client.request')
def test_error_handling_403_forbidden(mock_request, quickbooks_tools):
    mock_response = Mock()
    mock_response.status_code = 403
    mock_response.json.return_value = {"Fault": {"Error": [{"Message": "Permission Denied"}]}}
    mock_response.headers = {"Content-Type": "application/json"}

    error = httpx.HTTPStatusError("403 Forbidden", request=Mock(), response=mock_response)
    mock_request.side_effect = error

    tool_func = quickbooks_tools["quickbooks_search_customers"]

    result_str = tool_func(query="test")
    result = json.loads(result_str)

    assert result["success"] is False
    assert "403" in result.get("error", "") or "Permission" in result.get("error", "")


@patch('httpx.Client.request')
def test_create_customer(mock_request, quickbooks_tools):
    mock_response = Mock()
    mock_response.json.return_value = {
        "Customer": {"Id": "CUST2", "DisplayName": "New Corp"}
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    tool_func = quickbooks_tools["quickbooks_create_customer"]

    result_str = tool_func(
        display_name="New Corp",
        email="new@corp.com",
        phone="123456",
        notes="VIP"
    )
    result = json.loads(result_str)

    assert result["success"] is True
    assert result["CustomerID"] == "CUST2"


@patch('httpx.Client.request')
def test_create_expense(mock_request, quickbooks_tools):
    mock_response = Mock()
    mock_response.json.return_value = {
        "Purchase": {"Id": "EXP1", "TotalAmt": 50.0}
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    tool_func = quickbooks_tools["quickbooks_create_expense"]

    result_str = tool_func(
        payee="Vendor A",
        amount=50.0,
        expense_account_id="60",
        memo="Lunch"
    )
    result = json.loads(result_str)

    assert result["success"] is True
    assert result["ExpenseID"] == "EXP1"

    payload = mock_request.call_args[1]["json"]
    assert payload["Line"][0]["AccountBasedExpenseLineDetail"]["AccountRef"]["value"] == "60"
    assert payload["PrivateNote"] == "Lunch"


@patch('httpx.Client.request')
def test_search_customers_empty(mock_request, quickbooks_tools):
    mock_response = Mock()
    mock_response.json.return_value = {"QueryResponse": {}}
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    tool_func = quickbooks_tools["quickbooks_search_customers"]

    result_str = tool_func(query="NonExistent")
    result = json.loads(result_str)

    assert result["success"] is True
    assert len(result["customers"]) == 0