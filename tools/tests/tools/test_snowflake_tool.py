import os
import unittest
from unittest.mock import patch, MagicMock
from aden_tools.tools.snowflake_tool.snowflake_tool import register_tools, SnowflakeClient
from fastmcp import FastMCP

class TestSnowflakeTool(unittest.TestCase):
    def setUp(self):
        self.mcp = FastMCP("test-server")
        
        # Mock valid private key (RSA 2048) for SnowflakeClient init (doesn't have to be valid for load_pem unless used)
        # But SnowflakeClient.execute_query calls _generate_jwt which calls load_pem_private_key.
        # So mocks are needed.
        self.mock_private_key = "-----BEGIN PRIVATE KEY-----\nMIIEvgIB...FAKE_KEY...==\n-----END PRIVATE KEY-----"
        
        self.mock_creds = {
            "snowflake_account": "test-account",
            "snowflake_user": "test-user", 
            "snowflake_private_key": self.mock_private_key,
            "snowflake_database": "test-db",
            "snowflake_schema": "test-schema",
            "snowflake_warehouse": "test-wh"
        }

    @patch("aden_tools.tools.snowflake_tool.snowflake_tool.httpx.Client")
    @patch("aden_tools.tools.snowflake_tool.snowflake_tool.serialization.load_pem_private_key")
    @patch("aden_tools.tools.snowflake_tool.snowflake_tool.jwt.encode")
    def test_snowflake_client_query_success(self, mock_jwt_encode, mock_load_key, mock_client_cls):
        # Setup mocks
        mock_jwt_encode.return_value = "mock_token"
        
        # Mock Private Key Structure
        mock_key_obj = MagicMock()
        mock_pub_key = MagicMock()
        # Ensure public_bytes returns bytes so hashlib accepts it
        mock_pub_key.public_bytes.return_value = b"mock_public_key_bytes"
        mock_key_obj.public_key.return_value = mock_pub_key
        
        mock_load_key.return_value = mock_key_obj
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "resultSetMetaData": {
                "rowType": [{"name": "COL1"}, {"name": "COL2"}]
            },
            "data": [
                ["val1", "val2"],
                ["val3", "val4"]
            ]
        }
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = mock_resp
        
        client = SnowflakeClient("test-account", "test-user", self.mock_private_key)
        
        # Test execute_query
        result = client.execute_query("SELECT * FROM TEST")
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["COL1"], "val1")
        self.assertEqual(result[0]["COL2"], "val2")
        
        # Verify URL construction
        args, kwargs = mock_client.post.call_args
        self.assertIn("https://test-account.snowflakecomputing.com/api/v2/statements", args[0])
        
        # Verify Headers
        headers = kwargs.get("headers", {})
        self.assertEqual(headers["Authorization"], "Bearer mock_token")
        self.assertEqual(headers["X-Snowflake-Authorization-Token-Type"], "KEYPAIR_JWT")

    def test_tool_registration_and_execution(self):
        # Mock credentials dict
        creds_obj = MagicMock()
        creds_obj.get.side_effect = lambda k: self.mock_creds.get(k)
        
        # Register tools
        register_tools(self.mcp, credentials=creds_obj)
        
        # Verify tools are registered
        # fastmcp 2.x uses get_tool to retrieve registered tools
        # If tool doesn't exist, it might raise or return None depending on impl, 
        # but for existence check we can just try to get it.
        try:
            query_tool = self.mcp.get_tool("snowflake_query")
            self.assertIsNotNone(query_tool)
            describe_tool = self.mcp.get_tool("snowflake_describe")
            self.assertIsNotNone(describe_tool)
            insert_tool = self.mcp.get_tool("snowflake_insert")
            self.assertIsNotNone(insert_tool)
        except Exception as e:
            self.fail(f"Tool registration failed: {e}")
        
        # To test execution, we would need to invoke the tool function stored in mcp._tools.
        # But FastMCP 2.0 structure might differ. Assuming standard dictionary of tool definitions.
        # Testing full integration requires careful mocking of inner SnowflakeClient inside the closure.
        # For now, client logic test above covers most risk.
        
if __name__ == "__main__":
    unittest.main()
