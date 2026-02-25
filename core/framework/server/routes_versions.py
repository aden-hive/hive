"""Agent version management routes.

Agent-bound endpoints for git-based versioning. These are NOT session-bound —
the version history lives with the agent in exports/{agent_name}/.

Endpoints:
- GET    /api/agents/{agent_name}/versions              — list all versions
- POST   /api/agents/{agent_name}/versions              — create new version
- GET    /api/agents/{agent_name}/versions/{version}    — version detail
- DELETE /api/agents/{agent_name}/versions/{version}    — delete version tag
- GET    /api/agents/{agent_name}/history               — commit log
- GET    /api/agents/{agent_name}/files                 — list files at ref
- GET    /api/agents/{agent_name}/files/{path:.+}       — file content at ref
- GET    /api/agents/{agent_name}/diff                  — diff between refs
"""

import logging
from pathlib import Path

from aiohttp import web

from framework.server.app import safe_path_segment
from framework.utils.git import (
    commit_all,
    create_tag,
    delete_tag,
    diff_between,
    has_changes,
    is_git_repo,
    latest_version,
    list_files_at_ref,
    list_tags,
    log,
    next_version,
    parse_semver,
    show_file,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_agent_dir(request: web.Request) -> tuple[Path, str]:
    """Resolve {agent_name} to an exports/ directory.

    Returns (agent_dir, agent_name).
    Raises HTTPNotFound if the directory doesn't exist.
    Raises HTTPBadRequest if the name is unsafe.
    """
    agent_name = safe_path_segment(request.match_info["agent_name"])
    agent_dir = Path("exports") / agent_name
    if not agent_dir.is_dir():
        raise web.HTTPNotFound(
            text=f'{{"error": "Agent \\"{agent_name}\\" not found in exports/"}}',
            content_type="application/json",
        )
    return agent_dir, agent_name


def _require_git(agent_dir: Path, agent_name: str) -> None:
    """Raise HTTPConflict if the agent dir is not a git repo."""
    if not is_git_repo(agent_dir):
        raise web.HTTPConflict(
            text=f'{{"error": "Agent \\"{agent_name}\\" has no git repository. Export the agent first."}}',
            content_type="application/json",
        )


# ---------------------------------------------------------------------------
# Version listing and creation
# ---------------------------------------------------------------------------


async def handle_list_versions(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_name}/versions — list all semver versions."""
    agent_dir, agent_name = _resolve_agent_dir(request)

    if not is_git_repo(agent_dir):
        return web.json_response({
            "agent_name": agent_name,
            "has_git": False,
            "versions": [],
            "latest": None,
        })

    tags = list_tags(agent_dir)
    return web.json_response({
        "agent_name": agent_name,
        "has_git": True,
        "versions": tags,
        "latest": tags[0]["tag"] if tags else None,
    })


async def handle_create_version(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_name}/versions — create a new version tag.

    Body: {"version": "v1.0.0", "message": "..."} or {"bump": "patch", "message": "..."}
    """
    agent_dir, agent_name = _resolve_agent_dir(request)
    _require_git(agent_dir, agent_name)

    body = await request.json()
    version = body.get("version")
    bump = body.get("bump")
    message = body.get("message", "")

    if not version and not bump:
        return web.json_response(
            {"error": "Provide 'version' (e.g. 'v1.0.0') or 'bump' ('patch'|'minor'|'major')"},
            status=400,
        )

    if bump:
        if bump not in ("patch", "minor", "major"):
            return web.json_response(
                {"error": f"Invalid bump type '{bump}'. Use 'patch', 'minor', or 'major'"},
                status=400,
            )
        version = next_version(agent_dir, bump)

    # Auto-commit uncommitted changes before tagging
    if has_changes(agent_dir):
        commit_all(agent_dir, "pre-release commit")

    try:
        create_tag(agent_dir, version, message)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=500)

    # Find the tag info we just created
    tags = list_tags(agent_dir)
    tag_info = next((t for t in tags if t["tag"] == version), {"tag": version})

    return web.json_response(tag_info, status=201)


async def handle_get_version(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_name}/versions/{version} — version detail."""
    agent_dir, agent_name = _resolve_agent_dir(request)
    _require_git(agent_dir, agent_name)

    version = request.match_info["version"]

    # Find the tag
    tags = list_tags(agent_dir)
    tag_info = next((t for t in tags if t["tag"] == version), None)
    if tag_info is None:
        return web.json_response(
            {"error": f"Version '{version}' not found"},
            status=404,
        )

    # Get files at this version
    files = list_files_at_ref(agent_dir, version)

    # Get diff from previous version
    tag_idx = next((i for i, t in enumerate(tags) if t["tag"] == version), -1)
    prev_diff = ""
    if tag_idx >= 0 and tag_idx + 1 < len(tags):
        prev_tag = tags[tag_idx + 1]["tag"]
        prev_diff = diff_between(agent_dir, prev_tag, version)

    return web.json_response({
        **tag_info,
        "files": files,
        "diff_from_previous": prev_diff,
    })


async def handle_delete_version(request: web.Request) -> web.Response:
    """DELETE /api/agents/{agent_name}/versions/{version} — delete a version tag."""
    agent_dir, agent_name = _resolve_agent_dir(request)
    _require_git(agent_dir, agent_name)

    version = request.match_info["version"]

    try:
        delete_tag(agent_dir, version)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=404)

    return web.json_response({"deleted": version})


# ---------------------------------------------------------------------------
# Commit history
# ---------------------------------------------------------------------------


async def handle_history(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_name}/history — commit log.

    Query params: ?limit=50&since=v1.0.0
    """
    agent_dir, agent_name = _resolve_agent_dir(request)
    _require_git(agent_dir, agent_name)

    limit = int(request.query.get("limit", "50"))
    since = request.query.get("since", "")

    commits = log(agent_dir, limit=limit, since_tag=since)
    return web.json_response({
        "agent_name": agent_name,
        "commits": commits,
        "total": len(commits),
    })


# ---------------------------------------------------------------------------
# File inspection at specific refs
# ---------------------------------------------------------------------------


async def handle_list_files(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_name}/files — list files at a ref.

    Query params: ?ref=v1.0.0 (default: HEAD)
    """
    agent_dir, agent_name = _resolve_agent_dir(request)
    _require_git(agent_dir, agent_name)

    ref = request.query.get("ref", "HEAD")
    files = list_files_at_ref(agent_dir, ref)

    if not files and ref != "HEAD":
        return web.json_response(
            {"error": f"Ref '{ref}' not found or has no files"},
            status=404,
        )

    return web.json_response({
        "agent_name": agent_name,
        "ref": ref,
        "files": files,
    })


async def handle_get_file(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_name}/files/{path:.+} — file content at a ref.

    Query params: ?ref=v1.0.0 (default: HEAD)
    """
    agent_dir, agent_name = _resolve_agent_dir(request)
    _require_git(agent_dir, agent_name)

    file_path = request.match_info["path"]
    ref = request.query.get("ref", "HEAD")

    content = show_file(agent_dir, ref, file_path)
    if content is None:
        return web.json_response(
            {"error": f"File '{file_path}' not found at ref '{ref}'"},
            status=404,
        )

    return web.json_response({
        "agent_name": agent_name,
        "ref": ref,
        "path": file_path,
        "content": content,
    })


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


async def handle_diff(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_name}/diff — diff between two refs.

    Query params: ?from=v1.0.0&to=v1.1.0
    """
    agent_dir, agent_name = _resolve_agent_dir(request)
    _require_git(agent_dir, agent_name)

    ref_from = request.query.get("from")
    ref_to = request.query.get("to", "HEAD")

    if not ref_from:
        return web.json_response(
            {"error": "'from' query parameter is required"},
            status=400,
        )

    diff = diff_between(agent_dir, ref_from, ref_to)
    return web.json_response({
        "agent_name": agent_name,
        "from": ref_from,
        "to": ref_to,
        "diff": diff,
    })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_routes(app: web.Application) -> None:
    """Register version management routes."""
    # Versions (tags)
    app.router.add_get(
        "/api/agents/{agent_name}/versions", handle_list_versions
    )
    app.router.add_post(
        "/api/agents/{agent_name}/versions", handle_create_version
    )
    app.router.add_get(
        "/api/agents/{agent_name}/versions/{version}", handle_get_version
    )
    app.router.add_delete(
        "/api/agents/{agent_name}/versions/{version}", handle_delete_version
    )

    # History
    app.router.add_get(
        "/api/agents/{agent_name}/history", handle_history
    )

    # Files at ref
    app.router.add_get(
        "/api/agents/{agent_name}/files", handle_list_files
    )
    app.router.add_get(
        "/api/agents/{agent_name}/files/{path:.+}", handle_get_file
    )

    # Diff
    app.router.add_get(
        "/api/agents/{agent_name}/diff", handle_diff
    )
