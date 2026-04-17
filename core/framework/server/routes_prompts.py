"""Custom user prompts — CRUD for user-uploaded prompts.

- GET    /api/prompts        — list all custom prompts
- POST   /api/prompts        — add a new custom prompt
- DELETE /api/prompts/{id}   — delete a custom prompt
"""

import json
import logging
import time
from pathlib import Path

from aiohttp import web

from framework.config import HIVE_HOME

logger = logging.getLogger(__name__)

CUSTOM_PROMPTS_FILE = HIVE_HOME / "custom_prompts.json"


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
        "custom": True,
    }
    prompts.append(new_prompt)
    _save_custom_prompts(prompts)
    logger.info("Custom prompt added: %s", title)
    return web.json_response(new_prompt, status=201)


async def handle_delete_prompt(request: web.Request) -> web.Response:
    """DELETE /api/prompts/{prompt_id} — delete a custom prompt."""
    prompt_id = request.match_info["prompt_id"]
    prompts = _load_custom_prompts()
    before = len(prompts)
    prompts = [p for p in prompts if p.get("id") != prompt_id]
    if len(prompts) == before:
        return web.json_response({"error": "Prompt not found"}, status=404)
    _save_custom_prompts(prompts)
    return web.json_response({"deleted": prompt_id})


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/prompts", handle_list_prompts)
    app.router.add_post("/api/prompts", handle_create_prompt)
    app.router.add_delete("/api/prompts/{prompt_id}", handle_delete_prompt)
