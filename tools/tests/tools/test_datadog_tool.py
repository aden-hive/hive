import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import httpx
from mcp.server.fastmcp import FastMCP

# Add the tool directory to path to import directly, bypassing 'aden_tools.tools' package init
# which triggers loading of all tools and their dependencies (resend, playwright, etc.)
current_dir = os.path.dirname(os.path.abspath(__file__))
tool_dir = os.path.abspath(os.path.join(current_dir, "../../src/aden_tools/tools/datadog_tool"))
sys.path.insert(0, tool_dir)

from datadog_tool import register_tools

class TestDatadogTool(unittest.TestCase):
    def setUp(self):
        # Mock MCP server to capture registered tools
        self.mcp = MagicMock()
        self.tools = {}
        
        # Mock the @mcp.tool() decorator
        def tool_decorator(*args, **kwargs):
            def wrapper(func):
                self.tools[func.__name__] = func
                return func
            return wrapper
            
        self.mcp.tool.side_effect = tool_decorator
        
        register_tools(self.mcp)
        self.tool_map = self.tools

    def test_missing_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            result = self.tool_map["datadog_list_logs"](query="test")
            self.assertIn("Configuration Error", result)
            self.assertIn("DATADOG_API_KEY", result)

    @patch("httpx.Client")
    def test_list_logs_success(self, mock_client_cls):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "attributes": {
                        "timestamp": "2023-10-27T10:00:00Z",
                        "service": "web-server",
                        "status": "error",
                        "message": "Something went wrong",
                        "tags": ["env:prod"]
                    }
                }
            ]
        }
        mock_client.post.return_value = mock_response
        
        env = {
            "DATADOG_API_KEY": "fake_api_key",
            "DATADOG_APP_KEY": "fake_app_key"
        }
        
        with patch.dict(os.environ, env):
            result = self.tool_map["datadog_list_logs"](query="service:web")
            
            # Verify request
            mock_client.post.assert_called_once()
            args, kwargs = mock_client.post.call_args
            url = args[0] if args else kwargs.get("url")
            self.assertEqual(url, "https://api.datadoghq.com/api/v2/logs/events/search")
            self.assertEqual(kwargs["headers"]["DD-API-KEY"], "fake_api_key")
            self.assertEqual(kwargs["json"]["filter"]["query"], "service:web")
            
            # Verify result parsing
            data = json.loads(result)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["service"], "web-server")

    @patch("httpx.Client")
    def test_list_logs_forbidden(self, mock_client_cls):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_client.post.return_value = mock_response
        
        env = {"DATADOG_API_KEY": "k", "DATADOG_APP_KEY": "k"}
        with patch.dict(os.environ, env):
            result = self.tool_map["datadog_list_logs"](query="test")
            self.assertIn("Error 403: Forbidden", result)

    @patch("httpx.Client")
    def test_get_metrics_success(self, mock_client_cls):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "series": [
                {
                    "metric": "system.cpu.idle",
                    "pointlist": [[1000, 90], [1001, 91]],
                    "scope": "host:server1"
                }
            ]
        }
        mock_client.get.return_value = mock_response
        
        env = {"DATADOG_API_KEY": "k", "DATADOG_APP_KEY": "k"}
        with patch.dict(os.environ, env):
            result = self.tool_map["datadog_get_metrics"](query="avg:system.cpu.idle{*}")
            
            data = json.loads(result)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["points_count"], 2)

    @patch("httpx.Client")
    def test_get_monitor_status(self, mock_client_cls):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "monitors": [
                {"name": "High CPU", "overall_state": "Alert", "id": 1, "tags": []},
                {"name": "Low Memory", "overall_state": "OK", "id": 2, "tags": []}
            ]
        }
        mock_client.get.return_value = mock_response
        
        env = {"DATADOG_API_KEY": "k", "DATADOG_APP_KEY": "k"}
        with patch.dict(os.environ, env):
            # Default filter triggers on Alert,Warn
            result = self.tool_map["datadog_get_monitor_status"](monitor_tags="env:prod")
            data = json.loads(result)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "High CPU")
            
            # Custom filter
            result_ok = self.tool_map["datadog_get_monitor_status"](monitor_tags="env:prod", group_states="OK")
            data_ok = json.loads(result_ok)
            self.assertEqual(len(data_ok), 1)
            self.assertEqual(data_ok[0]["name"], "Low Memory")

    @patch("httpx.Client")
    def test_custom_site(self, mock_client_cls):
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_client.post.return_value = mock_response
        
        env = {
            "DATADOG_API_KEY": "k",
            "DATADOG_APP_KEY": "k",
            "DATADOG_SITE": "datadoghq.eu"
        }
        with patch.dict(os.environ, env):
            self.tool_map["datadog_list_logs"](query="test")
            _, kwargs = mock_client.post.call_args
            args, kwargs = mock_client.post.call_args
            url = args[0] if args else kwargs.get("url")
            self.assertIn("api.datadoghq.eu", url)

if __name__ == "__main__":
    unittest.main()
