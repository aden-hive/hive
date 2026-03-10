from __future__ import annotations

from framework.mcp.auth.models import MCPAuthDecision, MCPAuthToken
from framework.mcp.errors import (
    MCPAuthRequiredError,
    MCPAuthRequiredExternalError,
    MCPHTTPUnauthorizedError,
)
from framework.mcp.models import MCPServerConfig
from framework.mcp.session.runtime import MCPClientSessionRuntime


class _Response:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.text = ""

    def json(self):
        raise ValueError("no json")


class _Transport:
    def __init__(self):
        self.token: str | None = None
        self.list_calls = 0

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def list_tools(self):
        self.list_calls += 1
        if self.token is None:
            raise MCPHTTPUnauthorizedError(
                server_name="Github",
                message="unauthorized",
                response=_Response(),
                rpc_path="/mcp",
                attempted_auth=False,
            )
        return [{"name": "tool_a", "inputSchema": {"type": "object"}}]

    def call_tool(self, tool_name: str, arguments: dict):
        _ = (tool_name, arguments)
        return {"ok": True}

    def set_bearer_token(self, token: str) -> None:
        self.token = token

    def has_bearer_token(self) -> bool:
        return self.token is not None


class _AlwaysUnauthorizedTransport(_Transport):
    def list_tools(self):
        self.list_calls += 1
        raise MCPHTTPUnauthorizedError(
            server_name="Github",
            message="unauthorized",
            response=_Response(),
            rpc_path="/mcp",
            attempted_auth=self.token is not None,
        )


class _AuthManagerRetryThenExternal:
    def resolve_unauthorized(self, config, response, token_already_tried):
        _ = (config, response)
        if not token_already_tried:
            return MCPAuthDecision(
                kind="retry_with_token",
                token=MCPAuthToken(value="abc", credential_id="github", key_name="access_token"),
            )
        return MCPAuthDecision(
            kind="auth_required_external",
            payload={"type": "auth_required_external", "action": "authorize_via_aden"},
        )


class _AuthManagerAuthRequired:
    def resolve_unauthorized(self, config, response, token_already_tried):
        _ = (config, response, token_already_tried)
        return MCPAuthDecision(
            kind="auth_required",
            payload={"type": "auth_required", "auth_url": "https://oauth.example.com/start"},
        )


def _config() -> MCPServerConfig:
    return MCPServerConfig(name="Github", transport="http", url="https://example.com/mcp")


def test_runtime_without_auth_manager_executes_directly():
    transport = _Transport()
    transport.set_bearer_token("already-set")
    runtime = MCPClientSessionRuntime(config=_config(), transport=transport, auth_manager=None)

    tools = runtime.list_tools()

    assert tools[0]["name"] == "tool_a"


def test_runtime_retries_once_with_token():
    transport = _Transport()
    runtime = MCPClientSessionRuntime(
        config=_config(),
        transport=transport,
        auth_manager=_AuthManagerRetryThenExternal(),
    )

    tools = runtime.list_tools()

    assert tools[0]["name"] == "tool_a"
    assert transport.token == "abc"
    assert transport.list_calls == 2


def test_runtime_raises_auth_required_from_decision():
    transport = _AlwaysUnauthorizedTransport()
    runtime = MCPClientSessionRuntime(
        config=_config(),
        transport=transport,
        auth_manager=_AuthManagerAuthRequired(),
    )

    try:
        runtime.list_tools()
        raise AssertionError("expected MCPAuthRequiredError")
    except MCPAuthRequiredError as exc:
        assert exc.payload["type"] == "auth_required"


def test_runtime_raises_external_auth_after_retry_unauthorized():
    transport = _AlwaysUnauthorizedTransport()
    runtime = MCPClientSessionRuntime(
        config=_config(),
        transport=transport,
        auth_manager=_AuthManagerRetryThenExternal(),
    )

    try:
        runtime.list_tools()
        raise AssertionError("expected MCPAuthRequiredExternalError")
    except MCPAuthRequiredExternalError as exc:
        assert exc.payload["type"] == "auth_required_external"
