# SAP Tool

Access SAP S/4HANA data via OData APIs — purchase orders, business partners, products, and sales orders.

## Tools

| Tool | Description |
|------|-------------|
| `sap_list_purchase_orders` | List purchase orders with optional filters |
| `sap_get_purchase_order` | Get details of a specific purchase order |
| `sap_list_business_partners` | List business partners with search and category filters |
| `sap_list_products` | List products with optional search |
| `sap_list_sales_orders` | List sales orders with customer and date filters |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `SAP_BASE_URL` | SAP S/4HANA OData base URL |
| `SAP_USERNAME` | SAP username for Basic Auth |
| `SAP_PASSWORD` | SAP password for Basic Auth |

Get credentials from your SAP system administrator.

## Usage Examples

### List purchase orders
```python
sap_list_purchase_orders(top=20)
```

### Get a specific purchase order
```python
sap_get_purchase_order(purchase_order="4500000001")
```

### Search business partners
```python
sap_list_business_partners(search="Acme", category="supplier", top=10)
```

### List recent sales orders
```python
sap_list_sales_orders(top=20)
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "SAP_BASE_URL, SAP_USERNAME, and SAP_PASSWORD are required", "help": "Set SAP_BASE_URL, SAP_USERNAME, and SAP_PASSWORD environment variables"}
{"error": "SAP API error (HTTP 404): Resource not found"}
{"error": "Request timed out"}
```
