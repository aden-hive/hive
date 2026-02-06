# image_tools

A small, safe, pure‑Python MCP toolset providing basic image utilities for agents.

## Summary
Provides four tools for common image tasks: resizing, compression, format conversion, and metadata extraction. Designed to be memory conscious and easy to register with a FastMCP server.

## Features
- image_resize — Resize images (optionally maintain aspect ratio).
- image_compress — Compress JPEG/PNG/WebP with a simple quality mapping.
- image_convert — Convert between common formats (png, jpg/jpeg, webp, bmp, gif).
- image_metadata — Read format, mode, size, file size and optional EXIF.

## Installation
Requires Pillow (BSD-3). Install:
```
pip install "Pillow>=10.0.0"
```

## Usage (register with MCP)
```py
from fastmcp import FastMCP
from aden_tools.tools.image_tools import register_tools

mcp = FastMCP("server")
register_tools(mcp)
```

## Tool signatures (examples)
- image_resize(image_path: str, width: int, height: int, maintain_aspect_ratio: bool = True, output_path: str | None = None) -> dict
- image_compress(image_path: str, quality: int = 75, output_path: str | None = None) -> dict
- image_convert(image_path: str, target_format: str, output_path: str | None = None) -> dict
- image_metadata(image_path: str, include_exif: bool = True) -> dict

Each tool returns a dict with either a "success": True and result fields, or an "error" key with a message.

## Notes / Limitations
- Expects trusted file paths; follow-up work will integrate sandboxing/session helpers.
- GIF/animated images: only the first frame is handled; animation preservation is out of scope.
- Tests include a permission-denial case that is skipped on Windows (chmod behavior differs).
- File size capped for safety (10 MB by default).

## Tests
Tests live at: tools/tests/tools/test_image_tool.py  
Run locally:
```
python -m pytest tools/tests/tools/test_image_tool.py -q
```