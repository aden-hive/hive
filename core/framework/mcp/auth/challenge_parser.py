"""HTTP auth challenge parsing for MCP 401 responses."""

from __future__ import annotations

import json
import re
from typing import Any

from framework.mcp.auth.models import MCPAuthChallenge


class MCPAuthChallengeParser:
    """Parses WWW-Authenticate/body hints into MCPAuthChallenge."""

    AUTH_URL_KEYS = (
        "auth_url",
        "authorization_url",
        "authorize_url",
        "authorization_uri",
        "oauth_url",
    )

    def parse(self, response: Any) -> MCPAuthChallenge:
        challenge = MCPAuthChallenge()
        www_authenticate = response.headers.get("WWW-Authenticate")
        challenge.raw_www_authenticate = www_authenticate

        if www_authenticate:
            challenge.auth_url = self._extract_auth_url_from_header(www_authenticate)
            challenge.resource_metadata = self._extract_param(
                www_authenticate, "resource_metadata"
            )
            scope = self._extract_param(www_authenticate, "scope")
            if scope:
                challenge.required_scopes = [item for item in scope.split(" ") if item]

        body = self._safe_json(response)
        if isinstance(body, dict):
            challenge.auth_url = challenge.auth_url or self._extract_auth_url_from_body(body)

            if not challenge.required_headers:
                required_headers = body.get("required_headers")
                if isinstance(required_headers, list):
                    challenge.required_headers = [str(item) for item in required_headers]
            if not challenge.resource_metadata:
                rm = body.get("resource_metadata")
                if isinstance(rm, str):
                    challenge.resource_metadata = rm
            if not challenge.required_scopes:
                scopes = body.get("scopes") or body.get("required_scopes")
                if isinstance(scopes, list):
                    challenge.required_scopes = [str(item) for item in scopes]
                elif isinstance(scopes, str):
                    challenge.required_scopes = [item for item in scopes.split(" ") if item]

        if not challenge.auth_url:
            location = response.headers.get("Location")
            if location:
                challenge.auth_url = location

        return challenge

    def _extract_auth_url_from_header(self, header_value: str) -> str | None:
        for key in self.AUTH_URL_KEYS:
            value = self._extract_param(header_value, key)
            if value:
                return value
        return None

    def _extract_auth_url_from_body(self, payload: dict[str, Any]) -> str | None:
        for key in self.AUTH_URL_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        error = payload.get("error")
        if isinstance(error, dict):
            for key in self.AUTH_URL_KEYS:
                value = error.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _extract_param(header: str, key: str) -> str | None:
        pattern = rf'{re.escape(key)}="?([^",]+)"?'
        match = re.search(pattern, header, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _safe_json(response: Any) -> Any:
        try:
            return response.json()
        except Exception:
            pass
        text = getattr(response, "text", None)
        if isinstance(text, str) and text:
            try:
                return json.loads(text)
            except Exception:
                return None
        return None
