"""Live end-to-end test of the queen → fork → colony flow.

Hits the real LLM via the in-process aiohttp app. Validates that:
  - The queen identity hook fires after queen startup
  - ``handle_colony_spawn`` produces the right artifacts under the actual
    selected queen identity (not "default")
  - The forked queen session dir lives under the correct queen profile
  - The colony's metadata.json picks up the real queen_name

Skipped automatically if no LLM API key is configured.

Costs a few cents per run.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

# ---------------------------------------------------------------------------
# Skip if no live LLM credentials are available
# ---------------------------------------------------------------------------


_LLM_KEY_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "ZAI_API_KEY",
    "OPENROUTER_API_KEY",
    "CEREBRAS_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_AI_API_KEY",
    "MINIMAX_API_KEY",
)


def _has_any_llm_key() -> bool:
    return any(os.environ.get(k) for k in _LLM_KEY_ENV_VARS)


pytestmark = pytest.mark.skipif(
    not _has_any_llm_key(),
    reason="No LLM API key set; skipping live integration test",
)


# ---------------------------------------------------------------------------
# Fixture: isolated ~/.hive in a temp dir
# ---------------------------------------------------------------------------


# Modules that import HIVE_HOME / QUEENS_DIR / COLONIES_DIR / MEMORIES_DIR /
# HIVE_CONFIG_FILE at import time and need their bindings rewritten when we
# redirect ~/.hive to a temp directory.
_HIVE_PATH_CONSUMERS = (
    "framework.config",
    "framework.server.session_manager",
    "framework.server.queen_orchestrator",
    "framework.server.routes_queens",
    "framework.server.app",
    "framework.agents.discovery",
    "framework.agents.queen.queen_profiles",
    "framework.tools.queen_lifecycle_tools",
    "framework.storage.migrate_v2",
    "framework.loader.cli",
)

_HIVE_PATH_NAMES = (
    ("HIVE_HOME", lambda h: h),
    ("QUEENS_DIR", lambda h: h / "agents" / "queens"),
    ("COLONIES_DIR", lambda h: h / "colonies"),
    ("MEMORIES_DIR", lambda h: h / "memories"),
    ("HIVE_CONFIG_FILE", lambda h: h / "configuration.json"),
)


@pytest.fixture
def isolated_hive_home(tmp_path, monkeypatch):
    """Redirect ~/.hive to a temp directory.

    Patches Path.home() AND every module-level binding of HIVE_HOME and
    its derivatives, since those constants were captured at import time
    and won't follow Path.home() changes alone.

    Copies the user's real ~/.hive/configuration.json into the temp home
    so the LLM provider config (model, api_base) is preserved.
    """
    fake_home_root = tmp_path
    fake_hive = fake_home_root / ".hive"
    fake_hive.mkdir()

    # Copy LLM configuration so the framework picks up the user's model.
    # Done BEFORE we monkey-patch Path.home so the source resolves correctly.
    real_config = Path.home() / ".hive" / "configuration.json"
    if real_config.exists():
        shutil.copy(real_config, fake_hive / "configuration.json")

    # Patch Path.home -> tmp_path so any call-site computation goes there.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home_root))

    # Patch every module-level binding that captured a path constant.
    for mod_name in _HIVE_PATH_CONSUMERS:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        for attr_name, builder in _HIVE_PATH_NAMES:
            if hasattr(mod, attr_name):
                monkeypatch.setattr(mod, attr_name, builder(fake_hive))

    yield fake_hive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_queen_identity(
    client: TestClient,
    session_id: str,
    *,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> str:
    """Poll /api/sessions/{id} until queen_id is set to a non-default value.

    Returns the resolved queen_id. Fails the test on timeout.
    """
    deadline = time.time() + timeout
    last_qid: str | None = None
    while time.time() < deadline:
        r = await client.get(f"/api/sessions/{session_id}")
        if r.status == 200:
            d = await r.json()
            qid = d.get("queen_id")
            if qid:
                last_qid = qid
                if qid != "default":
                    return qid
        await asyncio.sleep(poll_interval)
    pytest.fail(
        f"Queen identity not selected within {timeout}s "
        f"(last queen_id={last_qid!r}). The queen identity hook may not be firing."
    )


# ---------------------------------------------------------------------------
# The live test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_queen_fork_to_colony(isolated_hive_home):
    """Spin up a real queen, let her select an identity, fork to a colony.

    Validates the full wiring against a live LLM:
      1. Queen-only session starts and runs the identity hook
      2. session.queen_dir gets relocated from default/ to the selected queen
      3. handle_colony_spawn produces metadata pointing at the real queen
      4. The forked queen session dir lives under the correct queen identity
      5. Conversations are copied through to worker storage
    """
    from framework.agents.queen.queen_profiles import ensure_default_queens
    from framework.server.app import create_app
    from framework.server.session_manager import _queen_session_dir

    # Pre-populate queen profiles in the temp ~/.hive so the identity
    # hook has something to choose from.
    ensure_default_queens()

    app = create_app()  # picks up model from copied configuration.json
    manager = app["manager"]

    async with TestClient(TestServer(app)) as client:
        # ── 1. Create a queen-only session ─────────────────────────
        # The initial_prompt steers the identity hook toward a finance queen.
        resp = await client.post(
            "/api/sessions",
            json={
                "initial_prompt": (
                    "I want to incubate a finance colony to help me trade "
                    "carefully on a small honeycomb market. Just briefly "
                    "acknowledge — one sentence is fine."
                ),
            },
        )
        assert resp.status == 201, await resp.text()
        body = await resp.json()
        session_id = body["session_id"]
        assert session_id.startswith("session_")

        # ── 2. Wait for queen identity hook to fire ────────────────
        queen_name = await _wait_for_queen_identity(client, session_id)
        assert queen_name != "default", f"Identity hook didn't pick a real queen, got {queen_name!r}"

        # ── 3. Fork to a colony ────────────────────────────────────
        colony_name = "live_test_honeycomb"
        resp = await client.post(
            f"/api/sessions/{session_id}/colony-spawn",
            json={"colony_name": colony_name, "task": "trade carefully"},
        )
        assert resp.status == 200, await resp.text()
        spawn_data = await resp.json()
        colony_session_id = spawn_data["queen_session_id"]
        assert spawn_data["colony_name"] == colony_name
        assert spawn_data["is_new"] is True
        assert colony_session_id != session_id

        # ── 4. Validate on-disk artifacts ──────────────────────────
        colony_dir = isolated_hive_home / "colonies" / colony_name
        assert colony_dir.is_dir()
        assert (colony_dir / "worker.json").is_file()
        assert (colony_dir / "metadata.json").is_file()

        metadata = json.loads((colony_dir / "metadata.json").read_text())
        assert metadata["colony_name"] == colony_name
        # The crucial assertion: the metadata's queen_name must be the
        # auto-selected queen, not "default". This is what failed
        # repeatedly yesterday before the queen-dir relocate fix.
        assert metadata["queen_name"] == queen_name, (
            f"metadata.queen_name should be {queen_name!r}, got "
            f"{metadata['queen_name']!r}. The session-dir relocation in "
            f"queen_orchestrator may not be firing."
        )
        assert metadata["queen_session_id"] == colony_session_id
        assert metadata["source_session_id"] == session_id

        worker_meta = json.loads((colony_dir / "worker.json").read_text())
        assert worker_meta["queen_id"] == queen_name
        assert worker_meta["spawned_from"] == session_id
        # The queen always has at least the framework-default tools
        assert len(worker_meta["tools"]) > 0
        # Goal carries the task we passed in
        assert worker_meta["goal"]["description"] == "trade carefully"

        # ── 5. Validate the forked queen session dir ──────────────
        # It must live under the SELECTED queen identity, not "default".
        dest_queen_dir = _queen_session_dir(colony_session_id, queen_name)
        assert dest_queen_dir.is_dir(), f"Forked session dir not under {queen_name}/, expected {dest_queen_dir}"
        # Conversations from the original queen session were copied
        assert (dest_queen_dir / "conversations").is_dir()

        dest_meta = json.loads((dest_queen_dir / "meta.json").read_text())
        assert dest_meta["colony_fork"] is True
        assert dest_meta["queen_id"] == queen_name
        assert dest_meta["forked_from"] == session_id
        assert dest_meta["agent_path"] == str(colony_dir)

        # ── 6. The forked session must NOT show up in the queen DM history.
        from framework.server.session_manager import SessionManager

        cold = SessionManager.list_cold_sessions()
        forked_in_history = [s for s in cold if s.get("session_id") == colony_session_id]
        assert not forked_in_history, f"Forked colony session leaked into queen DM history: {forked_in_history}"

        # ── 7. Worker storage received the conversations ──────────
        worker_storage_convs = isolated_hive_home / "agents" / colony_name / "worker" / "conversations"
        assert worker_storage_convs.is_dir()
        # The queen has had at least one turn (the initial_prompt acknowledgment),
        # so there should be conversation parts.
        parts_dir = worker_storage_convs / "parts"
        if parts_dir.exists():
            assert any(parts_dir.iterdir()), "worker storage has conversations dir but no parts"

        # ── 8. Stop the live session cleanly ──────────────────────
        resp = await client.delete(f"/api/sessions/{session_id}")
        assert resp.status == 200

        # Drain background queen task so pytest doesn't warn about
        # never-awaited coroutines.
        await manager.shutdown_all()
