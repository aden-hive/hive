# Local credential parity: aliases, identity, status, and credential tester integration

## Summary

Gives local API key credentials (Brave Search, GitHub, Exa, Stripe, etc.) the same feature set as Aden OAuth credentials: named aliases, identity metadata, status tracking, CRUD management, and full visibility in the credential tester.

Fixes a bug where credentials configured with the existing `store_credential` MCP tool were invisible in the credential tester account picker.

---

## Changes

### New: `core/framework/credentials/local/`

**`models.py`** — `LocalAccountInfo` dataclass mirroring `AdenIntegrationInfo`:
- Fields: `credential_id`, `alias`, `status` (`active` / `failed` / `unknown`), `identity`, `last_validated`, `created_at`
- `storage_id` property returns `"{credential_id}/{alias}"` (e.g. `brave_search/work`)
- `to_account_dict()` returns same shape as Aden account dicts — feeds account picker without changes

**`registry.py`** — `LocalCredentialRegistry`, the core engine:
- `save_account(credential_id, alias, api_key)` — runs health check, extracts identity, stores at `{credential_id}/{alias}` in `EncryptedFileStorage`
- `list_accounts(credential_id=None)` — reads all `{x}/{y}` entries from storage
- `get_key(credential_id, alias)` — returns raw secret
- `delete_account(credential_id, alias)` — removes entry
- `validate_account(credential_id, alias)` — re-runs health check, updates `_status` and `last_refreshed` in-place
- `default()` classmethod — uses `~/.hive/credentials`

Storage convention: `{credential_id}/{alias}` as `CredentialObject.id`. Legacy flat entries (`brave_search`, no slash) continue to work — env var fallback is unchanged.

---

### Modified: `tools/src/aden_tools/credentials/store_adapter.py`

- `get(name, account=None)` — added `account=` param for per-call routing to a named local account; mirrors Aden `account=` routing
- `activate_local_account(credential_id, alias)` — injects a named account's key into `os.environ[spec.env_var]` for session-level activation
- `list_local_accounts(credential_id=None)` — delegates to `LocalCredentialRegistry`

---

### Modified: `core/framework/credentials/__init__.py`

Exports `LocalAccountInfo` and `LocalCredentialRegistry`.

---

### Modified: `core/framework/agents/credential_tester/agent.py`

Full rewrite of account listing and configuration:

- `_list_aden_accounts()` — extracted from old `list_connected_accounts()`
- `_list_local_accounts()` — uses `LocalCredentialRegistry`
- `_list_env_fallback_accounts()` — detects credentials configured via env var **or** in old flat encrypted format; fixes the invisible-credential bug
- `list_connected_accounts()` — combines all three, deduplicates
- `configure_for_account()` — branches on `source` field:
  - `"aden"` → adds `get_account_info` tool, prompts with `account="alias"`
  - `"local"` → calls `_activate_local_account()`, prompt has no `account=` param
- `_activate_local_account()` — handles three cases: named registry entry, old flat encrypted entry, env var already set; also handles grouped credentials (e.g. `google_custom_search` sets both `GOOGLE_API_KEY` and `GOOGLE_CSE_ID`)
- `get_tools_for_provider()` — fixed to match both `credential_id` AND `credential_group`

---

### Modified: `core/framework/mcp/agent_builder_server.py`

- `store_credential(name, value, alias="default", ...)` — added `alias` param; now delegates to `LocalCredentialRegistry.save_account()` with auto health check; returns `status` and `identity`
- `list_stored_credentials()` — delegates to `LocalCredentialRegistry.list_accounts()`; returns `credential_id`, `alias`, `status`, `identity`, `last_validated`
- `delete_stored_credential(name, alias="default")` — added `alias` param
- `validate_credential(name, alias="default")` — **new tool** — re-runs health check via `LocalCredentialRegistry.validate_account()`, returns updated status and identity

---

### Modified: `core/framework/tui/screens/account_selection.py`

- Aden accounts rendered first, local accounts second
- Local accounts display a `[local]` badge
- Identity label shows email, username, or workspace when available

---

### New: `core/framework/tui/screens/add_local_credential.py`

Two-phase modal for adding a named local API key:

1. **Type selection** — filtered list of all `direct_api_key_supported=True` credentials
2. **Form** — alias input + password input → "Test & Save" runs health check inline, shows identity result, auto-dismisses on success

Exported from `core/framework/tui/screens/__init__.py`.

---

## Bug fix

**Credential tester not showing configured credentials** (e.g. Brave Search stored via `store_credential`):

- `_list_env_fallback_accounts()` previously used `CredentialStoreAdapter.with_env_storage()`, which only checked `os.environ`. Credentials stored in `EncryptedFileStorage` with the old flat format (`brave_search`, no slash) were invisible.
- `_activate_local_account()` early-returned when `alias == "default"`, assuming the env var was already set. Old flat encrypted credentials are not in `os.environ`.

**Fix**: `_list_env_fallback_accounts()` now also reads `EncryptedFileStorage.list_all()` and treats any flat entry (no `/`) as configured. `_activate_local_account()` now falls through to load from the flat encrypted entry when the env var is not set and the registry has no named entry.

---

## Test plan

- [ ] `store_credential("brave_search", "BSA-xxx", alias="work")` → health check runs, identity shown, stored as `brave_search/work`
- [ ] `list_stored_credentials()` → shows `credential_id`, `alias`, `status`, `identity`, `last_validated`
- [ ] `validate_credential("brave_search", "work")` → re-runs health check, updates status
- [ ] `delete_stored_credential("brave_search", alias="work")` → removes entry
- [ ] Credential tester account picker shows local accounts with `[local]` badge alongside Aden accounts
- [ ] Selecting a local account activates the key and tools work without `account=` param
- [ ] Selecting a legacy flat credential (stored before this PR) activates it correctly
- [ ] `AddLocalCredentialScreen` — select type, enter alias + key, health check runs inline, screen closes on success
- [ ] `CredentialStoreAdapter.get("brave_search", account="work")` returns key from registry
