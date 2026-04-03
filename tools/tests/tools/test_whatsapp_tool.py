"""
Tests for WhatsApp Cloud API tool.

Covers:
- _WhatsAppClient methods (send_message, send_template, list_templates,
  mark_as_read, send_reaction, send_media)
- Error handling (API errors, invalid token, rate limiting)
- Credential retrieval (CredentialStoreAdapter vs env var)
- MCP tool functions (whatsapp_send_message, whatsapp_send_template,
  whatsapp_list_templates, whatsapp_mark_as_read, whatsapp_send_reaction,
  whatsapp_send_image, whatsapp_send_document)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from fastmcp import FastMCP

from aden_tools.tools.whatsapp_tool.whatsapp_tool import (
    _WhatsAppClient,
    register_tools,
)

# --- _WhatsAppClient tests ---


class TestWhatsAppClient:
    def setup_method(self):
        self.client = _WhatsAppClient("test-access-token", "123456789")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "Bearer test-access-token"
        assert headers["Content-Type"] == "application/json"

    def test_messages_url(self):
        assert "123456789/messages" in self.client._messages_url
        assert self.client._messages_url.startswith("https://graph.facebook.com/v25.0/")

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "messages": [{"id": "wamid.abc123"}],
        }
        result = self.client._handle_response(response)
        assert "messages" in result
        assert result["messages"][0]["id"] == "wamid.abc123"

    def test_handle_response_401(self):
        response = MagicMock()
        response.status_code = 401
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Invalid" in result["error"] or "expired" in result["error"]

    def test_handle_response_429(self):
        response = MagicMock()
        response.status_code = 429
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Rate limit" in result["error"]

    def test_handle_response_api_error(self):
        response = MagicMock()
        response.status_code = 400
        response.json.return_value = {
            "error": {
                "message": "Invalid parameter",
                "code": 100,
                "type": "OAuthException",
            }
        }
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Invalid parameter" in result["error"]
        assert result["error_code"] == 100

    def test_handle_response_expired_window(self):
        response = MagicMock()
        response.status_code = 400
        response.json.return_value = {
            "error": {
                "message": "Re-engagement message",
                "code": 131047,
            }
        }
        result = self.client._handle_response(response)
        assert "error" in result
        assert "template" in result["error"].lower()

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_message(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [{"id": "wamid.msg123"}],
        }
        mock_post.return_value = mock_response

        result = self.client.send_message("+14155552671", "Hello!")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["type"] == "text"
        assert call_kwargs["json"]["text"]["body"] == "Hello!"
        assert call_kwargs["json"]["to"] == "+14155552671"
        assert result["messages"][0]["id"] == "wamid.msg123"

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_template(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [{"id": "wamid.tmpl123"}],
        }
        mock_post.return_value = mock_response

        result = self.client.send_template("+14155552671", "hello_world", "en")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["type"] == "template"
        assert call_kwargs["json"]["template"]["name"] == "hello_world"
        assert call_kwargs["json"]["template"]["language"]["code"] == "en"
        assert result["messages"][0]["id"] == "wamid.tmpl123"

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_template_with_components(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.x"}]}
        mock_post.return_value = mock_response

        components = [{"type": "body", "parameters": [{"type": "text", "text": "John"}]}]
        self.client.send_template("+14155552671", "welcome", "en", components)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["template"]["components"] == components

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.get")
    def test_list_templates(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "name": "hello_world",
                    "status": "APPROVED",
                    "language": "en",
                    "category": "UTILITY",
                },
            ]
        }
        mock_get.return_value = mock_response

        result = self.client.list_templates("waba123")

        mock_get.assert_called_once()
        assert result["data"][0]["name"] == "hello_world"

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_mark_as_read(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}
        mock_post.return_value = mock_response

        result = self.client.mark_as_read("wamid.abc")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["status"] == "read"
        assert call_kwargs["json"]["message_id"] == "wamid.abc"
        assert result["success"] is True

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_reaction(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.react1"}]}
        mock_post.return_value = mock_response

        self.client.send_reaction("+14155552671", "wamid.abc", "\U0001f44d")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["to"] == "+14155552671"
        assert call_kwargs["json"]["type"] == "reaction"
        assert call_kwargs["json"]["reaction"]["emoji"] == "\U0001f44d"
        assert call_kwargs["json"]["reaction"]["message_id"] == "wamid.abc"

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_media_image(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.img1"}]}
        mock_post.return_value = mock_response

        self.client.send_media(
            "+14155552671", "image", "https://example.com/photo.jpg", caption="A photo"
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["type"] == "image"
        assert call_kwargs["json"]["image"]["link"] == "https://example.com/photo.jpg"
        assert call_kwargs["json"]["image"]["caption"] == "A photo"

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_media_document_with_filename(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.doc1"}]}
        mock_post.return_value = mock_response

        self.client.send_media(
            "+14155552671",
            "document",
            "https://example.com/report.pdf",
            caption="Report",
            filename="report.pdf",
        )

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["type"] == "document"
        assert call_kwargs["json"]["document"]["filename"] == "report.pdf"


# --- register_tools tests ---


class TestRegisterTools:
    def setup_method(self):
        self.mcp = FastMCP("test-whatsapp")

    def test_register_tools_creates_tools(self):
        register_tools(self.mcp)

        tool_names = [tool.name for tool in self.mcp._tool_manager._tools.values()]
        assert "whatsapp_send_message" in tool_names
        assert "whatsapp_send_template" in tool_names
        assert "whatsapp_list_templates" in tool_names
        assert "whatsapp_mark_as_read" in tool_names
        assert "whatsapp_send_reaction" in tool_names
        assert "whatsapp_send_image" in tool_names
        assert "whatsapp_send_document" in tool_names

    def test_no_credentials_returns_error(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        with patch("os.getenv", return_value=None):
            result = tools["whatsapp_send_message"].fn(to="+14155552671", body="test")

        assert "error" in result
        assert "not configured" in result["error"]

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_message_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messages": [{"id": "wamid.ok123"}],
        }
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        with patch(
            "os.getenv",
            side_effect=lambda k: {
                "WHATSAPP_ACCESS_TOKEN": "test-token",
                "WHATSAPP_PHONE_NUMBER_ID": "12345",
            }.get(k),
        ):
            result = tools["whatsapp_send_message"].fn(to="+14155552671", body="Hello!")

        assert result["success"] is True
        assert result["message_id"] == "wamid.ok123"

    def test_credentials_adapter_used(self):
        mock_credentials = MagicMock()
        mock_credentials.get.side_effect = lambda k: {
            "whatsapp": "token-from-store",
            "whatsapp_phone_number_id": "phone-from-store",
        }.get(k)

        register_tools(self.mcp, credentials=mock_credentials)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        with patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"messages": [{"id": "wamid.x"}]}
            mock_post.return_value = mock_response

            tools["whatsapp_send_message"].fn(to="+14155552671", body="test")

            call_kwargs = mock_post.call_args.kwargs
            assert "token-from-store" in call_kwargs["headers"]["Authorization"]

    def test_send_message_missing_params(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        result = tools["whatsapp_send_message"].fn(to="", body="")
        assert "error" in result

    def test_send_template_missing_params(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        result = tools["whatsapp_send_template"].fn(to="", template_name="")
        assert "error" in result

    def test_send_template_invalid_components_json(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        with patch(
            "os.getenv",
            side_effect=lambda k: {
                "WHATSAPP_ACCESS_TOKEN": "tok",
                "WHATSAPP_PHONE_NUMBER_ID": "123",
            }.get(k),
        ):
            result = tools["whatsapp_send_template"].fn(
                to="+14155552671",
                template_name="hello",
                components="{invalid json",
            )

        assert "error" in result
        assert "Invalid components JSON" in result["error"]

    def test_list_templates_missing_waba_id(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        result = tools["whatsapp_list_templates"].fn(waba_id="")
        assert "error" in result

    def test_mark_as_read_missing_message_id(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        result = tools["whatsapp_mark_as_read"].fn(message_id="")
        assert "error" in result

    def test_send_reaction_missing_params(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        result = tools["whatsapp_send_reaction"].fn(to="", message_id="", emoji="")
        assert "error" in result

    def test_send_image_missing_params(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        result = tools["whatsapp_send_image"].fn(to="", image_url="")
        assert "error" in result

    def test_send_document_missing_params(self):
        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        result = tools["whatsapp_send_document"].fn(to="", document_url="")
        assert "error" in result


# --- Error handling tests ---


class TestErrorHandling:
    def setup_method(self):
        self.mcp = FastMCP("test-whatsapp")

    def _get_tools(self):
        return {t.name: t for t in self.mcp._tool_manager._tools.values()}

    def _env_patch(self):
        return patch(
            "os.getenv",
            side_effect=lambda k: {
                "WHATSAPP_ACCESS_TOKEN": "tok",
                "WHATSAPP_PHONE_NUMBER_ID": "123",
            }.get(k),
        )

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_message_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with self._env_patch():
            result = tools["whatsapp_send_message"].fn(to="+1234", body="test")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_message_network_error(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("Connection failed")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with self._env_patch():
            result = tools["whatsapp_send_message"].fn(to="+1234", body="test")

        assert "error" in result
        assert "network" in result["error"].lower() or "connection" in result["error"].lower()

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_template_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with self._env_patch():
            result = tools["whatsapp_send_template"].fn(to="+1234", template_name="hello")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.get")
    def test_list_templates_timeout(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with self._env_patch():
            result = tools["whatsapp_list_templates"].fn(waba_id="waba123")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_mark_as_read_network_error(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("Connection failed")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with self._env_patch():
            result = tools["whatsapp_mark_as_read"].fn(message_id="wamid.abc")

        assert "error" in result

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_reaction_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with self._env_patch():
            result = tools["whatsapp_send_reaction"].fn(
                to="+14155552671",
                message_id="wamid.abc",
                emoji="\U0001f44d",
            )

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_image_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with self._env_patch():
            result = tools["whatsapp_send_image"].fn(
                to="+1234", image_url="https://example.com/img.jpg"
            )

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_send_document_network_error(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("Connection failed")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with self._env_patch():
            result = tools["whatsapp_send_document"].fn(
                to="+1234", document_url="https://example.com/doc.pdf"
            )

        assert "error" in result

    @patch("aden_tools.tools.whatsapp_tool.whatsapp_tool.httpx.post")
    def test_all_tools_return_error_without_credentials(self, mock_post):
        """All tools should return error dict when no credentials are configured."""
        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        tool_calls = {
            "whatsapp_send_message": {"to": "+1234", "body": "test"},
            "whatsapp_send_template": {"to": "+1234", "template_name": "hello"},
            "whatsapp_list_templates": {"waba_id": "waba123"},
            "whatsapp_mark_as_read": {"message_id": "wamid.abc"},
            "whatsapp_send_reaction": {
                "to": "+14155552671",
                "message_id": "wamid.abc",
                "emoji": "\U0001f44d",
            },
            "whatsapp_send_image": {"to": "+1234", "image_url": "https://example.com/img.jpg"},
            "whatsapp_send_document": {
                "to": "+1234",
                "document_url": "https://example.com/doc.pdf",
            },
        }

        with patch("os.getenv", return_value=None):
            for tool_name, kwargs in tool_calls.items():
                result = tools[tool_name].fn(**kwargs)
                assert "error" in result, f"{tool_name} should return error without credentials"
                assert "not configured" in result["error"]
