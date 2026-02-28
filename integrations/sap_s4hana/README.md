# SAP S/4HANA Integration

Read-only integration for SAP S/4HANA procurement data.

## Supported Operations

- Fetch Purchase Orders
- Fetch Vendor/Supplier Master Data
- Get Purchase Order by ID
- Health Check Connection

## Configuration

Set environment variables:
```bash
export SAP_BASE_URL="https://your-sap-server:port/sap/opu/odata/sap"
export SAP_USERNAME="your_username"
export SAP_PASSWORD="your_password"
export SAP_CLIENT="100"
export SAP_VERIFY_SSL="true"

## USAGE

from integrations.sap_s4hana import create_sap_connector_from_env

connector = create_sap_connector_from_env()

# Fetch purchase orders
pos = connector.fetch_purchase_orders(filters={"Supplier": "12345"})

# Fetch vendors
vendors = connector.fetch_vendors()

# Get specific PO
po = connector.get_purchase_order_by_id("4500000001")

## API Coverage
This integration uses SAP's standard OData APIs:
- API_PURCHASEORDER_SRV for purchase orders
- API_BUSINESS_PARTNER for vendor data

## Security
- Uses HTTP Basic Authentication
- Supports SSL verification (configurable)
- Read-only operations (no write access)
- Credentials stored via Hive credential system