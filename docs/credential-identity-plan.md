# Credential Identity & Multi-Account Foundation (Issue #4755)

## Context

Agents are identity-blind. When `gmail_read_email` runs, neither the LLM nor the tool
knows whose inbox it's operating on. One `ADEN_API_KEY` can back N accounts of the same
provider (e.g., 10 Gmail accounts), but today the system can only surface one — the last
one synced silently overwrites all others.

This plan traces the **5-tuple relationship** (Agent Definition → Agent Instance →
Agent Tool → Auth Provider → Auth User Identity) through every layer of the stack,
identifies exactly where things break, and prescribes targeted fixes.

### Motivating Scenarios

**Scenario A — Executive Assistant Agent**: A company deploys an agent that manages
calendars for 5 executives. Each executive has connected their Google account through
Aden. The agent's job is to check each person's availability and schedule meetings.
Today: the agent can only see ONE person's calendar (whichever synced last). The other
4 accounts are silently lost in the index collision. The agent schedules meetings on
the wrong person's calendar with no indication anything is wrong.

**Scenario B — Multi-Channel Support Agent**: A support team agent is connected to
3 Slack workspaces (Engineering, Sales, Support), a shared Gmail inbox, and a personal
Gmail for the team lead. Today: the agent sees one Slack workspace, one Gmail. It
cannot tell which Slack workspace it's posting to or whose Gmail it's reading. It
might reply to a customer email from the team lead's personal inbox.

**Scenario C — Compliance & Audit**: An enterprise client requires audit logs showing
which account was accessed, when, and by which agent. Today: the system logs
`credentials.get("google")` — no record of which of the 10 Google accounts was used.
Impossible to audit.

**Scenario D — Single-Account Agent (backward compat)**: A simple agent uses one
Gmail account and one Slack bot. Nothing should change. `credentials.get("google")`
returns the same token it always did. Zero migration, zero configuration changes.

---

## The 5-Tuple Model

Every credential interaction involves five entities. Understanding how they relate
(and where the relationships break) is the key to the fix.

```
Agent Definition ──→ Agent Instance ──→ Agent Tool ──→ Auth Provider ──→ Auth User Identity
  "I need Gmail"    "Here's your       "Give me a      "Here's one      "Whose token
                     Gmail tool"        token"           token"           is this?"
                                                                          ← MISSING
```

### 1. Agent Definition (what tools are needed)

**Files**: `exports/{name}/agent.py`, `nodes/__init__.py`, `mcp_servers.json`

An exported agent declares `NodeSpec.tools = ["gmail_read_email", "gmail_send_email"]`.
The `mcp_servers.json` points to the tools MCP server. The agent definition has NO
credential awareness — it names tools, not credentials. This is intentional: the same
agent definition can run against different credential sets in different environments
(dev vs. prod, tenant A vs. tenant B).

**Business logic**: Agent definitions are portable templates. A "Gmail Triage" agent
built by one team can be deployed to 50 different customers, each with their own
Google accounts. The agent definition never hard-codes credential IDs.

**Status**: Fine. No changes needed.

### 2. Agent Instance (runtime wiring)

**Files**: `runner.py`, `tool_registry.py`, `mcp_client.py`

`AgentRunner.__init__()` does three things in sequence:
1. `validate_agent_credentials(graph.nodes)` — checks presence + health
2. `ToolRegistry.load_mcp_config()` → `MCPClient` spawns subprocess
3. `_setup()` → `create_agent_runtime()` with discovered tools

The `ToolRegistry` bridges parent ↔ MCP subprocess:
- `CONTEXT_PARAMS = {"workspace_id", "agent_id", "session_id", "data_dir"}` — stripped
  from LLM schema, injected at call time via `make_mcp_executor` closure
- `set_session_context()` — set once at startup
- `set_execution_context()` — per-execution via `contextvars`

The MCP subprocess inherits `os.environ` at spawn time via
`merged_env = {**os.environ, **(config.env or {})}` in `mcp_client.py:157`.

**Business logic**: The agent instance is where "portable template" meets "specific
deployment." An instance knows which Aden API key to use, which workspace it belongs
to, which tools are available. The `CONTEXT_PARAMS` mechanism is how the framework
passes deployment-specific context into tools without the LLM knowing or caring.
This is the natural extension point for `account` routing in the future.

**Scenario**: Two customers both deploy the same "Email Triage" agent. Customer A
has 2 Google accounts; Customer B has 5. Each customer's `AgentRunner` validates
against their own Aden key, discovers different sets of credentials, and wires them
into the same agent graph. The agent definition is identical.

**Status**: Works for single-account. The `CONTEXT_PARAMS` pattern is the right
mechanism for future multi-account routing (adding `account` param).

### 3. Agent Tool (credential consumption)

**Files**: `tools/src/aden_tools/tools/*/`, `tools/mcp_server.py`

Every tool follows the same pattern:
```python
def register_gmail_tools(mcp, credentials=None):
    def _get_token():
        if credentials is not None:
            return credentials.get("google")   # ← single token, identity unknown
        return os.getenv("GOOGLE_ACCESS_TOKEN")

    @mcp.tool()
    def gmail_read_email(message_id: str):
        token = _get_token()
        ...
```

The `credentials` object is `CredentialStoreAdapter`, created once at MCP server startup
via `CredentialStoreAdapter.default()`. All tool closures capture this single shared
instance.

**Business logic**: Tools are the consumer endpoint — they need a valid access token
to call external APIs. They don't care about Aden, sync, or storage. They just need
`_get_token()` to return the right token. Today, "right" is undefined because there's
no way to say "the token for alice@company.com, not bob@company.com."

**Where it breaks — Scenario A revisited**: The executive assistant agent calls
`gmail_read_email()` intending to read Alice's inbox. `_get_token()` returns
`credentials.get("google")` which resolves to... Bob's token (he synced last).
The agent reads Bob's emails, thinks they're Alice's, and schedules meetings
accordingly. No error is raised. No indication anything is wrong. The agent is
confidently operating on the wrong person's data.

**Where it breaks — Scenario B revisited**: The support agent calls
`slack_post_message(channel="support-tickets")`. It uses a Slack token from
the Engineering workspace (last synced). The message goes to a channel that
doesn't exist in Engineering, returns an error, and the agent retries in a loop
with no understanding of why it's failing.

### 4. Auth Provider (credential storage & resolution)

**Files**: `store.py`, `aden/storage.py`, `aden/provider.py`, `aden/client.py`

Resolution chain:
```
credentials.get("google")
→ CredentialStoreAdapter.get("google")
→ CredentialStore.get("google")
→ AdenCachedStorage.load("google")
→ _provider_index.get("google") → "google_def456"  (last write wins)
→ _load_by_id("google_def456")
→ Returns ONE CredentialObject
```

**The index collision bug** (`storage.py:303`):
```python
def _index_provider(self, credential):
    provider_name = integration_type_key.value.get_secret_value()
    self._provider_index[provider_name] = credential.id   # ← OVERWRITES
```

**Business logic**: The storage layer is responsible for mapping human-readable
provider names ("google") to internal hash-based credential IDs ("google_abc123").
This mapping is essential because Aden generates unique hash IDs per connected account,
but tools reference providers by name. The `_provider_index` is this mapping.

**Why it's a `dict[str, str]` today**: The original design assumed 1:1 between
provider name and credential. "One Google account per API key." This was valid
for simple deployments but breaks fundamentally when an Aden API key backs multiple
accounts of the same provider.

**The collision mechanics**: When `sync_all()` runs, it iterates over all active
integrations from Aden. For a user with 3 Gmail accounts:

1. Sync `google_abc123` (alice@co.com) → `_provider_index["google"] = "google_abc123"`
2. Sync `google_def456` (bob@co.com) → `_provider_index["google"] = "google_def456"` ← Alice lost
3. Sync `google_ghi789` (carol@co.com) → `_provider_index["google"] = "google_ghi789"` ← Bob lost

All three `.enc` files exist on disk. Only Carol's is reachable by name. Alice's and
Bob's tokens are orphaned — encrypted, on disk, but invisible to the resolution chain.

**Why the disk layer is fine**: `EncryptedFileStorage` uses the hash ID as filename:
`google_abc123.enc`, `google_def456.enc`. No collision. The problem is purely in the
in-memory index that maps names to IDs.

### 5. Auth User Identity (THE MISSING PIECE)

**Files**: `models.py` (no identity model), `aden/provider.py` (metadata discarded),
`health_check.py` (identity parsed then discarded), `validation.py` (details ignored)

**Business logic**: Identity answers "whose account is this?" Every external service
provides identity data in its API responses — Gmail returns `emailAddress`, GitHub
returns `login`, Slack returns `team` + `user`. This data already flows through the
system during health checks and Aden syncs. It's parsed, briefly held in local
variables, and then discarded. No model captures it. No property exposes it. No
downstream consumer reads it.

Identity data exists at two sources but is discarded:

| Source | Data Available | What Happens |
|--------|---------------|--------------|
| Aden `metadata.email` | Email of connected account | `_aden_response_to_credential()` ignores `metadata` dict |
| Gmail health check | `emailAddress` field | `OAuthBearerHealthChecker.check()` returns `valid=True`, discards response body |
| GitHub health check | `login` username | Parsed to `details["username"]`, validation ignores `details` |
| Slack health check | `team`, `user` | Parsed to `details`, validation ignores `details` |
| Discord health check | `username`, `id` | Parsed to `details`, validation ignores `details` |
| Calendar health check | Primary calendar `id` = email | `OAuthBearerHealthChecker.check()` discards response body |

**The waste**: Every agent startup already makes these health check API calls. The
identity data is RIGHT THERE in the response body. We parse it for validation logic,
then throw it away. Zero additional API calls needed — we just need to keep what we
already have.

**What identity enables downstream**:
- LLM knows whose inbox it's reading (system prompt awareness)
- Tools can route to specific accounts (future `account` parameter)
- Audit logs can record which identity was accessed
- Users can see which accounts are connected in TUI/dashboard
- Agents can reason about cross-account operations ("forward from alice to bob")

---

## What Changes — Layer by Layer

### Step 1: `CredentialIdentity` model on `CredentialObject`

**File**: `core/framework/credentials/models.py`

**Business logic**: Every credential needs a structured way to answer "who does this
belong to?" Different providers express identity differently:

| Provider | Primary Identity | Secondary Identity |
|----------|-----------------|-------------------|
| Google (Gmail, Calendar, Drive) | Email address | — |
| Slack | Workspace name | Bot username |
| GitHub | Username (login) | — |
| Discord | Username | Account ID |
| HubSpot | Portal ID | — |
| Microsoft 365 | Email address | Tenant ID |

The `CredentialIdentity` model normalizes these into four universal fields:
`email`, `username`, `workspace`, `account_id`. The `label` property picks the
best human-readable identifier for display (email preferred, then username, etc.).

**Why a computed property, not a stored field**: Identity is derived from
`_identity_*` keys that already exist in the credential's key vault. Storing it
as a separate field would create a sync problem (what if keys update but the field
doesn't?). A computed property always reflects current state.

**Scenarios this enables**:

- **Display**: `cred.identity.label` → `"alice@company.com"` (for system prompts, TUI, logs)
- **Comparison**: `cred.identity.email == "alice@company.com"` (for account routing)
- **Serialization**: `cred.identity.to_dict()` → `{"email": "alice@company.com"}` (for MCP tool responses)
- **Existence check**: `cred.identity.is_known` → `True` (skip accounts with no identity)
- **Provider type**: `cred.provider_type` → `"google"` (from `_integration_type` key)

**Key design decision**: `set_identity(**fields)` persists as `_identity_*` keys using
the existing `set_key()` method. This means identity survives serialization/deserialization
through `EncryptedFileStorage` without any schema migration. Old credentials without
identity keys simply return `CredentialIdentity()` with all `None` fields and
`label == "unknown"`.

```python
class CredentialIdentity(BaseModel):
    email: str | None = None
    username: str | None = None
    workspace: str | None = None
    account_id: str | None = None

    @property
    def label(self) -> str:
        return self.email or self.username or self.workspace or self.account_id or "unknown"

    @property
    def is_known(self) -> bool:
        return bool(self.email or self.username or self.workspace or self.account_id)

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump().items() if v is not None}
```

On `CredentialObject`:

```python
@property
def identity(self) -> CredentialIdentity:
    fields = {}
    for key_name, key_obj in self.keys.items():
        if key_name.startswith("_identity_"):
            field = key_name[len("_identity_"):]
            fields[field] = key_obj.value.get_secret_value()
    return CredentialIdentity(**{k: v for k, v in fields.items()
                                 if k in CredentialIdentity.model_fields})

@property
def provider_type(self) -> str | None:
    key = self.keys.get("_integration_type")
    return key.value.get_secret_value() if key else None

def set_identity(self, **fields: str) -> None:
    for field_name, value in fields.items():
        if value:
            self.set_key(f"_identity_{field_name}", value)
```

---

### Step 2: Fix storage multi-account index

**File**: `core/framework/credentials/aden/storage.py`

**Business logic**: The core bug. When a user connects multiple accounts of the same
provider type through Aden, all but the last one becomes unreachable. This affects
every multi-account deployment silently — no error, no warning, just missing accounts.

**`_provider_index`**: `dict[str, str]` → `dict[str, list[str]]`

**Before (broken)**:
```
sync google_abc123 (alice)  → index["google"] = "google_abc123"
sync google_def456 (bob)    → index["google"] = "google_def456"  ← alice lost
load("google")              → returns bob's token
```

**After (fixed)**:
```
sync google_abc123 (alice)  → index["google"] = ["google_abc123"]
sync google_def456 (bob)    → index["google"] = ["google_abc123", "google_def456"]
load("google")              → returns alice's token (first = backward compat)
load_all_for_provider("google") → returns [alice, bob]
```

**Backward compatibility contract**: Every existing tool calls `credentials.get("google")`
and expects a single token string back. This MUST continue to work. `load("google")`
returns the first credential in the list — same behavior as before for single-account
deployments, deterministic (first-synced-first-served) for multi-account.

**Scenarios**:

- **Single account** (most common today): `index["google"] = ["google_abc123"]`.
  `load("google")` returns the only entry. Identical behavior to before.

- **Two accounts, same provider**: `index["google"] = ["google_abc123", "google_def456"]`.
  `load("google")` returns first. `load_all_for_provider("google")` returns both.
  Existing tools see no change; new APIs can enumerate.

- **Mixed providers**: `index["google"] = ["google_abc123"], index["slack"] = ["slack_xyz"]`.
  Each provider resolves independently.

- **Credential removed from Aden**: On next `sync_all()`, `rebuild_provider_index()`
  rebuilds from disk. The removed credential's `.enc` file is gone, so it drops from
  the index naturally.

- **`exists()` check**: Validation calls `exists("google")` to check if credentials
  are available before running health checks. Must return `True` if ANY Google account
  exists, not just the last-synced one.

```python
# _index_provider — append, don't overwrite
def _index_provider(self, credential):
    ...
    if provider_name not in self._provider_index:
        self._provider_index[provider_name] = []
    if credential.id not in self._provider_index[provider_name]:
        self._provider_index[provider_name].append(credential.id)

# load — first match (backward compat)
def load(self, credential_id):
    resolved_ids = self._provider_index.get(credential_id)
    if resolved_ids:
        for rid in resolved_ids:
            if rid != credential_id:
                result = self._load_by_id(rid)
                if result is not None:
                    return result
    return self._load_by_id(credential_id)

# NEW: enumerate all accounts
def load_all_for_provider(self, provider_name: str) -> list[CredentialObject]:
    results = []
    for cid in self._provider_index.get(provider_name, []):
        cred = self._load_by_id(cid)
        if cred:
            results.append(cred)
    return results
```

---

### Step 3: Preserve Aden metadata as identity

**File**: `core/framework/credentials/aden/provider.py`

**Business logic**: When a user connects a Google account through Aden's OAuth flow,
the Aden server stores metadata about the connected account — most importantly, the
email address. This metadata comes back in every API response as
`metadata: {"email": "alice@company.com"}`. Today, this metadata is present in
`AdenCredentialResponse.metadata` (the `from_dict()` parser already handles it) but
is never written into the `CredentialObject`'s key vault. It's silently dropped.

**Why Aden metadata is the primary identity source**: Aden captures identity at the
moment of OAuth authorization — the user explicitly grants access, and the Aden server
records who they are. This is more authoritative than health checks because:
1. It's captured at consent time, not at validation time
2. It works even if the health check endpoint is down
3. It's available immediately on first sync, before any health check runs

**When metadata arrives**: Two code paths create/update credentials from Aden responses:

1. **`_aden_response_to_credential()`** — first-time sync. The credential doesn't
   exist locally yet. We're building it from scratch. Metadata should be written as
   `_identity_*` keys in the initial key dict.

2. **`_update_credential_from_aden()`** — token refresh. The credential already exists.
   The access token is updated. Metadata should be written/overwritten as `_identity_*`
   keys on the existing credential object.

**Scenario — first sync**: User connects `alice@company.com` through Aden. Aden
returns `{access_token: "...", metadata: {email: "alice@company.com"}}`. The
credential is created with `_identity_email = "alice@company.com"`. Later,
`cred.identity.email` returns `"alice@company.com"`.

**Scenario — token refresh**: Alice's token expires. Aden refreshes it and returns
updated metadata. `_update_credential_from_aden()` updates the access token AND
refreshes `_identity_email`. If Alice changed her email (e.g., name change), the
identity stays current.

**Scenario — no metadata**: Some Aden integrations may not return metadata (e.g.,
a simple API key integration). The loop `for meta_key, meta_value in (metadata or {}).items()`
safely does nothing. The credential has no `_identity_*` keys, and `cred.identity`
returns `CredentialIdentity()` with `label == "unknown"`.

```python
# In _aden_response_to_credential, after building keys dict:
for meta_key, meta_value in (aden_response.metadata or {}).items():
    if meta_value and isinstance(meta_value, str):
        keys[f"_identity_{meta_key}"] = CredentialKey(
            name=f"_identity_{meta_key}",
            value=SecretStr(meta_value),
        )

# In _update_credential_from_aden, after updating access_token:
for meta_key, meta_value in (aden_response.metadata or {}).items():
    if meta_value and isinstance(meta_value, str):
        credential.keys[f"_identity_{meta_key}"] = CredentialKey(
            name=f"_identity_{meta_key}",
            value=SecretStr(meta_value),
        )
```

---

### Step 4: Extract identity from health checks

**File**: `tools/src/aden_tools/credentials/health_check.py`

**Business logic**: Health checks are the second identity source. Every agent startup
runs `validate_agent_credentials()` which calls provider-specific health check
endpoints. These endpoints return identity data as a side effect of validation:

| Health Check Endpoint | What It Returns | Identity We Extract |
|----------------------|----------------|-------------------|
| Gmail: `GET /users/me/profile` | `{emailAddress, messagesTotal, ...}` | `email = emailAddress` |
| Calendar: `GET /users/me/calendarList` | `{items: [{id, primary, ...}]}` | `email = primary calendar id` |
| Slack: `POST auth.test` | `{ok, team, user, bot_id, ...}` | `workspace = team, username = user` |
| GitHub: `GET /user` | `{login, id, name, ...}` | `username = login` |
| Discord: `GET /users/@me` | `{username, id, ...}` | `username = username` |

**Why health checks matter as an identity source**:

1. **Fallback when Aden metadata is missing**: Not all Aden integrations return
   metadata. The health check always hits the actual service, so identity is always
   available on success.

2. **Ground truth verification**: Aden metadata is captured at OAuth time. If the
   user's email changed since then, the health check returns the CURRENT identity.

3. **Non-Aden credentials**: When credentials are configured via environment
   variables (no Aden), health checks are the ONLY identity source. A dev sets
   `GOOGLE_ACCESS_TOKEN` manually — the health check reveals whose token it is.

4. **Zero additional cost**: The health check API call is already happening. We
   just need to parse the response body that's currently discarded after the
   status code check.

**Design — `_extract_identity()` hook**: The base `OAuthBearerHealthChecker` gets
a new virtual method `_extract_identity(data: dict) -> dict[str, str]` that subclasses
override. The `check()` method calls it when the response is 200 OK:

```python
class OAuthBearerHealthChecker:
    def _extract_identity(self, data: dict) -> dict[str, str]:
        """Override to extract identity fields from successful response."""
        return {}

    def check(self, access_token: str) -> HealthCheckResult:
        ...
        if response.status_code == 200:
            identity = {}
            try:
                data = response.json()
                identity = self._extract_identity(data)
            except Exception:
                pass  # Identity extraction is best-effort
            return HealthCheckResult(
                valid=True,
                message=f"{self.service_name} credentials valid",
                details={"identity": identity} if identity else {},
            )
```

**Why `details["identity"]`**: The existing `HealthCheckResult` has a `details: dict`
field that's used ad-hoc by different checkers. By putting identity under a standardized
`"identity"` key, Step 5 can generically extract it without knowing which checker
ran. Existing `details` fields (`username`, `team`, `bot_id`) continue to exist
alongside — no breaking changes.

**Standalone checkers** (Slack, GitHub, Discord) don't extend `OAuthBearerHealthChecker`.
They already parse identity data into their `details` dict. For these, we simply add
an `"identity"` key with the structured fields alongside existing keys.

**Scenario — Gmail health check enriches a credential without Aden metadata**: A dev
sets `GOOGLE_ACCESS_TOKEN` as an env var. The credential has no `_identity_*` keys.
On startup, the Gmail health check calls `/users/me/profile`, gets
`{emailAddress: "dev@gmail.com"}`, returns `details={"identity": {"email": "dev@gmail.com"}}`.
Step 5 persists this. Now `cred.identity.email` works even without Aden.

**Scenario — health check fails**: Token is expired or revoked. Response is 401.
No identity extracted (identity extraction only runs on 200). The health check
returns `valid=False`. Step 5 skips persistence. The credential's existing identity
(if any, from Aden metadata) remains unchanged.

**Scenario — identity extraction throws**: The response body is malformed or missing
expected fields. The `try/except` in `check()` catches it. Health check still returns
`valid=True` (the token worked). Identity is just not extracted. Best-effort, never
blocks validation.

---

### Step 5: Persist identity during validation

**File**: `core/framework/credentials/validation.py`

**Business logic**: Steps 3 and 4 produce identity data. Step 5 is the bridge that
takes identity from health check results and persists it to the credential store.
This runs during `validate_agent_credentials()`, which is called at every agent startup.

**Why persist during validation**: Validation is the natural lifecycle hook because:
1. It runs on every agent startup (guaranteed execution)
2. It already has access to the credential store
3. It already runs health checks (identity is available in the result)
4. It runs BEFORE the agent executes (identity is available for system prompt injection)

**Flow**:
```
Agent startup
→ validate_agent_credentials()
  → for each credential:
    → check_credential_health(token) → HealthCheckResult
    → if result.valid AND result.details["identity"] exists:
      → cred_obj = store.get_credential(cred_id)
      → cred_obj.set_identity(**identity_data)
      → store.save_credential(cred_obj)  ← persisted to disk
```

**Scenario — identity from health check augments Aden metadata**: Aden provides
`metadata.email = "alice@company.com"` (stored as `_identity_email` in Step 3).
The Slack health check returns `identity: {workspace: "Acme Corp", username: "hive-bot"}`.
Step 5 adds `_identity_workspace` and `_identity_username` to the Slack credential.
Now both credentials have rich identity data from their respective sources.

**Scenario — identity update on restart**: Between agent runs, the GitHub user
renamed from `old-username` to `new-username`. On next startup, the health check
returns `identity: {username: "new-username"}`. Step 5 calls `set_identity(username="new-username")`,
which overwrites `_identity_username`. The credential now reflects the current identity.

**Scenario — multiple accounts of same provider**: With the index fix (Step 2),
`validate_agent_credentials()` iterates over all credentials. Each Google account
gets its own health check. Each health check returns a different `emailAddress`.
Each identity is persisted to the correct `CredentialObject`. Account A gets
`_identity_email = "alice@co.com"`, Account B gets `_identity_email = "bob@co.com"`.

**Error handling**: Identity persistence is best-effort. If `get_credential()` fails
or `save_credential()` fails, the exception is caught and swallowed. The agent still
starts. The credential still works. It just won't have identity data for that account.
This is acceptable because identity is informational, not functional.

```python
if result.valid:
    identity_data = result.details.get("identity")
    if identity_data and isinstance(identity_data, dict):
        try:
            cred_obj = store.get_credential(cred_id, refresh_if_needed=False)
            if cred_obj:
                cred_obj.set_identity(**identity_data)
                store.save_credential(cred_obj)
        except Exception:
            pass  # Identity persistence is best-effort
```

---

### Step 6: Account listing & identity APIs

**Files**: `core/framework/credentials/store.py`, `tools/src/aden_tools/credentials/store_adapter.py`

**Business logic**: Steps 1-5 populate identity data. Step 6 exposes it through
clean APIs. Two layers need new methods:

1. **`CredentialStore`** (framework layer) — knows about `CredentialObject` and storage
2. **`CredentialStoreAdapter`** (tool boundary) — wraps the store with `CredentialSpec`-aware
   APIs, sits in the MCP subprocess, consumed by tools

**Why two layers**: The store is a framework concept (core/). The adapter is a tools
concept (tools/). Tools never import from core directly. The adapter bridges the gap,
translating between credential IDs and spec names, handling the "is this credential
configured and available?" logic.

**APIs added to `CredentialStore`**:

- `list_accounts(provider_name)` — returns all accounts for a provider type with
  their identities. Delegates to `storage.load_all_for_provider()` (Step 2). Returns
  a list of dicts, not raw `CredentialObject`s, to avoid leaking secrets upstream.

- `get_credential_by_identity(provider_name, label)` — finds a specific account by
  matching `cred.identity.label` against the provided label. This is the resolution
  mechanism for future multi-account routing: "give me the token for alice@co.com."

**APIs added to `CredentialStoreAdapter`**:

- `get_identity(name)` — returns the identity dict for a named credential spec.
  Used by tools that want to know whose token they're using for logging/display.

- `list_accounts(provider_name)` — delegates to store. Used by the `get_account_info`
  MCP tool (Step 8).

- `get_all_account_info()` — iterates over all configured credential specs, collects
  all accounts across all providers. Used to build the system prompt (Step 7).
  Deduplicates by provider name to avoid listing the same provider's accounts twice
  when multiple specs map to the same provider.

- `get_by_identity(provider_name, label)` — resolves a specific account's token by
  identity label. Used by future multi-account routing (Step 9). Returns a raw token
  string, not a `CredentialObject`.

**Scenario — system prompt building**: At agent startup, the runner calls
`adapter.get_all_account_info()`. The adapter iterates over specs:
`{"gmail": CredentialSpec(credential_id="google"), "gcal": CredentialSpec(credential_id="google"), "slack": CredentialSpec(...)}`.
It deduplicates by provider: `google` and `slack`. For `google`, `list_accounts("google")`
returns 2 accounts. For `slack`, 1 account. Result: 3 account entries for the system prompt.

**Scenario — identity-based routing (future)**: The LLM calls
`gmail_read_email(account="alice@co.com")`. The tool calls
`credentials.get_by_identity("google", "alice@co.com")`. The adapter delegates to
`store.get_credential_by_identity("google", "alice@co.com")` which scans all Google
credentials, finds the one where `identity.label == "alice@co.com"`, and returns
its access token. The right inbox is read.

```python
# CredentialStore
def list_accounts(self, provider_name: str) -> list[dict[str, Any]]:
    if hasattr(self._storage, 'load_all_for_provider'):
        creds = self._storage.load_all_for_provider(provider_name)
    else:
        cred = self.get_credential(provider_name)
        creds = [cred] if cred else []
    return [
        {"credential_id": c.id, "provider": provider_name,
         "identity": c.identity.to_dict(), "label": c.identity.label}
        for c in creds
    ]

def get_credential_by_identity(self, provider_name: str, label: str) -> CredentialObject | None:
    if hasattr(self._storage, 'load_all_for_provider'):
        for cred in self._storage.load_all_for_provider(provider_name):
            if cred.identity.label == label:
                return cred
    return None
```

```python
# CredentialStoreAdapter
def get_all_account_info(self) -> list[dict[str, Any]]:
    accounts = []
    seen: set[str] = set()
    for name, spec in self._specs.items():
        provider = spec.credential_id or name
        if provider in seen or not self.is_available(name):
            continue
        seen.add(provider)
        accounts.extend(self._store.list_accounts(provider))
    return accounts

def get_by_identity(self, provider_name: str, label: str) -> str | None:
    cred = self._store.get_credential_by_identity(provider_name, label)
    return cred.get_default_key() if cred else None
```

---

### Step 7: Surface identity to LLM via system prompt

**Files**: `prompt_composer.py`, `executor.py`, `event_loop_node.py`, `node.py`, `runner.py`

**Business logic**: The LLM needs to know what accounts are connected so it can:

1. **Communicate clearly to the user**: "I checked alice@company.com's inbox and
   found 3 unread messages" vs. "I checked the inbox and found 3 unread messages"

2. **Disambiguate operations**: When asked "check my emails," the LLM can respond
   "You have 2 Google accounts connected: alice@company.com and bob@company.com.
   Which would you like me to check?" (requires Step 9 routing, but awareness comes first)

3. **Prevent hallucination**: Without account info, the LLM might invent account
   names or assume capabilities it doesn't have. With the accounts prompt, it knows
   exactly what's available.

4. **Cross-account reasoning**: "Forward the email from alice's inbox to bob's inbox"
   requires knowing both accounts exist and which is which.

**Where it sits in the three-layer prompt**:
```
Layer 1 — Identity: "You are a thorough email management agent."
         Accounts:  "Connected accounts:
                     - google: alice@company.com (email: alice@company.com)
                     - google: bob@company.com (email: bob@company.com)
                     - slack: Acme Corp (workspace: Acme Corp, username: hive-bot)"
Layer 2 — Narrative: "We've triaged 15 emails so far..."
Layer 3 — Focus:     "Your current task: categorize remaining unread emails"
```

Accounts sit between identity (static personality) and narrative (dynamic state)
because connected accounts are semi-static — they don't change during a session but
are deployment-specific (different from the agent definition).

**Injection path through the framework**:
```
AgentRunner._setup()
  → CredentialStoreAdapter.get_all_account_info()
  → build_accounts_prompt(accounts)           ← new function in prompt_composer.py
  → GraphExecutor(accounts_prompt=...)        ← new init param
  → NodeContext(accounts_prompt=...)          ← new field
  → compose_system_prompt(..., accounts_prompt=...)  ← new param
```

**Why it flows through `NodeContext`**: For the first node in a graph (or an isolated
`EventLoopNode`), the system prompt is built in `EventLoopNode.execute()`, not through
the continuous transition path. `NodeContext.accounts_prompt` carries the data to
both paths:

- **Continuous transition**: `compose_system_prompt()` in the executor uses
  `self.accounts_prompt` directly
- **First node / isolated node**: `EventLoopNode.execute()` reads `ctx.accounts_prompt`
  and appends it to the system prompt

**Scenario — no credentials**: An agent with no external integrations (pure LLM
reasoning, no tools). `get_all_account_info()` returns `[]`. `build_accounts_prompt([])`
returns `""`. The accounts block is omitted from the system prompt. Zero impact.

**Scenario — single account**: One Google account. System prompt shows
`"Connected accounts:\n- google: alice@company.com (email: alice@company.com)"`.
The LLM knows who it's operating as.

**Scenario — unknown identity**: A credential exists but has no `_identity_*` keys
(maybe Aden didn't provide metadata and health checks haven't run yet). `identity.label`
returns `"unknown"`. The prompt shows `"- google: unknown"`. Better than nothing —
the LLM knows Google is connected, just not whose account.

```python
def build_accounts_prompt(accounts: list[dict[str, Any]]) -> str:
    if not accounts:
        return ""
    lines = ["Connected accounts:"]
    for acct in accounts:
        provider = acct.get("provider", "unknown")
        label = acct.get("label", "unknown")
        identity = acct.get("identity", {})
        detail_parts = [f"{k}: {v}" for k, v in identity.items() if v]
        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
        lines.append(f"- {provider}: {label}{detail}")
    return "\n".join(lines)
```

---

### Step 8: `get_account_info` MCP tool

**New directory**: `tools/src/aden_tools/tools/account_info_tool/`

**Business logic**: Step 7 gives the LLM passive awareness (system prompt). Step 8
gives the LLM active introspection — it can call `get_account_info()` to query
connected accounts at runtime, even mid-conversation.

**Why both passive and active**: The system prompt provides context at conversation
start. But in long-running agents with many tools, the system prompt may get
compacted (truncated during context management). The MCP tool ensures the LLM can
always re-discover account info even after compaction.

**Use cases**:

- **User asks "what accounts are connected?"**: LLM calls `get_account_info()`,
  formats the response for the user.

- **LLM needs to decide which account to use**: Before sending an email, the LLM
  calls `get_account_info(provider="google")` to see which Gmail accounts are
  available, then asks the user which one to send from.

- **Dynamic account discovery**: In a long-running session, accounts might be
  added/revoked (Aden dashboard). The tool provides current state vs. the stale
  system prompt.

- **Debugging/transparency**: The user can ask "which Slack workspace are you
  connected to?" and get a precise answer.

**API design**:

```python
@mcp.tool()
def get_account_info(provider: str = "") -> dict:
    """List connected accounts and their identities.

    Call with no arguments to see all connected accounts.
    Call with provider="google" to filter by provider type.

    Returns account IDs, provider types, and identity labels
    (email, username, workspace) for each connected account.
    """
    if credentials is None:
        return {"accounts": [], "message": "No credential store configured"}
    if provider:
        accounts = credentials.list_accounts(provider)
    else:
        accounts = credentials.get_all_account_info()
    return {"accounts": accounts, "count": len(accounts)}
```

**Response example**:
```json
{
  "accounts": [
    {"credential_id": "google_abc123", "provider": "google",
     "identity": {"email": "alice@company.com"}, "label": "alice@company.com"},
    {"credential_id": "google_def456", "provider": "google",
     "identity": {"email": "bob@company.com"}, "label": "bob@company.com"},
    {"credential_id": "slack_xyz", "provider": "slack",
     "identity": {"workspace": "Acme Corp", "username": "hive-bot"},
     "label": "Acme Corp"}
  ],
  "count": 3
}
```

Register in `tools/src/aden_tools/tools/__init__.py` alongside existing tools.

---

### Step 9: Multi-account routing extension point (design only, no code)

**Business logic**: Steps 1-8 build the foundation. Step 9 designs (but does not
implement) the per-tool-call account selection mechanism. This is the endgame:
when the LLM calls `gmail_read_email(account="alice@co.com")`, the right token
is used.

**Why design-only in this PR**: Multi-account routing requires changes to every
tool's `_get_token()` function and introduces the `account` parameter across all
tool signatures. This is a significant surface area change that should be a
separate PR with its own testing. The foundation from Steps 1-8 makes it a
straightforward addition.

**How it will work — the full flow**:

1. **LLM discovers accounts**: Via system prompt (Step 7) or `get_account_info` tool
   (Step 8), the LLM knows `alice@company.com` and `bob@company.com` are connected.

2. **User says "check alice's inbox"**: The LLM calls
   `gmail_read_email(account="alice@company.com")`.

3. **Tool resolves account**: `_get_token("alice@company.com")` calls
   `credentials.get_by_identity("google", "alice@company.com")`.

4. **Store resolves credential**: `get_credential_by_identity("google", "alice@company.com")`
   scans all Google credentials, finds the one where `identity.label == "alice@company.com"`,
   returns its access token.

5. **API call with correct token**: The tool uses Alice's token to call the Gmail API.
   The right inbox is read.

**Pinned single-account agents**: For agents that should ALWAYS use a specific account
(e.g., a shared support inbox), the `account` parameter becomes a `CONTEXT_PARAM` in
`ToolRegistry`. It's stripped from the LLM schema (the LLM can't override it) and
auto-injected at call time from `NodeSpec` or `GraphSpec` configuration. This follows
the exact same pattern as `data_dir` — proven, concurrency-safe, framework-native.

**Why `CredentialIdentity.label` is the stable routing key**:
- It's human-readable (email addresses, usernames)
- It's deterministic (computed from `_identity_*` keys)
- It matches what the LLM sees in the system prompt
- It survives credential refresh (identity doesn't change when tokens rotate)
- It's unique within a provider (two Google accounts always have different emails)

---

## How This Works with Exported/Template Agents

### Agent definition (no changes)

Exported agents in `exports/` declare tools via `NodeSpec.tools` and MCP servers via
`mcp_servers.json`. They don't know about credentials — this is by design. Credential
specs (`CredentialSpec.tools`) provide the external mapping from tool name to credential.

**Scenario — same agent, different deployments**: The "Email Triage" agent template
is used by 3 customers. Customer A has 1 Gmail account. Customer B has 5. Customer C
has 3 Gmail and 2 Outlook. The agent definition is identical for all three. Only
the Aden API key (and thus the available credentials) differs.

### Agent instance (accounts_prompt injection)

When `AgentRunner.load()` instantiates an agent:
1. `validate_agent_credentials()` runs — syncs Aden, checks presence/health
2. Identity is persisted during validation (Step 5)
3. `_setup()` collects `accounts_prompt` via `CredentialStoreAdapter.get_all_account_info()`
4. Passes to `GraphExecutor(accounts_prompt=...)` → `compose_system_prompt()`

The agent definition doesn't need to change. Identity flows through the existing
runtime wiring.

### MCP subprocess (independent adapter)

The MCP subprocess creates its own `CredentialStoreAdapter.default()` at startup.
This triggers an independent `sync_all()` from Aden. With the index fix (Step 2),
all accounts are preserved. The adapter's new methods (`list_accounts()`,
`get_all_account_info()`, `get_by_identity()`) are available to tools in the subprocess.

**Why independent sync is correct**: The MCP subprocess runs in a separate process
with its own memory space. It cannot share the parent's `CredentialStore`. Both
processes sync from the same Aden server (same API key), so they see the same
credentials. The disk-level `EncryptedFileStorage` handles concurrent access safely
(each read is atomic file read, writes use temp+rename).

### ToolRegistry bridge (future routing)

When multi-account routing is implemented (Step 9), the `account` parameter will be
added to `CONTEXT_PARAMS`. `ToolRegistry._convert_mcp_tool_to_framework_tool()` will
strip it from LLM schema (line 467). `make_mcp_executor()` will inject it at call time
(line 421). This follows the exact same pattern as `data_dir`.

---

## Files Modified (Summary)

| # | File | Changes |
|---|------|---------|
| 1 | `core/framework/credentials/models.py` | `CredentialIdentity`, `identity` property, `set_identity()`, `provider_type` |
| 2 | `core/framework/credentials/aden/storage.py` | `_provider_index: dict[str, list[str]]`, `load_all_for_provider()`, fix `exists()`, `rebuild_provider_index()` |
| 3 | `core/framework/credentials/aden/provider.py` | Persist `metadata` as `_identity_*` keys in both `_aden_response_to_credential` and `_update_credential_from_aden` |
| 4 | `tools/src/aden_tools/credentials/health_check.py` | `_extract_identity()` hook on `OAuthBearerHealthChecker`, overrides per checker, `identity` key in standalone checker `details` |
| 5 | `core/framework/credentials/validation.py` | Persist identity from health check `details["identity"]` via `set_identity()` |
| 6 | `core/framework/credentials/store.py` | `list_accounts()`, `get_credential_by_identity()` |
| 7 | `tools/src/aden_tools/credentials/store_adapter.py` | `get_identity()`, `list_accounts()`, `get_all_account_info()`, `get_by_identity()` |
| 8 | `core/framework/graph/prompt_composer.py` | `build_accounts_prompt()`, `accounts_prompt` param on `compose_system_prompt()` |
| 9 | `core/framework/graph/node.py` | `accounts_prompt: str = ""` on `NodeContext` |
| 10 | `core/framework/graph/executor.py` | `accounts_prompt` init param, pass to `compose_system_prompt()` and `_build_context()` |
| 11 | `core/framework/graph/event_loop_node.py` | Append `accounts_prompt` for first node system prompt |
| 12 | `core/framework/runner/runner.py` | Collect accounts info in `_setup()`, pass to executor |
| 13 | `tools/src/aden_tools/tools/account_info_tool/` | New `get_account_info` MCP tool |
| 14 | `tools/src/aden_tools/tools/__init__.py` | Register account info tool |

---

## Verification

1. **Multi-index**: Sync 2 Google accounts → both in `_provider_index["google"]` (not overwritten)
2. **Identity model**: `cred.identity.email` returns email, `cred.identity.label` returns best label
3. **Health check identity**: `GoogleGmailHealthChecker.check(token)` → `result.details["identity"]["email"]`
4. **Persistence**: After validation, credential on disk has `_identity_email` key
5. **Account listing**: `adapter.list_accounts("google")` → 2 accounts with distinct identities
6. **System prompt**: `compose_system_prompt(accounts_prompt=...)` includes "Connected accounts"
7. **MCP tool**: `get_account_info(provider="google")` returns both accounts with labels
8. **Backward compat**: `credentials.get("google")` still returns single token string
9. **Existing tests**: `PYTHONPATH=core:tools/src python -m pytest tools/tests/ -x -q -k "credential"`
