#!/usr/bin/env python3
"""Timeline viewer for Hive LLM debug JSONL sessions.

Sister script to ``llm_debug_log_visualizer.py``. Where that one renders
turn-by-turn cards, this one renders a chronological event timeline so a
developer can click any event (user input, tool use, tool result, assistant
text) and inspect the *raw* request payload that was sent to the LLM at that
moment — system prompt, full tool schemas, full messages array.

Usage:
    uv run --no-project scripts/llm_timeline_viewer.py
    uv run --no-project scripts/llm_timeline_viewer.py --session <execution_id>
    uv run --no-project scripts/llm_timeline_viewer.py --port 8080
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
    parser.add_argument("--session", help="Execution ID to select initially.")
    parser.add_argument("--limit-files", type=int, default=200)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--include-tests", action="store_true")
    return parser.parse_args()


def _format_timestamp(raw: str) -> str:
    if not raw:
        return "-"
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def _is_test_session(execution_id: str, records: list[dict[str, Any]]) -> bool:
    if execution_id.startswith("<MagicMock"):
        return True
    models = {
        str(r.get("token_counts", {}).get("model", "")) for r in records if isinstance(r.get("token_counts"), dict)
    }
    models.discard("")
    if models and models <= {"mock"}:
        return True
    if not models:
        return True
    return False


def _discover_session_summaries(logs_dir: Path, limit_files: int, include_tests: bool) -> list[SessionSummary]:
    if not logs_dir.exists():
        raise FileNotFoundError(f"log directory not found: {logs_dir}")

    files = sorted(
        [p for p in logs_dir.iterdir() if p.is_file() and p.suffix == ".jsonl"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit_files]

    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in files:
        try:
            with path.open(encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    eid = str(payload.get("execution_id") or "").strip()
                    if not eid:
                        continue
                    minimal = {
                        "timestamp": payload.get("timestamp", ""),
                        "iteration": payload.get("iteration", 0),
                        "stream_id": payload.get("stream_id", ""),
                        "node_id": payload.get("node_id", ""),
                        "token_counts": payload.get("token_counts", {}),
                        "_log_file": str(path),
                    }
                    by_session[eid].append(minimal)
        except OSError:
            continue

    if not include_tests:
        by_session = {eid: recs for eid, recs in by_session.items() if not _is_test_session(eid, recs)}

    summaries: list[SessionSummary] = []
    for eid, recs in by_session.items():
        recs.sort(key=lambda r: (str(r.get("timestamp", "")), r.get("iteration", 0)))
        first, last = recs[0], recs[-1]
        summaries.append(
            SessionSummary(
                execution_id=eid,
                log_file=str(first.get("_log_file", "")),
                start_timestamp=str(first.get("timestamp", "")),
                end_timestamp=str(last.get("timestamp", "")),
                turn_count=len(recs),
                streams=sorted({str(r.get("stream_id", "")) for r in recs if r.get("stream_id")}),
                nodes=sorted({str(r.get("node_id", "")) for r in recs if r.get("node_id")}),
                models=sorted(
                    {
                        str(r.get("token_counts", {}).get("model", ""))
                        for r in recs
                        if isinstance(r.get("token_counts"), dict) and r.get("token_counts", {}).get("model")
                    }
                ),
            )
        )

    summaries.sort(key=lambda s: s.start_timestamp, reverse=True)
    return summaries


def _load_session_data(logs_dir: Path, session_id: str, limit_files: int) -> list[dict[str, Any]] | None:
    if not logs_dir.exists():
        return None

    files = sorted(
        [p for p in logs_dir.iterdir() if p.is_file() and p.suffix == ".jsonl"],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit_files]

    records: list[dict[str, Any]] = []
    for path in files:
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
                            "_parse_error": f"{path.name}:{line_number}",
                            "_raw_line": line,
                        }
                    if str(payload.get("execution_id") or "").strip() == session_id:
                        payload["_log_file"] = str(path)
                        records.append(payload)
        except OSError:
            continue

    if not records:
        return None
    records.sort(key=lambda r: (str(r.get("timestamp", "")), r.get("iteration", 0)))
    return records


def _render_html(summaries: list[SessionSummary], initial_session_id: str) -> str:
    summaries_data = [
        {
            "execution_id": s.execution_id,
            "log_file": s.log_file,
            "start_timestamp": s.start_timestamp,
            "end_timestamp": s.end_timestamp,
            "start_display": _format_timestamp(s.start_timestamp),
            "end_display": _format_timestamp(s.end_timestamp),
            "turn_count": s.turn_count,
            "streams": s.streams,
            "nodes": s.nodes,
            "models": s.models,
        }
        for s in summaries
    ]
    initial = initial_session_id or (summaries[0].execution_id if summaries else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hive LLM Timeline</title>
  <style>
    :root {{
      --bg: #0f1115;
      --panel: #161922;
      --panel-2: #1c2030;
      --line: #262b3a;
      --ink: #e6e8ee;
      --muted: #8a93a6;
      --accent: #e07a48;
      --accent-2: #6aa9ff;
      --user: #2dd4bf;
      --assistant: #c084fc;
      --tool-use: #f59e0b;
      --tool-result: #34d399;
      --system: #94a3b8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 13px/1.5 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    .app {{
      display: grid;
      grid-template-columns: 280px 420px minmax(0, 1fr);
      height: 100vh;
    }}
    .col {{
      border-right: 1px solid var(--line);
      overflow: auto;
      min-width: 0;
    }}
    .col:last-child {{ border-right: 0; }}
    .col-head {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky; top: 0; z-index: 1;
      display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    }}
    .col-head h2 {{ margin: 0; font-size: 13px; letter-spacing: 0.04em;
                     text-transform: uppercase; color: var(--muted); flex: 1; }}
    .col-head input, .col-head select {{
      background: var(--panel-2);
      color: var(--ink);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 10px;
      font: inherit;
      width: 100%;
    }}
    .session-list {{ padding: 8px; }}
    .session {{
      padding: 10px 12px;
      border-radius: 10px;
      cursor: pointer;
      margin-bottom: 4px;
    }}
    .session:hover {{ background: var(--panel); }}
    .session.active {{ background: linear-gradient(135deg, #2a1d14, #1a1410);
                       border: 1px solid #4a2e1c; }}
    .session .sid {{ font-family: ui-monospace, Menlo, monospace; font-size: 11px;
                     word-break: break-all; }}
    .session .meta {{ margin-top: 6px; color: var(--muted); font-size: 11px; }}
    .timeline {{ padding: 4px 0; }}
    .ev {{
      padding: 8px 12px 8px 36px;
      border-left: 2px solid var(--line);
      margin-left: 14px;
      position: relative;
      cursor: pointer;
    }}
    .ev:hover {{ background: var(--panel); }}
    .ev.active {{ background: var(--panel-2); }}
    .ev::before {{
      content: "";
      position: absolute;
      left: -7px; top: 14px;
      width: 12px; height: 12px;
      border-radius: 50%;
      background: var(--line);
      border: 2px solid var(--bg);
    }}
    .ev.kind-user::before {{ background: var(--user); }}
    .ev.kind-assistant::before {{ background: var(--assistant); }}
    .ev.kind-tool_use::before {{ background: var(--tool-use); }}
    .ev.kind-tool_result::before {{ background: var(--tool-result); }}
    .ev.kind-system::before {{ background: var(--system); }}
    .ev .row {{ display: flex; gap: 8px; align-items: center; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .badge.kind-user {{ background: rgba(45, 212, 191, 0.16); color: var(--user); }}
    .badge.kind-assistant {{ background: rgba(192, 132, 252, 0.16); color: var(--assistant); }}
    .badge.kind-tool_use {{ background: rgba(245, 158, 11, 0.16); color: var(--tool-use); }}
    .badge.kind-tool_result {{ background: rgba(52, 211, 153, 0.16); color: var(--tool-result); }}
    .badge.kind-system {{ background: rgba(148, 163, 184, 0.16); color: var(--system); }}
    .badge.err {{ background: rgba(239, 68, 68, 0.18); color: #fca5a5; }}
    .ev .ts {{ color: var(--muted); font-size: 11px; margin-left: auto;
                font-family: ui-monospace, Menlo, monospace; }}
    .ev .iter {{ color: var(--muted); font-size: 11px;
                  font-family: ui-monospace, Menlo, monospace; }}
    .ev .preview {{
      margin-top: 4px;
      color: var(--muted);
      font-family: ui-monospace, Menlo, monospace;
      font-size: 11px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .ev .turn-marker {{ color: var(--accent); font-weight: 700; }}
    .raw {{ padding: 14px 18px; }}
    .raw h3 {{ margin: 0 0 8px; font-size: 12px; color: var(--muted);
                text-transform: uppercase; letter-spacing: 0.06em; }}
    .raw section {{ margin-bottom: 18px; }}
    .raw .head {{
      display: flex; gap: 10px; align-items: center; margin-bottom: 12px;
      flex-wrap: wrap;
    }}
    .raw .chip {{
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 11px;
      color: var(--muted);
      font-family: ui-monospace, Menlo, monospace;
    }}
    pre.json {{
      margin: 0;
      padding: 12px 14px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      max-height: 60vh;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, Menlo, monospace;
      font-size: 12px;
    }}
    pre.text {{
      margin: 0;
      padding: 12px 14px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      max-height: 60vh;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font: inherit;
      line-height: 1.55;
    }}
    .hl-msg {{
      outline: 2px solid var(--accent);
      border-radius: 8px;
      background: rgba(224, 122, 72, 0.08);
    }}
    .msg {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      margin: 8px 0;
      background: var(--panel-2);
    }}
    .msg-head {{ display: flex; gap: 8px; align-items: center; margin-bottom: 6px;
                   font-size: 11px; color: var(--muted); }}
    .empty {{ color: var(--muted); padding: 24px; text-align: center;
               border: 1px dashed var(--line); border-radius: 10px; margin: 14px; }}
    details > summary {{ cursor: pointer; color: var(--accent-2); user-select: none; }}
    details {{ margin-top: 6px; }}
    .scroll-target {{ scroll-margin-top: 80px; }}
  </style>
</head>
<body>
  <div class="app">
    <div class="col">
      <div class="col-head">
        <h2>Sessions</h2>
        <input id="sessionSearch" type="search" placeholder="Filter">
      </div>
      <div class="session-list" id="sessionList"></div>
    </div>
    <div class="col">
      <div class="col-head">
        <h2 id="timelineHead">Timeline</h2>
        <select id="kindFilter">
          <option value="">all events</option>
          <option value="user">user input</option>
          <option value="assistant">assistant text</option>
          <option value="tool_use">tool use</option>
          <option value="tool_result">tool result</option>
          <option value="system">system</option>
        </select>
      </div>
      <div class="timeline" id="timeline"></div>
    </div>
    <div class="col">
      <div class="col-head"><h2>Raw context sent to LLM</h2></div>
      <div class="raw" id="raw">
        <div class="empty">Select an event on the timeline to view the raw request payload (system prompt, tool schemas, full messages array) for that LLM call.</div>
      </div>
    </div>
  </div>

  <script id="session-summaries" type="application/json">{json.dumps(summaries_data, ensure_ascii=False)}</script>
  <script>
    const summaries = JSON.parse(document.getElementById("session-summaries").textContent);
    const initialSessionId = {json.dumps(initial, ensure_ascii=False)};
    const recordCache = {{}};

    let activeSessionId = initialSessionId || (summaries[0] ? summaries[0].execution_id : "");
    let activeRecords = [];
    let activeEvents = [];
    let activeToolMeta = new Map();  // tool_call_id -> {{toolName, isError, ...}}
    let activeEventId = null;

    const $ = (id) => document.getElementById(id);

    function escapeHtml(value) {{
      return String(value == null ? "" : value)
        .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
    }}
    function shortTime(iso) {{
      // Normalize to local clock-time. Two formats land here:
      //   - "2026-04-29T18:24:08"          (naive — older turn timestamps)
      //   - "2026-04-30T01:24:08+00:00"    (UTC — tool_call start_timestamp)
      // Per ISO 8601, naive = local, so `new Date(s)` interprets correctly.
      if (!iso) return "";
      const d = new Date(String(iso));
      if (Number.isNaN(d.getTime())) {{
        const m = String(iso).match(/T(\\d{{2}}:\\d{{2}}:\\d{{2}})/);
        return m ? m[1] : String(iso);
      }}
      return d.toLocaleTimeString([], {{ hour12: false }});
    }}
    function preview(text, n = 140) {{
      const s = String(text == null ? "" : text).replace(/\\s+/g, " ").trim();
      return s.length > n ? s.slice(0, n) + "…" : s;
    }}
    function contentToText(content) {{
      if (content == null) return "";
      if (typeof content === "string") return content;
      if (Array.isArray(content)) {{
        return content.map((b) => {{
          if (!b || typeof b !== "object") return "";
          if (b.type === "text") return b.text || "";
          if (b.type === "image_url") return "[image]";
          if (b.type === "image") return "[image]";
          if (b.type === "tool_use") return `[tool_use:${{b.name || ""}}]`;
          if (b.type === "tool_result") {{
            const c = b.content;
            if (typeof c === "string") return c;
            if (Array.isArray(c)) return contentToText(c);
            return "[tool_result]";
          }}
          return JSON.stringify(b).slice(0, 200);
        }}).join(" · ");
      }}
      try {{ return JSON.stringify(content).slice(0, 200); }} catch {{ return ""; }}
    }}

    function renderSessions() {{
      const q = ($("sessionSearch").value || "").toLowerCase().trim();
      const filtered = summaries.filter((s) => {{
        if (!q) return true;
        return [s.execution_id, s.start_display, ...(s.models || []), ...(s.nodes || [])]
          .join("\\n").toLowerCase().includes(q);
      }});
      $("sessionList").innerHTML = filtered.map((s) => {{
        const cls = s.execution_id === activeSessionId ? "session active" : "session";
        const chips = [s.start_display, `${{s.turn_count}} turns`, ...(s.models || []).slice(0, 1)]
          .filter(Boolean).map((c) => escapeHtml(c)).join(" · ");
        return `<div class="${{cls}}" data-sid="${{escapeHtml(s.execution_id)}}">
                  <div class="sid">${{escapeHtml(s.execution_id)}}</div>
                  <div class="meta">${{chips}}</div>
                </div>`;
      }}).join("") || '<div class="empty">No sessions.</div>';
    }}

    /**
     * Build the chronological event list from a session's turn records.
     *
     * Each record is one LLM call. To avoid re-emitting the same conversation
     * messages on every turn, we diff: for turn N, only the messages added on
     * top of turn N-1's `messages` are new events (these are the user inputs
     * and tool_results that triggered turn N). Then we add an output event for
     * the assistant text and one event per tool_call from this turn.
     */
    /**
     * Build a global tool_use_id -> {{startTs, durationS, toolName, isError}}
     * map across ALL turns. The records use OpenAI-style envelopes:
     *   - assistant message: {{role, content: null, tool_calls: [{{id, function:{{name,arguments}}}}]}}
     *   - tool message:      {{role:"tool", tool_call_id, content}}
     * rec.tool_calls carries each invocation's real start_timestamp + duration_s,
     * which is what we need so tool_uses sit at their actual execution time
     * (not the much later "turn was logged" wall clock) and tool_results
     * sit just after their matching call.
     */
    function buildToolMeta(records) {{
      const toolMeta = new Map();
      for (const rec of records) {{
        for (const tc of (rec.tool_calls || [])) {{
          const id = tc.tool_use_id || tc.id;
          if (!id) continue;
          toolMeta.set(id, {{
            startTs: tc.start_timestamp || rec.timestamp || "",
            durationS: typeof tc.duration_s === "number" ? tc.duration_s : 0,
            toolName: tc.tool_name || (tc.function && tc.function.name) || "?",
            isError: !!tc.is_error,
          }});
        }}
      }}
      return toolMeta;
    }}

    function buildEvents(records, toolMeta) {{
      const addSeconds = (iso, sec) => {{
        if (!iso) return iso;
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        d.setTime(d.getTime() + (sec || 0) * 1000);
        return d.toISOString();
      }};

      const events = [];
      // Dedupe by content-derived key (not array position): context pruning
      // shrinks `messages` between turns and a watermark drops everything
      // after the cut. Hashing anchors each unique message/call/result to
      // the FIRST turn it appeared in.
      const seenMsg = new Set();
      const stableMsgKey = (m) => {{
        const role = String(m.role || "");
        const tcid = m.tool_call_id || "";
        let body = "";
        try {{ body = typeof m.content === "string" ? m.content : JSON.stringify(m); }}
        catch {{ body = ""; }}
        return role + "\\x1f" + tcid + "\\x1f" + body.slice(0, 600);
      }};
      const seenAsstText = new Set();
      const seenToolUse = new Set();

      for (let i = 0; i < records.length; i++) {{
        const rec = records[i];
        const msgs = Array.isArray(rec.messages) ? rec.messages : [];

        // Per-turn timestamp inference: tool_use / tool_result have REAL
        // timestamps (from rec.tool_calls); user / asst text only have the
        // turn-record timestamp (the "logged at" wall clock, much later
        // than when the event actually happened). Forward+backward fill from
        // known tool times so neighbors display monotonically.
        const msgTs = new Array(msgs.length).fill(null);
        for (let j = 0; j < msgs.length; j++) {{
          const m = msgs[j];
          if (m.role === "tool") {{
            const meta = toolMeta.get(m.tool_call_id || "");
            if (meta) msgTs[j] = addSeconds(meta.startTs, meta.durationS);
          }} else if (m.role === "assistant" && Array.isArray(m.tool_calls) && m.tool_calls.length) {{
            const meta = toolMeta.get(m.tool_calls[0].id || "");
            if (meta) msgTs[j] = meta.startTs;
          }}
        }}
        let lastKnown = null;
        for (let j = 0; j < msgs.length; j++) {{
          if (msgTs[j] !== null) lastKnown = msgTs[j];
          else if (lastKnown !== null) msgTs[j] = lastKnown;
        }}
        let nextKnown = null;
        for (let j = msgs.length - 1; j >= 0; j--) {{
          if (msgTs[j] !== null) nextKnown = msgTs[j];
          else if (nextKnown !== null) msgTs[j] = nextKnown;
        }}
        for (let j = 0; j < msgs.length; j++) {{
          if (msgTs[j] === null) msgTs[j] = rec.timestamp || "";
        }}

        // Walk messages in natural (chronological) order so user → asst text
        // → tool_use → tool_result land in the order they happened.
        for (let j = 0; j < msgs.length; j++) {{
          const m = msgs[j];
          const key = stableMsgKey(m);
          if (seenMsg.has(key)) continue;
          seenMsg.add(key);
          const role = String(m.role || "user");
          const ts = msgTs[j];

          if (role === "user") {{
            events.push({{
              id: `t${{i}}-m${{j}}`,
              kind: "user", role: "user", label: "user",
              preview: preview(contentToText(m.content)),
              timestamp: ts,
              iteration: rec.iteration ?? "?",
              turnIndex: i, messageIndex: j,
              scrollTarget: `msg-${{j}}`,
            }});
            continue;
          }}

          if (role === "system") {{
            events.push({{
              id: `t${{i}}-m${{j}}`,
              kind: "system", role: "system", label: "system",
              preview: preview(contentToText(m.content)),
              timestamp: ts,
              iteration: rec.iteration ?? "?",
              turnIndex: i, messageIndex: j,
              scrollTarget: `msg-${{j}}`,
            }});
            continue;
          }}

          if (role === "tool") {{
            const tcid = m.tool_call_id || "";
            const meta = toolMeta.get(tcid);
            events.push({{
              id: `t${{i}}-m${{j}}`,
              kind: "tool_result", role: "tool",
              label: meta ? `tool_result · ${{meta.toolName}}` : "tool_result",
              preview: preview(contentToText(m.content)),
              timestamp: ts,
              iteration: rec.iteration ?? "?",
              turnIndex: i, messageIndex: j,
              scrollTarget: `msg-${{j}}`,
              isError: !!(meta && meta.isError),
            }});
            continue;
          }}

          if (role === "assistant") {{
            const text = typeof m.content === "string" ? m.content : "";
            if (text.trim()) {{
              const k = text.slice(0, 400);
              if (!seenAsstText.has(k)) {{
                seenAsstText.add(k);
                events.push({{
                  id: `t${{i}}-m${{j}}-text`,
                  kind: "assistant", role: "assistant", label: "assistant",
                  preview: preview(text),
                  timestamp: ts,
                  iteration: rec.iteration ?? "?",
                  turnIndex: i, messageIndex: j,
                  scrollTarget: `msg-${{j}}`,
                }});
              }}
            }}
            const tcs = Array.isArray(m.tool_calls) ? m.tool_calls : [];
            for (let k = 0; k < tcs.length; k++) {{
              const tc = tcs[k];
              const tcid = tc.id || tc.tool_use_id || "";
              if (tcid && seenToolUse.has(tcid)) continue;
              if (tcid) seenToolUse.add(tcid);
              const meta = toolMeta.get(tcid);
              const name = (tc.function && tc.function.name) || (meta && meta.toolName) || tc.tool_name || "?";
              let argsObj = {{}};
              try {{
                const raw = (tc.function && tc.function.arguments) || tc.tool_input || tc.input || {{}};
                argsObj = typeof raw === "string" ? JSON.parse(raw) : raw;
              }} catch {{}}
              events.push({{
                id: `t${{i}}-m${{j}}-tc${{k}}`,
                kind: "tool_use", role: "assistant",
                label: `tool_use · ${{name}}`,
                preview: preview(JSON.stringify(argsObj)),
                timestamp: meta ? meta.startTs : ts,
                iteration: rec.iteration ?? "?",
                turnIndex: i, messageIndex: j,
                scrollTarget: `msg-${{j}}`,
                toolName: name,
                isError: !!(meta && meta.isError),
              }});
            }}
          }}
        }}

        // The FINAL LLM response of this turn is captured separately in
        // rec.assistant_text + rec.tool_calls; it only enters `messages` on
        // the NEXT turn. Emit it now so it anchors to the correct turn.
        const at = String(rec.assistant_text || "").trim();
        if (at) {{
          const k = at.slice(0, 400);
          if (!seenAsstText.has(k)) {{
            seenAsstText.add(k);
            events.push({{
              id: `t${{i}}-asst`,
              kind: "assistant", role: "assistant", label: "assistant",
              preview: preview(at),
              timestamp: rec.timestamp || "",
              iteration: rec.iteration ?? "?",
              turnIndex: i, messageIndex: -1,
              scrollTarget: "assistant-text",
            }});
          }}
        }}
        for (const tc of (rec.tool_calls || [])) {{
          const tcid = tc.tool_use_id || tc.id || "";
          if (tcid && seenToolUse.has(tcid)) continue;
          if (tcid) seenToolUse.add(tcid);
          const name = tc.tool_name || (tc.function && tc.function.name) || "?";
          let inputPreview = "";
          try {{ inputPreview = preview(JSON.stringify(tc.tool_input || tc.input || {{}})); }} catch {{}}
          events.push({{
            id: `t${{i}}-tc-${{tcid || Math.random()}}`,
            kind: "tool_use", role: "assistant",
            label: `tool_use · ${{name}}`,
            preview: inputPreview,
            timestamp: tc.start_timestamp || rec.timestamp || "",
            iteration: rec.iteration ?? "?",
            turnIndex: i, messageIndex: -1,
            scrollTarget: "assistant-text",
            toolName: name,
            isError: !!tc.is_error,
          }});
        }}
      }}

      // No cross-turn sort: messages are appended chronologically by the
      // framework, dedup anchors each item to its first appearance, and
      // tool_use events get their real start_timestamp directly. Sorting on
      // mixed real/inferred timestamps risks reordering across turns where
      // the inferred timestamps aren't reliable enough to trust.
      return events;
    }}

    function renderTimeline() {{
      const head = $("timelineHead");
      head.textContent = `Timeline${{activeRecords.length ? ` · ${{activeRecords.length}} turns · ${{activeEvents.length}} events` : ""}}`;
      const filter = $("kindFilter").value;
      const html = activeEvents.filter((e) => !filter || e.kind === filter).map((e) => {{
        const errBadge = e.isError ? `<span class="badge err">err</span>` : "";
        return `<div class="ev kind-${{e.kind}} ${{activeEventId === e.id ? "active" : ""}}" data-evid="${{escapeHtml(e.id)}}">
          <div class="row">
            <span class="badge kind-${{e.kind}}">${{escapeHtml(e.label)}}</span>
            ${{errBadge}}
            <span class="iter">iter ${{escapeHtml(e.iteration)}}</span>
            <span class="ts">${{escapeHtml(shortTime(e.timestamp))}}</span>
          </div>
          ${{e.preview ? `<div class="preview">${{escapeHtml(e.preview)}}</div>` : ""}}
        </div>`;
      }}).join("") || '<div class="empty">No events for this filter.</div>';
      $("timeline").innerHTML = html;
    }}

    function renderRaw(event) {{
      if (!event) {{
        $("raw").innerHTML = '<div class="empty">Select an event.</div>';
        return;
      }}
      const rec = activeRecords[event.turnIndex];
      if (!rec) {{
        $("raw").innerHTML = '<div class="empty">Record not found.</div>';
        return;
      }}
      const tc = rec.token_counts || {{}};
      const messages = Array.isArray(rec.messages) ? rec.messages : [];
      const tools = Array.isArray(rec.tools) ? rec.tools : [];
      const toolsMissing = !rec.tools;
      const sys = String(rec.system_prompt || "");
      const ast = String(rec.assistant_text || "");
      const tcs = Array.isArray(rec.tool_calls) ? rec.tool_calls : [];

      const head = `
        <div class="head">
          <span class="chip">turn ${{event.turnIndex + 1}}/${{activeRecords.length}}</span>
          <span class="chip">iter ${{escapeHtml(rec.iteration ?? "?")}}</span>
          <span class="chip">${{escapeHtml(rec.timestamp || "")}}</span>
          <span class="chip">node=${{escapeHtml(rec.node_id || "-")}}</span>
          <span class="chip">model=${{escapeHtml(tc.model || "-")}}</span>
          <span class="chip">in=${{escapeHtml(tc.input ?? "-")}} out=${{escapeHtml(tc.output ?? "-")}}</span>
          <span class="chip">stop=${{escapeHtml(tc.stop_reason || "-")}}</span>
        </div>`;

      // Messages section: highlight the message this event refers to (if any).
      // Use the SAME semantic labels the timeline uses — an assistant message
      // with tool_calls is a tool_use, a `tool` role message is a tool_result.
      // Render each message's BODY in the most informative way for its kind:
      //   - user / system / asst-text: show content as plain text (wrapping
      //     it in a JSON envelope obscures readable prose)
      //   - assistant tool_calls: show the tool_calls array (content is null)
      //   - tool result: show content (tool_call_id is already in the badge)
      const msgHtml = messages.map((m, idx) => {{
        const hl = idx === event.messageIndex ? " hl-msg scroll-target" : "";
        const role = String(m.role || "?");
        let kind = role === "tool" ? "tool_result"
                 : role === "assistant" ? "assistant"
                 : role === "system" ? "system" : "user";
        let label = role;
        let bodyHtml = "";
        if (role === "assistant" && Array.isArray(m.tool_calls) && m.tool_calls.length) {{
          kind = "tool_use";
          const names = m.tool_calls
            .map((tc) => (tc.function && tc.function.name) || tc.tool_name || "?")
            .join(", ");
          label = `tool_use · ${{names}}`;
          bodyHtml = `<pre class="json">${{escapeHtml(JSON.stringify(m.tool_calls, null, 2))}}</pre>`;
          if (typeof m.content === "string" && m.content.trim()) {{
            // Rare but possible: assistant message with both text + tool_calls.
            bodyHtml = `<pre class="text">${{escapeHtml(m.content)}}</pre>` + bodyHtml;
          }}
        }} else if (role === "tool") {{
          const meta = activeToolMeta.get(m.tool_call_id || "");
          label = meta ? `tool_result · ${{meta.toolName}}` : "tool_result";
          const c = m.content;
          bodyHtml = typeof c === "string"
            ? `<pre class="text">${{escapeHtml(c)}}</pre>`
            : `<pre class="json">${{escapeHtml(JSON.stringify(c, null, 2))}}</pre>`;
        }} else {{
          const c = m.content;
          bodyHtml = typeof c === "string"
            ? `<pre class="text">${{escapeHtml(c)}}</pre>`
            : `<pre class="json">${{escapeHtml(JSON.stringify(c, null, 2))}}</pre>`;
        }}
        return `<div class="msg${{hl}}" id="msg-${{idx}}">
          <div class="msg-head">
            <span class="badge kind-${{kind}}">${{escapeHtml(label)}}</span>
            <span class="iter">[${{idx}}]</span>
          </div>
          ${{bodyHtml}}
        </div>`;
      }}).join("") || '<div class="empty">No messages.</div>';

      // Tool calls section (the assistant's outputs from this turn).
      const tcsHtml = tcs.map((c, k) => {{
        const hl = event.scrollTarget === `tool-call-${{k}}` ? " hl-msg scroll-target" : "";
        const name = c.tool_name || (c.function && c.function.name) || "?";
        return `<div class="msg${{hl}}" id="tool-call-${{k}}">
          <div class="msg-head">
            <span class="badge kind-tool_use">tool_use</span>
            <span class="iter">${{escapeHtml(name)}}</span>
            ${{c.is_error ? '<span class="badge err">err</span>' : ""}}
          </div>
          <pre class="json">${{escapeHtml(JSON.stringify(c, null, 2))}}</pre>
        </div>`;
      }}).join("");

      const astHl = event.scrollTarget === "assistant-text" ? " hl-msg scroll-target" : "";
      const astHtml = ast ? `<div class="msg${{astHl}}" id="assistant-text">
          <div class="msg-head"><span class="badge kind-assistant">assistant text</span></div>
          <pre class="text">${{escapeHtml(ast)}}</pre>
        </div>` : "";

      const toolsNotice = toolsMissing
        ? '<div class="empty" style="margin:8px 0;">Tool schemas were not captured for this turn. Re-run the agent with the updated logger to populate this section.</div>'
        : "";

      $("raw").innerHTML = `
        ${{head}}
        <section>
          <h3>System prompt</h3>
          <details ${{sys.length < 4000 ? "open" : ""}}><summary>${{sys.length}} chars</summary>
            <pre class="text">${{escapeHtml(sys)}}</pre>
          </details>
        </section>
        <section>
          <h3>Tools (${{tools.length}})</h3>
          ${{toolsNotice}}
          ${{tools.length ? `<details><summary>show tool schemas</summary>
            <pre class="json">${{escapeHtml(JSON.stringify(tools, null, 2))}}</pre>
          </details>` : ""}}
        </section>
        <section>
          <h3>Messages sent to LLM (${{messages.length}})</h3>
          ${{msgHtml}}
        </section>
        ${{ast || tcs.length ? `<section>
          <h3>Assistant response from this turn</h3>
          ${{astHtml}}
          ${{tcsHtml}}
        </section>` : ""}}
      `;

      // Scroll to the highlighted target so the developer immediately sees it.
      requestAnimationFrame(() => {{
        const target = document.querySelector(".raw .scroll-target");
        if (target) target.scrollIntoView({{ behavior: "smooth", block: "start" }});
      }});
    }}

    async function loadSession(sid) {{
      activeSessionId = sid;
      activeEventId = null;
      renderSessions();
      $("timelineHead").textContent = "Timeline · loading…";
      $("timeline").innerHTML = '<div class="empty">Loading…</div>';
      let records = recordCache[sid];
      if (!records) {{
        const resp = await fetch(`/api/session/${{encodeURIComponent(sid)}}`);
        records = resp.ok ? await resp.json() : [];
        recordCache[sid] = records;
      }}
      if (activeSessionId !== sid) return;
      activeRecords = records || [];
      activeToolMeta = buildToolMeta(activeRecords);
      activeEvents = buildEvents(activeRecords, activeToolMeta);
      renderTimeline();
      $("raw").innerHTML = '<div class="empty">Click any event on the left to view the raw request payload.</div>';
      history.replaceState(null, "", `#${{encodeURIComponent(sid)}}`);
    }}

    $("sessionList").addEventListener("click", (e) => {{
      const card = e.target.closest(".session");
      if (card) loadSession(card.dataset.sid);
    }});
    $("sessionSearch").addEventListener("input", renderSessions);
    $("kindFilter").addEventListener("change", renderTimeline);
    $("timeline").addEventListener("click", (e) => {{
      const evEl = e.target.closest(".ev");
      if (!evEl) return;
      activeEventId = evEl.dataset.evid;
      const ev = activeEvents.find((x) => x.id === activeEventId);
      renderTimeline();
      renderRaw(ev);
    }});

    renderSessions();
    const hashSid = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    const known = new Set(summaries.map((s) => s.execution_id));
    const boot = known.has(hashSid) ? hashSid : activeSessionId;
    if (boot) loadSession(boot);
  </script>
</body>
</html>
"""


def _run_server(html: str, logs_dir: Path, limit_files: int, port: int, no_open: bool) -> None:
    html_bytes = html.encode("utf-8")
    cache: dict[str, list[dict[str, Any]]] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/":
                self._respond(200, "text/html; charset=utf-8", html_bytes)
            elif self.path.startswith("/api/session/"):
                sid = urllib.parse.unquote(self.path[len("/api/session/") :])
                records = cache.get(sid)
                if records is None:
                    records = _load_session_data(logs_dir, sid, limit_files)
                    if records is not None:
                        cache[sid] = records
                if records is None:
                    self._respond(404, "application/json", b"[]")
                else:
                    body = json.dumps(records, ensure_ascii=False).encode("utf-8")
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
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"
    print(f"Serving timeline viewer at {url}  (Ctrl+C to stop)")
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
    logs_dir = args.logs_dir.expanduser()
    summaries = _discover_session_summaries(logs_dir, args.limit_files, args.include_tests)
    initial = args.session or (summaries[0].execution_id if summaries else "")
    if initial and not any(s.execution_id == initial for s in summaries):
        print(f"session not found: {initial}")
        return 1
    html = _render_html(summaries, initial)
    _run_server(html, logs_dir, args.limit_files, args.port, args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
