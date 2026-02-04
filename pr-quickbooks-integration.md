Implement QuickBooks Integration

# Description
Implements QuickBooks Online integration for the Hive agent framework to enable automated accounting and financial operations.

## Features
- Create and retrieve invoices
- Search and create customers
- Record payments against invoices
- Track business expenses
- Integration with credential management system
- MCP tool registration

## Tools Added
- `quickbooks_create_invoice`: Create invoices for customers
- `quickbooks_get_invoice`: Retrieve complete invoice details
- `quickbooks_search_customers`: Search for customers by name, email, or ID
- `quickbooks_create_customer`: Add new customers to QuickBooks
- `quickbooks_record_payment`: Record payments against invoices
- `quickbooks_create_expense`: Track business expenses and bills

## Authentication
- Requires `QUICKBOOKS_ACCESS_TOKEN` (OAuth 2.0)
- Requires `QUICKBOOKS_REALM_ID` (Company ID)

## Testing
- Unit tests added in `tools/tests/tools/test_quickbooks_tool.py`
- Verified using `pytest` in `agents` environment

## Related Issue
- Addresses issue #2996
