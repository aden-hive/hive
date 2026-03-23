"""
Tests for Mattermost tool.

Covers:
- _MattermostClient methods (list_teams, list_channels, send_message, get_posts, etc.)
- Error handling (401, 403, 404, 429, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All MCP tool functions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.mattermost_tool.mattermost_tool import (
    MAX_MESSAGE_LENGTH,
    MAX_RETRIES,
    _MattermostClient,
    register_tools,
)

# --- _MattermostClient tests ---


class TestMattermostClient:
    def setup_method(self):
        self.client = _MattermostClient(
            "test-access-token", "https://mattermost.example.com"
        )

    def test_headers(self):
        headers = self.client._headers
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer test-access-token"

    def test_base_url_strips_trailing_slash(self):
        client = _MattermostClient("tok", "https://mm.example.com/")
        assert client._base_url == "https://mm.example.com/api/v4"

    def test_base_url_preserves_api_v4(self):
        client = _MattermostClient("tok", "https://mm.example.com/api/v4")
        assert client._base_url == "https://mm.example.com/api/v4"

    def test_base_url_appends_api_v4(self):
        client = _MattermostClient("tok", "https://mm.example.com")
        assert client._base_url == "https://mm.example.com/api/v4"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id": "abc123", "username": "testbot"}
        assert self.client._handle_response(response) == {
            "id": "abc123",
            "username": "testbot",
        }

    def test_handle_response_201(self):
        response = MagicMock()
        response.status_code = 201
        response.json.return_value = {"id": "post123", "message": "hello"}
        result = self.client._handle_response(response)
        assert result == {"id": "post123", "message": "hello"}

    def test_handle_response_204(self):
        response = MagicMock()
        response.status_code = 204
        result = self.client._handle_response(response)
        assert result == {"success": True}

    def test_handle_response_rate_limit_429(self):
        response = MagicMock()
        response.status_code = 429
        response.headers = {"Retry-After": "2.5"}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert result["retry_after"] == 2.5

    @pytest.mark.parametrize("status_code", [401, 403, 404, 500])
    def test_handle_response_errors(self, status_code):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"message": "Test error"}
        response.text = "Test error"
        result = self.client._handle_response(response)
        assert "error" in result
        assert str(status_code) in result["error"]

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_list_teams(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "t1", "name": "test-team", "display_name": "Test Team"},
                    {"id": "t2", "name": "dev-team", "display_name": "Dev Team"},
                ]
            ),
        )
        result = self.client.list_teams()
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "GET"
        assert "users/me/teams" in mock_request.call_args[0][1]
        assert len(result) == 2
        assert result[0]["display_name"] == "Test Team"

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_list_channels(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "c1", "name": "town-square", "type": "O"},
                    {"id": "c2", "name": "off-topic", "type": "O"},
                ]
            ),
        )
        result = self.client.list_channels("t1")
        mock_request.assert_called_once()
        assert "teams/t1/channels" in mock_request.call_args[0][1]
        assert len(result) == 2
        assert result[0]["name"] == "town-square"

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_send_message(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=201,
            json=MagicMock(
                return_value={
                    "id": "p123",
                    "channel_id": "c1",
                    "message": "Hello world",
                }
            ),
        )
        result = self.client.send_message("c1", "Hello world")
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "POST"
        assert "posts" in mock_request.call_args[0][1]
        assert result["message"] == "Hello world"

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_send_message_with_thread(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=201,
            json=MagicMock(
                return_value={
                    "id": "p124",
                    "channel_id": "c1",
                    "message": "Reply",
                    "root_id": "p123",
                }
            ),
        )
        result = self.client.send_message("c1", "Reply", root_id="p123")
        call_kwargs = mock_request.call_args[1]
        assert call_kwargs["json"]["root_id"] == "p123"
        assert result["root_id"] == "p123"

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_get_posts(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "order": ["p1", "p2"],
                    "posts": {
                        "p1": {"id": "p1", "message": "First"},
                        "p2": {"id": "p2", "message": "Second"},
                    },
                }
            ),
        )
        result = self.client.get_posts("c1", per_page=10)
        mock_request.assert_called_once()
        assert mock_request.call_args[1]["params"]["per_page"] == 10
        assert "order" in result
        assert len(result["order"]) == 2

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_get_channel(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "c1",
                    "name": "town-square",
                    "display_name": "Town Square",
                    "type": "O",
                }
            ),
        )
        result = self.client.get_channel("c1")
        assert result["name"] == "town-square"
        assert result["type"] == "O"

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_delete_post(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200, json=MagicMock(return_value={"status": "ok"}))
        result = self.client.delete_post("p123")
        assert mock_request.call_args[0][0] == "DELETE"
        assert "posts/p123" in mock_request.call_args[0][1]

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_create_reaction(self, mock_request):
        # First call returns user info, second creates the reaction
        mock_request.side_effect = [
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"id": "user123", "username": "testbot"}),
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(
                    return_value={
                        "user_id": "user123",
                        "post_id": "p123",
                        "emoji_name": "thumbsup",
                    }
                ),
            ),
        ]
        result = self.client.create_reaction("p123", "thumbsup")
        assert result["emoji_name"] == "thumbsup"
        # Second call should be the reaction POST
        assert mock_request.call_args_list[1][1]["json"]["emoji_name"] == "thumbsup"

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.time.sleep")
    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_retry_on_429_then_success(self, mock_request, mock_sleep):
        mock_request.side_effect = [
            MagicMock(
                status_code=429,
                headers={"Retry-After": "0.01"},
                text="{}",
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(
                    return_value=[{"id": "t1", "name": "team"}]
                ),
            ),
        ]
        result = self.client.list_teams()
        assert len(result) == 1
        assert result[0]["name"] == "team"
        assert mock_request.call_count == 2
        mock_sleep.assert_called_once_with(0.01)

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.time.sleep")
    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_retry_exhausted_returns_error(self, mock_request, mock_sleep):
        mock_request.return_value = MagicMock(
            status_code=429,
            headers={"Retry-After": "0.01"},
            text="{}",
        )
        result = self.client.list_teams()
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert mock_request.call_count == MAX_RETRIES + 1


# --- Tool registration tests ---


class TestMattermostListTeamsTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.side_effect = lambda key: {
            "mattermost": "test-token",
            "mattermost_url": "https://mattermost.example.com",
        }.get(key)
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_list_teams_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[{"id": "t1", "name": "test-team"}]
            ),
        )
        result = self._fn("mattermost_list_teams")()
        assert result["success"] is True
        assert len(result["teams"]) == 1
        assert result["teams"][0]["name"] == "test-team"

    def test_list_teams_no_credentials(self):
        mcp = MagicMock()
        fns = []
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        register_tools(mcp, credentials=None)
        with patch.dict("os.environ", {"MATTERMOST_ACCESS_TOKEN": ""}, clear=False):
            result = next(
                f for f in fns if f.__name__ == "mattermost_list_teams"
            )()
        assert "error" in result
        assert "not configured" in result["error"]


class TestMattermostListChannelsTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.side_effect = lambda key: {
            "mattermost": "test-token",
            "mattermost_url": "https://mattermost.example.com",
        }.get(key)
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_list_channels_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "c1", "name": "town-square", "type": "O"},
                ]
            ),
        )
        result = self._fn("mattermost_list_channels")("team-123")
        assert result["success"] is True
        assert len(result["channels"]) == 1
        assert result["channels"][0]["name"] == "town-square"

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_list_channels_error(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=404,
            json=MagicMock(return_value={"message": "Unknown Team"}),
            text="Unknown Team",
        )
        result = self._fn("mattermost_list_channels")("bad-team")
        assert "error" in result
        assert "404" in result["error"]


class TestMattermostSendMessageTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.side_effect = lambda key: {
            "mattermost": "test-token",
            "mattermost_url": "https://mattermost.example.com",
        }.get(key)
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_send_message_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=201,
            json=MagicMock(
                return_value={
                    "id": "p123",
                    "channel_id": "c1",
                    "message": "Incident resolved",
                }
            ),
        )
        result = self._fn("mattermost_send_message")("c1", "Incident resolved")
        assert result["success"] is True
        assert result["post"]["message"] == "Incident resolved"

    def test_send_message_length_validation(self):
        long_content = "x" * (MAX_MESSAGE_LENGTH + 1)
        result = self._fn("mattermost_send_message")("c1", long_content)
        assert "error" in result
        assert str(MAX_MESSAGE_LENGTH) in result["error"]
        assert result["max_length"] == MAX_MESSAGE_LENGTH
        assert result["provided"] == MAX_MESSAGE_LENGTH + 1

    def test_send_message_exactly_at_limit(self):
        content = "x" * MAX_MESSAGE_LENGTH
        with patch(
            "aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request"
        ) as mock_request:
            mock_request.return_value = MagicMock(
                status_code=201,
                json=MagicMock(
                    return_value={"id": "p1", "channel_id": "c1", "message": content}
                ),
            )
            result = self._fn("mattermost_send_message")("c1", content)
        assert result["success"] is True

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_send_message_rate_limit_429_exhausted(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=429,
            headers={"Retry-After": "5"},
            text="{}",
        )
        result = self._fn("mattermost_send_message")("c1", "Hello")
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert mock_request.call_count == MAX_RETRIES + 1

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_send_message_rate_limit_then_success(self, mock_request):
        mock_request.side_effect = [
            MagicMock(
                status_code=429,
                headers={"Retry-After": "0.01"},
                text="{}",
            ),
            MagicMock(
                status_code=201,
                json=MagicMock(
                    return_value={"id": "p1", "channel_id": "c1", "message": "Hi"}
                ),
            ),
        ]
        result = self._fn("mattermost_send_message")("c1", "Hi")
        assert result["success"] is True
        assert result["post"]["message"] == "Hi"
        assert mock_request.call_count == 2


class TestMattermostGetPostsTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.side_effect = lambda key: {
            "mattermost": "test-token",
            "mattermost_url": "https://mattermost.example.com",
        }.get(key)
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_get_posts_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "order": ["p1"],
                    "posts": {"p1": {"id": "p1", "message": "First message"}},
                }
            ),
        )
        result = self._fn("mattermost_get_posts")("c1", per_page=10)
        assert result["success"] is True
        assert "posts" in result


class TestMattermostGetChannelTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.side_effect = lambda key: {
            "mattermost": "test-token",
            "mattermost_url": "https://mattermost.example.com",
        }.get(key)
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_get_channel_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "c1",
                    "name": "town-square",
                    "display_name": "Town Square",
                    "type": "O",
                }
            ),
        )
        result = self._fn("mattermost_get_channel")("c1")
        assert result["success"] is True
        assert result["channel"]["name"] == "town-square"


class TestMattermostDeletePostTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.side_effect = lambda key: {
            "mattermost": "test-token",
            "mattermost_url": "https://mattermost.example.com",
        }.get(key)
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_delete_post_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200, json=MagicMock(return_value={"status": "ok"})
        )
        result = self._fn("mattermost_delete_post")("p123")
        assert result["success"] is True
        assert result["deleted_post_id"] == "p123"


class TestMattermostCreateReactionTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.side_effect = lambda key: {
            "mattermost": "test-token",
            "mattermost_url": "https://mattermost.example.com",
        }.get(key)
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
    def test_create_reaction_success(self, mock_request):
        mock_request.side_effect = [
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"id": "user123"}),
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(
                    return_value={
                        "user_id": "user123",
                        "post_id": "p123",
                        "emoji_name": "thumbsup",
                    }
                ),
            ),
        ]
        result = self._fn("mattermost_create_reaction")("p123", "thumbsup")
        assert result["success"] is True


class TestMattermostNoUrl:
    """Test that missing URL returns a helpful error."""

    def test_missing_url_returns_error(self):
        mcp = MagicMock()
        fns = []
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        cred = MagicMock()
        # Token is set but URL is not
        cred.get.side_effect = lambda key: {
            "mattermost": "test-token",
            "mattermost_url": None,
        }.get(key)
        register_tools(mcp, credentials=cred)
        with patch.dict("os.environ", {"MATTERMOST_URL": ""}, clear=False):
            fn = next(f for f in fns if f.__name__ == "mattermost_list_teams")
            result = fn()
        assert "error" in result
        assert "URL" in result["error"]


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_mattermost_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "mattermost" in CREDENTIAL_SPECS

    def test_mattermost_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["mattermost"]
        assert spec.env_var == "MATTERMOST_ACCESS_TOKEN"

    def test_mattermost_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["mattermost"]
        assert "mattermost_list_teams" in spec.tools
        assert "mattermost_list_channels" in spec.tools
        assert "mattermost_get_channel" in spec.tools
        assert "mattermost_send_message" in spec.tools
        assert "mattermost_get_posts" in spec.tools
        assert "mattermost_create_reaction" in spec.tools
        assert "mattermost_delete_post" in spec.tools
        assert len(spec.tools) == 7

    def test_mattermost_url_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "mattermost_url" in CREDENTIAL_SPECS

    def test_mattermost_url_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["mattermost_url"]
        assert spec.env_var == "MATTERMOST_URL"
