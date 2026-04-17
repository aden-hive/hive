# Shopify Tool

Order, product, and customer management via the Shopify Admin REST API.

## Tools

| Tool | Description |
|------|-------------|
| `shopify_list_orders` | List orders with optional status and fulfillment filters |
| `shopify_get_order` | Get full details of a specific order by ID |
| `shopify_update_order` | Update order tags or internal note |
| `shopify_cancel_order` | Cancel an order (optional restock/email/refund) |
| `shopify_refund_order` | Refund an order via the store payment gateway |
| `shopify_list_products` | List products with optional status, type, and vendor filters |
| `shopify_get_product` | Get full product details including variants and images |
| `shopify_update_product` | Update title, body_html, status, tags, or vendor of a product |
| `shopify_list_customers` | List customers in the store |
| `shopify_get_customer` | Get full customer details including addresses and order stats |
| `shopify_search_customers` | Search customers by email, name, or other fields |
| `shopify_create_draft_order` | Create a draft order with line items |
| `shopify_send_draft_order_invoice` | Send a draft order invoice email to collect payment |

## Setup

Requires a Shopify Custom App access token and your store name:

1. Go to your Shopify admin → **Settings → Apps and sales channels → Develop apps**
2. Create a custom app and install it with the required API scopes
3. Copy the **Admin API access token** from the app credentials

```bash
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
SHOPIFY_STORE_NAME=your-store-name
```

> `SHOPIFY_STORE_NAME` is the subdomain of your store. For `https://my-shop.myshopify.com`, use `my-shop`.

Required API scopes:
- `read_orders`, `write_orders` — order management
- `read_products`, `write_products` — product management
- `read_customers`, `write_customers` — customer management
- `read_draft_orders`, `write_draft_orders` — draft order creation

## Usage Examples

### List open orders

```python
shopify_list_orders(status="open", limit=50)
```

### List paid but unfulfilled orders

```python
shopify_list_orders(
    financial_status="paid",
    fulfillment_status="unshipped",
    limit=25,
)
```

### Get a specific order

```python
shopify_get_order(order_id="5678901234")
```

### Update an order's tags / note

```python
shopify_update_order(
    order_id="5678901234",
    tags="vip,needs_followup",
    note="Customer requested delivery window 2-4pm",
)
```

### Cancel an order

```python
shopify_cancel_order(
    order_id="5678901234",
    reason="customer",
    restock=True,
    email=True,
    refund=False,
)
```

### Refund an order

```python
shopify_refund_order(
    order_id="5678901234",
    amount="199.00",
    note="Customer requested refund",
    notify=False,
)
```

### List active products

```python
shopify_list_products(status="active", limit=50)
```

### Get a specific product

```python
shopify_get_product(product_id="1234567890")
```

### Update a product

```python
shopify_update_product(
    product_id="1234567890",
    title="Updated Product Name",
    status="active",
    tags="sale,featured",
)
```

### List customers

```python
shopify_list_customers(limit=100)
```

### Search customers by email

```python
shopify_search_customers(query="email:alice@example.com")
```

### Search customers by name

```python
shopify_search_customers(query="first_name:Alice")
```

### Create a draft order

```python
shopify_create_draft_order(
    line_items_json='[{"variant_id": 12345678, "quantity": 2}]',
    customer_id="987654321",
    note="VIP order",
    tags="manual,vip",
)
```

### Send draft order invoice email (collect payment)

```python
shopify_send_draft_order_invoice(
    draft_order_id="123456789",
    subject="Invoice for your order",
    custom_message="Thanks! Please complete payment using the link in this invoice.",
)
```

## Order Status Values

| Filter | Values |
|--------|--------|
| `status` | `open`, `closed`, `cancelled`, `any` |
| `financial_status` | `paid`, `pending`, `refunded`, `voided` |
| `fulfillment_status` | `fulfilled`, `partial`, `on_hold`, `null` (unfulfilled) |

> **Note:** `fulfillment_status=null` filters for unfulfilled orders. Shopify silently ignores unrecognized filter values rather than returning an error.

## Error Handling

All tools return error dicts on failure:

```python
{"error": "Shopify credentials not configured", "help": "Set SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_NAME environment variables or configure via credential store"}
{"error": "Invalid Shopify access token"}
{"error": "Insufficient API scopes for this Shopify resource"}
{"error": "Shopify rate limit exceeded. Try again later."}
```
