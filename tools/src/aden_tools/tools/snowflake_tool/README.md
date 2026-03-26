# Snowflake Tool

Execute SQL statements against Snowflake via the REST API v2.

## Supported Actions

- **snowflake_execute_sql** – Submit a SQL statement for execution (returns statement handle for async queries)
- **snowflake_get_statement_status** – Check the status and retrieve results of a submitted statement
- **snowflake_cancel_statement** – Cancel a running statement

## Setup

1. Generate a Snowflake OAuth token or use key-pair authentication.

2. Set the required environment variables:
   ```bash
   export SNOWFLAKE_ACCOUNT=your-account-identifier    # e.g., xy12345.us-east-1
   export SNOWFLAKE_TOKEN=your-oauth-or-jwt-token
   ```

3. Optionally set defaults:
   ```bash
   export SNOWFLAKE_WAREHOUSE=COMPUTE_WH
   export SNOWFLAKE_DATABASE=MY_DB
   export SNOWFLAKE_SCHEMA=PUBLIC
   ```

## Use Case

Example: "Run a daily query to aggregate transaction volumes by merchant category and check if any category exceeds the 30-day rolling average by more than 2 standard deviations."
