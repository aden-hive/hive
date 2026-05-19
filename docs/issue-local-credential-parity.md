# Local API key credentials lack feature parity with Aden OAuth credentials

## Summary

The credential tester only surfaces accounts synced via Aden OAuth (requires `ADEN_API_KEY`). Users who authenticate services with a direct API key — Brave Search, GitHub, Exa, Google Maps, Stripe, Telegram, and many others — have no way to list, manage, or test those credentials through the same interface.

## Problem

Local API key credentials are completely flat today:

- **No namespace** — one env var per service (`BRAVE_SEARCH_API_KEY`), no aliases, no multi-account support
- **No identity metadata** — no way to record who owns a key (email, username, workspace)
- **No status tracking** — no "active / failed / unknown" state
- **Not visible in credential tester** — the account picker only calls the Aden API; it silently shows nothing if `ADEN_API_KEY` is absent
- **No management surface** — no list/add/delete/validate flow for API keys

Aden credentials have all of this: `integration_id`, alias, identity, status, health-check-on-sync, and a full listing API.

## Affected credentials (local-only by default)

Brave Search, Exa Search, Google Search (CSE), SerpAPI, GitHub, Google Maps, Telegram, Apollo, Stripe, Razorpay, Cal.com, BigQuery, GCP Vision, Resend, and more.

## Expected behavior

- Running the credential tester should surface **all** configured credentials — Aden-synced and local API keys together, in the same account picker
- Local API key accounts should support aliases (`work`, `personal`) so users can store multiple keys per service
- Identity metadata (username, email, workspace) should be extracted automatically via health check when a key is saved
- A status badge (`active` / `failed` / `unknown`) should indicate whether the key was last verified successfully
- The TUI should provide an "Add Local Credential" screen with a live health check
- The MCP `store_credential` / `list_stored_credentials` / `delete_stored_credential` tools should support aliases; a new `validate_credential` tool should allow re-checking a stored key at any time

## Root cause (bonus bug)

Even credentials configured with the existing `store_credential` MCP tool are invisible in the credential tester because:

1. `_list_env_fallback_accounts()` only checked env vars — it missed credentials stored in `EncryptedFileStorage` using the old flat format (`brave_search`, no alias)
2. `_activate_local_account()` early-returned for `alias == "default"`, assuming the env var was already set — but old flat encrypted credentials are not in `os.environ`
