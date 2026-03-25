# Supabase Tool

Database queries, authentication, and edge function invocation via the Supabase REST API.

## Supported Actions

### Database (PostgREST)
- **supabase_select** – Query rows with filters, ordering, and pagination
- **supabase_insert** – Insert one or more rows
- **supabase_update** – Update rows matching a filter
- **supabase_delete** – Delete rows matching a filter

### Authentication (GoTrue)
- **supabase_auth_signup** – Create a new user account
- **supabase_auth_signin** – Sign in with email and password

### Edge Functions
- **supabase_edge_invoke** – Invoke a deployed edge function with custom payload

## Setup

1. Get your project URL and API keys from the [Supabase Dashboard](https://supabase.com/dashboard) (Settings → API).

2. Set the required environment variables:
   ```bash
   export SUPABASE_URL=https://your-project-id.supabase.co
   export SUPABASE_KEY=your-anon-or-service-role-key
   ```

   Use the **anon key** for client-side operations or the **service role key** for admin operations (bypasses Row Level Security).

## Use Case

Example: "Query the `orders` table for all pending orders from the last 24 hours, invoke the `process-payment` edge function for each, and update their status to 'completed'."
