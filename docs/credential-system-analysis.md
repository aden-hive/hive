# Credential System: Complete Code Path Analysis

## Architecture Overview

```
                      ┌──────────────┐
                      │  AgentRunner  │  runner.py:_validate_credentials()
                      └──────┬───────┘
                             │
                      ┌──────▼───────┐
                      │  validation  │  validate_agent_credentials()
                      │  (2-phase)   │  Phase 1: presence  Phase 2: health check
                      └──────┬───────┘
                             │
               ┌─────────────▼─────────────┐
               │     CredentialStore        │  store.py
               │  (cache + provider mgmt)   │
               └─────────────┬─────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
  ┌──────▼──────┐    ┌──────▼──────┐    ┌───────▼───────┐
  │ EnvVarStorage│    │ Encrypted   │    │ AdenCached    │
  │ (primary)    │    │ FileStorage │    │ Storage       │
  └─────────────┘    │ (fallback)  │    │ (Aden sync)   │
                     └─────────────┘    └───────┬───────┘
                                                │
                                        ┌───────▼───────┐
                                        │AdenSyncProvider│
                                        │+ AdenClient    │
                                        └───────────────┘
```

### Key Files

| Layer | File | Purpose |
|-------|------|---------|
| Models | `core/framework/credentials/models.py` | `CredentialObject`, `CredentialKey`, exception hierarchy |
| Storage | `core/framework/credentials/storage.py` | `EncryptedFileStorage`, `EnvVarStorage`, `CompositeStorage` |
| Store | `core/framework/credentials/store.py` | `CredentialStore` — cache, providers, refresh |
| Validation | `core/framework/credentials/validation.py` | `validate_agent_credentials()` — two-phase pre-flight check |
| Setup | `core/framework/credentials/setup.py` | `CredentialSetupSession` — interactive credential collection |
| Aden client | `core/framework/credentials/aden/client.py` | `AdenCredentialClient` — HTTP calls to api.adenhq.com |
| Aden provider | `core/framework/credentials/aden/provider.py` | `AdenSyncProvider` — refresh, sync, fetch |
| Aden storage | `core/framework/credentials/aden/storage.py` | `AdenCachedStorage` — local cache + Aden fallback |
| Specs | `tools/src/aden_tools/credentials/` | `CredentialSpec` per integration (env_var, health check, etc.) |
| Runner | `core/framework/runner/runner.py` | `_validate_credentials()` — agent startup gate |
| TUI | `core/framework/tui/screens/credential_setup.py` | `CredentialSetupScreen` — modal credential form |
| TUI app | `core/framework/tui/app.py` | `_show_credential_setup()`, `_load_and_switch_agent()` |

### Exception Hierarchy

```
CredentialError                    ← base (caught by runner + TUI)
  ├── CredentialDecryptionError    ← corrupted/wrong-key .enc files
  ├── CredentialKeyNotFoundError   ← key name not in credential
  ├── CredentialNotFoundError      ← credential ID not found
  ├── CredentialRefreshError       ← refresh failed (e.g., revoked OAuth)
  └── CredentialValidationError    ← schema/format invalid
```

---

## Scenario 1: User Supplies Correct Credential

### Flow

```
AgentRunner._setup()
  → _ensure_credential_key_env()              # validation.py:16
  │   Loads HIVE_CREDENTIAL_KEY, ADEN_API_KEY from shell config into os.environ
  │
  → _validate_credentials()                    # runner.py:418
      → validate_agent_credentials(nodes)      # validation.py:94
          │
          │ Phase 0: Aden pre-sync (if ADEN_API_KEY set)
          │   → _presync_aden_tokens()         # validation.py:50
          │     → CredentialStore.with_aden_sync(auto_sync=True)
          │     → For each aden_supported spec: get_key() → set os.environ
          │
          │ Build store:
          │   EnvVarStorage (primary) + EncryptedFileStorage (fallback if HIVE_CREDENTIAL_KEY set)
          │
          │ Phase 1: Presence check
          │   → store.is_available(cred_id)
          │     → EnvVarStorage.load() → os.environ[env_var] → CredentialObject ✓
          │   Result: NOT in missing list
          │
          │ Phase 2: Health check (if spec.health_check_endpoint set)
          │   → check_credential_health(cred_name, value)
          │     e.g., Anthropic: POST /v1/messages → 400 (key valid, request malformed) → valid=True
          │     e.g., Brave:     GET /search?q=test → 200 → valid=True
          │   Result: NOT in invalid list
          │
          │ errors = [] → returns normally ✓
```

### What Happens

- Validation passes silently
- Agent loads and runs
- No files written, no user-visible output
- `CredentialStore._cache` populated (5-min TTL)

---

## Scenario 2: User Supplies Wrong Credential

### Flow

```
validate_agent_credentials(nodes)
  │
  │ Phase 1: Presence check
  │   → store.is_available("anthropic")
  │   → EnvVarStorage.load() → os.environ["ANTHROPIC_API_KEY"] = "wrong-key"
  │   → Returns CredentialObject ✓ (value exists, content not validated)
  │   Result: passes presence check, added to to_verify list
  │
  │ Phase 2: Health check
  │   → check_credential_health("anthropic", credential_object)
  │   → AnthropicHealthChecker: POST /v1/messages with x-api-key: "wrong-key"
  │   → Response: 401 Unauthorized
  │   → HealthCheckResult(valid=False, message="API key is invalid")
  │   → Added to invalid list, cred_name added to failed_cred_names
  │
  │ CredentialError raised:
  │   "Invalid or expired credentials:
  │      ANTHROPIC_API_KEY for event_loop nodes — Anthropic API key is invalid
  │      Get a new key at: https://console.anthropic.com/settings/keys"
  │   exc.failed_cred_names = ["anthropic"]
```

### TUI Path (non-interactive)

```
_load_and_switch_agent()                        # app.py:356
  except CredentialError as e:                  # app.py:382
    → _show_credential_setup(agent_path, e)     # app.py:404
      → build_setup_session_from_error(e)       # validation.py:253
        → failed_cred_names = ["anthropic"]
        → Creates MissingCredential for anthropic
      → push_screen(CredentialSetupScreen)
```

### CLI Path (interactive with TTY)

```
_validate_credentials()                          # runner.py:418
  except CredentialError as e:                   # runner.py:440
    → print(str(e), file=sys.stderr)
    → session = build_setup_session_from_error(e)
    → session.run_interactive()                  # Terminal prompts
    → validate_agent_credentials(nodes)          # Re-validate
```

### What User Sees

- TUI: Credential setup modal with the invalid credential's input field
- CLI: Error message printed, interactive prompts

### Silent Failure Risk

If `check_credential_health()` itself throws (network timeout, DNS failure, import error),
it's caught at `validation.py:231`:
```python
except Exception as exc:
    logger.debug("Health check for %s failed: %s", cred_name, exc)
```
The credential is NOT added to `invalid`. **Agent starts with a bad key.** Only `logger.debug`
records the issue.

---

## Scenario 3: Credential Expired But Can Be Refreshed

Applies to OAuth2 credentials (Google, HubSpot, etc.) managed via AdenSyncProvider.

### Flow: Token Refresh During Runtime

```
CredentialStore.get_credential(cred_id, refresh_if_needed=True)   # store.py:176
  │
  │ Check cache → cached credential found
  │ → _should_refresh(cached)                                      # store.py:442
  │   → AdenSyncProvider.should_refresh(credential)                # provider.py:238
  │     → access_key = credential.keys["access_token"]
  │     → datetime.now(UTC) >= (expires_at - 5min buffer)
  │     → Returns True (within refresh window)
  │
  │ → _refresh_credential(cached)                                  # store.py:456
  │   → AdenSyncProvider.refresh(credential)                       # provider.py:151
  │     → client.request_refresh(credential.id)                    # client.py:356
  │       → POST /v1/credentials/{id}/refresh
  │       → Server refreshes OAuth token, returns new access_token
  │     → _update_credential_from_aden(credential, response)
  │       → Updates access_token value + expires_at
  │   → storage.save(refreshed)                                    # Writes new .enc file
  │   → _add_to_cache(refreshed)                                   # Updates in-memory cache
  │   → Returns refreshed credential ✓
```

### Flow: Expired Token Caught During Validation

```
validate_agent_credentials(nodes)
  │
  │ Phase 0: _presync_aden_tokens()
  │   → CredentialStore.with_aden_sync(auto_sync=True)
  │   → provider.sync_all() fetches fresh tokens from Aden
  │   → Fresh token set in os.environ ✓
  │
  │ Phase 2: Health check with fresh token → valid=True ✓
```

### What Happens

- Refresh is transparent to the user
- New token written to `~/.hive/credentials/credentials/{id}.enc`
- In-memory cache updated
- Logged: `INFO: Refreshed credential '{id}' via Aden server`

---

## Scenario 4: Credential Expired and Cannot Be Refreshed

OAuth refresh token is revoked (user disconnected integration on hive.adenhq.com, or
the refresh token itself expired).

### Flow: Refresh Attempt

```
AdenSyncProvider.refresh(credential)                    # provider.py:151
  → client.request_refresh(credential.id)               # client.py:356
    → POST /v1/credentials/{id}/refresh
    → Response: 400 {"error": "refresh_failed",
    │                 "requires_reauthorization": true,
    │                 "reauthorization_url": "https://..."}
    → AdenRefreshError raised                            # client.py:297

  except AdenRefreshError as e:                          # provider.py:186
    → logger.error("Aden refresh failed for '{id}': ...")
    → raise CredentialRefreshError(
        "Integration '{id}' requires re-authorization. Visit: ..."
      )
```

### What CredentialStore Does

```
CredentialStore._refresh_credential(credential)          # store.py:456
  except CredentialRefreshError as e:                    # store.py:474
    → logger.error("Failed to refresh credential '{id}': ...")
    → return credential   ← RETURNS STALE/EXPIRED CREDENTIAL!
```

**BUG: Silent failure.** The store returns the expired credential without raising.
The caller gets an expired token. Downstream API calls fail with 401.

### During Validation

If validation runs health check on the expired token:
```
check_credential_health() → 401 → valid=False
→ Added to invalid list → CredentialError raised
→ TUI shows credential setup screen
```

### Gap: Token Expires After Validation

If the token expires **during agent execution** (after validation passed):
- Refresh fails silently (returns stale credential)
- Tool call gets 401 from downstream API
- LLM sees tool error, no framework-level recovery

---

## Scenario 5: Credential Store File Sabotaged (Wrong Content)

File `~/.hive/credentials/credentials/{id}.enc` replaced with valid Fernet-encrypted
content encoding wrong JSON (e.g., `{"bad": "data"}`).

### Flow

```
EncryptedFileStorage.load(credential_id)              # storage.py:193
  → fernet.decrypt(encrypted)                         # Succeeds (valid Fernet)
  → json.loads(decrypted)                             # Succeeds (valid JSON)
  → _deserialize_credential(data)                     # storage.py:252
    → CredentialObject.model_validate({"bad": "data"})
```

### Sub-case A: Missing `id` field

```
CredentialObject.model_validate({"bad": "data"})
  → Pydantic ValidationError: "id - Field required"
  → NOT caught by EncryptedFileStorage's try/except (only covers decrypt + json.loads)
  → Propagates up uncaught
```

**TUI**: Caught by generic `except Exception` in `_load_and_switch_agent()` (app.py:389):
```
self.notify("Failed to load agent: 1 validation error for CredentialObject...", severity="error")
```
User sees generic error notification. NOT a credential setup screen. **Not actionable.**

**CLI**: Unhandled traceback.

### Sub-case B: Valid `id` but wrong/empty keys

```
CredentialObject.model_validate({"id": "my_cred", "keys": {}})
  → Valid CredentialObject with keys={} (Pydantic extra="allow", keys defaults to {})
  → store.is_available() → get_credential() returns CredentialObject
  → But get() / get_key() returns None → is_available returns False
  → Treated as "missing" credential
```

User sees credential setup screen as if the credential was never configured.
**The actual cause (sabotaged file) is hidden.**

---

## Scenario 6: Credential Store File Corrupted (Binary Garbage)

File `~/.hive/credentials/credentials/{id}.enc` contains random binary data.

### Flow

```
EncryptedFileStorage.load(credential_id)              # storage.py:193
  → fernet.decrypt(binary_garbage)
  → Raises cryptography.fernet.InvalidToken
  → Caught by except Exception:                       # storage.py:210
    → raise CredentialDecryptionError(
        "Failed to decrypt credential '{id}': InvalidToken"
      )
```

### Propagation

```
CredentialDecryptionError (subclass of CredentialError)
  → CompositeStorage.load(): NOT caught → propagates
  → CredentialStore.get_credential(): NOT caught → propagates
  → validate_agent_credentials() → propagates out entirely
```

**TUI** (app.py:382):
```python
except CredentialError as e:   # CATCHES CredentialDecryptionError
    self._show_credential_setup(str(agent_path), credential_error=e)
```
Shows credential setup screen! But `CredentialDecryptionError` does NOT have
`failed_cred_names` attribute → `getattr(e, "failed_cred_names", [])` returns `[]`
→ session falls back to `from_agent_path()` detection.

User sees credential setup screen as if credential is missing.
**Corruption is hidden.** Re-entering the credential overwrites the corrupted file.

### CompositeStorage Bug

If `CompositeStorage(primary=EnvVarStorage, fallbacks=[EncryptedFileStorage])` is used,
the storage tries primary first. But if `EncryptedFileStorage` is a fallback and
the .enc file is corrupted:
```
CompositeStorage.load()
  → primary (EnvVarStorage) → env var IS set → returns CredentialObject ✓
```
The corrupted fallback is never touched. **This case works fine.**

But if the storage order is reversed (encrypted primary, env fallback):
```
CompositeStorage.load()
  → primary (EncryptedFileStorage) → CredentialDecryptionError
  → NOT caught → propagates  ← BUG: fallback never tried
```
The exception from primary propagates BEFORE checking the fallback.
**A corrupted .enc file blocks access even when the env var has a valid value.**

---

## Scenario 7: ADEN_API_KEY Set But Vendor OAuth Not Authorized

User has valid `ADEN_API_KEY`. Agent needs HubSpot/Google. User has NOT connected
that integration on hive.adenhq.com.

### Flow

```
validate_agent_credentials(nodes)
  │
  │ Phase 0: _presync_aden_tokens()
  │   → CredentialStore.with_aden_sync(auto_sync=True)
  │   → provider.sync_all(store)
  │     → client.list_integrations()           # GET /v1/credentials
  │     → HubSpot NOT in response (never connected)
  │     → Only connected integrations synced
  │
  │   → For hubspot spec: get_key("hubspot", "access_token")
  │     → AdenCachedStorage.load("hubspot")
  │       → _provider_index.get("hubspot") → None (not synced)
  │       → _load_by_id("hubspot")
  │         → local: None (not cached)
  │         → aden: fetch_from_aden("hubspot")
  │           → GET /v1/credentials/hubspot → 404
  │           → AdenNotFoundError caught → returns None
  │       → Returns None
  │     → get_key returns None
  │   → os.environ["HUBSPOT_ACCESS_TOKEN"] NOT set
  │
  │ Phase 1: Presence check
  │   → _check_credential(hubspot_spec, "hubspot", "hubspot tools")
  │   → store.is_available("hubspot") → False
  │   → has_aden_key=True, aden_supported=True, direct_api_key_supported=False
  │   → Goes into aden_not_connected list (NOT failed_cred_names)
  │
  │ CredentialError raised:
  │   "Aden integrations not connected (ADEN_API_KEY is set but OAuth tokens unavailable):
  │      HUBSPOT_ACCESS_TOKEN for hubspot tools
  │      Connect this integration at hive.adenhq.com first."
  │   exc.failed_cred_names = []   ← empty!
```

### TUI Behavior

```
_show_credential_setup(agent_path, credential_error=e)
  → build_setup_session_from_error(e)
  → failed_cred_names = [] → falls back to from_agent_path()
  → detect_missing_credentials_from_nodes() finds hubspot missing
  → session.missing = [MissingCredential(hubspot, aden_supported=True, ...)]
  → NOT empty → CredentialSetupScreen pushed
```

Setup screen shows ADEN_API_KEY input (already set). User clicks "Save & Continue":
```
_save_credentials()
  → ADEN_API_KEY already in env → configured += 1
  → _sync_aden_credentials()
    → provider.sync_all() → hubspot still not connected → synced=0
    → Notification: "No active integrations found in Aden."
    → For hubspot: store.is_available("hubspot") → False
    → Notification: "hubspot (id='hubspot') not found in Aden."
  → configured > 0 → dismiss(True)
```

TUI retries `_do_load_agent()` → validation fails again → **LOOP.**

### What User Sees

1. Setup screen appears, ADEN_API_KEY field shown
2. User clicks Save
3. Warning: "hubspot not found in Aden. Connect this integration at hive.adenhq.com first."
4. Screen dismisses (configured=1 from ADEN_API_KEY)
5. Agent reload fails → setup screen appears again
6. Repeat forever

### Root Cause

`configured += 1` fires when ADEN_API_KEY is saved, even though the actual needed
credential (hubspot OAuth token) was NOT obtained. The screen dismisses with "success"
but the agent still can't load.

---

## Known Silent Failure Points

| # | Location | What Happens | Risk |
|---|----------|-------------|------|
| 1 | `validation.py:231` | `check_credential_health()` throws → `logger.debug()` → credential treated as valid | Agent starts with bad key |
| 2 | `store.py:474-476` | `CredentialRefreshError` caught → returns stale credential | Tool calls fail with 401 at runtime |
| 3 | `store.py:706-708` | `with_aden_sync()` catches all Exception → falls back to local-only store silently | Aden sync failure invisible |
| 4 | `provider.py:312-313` | Individual integration sync fails → `logger.warning()` → skipped | Integration silently missing |
| 5 | `credential_setup.py:262-263` | `_persist_to_local_store()` → `except Exception: pass` | Credential lost on restart |
| 6 | `storage.py:489-501` | `CompositeStorage.load()` doesn't catch primary storage exceptions | Corrupted .enc blocks env var fallback |
| 7 | `validation.py:63-65` | `_presync_aden_tokens()` catches all Exception → `logger.warning()` | Aden tokens not refreshed, stale values used |

---

## Storage Priority Order

### During Validation (`validate_agent_credentials`)

```
1. os.environ (via EnvVarStorage)           ← WINS if set
2. ~/.hive/credentials/credentials/*.enc    ← fallback (only if HIVE_CREDENTIAL_KEY set)
```

### During Runtime (`CredentialStoreAdapter.default()`)

```
1. EncryptedFileStorage                     ← primary (if HIVE_CREDENTIAL_KEY set)
2. EnvVarStorage                            ← fallback
3. AdenSyncProvider                         ← if ADEN_API_KEY set, auto-refresh on access
```

**Note: validation and runtime use DIFFERENT storage priority orders.** Validation
prefers env vars; runtime prefers encrypted store. This means a credential can pass
validation (from env) but fail at runtime (encrypted store has stale value and env
var was only set in the validation process, not persisted).

### During TUI Credential Setup (`_sync_aden_credentials`)

```
1. AdenSyncProvider.sync_all()              ← fetches from Aden API
2. AdenCachedStorage                        ← local encrypted cache
   (no EnvVarStorage in this path)
```

---

## File Locations on Disk

```
~/.hive/
  credentials/
    credentials/                            # EncryptedFileStorage base
      {credential_id}.enc                   # Fernet-encrypted JSON
    key.txt                                 # HIVE_CREDENTIAL_KEY (generated if missing)
  configuration.json                        # Global config
```

### .enc File Format (decrypted)

```json
{
  "id": "hubspot",
  "credential_type": "oauth2",
  "keys": {
    "access_token": {
      "name": "access_token",
      "value": "ya29.a0ARrdaM...",
      "expires_at": "2025-01-15T12:00:00+00:00"
    },
    "_aden_managed": {
      "name": "_aden_managed",
      "value": "true"
    },
    "_integration_type": {
      "name": "_integration_type",
      "value": "hubspot"
    }
  },
  "provider_id": "aden_sync",
  "auto_refresh": true
}
```

The `_integration_type` key is used by `AdenCachedStorage._index_provider()` to map
provider names (e.g., "hubspot") to hash-based credential IDs from Aden.
