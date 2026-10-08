# QuickBooks Tool

Manage customers, invoices, payments, and company info using the QuickBooks Online API.

## Tools

| Tool | Description |
|------|-------------|
| `quickbooks_query` | Run a QuickBooks SQL-like query |
| `quickbooks_get_entity` | Get any entity by type and ID |
| `quickbooks_create_customer` | Create a new customer |
| `quickbooks_create_invoice` | Create a new invoice |
| `quickbooks_get_company_info` | Get company information |
| `quickbooks_list_invoices` | List invoices with date and status filters |
| `quickbooks_get_customer` | Get a customer by ID |
| `quickbooks_create_payment` | Record a payment against an invoice |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `QUICKBOOKS_ACCESS_TOKEN` | OAuth2 access token |
| `QUICKBOOKS_REALM_ID` | QuickBooks company/realm ID |

Get credentials at: [Intuit Developer Portal](https://developer.intuit.com/)

## Usage Examples

### Query customers
```python
quickbooks_query(query="SELECT * FROM Customer WHERE DisplayName LIKE '%Acme%'")
```

### Create a customer
```python
quickbooks_create_customer(display_name="Acme Corp", email="billing@acme.com")
```

### Create an invoice
```python
quickbooks_create_invoice(
    customer_id="123",
    line_items=[{"description": "Consulting", "amount": 5000, "quantity": 1}],
)
```

### List recent invoices
```python
quickbooks_list_invoices(start_date="2026-01-01", status="Overdue")
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "QUICKBOOKS_ACCESS_TOKEN and QUICKBOOKS_REALM_ID are required", "help": "Set QUICKBOOKS_ACCESS_TOKEN and QUICKBOOKS_REALM_ID environment variables"}
{"error": "QuickBooks API error (HTTP 401): AuthenticationFailed"}
{"error": "Request timed out"}
```
