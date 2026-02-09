import pytest
from unittest.mock import Mock, patch
import httpx
from aden_tools.tools.quickbooks_tool import QuickBooksClient

@pytest.fixture
def mock_credentials():
    return {
        "access_token": "test_token",
        "realm_id": "test_realm"
    }

@pytest.fixture
def qb_client(mock_credentials):
    return QuickBooksClient(mock_credentials["access_token"], mock_credentials["realm_id"])

def test_client_init(mock_credentials):
    client = QuickBooksClient(mock_credentials["access_token"], mock_credentials["realm_id"])
    assert client.access_token == "test_token"
    assert client.realm_id == "test_realm"
    assert str(client.client.base_url) == "https://quickbooks.api.intuit.com/v3/company/test_realm/"

@patch('httpx.Client.request')
def test_create_invoice(mock_request, qb_client):
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

    line_items = [{"Amount": 150.0, "DetailType": "SalesItemLineDetail"}]
    invoice = qb_client.create_invoice("CUST1", line_items, "2024-12-31")
    
    assert invoice["Id"] == "123"
    assert invoice["TotalAmt"] == 150.0
    mock_request.assert_called_once()
    assert mock_request.call_args[1]["json"]["CustomerRef"]["value"] == "CUST1"

@patch('httpx.Client.request')
def test_search_customers(mock_request, qb_client):
    mock_response = Mock()
    mock_response.json.return_value = {
        "QueryResponse": {
            "Customer": [{"Id": "1", "DisplayName": "Test Customer", "Balance": 50.0}]
        }
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    customers_json = qb_client.search_customers("Test")
    # Note: QuickBooksClient.search_customers returns list, but mcp.tool version returns JSON string.
    # In qb_client tests we are calling the class method directly which returns list of dicts.
    
    assert len(customers_json) == 1
    assert customers_json[0]["DisplayName"] == "Test Customer"
    assert customers_json[0]["Balance"] == 50.0

@patch('httpx.Client.request')
def test_record_payment(mock_request, qb_client):
    # Mock calls for record_payment which uses get_invoice inside
    
    # 1. Invoice fetch for CustomerRef
    mock_invoice_resp = Mock()
    mock_invoice_resp.json.return_value = {"Invoice": {"CustomerRef": {"value": "CUST1"}}}
    mock_invoice_resp.raise_for_status.return_value = None
    
    # 2. Payment creation
    mock_payment_resp = Mock()
    mock_payment_resp.json.return_value = {"Payment": {"Id": "PAY1", "TotalAmt": 100.0}}
    mock_payment_resp.raise_for_status.return_value = None
    
    mock_request.side_effect = [mock_invoice_resp, mock_payment_resp]

    payment = qb_client.record_payment("INV1", 100.0, "2024-02-04", reference_number="REF999")
    assert payment["Id"] == "PAY1"
    assert mock_request.call_count == 2

@patch('httpx.Client.request')
def test_error_handling_401(mock_request, qb_client):
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"Fault": {"Error": [{"Message": "Unauthorized"}]}}
    mock_response.headers = {"Content-Type": "application/json"}
    
    error = httpx.HTTPStatusError("401 Unauthorized", request=Mock(), response=mock_response)
    mock_request.side_effect = error

    with pytest.raises(httpx.HTTPStatusError):
        qb_client.get_invoice("123")

@patch('httpx.Client.request')
def test_error_handling_429_rate_limit(mock_request, qb_client):
    mock_response = Mock()
    mock_response.status_code = 429
    mock_response.headers = {"Content-Type": "text/plain"}
    mock_response.text = "Too Many Requests"
    
    error = httpx.HTTPStatusError("429 Too Many Requests", request=Mock(), response=mock_response)
    mock_request.side_effect = error

    with pytest.raises(httpx.HTTPStatusError):
        qb_client.get_invoice("123")

@patch('httpx.Client.request')
def test_error_handling_403_forbidden(mock_request, qb_client):
    mock_response = Mock()
    mock_response.status_code = 403
    mock_response.json.return_value = {"Fault": {"Error": [{"Message": "Permission Denied"}]}}
    mock_response.headers = {"Content-Type": "application/json"}
    
    error = httpx.HTTPStatusError("403 Forbidden", request=Mock(), response=mock_response)
    mock_request.side_effect = error

    with pytest.raises(httpx.HTTPStatusError):
        qb_client.search_customers("test")

@patch('httpx.Client.request')
def test_create_customer(mock_request, qb_client):
    mock_response = Mock()
    mock_response.json.return_value = {
        "Customer": {"Id": "CUST2", "DisplayName": "New Corp"}
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    customer = qb_client.create_customer("New Corp", "new@corp.com", phone="123456", notes="VIP")
    assert customer["Id"] == "CUST2"
    assert mock_request.call_args[1]["json"]["DisplayName"] == "New Corp"
    assert mock_request.call_args[1]["json"]["PrimaryPhone"]["FreeFormNumber"] == "123456"
    assert mock_request.call_args[1]["json"]["Notes"] == "VIP"

@patch('httpx.Client.request')
def test_record_payment(mock_request, qb_client):
    # Mock get_invoice call first which record_payment uses internally
    mock_invoice_response = Mock()
    mock_invoice_response.json.return_value = {
        "Invoice": {"CustomerRef": {"value": "CUST1"}}
    }
    mock_invoice_response.raise_for_status.return_value = None
    
    # Mock payment response
    mock_payment_response = Mock()
    mock_payment_response.json.return_value = {
        "Payment": {"Id": "PAY1", "TotalAmt": 100.0}
    }
    mock_payment_response.raise_for_status.return_value = None
    
    mock_request.side_effect = [mock_invoice_response, mock_payment_response]

    payment = qb_client.record_payment("INV1", 100.0, "2024-02-04", reference_number="REF999")
    assert payment["Id"] == "PAY1"
    assert mock_request.call_count == 2
    assert mock_request.call_args[1]["json"]["PaymentRefNum"] == "REF999"

@patch('httpx.Client.request')
def test_create_expense(mock_request, qb_client):
    mock_response = Mock()
    mock_response.json.return_value = {
        "Purchase": {"Id": "EXP1", "TotalAmt": 50.0}
    }
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    expense = qb_client.create_expense("Vendor A", 50.0, "60", memo="Lunch")
    assert expense["Id"] == "EXP1"
    assert mock_request.call_args[1]["json"]["AccountRef"]["value"] == "60"
    assert mock_request.call_args[1]["json"]["PrivateNote"] == "Lunch"

@patch('httpx.Client.request')
def test_search_customers_empty(mock_request, qb_client):
    mock_response = Mock()
    mock_response.json.return_value = {"QueryResponse": {}} # QBO returns empty QueryResponse if no matches
    mock_response.raise_for_status.return_value = None
    mock_request.return_value = mock_response

    customers = qb_client.search_customers("NonExistent")
    assert customers == []