# Aden Credential Sync Integration

Implementation guideline for integrating the Hive credential store with the Aden authentication server.

## Overview

The Aden server handles OAuth2 authorization code flows (user login, consent, token generation). The local credential store acts as a **driver** that:

1. Fetches tokens from the Aden server on demand
2. Caches tokens locally for performance and offline resilience
3. Delegates refresh operations to the Aden server
4. Optionally reports usage statistics back to Aden

```
┌─────────────────────────────────────────────────────────────────┐
│                    Local Agent Environment                      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   CredentialStore                        │   │
│  │  ┌────────────────────┐  ┌────────────────────────────┐  │   │
│  │  │EncryptedFileStorage│  │    AdenSyncProvider        │  │   │
│  │  │  (local cache)     │  │  - Fetches from Aden       │  │   │
│  │  │ ~/.hive/credentials│  │  - Delegates refresh       │  │   │
│  │  └────────────────────┘  │  - Reports usage           │  │   │
│  │                          └─────────────┬──────────────┘  │   │
│  └────────────────────────────────────────┼─────────────────┘   │
│                                           │                     │
└───────────────────────────────────────────┼─────────────────────┘
                                            │ HTTPS
                                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Aden Server                               │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Integration Management                      │   │
│  │  - HubSpot, GitHub, Slack, etc.                          │   │
│  │  - Handles OAuth2 auth code flow                         │   │
│  │  - Stores refresh tokens securely                        │   │
│  │  - Performs token refresh on request                     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Aden API Contract

The Aden server must expose these REST endpoints.

### Authentication

All requests include:

- `Authorization: Bearer {agent_api_key}` - Agent's API key
- `X-Tenant-ID: {tenant_id}` - (Optional) For multi-tenant deployments

### Endpoints

#### 1. Get Credential

Fetch the current access token for an integration. The Aden server should refresh internally if the token is expired.

```
GET /v1/credentials/{integration_id}

Headers:
  Authorization: Bearer {agent_api_key}
  X-Tenant-ID: {tenant_id}  (optional)

Response 200 OK:
{
  "integration_id": "hubspot",
  "integration_type": "hubspot",
  "access_token": "CJTFwvnuLxIFAgEY...",
  "token_type": "Bearer",
  "expires_at": "2026-01-28T15:30:00Z",
  "scopes": ["crm.objects.contacts.read", "crm.objects.contacts.write"],
  "metadata": {
    "portal_id": "12345678",
    "connected_at": "2026-01-15T10:00:00Z"
  }
}

Response 404 Not Found:
{
  "error": "integration_not_found",
  "message": "No integration 'hubspot' found for this tenant"
}

Response 401 Unauthorized:
{
  "error": "invalid_api_key",
  "message": "Agent API key is invalid or revoked"
}
```

#### 2. Request Token Refresh

Explicitly request the Aden server to refresh the token. Use this when the local store detects an expired or near-expiry token.

```
POST /v1/credentials/{integration_id}/refresh

Headers:
  Authorization: Bearer {agent_api_key}

Response 200 OK:
{
  "integration_id": "hubspot",
  "integration_type": "hubspot",
  "access_token": "NEW_ACCESS_TOKEN...",
  "token_type": "Bearer",
  "expires_at": "2026-01-28T16:30:00Z",
  "scopes": ["crm.objects.contacts.read", "crm.objects.contacts.write"],
  "metadata": {}
}

Response 400 Bad Request:
{
  "error": "refresh_failed",
  "message": "Refresh token is invalid or revoked. User must re-authorize.",
  "requires_reauthorization": true,
  "reauthorization_url": "https://api.adenhq.com/integrations/hubspot/connect"
}

Response 429 Too Many Requests:
{
  "error": "rate_limited",
  "message": "Too many refresh requests. Try again later.",
  "retry_after": 60
}
```

#### 3. List Integrations

List all integrations available for this agent/tenant.

```
GET /v1/credentials

Headers:
  Authorization: Bearer {agent_api_key}

Response 200 OK:
{
  "integrations": [
    {
      "integration_id": "hubspot",
      "integration_type": "hubspot",
      "status": "active",
      "expires_at": "2026-01-28T15:30:00Z"
    },
    {
      "integration_id": "github",
      "integration_type": "github",
      "status": "active",
      "expires_at": null
    },
    {
      "integration_id": "slack",
      "integration_type": "slack",
      "status": "requires_reauth",
      "expires_at": null
    }
  ],
  "tenant_id": "tenant-123"
}
```

#### 4. Validate Token

Check if a token is still valid without fetching it.

```
GET /v1/credentials/{integration_id}/validate

Headers:
  Authorization: Bearer {agent_api_key}

Response 200 OK:
{
  "valid": true,
  "expires_at": "2026-01-28T15:30:00Z",
  "expires_in_seconds": 3600
}

Response 200 OK (invalid):
{
  "valid": false,
  "reason": "token_expired",
  "requires_reauthorization": false
}

Response 200 OK (needs reauth):
{
  "valid": false,
  "reason": "refresh_token_revoked",
  "requires_reauthorization": true,
  "reauthorization_url": "https://api.adenhq.com/integrations/hubspot/connect"
}
```

#### 5. Report Usage (Optional)

Report credential usage statistics back to Aden for analytics/billing.

```
POST /v1/credentials/{integration_id}/usage

Headers:
  Authorization: Bearer {agent_api_key}
  Content-Type: application/json

Request:
{
  "operation": "api_call",
  "status": "success",
  "timestamp": "2026-01-28T14:00:00Z",
  "metadata": {
    "endpoint": "/crm/v3/objects/contacts",
    "method": "GET",
    "response_code": 200
  }
}

Response 200 OK:
{
  "received": true
}
```

#### 6. Health Check

```
GET /health

Response 200 OK:
{
  "status": "healthy",
  "version": "1.2.3",
  "timestamp": "2026-01-28T14:00:00Z"
}
```

---

## Local Implementation Components

### File Structure

```
core/framework/credentials/
├── aden/
│   ├── __init__.py          # Module exports
│   ├── client.py            # AdenCredentialClient - HTTP client
│   ├── provider.py          # AdenSyncProvider - CredentialProvider impl
│   └── storage.py           # AdenCachedStorage - Optional cached storage
└── ... (existing files)
```

### 1. Aden Client (`client.py`)

HTTP client for communicating with the Aden server.

```python
@dataclass
class AdenClientConfig:
    """Configuration for Aden API client."""
    base_url: str                    # e.g., "https://api.adenhq.com"
    api_key: str | None = None       # Loaded from ADEN_API_KEY env var if not provided
    tenant_id: str | None = None     # For multi-tenant
    timeout: float = 30.0
    retry_attempts: int = 3
    retry_delay: float = 1.0


@dataclass
class AdenCredentialResponse:
    """Response from Aden server."""
    integration_id: str
    integration_type: str
    access_token: str
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class AdenCredentialClient:
    """HTTP client for Aden credential server."""

    def __init__(self, config: AdenClientConfig): ...

    def get_credential(self, integration_id: str) -> AdenCredentialResponse | None:
        """Fetch credential from Aden. Returns None if not found."""

    def request_refresh(self, integration_id: str) -> AdenCredentialResponse:
        """Request Aden to refresh the token."""

    def list_integrations(self) -> list[dict]:
        """List all available integrations."""

    def validate_token(self, integration_id: str) -> dict:
        """Check if token is valid."""

    def report_usage(self, integration_id: str, operation: str, status: str, metadata: dict) -> None:
        """Report usage statistics."""

    def health_check(self) -> dict:
        """Check Aden server health."""
```

### 2. Aden Sync Provider (`provider.py`)

Implements `CredentialProvider` interface, delegates refresh to Aden.

```python
class AdenSyncProvider(CredentialProvider):
    """
    Provider that synchronizes credentials with Aden server.

    Usage:
        # API key loaded from ADEN_API_KEY env var by default
        client = AdenCredentialClient(AdenClientConfig(
            base_url="https://api.adenhq.com",
        ))

        provider = AdenSyncProvider(client=client)

        store = CredentialStore(
            storage=EncryptedFileStorage(),
            providers=[provider],
            auto_refresh=True,
        )
    """

    def __init__(
        self,
        client: AdenCredentialClient,
        provider_id: str = "aden_sync",
        refresh_buffer_minutes: int = 5,
        report_usage: bool = False,
    ): ...

    @property
    def provider_id(self) -> str: ...

    @property
    def supported_types(self) -> list[CredentialType]:
        return [CredentialType.OAUTH2, CredentialType.BEARER_TOKEN]

    def refresh(self, credential: CredentialObject) -> CredentialObject:
        """Refresh by calling Aden server."""

    def validate(self, credential: CredentialObject) -> bool:
        """Validate via Aden introspection."""

    def should_refresh(self, credential: CredentialObject) -> bool:
        """Check if within refresh buffer of expiration."""

    def fetch_from_aden(self, integration_id: str) -> CredentialObject | None:
        """Fetch credential directly from Aden (for initial population)."""

    def sync_all(self, store: CredentialStore) -> int:
        """Sync all integrations from Aden to local store. Returns count."""
```

### 3. Aden Cached Storage (`storage.py`) - Optional

Storage backend that combines local cache with Aden fallback.

```python
class AdenCachedStorage(CredentialStorage):
    """
    Storage with local cache + Aden fallback.

    - Reads: Try local first, fallback to Aden if stale/missing
    - Writes: Always write to local cache
    - Provides offline resilience

    Usage:
        storage = AdenCachedStorage(
            local_storage=EncryptedFileStorage(),
            aden_provider=provider,
            cache_ttl_seconds=600,  # 5 minutes
        )
    """

    def __init__(
        self,
        local_storage: CredentialStorage,
        aden_provider: AdenSyncProvider,
        cache_ttl_seconds: int = 300,
    ): ...

    def load(self, credential_id: str) -> CredentialObject | None:
        """Load from cache, fallback to Aden if stale."""

    def save(self, credential: CredentialObject) -> None:
        """Save to local cache."""

    def sync_all_from_aden(self) -> int:
        """Pull all credentials from Aden to local cache."""
```

---

## Integration Patterns

### Pattern A: Provider-Only (Recommended)

Simple setup where local storage is just a cache, Aden handles refresh.

```python
from core.framework.credentials import CredentialStore
from core.framework.credentials.storage import EncryptedFileStorage
from core.framework.credentials.aden import AdenCredentialClient, AdenClientConfig, AdenSyncProvider

# Configure
# API key loaded from ADEN_API_KEY env var by default
client = AdenCredentialClient(AdenClientConfig(
    base_url=os.environ["ADEN_API_URL"],
    tenant_id=os.environ.get("ADEN_TENANT_ID"),
))

provider = AdenSyncProvider(client=client)

store = CredentialStore(
    storage=EncryptedFileStorage(),  # ~/.hive/credentials
    providers=[provider],
    auto_refresh=True,
)

# Initial sync from Aden
provider.sync_all(store)

# Use normally - auto-refreshes via Aden when needed
token = store.get_key("hubspot", "access_token")
```

### Pattern B: With Cached Storage (Offline Resilience)

For environments that may lose connectivity to Aden temporarily.

```python
from core.framework.credentials.aden import AdenCachedStorage

storage = AdenCachedStorage(
    local_storage=EncryptedFileStorage(),
    aden_provider=provider,
    cache_ttl_seconds=600,  # Re-check Aden every 5 min
)

store = CredentialStore(
    storage=storage,
    providers=[provider],
    auto_refresh=True,
)

# Credentials automatically fetched from Aden on first access
# Cached locally for 5 minutes
# Falls back to cache if Aden is unreachable
```

### Pattern C: Multi-Tenant

```python
def create_tenant_store(tenant_id: str) -> CredentialStore:
    # Explicit api_key for per-tenant credentials
    client = AdenCredentialClient(AdenClientConfig(
        base_url=os.environ["ADEN_API_URL"],
        api_key=os.environ[f"ADEN_API_KEY_{tenant_id}"],
        tenant_id=tenant_id,
    ))

    provider = AdenSyncProvider(client=client, provider_id=f"aden_{tenant_id}")

    return CredentialStore(
        storage=EncryptedFileStorage(f"~/.hive/credentials/{tenant_id}"),
        providers=[provider],
    )
```

---

## Error Handling

### Aden Unavailable

```python
class AdenSyncProvider:
    def refresh(self, credential: CredentialObject) -> CredentialObject:
        try:
            return self._refresh_via_aden(credential)
        except httpx.ConnectError:
            # Network unavailable
            if not self._is_token_expired(credential):
                logger.warning(f"Aden unavailable, using cached token")
                return credential
            raise CredentialRefreshError("Aden unavailable and token expired")
```

### Re-authorization Required

When refresh token is revoked, Aden returns `requires_reauthorization: true`.

```python
if response.get("requires_reauthorization"):
    raise CredentialRefreshError(
        f"Integration '{integration_id}' requires re-authorization. "
        f"Visit: {response.get('reauthorization_url')}"
    )
```

### Rate Limiting

```python
if response.status_code == 429:
    retry_after = response.headers.get("Retry-After", 60)
    raise CredentialRefreshError(
        f"Rate limited. Retry after {retry_after} seconds."
    )
```

---

## Security Considerations

### Agent API Keys

- Each agent deployment gets a unique API key from Aden
- Keys are scoped to specific tenants/integrations
- Store in environment variable: `ADEN_API_KEY`
- Keys can be rotated without affecting stored credentials

### Token Security

- Access tokens cached locally are encrypted (EncryptedFileStorage)
- Refresh tokens NEVER leave the Aden server
- Short cache TTLs limit exposure window
- TLS required for all Aden communication

### Audit Trail

- Aden maintains full audit log of token access
- Usage reporting (optional) provides per-agent visibility
- Local store logs refresh attempts

---

## Environment Variables

| Variable              | Required | Description                    |
| --------------------- | -------- | ------------------------------ |
| `ADEN_API_URL`        | Yes      | Base URL of Aden auth server   |
| `ADEN_API_KEY`        | Yes      | Agent's API key for Aden       |
| `ADEN_TENANT_ID`      | No       | Tenant ID for multi-tenant     |
| `HIVE_CREDENTIAL_KEY` | Yes      | Encryption key for local cache |

---

## Migration from Direct OAuth2

If currently using `BaseOAuth2Provider` directly:

```python
# Before: Direct OAuth2 refresh
provider = HubSpotOAuth2Provider(
    client_id="...",
    client_secret="...",
)

# After: Delegate to Aden
provider = AdenSyncProvider(
    client=AdenCredentialClient(AdenClientConfig(
        base_url="https://api.adenhq.com",
        api_key="...",
    ))
)

# Store usage unchanged
store = CredentialStore(
    storage=EncryptedFileStorage(),
    providers=[provider],
)
```

The Aden server now handles:

- Client credentials (client_id, client_secret)
- Refresh token storage
- Token refresh logic
- Rate limiting with providers

---

## Testing

### Mock Aden Server

For local development/testing:

```python
from unittest.mock import Mock

mock_client = Mock(spec=AdenCredentialClient)
mock_client.get_credential.return_value = AdenCredentialResponse(
    integration_id="hubspot",
    integration_type="hubspot",
    access_token="test-token",
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)

provider = AdenSyncProvider(client=mock_client)
```

### Integration Tests

Test against Aden staging environment:

```python
@pytest.mark.integration
def test_aden_sync():
    client = AdenCredentialClient(AdenClientConfig(
        base_url=os.environ["ADEN_STAGING_URL"],
        api_key=os.environ["ADEN_STAGING_API_KEY"],
    ))

    # Should successfully fetch
    response = client.get_credential("hubspot")
    assert response is not None
    assert response.access_token
```
