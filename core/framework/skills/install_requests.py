"""A queen's requests to install a skill in the shared library, kept until the user decides.

A skill in ``HIVE_HOME/skills`` reaches every queen and colony, so a queen can't put one there on
her own: ``write_skill(scope="global")`` files a request here, in her session's folder, and the
session's chat page asks the user. Approving installs the copy stored here, not whatever the
queen says later. Requests survive a page reload and a restart.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Literal

from framework.skills.overrides import utc_now
from framework.skills.skill_writer import SkillDraft, build_draft

FILE_NAME = "skill_installs.json"

Decision = Literal["approved", "denied"]


class RequestNotFound(LookupError):
    """No request with that id in the session."""


class RequestDecided(RuntimeError):
    """The request was already approved or denied."""


def add_request(session_dir: Path, draft: SkillDraft) -> dict[str, Any]:
    """File a pending request to install ``draft``; it replaces a pending one for the same name."""
    requests = [r for r in _load(session_dir) if not (r["status"] == "pending" and r["name"] == draft.name)]
    request = {
        "id": uuid.uuid4().hex,
        "name": draft.name,
        "description": draft.description,
        "body": draft.body,
        "files": [{"path": f.rel_path.as_posix(), "content": f.content} for f in draft.files],
        "requested_at": utc_now().isoformat(),
        "status": "pending",
    }
    requests.append(request)
    _save(session_dir, requests)
    return request


def pending_requests(session_dir: Path) -> list[dict[str, Any]]:
    """The requests the user hasn't decided yet, oldest first."""
    return [r for r in _load(session_dir) if r["status"] == "pending"]


def pending_request(session_dir: Path, request_id: str) -> dict[str, Any]:
    """The pending request ``request_id``.

    Raises:
        RequestNotFound: no such request.
        RequestDecided: it was already approved or denied.
    """
    for request in _load(session_dir):
        if request["id"] == request_id:
            if request["status"] != "pending":
                raise RequestDecided(f"skill install request {request_id} was already {request['status']}")
            return request
    raise RequestNotFound(f"no skill install request {request_id}")


def mark_decided(session_dir: Path, request_id: str, decision: Decision) -> None:
    """Record the user's decision on a pending request."""
    requests = _load(session_dir)
    for request in requests:
        if request["id"] == request_id:
            request["status"] = decision
            request["decided_at"] = utc_now().isoformat()
    _save(session_dir, requests)


def draft_of(request: dict[str, Any]) -> SkillDraft:
    """The skill a request installs. It was validated when it was filed."""
    draft, err = build_draft(
        skill_name=request["name"],
        skill_description=request["description"],
        skill_body=request["body"],
        skill_files=request["files"],
    )
    if draft is None:
        raise ValueError(f"skill install request {request['id']} is no longer a valid skill: {err}")
    return draft


def _load(session_dir: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads((session_dir / FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in data if isinstance(r, dict) and isinstance(r.get("id"), str)] if isinstance(data, list) else []


def _save(session_dir: Path, requests: list[dict[str, Any]]) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    tmp = session_dir / f"{FILE_NAME}.tmp"
    tmp.write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(session_dir / FILE_NAME)
