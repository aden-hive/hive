"""Image generation tool — generate and edit images, billed to Hive credits.

Calls the Hive LLM proxy's image endpoint (``{proxy}/v1/images/generations``),
which forwards to OpenAI's ``gpt-image-2`` with a *server-side* key and meters
the returned token usage so the cost lands on the user's Hive credits — exactly
like a normal LLM call. The user supplies no API key of their own: auth reuses
the runtime's per-user proxy token (``HIVE_API_KEY``), the same Bearer token the
LLM client sends, and the proxy maps that token to the team for billing.

Text-to-image uses the generations path. When ``reference_images`` are supplied
the proxy routes to OpenAI's ``/v1/images/edits`` instead; this tool loads each
reference (local path or ``http(s)`` URL), base64-encodes it, and ships it in
the JSON ``image`` array so the proxy can rebuild OpenAI's multipart form. The
proxy is intentionally JSON-only — this tool never sends multipart upstream.

Defaults match the product spec: model ``gpt-image-2``, ``quality="low"`` (the
cheapest tier), ``size="1024x1024"``, ``n=1``. Before saving, each image runs
through ``_postprocess_image`` — a Pillow pass that crisps the model's soft
edges and strips the embedded C2PA provenance watermark (best-effort; the raw
image is kept on any failure). Generated images are written to the tool-artifact
dir; the result carries each saved path plus one inline preview. Hand a path to
``attach_file`` to surface it to the user as a chip.

API reference: https://developers.openai.com/api/docs/guides/image-generation
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

# Proxy default host (mirrors framework.config.HIVE_LLM_ENDPOINT). Overridable
# via HIVE_LLM_BASE_URL, the same override the LLM client honors.
DEFAULT_PROXY_BASE = "https://llm.open-hive.com"
IMAGES_PATH = "/v1/images/generations"

DEFAULT_MODEL = "gpt-image-2"
MAX_N = 4  # clamp: each image is billed separately, so cap runaway spend
MAX_REFERENCE_IMAGES = 10  # OpenAI edits accepts up to ~10 reference images
MAX_REF_BYTES = 10 * 1024 * 1024  # per reference image (matches vision_tool)
MAX_TOTAL_REF_BYTES = 20 * 1024 * 1024  # total reference payload over the proxy
# Image generation can take minutes. The tool runs in the background (it's in
# LoopConfig.background_tools), so this long wait never blocks the agent. Keep
# it under the background-tool timeout (235s) and the 240s MCP-client ceiling.
REQUEST_TIMEOUT = 225.0

# Only "low" quality is enabled for cost control. "medium"/"high"/"auto" are
# all disabled and forced down to "low" (medium is ~6x and high ~35x a low
# draft's output tokens/cost). Re-enable a tier by adding it to _ALLOWED_QUALITY.
_ALLOWED_QUALITY = {"low"}
_VALID_FORMATS = {"png", "jpeg", "webp"}
_FORMAT_TO_EXT = {"png": "png", "jpeg": "jpg", "webp": "webp"}
_FORMAT_TO_MIME = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
_SUFFIX_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _err(message: str, **extra: object) -> list:
    """Return an error as a single-block MCP content list.

    Always returning a list (never a bare dict) keeps the tool's return shape
    uniform with the success path, so the leading block the agent reads is
    always JSON — same convention as ``attach_file``.
    """
    payload: dict[str, object] = {"error": message}
    payload.update(extra)
    return [TextContent(type="text", text=json.dumps(payload))]


def _resolve_image_artifact_dir() -> Path:
    """Directory where generated images are written.

    Prefers ``<HIVE_STORAGE_PATH>/data`` (the per-agent session data dir the
    framework injects into the MCP subprocess env); falls back to the shared
    ``<HIVE_HOME>/tool-artifacts``. Identical resolution to ``web_scrape``.
    """
    storage = os.environ.get("HIVE_STORAGE_PATH")
    if storage:
        return Path(storage) / "data"
    hive_home = os.environ.get("HIVE_HOME")
    base = Path(hive_home).expanduser() if hive_home else Path.home() / ".hive"
    return base / "tool-artifacts"


def _is_internal_address(raw_ip: str) -> bool:
    """True for any non-public address (fails closed on unparseable input)."""
    ip_str = raw_ip.split("%")[0] if "%" in raw_ip else raw_ip
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return not addr.is_global or addr.is_multicast


def _url_target_is_public(url: str) -> bool:
    """SSRF guard: resolve the URL host and reject internal/non-public targets.

    Reference-image URLs are fetched from inside the runtime, so we must block
    requests that would reach link-local / private / loopback infrastructure.
    """
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return bool(infos) and all(not _is_internal_address(str(i[4][0])) for i in infos)


def _load_reference_image(source: str) -> tuple[str, int] | dict[str, str]:
    """Load a reference image (local path or http(s) URL) → (base64, byte_len).

    Returns an ``{"error": ...}`` dict on any failure. The proxy expects raw
    base64 (no ``data:`` prefix); it rebuilds OpenAI's multipart ``image[]``.
    """
    if source.startswith(("http://", "https://")):
        if not _url_target_is_public(source):
            return {"error": f"Blocked non-public or unresolvable image URL: {source}"}
        try:
            resp = httpx.get(source, timeout=30.0, follow_redirects=True)
        except httpx.TimeoutException:
            return {"error": f"Reference image download timed out: {source}"}
        except httpx.RequestError as exc:
            return {"error": f"Failed to fetch reference image {source}: {exc}"}
        if resp.status_code != 200:
            return {"error": f"Reference image fetch failed (HTTP {resp.status_code}): {source}"}
        content_type = resp.headers.get("content-type", "").lower()
        if not content_type.startswith("image/"):
            return {"error": f"Reference URL is not an image (content-type {content_type or 'unknown'}): {source}"}
        raw = resp.content
        if len(raw) > MAX_REF_BYTES:
            return {"error": f"Reference image exceeds {MAX_REF_BYTES // (1024 * 1024)}MB: {source}"}
        return base64.b64encode(raw).decode("utf-8"), len(raw)

    path = Path(source).expanduser()
    if not path.exists() or not path.is_file():
        return {"error": f"Reference image not found: {source}"}
    size = path.stat().st_size
    if size > MAX_REF_BYTES:
        return {"error": f"Reference image exceeds {MAX_REF_BYTES // (1024 * 1024)}MB: {source}"}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"error": f"Failed to read reference image {source}: {exc}"}
    return base64.b64encode(raw).decode("utf-8"), len(raw)


def _proxy_error(resp: httpx.Response) -> str:
    """Extract a human-readable message from a proxy/OpenAI error response.

    Both the Hive proxy (``{"type":"error","error":{"type","message"}}``) and
    OpenAI (``{"error":{"message"}}``) nest the message under ``error``.
    """
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("type") or err)
    if isinstance(err, str):
        return err
    return resp.text[:300]


def _postprocess_image(raw: bytes, fmt: str) -> bytes:
    """Crisp up a generated image and strip its provenance watermark.

    ``gpt-image`` output has two rough spots: a soft anti-aliased *glow* around
    text/shapes and low-frequency *mottle* in flat fills, plus an embedded C2PA
    content-credentials manifest (a ``caBX`` PNG chunk — OpenAI's provenance
    watermark). This does three passes with Pillow only (no numpy):

    1. **Flatness-masked median denoise** — smooths the mottle in flat regions
       while keeping original pixels at edges (masked by a high-pass edge map),
       so text/lines stay sharp.
    2. **Unsharp mask** (radius 1.1, 110%, threshold 2) — tightens the glow into
       crisp edges. Deliberately mild: stronger settings ring/halo on the
       high-contrast flat-color art these diagrams are made of.
    3. **Re-encode from pixels** — Pillow writes none of the source's ancillary
       chunks, so the C2PA/EXIF/XMP metadata (the watermark) is dropped.

    Note: gpt-image does *not* embed a robust invisible pixel watermark (that's
    Google SynthID), so the re-encode removes provenance completely and
    losslessly — no quality-destroying attack needed.

    Best-effort: any failure (Pillow missing, decode error, unknown format)
    returns ``raw`` unchanged so image generation — which was already billed —
    never breaks over cosmetics.
    """
    try:
        from io import BytesIO

        from PIL import Image, ImageChops, ImageFilter

        im = Image.open(BytesIO(raw))
        had_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        if had_alpha and fmt != "jpeg":  # JPEG has no alpha channel
            im = im.convert("RGBA")
            alpha = im.getchannel("A")
            base = im.convert("RGB")
        else:
            alpha = None
            base = im.convert("RGB")

        # 1. Denoise flat fills only. `edge` is a high-pass map (|img - blur|);
        # composite keeps `base` where edges are strong, `den` where flat.
        den = base.filter(ImageFilter.MedianFilter(3))
        gray = base.convert("L")
        edge = ImageChops.difference(gray, gray.filter(ImageFilter.GaussianBlur(1)))
        edge = edge.point(lambda p: 255 if p * 8 > 255 else p * 8)
        result = Image.composite(base, den, edge)

        # 2. Crispen.
        result = result.filter(ImageFilter.UnsharpMask(radius=1.1, percent=110, threshold=2))

        if alpha is not None:
            result = result.convert("RGBA")
            result.putalpha(alpha)

        # 3. Re-encode without metadata (drops the C2PA watermark chunk).
        out = BytesIO()
        if fmt == "jpeg":
            result.save(out, "JPEG", quality=95, subsampling=0)
        elif fmt == "webp":
            result.save(out, "WEBP", quality=95, method=6)
        else:
            result.save(out, "PNG", optimize=True)
        return out.getvalue()
    except Exception:
        # Never let cosmetic post-processing sink an already-billed generation.
        return raw


def register_tools(mcp: FastMCP) -> None:
    """Register the image generation tool with the MCP server."""

    @mcp.tool()
    def image_generate(
        prompt: str,
        reference_images: list[str] | None = None,
        size: str = "1024x1024",
        quality: str = "low",
        n: int = 1,
        output_format: str = "png",
        model: str = DEFAULT_MODEL,
    ) -> list:
        """Generate or edit an image from a text prompt. Billed to Hive credits.

        Routes through the Hive image service (OpenAI ``gpt-image-2``). The cost
        is charged to the user's credits like an LLM call — no API key needed.

        Provide ``reference_images`` to edit / compose from existing images
        (e.g. restyle a product photo, combine elements, keep a character's
        identity); the model conditions on them at high fidelity. Without them
        it's pure text-to-image.

        Args:
            prompt: What to draw. Be specific about subject, style, composition,
                colors, and any text to render.
            reference_images: Up to 10 local file paths or http(s) URLs to
                condition on. Omit for text-to-image.
            size: ``1024x1024`` (default), ``1536x1024`` (landscape),
                ``1024x1536`` (portrait), or ``auto``.
            quality: ``low`` only. Higher tiers (``medium``/``high``/``auto``)
                are disabled for cost control and are forced down to ``low``.
            n: Number of images, 1-4 (default 1). Each one is billed separately.
            output_format: ``png`` (default), ``jpeg``, or ``webp``.
            model: Image model. Defaults to ``gpt-image-2``.

        Returns:
            An MCP content list: a leading TextContent JSON summary with
            ``images`` (each ``{path, size, quality, format, bytes}``), ``model``,
            ``n``, and ``usage`` tokens, plus one inline image preview. Pass a
            saved ``path`` to ``attach_file`` to show the user a downloadable
            chip. On failure, a single TextContent JSON ``{"error": ...}``.
        """
        token = os.environ.get("HIVE_API_KEY")
        if not token:
            return _err("Image generation unavailable: missing Hive proxy token. Sign in to refresh credentials, then retry.")

        # Normalize / clamp inputs (the proxy validates further upstream).
        n = max(1, min(int(n), MAX_N))
        if quality not in _ALLOWED_QUALITY:
            quality = "low"  # medium/high/auto disabled — cost control
        output_format = output_format if output_format in _VALID_FORMATS else "png"

        body: dict[str, object] = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": n,
            "output_format": output_format,
        }

        # Load reference images (if any) into the JSON `image` base64 array.
        if reference_images:
            if len(reference_images) > MAX_REFERENCE_IMAGES:
                return _err(f"Too many reference images: {len(reference_images)} (max {MAX_REFERENCE_IMAGES}).")
            encoded: list[str] = []
            total = 0
            for src in reference_images:
                loaded = _load_reference_image(src)
                if isinstance(loaded, dict):
                    return _err(loaded["error"])
                b64, nbytes = loaded
                total += nbytes
                if total > MAX_TOTAL_REF_BYTES:
                    return _err(f"Reference images total exceeds {MAX_TOTAL_REF_BYTES // (1024 * 1024)}MB.")
                encoded.append(b64)
            body["image"] = encoded

        base = (os.environ.get("HIVE_LLM_BASE_URL") or DEFAULT_PROXY_BASE).rstrip("/")
        url = base + IMAGES_PATH
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT)
        except httpx.TimeoutException:
            # Don't auto-retry: the image may have been generated (and billed).
            return _err("Image generation timed out. Try again; do not retry repeatedly.")
        except httpx.RequestError as exc:
            return _err(f"Network error reaching image service: {exc}")

        if resp.status_code != 200:
            detail = _proxy_error(resp)
            if resp.status_code == 402:
                return _err(f"Out of Hive credits (or subscription inactive): {detail}", status=402)
            if resp.status_code == 401:
                return _err("Authentication failed reaching the image service (proxy token rejected).", status=401)
            if resp.status_code == 403:
                return _err(f"Image model unavailable (provider access / org verification): {detail}", status=403)
            if resp.status_code == 429:
                return _err("Image service rate-limited. Wait a moment, then retry once.", status=429)
            if resp.status_code == 400:
                return _err(f"Image request rejected: {detail}. Rephrase the prompt if it was moderated.", status=400)
            return _err(f"Image service error (HTTP {resp.status_code}): {detail}", status=resp.status_code)

        try:
            data = resp.json()
        except ValueError:
            return _err("Image service returned a non-JSON response.")
        items = data.get("data") if isinstance(data, dict) else None
        if not items:
            return _err("Image service returned no image data.")

        out_dir = _resolve_image_artifact_dir()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _err(f"Failed to create output directory: {exc}")

        ext = _FORMAT_TO_EXT.get(output_format, "png")
        mime = _FORMAT_TO_MIME.get(output_format, "image/png")
        ts_ms = int(time.time() * 1000)
        saved: list[dict[str, object]] = []
        first_preview_b64: str | None = None
        for idx, item in enumerate(items):
            b64 = item.get("b64_json") if isinstance(item, dict) else None
            if not b64:
                continue
            try:
                raw = base64.b64decode(b64)
            except (ValueError, TypeError):
                continue
            # Crisp up rough edges and strip the C2PA provenance watermark
            # before the bytes ever touch disk (best-effort; returns raw on any
            # failure). Do this once here so the saved file, the reported byte
            # count, and the inline preview all reflect the cleaned image.
            raw = _postprocess_image(raw, output_format)
            path = out_dir / f"image_gen_{ts_ms}_{idx}.{ext}"
            try:
                path.write_bytes(raw)
            except OSError as exc:
                return _err(f"Failed to write generated image: {exc}")
            saved.append(
                {
                    "path": str(path.resolve()),
                    "size": size,
                    "quality": quality,
                    "format": output_format,
                    "bytes": len(raw),
                }
            )
            # Inline only the first image to keep the result JSON-first and
            # under the agent-loop's max_tool_result_chars (a spilled result
            # would lose this summary). The rest live on disk; the agent can
            # attach_file them. Re-encode the cleaned bytes so the preview
            # matches what was saved.
            if first_preview_b64 is None:
                first_preview_b64 = base64.b64encode(raw).decode("utf-8")

        if not saved:
            return _err("Image service returned data but no decodable image.")

        summary: dict[str, object] = {
            "images": saved,
            "model": model,
            "n": len(saved),
            "usage": data.get("usage") if isinstance(data, dict) else None,
            "next_step": "Call attach_file(path) on an image path to show the user a downloadable chip.",
        }
        if len(saved) > 1:
            summary["note"] = "Only the first image is previewed inline; the rest are on disk — attach_file them to show the user."

        blocks: list[object] = [TextContent(type="text", text=json.dumps(summary))]
        if first_preview_b64 is not None:
            blocks.append(ImageContent(type="image", data=first_preview_b64, mimeType=mime))
        return blocks
