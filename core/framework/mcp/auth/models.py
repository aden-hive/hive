"""Auth models for MCP HTTP OAuth decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AuthDecisionKind = Literal["retry_with_token", "auth_required", "auth_required_external"]


@dataclass
class MCPAuthChallenge:
    """Parsed auth challenge details from an HTTP 401 response."""

    auth_url: str | None = None
    resource_metadata: str | None = None
    required_scopes: list[str] = field(default_factory=list)
    required_headers: list[str] = field(default_factory=list)
    raw_www_authenticate: str | None = None


@dataclass
class MCPAuthToken:
    """Token resolved from credential store."""

    value: str
    credential_id: str
    key_name: str


@dataclass
class MCPAuthDecision:
    """Auth decision produced by strategy/manager."""

    kind: AuthDecisionKind
    payload: dict[str, Any] = field(default_factory=dict)
    token: MCPAuthToken | None = None
