"""
Tests for Linear project management tool.

Covers:
- _LinearClient methods (issues, projects, teams, users, labels)
- GraphQL query construction and response handling
- Error handling (401, 403, 429, GraphQL errors, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 18 MCP tool functions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.linear_tool.linear_tool import (
    LINEAR_API_BASE,
    _LinearClient,
    register_tools,
)

# --- _LinearClient tests ---


class TestLinearClient:
    def setup_method(self):
        self.client = _LinearClient("lin_api_test_key")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Authorization"] == "lin_api_test_key"
        assert headers["Content-Type"] == "application/json"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {"issues": []}}
        result = self.client._handle_response(response)
        assert result == {"issues": []}

    @pytest.mark.parametrize(
        "status_code,expected_substring",
        [
            (401, "Invalid or expired"),
            (403, "Insufficient permissions"),
            (429, "rate limit"),
        ],
    )
    def test_handle_response_errors(self, status_code, expected_substring):
        response = MagicMock()
        response.status_code = status_code
        result = self.client._handle_response(response)
        assert "error" in result
        assert expected_substring in result["error"]

    def test_handle_response_graphql_error(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "errors": [{"message": "Issue not found"}],
        }
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Issue not found" in result["error"]

    def test_handle_response_generic_error(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"message": "Internal Server Error"}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "500" in result["error"]

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_execute_query(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"viewer": {"id": "user-123", "name": "Test User"}}
        }
        mock_post.return_value = mock_response

        result = self.client._execute_query("query Viewer { viewer { id name } }")

        mock_post.assert_called_once_with(
            LINEAR_API_BASE,
            headers=self.client._headers,
            json={"query": "query Viewer { viewer { id name } }"},
            timeout=30.0,
        )
        assert result == {"viewer": {"id": "user-123", "name": "Test User"}}

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_execute_query_with_variables(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"issue": {"id": "issue-123", "title": "Test Issue"}}
        }
        mock_post.return_value = mock_response

        result = self.client._execute_query(
            "query Issue($id: String!) { issue(id: $id) { id title } }",
            {"id": "issue-123"},
        )

        call_json = mock_post.call_args.kwargs["json"]
        assert "variables" in call_json
        assert call_json["variables"] == {"id": "issue-123"}

    # --- Issue Operations ---

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_create_issue(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "issue-456",
                        "identifier": "ENG-123",
                        "title": "Test Issue",
                        "url": "https://linear.app/team/issue/ENG-123",
                    },
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.create_issue(
            title="Test Issue",
            team_id="team-123",
            description="Test description",
            priority=2,
        )

        assert result["success"] is True
        assert result["issue"]["identifier"] == "ENG-123"

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_get_issue(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "issue": {
                    "id": "issue-123",
                    "identifier": "ENG-123",
                    "title": "Test Issue",
                    "state": {"name": "In Progress"},
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.get_issue("ENG-123")

        assert result["identifier"] == "ENG-123"
        assert result["state"]["name"] == "In Progress"

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_update_issue(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {"id": "issue-123", "title": "Updated Title"},
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.update_issue(
            issue_id="issue-123",
            title="Updated Title",
            priority=1,
        )

        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_delete_issue(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"issueDelete": {"success": True}}}
        mock_post.return_value = mock_response

        result = self.client.delete_issue("issue-123")

        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_search_issues(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "issues": {
                    "nodes": [
                        {"id": "1", "identifier": "ENG-1", "title": "Issue 1"},
                        {"id": "2", "identifier": "ENG-2", "title": "Issue 2"},
                    ],
                    "pageInfo": {"hasNextPage": False},
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.search_issues(query="bug", team_id="team-123", limit=10)

        assert result["total"] == 2
        assert len(result["issues"]) == 2

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_add_comment(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "commentCreate": {
                    "success": True,
                    "comment": {"id": "comment-123", "body": "Test comment"},
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.add_comment("issue-123", "Test comment")

        assert result["success"] is True

    # --- Project Operations ---

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_create_project(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "projectCreate": {
                    "success": True,
                    "project": {
                        "id": "project-123",
                        "name": "Q1 Roadmap",
                        "url": "https://linear.app/team/project/q1-roadmap",
                    },
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.create_project(
            name="Q1 Roadmap",
            team_ids=["team-123"],
            description="Q1 goals",
            state="planned",
        )

        assert result["success"] is True
        assert result["project"]["name"] == "Q1 Roadmap"

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_get_project(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "project": {
                    "id": "project-123",
                    "name": "Q1 Roadmap",
                    "progress": 0.5,
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.get_project("project-123")

        assert result["name"] == "Q1 Roadmap"
        assert result["progress"] == 0.5

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_list_projects(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "projects": {
                    "nodes": [
                        {"id": "1", "name": "Project 1"},
                        {"id": "2", "name": "Project 2"},
                    ],
                    "pageInfo": {"hasNextPage": False},
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.list_projects(limit=50)

        assert result["total"] == 2

    # --- Team Operations ---

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_list_teams(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "teams": {
                    "nodes": [
                        {"id": "team-1", "name": "Engineering", "key": "ENG"},
                        {"id": "team-2", "name": "Design", "key": "DES"},
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.list_teams()

        assert result["total"] == 2
        assert result["teams"][0]["key"] == "ENG"

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_get_workflow_states(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "workflowStates": {
                    "nodes": [
                        {"id": "state-1", "name": "Backlog", "type": "backlog"},
                        {"id": "state-2", "name": "In Progress", "type": "started"},
                        {"id": "state-3", "name": "Done", "type": "completed"},
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.get_workflow_states("team-123")

        assert result["total"] == 3

    # --- User Operations ---

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_list_users(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "users": {
                    "nodes": [
                        {"id": "user-1", "name": "Alice", "email": "alice@example.com"},
                        {"id": "user-2", "name": "Bob", "email": "bob@example.com"},
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.list_users()

        assert result["total"] == 2

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_get_viewer(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "viewer": {
                    "id": "user-123",
                    "name": "Test User",
                    "email": "test@example.com",
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.get_viewer()

        assert result["name"] == "Test User"

    # --- Label Operations ---

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_create_label(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "issueLabelCreate": {
                    "success": True,
                    "issueLabel": {"id": "label-123", "name": "bug", "color": "#FF0000"},
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.create_label(name="bug", team_id="team-123", color="#FF0000")

        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_list_labels(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "issueLabels": {
                    "nodes": [
                        {"id": "label-1", "name": "bug"},
                        {"id": "label-2", "name": "feature"},
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = self.client.list_labels()

        assert result["total"] == 2


# --- MCP tool registration and credential tests ---


class TestToolRegistration:
    def test_register_tools_registers_all_tools(self):
        mcp = MagicMock()
        mcp.tool.return_value = lambda fn: fn
        register_tools(mcp)
        # 18 tools: 6 issue + 4 project + 3 team + 2 label + 3 user
        assert mcp.tool.call_count == 18

    def test_no_credentials_returns_error(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        with patch.dict("os.environ", {}, clear=True):
            register_tools(mcp, credentials=None)

        # Pick the first tool and call it
        teams_fn = next(fn for fn in registered_fns if fn.__name__ == "linear_teams_list")
        result = teams_fn()
        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_credential_manager(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        cred_manager = MagicMock()
        cred_manager.get.return_value = "lin_api_test_key"

        register_tools(mcp, credentials=cred_manager)

        teams_fn = next(fn for fn in registered_fns if fn.__name__ == "linear_teams_list")

        with patch("aden_tools.tools.linear_tool.linear_tool.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"teams": {"nodes": []}}}
            mock_post.return_value = mock_response

            result = teams_fn()

        cred_manager.get.assert_called_with("linear")
        assert result["total"] == 0

    def test_credentials_from_env_var(self):
        mcp = MagicMock()
        registered_fns = []
        mcp.tool.return_value = lambda fn: registered_fns.append(fn) or fn

        register_tools(mcp, credentials=None)

        teams_fn = next(fn for fn in registered_fns if fn.__name__ == "linear_teams_list")

        with (
            patch.dict("os.environ", {"LINEAR_API_KEY": "lin_api_env_key"}),
            patch("aden_tools.tools.linear_tool.linear_tool.httpx.post") as mock_post,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"teams": {"nodes": []}}}
            mock_post.return_value = mock_response

            result = teams_fn()

        assert result["total"] == 0
        # Verify the key was used in headers
        call_headers = mock_post.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "lin_api_env_key"


# --- Individual tool function tests ---


class TestIssueTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_issue_create(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "issueCreate": {
                            "success": True,
                            "issue": {"id": "1", "identifier": "ENG-1"},
                        }
                    }
                }
            ),
        )
        result = self._fn("linear_issue_create")(title="Test Issue", team_id="team-123")
        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_issue_get(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": {"issue": {"id": "1", "identifier": "ENG-1"}}}),
        )
        result = self._fn("linear_issue_get")(issue_id="ENG-1")
        assert result["identifier"] == "ENG-1"

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_issue_update(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"issueUpdate": {"success": True, "issue": {"id": "1"}}}}
            ),
        )
        result = self._fn("linear_issue_update")(issue_id="1", title="New Title")
        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_issue_delete(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": {"issueDelete": {"success": True}}}),
        )
        result = self._fn("linear_issue_delete")(issue_id="1")
        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_issue_search(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "issues": {
                            "nodes": [{"id": "1"}],
                            "pageInfo": {"hasNextPage": False},
                        }
                    }
                }
            ),
        )
        result = self._fn("linear_issue_search")(query="test")
        assert result["total"] == 1

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_issue_add_comment(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"commentCreate": {"success": True, "comment": {"id": "c1"}}}}
            ),
        )
        result = self._fn("linear_issue_add_comment")(issue_id="1", body="Test comment")
        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_issue_create_timeout(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        result = self._fn("linear_issue_create")(title="Test Issue", team_id="team-123")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_issue_get_network_error(self, mock_post):
        mock_post.side_effect = httpx.RequestError("connection failed")
        result = self._fn("linear_issue_get")(issue_id="1")
        assert "error" in result
        assert "Network error" in result["error"]


class TestProjectTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_project_create(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "projectCreate": {
                            "success": True,
                            "project": {"id": "p1", "name": "Test"},
                        }
                    }
                }
            ),
        )
        result = self._fn("linear_project_create")(name="Test Project", team_ids=["team-1"])
        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_project_get(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": {"project": {"id": "p1", "name": "Test"}}}),
        )
        result = self._fn("linear_project_get")(project_id="p1")
        assert result["name"] == "Test"

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_project_update(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"projectUpdate": {"success": True, "project": {"id": "p1"}}}}
            ),
        )
        result = self._fn("linear_project_update")(project_id="p1", name="New Name")
        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_project_list(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "projects": {
                            "nodes": [{"id": "p1"}],
                            "pageInfo": {"hasNextPage": False},
                        }
                    }
                }
            ),
        )
        result = self._fn("linear_project_list")()
        assert result["total"] == 1


class TestTeamTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_teams_list(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"teams": {"nodes": [{"id": "t1", "name": "Eng"}]}}}
            ),
        )
        result = self._fn("linear_teams_list")()
        assert result["total"] == 1

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_team_get(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"team": {"id": "t1", "name": "Eng", "key": "ENG"}}}
            ),
        )
        result = self._fn("linear_team_get")(team_id="t1")
        assert result["key"] == "ENG"

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_workflow_states_get(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"workflowStates": {"nodes": [{"id": "s1", "name": "Todo"}]}}}
            ),
        )
        result = self._fn("linear_workflow_states_get")(team_id="t1")
        assert result["total"] == 1


class TestUserTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_users_list(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"users": {"nodes": [{"id": "u1", "name": "Alice"}]}}}
            ),
        )
        result = self._fn("linear_users_list")()
        assert result["total"] == 1

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_user_get(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": {"user": {"id": "u1", "name": "Alice"}}}),
        )
        result = self._fn("linear_user_get")(user_id="u1")
        assert result["name"] == "Alice"

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_viewer(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"data": {"viewer": {"id": "me", "name": "Current User"}}}),
        )
        result = self._fn("linear_viewer")()
        assert result["name"] == "Current User"


class TestLabelTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "tok"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_label_create(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "data": {
                        "issueLabelCreate": {
                            "success": True,
                            "issueLabel": {"id": "l1", "name": "bug"},
                        }
                    }
                }
            ),
        )
        result = self._fn("linear_label_create")(name="bug", team_id="t1")
        assert result["success"] is True

    @patch("aden_tools.tools.linear_tool.linear_tool.httpx.post")
    def test_linear_labels_list(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={"data": {"issueLabels": {"nodes": [{"id": "l1", "name": "bug"}]}}}
            ),
        )
        result = self._fn("linear_labels_list")()
        assert result["total"] == 1
