"""
xAPI Learning Record Agent — pure-function tools.

Follows the ToolRegistry.discover_from_module() contract:
  - TOOLS: dict[str, Tool]  — tool definitions
  - tool_executor(tool_use)  — unified dispatcher

All three functions are deterministic and require no LLM:
  - build_xapi_statement(event)  → xAPI 1.0.3 statement dict
  - validate_statement(statement) → {"valid": bool, "errors": list}
  - post_to_lrs(statement, endpoint, username, password) → {"statement_id", "success", "error"}
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from framework.llm.provider import Tool, ToolResult, ToolUse

# ---------------------------------------------------------------------------
# Tool definitions (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------

TOOLS = {
    "build_xapi_statement": Tool(
        name="build_xapi_statement",
        description=(
            "Build a valid xAPI 1.0.3 JSON statement from a normalized learning event. "
            "Accepts actor (name, mbox), verb (id URI, display), object (id URI, name), "
            "and optional result (score raw/min/max/scaled, completion, success, response). "
            "Returns a complete xAPI statement dict with generated id and timestamp."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event": {
                    "type": "object",
                    "description": (
                        "Normalized learning event. Required: actor.name, actor.mbox, "
                        "verb.id, verb.display, object.id, object.name. "
                        "Optional: result.score.raw, result.score.min, result.score.max, "
                        "result.score.scaled, result.completion, result.success, result.response, "
                        "platform, language."
                    ),
                },
            },
            "required": ["event"],
        },
    ),
    "validate_statement": Tool(
        name="validate_statement",
        description=(
            "Validate an xAPI 1.0.3 statement dict for required fields, URI format, "
            "mbox format (mailto:), and score range (0.0–1.0 for scaled). "
            "Returns {valid: bool, errors: list[str]}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "statement": {
                    "type": "object",
                    "description": "xAPI statement dict to validate.",
                },
            },
            "required": ["statement"],
        },
    ),
    "post_to_lrs": Tool(
        name="post_to_lrs",
        description=(
            "POST an xAPI statement to an LRS endpoint using HTTP Basic auth. "
            "Handles 200/204 as success, retries once on 5xx errors. "
            "Returns {statement_id: str, success: bool, error: str|None}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "statement": {
                    "type": "object",
                    "description": "Valid xAPI statement dict to dispatch.",
                },
                "endpoint": {
                    "type": "string",
                    "description": "LRS statements endpoint URL.",
                },
                "username": {
                    "type": "string",
                    "description": "LRS Basic auth username.",
                },
                "password": {
                    "type": "string",
                    "description": "LRS Basic auth password.",
                },
            },
            "required": ["statement", "endpoint", "username", "password"],
        },
    ),
}


# ---------------------------------------------------------------------------
# Core implementations
# ---------------------------------------------------------------------------

_IRI_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://\S+$")
_MBOX_PATTERN = re.compile(r"^mailto:[^@\s]+@[^@\s]+\.[^@\s]+$")


def build_xapi_statement(event: dict) -> dict:
    """Build a valid xAPI 1.0.3 statement from a normalized event dict.

    Args:
        event: Normalized learning event with actor, verb, object, and
               optional result/platform/language fields.

    Returns:
        Complete xAPI 1.0.3 statement dict with generated id and timestamp.
    """
    from .config import PLATFORM

    language = event.get("language", "en-US")
    platform = event.get("platform", PLATFORM)

    # Actor
    actor: dict[str, Any] = {
        "objectType": "Agent",
        "name": event["actor"]["name"],
        "mbox": event["actor"]["mbox"],
    }

    # Verb
    verb: dict[str, Any] = {
        "id": event["verb"]["id"],
        "display": {language: event["verb"]["display"]},
    }

    # Object (Activity)
    activity: dict[str, Any] = {
        "objectType": "Activity",
        "id": event["object"]["id"],
        "definition": {
            "name": {language: event["object"]["name"]},
        },
    }
    if event["object"].get("description"):
        activity["definition"]["description"] = {
            language: event["object"]["description"]
        }
    if event["object"].get("type"):
        activity["definition"]["type"] = event["object"]["type"]

    # Statement skeleton
    statement: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "actor": actor,
        "verb": verb,
        "object": activity,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        + "Z",
        "version": "1.0.3",
        "context": {
            "platform": platform,
        },
    }

    # Optional result block
    result_data = event.get("result", {})
    if result_data:
        result: dict[str, Any] = {}

        score_data = result_data.get("score", {})
        if score_data:
            score: dict[str, Any] = {}
            if "scaled" in score_data:
                score["scaled"] = float(score_data["scaled"])
            if "raw" in score_data:
                score["raw"] = float(score_data["raw"])
            if "min" in score_data:
                score["min"] = float(score_data["min"])
            if "max" in score_data:
                score["max"] = float(score_data["max"])
            result["score"] = score

        if "completion" in result_data:
            result["completion"] = bool(result_data["completion"])
        if "success" in result_data:
            result["success"] = bool(result_data["success"])
        if "response" in result_data:
            result["response"] = str(result_data["response"])
        if "duration" in result_data:
            result["duration"] = str(result_data["duration"])

        if result:
            statement["result"] = result

    return statement


def validate_statement(statement: dict) -> dict:
    """Validate an xAPI 1.0.3 statement for required fields and format rules.

    Checks:
    - statement.id is a valid UUID string
    - actor.mbox matches mailto: format
    - verb.id is a valid IRI
    - object.id is a valid IRI
    - version is present
    - result.score.scaled is in range [0.0, 1.0] if present

    Args:
        statement: xAPI statement dict to validate.

    Returns:
        {"valid": bool, "errors": list[str]}
    """
    errors: list[str] = []

    # Required top-level fields
    for field in ("id", "actor", "verb", "object", "timestamp", "version"):
        if field not in statement:
            errors.append(f"Missing required field: '{field}'")

    # statement.id must be a UUID
    if "id" in statement:
        try:
            uuid.UUID(str(statement["id"]))
        except ValueError:
            errors.append(
                f"statement.id '{statement['id']}' is not a valid UUID"
            )

    # actor checks
    actor = statement.get("actor", {})
    if "mbox" in actor:
        if not _MBOX_PATTERN.match(actor["mbox"]):
            errors.append(
                f"actor.mbox '{actor['mbox']}' must be in mailto:user@domain format"
            )
    elif "mbox_sha1sum" not in actor and "openid" not in actor and "account" not in actor:
        errors.append(
            "actor must have at least one IFI: mbox, mbox_sha1sum, openid, or account"
        )

    # verb.id must be a valid IRI
    verb = statement.get("verb", {})
    if "id" in verb:
        if not _IRI_PATTERN.match(verb["id"]):
            errors.append(
                f"verb.id '{verb['id']}' is not a valid IRI"
            )
    else:
        errors.append("Missing required field: 'verb.id'")

    # object.id must be a valid IRI
    obj = statement.get("object", {})
    if "id" in obj:
        if not _IRI_PATTERN.match(obj["id"]):
            errors.append(
                f"object.id '{obj['id']}' is not a valid IRI"
            )
    else:
        errors.append("Missing required field: 'object.id'")

    # result.score.scaled must be in [0.0, 1.0]
    result = statement.get("result", {})
    score = result.get("score", {})
    if "scaled" in score:
        try:
            scaled = float(score["scaled"])
            if not (0.0 <= scaled <= 1.0):
                errors.append(
                    f"result.score.scaled '{scaled}' must be in range [0.0, 1.0]"
                )
        except (TypeError, ValueError):
            errors.append(
                f"result.score.scaled '{score['scaled']}' must be a number"
            )

    # timestamp must be a valid ISO 8601 datetime
    ts = statement.get("timestamp")
    if ts is not None:
        try:
            datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            errors.append(
                f"timestamp '{ts}' is not a valid ISO 8601 datetime"
            )

    # version must be exactly "1.0.3" per the xAPI specification
    version = statement.get("version")
    if version is not None and version != "1.0.3":
        errors.append(
            f"version '{version}' must be '1.0.3'"
        )

    return {"valid": len(errors) == 0, "errors": errors}


def post_to_lrs(
    statement: dict,
    endpoint: str,
    username: str,
    password: str,
) -> dict:
    """POST an xAPI statement to an LRS using HTTP Basic auth.

    Handles 200/204 as success. Retries once on 5xx errors.
    Uses the statement's existing 'id' field as the statement_id.

    Args:
        statement: Valid xAPI statement dict.
        endpoint:  LRS statements endpoint URL.
        username:  Basic auth username.
        password:  Basic auth password.

    Returns:
        {"statement_id": str, "success": bool, "error": str | None}
    """
    import base64
    import urllib.error
    import urllib.request

    if "id" not in statement:
        return {
            "statement_id": None,
            "success": False,
            "error": (
                "statement is missing required 'id' field; "
                "call build_xapi_statement/validate_statement first"
            ),
        }
    statement_id = statement["id"]

    headers = {
        "Content-Type": "application/json",
        "X-Experience-API-Version": "1.0.3",
        "Authorization": "Basic "
        + base64.b64encode(f"{username}:{password}".encode()).decode(),
    }

    body = json.dumps(statement, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, headers=headers, method="POST"
    )

    def _attempt() -> dict:
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                status = resp.getcode()
                if status in (200, 204):
                    return {
                        "statement_id": statement_id,
                        "success": True,
                        "error": None,
                    }
                return {
                    "statement_id": statement_id,
                    "success": False,
                    "error": f"Unexpected HTTP status: {status}",
                }
        except urllib.error.HTTPError as exc:
            return {
                "statement_id": statement_id,
                "success": False,
                "error": f"HTTP {exc.code}: {exc.reason}",
                "_retryable": exc.code >= 500,
            }
        except Exception as exc:
            return {
                "statement_id": statement_id,
                "success": False,
                "error": str(exc),
                "_retryable": False,
            }

    result = _attempt()

    # Retry once on 5xx
    if not result["success"] and result.pop("_retryable", False):
        time.sleep(1)
        result = _attempt()
        result.pop("_retryable", None)
    else:
        result.pop("_retryable", None)

    return result


# ---------------------------------------------------------------------------
# Unified tool executor (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch tool calls to their implementations."""
    try:
        if tool_use.name == "build_xapi_statement":
            event = tool_use.input.get("event", {})
            result = build_xapi_statement(event=event)
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error=False,
            )

        if tool_use.name == "validate_statement":
            statement = tool_use.input.get("statement", {})
            result = validate_statement(statement=statement)
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error=not result["valid"],
            )

        if tool_use.name == "post_to_lrs":
            statement = tool_use.input.get("statement", {})
            endpoint = tool_use.input.get("endpoint", "")
            username = tool_use.input.get("username", "")
            password = tool_use.input.get("password", "")
            result = post_to_lrs(
                statement=statement,
                endpoint=endpoint,
                username=username,
                password=password,
            )
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error=not result["success"],
            )

    except Exception as exc:
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps({"error": str(exc)}),
            is_error=True,
        )

    return ToolResult(
        tool_use_id=tool_use.id,
        content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
        is_error=True,
    )
