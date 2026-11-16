"""The ``hive`` MCP server a Claude Code queen's runs get: ``list_queens`` and ``message_queen``.

Claude Code starts it (``--mcp-config``, written by :mod:`framework.server.claude_code_queens`) with
``HIVE_QUEEN_MAIL_URL``, ``HIVE_QUEEN_MAIL_TOKEN`` and ``HIVE_QUEEN_MAIL_FROM`` (the conversation she
writes from) in its environment, and it calls ``hive serve``'s ``/api/queen-mail/...`` routes. It
imports only the standard library and ``mcp``, so it starts quickly.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

server = FastMCP("hive")


# Handing a letter to a queen who has to start first can take a while; a timeout here would report a
# letter as failed that then arrives, and invite a duplicate.
_TIMEOUT_S = 180


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"X-Queen-Mail-Token": os.environ.get("HIVE_QUEEN_MAIL_TOKEN", ""), "Content-Type": "application/json"}
    request = urllib.request.Request(
        os.environ.get("HIVE_QUEEN_MAIL_URL", "").rstrip("/") + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except ValueError:
            return {"error": f"Hive answered {e.code}"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"error": f"Can't reach Hive: {e}"}


@server.tool()
def list_queens() -> str:
    """The other queens you can write to with message_queen: each one's id, name and title."""
    query = urllib.parse.urlencode({"from": os.environ.get("HIVE_QUEEN_MAIL_FROM", "")})
    return json.dumps(_call("GET", f"/api/queen-mail/queens?{query}"), ensure_ascii=False)


@server.tool()
def message_queen(queen_id: str, message: str) -> str:
    """Write to another queen. It returns at once; her answer arrives later as a new message in this
    conversation, "[Name(queen_id)]: ...". She can't see your conversation, so say what she needs to know.
    Returns {sent, to, depth}, or {error} (no such queen, today's limit reached, or the chain of letters
    that led here is too long)."""
    body = {"from": os.environ.get("HIVE_QUEEN_MAIL_FROM", ""), "to": queen_id, "message": message}
    return json.dumps(_call("POST", "/api/queen-mail/letters", body), ensure_ascii=False)


if __name__ == "__main__":
    server.run()
