"""
SAP S/4HANA Cloud credentials.

Contains credentials for the SAP S/4HANA Cloud OData APIs.
Requires SAP_BASE_URL, SAP_USERNAME, and SAP_PASSWORD.
"""

from .base import CredentialSpec

SAP_CREDENTIALS = {
    "sap_base_url": CredentialSpec(
        env_var="SAP_BASE_URL",
        tools=[
            "sap_list_purchase_orders",
            "sap_get_purchase_order",
            "sap_list_business_partners",
            "sap_list_products",
            "sap_list_sales_orders",
        ],
        required=True,
        startup_required=False,
        help_url="https://api.sap.com/package/SAPS4HANACloud/odata",
        description="SAP S/4HANA Cloud base URL (e.g. 'https://tenant-api.s4hana.ondemand.com')",
        direct_api_key_supported=True,
        api_key_instructions="""To set up SAP S/4HANA Cloud API access:
1. Create a Communication User in S/4HANA Cloud
2. Set up Communication Arrangements for the APIs you need
3. Set environment variables:
   export SAP_BASE_URL=https://your-tenant-api.s4hana.ondemand.com
   export SAP_USERNAME=your-communication-user
   export SAP_PASSWORD=your-password""",
        health_check_endpoint="",
        credential_id="sap_base_url",
        credential_key="api_key",
    ),
    "sap_username": CredentialSpec(
        env_var="SAP_USERNAME",
        tools=[
            "sap_list_purchase_orders",
            "sap_get_purchase_order",
            "sap_list_business_partners",
            "sap_list_products",
            "sap_list_sales_orders",
        ],
        required=True,
        startup_required=False,
        help_url="https://api.sap.com/package/SAPS4HANACloud/odata",
        description="SAP S/4HANA Communication User username",
        direct_api_key_supported=True,
        api_key_instructions="""See SAP_BASE_URL instructions above.""",
        health_check_endpoint="",
        credential_id="sap_username",
        credential_key="api_key",
    ),
    "sap_password": CredentialSpec(
        env_var="SAP_PASSWORD",
        tools=[
            "sap_list_purchase_orders",
            "sap_get_purchase_order",
            "sap_list_business_partners",
            "sap_list_products",
            "sap_list_sales_orders",
        ],
        required=True,
        startup_required=False,
        help_url="https://api.sap.com/package/SAPS4HANACloud/odata",
        description="SAP S/4HANA Communication User password",
        direct_api_key_supported=True,
        api_key_instructions="""See SAP_BASE_URL instructions above.""",
        health_check_endpoint="",
        credential_id="sap_password",
        credential_key="api_key",
    ),
}
