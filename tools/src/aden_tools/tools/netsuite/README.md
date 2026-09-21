 
 # NetSuite
Manage ERP records and business operations via the NetSuite REST API.

 ## Setup
 ```py
 # Required – NetSuite account credentials
export NETSUITE_ACCOUNT_ID=123456

# OAuth Consumer credentials
export NETSUITE_CONSUMER_KEY=xxx
export NETSUITE_CONSUMER_SECRET=xxx

# Token based authentication
export NETSUITE_TOKEN_ID=xxx
export NETSUITE_TOKEN_SECRET=xxx
```
## All Tools (21 total)

### Customers(5)

|          Tool           |         Description       |
|-------------------------|---------------------------|
|netsuite_create_customer | Create new customer record|
|netsuite_get_customer    | Fetch customer info       |
|netsuite_update_customer | Update customer           |
|netsuite_lost_customers  | List customers             |
|netsuite_delete_customer | Delete a customer         |


### Invoices(4)

|          Tool         | Description    |
|-----------------------|----------------|
|netsuite_create_invoice| Create invoice |
|netsuite_get_invoice   | Fetch invoice  |
|netsuite_update_invoice| Update invoice |
|netsuite_delete_invoice| delete invoice |


### Sales(4)
|          Tool             | Description       |
|---------------------------|-------------------|
|netsuite_list_sales_order  | List sales order  |
|netsuite_get_sales_order   | Get sales order   |
|netsuite_create_sales_order| Create sales order|
|netsuite_delete_sales_order| Delete sales order|


### Vendor(4)

|          Tool         | Description   |
|-----------------------|---------------|
|netsuite_list_vendors  | List vendors  |
|netsuite_create_vendor | Create vendor |
|netsuite_get_vendor    | Get a vendor  |
|netsuite_delete_vendor | Delete vendor |


### Transactions(4)
|          Tool              | Description        |
|----------------------------|--------------------|
|netsuite_list_transactions  | List transactions  |
|netsuite_create_transaction | Create transaction |
|netsuite_get_transaction    | Get transaction    |
|netsuite_delete_transactions| Delete transaction |


## Required Permissions
Configure an Integration Role in NetSuite with the following permissions:
- Customers
- Transactions
- Sales Orders
- Vendors
- Invoices


## Examples Usage
```py
netsuite_create_customer(
    company_name="xxx Inc",
    email="sales@axxx.com",
    phone="555-1234"
)
```
```py 
netsuite_create_invoice(
    customer_id=1234,
    item_id=567,
    quantity=2,
    rate=150,
    currency="USD"
)
```


## Error Codes
| Error | Meaning |
|------|---------|
| 401 | Unauthorized |
| 403 | Permission error |
| 404 | Record not found |
| 429 | Rate limit |


## Example response
{
 "type": "https://docs.oracle.com/errors/not-found",
 "title": "Record Not Found",
 "status": 404
}


## API Reference
This tool interacts with the NetSuite REST Record API.
Common endpoints include:
- POST /record/v1/customer  
- GET  /record/v1/customer/{id}  
- POST /record/v1/invoice  
- GET  /record/v1/## Error Codes
