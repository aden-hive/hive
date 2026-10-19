# Zoho CRM Tool

Integration with Zoho CRM for managing leads, contacts, accounts, deals, and notes via the Zoho CRM API v8.

## Overview

This tool enables Hive agents to:

- Search records by word or criteria
- Get, create, and update records in Leads, Contacts, Accounts, and Deals
- Add notes to any supported record

## Available Tools

Five MCP tools (Phase 1):

- `zoho_crm_search` – Search records in a module (`criteria` or `word` required)
- `zoho_crm_get_record` – Fetch a single record by ID
- `zoho_crm_create_record` – Create a new record
- `zoho_crm_update_record` – Update an existing record
- `zoho_crm_add_note` – Add a note to a record (Leads, Contacts, Accounts, Deals)

## Setup: What You Need vs What We Do

### What the user must provide (one-time)

Zoho uses OAuth2. The user does **not** give us an access token for normal use. They give us three values (get them once from [Zoho API Console](https://api-console.zoho.com/)):

| Env var                                                 | Required?          | What it is                                                                                                                                                                                                                |
| ------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ZOHO_CLIENT_ID**                                | Yes (refresh flow) | From Zoho API Console → your client                                                                                                                                                                                      |
| **ZOHO_CLIENT_SECRET**                            | Yes (refresh flow) | From Zoho API Console → your client                                                                                                                                                                                      |
| **ZOHO_REFRESH_TOKEN**                            | Yes (refresh flow) | From one-time OAuth or Self Client flow (see below)                                                                                                                                                                       |
| **ZOHO_ACCOUNTS_DOMAIN** or **ZOHO_REGION** | Yes (refresh flow) | Region: set `ZOHO_ACCOUNTS_DOMAIN` (full URL) **or** `ZOHO_REGION`. Valid `ZOHO_REGION`: **in**, **us**, **eu**, **au**, **jp**, **uk**, **sg** (exact codes only). |

When refresh flow is used, we derive API routing from Zoho token metadata (`api_domain`) and use it for CRM calls.

**When using access token only (no refresh flow):**

| Env var                   | When to set                                                                   |
| ------------------------- | ----------------------------------------------------------------------------- |
| **ZOHO_API_DOMAIN** | Strongly recommended — set to your region (e.g.`https://www.zohoapis.in`). If omitted, code falls back to `https://www.zohoapis.com` (US). |



### What we do for the user

- **Access token:** We get it ourselves by exchanging the refresh token. The user never pastes an access token unless they choose the “access token only” option.
- **Access token expiry:** When using the refresh flow, we get a new access token whenever needed (they expire in ~1 hour). The user does not need to “make a new one” — we use the refresh token to get a fresh access token each time (or the credential store does it if configured).
- **Region/routing:** For refresh flow you set either `ZOHO_ACCOUNTS_DOMAIN` (full URL) or `ZOHO_REGION` (`us`, `in`, `eu`, etc.). After token exchange, Zoho returns `api_domain` (e.g. `https://www.zohoapis.in`), which we use for CRM API calls.

### How to start using the refresh flow

1. Get **Client ID**, **Client Secret**, and **Refresh token** once from Zoho .
2. Set environment variables. Use either **ZOHO_ACCOUNTS_DOMAIN** or **ZOHO_REGION**:

```bash
export ZOHO_CLIENT_ID="your_client_id"
export ZOHO_CLIENT_SECRET="your_client_secret"
export ZOHO_REFRESH_TOKEN="your_refresh_token"
# One of:
export ZOHO_ACCOUNTS_DOMAIN="https://accounts.zoho.in"   # or .com / .eu
export ZOHO_REGION="in"   # valid: in, us, eu, au, jp, uk, sg
```

**Access token only (quick test):**
Set `ZOHO_ACCESS_TOKEN` and preferably **ZOHO_API_DOMAIN** for your DC. Token expires in ~1 h.

```bash
export ZOHO_ACCESS_TOKEN="1000.xxxx..."
export ZOHO_API_DOMAIN="https://www.zohoapis.in"   # your region
```

3. Use the tools as usual. The first call exchanges the refresh token; we use Zoho's returned `api_domain` for CRM calls. You do not set or refresh the access token yourself.

### Credential Store (optional)

For auto-refresh and production, store the OAuth2 credential and register the Zoho provider:

```python
from framework.credentials import CredentialStore
from framework.credentials.oauth2 import ZohoOAuth2Provider

zoho_provider = ZohoOAuth2Provider(
    client_id=os.getenv("ZOHO_CLIENT_ID", ""),
    client_secret=os.getenv("ZOHO_CLIENT_SECRET", ""),
    accounts_domain=os.getenv("ZOHO_ACCOUNTS_DOMAIN", "https://accounts.zoho.com"),
)
store = CredentialStore.with_encrypted_storage(providers=[zoho_provider])
```

## Usage

### zoho_crm_search

Search records in a module. The API requires at least one of: `word`, `criteria`, `email`, or `phone`.

**Arguments:**

- `module` (str, required) – One of: Leads, Contacts, Accounts, Deals
- `criteria` (str, default: "") – Zoho criteria, e.g. `(Email:equals:user@example.com)`
- `page` (int, default: 1) – Page number
- `per_page` (int, default: 200) – Records per page (1–200)
- `fields` (list[str], optional) – Field API names to return
- `word` (str, default: "") – Optional full-text search word

**Example:**

```python
# Search with criteria
zoho_crm_search(module="Contacts", criteria="(Email:equals:john@example.com)")

# Search by word
zoho_crm_search(module="Leads", word="Zoho", page=1, per_page=10)
```

### zoho_crm_get_record

Fetch a single record by ID.

**Arguments:**

- `module` (str, required) – Leads, Contacts, Accounts, or Deals
- `id` (str, required) – Record ID

**Example:**

```python
zoho_crm_get_record(module="Leads", id="1192161000000585006")
```

### zoho_crm_create_record

Create a new record. Use field API names (e.g. `First_Name`, `Last_Name`, `Company`).

**Arguments:**

- `module` (str, required) – Leads, Contacts, Accounts, or Deals
- `data` (dict, required) – Field API name → value

**Example:**

```python
zoho_crm_create_record(
    module="Leads",
    data={"First_Name": "Jane", "Last_Name": "Doe", "Company": "Acme Inc", "Email": "jane@acme.com"}
)
```

### zoho_crm_update_record

Update an existing record. Send only the fields you want to change.

**Arguments:**

- `module` (str, required) – Leads, Contacts, Accounts, or Deals
- `id` (str, required) – Record ID
- `data` (dict, required) – Field API name → value

**Example:**

```python
zoho_crm_update_record(module="Leads", id="1192161000000585006", data={"Description": "Follow up next week"})
```

### zoho_crm_add_note

Add a note to a record. The note appears in the record’s Notes section in Zoho CRM.

**Arguments:**

- `module` (str, required) – Parent module (Leads, Contacts, Accounts, Deals)
- `id` (str, required) – Parent record ID
- `note_title` (str, required) – Title of the note
- `note_content` (str, required) – Body of the note

**Example:**

```python
zoho_crm_add_note(
    module="Leads",
    id="1192161000000585006",
    note_title="Call back",
    note_content="Customer asked for pricing by Friday."
)
```

## Response Format

- **Success:** `{"success": true, "id": "...|null", "module": "...", "data": ..., "raw": {...}, ...}`
- **Error:** `{"error": "Description", "retriable": true}` (optional, for rate limits)
- Search pagination includes `more_records` and `next_page` (`null` when no next page).

## Testing

Unit tests (mocked HTTP):

```bash
uv run pytest tools/src/aden_tools/tools/zoho_crm_tool/tests/test_zoho_crm_tool.py -v
```

## API Reference

- [Zoho CRM API v8](https://www.zoho.com/crm/developer/docs/api/v8/)
