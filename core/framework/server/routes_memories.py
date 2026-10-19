"""User memory files — list/read/update/delete operations on memory markdown.

Memory files live under ``HIVE_HOME/memories/`` with subdirectories per
scope (``global/``, ``agents/queens/<queen>/``, ``colonies/<colony>/``,
``agents/<worker>/``). Each ``.md`` file has YAML frontmatter (``name``,
``type``, ``description``) and a markdown body. These endpoints surface
those files to the frontend's Memory configuration section so the user
can review and edit the long-term memory the queens have accumulated.

- GET    /api/memories            — list every memory file, grouped by scope
- GET    /api/memories/file       — read one memory file (?path=relative/path.md)
- PUT    /api/memories/file       — overwrite one memory file's contents
- DELETE /api/memories/file       — delete one memory file
"""

import logging
from pathlib import Path

from aiohttp import web

from framework.agents.queen.queen_memory_v2 import (
    MAX_FILE_SIZE_BYTES,
    MemoryFile,
    build_memory_document,
)
from framework.cloud_sync_hooks import schedule_push
from framework.config import MEMORIES_DIR

logger = logging.getLogger(__name__)


def _maybe_sync_memory(rel: str) -> None:
    """Push a memory file to the cloud — only global + per-queen scope (v1)."""
    if rel.startswith("global/") or rel.startswith("agents/queens/"):
        schedule_push("memory", rel)


def _resolve_safe_path(rel: str) -> Path | None:
    """Resolve *rel* under ``MEMORIES_DIR``, refusing traversal/non-md paths.

    Returns ``None`` for any path that escapes ``MEMORIES_DIR`` or that
    doesn't end in ``.md``. This is the single bottleneck for path
    validation — every handler routes through it before touching disk.
    """
    if not rel or rel.startswith(("/", "\\")):
        return None
    parts = rel.replace("\\", "/").split("/")
    if any(p in ("", "..", ".") for p in parts):
        return None
    base = MEMORIES_DIR.resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    if target.suffix.lower() != ".md":
        return None
    return target


def _scope_for_rel(parts: list[str]) -> dict:
    """Derive a UI-friendly ``{scope, scope_name}`` label for a relative path.

    Maps on-disk layout to the labels the frontend's Memory section
    groups by — keeps the directory taxonomy out of the renderer.
    """
    parent = parts[:-1]  # strip filename
    if not parent:
        return {"scope": "root", "scope_name": ""}
    if parent[0] == "global":
        return {"scope": "global", "scope_name": ""}
    if parent[:2] == ["agents", "queens"] and len(parent) >= 3:
        return {"scope": "queen", "scope_name": parent[2]}
    if parent[0] == "colonies" and len(parent) >= 2:
        return {"scope": "colony", "scope_name": parent[1]}
    if parent[0] == "agents" and len(parent) >= 2:
        return {"scope": "agent", "scope_name": parent[1]}
    return {"scope": "/".join(parent), "scope_name": ""}


def _memory_to_dict(mf: MemoryFile, rel_path: str) -> dict:
    entry = {
        "path": rel_path,
        "filename": mf.filename,
        "name": mf.name,
        "type": mf.type,
        "description": mf.description,
        "mtime": mf.mtime,
    }
    entry.update(_scope_for_rel(list(Path(rel_path).parts)))
    return entry


async def handle_list_memories(request: web.Request) -> web.Response:
    """GET /api/memories — list every memory file under MEMORIES_DIR."""
    if not MEMORIES_DIR.is_dir():
        return web.json_response({"memories": []})

    base = MEMORIES_DIR.resolve()
    entries: list[dict] = []
    for md_path in base.rglob("*.md"):
        if not md_path.is_file() or md_path.name.startswith("."):
            continue
        rel = md_path.relative_to(base).as_posix()
        try:
            mf = MemoryFile.from_path(md_path)
        except Exception:
            logger.warning("Failed to parse memory file %s", md_path, exc_info=True)
            continue
        entries.append(_memory_to_dict(mf, rel))

    # Group by scope, newest first within a scope.
    entries.sort(key=lambda e: (e.get("scope") or "", e.get("scope_name") or "", -(e.get("mtime") or 0.0)))
    return web.json_response({"memories": entries})


async def handle_get_memory(request: web.Request) -> web.Response:
    """GET /api/memories/file?path=… — read one memory file's content."""
    rel = request.rel_url.query.get("path", "")
    target = _resolve_safe_path(rel)
    if target is None:
        return web.json_response({"error": "Invalid path"}, status=400)
    if not target.is_file():
        return web.json_response({"error": "Memory not found"}, status=404)

    try:
        content = target.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to read memory %s: %s", rel, exc)
        return web.json_response({"error": "Could not read memory"}, status=500)

    mf = MemoryFile.from_path(target)
    payload = _memory_to_dict(mf, rel)
    payload["content"] = content
    return web.json_response(payload)


async def handle_create_memory(request: web.Request) -> web.Response:
    """POST /api/memories/file?path=… — create a memory file if absent.

    Idempotent seed endpoint (used by the desktop on init to materialize a
    memory from onboarding data, e.g. the company website for ICP context).
    Body: ``{name, body, description?, type?}`` — assembled into the standard
    frontmatter document via :func:`build_memory_document`. If the target
    already exists it is left untouched and ``created: false`` is returned, so
    repeated startups never clobber the user's edits or the reflection agent's
    updates. Use PUT to overwrite an existing file.
    """
    rel = request.rel_url.query.get("path", "")
    target = _resolve_safe_path(rel)
    if target is None:
        return web.json_response({"error": "Invalid path"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    name = body.get("name")
    mem_body = body.get("body")
    if not isinstance(name, str) or not name.strip():
        return web.json_response({"error": "name must be a non-empty string"}, status=400)
    if not isinstance(mem_body, str) or not mem_body.strip():
        return web.json_response({"error": "body must be a non-empty string"}, status=400)
    description = body.get("description")
    mem_type = body.get("type")

    # Idempotent: never overwrite an existing memory here.
    if target.exists():
        return web.json_response({"created": False, "path": rel})

    content = build_memory_document(
        name=name,
        description=description if isinstance(description, str) else "",
        mem_type=mem_type if isinstance(mem_type, str) and mem_type.strip() else "profile",
        body=mem_body,
    )
    if len(content.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
        return web.json_response(
            {"error": f"Memory exceeds the {MAX_FILE_SIZE_BYTES}-byte limit"},
            status=400,
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to create memory %s: %s", rel, exc)
        return web.json_response({"error": "Could not create memory"}, status=500)

    logger.info("Memory created: %s", rel)
    _maybe_sync_memory(rel)
    mf = MemoryFile.from_path(target)
    payload = _memory_to_dict(mf, rel)
    payload["content"] = content
    payload["created"] = True
    return web.json_response(payload)


async def handle_update_memory(request: web.Request) -> web.Response:
    """PUT /api/memories/file?path=… — overwrite a memory file's content."""
    rel = request.rel_url.query.get("path", "")
    target = _resolve_safe_path(rel)
    if target is None:
        return web.json_response({"error": "Invalid path"}, status=400)
    if not target.is_file():
        return web.json_response({"error": "Memory not found"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        return web.json_response({"error": "Content must be a non-empty string"}, status=400)
    if len(content.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
        return web.json_response(
            {"error": f"Memory exceeds the {MAX_FILE_SIZE_BYTES}-byte limit"},
            status=400,
        )

    # Normalise trailing newline — matches how the queen agent writes
    # these files, so manual edits don't churn the diff on next save.
    if not content.endswith("\n"):
        content += "\n"
    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write memory %s: %s", rel, exc)
        return web.json_response({"error": "Could not write memory"}, status=500)

    logger.info("Memory updated: %s", rel)
    _maybe_sync_memory(rel)
    mf = MemoryFile.from_path(target)
    payload = _memory_to_dict(mf, rel)
    payload["content"] = content
    return web.json_response(payload)


async def handle_delete_memory(request: web.Request) -> web.Response:
    """DELETE /api/memories/file?path=… — delete a memory file."""
    rel = request.rel_url.query.get("path", "")
    target = _resolve_safe_path(rel)
    if target is None:
        return web.json_response({"error": "Invalid path"}, status=400)
    if not target.is_file():
        return web.json_response({"error": "Memory not found"}, status=404)

    try:
        target.unlink()
    except OSError as exc:
        logger.warning("Failed to delete memory %s: %s", rel, exc)
        return web.json_response({"error": "Could not delete memory"}, status=500)

    logger.info("Memory deleted: %s", rel)
    _maybe_sync_memory(rel)
    return web.json_response({"deleted": rel})


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/memories", handle_list_memories)
    app.router.add_get("/api/memories/file", handle_get_memory)
    app.router.add_post("/api/memories/file", handle_create_memory)
    app.router.add_put("/api/memories/file", handle_update_memory)
    app.router.add_delete("/api/memories/file", handle_delete_memory)
