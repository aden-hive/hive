"""
Shopify Admin REST API credentials.

Contains credentials for the Shopify Admin API.
Requires SHOPIFY_ACCESS_TOKEN and SHOPIFY_STORE_NAME.
"""

from .base import CredentialSpec

SHOPIFY_CREDENTIALS = {
    "shopify": CredentialSpec(
        env_var="SHOPIFY_ACCESS_TOKEN",
        tools=[
            "shopify_list_orders",
            "shopify_get_order",
            "shopify_list_products",
            "shopify_get_product",
            "shopify_list_customers",
            "shopify_search_customers",
            "shopify_update_product",
            "shopify_get_customer",
            "shopify_create_draft_order",
        ],
        required=True,
        startup_required=False,
        help_url="https://shopify.dev/docs/api/admin-rest",
        description="Shopify Admin API access token (starts with shpat_)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Shopify Admin API access:
1. In Shopify Admin, go to Settings > Apps and sales channels > Develop apps
2. Create a custom app with scopes: read_orders, read_products, read_customers
3. Install the app and reveal the Admin API access token
4. Set environment variables:
   export SHOPIFY_ACCESS_TOKEN=shpat_your-token
   export SHOPIFY_STORE_NAME=your-store-name""",
        health_check_endpoint="",
        credential_id="shopify",
        credential_key="api_key",
    ),
    "shopify_store_name": CredentialSpec(
        env_var="SHOPIFY_STORE_NAME",
        tools=[
            "shopify_list_orders",
            "shopify_get_order",
            "shopify_list_products",
            "shopify_get_product",
            "shopify_list_customers",
            "shopify_search_customers",
            "shopify_update_product",
            "shopify_get_customer",
            "shopify_create_draft_order",
        ],
        required=True,
        startup_required=False,
        help_url="https://shopify.dev/docs/api/admin-rest",
        description="Shopify store subdomain (e.g. 'my-store' from my-store.myshopify.com)",
        direct_api_key_supported=True,
        api_key_instructions="""See SHOPIFY_ACCESS_TOKEN instructions above.""",
        health_check_endpoint="",
        credential_id="shopify_store_name",
        credential_key="api_key",
    ),
}
