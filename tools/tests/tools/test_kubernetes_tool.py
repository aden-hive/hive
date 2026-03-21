import pytest
from unittest.mock import MagicMock, patch
from fastmcp import FastMCP
from aden_tools.tools.kubernetes_tool.kubernetes_tool import register_tools

@pytest.fixture
def mcp():
    return FastMCP("test_kubernetes")

@pytest.fixture
def tool_fns(mcp: FastMCP):
    """Extracts all registered tools and maps them by name for easy testing."""
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}

@patch('aden_tools.tools.kubernetes_tool.kubernetes_tool.K8S_AVAILABLE', False)
def test_kubernetes_missing_dependency(tool_fns):
    """Test that missing dependencies return a controlled error dict, not an exception."""
    result = tool_fns["kubernetes_list_pods"](namespace="default")
    assert "error" in result
    assert "kubernetes python package is not installed" in result["error"]

@patch('aden_tools.tools.kubernetes_tool.kubernetes_tool.K8S_AVAILABLE', True)
@patch('aden_tools.tools.kubernetes_tool.kubernetes_tool.config')
@patch('aden_tools.tools.kubernetes_tool.kubernetes_tool.client')
def test_kubernetes_list_pods_success(mock_client, mock_config, tool_fns):
    """Test successful pod retrieval."""
    # Setup the mock Kubernetes response
    mock_pod = MagicMock()
    mock_pod.metadata.name = "test-pod"
    mock_pod.status.phase = "Running"
    mock_pod.status.pod_ip = "10.0.0.1"
    mock_pod.spec.node_name = "test-node"
    
    mock_v1 = MagicMock()
    mock_v1.list_namespaced_pod.return_value.items = [mock_pod]
    mock_client.CoreV1Api.return_value = mock_v1

    # Call the tool directly from the extracted functions map
    result = tool_fns["kubernetes_list_pods"](namespace="default")
    
    assert "error" not in result
    assert result["total"] == 1
    assert result["pods"][0]["name"] == "test-pod"
    assert result["pods"][0]["status"] == "Running"