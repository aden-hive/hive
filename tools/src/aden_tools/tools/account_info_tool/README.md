# Account Info Tool

The Account Info tool allows Aden Hive agents to query the available identities and connected accounts in the current runtime environment. This helps agents understand which credentials they have access to before attempting to use provider-specific tools.

## Features

- **List All Accounts**: Retrieve a list of all accounts currently configured in the Hive credential store.
- **Provider Filtering**: Filter accounts by provider name (e.g., "google", "github", "hubspot").
- **Identity Labels**: See identity markers like email, username, or workspace ID associated with each credential.

## Tools

### `get_account_info`
Lists connected accounts and their identities.
- **provider**: Optional string to filter by provider type.

## Use Cases

Agents can use this tool to:
1. Confirm if a user has connected their HubSpot or Slack account.
2. Choose the correct account alias when multiple accounts for the same provider are available.
3. Inform the user about missing credentials required for a specific task.
