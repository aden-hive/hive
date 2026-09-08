#!/usr/bin/env python3
"""Render a Hive conversation parts directory as a self-contained HTML timeline.

Usage:
    uv run --no-project scripts/conversation_parts_viewer.py /path/to/conversations
    uv run --no-project scripts/conversation_parts_viewer.py /path/to/conversations --out /tmp/conversation.html
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("conversation_dir", type=Path, help="Directory containing meta.json and parts/*.json")
    parser.add_argument(
        "--out", type=Path, default=None, help="HTML output path. Defaults to /tmp/<conversation-dir>-conversation.html"
    )
    parser.add_argument("--open", action="store_true", help="Open the generated HTML in the default browser")
    parser.add_argument(
        "--max-embed-chars", type=int, default=2_000_000, help="Trim very large content fields before embedding in HTML"
    )
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def _decode_leading_json(text: str) -> tuple[Any | None, str]:
    decoder = json.JSONDecoder()
    stripped = text.lstrip()
    if not stripped:
        return None, ""
    try:
        value, end = decoder.raw_decode(stripped)
    except json.JSONDecodeError:
        return None, text
    return value, stripped[end:].strip()


def _shorten(value: Any, max_chars: int) -> Any:
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + f"\n\n[trimmed {len(value) - max_chars:,} chars]"
    if isinstance(value, list):
        return [_shorten(item, max_chars) for item in value]
    if isinstance(value, dict):
        return {key: _shorten(item, max_chars) for key, item in value.items()}
    return value


def _part_summary(part: dict[str, Any], max_embed_chars: int) -> dict[str, Any]:
    content = str(part.get("content") or "")
    decoded_json, trailing_text = _decode_leading_json(content) if part.get("role") == "tool" else (None, "")
    tool_calls = part.get("tool_calls") if isinstance(part.get("tool_calls"), list) else []

    return {
        "seq": part.get("seq"),
        "role": part.get("role", "unknown"),
        "content": _shorten(content, max_embed_chars),
        "contentChars": len(content),
        "tool_use_id": part.get("tool_use_id"),
        "tool_calls": _shorten(tool_calls, max_embed_chars),
        "decoded_tool_json": _shorten(decoded_json, max_embed_chars),
        "decoded_tool_trailing_text": _shorten(trailing_text, max_embed_chars),
        "raw": _shorten(part, max_embed_chars),
    }


def _load_parts(conversation_dir: Path, max_embed_chars: int) -> list[dict[str, Any]]:
    parts_dir = conversation_dir / "parts"
    if not parts_dir.is_dir():
        raise FileNotFoundError(f"missing parts directory: {parts_dir}")

    parts: list[dict[str, Any]] = []
    for path in sorted(parts_dir.glob("*.json")):
        part = _read_json(path)
        summary = _part_summary(part, max_embed_chars)
        summary["file"] = str(path)
        parts.append(summary)

    parts.sort(
        key=lambda item: (item.get("seq") if isinstance(item.get("seq"), int) else sys.maxsize, item.get("file", ""))
    )
    return parts


def _tool_call_maps(parts: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, list[int]]]:
    calls_by_id: dict[str, dict[str, Any]] = {}
    result_seq_by_call_id: dict[str, list[int]] = {}
    for part in parts:
        for call in part.get("tool_calls") or []:
            call_id = str(call.get("id") or "")
            if call_id:
                calls_by_id[call_id] = call
        tool_use_id = part.get("tool_use_id")
        if tool_use_id:
            result_seq_by_call_id.setdefault(str(tool_use_id), []).append(part.get("seq"))
    return calls_by_id, result_seq_by_call_id


def _read_optional_meta(conversation_dir: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for name in ("meta.json", "cursor.json"):
        path = conversation_dir / name
        if path.exists():
            try:
                meta[name] = _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                meta[name] = {"error": str(exc)}
    return meta


def _default_output_path(conversation_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("/tmp") / f"{conversation_dir.name}_conversation_{stamp}.html"


def _render_html(conversation_dir: Path, parts: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    role_counts = Counter(str(part.get("role", "unknown")) for part in parts)
    calls_by_id, result_seq_by_call_id = _tool_call_maps(parts)
    call_names = Counter(
        str(call.get("function", {}).get("name") or "unknown")
        for call in calls_by_id.values()
        if isinstance(call.get("function"), dict)
    )

    payload = {
        "conversationDir": str(conversation_dir),
        "parts": parts,
        "meta": meta,
        "callsById": calls_by_id,
        "resultSeqByCallId": result_seq_by_call_id,
        "roleCounts": dict(role_counts),
        "callNames": dict(call_names),
    }
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hive Conversation Parts Viewer</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #f5f5f2;
  --panel: #ffffff;
  --ink: #181816;
  --muted: #66665f;
  --border: #dad8cf;
  --user: #0f766e;
  --assistant: #2563eb;
  --tool: #b45309;
  --system: #7c3aed;
  --shadow: 0 8px 24px rgba(22, 22, 19, 0.08);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #151513;
    --panel: #20201d;
    --ink: #f1f0ea;
    --muted: #aaa79b;
    --border: #3b3a34;
    --shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
button, input, select {{
  font: inherit;
}}
.layout {{
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  min-height: 100vh;
}}
aside {{
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: auto;
  border-right: 1px solid var(--border);
  background: color-mix(in srgb, var(--panel) 92%, var(--bg));
  padding: 18px;
}}
main {{
  padding: 22px;
}}
h1 {{
  margin: 0 0 8px;
  font-size: 20px;
  letter-spacing: 0;
}}
h2 {{
  margin: 18px 0 8px;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--muted);
}}
.path {{
  color: var(--muted);
  overflow-wrap: anywhere;
  font-size: 12px;
}}
.controls {{
  display: grid;
  gap: 8px;
  margin: 16px 0;
}}
.row {{
  display: flex;
  gap: 8px;
  align-items: center;
}}
input, select, button {{
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--panel);
  color: var(--ink);
  padding: 8px 10px;
}}
input, select {{
  width: 100%;
}}
button {{
  cursor: pointer;
  white-space: nowrap;
}}
.stat-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}}
.stat {{
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  background: var(--panel);
}}
.stat strong {{
  display: block;
  font-size: 20px;
}}
.chips {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}
.chip {{
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--muted);
  background: var(--panel);
  font-size: 12px;
}}
.timeline {{
  display: grid;
  gap: 12px;
  max-width: 1180px;
}}
.part {{
  border: 1px solid var(--border);
  border-left-width: 5px;
  border-radius: 8px;
  background: var(--panel);
  box-shadow: var(--shadow);
  overflow: clip;
}}
.part[data-role="user"] {{ border-left-color: var(--user); }}
.part[data-role="assistant"] {{ border-left-color: var(--assistant); }}
.part[data-role="tool"] {{ border-left-color: var(--tool); }}
.part[data-role="system"] {{ border-left-color: var(--system); }}
.part-header {{
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  padding: 11px 13px;
  border-bottom: 1px solid var(--border);
}}
.seq {{
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}}
.role {{
  display: inline-flex;
  align-items: center;
  width: max-content;
  border-radius: 999px;
  padding: 2px 8px;
  background: var(--bg);
  color: var(--muted);
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: .08em;
}}
.title {{
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
}}
.part-body {{
  display: grid;
  gap: 10px;
  padding: 13px;
}}
.preview {{
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 14em;
  overflow: auto;
}}
details {{
  border: 1px solid var(--border);
  border-radius: 7px;
  background: color-mix(in srgb, var(--panel) 88%, var(--bg));
}}
summary {{
  cursor: pointer;
  padding: 8px 10px;
  color: var(--muted);
}}
pre {{
  margin: 0;
  padding: 10px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border-top: 1px solid var(--border);
  font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}}
.hidden {{
  display: none;
}}
@media (max-width: 860px) {{
  .layout {{ grid-template-columns: 1fr; }}
  aside {{ position: relative; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }}
  main {{ padding: 14px; }}
  .part-header {{ grid-template-columns: 1fr; }}
  .title {{ white-space: normal; }}
}}
</style>
</head>
<body>
<div class="layout">
  <aside>
    <h1>Conversation Parts</h1>
    <div class="path"></div>
    <div class="controls">
      <input id="search" type="search" placeholder="Search content, tool names, ids">
      <div class="row">
        <select id="roleFilter" aria-label="Role filter">
          <option value="">All roles</option>
        </select>
        <button id="expandAll">Expand</button>
        <button id="collapseAll">Collapse</button>
      </div>
    </div>
    <h2>Summary</h2>
    <div class="stat-grid" id="stats"></div>
    <h2>Tool Calls</h2>
    <div class="chips" id="toolChips"></div>
    <h2>Metadata</h2>
    <details>
      <summary>meta.json / cursor.json</summary>
      <pre id="meta"></pre>
    </details>
  </aside>
  <main>
    <div class="timeline" id="timeline"></div>
  </main>
</div>
<script id="payload" type="application/json">{payload_json}</script>
<script>
const data = JSON.parse(document.getElementById("payload").textContent);
const callsById = data.callsById || {{}};
const resultSeqByCallId = data.resultSeqByCallId || {{}};
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}}[c]));
const asJson = (value) => JSON.stringify(value, null, 2);

document.querySelector(".path").textContent = data.conversationDir;
document.getElementById("meta").textContent = asJson(data.meta);

const roleFilter = document.getElementById("roleFilter");
Object.keys(data.roleCounts).sort().forEach(role => {{
  const option = document.createElement("option");
  option.value = role;
  option.textContent = `${{role}} (${{data.roleCounts[role]}})`;
  roleFilter.appendChild(option);
}});

const stats = document.getElementById("stats");
const totalToolCalls = Object.values(data.callNames || {{}}).reduce((sum, count) => sum + count, 0);
[
  ["Parts", data.parts.length],
  ["Tool calls", totalToolCalls],
  ...Object.entries(data.roleCounts).sort(),
].forEach(([label, value]) => {{
  const div = document.createElement("div");
  div.className = "stat";
  div.innerHTML = `<strong>${{esc(value)}}</strong><span>${{esc(label)}}</span>`;
  stats.appendChild(div);
}});

const toolChips = document.getElementById("toolChips");
Object.entries(data.callNames || {{}}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).forEach(([name, count]) => {{
  const span = document.createElement("span");
  span.className = "chip";
  span.textContent = `${{name}} x ${{count}}`;
  toolChips.appendChild(span);
}});
if (!toolChips.childElementCount) toolChips.textContent = "No tool calls found.";

function toolNameForResult(part) {{
  const call = callsById[part.tool_use_id];
  return call?.function?.name || part.tool_use_id || "tool result";
}}

function toolCallTitle(call) {{
  const name = call?.function?.name || "unknown_tool";
  const resultSeqs = resultSeqByCallId[call.id] || [];
  return `${{name}}${{resultSeqs.length ? " -> result #" + resultSeqs.join(", #") : ""}}`;
}}

function partTitle(part) {{
  if (part.role === "assistant" && part.tool_calls?.length) {{
    return part.tool_calls.map(toolCallTitle).join(" | ");
  }}
  if (part.role === "tool") return `result for ${{toolNameForResult(part)}}`;
  const firstLine = String(part.content || "").split(/\\n/).find(Boolean) || "";
  return firstLine.slice(0, 160);
}}

function renderToolCalls(part) {{
  if (!part.tool_calls?.length) return "";
  return `<details open><summary>Tool calls (${{part.tool_calls.length}})</summary><pre>${{esc(asJson(part.tool_calls))}}</pre></details>`;
}}

function renderToolJson(part) {{
  if (part.decoded_tool_json === null || part.decoded_tool_json === undefined) return "";
  const trailing = part.decoded_tool_trailing_text ? `\\n\\n--- trailing text ---\\n${{part.decoded_tool_trailing_text}}` : "";
  return `<details open><summary>Decoded tool result JSON</summary><pre>${{esc(asJson(part.decoded_tool_json) + trailing)}}</pre></details>`;
}}

function renderPart(part) {{
  const title = partTitle(part);
  const searchable = [
    part.seq, part.role, part.content, part.tool_use_id, title,
    ...(part.tool_calls || []).map(call => `${{call.id}} ${{call?.function?.name}} ${{call?.function?.arguments}}`)
  ].join("\\n").toLowerCase();

  return `<article class="part" data-role="${{esc(part.role)}}" data-search="${{esc(searchable)}}">
    <div class="part-header">
      <span class="seq">#${{esc(part.seq)}}</span>
      <span class="title">${{esc(title)}}</span>
      <span class="role">${{esc(part.role)}}</span>
    </div>
    <div class="part-body">
      <div class="chips">
        <span class="chip">${{esc(part.contentChars)}} chars</span>
        ${{part.tool_use_id ? `<span class="chip">${{esc(part.tool_use_id)}}</span>` : ""}}
        ${{part.file ? `<span class="chip">${{esc(part.file.split("/").pop())}}</span>` : ""}}
      </div>
      <div class="preview">${{esc(part.content || "(no content)")}}</div>
      ${{renderToolCalls(part)}}
      ${{renderToolJson(part)}}
      <details><summary>Raw part JSON</summary><pre>${{esc(asJson(part.raw))}}</pre></details>
    </div>
  </article>`;
}}

const timeline = document.getElementById("timeline");
timeline.innerHTML = data.parts.map(renderPart).join("");

function applyFilters() {{
  const query = document.getElementById("search").value.trim().toLowerCase();
  const role = roleFilter.value;
  document.querySelectorAll(".part").forEach(node => {{
    const roleOk = !role || node.dataset.role === role;
    const queryOk = !query || node.dataset.search.includes(query);
    node.classList.toggle("hidden", !(roleOk && queryOk));
  }});
}}

document.getElementById("search").addEventListener("input", applyFilters);
roleFilter.addEventListener("change", applyFilters);
document.getElementById("expandAll").addEventListener("click", () => document.querySelectorAll("details").forEach(d => d.open = true));
document.getElementById("collapseAll").addEventListener("click", () => document.querySelectorAll("details").forEach(d => d.open = false));
</script>
</body>
</html>
"""


def main() -> int:
    args = _parse_args()
    conversation_dir = args.conversation_dir.expanduser().resolve()
    if not conversation_dir.is_dir():
        raise FileNotFoundError(f"conversation directory not found: {conversation_dir}")

    parts = _load_parts(conversation_dir, args.max_embed_chars)
    meta = _read_optional_meta(conversation_dir)
    out_path = (args.out or _default_output_path(conversation_dir)).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_html(conversation_dir, parts, meta), encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"Rendered {len(parts)} parts")
    if args.open:
        webbrowser.open(out_path.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
