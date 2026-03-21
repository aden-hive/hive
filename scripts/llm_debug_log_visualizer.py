#!/usr/bin/env python3
"""Open a browser-based viewer for Hive LLM debug JSONL sessions.

Starts a local HTTP server and loads session data on demand (one at a time).

Usage:
    uv run --no-project scripts/llm_debug_log_visualizer.py
    uv run --no-project scripts/llm_debug_log_visualizer.py --session <execution_id>
    uv run --no-project scripts/llm_debug_log_visualizer.py --port 8080
    uv run --no-project scripts/llm_debug_log_visualizer.py --output debug.html
"""

from __future__ import annotations

import argparse
import http.server
import json
import urllib.parse
import webbrowser
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SessionSummary:
    execution_id: str
    log_file: str
    start_timestamp: str
    end_timestamp: str
    turn_count: int
    streams: list[str]
    nodes: list[str]
    models: list[str]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path.home() / ".hive" / "llm_logs",
        help="Directory containing Hive LLM debug JSONL files.",
    )
    parser.add_argument(
        "--session",
        help="Execution ID to select initially in the webpage.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional HTML output path. Defaults to a temporary file.",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=200,
        help="Maximum number of newest log files to scan.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port for the local server (0 = auto-pick a free port).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Start the server but do not open a browser.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Show test/mock sessions (hidden by default).",
    )
    return parser.parse_args()


def _safe_read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    payload = {
                        "timestamp": "",
                        "execution_id": "",
                        "assistant_text": "",
                        "_parse_error": f"{path.name}:{line_number}",
                        "_raw_line": line,
                    }
                payload["_log_file"] = str(path)
                records.append(payload)
    except OSError as exc:
        print(f"warning: failed to read {path}: {exc}")
    return records


def _discover_records(logs_dir: Path, limit_files: int) -> list[dict[str, Any]]:
    if not logs_dir.exists():
        raise FileNotFoundError(f"log directory not found: {logs_dir}")

    files = sorted(
        [
            path
            for path in logs_dir.iterdir()
            if path.is_file() and path.suffix == ".jsonl"
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:limit_files]

    records: list[dict[str, Any]] = []
    for path in files:
        records.extend(_safe_read_jsonl(path))
    return records


def _format_timestamp(raw: str) -> str:
    if not raw:
        return "-"
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def _is_test_session(execution_id: str, records: list[dict[str, Any]]) -> bool:
    """Return True for sessions that look like test artifacts."""
    if execution_id.startswith("<MagicMock"):
        return True
    models = {
        str(r.get("token_counts", {}).get("model", ""))
        for r in records
        if isinstance(r.get("token_counts"), dict)
    }
    models.discard("")
    # Sessions that only used the mock LLM provider.
    if models and models <= {"mock"}:
        return True
    # Sessions with no real model at all (empty string or missing).
    if not models:
        return True
    return False


def _group_sessions(
    records: list[dict[str, Any]],
    *,
    include_tests: bool = False,
) -> tuple[list[SessionSummary], dict[str, list[dict[str, Any]]]]:
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        execution_id = str(record.get("execution_id") or "").strip()
        if execution_id:
            by_session[execution_id].append(record)

    if not include_tests:
        by_session = {
            eid: recs
            for eid, recs in by_session.items()
            if not _is_test_session(eid, recs)
        }

    summaries: list[SessionSummary] = []
    for execution_id, session_records in by_session.items():
        session_records.sort(
            key=lambda record: (
                str(record.get("timestamp", "")),
                record.get("iteration", 0),
            )
        )
        first = session_records[0]
        last = session_records[-1]
        summaries.append(
            SessionSummary(
                execution_id=execution_id,
                log_file=str(first.get("_log_file", "")),
                start_timestamp=str(first.get("timestamp", "")),
                end_timestamp=str(last.get("timestamp", "")),
                turn_count=len(session_records),
                streams=sorted(
                    {
                        str(r.get("stream_id", ""))
                        for r in session_records
                        if r.get("stream_id")
                    }
                ),
                nodes=sorted(
                    {
                        str(r.get("node_id", ""))
                        for r in session_records
                        if r.get("node_id")
                    }
                ),
                models=sorted(
                    {
                        str(r.get("token_counts", {}).get("model", ""))
                        for r in session_records
                        if isinstance(r.get("token_counts"), dict)
                        and r.get("token_counts", {}).get("model")
                    }
                ),
            )
        )

    summaries.sort(key=lambda summary: summary.start_timestamp, reverse=True)
    return summaries, by_session


def _render_html(
    summaries: list[SessionSummary],
    initial_session_id: str,
) -> str:
    summaries_data = [
        {
            "execution_id": summary.execution_id,
            "log_file": summary.log_file,
            "start_timestamp": summary.start_timestamp,
            "end_timestamp": summary.end_timestamp,
            "start_display": _format_timestamp(summary.start_timestamp),
            "end_display": _format_timestamp(summary.end_timestamp),
            "turn_count": summary.turn_count,
            "streams": summary.streams,
            "nodes": summary.nodes,
            "models": summary.models,
        }
        for summary in summaries
    ]

    initial = initial_session_id or (summaries[0].execution_id if summaries else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hive LLM Debug Viewer</title>
  <style>
    :root {{
      --bg: #efe6d8;
      --panel: rgba(255, 251, 245, 0.92);
      --panel-strong: #fffdfa;
      --ink: #1f1d19;
      --muted: #6d6457;
      --line: #ddceb6;
      --accent: #b64a2b;
      --accent-deep: #7a2813;
      --sidebar: #2b211d;
      --sidebar-soft: #3e302a;
      --user: #0f766e;
      --assistant: #7c3aed;
      --tool: #9a3412;
      --shadow: 0 18px 44px rgba(60, 39, 14, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(182, 74, 43, 0.14), transparent 28rem),
        linear-gradient(180deg, #f8f3ea 0%, var(--bg) 100%);
    }}
    .app {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
    }}
    .sidebar {{
      background:
        linear-gradient(180deg, rgba(62, 48, 42, 0.96), rgba(29, 21, 18, 0.98));
      color: white;
      padding: 24px 18px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }}
    .brand {{
      margin-bottom: 20px;
    }}
    .brand h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      line-height: 1;
    }}
    .brand p {{
      margin: 0;
      color: rgba(255, 255, 255, 0.72);
      line-height: 1.45;
    }}
    .sidebar input, .sidebar select {{
      width: 100%;
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.08);
      color: white;
      padding: 12px 14px;
      margin: 10px 0;
    }}
    .sidebar input {{
      width: 100%;
      border: 1px solid rgba(255, 255, 255, 0.14);
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.08);
      color: white;
      padding: 12px 14px;
      margin: 10px 0;
    }}
    .sidebar input::placeholder {{
      color: rgba(255, 255, 255, 0.5);
    }}
    .setup-note {{
      margin-top: 14px;
      padding: 14px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.07);
      border: 1px solid rgba(255, 255, 255, 0.12);
    }}
    .setup-note h3 {{
      margin: 0 0 8px;
      font-size: 14px;
    }}
    .setup-note p {{
      margin: 0 0 10px;
      color: rgba(255, 255, 255, 0.76);
      line-height: 1.45;
      font-size: 13px;
    }}
    .setup-note pre {{
      margin: 0;
      background: rgba(0, 0, 0, 0.24);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: white;
    }}
    .session-list {{
      display: grid;
      gap: 10px;
      margin-top: 16px;
    }}
    .session-card {{
      border: 1px solid rgba(255, 255, 255, 0.1);
      background: rgba(255, 255, 255, 0.06);
      color: white;
      border-radius: 18px;
      padding: 14px;
      cursor: pointer;
      text-align: left;
      width: 100%;
    }}
    .session-card.active {{
      background: linear-gradient(145deg, rgba(182, 74, 43, 0.96), rgba(122, 40, 19, 0.96));
      border-color: rgba(255, 255, 255, 0.24);
    }}
    .session-card .sid {{
      font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
      font-size: 12px;
      word-break: break-all;
      opacity: 0.95;
    }}
    .session-card .meta {{
      margin-top: 8px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      font-size: 12px;
      color: rgba(255, 255, 255, 0.76);
    }}
    .session-card .meta span {{
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.09);
      padding: 4px 8px;
    }}
    .main {{
      padding: 26px;
      min-width: 0;
    }}
    .hero {{
      background: linear-gradient(145deg, rgba(182, 74, 43, 0.96), rgba(122, 40, 19, 0.96));
      color: white;
      border-radius: 28px;
      padding: 28px;
      box-shadow: var(--shadow);
    }}
    .hero h2 {{
      margin: 0 0 8px;
      font-size: clamp(30px, 5vw, 46px);
      line-height: 1.02;
    }}
    .hero code {{
      display: inline-block;
      margin-top: 4px;
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.14);
      font-size: 13px;
      word-break: break-all;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .meta-card {{
      border-radius: 16px;
      padding: 14px;
      background: rgba(255, 255, 255, 0.11);
      border: 1px solid rgba(255, 255, 255, 0.14);
    }}
    .meta-card .label {{
      display: block;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: rgba(255, 255, 255, 0.68);
      margin-bottom: 6px;
    }}
    .toolbar {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin: 22px 0 18px;
    }}
    .toolbar input {{
      flex: 1 1 320px;
      min-width: 220px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 12px 16px;
      background: rgba(255, 255, 255, 0.9);
      box-shadow: var(--shadow);
    }}
    .toolbar button {{
      border: 0;
      border-radius: 999px;
      padding: 12px 16px;
      background: var(--accent);
      color: white;
      cursor: pointer;
    }}
    .turn {{
      background: var(--panel);
      border: 1px solid rgba(121, 93, 44, 0.14);
      border-radius: 24px;
      padding: 20px;
      margin: 18px 0;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }}
    .turn.hidden {{
      display: none;
    }}
    .turn-head {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    .turn-title {{
      font-size: 24px;
      font-weight: 700;
    }}
    .turn-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .turn-meta span {{
      background: #efe4d1;
      border-radius: 999px;
      padding: 6px 10px;
    }}
    details.block {{
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--panel-strong);
      padding: 14px 16px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
    }}
    .message {{
      margin-top: 12px;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: #fffdfa;
    }}
    .message-header {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 10px;
      font-size: 13px;
      color: var(--muted);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 999px;
      color: white;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .badge-user {{ background: var(--user); }}
    .badge-assistant {{ background: var(--assistant); }}
    .badge-tool {{ background: var(--tool); }}
    .badge-system {{ background: #334155; }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      overflow-x: auto;
      border-radius: 14px;
      padding: 14px;
      background: #faf5ec;
      border: 1px solid #eee2cf;
      font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
      font-size: 13px;
      line-height: 1.55;
    }}
    .tool-block {{
      margin-top: 12px;
    }}
    .tool-name {{
      font-weight: 700;
    }}
    .status {{
      margin-left: auto;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 11px;
      text-transform: uppercase;
      font-weight: 700;
    }}
    .status.ok {{
      background: #dcfce7;
      color: #166534;
    }}
    .status.error {{
      background: #fee2e2;
      color: #991b1b;
    }}
    .empty {{
      padding: 32px;
      color: var(--muted);
      text-align: center;
      border: 1px dashed var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.45);
    }}
    @media (max-width: 980px) {{
      .app {{
        grid-template-columns: 1fr;
      }}
      .sidebar {{
        position: static;
        height: auto;
      }}
      .main {{
        padding-top: 14px;
      }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <h1>Hive Debug</h1>
        <p>Pick a session in the browser and inspect prompts, inputs, outputs, and tool activity turn by turn.</p>
      </div>
      <input id="sessionSearch" type="search" placeholder="Filter sessions">
      <div class="setup-note">
        <h3>Logging status</h3>
        <p>LLM turn logging is always on. If this list is empty, run Hive once and refresh after the session produces turns.</p>
        <pre>~/.hive/llm_logs</pre>
      </div>
      <div class="session-list" id="sessionList"></div>
    </aside>
    <main class="main">
      <section class="hero">
        <h2 id="heroTitle">LLM Debug Session</h2>
        <code id="heroId"></code>
        <div class="meta-grid" id="metaGrid"></div>
      </section>
      <div class="toolbar">
        <input id="turnFilter" type="search" placeholder="Filter selected session by text, tool name, role, model, or prompt content">
        <button type="button" id="expandAll">Expand all</button>
        <button type="button" id="collapseAll">Collapse all</button>
      </div>
      <div id="turns"></div>
    </main>
  </div>

  <script id="session-summaries" type="application/json">{json.dumps(summaries_data, ensure_ascii=False)}</script>
  <script>
    const summaries = JSON.parse(document.getElementById("session-summaries").textContent);
    const recordCache = {{}};
    const initialSessionId = {json.dumps(initial, ensure_ascii=False)};

    const sessionSearch = document.getElementById("sessionSearch");
    const sessionList = document.getElementById("sessionList");
    const heroTitle = document.getElementById("heroTitle");
    const heroId = document.getElementById("heroId");
    const metaGrid = document.getElementById("metaGrid");
    const turnsEl = document.getElementById("turns");
    const turnFilter = document.getElementById("turnFilter");

    let activeSessionId = initialSessionId || (summaries[0] ? summaries[0].execution_id : "");

    function text(value) {{
      return value == null ? "" : String(value);
    }}

    function escapeHtml(value) {{
      return text(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }}

    function prettyJson(value) {{
      return escapeHtml(JSON.stringify(value, null, 2));
    }}

    function sessionMatches(summary, query) {{
      if (!query) return true;
      const haystack = [
        summary.execution_id,
        summary.start_display,
        summary.end_display,
        summary.log_file,
        ...(summary.streams || []),
        ...(summary.nodes || []),
        ...(summary.models || []),
      ].join("\\n").toLowerCase();
      return haystack.includes(query);
    }}

    function renderSessionChooser() {{
      const query = sessionSearch.value.trim().toLowerCase();
      const filtered = summaries.filter((summary) => sessionMatches(summary, query));

      sessionList.innerHTML = filtered
        .map((summary) => {{
          const active = summary.execution_id === activeSessionId ? " active" : "";
          const chips = [
            summary.start_display,
            `${{summary.turn_count}} turns`,
            ...(summary.models || []).slice(0, 2),
          ];
          return `
            <button type="button" class="session-card${{active}}" data-session-id="${{escapeHtml(summary.execution_id)}}">
              <div class="sid">${{escapeHtml(summary.execution_id)}}</div>
              <div class="meta">${{chips.map((chip) => `<span>${{escapeHtml(chip)}}</span>`).join("")}}</div>
            </button>
          `;
        }})
        .join("") || '<div class="empty">No matching sessions.</div>';
    }}

    function renderMetaCard(label, value) {{
      return `<div class="meta-card"><span class="label">${{escapeHtml(label)}}</span>${{escapeHtml(value || "-")}}</div>`;
    }}

    function renderMessage(message, index) {{
      const role = text(message.role || "unknown");
      const content = text(message.content || "");
      const toolCalls = message.tool_calls;
      return `
        <div class="message">
          <div class="message-header">
            <span class="badge badge-${{escapeHtml(role)}}">${{escapeHtml(role)}}</span>
            <span>message ${{index}}</span>
          </div>
          ${{
            content
              ? `<pre>${{escapeHtml(content)}}</pre>`
              : '<div class="empty">(empty message)</div>'
          }}
          ${{
            toolCalls
              ? `<details class="block"><summary>tool_calls</summary><pre>${{prettyJson(toolCalls)}}</pre></details>`
              : ""
          }}
        </div>
      `;
    }}

    function renderToolCall(toolCall, index) {{
      const name = text(toolCall.tool_name || (toolCall.function || {{}}).name || "unknown");
      const error = !!toolCall.is_error;
      return `
        <div class="tool-block">
          <div class="message-header">
            <span class="badge badge-tool">tool ${{index}}</span>
            <span class="tool-name">${{escapeHtml(name)}}</span>
            <span class="status ${{error ? "error" : "ok"}}">${{error ? "error" : "ok"}}</span>
          </div>
          <pre>${{prettyJson(toolCall)}}</pre>
        </div>
      `;
    }}

    function renderTurn(record) {{
      const tokenCounts = record.token_counts || {{}};
      const messages = Array.isArray(record.messages) ? record.messages : [];
      const toolCalls = Array.isArray(record.tool_calls) ? record.tool_calls : [];
      const toolResults = Array.isArray(record.tool_results) ? record.tool_results : [];
      const systemPrompt = text(record.system_prompt || "");
      const assistantText = text(record.assistant_text || "");
      const parseError = text(record._parse_error || "");

      return `
        <section class="turn">
          <div class="turn-head">
            <div class="turn-title">Iteration ${{escapeHtml(record.iteration ?? "?")}}</div>
            <div class="turn-meta">
              <span>${{escapeHtml(record.timestamp || "-")}}</span>
              <span>node=${{escapeHtml(record.node_id || "-")}}</span>
              <span>stream=${{escapeHtml(record.stream_id || "-")}}</span>
              <span>model=${{escapeHtml(tokenCounts.model || "-")}}</span>
              <span>stop=${{escapeHtml(tokenCounts.stop_reason || "-")}}</span>
              <span>in=${{escapeHtml(tokenCounts.input ?? "-")}}</span>
              <span>out=${{escapeHtml(tokenCounts.output ?? "-")}}</span>
            </div>
          </div>
          ${{
            systemPrompt
              ? `<details class="block" open><summary>System prompt</summary><pre>${{escapeHtml(systemPrompt)}}</pre></details>`
              : ""
          }}
          ${{
            messages.length
              ? `<details class="block" open><summary>Input messages (${{messages.length}})</summary>${{messages.map((message, index) => renderMessage(message, index + 1)).join("")}}</details>`
              : ""
          }}
          <details class="block" open>
            <summary>Assistant output</summary>
            <pre>${{escapeHtml(assistantText)}}</pre>
          </details>
          ${{
            toolCalls.length
              ? `<details class="block" open><summary>Tool calls (${{toolCalls.length}})</summary>${{toolCalls.map((toolCall, index) => renderToolCall(toolCall, index + 1)).join("")}}</details>`
              : ""
          }}
          ${{
            toolResults.length
              ? `<details class="block"><summary>Tool results (${{toolResults.length}})</summary><pre>${{prettyJson(toolResults)}}</pre></details>`
              : ""
          }}
          ${{
            parseError
              ? `<details class="block"><summary>Parse error</summary><pre>${{prettyJson(record)}}</pre></details>`
              : ""
          }}
        </section>
      `;
    }}

    async function fetchSession(sessionId) {{
      if (recordCache[sessionId]) return recordCache[sessionId];
      const resp = await fetch(`/api/session/${{encodeURIComponent(sessionId)}}`);
      if (!resp.ok) return [];
      const data = await resp.json();
      recordCache[sessionId] = data;
      return data;
    }}

    async function renderSession(sessionId) {{
      activeSessionId = sessionId;
      const summary = summaries.find((entry) => entry.execution_id === sessionId);

      renderSessionChooser();

      if (!summary) {{
        heroTitle.textContent = "No session selected";
        heroId.textContent = "";
        metaGrid.innerHTML = "";
        turnsEl.innerHTML = '<div class="empty">No session data available.</div>';
        return;
      }}

      heroTitle.textContent = "LLM Debug Session";
      heroId.textContent = summary.execution_id;
      metaGrid.innerHTML = [
        renderMetaCard("Started", summary.start_display),
        renderMetaCard("Ended", summary.end_display),
        renderMetaCard("Turns", String(summary.turn_count)),
        renderMetaCard("Streams", (summary.streams || []).join(", ")),
        renderMetaCard("Nodes", (summary.nodes || []).join(", ")),
        renderMetaCard("Models", (summary.models || []).join(", ")),
        renderMetaCard("Source file", summary.log_file),
      ].join("");

      turnsEl.innerHTML = '<div class="empty">Loading session\u2026</div>';
      const records = await fetchSession(sessionId);
      if (activeSessionId !== sessionId) return;
      turnsEl.innerHTML = records.length
        ? records.map((record) => renderTurn(record)).join("")
        : '<div class="empty">This session has no turn records.</div>';

      applyTurnFilter();
      history.replaceState(null, "", `#${{encodeURIComponent(sessionId)}}`);
    }}

    function applyTurnFilter() {{
      const query = turnFilter.value.trim().toLowerCase();
      for (const turn of document.querySelectorAll(".turn")) {{
        const visible = !query || turn.textContent.toLowerCase().includes(query);
        turn.classList.toggle("hidden", !visible);
      }}
    }}

    sessionSearch.addEventListener("input", renderSessionChooser);
    sessionList.addEventListener("click", (event) => {{
      const card = event.target.closest(".session-card");
      if (!card) return;
      renderSession(card.dataset.sessionId);
    }});
    turnFilter.addEventListener("input", applyTurnFilter);
    document.getElementById("expandAll").addEventListener("click", () => {{
      for (const details of document.querySelectorAll("details")) details.open = true;
    }});
    document.getElementById("collapseAll").addEventListener("click", () => {{
      for (const details of document.querySelectorAll("details")) details.open = false;
    }});

    const hashSession = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    const knownIds = new Set(summaries.map((s) => s.execution_id));
    const bootSession = knownIds.has(hashSession) ? hashSession : activeSessionId;
    renderSessionChooser();
    renderSession(bootSession);
  </script>
</body>
</html>
"""


def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda r: (str(r.get("timestamp", "")), r.get("iteration", 0)),
    )


def _run_server(
    html: str,
    sessions: dict[str, list[dict[str, Any]]],
    port: int,
    no_open: bool,
) -> None:
    html_bytes = html.encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                self._respond(200, "text/html; charset=utf-8", html_bytes)
            elif self.path.startswith("/api/session/"):
                sid = urllib.parse.unquote(self.path[len("/api/session/") :])
                records = sessions.get(sid)
                if records is None:
                    self._respond(404, "application/json", b"[]")
                else:
                    body = json.dumps(
                        _sort_records(records), ensure_ascii=False
                    ).encode("utf-8")
                    self._respond(200, "application/json", body)
            else:
                self.send_error(404)

        def _respond(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # silence per-request logs

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"
    print(f"Serving at {url}  (Ctrl+C to stop)")

    if not no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def main() -> int:
    args = _parse_args()
    records = _discover_records(args.logs_dir.expanduser(), args.limit_files)
    summaries, sessions = _group_sessions(records, include_tests=args.include_tests)

    initial_session_id = args.session or (
        summaries[0].execution_id if summaries else ""
    )
    if initial_session_id and initial_session_id not in sessions:
        print(f"session not found: {initial_session_id}")
        return 1

    html_report = _render_html(summaries, initial_session_id)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(html_report, encoding="utf-8")
        print(args.output)
        return 0

    _run_server(html_report, sessions, args.port, args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
