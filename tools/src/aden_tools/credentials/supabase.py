"""Credentials for Supabase integration."""

from .base import CredentialSpec

SUPABASE_CREDENTIALS = {
    "supabase_url": CredentialSpec(
        env_var="SUPABASE_URL",
        description="The unique Supabase URL for your project",
        required=False,
    ),
    "supabase_service_role_key": CredentialSpec(
        env_var="SUPABASE_SERVICE_ROLE_KEY",
        description="The service role key for backend access (Warning: Has full admin rights)",
        required=False,
    ),
    "supabase_anon_key": CredentialSpec(
        env_var="SUPABASE_ANON_KEY",
        description="The anonymous key for client-side access (Respects RLS)",
        required=False,
    ),
}
