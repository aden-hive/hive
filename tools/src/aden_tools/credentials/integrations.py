"""Registry of credentials for enterprise integrations (CRM, ERP, etc.)."""

from .base import CredentialSpec

INTEGRATION_CREDENTIALS = {
    "dynamics365": CredentialSpec(
        env_var="DYNAMICS365_CREDENTIALS",
        tools=[
            "dynamics365_search_accounts",
            "dynamics365_get_account",
            "dynamics365_create_account",
            "dynamics365_update_account",
            "dynamics365_delete_account",
            "dynamics365_search_contacts",
            "dynamics365_create_contact",
            "dynamics365_search_opportunities",
            "dynamics365_create_opportunity",
            "dynamics365_check_inventory",
            "dynamics365_search_invoices",
        ],
        description="Microsoft Dynamics 365 credentials (tenant_id:client_id:client_secret:environment)",
        help_url="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/AppRegistrationsBlade",
    ),
}
