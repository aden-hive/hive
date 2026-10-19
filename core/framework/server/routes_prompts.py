"""Custom user prompts — CRUD for user-uploaded prompts.

- GET    /api/prompts        — list all custom prompts
- POST   /api/prompts        — add a new custom prompt
- PATCH  /api/prompts/{id}   — update a custom prompt
- DELETE /api/prompts/{id}   — delete a custom prompt
"""

import json
import logging
import time

from aiohttp import web

from framework.cloud_sync_hooks import schedule_push
from framework.config import HIVE_HOME

logger = logging.getLogger(__name__)

CUSTOM_PROMPTS_FILE = HIVE_HOME / "custom_prompts.json"

# Per-item and per-list caps. `skills` holds hand-picked skill names (e.g.
# "hive.browser-automation"), so the length cap is generous enough to keep a
# fully-qualified skill name intact rather than truncating it. `tags` (freeform)
# uses the same shape.
_MAX_ITEMS = 10
_MAX_ITEM_LEN = 64


def _normalize_str_list(raw: object) -> list[str]:
    """Coerce an incoming string-list payload (tags or skills) to a clean,
    deduplicated lowercase list. Drops empties, trims whitespace, caps
    per-item length, and caps the overall list. Order is preserved (first
    occurrence wins)."""
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        val = item.strip().lower()[:_MAX_ITEM_LEN]
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
        if len(out) >= _MAX_ITEMS:
            break
    return out


def _load_custom_prompts() -> list[dict]:
    if not CUSTOM_PROMPTS_FILE.exists():
        return []
    try:
        data = json.loads(CUSTOM_PROMPTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_custom_prompts(prompts: list[dict]) -> None:
    CUSTOM_PROMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_PROMPTS_FILE.write_text(
        json.dumps(prompts, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


async def handle_list_prompts(request: web.Request) -> web.Response:
    """GET /api/prompts — list all custom prompts."""
    return web.json_response({"prompts": _load_custom_prompts()})


async def handle_create_prompt(request: web.Request) -> web.Response:
    """POST /api/prompts — add a new custom prompt."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    title = (body.get("title") or "").strip()
    category = (body.get("category") or "").strip()
    content = (body.get("content") or "").strip()

    if not title or not content:
        return web.json_response({"error": "Title and content are required"}, status=400)

    prompts = _load_custom_prompts()
    new_prompt = {
        "id": f"custom_{int(time.time() * 1000)}",
        "title": title,
        "category": category or "custom",
        "content": content,
        # Hand-picked skills the prompt references (also embedded inline in
        # content as <use_skill> markers). `tags` stays freeform.
        "skills": _normalize_str_list(body.get("skills")),
        "tags": _normalize_str_list(body.get("tags")),
        "custom": True,
    }
    prompts.append(new_prompt)
    _save_custom_prompts(prompts)
    logger.info("Custom prompt added: %s", title)
    schedule_push("prompt", new_prompt["id"])
    return web.json_response(new_prompt, status=201)


async def handle_update_prompt(request: web.Request) -> web.Response:
    """PATCH /api/prompts/{prompt_id} — update a custom prompt's title/category/content."""
    prompt_id = request.match_info["prompt_id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    # Only the user-editable fields are accepted; id/custom are immutable.
    updates: dict = {}
    if "title" in body:
        title = (body.get("title") or "").strip()
        if not title:
            return web.json_response({"error": "Title cannot be empty"}, status=400)
        updates["title"] = title
    if "category" in body:
        updates["category"] = (body.get("category") or "").strip() or "custom"
    if "content" in body:
        content = (body.get("content") or "").strip()
        if not content:
            return web.json_response({"error": "Content cannot be empty"}, status=400)
        updates["content"] = content
    if "skills" in body:
        # Always rewrite the full list — the modal submits the complete
        # hand-picked skill set on every save.
        updates["skills"] = _normalize_str_list(body.get("skills"))
    if "tags" in body:
        # Always rewrite the full list — partial tag edits aren't a thing
        # client-side; the modal submits the complete chip set.
        updates["tags"] = _normalize_str_list(body.get("tags"))

    if not updates:
        return web.json_response({"error": "No editable fields provided"}, status=400)

    prompts = _load_custom_prompts()
    for p in prompts:
        if p.get("id") == prompt_id:
            p.update(updates)
            _save_custom_prompts(prompts)
            logger.info("Custom prompt updated: %s", prompt_id)
            schedule_push("prompt", prompt_id)
            return web.json_response(p)
    return web.json_response({"error": "Prompt not found"}, status=404)


async def handle_delete_prompt(request: web.Request) -> web.Response:
    """DELETE /api/prompts/{prompt_id} — delete a custom prompt."""
    prompt_id = request.match_info["prompt_id"]
    prompts = _load_custom_prompts()
    before = len(prompts)
    prompts = [p for p in prompts if p.get("id") != prompt_id]
    if len(prompts) == before:
        return web.json_response({"error": "Prompt not found"}, status=404)
    _save_custom_prompts(prompts)
    schedule_push("prompt", prompt_id)
    return web.json_response({"deleted": prompt_id})


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/prompts", handle_list_prompts)
    app.router.add_post("/api/prompts", handle_create_prompt)
    app.router.add_patch("/api/prompts/{prompt_id}", handle_update_prompt)
    app.router.add_delete("/api/prompts/{prompt_id}", handle_delete_prompt)
