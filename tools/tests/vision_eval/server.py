"""Vision eval server.

A stdlib-only HTTP server that hosts a set of deliberately challenging
web-interaction tasks and records the outcomes per run. Used to benchmark
a vision-only Hive queen (no DOM access) against a defined set of clicks,
types, and drags.

Layout:

- ``GET /``                  index page; starts a new run, links to each task
- ``GET /task/<name>``       serves ``tasks/<name>.html`` with ``?run=`` propagated
- ``GET /static/<file>``     CSS / JS for the task pages
- ``POST /api/event``        body = {run, task, kind, payload}; appended to JSONL
- ``GET /report``            HTML scoreboard for the most recent (or ?run=) run

Run with:

    uv run python server.py [--port 8765] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
import threading
import time
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
TASKS_DIR = ROOT / "tasks"
STATIC_DIR = ROOT / "static"
RUNS_DIR = ROOT / "runs"

TASK_ORDER = [
    "precision_tiny_button",
    "precision_low_contrast",
    "precision_occluded",
    "disambiguation_duplicates",
    "disambiguation_text_as_image",
    "disambiguation_dropdown",
    "spatial_below_fold",
    "spatial_form_fill",
    "multistep_drag_drop",
    "multistep_tab_handoff",
]

TASK_TITLES = {
    "precision_tiny_button": "Tiny target",
    "precision_low_contrast": "Low contrast",
    "precision_occluded": "Partially occluded",
    "disambiguation_duplicates": "Identical duplicates",
    "disambiguation_text_as_image": "Rasterized labels",
    "disambiguation_dropdown": "Custom dropdown",
    "spatial_below_fold": "Below the fold",
    "spatial_form_fill": "Visual form fill",
    "multistep_drag_drop": "Drag and drop",
    "multistep_tab_handoff": "Cross-tab handoff",
}

TASK_CATEGORY = {
    "precision_tiny_button": "Precision",
    "precision_low_contrast": "Precision",
    "precision_occluded": "Precision",
    "disambiguation_duplicates": "Disambiguation",
    "disambiguation_text_as_image": "Disambiguation",
    "disambiguation_dropdown": "Disambiguation",
    "spatial_below_fold": "Spatial / form",
    "spatial_form_fill": "Spatial / form",
    "multistep_drag_drop": "Multi-step",
    "multistep_tab_handoff": "Multi-step",
}

# In-memory scoreboard: {run_id: {task: {"events": [...], "first_success_ts": float|None, "miss_count": int}}}
_RUNS: dict[str, dict[str, dict[str, Any]]] = {}
_RUNS_LOCK = threading.Lock()
_LATEST_RUN: dict[str, str | None] = {"id": None}

logger = logging.getLogger("vision_eval")


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _ensure_run(run_id: str) -> dict[str, dict[str, Any]]:
    with _RUNS_LOCK:
        if run_id not in _RUNS:
            _RUNS[run_id] = {name: _empty_task_state() for name in TASK_ORDER}
            _LATEST_RUN["id"] = run_id
        return _RUNS[run_id]


def _empty_task_state() -> dict[str, Any]:
    return {
        "events": [],
        "first_success_ts": None,
        "first_view_ts": None,
        "miss_count": 0,
        "pass_count": 0,
    }


def _append_event(run_id: str, task: str, kind: str, payload: dict[str, Any]) -> None:
    state = _ensure_run(run_id)
    if task not in state:
        # Unknown task name — accept it but don't break the run shape.
        state[task] = _empty_task_state()
    ts = time.time()
    entry = {"ts": ts, "task": task, "kind": kind, "payload": payload}
    with _RUNS_LOCK:
        t = state[task]
        t["events"].append(entry)
        if kind == "view" and t["first_view_ts"] is None:
            t["first_view_ts"] = ts
        elif kind == "success":
            t["pass_count"] += 1
            if t["first_success_ts"] is None:
                t["first_success_ts"] = ts
        elif kind == "miss":
            t["miss_count"] += 1
    # Durability: append to runs/<run>.jsonl
    RUNS_DIR.mkdir(exist_ok=True)
    line = json.dumps(entry, separators=(",", ":"))
    with (RUNS_DIR / f"{run_id}.jsonl").open("a") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _read_task_html(name: str) -> str | None:
    # Reject path traversal: only kebab/snake task names allowed.
    if not re.fullmatch(r"[a-z0-9_]+", name):
        return None
    path = TASKS_DIR / f"{name}.html"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _render_index(run_id: str) -> str:
    items = []
    for name in TASK_ORDER:
        title = TASK_TITLES.get(name, name)
        category = TASK_CATEGORY.get(name, "")
        items.append(
            f'<li><a href="/task/{name}?run={run_id}">'
            f'<span class="cat">{html.escape(category)}</span> '
            f'<span class="title">{html.escape(title)}</span> '
            f'<span class="slug">{html.escape(name)}</span></a></li>'
        )
    body = "\n".join(items)
    return f"""<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<title>Vision Eval — Index</title>
<link rel=stylesheet href="/static/style.css">
</head>
<body class="index">
<header>
<h1>Vision evaluation suite</h1>
<p>Run id: <code>{html.escape(run_id)}</code></p>
<p>Complete each task in order. Each page displays the instruction at the top
and a verdict banner under it after you act.
When done, visit <a href="/report?run={run_id}">the report</a>.</p>
</header>
<ol class="tasks">
{body}
</ol>
<footer>
<a href="/report?run={run_id}">View report →</a>
&nbsp;·&nbsp;
<a href="/?new=1">Start a fresh run</a>
</footer>
</body>
</html>
"""


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    mins, secs = divmod(seconds, 60)
    return f"{int(mins)}m {secs:.0f}s"


def _render_report(run_id: str) -> str:
    state = _ensure_run(run_id)
    rows = []
    passes = 0
    total_misses = 0
    for name in TASK_ORDER:
        t = state.get(name, _empty_task_state())
        status = "Pass" if t["pass_count"] > 0 else ("Miss" if t["miss_count"] > 0 else "Not attempted")
        status_class = "pass" if t["pass_count"] > 0 else ("miss" if t["miss_count"] > 0 else "skip")
        if t["pass_count"] > 0:
            passes += 1
        total_misses += t["miss_count"]
        time_to_pass = None
        if t["first_success_ts"] and t["first_view_ts"]:
            time_to_pass = t["first_success_ts"] - t["first_view_ts"]
        rows.append(
            "<tr>"
            f"<td>{html.escape(TASK_CATEGORY.get(name, ''))}</td>"
            f"<td><a href='/task/{name}?run={run_id}'>{html.escape(TASK_TITLES.get(name, name))}</a></td>"
            f"<td class='{status_class}'>{status}</td>"
            f"<td>{t['miss_count']}</td>"
            f"<td>{_format_duration(time_to_pass)}</td>"
            f"<td>{len(t['events'])}</td>"
            "</tr>"
        )
    total = len(TASK_ORDER)
    pct = round(100 * passes / total) if total else 0
    rows_html = "\n".join(rows)
    return f"""<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<title>Vision Eval — Report</title>
<link rel=stylesheet href="/static/style.css">
</head>
<body class="report">
<header>
<h1>Vision evaluation report</h1>
<p>Run id: <code>{html.escape(run_id)}</code></p>
<p class="score">Score: <strong>{passes}/{total}</strong> ({pct}%) · total misses: <strong>{total_misses}</strong></p>
</header>
<table>
<thead>
<tr>
<th>Category</th><th>Task</th><th>Status</th><th>Misses</th><th>Time to pass</th><th>Events</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
<footer>
<a href="/?run={run_id}">← Back to index</a>
&nbsp;·&nbsp;
<a href="/?new=1">Start a fresh run</a>
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "VisionEval/0.1"

    # Reduce log noise (one line per request is enough)
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        logger.info("%s - %s", self.address_string(), fmt % args)

    # -- helpers --

    def _send(self, status: HTTPStatus, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: HTTPStatus, text: str, content_type: str = "text/html; charset=utf-8") -> None:
        self._send(status, text.encode("utf-8"), content_type)

    def _send_json(self, status: HTTPStatus, obj: dict[str, Any]) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.path).query)

    def _path(self) -> str:
        return urlsplit(self.path).path

    # -- routes --

    def do_GET(self) -> None:  # noqa: N802
        path = self._path()
        query = self._query()

        if path == "/":
            # `?new=1` forces a new run id; otherwise reuse latest if present.
            if query.get("new") or _LATEST_RUN["id"] is None or query.get("run"):
                run_id = query.get("run", [None])[0] or _new_run_id()
            else:
                run_id = _LATEST_RUN["id"]
            _ensure_run(run_id)
            self._send_text(HTTPStatus.OK, _render_index(run_id))
            return

        if path == "/report":
            run_id = query.get("run", [None])[0] or _LATEST_RUN["id"] or _new_run_id()
            self._send_text(HTTPStatus.OK, _render_report(run_id))
            return

        if path.startswith("/task/"):
            name = path[len("/task/") :]
            html_body = _read_task_html(name)
            if html_body is None:
                self._send_text(HTTPStatus.NOT_FOUND, f"Unknown task: {html.escape(name)}")
                return
            run_id = query.get("run", [None])[0] or _LATEST_RUN["id"] or _new_run_id()
            _ensure_run(run_id)
            # Inject the run id and task name into the page so instrument.js can pick them up.
            inject = (
                f"<script>window.__EVAL__={{run:{json.dumps(run_id)},task:{json.dumps(name)}}};</script>"
                f'<script src="/static/instrument.js" defer></script>'
                f'<link rel="stylesheet" href="/static/style.css">'
            )
            if "</head>" in html_body:
                html_body = html_body.replace("</head>", inject + "</head>", 1)
            else:
                html_body = inject + html_body
            self._send_text(HTTPStatus.OK, html_body)
            return

        if path.startswith("/static/"):
            name = path[len("/static/") :]
            if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
                self._send_text(HTTPStatus.BAD_REQUEST, "bad name")
                return
            file_path = STATIC_DIR / name
            if not file_path.is_file():
                self._send_text(HTTPStatus.NOT_FOUND, "not found")
                return
            ct = (
                "text/css; charset=utf-8"
                if name.endswith(".css")
                else ("application/javascript" if name.endswith(".js") else "application/octet-stream")
            )
            self._send(HTTPStatus.OK, file_path.read_bytes(), ct)
            return

        self._send_text(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:  # noqa: N802
        path = self._path()
        if path != "/api/event":
            self._send_text(HTTPStatus.NOT_FOUND, "not found")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "bad_json"})
            return
        run_id = str(body.get("run") or _LATEST_RUN["id"] or _new_run_id())
        task = str(body.get("task") or "")
        kind = str(body.get("kind") or "")
        payload = body.get("payload") or {}
        if not task or kind not in {"view", "success", "miss"}:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "bad_event"})
            return
        _append_event(run_id, task, kind, payload if isinstance(payload, dict) else {"value": payload})
        self._send_json(HTTPStatus.OK, {"ok": True, "run": run_id})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Vision evaluation harness server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s %(message)s", level=logging.INFO)
    RUNS_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    logger.info("Listening on http://%s:%s/", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
