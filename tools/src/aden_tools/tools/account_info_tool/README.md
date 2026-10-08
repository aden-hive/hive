# Account Info Tool

Query connected accounts and their identities at runtime.

## Features

- **get_account_info** - List connected accounts with provider and identity details

## Overview

This tool allows agents to discover which external accounts are connected and available for use. It queries the credential store to retrieve account metadata without exposing secrets.

## Setup

No additional configuration required. The tool reads from the configured credential store.

## Usage Examples

### List All Connected Accounts
```python
get_account_info()
```

Returns:
```python
{
    "accounts": [
        {
            "account_id": "google_main",
            "provider": "google",
            "identity": "user@gmail.com"
        },
        {
            "account_id": "slack_workspace",
            "provider": "slack",
            "identity": "My Workspace"
        }
    ],
    "count": 2
}
```

### Filter by Provider
```python
get_account_info(provider="google")
```

Returns only Google-connected accounts:
```python
{
    "accounts": [
        {
            "account_id": "google_main",
            "provider": "google",
            "identity": "user@gmail.com"
        }
    ],
    "count": 1
}
```

## API Reference

### get_account_info

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| provider | str | No | Filter by provider type (e.g., "google", "slack") |

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| accounts | list | List of connected account objects |
| count | int | Number of accounts returned |

### Account Object

| Field | Type | Description |
|-------|------|-------------|
| account_id | str | Unique identifier for the account |
| provider | str | Provider type (google, slack, github, etc.) |
| identity | str | Human-readable identity (email, username, workspace) |

## Supported Providers

Common providers that may appear:
- `google` - Google accounts (Gmail, Drive, Calendar)
- `slack` - Slack workspaces
- `github` - GitHub accounts
- `hubspot` - HubSpot CRM accounts
- `brevo` - Brevo email/SMS accounts
- And any other configured OAuth or API integrations

## Error Handling
```python
{"accounts": [], "message": "No credential store configured"}
```

## Use Cases

- **Multi-account workflows**: Determine which accounts are available before making API calls
- **User context**: Show users which accounts are connected in chat interfaces
- **Conditional logic**: Route tasks to different accounts based on availability
