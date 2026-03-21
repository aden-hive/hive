"""
Simple API server for the Hive Dashboard.
Serves the frontend static files and provides endpoints to interact with agents.

Run with:
    cd hive && python frontend/server.py
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
import threading

FRONTEND_DIR = Path(__file__).parent
HIVE_DIR = FRONTEND_DIR.parent
PYTHON = str(HIVE_DIR / ".venv" / "bin" / "python")
PYTHONPATH = f"{HIVE_DIR / 'exports'}:{HIVE_DIR / 'core'}"

# In-memory task store: {task_id: {status, topic, output, error}}
tasks = {}
tasks_lock = threading.Lock()


def run_blog_writer(task_id: str, topic: str):
    """Run the blog writer agent in a subprocess and update task state."""
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH

    try:
        result = subprocess.run(
            [PYTHON, "-m", "blog_writer", "run", "--topic", topic, "--quiet"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(HIVE_DIR),
            timeout=300,
        )

        with tasks_lock:
            if result.returncode == 0:
                try:
                    output = json.loads(result.stdout)
                except json.JSONDecodeError:
                    output = {"raw": result.stdout}
                tasks[task_id]["status"] = "completed"
                tasks[task_id]["output"] = output
            else:
                tasks[task_id]["status"] = "failed"
                tasks[task_id]["error"] = result.stderr or result.stdout or "Unknown error"
    except subprocess.TimeoutExpired:
        with tasks_lock:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = "Task timed out after 5 minutes"
    except Exception as e:
        with tasks_lock:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e)


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def log_message(self, format, *args):
        # Suppress default request logging
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/tasks/blog":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON"}, status=400)
                return

            topic = data.get("topic", "").strip()
            if not topic:
                self.send_json({"error": "topic is required"}, status=400)
                return

            task_id = str(uuid.uuid4())[:8]
            with tasks_lock:
                tasks[task_id] = {"status": "running", "topic": topic, "output": None, "error": None}

            thread = threading.Thread(target=run_blog_writer, args=(task_id, topic), daemon=True)
            thread.start()

            print(f"[task {task_id}] Started blog writer: {topic!r}", flush=True)
            self.send_json({"task_id": task_id, "status": "running"})
        else:
            self.send_json({"error": "Not found"}, status=404)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path.startswith("/api/tasks/"):
            task_id = parsed.path.split("/api/tasks/")[-1].strip("/")
            with tasks_lock:
                task = tasks.get(task_id)
            if task is None:
                self.send_json({"error": "Task not found"}, status=404)
            else:
                self.send_json({"task_id": task_id, **task})
        elif parsed.path == "/api/tasks":
            with tasks_lock:
                self.send_json({"tasks": {tid: {**t} for tid, t in tasks.items()}})
        elif parsed.path == "/api/posts":
            posts_dir = HIVE_DIR / "blog_posts"
            files = sorted(posts_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True) if posts_dir.exists() else []
            self.send_json({"posts": [f.name for f in files]})
        elif parsed.path.startswith("/api/posts/"):
            filename = parsed.path.split("/api/posts/")[-1].strip("/")
            # Prevent path traversal
            if "/" in filename or "\\" in filename or not filename.endswith(".md"):
                self.send_json({"error": "Invalid filename"}, status=400)
                return
            post_path = HIVE_DIR / "blog_posts" / filename
            if not post_path.exists():
                self.send_json({"error": "Post not found"}, status=404)
            else:
                content = post_path.read_text(encoding="utf-8")
                self.send_json({"filename": filename, "content": content})
        else:
            # Serve static files
            super().do_GET()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("localhost", port), DashboardHandler)
    print(f"Hive Dashboard running at http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
