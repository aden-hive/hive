"""
Supabase credentials.

Contains credentials for Supabase database, auth, and edge functions.
"""

from .base import CredentialSpec

SUPABASE_CREDENTIALS = {
    "supabase": CredentialSpec(
        env_var="SUPABASE_ANON_KEY",
        tools=[
            "supabase_select",
            "supabase_insert",
            "supabase_update",
            "supabase_delete",
            "supabase_auth_signup",
            "supabase_auth_signin",
            "supabase_edge_invoke",
        ],
        required=True,
        startup_required=False,
        help_url="https://supabase.com/dashboard",
        description="Supabase anon/public API key (also requires SUPABASE_URL env var)",
        direct_api_key_supported=True,
        api_key_instructions="""To get Supabase credentials:
1. Go to https://supabase.com/dashboard
2. Create a new project or select an existing one
3. Go to Project Settings → API
4. Copy the 'anon' / 'public' key (starts with eyJ...)
5. Copy the Project URL (https://<ref>.supabase.co)
6. Set both environment variables:
   export SUPABASE_ANON_KEY=your-anon-key
   export SUPABASE_URL=https://your-project.supabase.co""",
        health_check_endpoint="",
        credential_id="supabase",
        credential_key="anon_key",
    ),
}
