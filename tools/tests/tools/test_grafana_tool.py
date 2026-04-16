import pytest
import respx
import httpx
import time
from aden_tools.tools.grafana_tool.grafana_tool import GrafanaClient, GrafanaToolError, register_tools

class MockFastMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")
    monkeypatch.setenv("GRAFANA_API_KEY", "test-token")
    monkeypatch.setenv("ADEN_HIVE_TESTING", "1")


@pytest.mark.asyncio
@respx.mock
async def test_grafana_client_valid_api_call():
    """Test valid API call via GrafanaClient."""
    respx.get("https://grafana.test/api/search?type=dash-db").mock(
        return_value=httpx.Response(200, json=[{"uid": "uid1"}])
    )
    client = GrafanaClient("https://grafana.test", "token123")
    result = await client.request("GET", "search?type=dash-db")
    assert result == [{"uid": "uid1"}]

@pytest.mark.asyncio
@respx.mock
async def test_grafana_client_unauthorized():
    """Test unauthorized access (401)."""
    respx.get("https://grafana.test/api/search?type=dash-db").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )
    client = GrafanaClient("https://grafana.test", "token123")
    
    with pytest.raises(GrafanaToolError) as exc:
        await client.request("GET", "search?type=dash-db")
    
    assert "Unauthorized. Check your GRAFANA_API_KEY." in str(exc.value)

@pytest.mark.asyncio
@respx.mock
async def test_grafana_client_rate_limiting_retries():
    """Test retry decorator for 429 rate limit."""
    route = respx.get("https://grafana.test/api/search?type=dash-db")
    
    # 429 error twice, then 200 OK
    route.side_effect = [
        httpx.Response(429, json={"message": "Rate limit exceeded"}),
        httpx.Response(429, json={"message": "Rate limit exceeded"}),
        httpx.Response(200, json=[{"uid": "success"}]),
    ]
    
    # Given the delay is exponential with 1.0s base:
    # 1st retry: 1s
    # 2nd retry: 2s
    # We should patch asyncio.sleep to avoid slow tests
    import asyncio
    original_sleep = asyncio.sleep
    try:
        async def mock_sleep(delay):
            pass
        asyncio.sleep = mock_sleep
        
        client = GrafanaClient("https://grafana.test", "token123")
        result = await client.request("GET", "search?type=dash-db")
        assert result == [{"uid": "success"}]
        assert route.call_count == 3
    finally:
        asyncio.sleep = original_sleep

@pytest.mark.asyncio
@respx.mock
async def test_grafana_list_dashboards_malformed_json(mock_env):
    """Test tool function handles malformed dashboard API response cleanly."""
    respx.get("https://grafana.example.com/api/search?type=dash-db").mock(
        return_value=httpx.Response(200, json={"error": "not a list layout as expected"})
    )
    
    mcp = MockFastMCP()
    register_tools(mcp)
    
    # Expected behavior: returns dict with "error" instead of crashing
    result = await mcp.tools["grafana_list_dashboards"]()
    assert "error" in result
    assert "expected list of dashboards" in result["error"]

@pytest.mark.asyncio
@respx.mock
async def test_grafana_list_dashboards_success(mock_env):
    """Test full dashboard list parsing logic."""
    respx.get("https://grafana.example.com/api/search?type=dash-db").mock(
        return_value=httpx.Response(200, json=[
            {"uid": "uid1", "title": "Dash 1", "uri": "", "tags": ["prod"], "isStarred": False, "type": "dash-db"},
            {"uid": "uid2", "title": "Dash 2", "type": "folder"} # should be ignored or processed with incomplete tags
        ])
    )
    
    mcp = MockFastMCP()
    register_tools(mcp)
    
    result = await mcp.tools["grafana_list_dashboards"]()
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["uid"] == "uid1"
    assert "prod" in result[0]["tags"]

@pytest.mark.asyncio
@respx.mock
async def test_grafana_create_annotation(mock_env):
    """Ensure annotation uses sanitize_for_log."""
    respx.post("https://grafana.example.com/api/annotations").mock(
        return_value=httpx.Response(200, json={"message": "Annotation added", "id": 123})
    )
    
    mcp = MockFastMCP()
    register_tools(mcp)
    
    # We pass some text that contains a secret
    result = await mcp.tools["grafana_create_annotation"]("dash1", "password=secret123")
    
    # The POST request should be caught and verify the sanitized format
    request = respx.calls.last.request
    import json
    data = json.loads(request.content)
    
    # sanitize_for_log should redact "password=secret123" to something like "password=********"
    assert "********" in data["text"]
    assert "execution-log" in data["tags"]
    assert result["message"] == "Annotation added"

@pytest.mark.asyncio
@respx.mock
async def test_grafana_list_alerts_success(mock_env):
    """Ensure grafana alerts returns cleanly structured outputs."""
    respx.get("https://grafana.example.com/api/v1/provisioning/alert-rules").mock(
        return_value=httpx.Response(200, json=[
            {"uid": "a1", "title": "High CPU", "execErrState": "OK"}
        ])
    )
    
    mcp = MockFastMCP()
    register_tools(mcp)
    
    result = await mcp.tools["grafana_list_alerts"]()
    assert isinstance(result, list)
    assert result[0]["uid"] == "a1"
    assert result[0]["state"] == "OK"
