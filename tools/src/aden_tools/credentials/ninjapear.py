"""
NinjaPear (Nubela) tool credentials.

Contains credentials for the NinjaPear API — company and people enrichment.
API reference: https://nubela.co/docs/
"""

from .base import CredentialSpec

NINJAPEAR_CREDENTIALS = {
    "ninjapear": CredentialSpec(
        env_var="NINJAPEAR_API_KEY",
        tools=[
            "ninjapear_get_person_profile",
            "ninjapear_get_company_details",
            "ninjapear_get_company_funding",
            "ninjapear_get_company_updates",
            "ninjapear_get_company_customers",
            "ninjapear_get_company_competitors",
            "ninjapear_get_credit_balance",
        ],
        required=True,
        startup_required=False,
        help_url="https://nubela.co/docs/",
        description="NinjaPear API key for company and people enrichment",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a NinjaPear API key:
1. Sign up at https://nubela.co/ using a WORK email address
   (free email providers such as Gmail, Outlook, Yahoo are not accepted)
2. Go to your Dashboard > API section
3. Copy your API key

Note: NinjaPear uses a credit system. Credits are only consumed on HTTP 200 responses.
- Free trial: small credit allocation (work email required to register)
- Paid: credit packs purchased as needed
- Credit costs per call:
  - ninjapear_get_person_profile: 3 credits
  - ninjapear_get_company_details: 2-5 credits
  - ninjapear_get_company_funding: 2+ credits (1 credit per investor)
  - ninjapear_get_company_updates: 2 credits
  - ninjapear_get_company_customers: 1 + 2 credits/company returned
  - ninjapear_get_company_competitors: 5 credits minimum
  - ninjapear_get_credit_balance: FREE (0 credits)

Set the environment variable:
  export NINJAPEAR_API_KEY=your-api-key""",
        health_check_endpoint="https://nubela.co/api/v1/meta/credit-balance",
        health_check_method="GET",
        credential_id="ninjapear",
        credential_key="api_key",
    ),
}
