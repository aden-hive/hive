"""
Tests for Google Sheets tool.

Covers:
- _GoogleSheetsClient methods (all CRUD operations)
- Error handling (401, 403, 404, 429, 500, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 11 MCP tool functions
- Batch operations
- Sheet management
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.google_sheets_tool.google_sheets_tool import (
    GOOGLE_SHEETS_API_BASE,
    _GoogleSheetsClient,
    register_tools,
)

# --- _GoogleSheetsClient tests ---


class TestGoogleSheetsClient:
    def setup_method(self):
        self.client = _GoogleSheetsClient("test-token")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"spreadsheetId": "123"}
        assert self.client._handle_response(response) == {"spreadsheetId": "123"}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid or expired"),
            (403, "Insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        response = MagicMock()
        response.status_code = status_code
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    def test_handle_response_generic_error(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"error": {"message": "Internal Server Error"}}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]

    def test_handle_response_generic_error_fallback(self):
        response = MagicMock()
        response.status_code = 500
        response.json.side_effect = Exception("parse error")
        response.text = "Internal Server Error"
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_get_spreadsheet(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "spreadsheetId": "123",
            "properties": {"title": "Test Sheet"},
        }
        mock_get.return_value = mock_response

        result = self.client.get_spreadsheet("123")

        mock_get.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123",
            headers=self.client._headers,
            params={},
            timeout=30.0,
        )
        assert result["spreadsheetId"] == "123"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_get_spreadsheet_with_grid_data(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"spreadsheetId": "123"}
        mock_get.return_value = mock_response

        self.client.get_spreadsheet("123", include_grid_data=True)

        assert mock_get.call_args.kwargs["params"]["includeGridData"] == "true"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_create_spreadsheet(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "spreadsheetId": "456",
            "properties": {"title": "New Sheet"},
        }
        mock_post.return_value = mock_response

        result = self.client.create_spreadsheet("New Sheet")

        mock_post.assert_called_once_with(
            GOOGLE_SHEETS_API_BASE,
            headers=self.client._headers,
            json={"properties": {"title": "New Sheet"}},
            timeout=30.0,
        )
        assert result["spreadsheetId"] == "456"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_create_spreadsheet_with_sheets(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"spreadsheetId": "456"}
        mock_post.return_value = mock_response

        self.client.create_spreadsheet("New Sheet", sheet_titles=["Sheet1", "Sheet2"])

        call_json = mock_post.call_args.kwargs["json"]
        assert "sheets" in call_json
        assert len(call_json["sheets"]) == 2
        assert call_json["sheets"][0]["properties"]["title"] == "Sheet1"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_get_values(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "range": "Sheet1!A1:B2",
            "values": [["A1", "B1"], ["A2", "B2"]],
        }
        mock_get.return_value = mock_response

        result = self.client.get_values("123", "Sheet1!A1:B2")

        mock_get.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123/values/Sheet1!A1:B2",
            headers=self.client._headers,
            params={"valueRenderOption": "FORMATTED_VALUE"},
            timeout=30.0,
        )
        assert result["values"] == [["A1", "B1"], ["A2", "B2"]]

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_get_values_unformatted(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"values": [["1", "2"]]}
        mock_get.return_value = mock_response

        self.client.get_values("123", "Sheet1!A1:B1", value_render_option="UNFORMATTED_VALUE")

        assert mock_get.call_args.kwargs["params"]["valueRenderOption"] == "UNFORMATTED_VALUE"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.put")
    def test_update_values(self, mock_put):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "updatedCells": 4,
            "updatedRows": 2,
        }
        mock_put.return_value = mock_response

        values = [["A1", "B1"], ["A2", "B2"]]
        result = self.client.update_values("123", "Sheet1!A1:B2", values)

        mock_put.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123/values/Sheet1!A1:B2",
            headers=self.client._headers,
            params={"valueInputOption": "USER_ENTERED"},
            json={"values": values},
            timeout=30.0,
        )
        assert result["updatedCells"] == 4

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.put")
    def test_update_values_raw(self, mock_put):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updatedCells": 1}
        mock_put.return_value = mock_response

        self.client.update_values("123", "Sheet1!A1", [["value"]], value_input_option="RAW")

        assert mock_put.call_args.kwargs["params"]["valueInputOption"] == "RAW"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_append_values(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "updates": {"updatedCells": 2},
        }
        mock_post.return_value = mock_response

        values = [["new", "row"]]
        result = self.client.append_values("123", "Sheet1!A1", values)

        mock_post.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123/values/Sheet1!A1:append",
            headers=self.client._headers,
            params={"valueInputOption": "USER_ENTERED"},
            json={"values": values},
            timeout=30.0,
        )
        assert "updates" in result

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_clear_values(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"clearedRange": "Sheet1!A1:B2"}
        mock_post.return_value = mock_response

        result = self.client.clear_values("123", "Sheet1!A1:B2")

        mock_post.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123/values/Sheet1!A1:B2:clear",
            headers=self.client._headers,
            timeout=30.0,
        )
        assert result["clearedRange"] == "Sheet1!A1:B2"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_batch_update_values(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "totalUpdatedCells": 6,
        }
        mock_post.return_value = mock_response

        data = [
            {"range": "Sheet1!A1:B1", "values": [["A", "B"]]},
            {"range": "Sheet1!A2:B2", "values": [["C", "D"]]},
        ]
        result = self.client.batch_update_values("123", data)

        mock_post.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123/values:batchUpdate",
            headers=self.client._headers,
            json={"valueInputOption": "USER_ENTERED", "data": data},
            timeout=30.0,
        )
        assert result["totalUpdatedCells"] == 6

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_batch_clear_values(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "clearedRanges": ["Sheet1!A1:B1", "Sheet1!C1:D1"],
        }
        mock_post.return_value = mock_response

        ranges = ["Sheet1!A1:B1", "Sheet1!C1:D1"]
        result = self.client.batch_clear_values("123", ranges)

        mock_post.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123/values:batchClear",
            headers=self.client._headers,
            json={"ranges": ranges},
            timeout=30.0,
        )
        assert len(result["clearedRanges"]) == 2

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_add_sheet(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "replies": [{"addSheet": {"properties": {"sheetId": 1, "title": "New Sheet"}}}]
        }
        mock_post.return_value = mock_response

        result = self.client.add_sheet("123", "New Sheet")

        mock_post.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123:batchUpdate",
            headers=self.client._headers,
            json={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": "New Sheet",
                                "gridProperties": {
                                    "rowCount": 1000,
                                    "columnCount": 26,
                                },
                            }
                        }
                    }
                ]
            },
            timeout=30.0,
        )
        assert "replies" in result

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_add_sheet_custom_dimensions(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"replies": []}
        mock_post.return_value = mock_response

        self.client.add_sheet("123", "Custom Sheet", row_count=500, column_count=10)

        call_json = mock_post.call_args.kwargs["json"]
        grid_props = call_json["requests"][0]["addSheet"]["properties"]["gridProperties"]
        assert grid_props["rowCount"] == 500
        assert grid_props["columnCount"] == 10

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_delete_sheet(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"replies": [{}]}
        mock_post.return_value = mock_response

        result = self.client.delete_sheet("123", 456)

        mock_post.assert_called_once_with(
            f"{GOOGLE_SHEETS_API_BASE}/123:batchUpdate",
            headers=self.client._headers,
            json={"requests": [{"deleteSheet": {"sheetId": 456}}]},
            timeout=30.0,
        )
        assert "replies" in result


# --- MCP tool registration and credential tests ---


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        assert mcp.tool.call_count == 10

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        # Pick the first tool and call it
        get_fn = next(fn for fn in registered_fns if fn.__name__ == "google_sheets_get_values")
        result = get_fn(spreadsheet_id="123", range_name="Sheet1!A1")
        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_credential_manager(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "test-token"

        register_tools(mcp, credentials=cred_manager)

        get_fn = next(fn for fn in registered_fns if fn.__name__ == "google_sheets_get_values")

        with patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"values": [["test"]]}
            mock_get.return_value = mock_response

            result = get_fn(spreadsheet_id="123", range_name="Sheet1!A1")

        cred_manager.get.assert_called_with("google")
        assert result["values"] == [["test"]]

    def test_credentials_from_env_var(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        get_fn = next(fn for fn in registered_fns if fn.__name__ == "google_sheets_get_values")

        with (
            patch.dict("os.environ", {"GOOGLE_ACCESS_TOKEN": "env-token"}),
            patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get") as mock_get,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"values": [["test"]]}
            mock_get.return_value = mock_response

            result = get_fn(spreadsheet_id="123", range_name="Sheet1!A1")

        assert result["values"] == [["test"]]
        # Verify the token was used in headers
        call_headers = mock_get.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Bearer env-token"

    def test_credentials_wrong_type_raises_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = {"not": "a string"}

        register_tools(mcp, credentials=cred_manager)

        get_fn = next(fn for fn in registered_fns if fn.__name__ == "google_sheets_get_values")

        with pytest.raises(TypeError, match="Expected string"):
            get_fn(spreadsheet_id="123", range_name="Sheet1!A1")


# --- Individual tool function tests ---


class TestSpreadsheetTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_get_spreadsheet(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"spreadsheetId": "123"})
        )
        result = self._fn("google_sheets_get_spreadsheet")(spreadsheet_id="123")
        assert result["spreadsheetId"] == "123"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_create_spreadsheet(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"spreadsheetId": "456"})
        )
        result = self._fn("google_sheets_create_spreadsheet")(title="New Sheet")
        assert result["spreadsheetId"] == "456"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_get_spreadsheet_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("google_sheets_get_spreadsheet")(spreadsheet_id="123")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_create_spreadsheet_network_error(self, mock_post):
        mock_post.side_effect = httpx.RequestError("connection failed")
        result = self._fn("google_sheets_create_spreadsheet")(title="New")
        assert "error" in result
        assert "Network error" in result["error"]


class TestReadDataTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_get_values(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"values": [["A", "B"]]})
        )
        result = self._fn("google_sheets_get_values")(
            spreadsheet_id="123", range_name="Sheet1!A1:B1"
        )
        assert result["values"] == [["A", "B"]]

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_get_values_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("google_sheets_get_values")(spreadsheet_id="123", range_name="Sheet1!A1")
        assert "error" in result
        assert "timed out" in result["error"]


class TestWriteDataTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.put")
    def test_update_values(self, mock_put):
        mock_put.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"updatedCells": 2})
        )
        result = self._fn("google_sheets_update_values")(
            spreadsheet_id="123", range_name="Sheet1!A1:B1", values=[["A", "B"]]
        )
        assert result["updatedCells"] == 2

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_append_values(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"updates": {"updatedCells": 2}})
        )
        result = self._fn("google_sheets_append_values")(
            spreadsheet_id="123", range_name="Sheet1!A1", values=[["new", "row"]]
        )
        assert "updates" in result

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_clear_values(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"clearedRange": "Sheet1!A1:B2"})
        )
        result = self._fn("google_sheets_clear_values")(
            spreadsheet_id="123", range_name="Sheet1!A1:B2"
        )
        assert result["clearedRange"] == "Sheet1!A1:B2"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.put")
    def test_update_values_network_error(self, mock_put):
        mock_put.side_effect = httpx.RequestError("connection failed")
        result = self._fn("google_sheets_update_values")(
            spreadsheet_id="123", range_name="Sheet1!A1", values=[["test"]]
        )
        assert "error" in result
        assert "Network error" in result["error"]


class TestBatchOperationsTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_batch_update_values(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"totalUpdatedCells": 4})
        )
        data = [
            {"range": "Sheet1!A1", "values": [["A"]]},
            {"range": "Sheet1!B1", "values": [["B"]]},
        ]
        result = self._fn("google_sheets_batch_update_values")(spreadsheet_id="123", data=data)
        assert result["totalUpdatedCells"] == 4

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_batch_clear_values(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"clearedRanges": ["Sheet1!A1"]})
        )
        result = self._fn("google_sheets_batch_clear_values")(
            spreadsheet_id="123", ranges=["Sheet1!A1"]
        )
        assert "clearedRanges" in result

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_batch_update_values_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("google_sheets_batch_update_values")(
            spreadsheet_id="123", data=[{"range": "A1", "values": [["test"]]}]
        )
        assert "error" in result
        assert "timed out" in result["error"]


class TestSheetManagementTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_add_sheet(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"replies": [{"addSheet": {"properties": {"sheetId": 1}}}]}
            ),
        )
        result = self._fn("google_sheets_add_sheet")(spreadsheet_id="123", title="New Sheet")
        assert "replies" in result

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_delete_sheet(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"replies": [{}]})
        )
        result = self._fn("google_sheets_delete_sheet")(spreadsheet_id="123", sheet_id=456)
        assert "replies" in result

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_add_sheet_network_error(self, mock_post):
        mock_post.side_effect = httpx.RequestError("connection failed")
        result = self._fn("google_sheets_add_sheet")(spreadsheet_id="123", title="New")
        assert "error" in result
        assert "Network error" in result["error"]

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_delete_sheet_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("google_sheets_delete_sheet")(spreadsheet_id="123", sheet_id=1)
        assert "error" in result
        assert "timed out" in result["error"]


# --- Error sanitization tests ---


class TestErrorSanitization:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_bearer_token_redacted_from_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError(
            "Connection failed, Authorization: Bearer ya29.secret_token_here"
        )
        result = self._fn("google_sheets_get_spreadsheet")(spreadsheet_id="123")
        assert "error" in result
        assert "Network error" in result["error"]
        assert "Bearer" not in result["error"]
        assert "secret_token" not in result["error"]
        assert "redacted" in result["error"]

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_authorization_header_redacted_from_error(self, mock_get):
        mock_get.side_effect = httpx.RequestError("Failed with Authorization header present")
        result = self._fn("google_sheets_get_spreadsheet")(spreadsheet_id="123")
        assert "error" in result
        assert "Authorization" not in result["error"]
        assert "redacted" in result["error"]

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_long_error_message_truncated(self, mock_get):
        long_msg = "x" * 300
        mock_get.side_effect = httpx.RequestError(long_msg)
        result = self._fn("google_sheets_get_spreadsheet")(spreadsheet_id="123")
        assert "error" in result
        assert len(result["error"]) < 300

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_safe_error_message_passes_through(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection refused")
        result = self._fn("google_sheets_get_spreadsheet")(spreadsheet_id="123")
        assert "error" in result
        assert "connection refused" in result["error"]


# --- Tracking parameter tests ---


class TestTrackingParameters:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get")
    def test_tracking_params_accepted_by_get_spreadsheet(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"spreadsheetId": "123"})
        )
        result = self._fn("google_sheets_get_spreadsheet")(
            spreadsheet_id="123",
            workspace_id="ws-1",
            agent_id="agent-1",
            session_id="sess-1",
        )
        assert result["spreadsheetId"] == "123"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_tracking_params_accepted_by_create_spreadsheet(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"spreadsheetId": "456"})
        )
        result = self._fn("google_sheets_create_spreadsheet")(
            title="Test",
            workspace_id="ws-1",
            agent_id="agent-1",
            session_id="sess-1",
        )
        assert result["spreadsheetId"] == "456"

    @patch("aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.post")
    def test_tracking_params_accepted_by_clear_values(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"clearedRange": "A1:B2"})
        )
        result = self._fn("google_sheets_clear_values")(
            spreadsheet_id="123",
            range_name="Sheet1!A1:B2",
            workspace_id="ws-1",
            agent_id="agent-1",
            session_id="sess-1",
        )
        assert result["clearedRange"] == "A1:B2"
