"""Tests for POST /api/colonies/import — tar-based colony onboarding.

The handler resolves writes against ``framework.config.COLONIES_DIR``;
every test redirects that into a ``tmp_path`` so we never touch the real
``~/.hive/colonies`` tree.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from framework.server import routes_colonies


def _build_tar(layout: dict[str, bytes | None], *, gzip: bool = True) -> bytes:
    """Build an in-memory tar with the given paths.

    ``layout`` maps archive member names to file contents; passing ``None``
    creates a directory entry instead of a regular file.
    """
    buf = io.BytesIO()
    mode = "w:gz" if gzip else "w"
    with tarfile.open(fileobj=buf, mode=mode) as tf:
        for name, content in layout.items():
            if content is None:
                info = tarfile.TarInfo(name=name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            else:
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                info.mode = 0o644
                tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _build_tar_with_symlink(top: str, link_name: str, link_target: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=top)
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tf.addfile(info)
        sym = tarfile.TarInfo(name=f"{top}/{link_name}")
        sym.type = tarfile.SYMTYPE
        sym.linkname = link_target
        tf.addfile(sym)
    return buf.getvalue()


@pytest.fixture
def colonies_dir(tmp_path, monkeypatch):
    """Redirect COLONIES_DIR into a tmp tree."""
    colonies = tmp_path / "colonies"
    colonies.mkdir()
    monkeypatch.setattr(routes_colonies, "COLONIES_DIR", colonies)
    return colonies


async def _client(app: web.Application) -> TestClient:
    return TestClient(TestServer(app))


def _app() -> web.Application:
    app = web.Application()
    routes_colonies.register_routes(app)
    return app


def _form(file_bytes: bytes, *, filename: str = "colony.tar.gz", **fields: str) -> FormData:
    fd = FormData()
    fd.add_field("file", file_bytes, filename=filename, content_type="application/gzip")
    for k, v in fields.items():
        fd.add_field(k, v)
    return fd


@pytest.mark.asyncio
async def test_happy_path_imports_colony(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "x_daily/": None,
            "x_daily/metadata.json": b'{"colony_id":"x_daily"}',
            "x_daily/scripts/run.sh": b"#!/bin/sh\necho hi\n",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 201, await resp.text()
        body = await resp.json()
    assert body["name"] == "x_daily"
    assert body["files_imported"] == 2
    assert (colonies_dir / "x_daily" / "metadata.json").read_bytes() == b'{"colony_id":"x_daily"}'
    assert (colonies_dir / "x_daily" / "scripts" / "run.sh").exists()


@pytest.mark.asyncio
async def test_name_override(colonies_dir: Path) -> None:
    archive = _build_tar({"x_daily/": None, "x_daily/file.txt": b"hi"})
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive, name="other_name"))
        assert resp.status == 201
        body = await resp.json()
    assert body["name"] == "other_name"
    assert (colonies_dir / "other_name" / "file.txt").read_bytes() == b"hi"
    assert not (colonies_dir / "x_daily").exists()


@pytest.mark.asyncio
async def test_rejects_existing_without_replace_flag(colonies_dir: Path) -> None:
    (colonies_dir / "x_daily").mkdir()
    (colonies_dir / "x_daily" / "old.txt").write_text("preserved")
    archive = _build_tar({"x_daily/": None, "x_daily/new.txt": b"new"})
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 409
    # Original content untouched
    assert (colonies_dir / "x_daily" / "old.txt").read_text() == "preserved"


@pytest.mark.asyncio
async def test_replace_existing_overwrites(colonies_dir: Path) -> None:
    (colonies_dir / "x_daily").mkdir()
    (colonies_dir / "x_daily" / "old.txt").write_text("preserved")
    archive = _build_tar({"x_daily/": None, "x_daily/new.txt": b"new"})
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/colonies/import",
            data=_form(archive, replace_existing="true"),
        )
        assert resp.status == 201, await resp.text()
    assert not (colonies_dir / "x_daily" / "old.txt").exists()
    assert (colonies_dir / "x_daily" / "new.txt").read_text() == "new"


@pytest.mark.asyncio
async def test_rejects_path_traversal(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "x_daily/": None,
            "x_daily/../escape.txt": b"oops",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400
        assert "traversal" in (await resp.json())["error"].lower() or "outside" in (await resp.json())["error"].lower()
    assert not (colonies_dir / "x_daily").exists()
    assert not (colonies_dir.parent / "escape.txt").exists()


@pytest.mark.asyncio
async def test_rejects_absolute_member(colonies_dir: Path) -> None:
    archive = _build_tar({"x_daily/": None, "/etc/passwd": b"oops"})
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400


@pytest.mark.asyncio
async def test_rejects_symlinks(colonies_dir: Path) -> None:
    archive = _build_tar_with_symlink("x_daily", "evil", "/etc/passwd")
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400
        assert "symlink" in (await resp.json())["error"].lower()


@pytest.mark.asyncio
async def test_rejects_multiple_top_level_dirs(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "a/": None,
            "a/x.txt": b"a",
            "b/": None,
            "b/y.txt": b"b",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400
        assert "top-level" in (await resp.json())["error"].lower()


@pytest.mark.asyncio
async def test_rejects_invalid_colony_id(colonies_dir: Path) -> None:
    archive = _build_tar({"Bad-Name/": None, "Bad-Name/x.txt": b"x"})
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400


@pytest.mark.asyncio
async def test_rejects_non_multipart(colonies_dir: Path) -> None:
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=b"not multipart", headers={"Content-Type": "application/octet-stream"})
        assert resp.status == 400


@pytest.mark.asyncio
async def test_rejects_corrupt_tar(colonies_dir: Path) -> None:
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(b"not a real tar"))
        assert resp.status == 400


@pytest.mark.asyncio
async def test_rejects_missing_file_part(colonies_dir: Path) -> None:
    fd = FormData()
    fd.add_field("name", "anything")
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=fd)
        assert resp.status == 400


@pytest.mark.asyncio
async def test_accepts_uncompressed_tar(colonies_dir: Path) -> None:
    archive = _build_tar({"x_daily/": None, "x_daily/file.txt": b"plain"}, gzip=False)
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/colonies/import",
            data=_form(archive, filename="colony.tar"),
        )
        assert resp.status == 201
    assert (colonies_dir / "x_daily" / "file.txt").read_text() == "plain"


# --------------------------------------------------------------------------
# Multi-root tar tests — the desktop's pushColonyToWorkspace ships the colony
# dir + worker conversations + the queen's forked session in one tar so the
# queen has full context on resume. Each recognised top-level prefix unpacks
# into its corresponding HIVE_HOME subtree.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_root_unpacks_three_subtrees(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/metadata.json": b'{"queen_session_id":"session_x"}',
            "colonies/x_daily/data/tracker.db": b"sqlite",
            "agents/x_daily/worker/": None,
            "agents/x_daily/worker/conversations/": None,
            "agents/x_daily/worker/conversations/0001.json": b'{"role":"user"}',
            "agents/x_daily/worker/conversations/0002.json": b'{"role":"assistant"}',
            "agents/queens/queen_alpha/sessions/session_x/": None,
            "agents/queens/queen_alpha/sessions/session_x/queen.json": b'{"id":"x"}',
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 201, await resp.text()
        body = await resp.json()
    # Colony files
    assert (colonies_dir / "x_daily" / "metadata.json").exists()
    assert (colonies_dir / "x_daily" / "data" / "tracker.db").exists()
    # Worker conversations under HIVE_HOME/agents/<colony>/worker/
    hive_home = colonies_dir.parent
    assert (hive_home / "agents" / "x_daily" / "worker" / "conversations" / "0001.json").read_bytes() == b'{"role":"user"}'
    # Queen forked session under HIVE_HOME/agents/queens/<queen>/sessions/<sid>/
    assert (hive_home / "agents" / "queens" / "queen_alpha" / "sessions" / "session_x" / "queen.json").exists()
    # Summary in response
    assert body["name"] == "x_daily"
    assert body["files_imported"] == 5
    by_root = body["by_root"]
    assert by_root["colonies"]["files"] == 2
    assert by_root["agents_worker"]["files"] == 2
    assert by_root["agents_queen"]["files"] == 1


@pytest.mark.asyncio
async def test_multi_root_colonies_only_succeeds(colonies_dir: Path) -> None:
    """The agents/ subtrees are optional — a fresh colony has no history."""
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/metadata.json": b"{}",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 201, await resp.text()
        body = await resp.json()
    assert body["files_imported"] == 1
    assert (colonies_dir / "x_daily" / "metadata.json").read_bytes() == b"{}"


@pytest.mark.asyncio
async def test_multi_root_rejects_missing_colonies_root(colonies_dir: Path) -> None:
    """Worker / queen trees alone aren't valid — every push must include
    the colony dir, otherwise the desktop's intent is unclear and we
    refuse rather than silently leave HIVE_HOME in a half-state."""
    archive = _build_tar(
        {
            "agents/x_daily/worker/": None,
            "agents/x_daily/worker/log.json": b"{}",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400, await resp.text()
        err = (await resp.json())["error"]
        assert "colonies/" in err


@pytest.mark.asyncio
async def test_multi_root_replace_existing_colony(colonies_dir: Path) -> None:
    (colonies_dir / "x_daily").mkdir()
    (colonies_dir / "x_daily" / "old.txt").write_text("preserved")
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/new.txt": b"new",
        }
    )
    # Without flag → 409
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 409
    assert (colonies_dir / "x_daily" / "old.txt").read_text() == "preserved"
    # With flag → wipes + replaces
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/colonies/import",
            data=_form(archive, replace_existing="true"),
        )
        assert resp.status == 201, await resp.text()
    assert not (colonies_dir / "x_daily" / "old.txt").exists()
    assert (colonies_dir / "x_daily" / "new.txt").read_text() == "new"


@pytest.mark.asyncio
async def test_multi_root_rejects_traversal_in_worker_subtree(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "agents/x_daily/worker/": None,
            "agents/x_daily/worker/../escape.txt": b"oops",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400
    hive_home = colonies_dir.parent
    assert not (hive_home / "agents" / "escape.txt").exists()


@pytest.mark.asyncio
async def test_multi_root_rejects_unknown_prefix(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "etc/passwd": b"oops",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        # The unknown root is silently ignored (it doesn't match any
        # recognised prefix); the colony root is required and present, so
        # extraction succeeds and only the colonies subtree lands. We don't
        # write outside HIVE_HOME because the dispatcher only routes to
        # known destinations.
        assert resp.status == 201, await resp.text()
    hive_home = colonies_dir.parent
    assert not (hive_home.parent / "etc" / "passwd").exists()
    assert not (hive_home / "etc" / "passwd").exists()


@pytest.mark.asyncio
async def test_multi_root_rejects_invalid_segment(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "agents/queens/Bad-Queen/sessions/sess_1/": None,
            "agents/queens/Bad-Queen/sessions/sess_1/x.json": b"{}",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400


@pytest.mark.asyncio
async def test_multi_root_overwrites_agents_subtree_in_place(colonies_dir: Path) -> None:
    """Worker/queen subtrees are append-mostly stores — the import handler
    extracts in place without an existence-conflict gate so the desktop can
    re-push from another machine without explicit overwrite."""
    hive_home = colonies_dir.parent
    worker_dir = hive_home / "agents" / "x_daily" / "worker" / "conversations"
    worker_dir.mkdir(parents=True)
    (worker_dir / "0000_old.json").write_text("old")
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "agents/x_daily/worker/": None,
            "agents/x_daily/worker/conversations/": None,
            "agents/x_daily/worker/conversations/0001_new.json": b"new",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/colonies/import",
            data=_form(archive, replace_existing="true"),
        )
        assert resp.status == 201, await resp.text()
    # Old conversation file untouched (extraction is additive on agents/),
    # new one written.
    assert (worker_dir / "0000_old.json").read_text() == "old"
    assert (worker_dir / "0001_new.json").read_text() == "new"


# --------------------------------------------------------------------------
# queens/ + memories/ roots — user-level state a pushed colony depends on
# (queen personas, avatars, agent memories). Overwrite in place; queen
# sessions/ subtrees are never touched.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_root_unpacks_queens_and_memories(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/metadata.json": b"{}",
            "queens/queen_alpha/": None,
            "queens/queen_alpha/profile.yaml": b"name: Alpha\n",
            "queens/queen_alpha/tools.json": b'{"enabled_mcp_tools": null}',
            "queens/queen_alpha/skills/research/SKILL.md": b"# skill",
            "memories/global/note.md": b"---\nname: note\n---\nbody\n",
            "memories/colonies/x_daily/fact.md": b"fact",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 201, await resp.text()
        body = await resp.json()
    hive_home = colonies_dir.parent
    assert (hive_home / "queens" / "queen_alpha" / "profile.yaml").read_bytes() == b"name: Alpha\n"
    assert (hive_home / "queens" / "queen_alpha" / "skills" / "research" / "SKILL.md").exists()
    assert (hive_home / "memories" / "global" / "note.md").exists()
    assert (hive_home / "memories" / "colonies" / "x_daily" / "fact.md").read_text() == "fact"
    assert body["by_root"]["queens"]["files"] == 3
    assert body["by_root"]["memories"]["files"] == 2


@pytest.mark.asyncio
async def test_multi_root_queens_sessions_are_skipped(colonies_dir: Path) -> None:
    """A push must never clobber this host's queen DM history — sessions/
    members in the tar are silently dropped, existing files preserved."""
    hive_home = colonies_dir.parent
    session_dir = hive_home / "queens" / "queen_alpha" / "sessions" / "session_vm"
    session_dir.mkdir(parents=True)
    (session_dir / "events.jsonl").write_text("vm-side")
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "queens/queen_alpha/profile.yaml": b"name: Alpha\n",
            "queens/queen_alpha/sessions/session_vm/events.jsonl": b"pushed",
            "queens/queen_alpha/sessions/session_other/events.jsonl": b"pushed",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 201, await resp.text()
        body = await resp.json()
    assert (session_dir / "events.jsonl").read_text() == "vm-side"
    assert not (hive_home / "queens" / "queen_alpha" / "sessions" / "session_other").exists()
    assert body["by_root"]["queens"]["files"] == 1  # profile.yaml only


@pytest.mark.asyncio
async def test_multi_root_queens_overwrite_in_place(colonies_dir: Path) -> None:
    """Unlike colonies/, the queens root is never wholesale-replaced — files
    not present in the tar survive."""
    hive_home = colonies_dir.parent
    queen_dir = hive_home / "queens" / "queen_alpha"
    queen_dir.mkdir(parents=True)
    (queen_dir / "profile.yaml").write_text("name: Old\n")
    (queen_dir / "untouched.json").write_text("keep")
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "queens/queen_alpha/profile.yaml": b"name: New\n",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 201, await resp.text()
    assert (queen_dir / "profile.yaml").read_text() == "name: New\n"
    assert (queen_dir / "untouched.json").read_text() == "keep"


@pytest.mark.asyncio
async def test_multi_root_avatar_replaces_stale_extension(colonies_dir: Path) -> None:
    hive_home = colonies_dir.parent
    queen_dir = hive_home / "queens" / "queen_alpha"
    queen_dir.mkdir(parents=True)
    (queen_dir / "avatar.png").write_bytes(b"old-png")
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "queens/queen_alpha/avatar.jpg": b"new-jpg",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 201, await resp.text()
    assert not (queen_dir / "avatar.png").exists()
    assert (queen_dir / "avatar.jpg").read_bytes() == b"new-jpg"


@pytest.mark.asyncio
async def test_multi_root_rejects_invalid_queen_id(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "queens/Bad-Queen/profile.yaml": b"name: x\n",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400


@pytest.mark.asyncio
async def test_multi_root_rejects_traversal_in_memories(colonies_dir: Path) -> None:
    archive = _build_tar(
        {
            "colonies/x_daily/": None,
            "colonies/x_daily/m.json": b"{}",
            "memories/../escape.md": b"oops",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 400
    hive_home = colonies_dir.parent
    assert not (hive_home / "escape.md").exists()


# --------------------------------------------------------------------------
# Streaming upload tests — the handler must NOT buffer the whole tar in
# memory (the prior implementation did, capping uploads at 100 MiB).
# Streaming to a tempfile lets us raise the cap to a disk-bound value and
# fail soft on truly-runaway uploads via 413 rather than process OOM.
# --------------------------------------------------------------------------


def _build_padded_tar(top: str, payload: bytes) -> bytes:
    """Build an uncompressed tar whose only file payload is ``payload``.

    Uncompressed so test wall-time stays low even for multi-MB payloads
    (we don't want the test fixture to itself become a gzip benchmark).
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(name=top)
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tf.addfile(info)
        info = tarfile.TarInfo(name=f"{top}/big.bin")
        info.size = len(payload)
        info.mode = 0o644
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_above_legacy_100mb_cap_succeeds(colonies_dir: Path, monkeypatch) -> None:
    """The handler used to cap at 100 MiB because it buffered everything in
    `io.BytesIO`. After the streaming rewrite the cap is disk-bound (2 GiB
    default), so a payload that would have failed the old cap must now
    succeed. We monkeypatch the cap up high enough for the streaming
    machinery to be the only check, then ship a 150 MiB tar.
    """
    monkeypatch.setattr(routes_colonies, "_MAX_UPLOAD_BYTES", 2 * 1024 * 1024 * 1024)
    payload = b"\0" * (150 * 1024 * 1024)
    archive = _build_padded_tar("big_colony", payload)
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/colonies/import",
            data=_form(archive, filename="big_colony.tar"),
        )
        assert resp.status == 201, await resp.text()
    extracted = (colonies_dir / "big_colony" / "big.bin").read_bytes()
    assert len(extracted) == len(payload)


@pytest.mark.asyncio
async def test_upload_over_cap_returns_413(colonies_dir: Path, monkeypatch) -> None:
    """Set the cap to something small (1 MiB) and ship more than that.
    The streaming reader must fail-fast with 413 — without writing the
    whole payload to disk first. We don't directly assert the temp file
    was unlinked (filesystem invariants are flaky on tmpfs/aufs), but
    the 413 contract is what the desktop relies on for error surfacing.
    """
    monkeypatch.setattr(routes_colonies, "_MAX_UPLOAD_BYTES", 1024 * 1024)  # 1 MiB
    payload = b"\0" * (2 * 1024 * 1024)
    archive = _build_padded_tar("big_colony", payload)
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/colonies/import",
            data=_form(archive, filename="big_colony.tar"),
        )
        assert resp.status == 413
        body = await resp.json()
        assert "exceeds" in body["error"]
    # Colony must NOT have been created from a partial extraction.
    assert not (colonies_dir / "big_colony").exists()


# ---------------------------------------------------------------------------
# Chunked resumable upload — /api/colonies/import/{init,chunk,status,finalize}
# ---------------------------------------------------------------------------


import hashlib  # noqa: E402
import json  # noqa: E402


def _staging_pointed_at(tmp_path: Path, monkeypatch) -> Path:
    """Redirect the module's upload-staging dir into ``tmp_path`` so tests
    don't share filesystem state through /tmp. Returns the redirected path."""
    staging = tmp_path / "uploads"
    monkeypatch.setattr(routes_colonies, "_UPLOAD_STAGING_DIR", staging)
    return staging


@pytest.mark.asyncio
async def test_chunked_upload_happy_path(colonies_dir: Path, tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    archive = _build_tar(
        {
            "x_daily/": None,
            "x_daily/metadata.json": b'{"colony_id":"x_daily"}',
            "x_daily/file.txt": b"chunked",
        }
    )
    sha = hashlib.sha256(archive).hexdigest()
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={
                "filename": "x_daily.tar.gz",
                "total_bytes": len(archive),
                "sha256": sha,
                "replace_existing": True,
            },
        )
        assert init.status == 201, await init.text()
        upload_id = (await init.json())["upload_id"]

        # Split into 3 arbitrary chunks to exercise offset math.
        cuts = [len(archive) // 3, (2 * len(archive)) // 3, len(archive)]
        offset = 0
        for end in cuts:
            chunk = archive[offset:end]
            resp = await c.put(
                f"/api/colonies/import/chunk/{upload_id}",
                params={"offset": str(offset)},
                data=chunk,
                headers={"content-type": "application/octet-stream"},
            )
            assert resp.status == 200, await resp.text()
            assert (await resp.json())["received"] == end
            offset = end

        status = await c.get(f"/api/colonies/import/status/{upload_id}")
        assert (await status.json())["received"] == len(archive)

        final = await c.post(f"/api/colonies/import/finalize/{upload_id}")
        assert final.status == 201, await final.text()

    assert (colonies_dir / "x_daily" / "metadata.json").exists()
    assert (colonies_dir / "x_daily" / "file.txt").read_bytes() == b"chunked"


@pytest.mark.asyncio
async def test_chunked_upload_sha256_mismatch_400(colonies_dir: Path, tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    archive = _build_tar({"x_daily/": None, "x_daily/x.txt": b"real"})
    wrong_sha = "0" * 64
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={
                "filename": "x.tar.gz",
                "total_bytes": len(archive),
                "sha256": wrong_sha,
                "replace_existing": True,
            },
        )
        upload_id = (await init.json())["upload_id"]
        resp = await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": "0"},
            data=archive,
            headers={"content-type": "application/octet-stream"},
        )
        assert resp.status == 200
        final = await c.post(f"/api/colonies/import/finalize/{upload_id}")
        assert final.status == 400
        body = await final.json()
        assert body["error"] == "sha256 mismatch"


@pytest.mark.asyncio
async def test_chunked_upload_offset_mismatch_409_then_resync(colonies_dir: Path, tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    archive = _build_tar({"x_daily/": None, "x_daily/x.txt": b"resync"})
    sha = hashlib.sha256(archive).hexdigest()
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": len(archive), "sha256": sha, "replace_existing": True},
        )
        upload_id = (await init.json())["upload_id"]

        # First half lands.
        half = len(archive) // 2
        r1 = await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": "0"},
            data=archive[:half],
            headers={"content-type": "application/octet-stream"},
        )
        assert r1.status == 200

        # Client wrongly thinks it still needs to send from offset 0 (e.g.
        # after a client-side crash) — server rejects with 409.
        r2 = await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": "0"},
            data=archive[:half],
            headers={"content-type": "application/octet-stream"},
        )
        assert r2.status == 409
        body = await r2.json()
        assert body["received"] == half

        # Client resyncs via /status, then sends the correct remainder.
        s = await c.get(f"/api/colonies/import/status/{upload_id}")
        received = (await s.json())["received"]
        r3 = await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": str(received)},
            data=archive[received:],
            headers={"content-type": "application/octet-stream"},
        )
        assert r3.status == 200

        final = await c.post(f"/api/colonies/import/finalize/{upload_id}")
        assert final.status == 201, await final.text()


@pytest.mark.asyncio
async def test_chunked_upload_overflow_413(colonies_dir: Path, tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 100, "sha256": "a" * 64, "replace_existing": True},
        )
        upload_id = (await init.json())["upload_id"]
        # Ship 200 bytes even though total is 100 — should 413 without
        # touching the staging file's size.
        resp = await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": "0"},
            data=b"x" * 200,
            headers={"content-type": "application/octet-stream"},
        )
        assert resp.status == 413
        # Meta must still say received=0 so the client's next /status
        # returns the honest zero.
        s = await c.get(f"/api/colonies/import/status/{upload_id}")
        assert (await s.json())["received"] == 0


@pytest.mark.asyncio
async def test_chunked_upload_finalize_incomplete_409(colonies_dir: Path, tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    archive = _build_tar({"x_daily/": None, "x_daily/x.txt": b"partial"})
    sha = hashlib.sha256(archive).hexdigest()
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": len(archive), "sha256": sha, "replace_existing": True},
        )
        upload_id = (await init.json())["upload_id"]
        half = len(archive) // 2
        await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": "0"},
            data=archive[:half],
            headers={"content-type": "application/octet-stream"},
        )
        resp = await c.post(f"/api/colonies/import/finalize/{upload_id}")
        assert resp.status == 409


@pytest.mark.asyncio
async def test_chunked_upload_delete_is_idempotent(tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 10, "sha256": "b" * 64, "replace_existing": False},
        )
        upload_id = (await init.json())["upload_id"]
        r1 = await c.delete(f"/api/colonies/import/{upload_id}")
        assert r1.status == 204
        r2 = await c.delete(f"/api/colonies/import/{upload_id}")
        assert r2.status == 204


@pytest.mark.asyncio
async def test_chunked_upload_unknown_id_404(tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    async with await _client(_app()) as c:
        s = await c.get("/api/colonies/import/status/deadbeefdeadbeef")
        assert s.status == 404
        r = await c.put(
            "/api/colonies/import/chunk/deadbeefdeadbeef",
            params={"offset": "0"},
            data=b"x",
            headers={"content-type": "application/octet-stream"},
        )
        assert r.status == 404
        f = await c.post("/api/colonies/import/finalize/deadbeefdeadbeef")
        assert f.status == 404


@pytest.mark.asyncio
async def test_chunked_upload_init_rejects_oversize_413(tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    monkeypatch.setattr(routes_colonies, "_MAX_UPLOAD_BYTES", 1024)
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 4096, "sha256": "c" * 64, "replace_existing": False},
        )
        assert resp.status == 413


@pytest.mark.asyncio
async def test_chunked_upload_invalid_id_400(tmp_path, monkeypatch) -> None:
    _staging_pointed_at(tmp_path, monkeypatch)
    async with await _client(_app()) as c:
        s = await c.get("/api/colonies/import/status/notavalidid")
        assert s.status == 400
        r = await c.put(
            "/api/colonies/import/chunk/notavalidid",
            params={"offset": "0"},
            data=b"x",
            headers={"content-type": "application/octet-stream"},
        )
        assert r.status == 400


@pytest.mark.asyncio
async def test_gc_of_stale_uploads(tmp_path, monkeypatch) -> None:
    """A meta file older than TTL should be swept on the next /init."""
    staging = _staging_pointed_at(tmp_path, monkeypatch)
    staging.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(routes_colonies, "_UPLOAD_TTL_SECONDS", 1)
    stale_id = "0" * 16
    (staging / f"{stale_id}.data").write_bytes(b"junk")
    (staging / f"{stale_id}.meta.json").write_text(json.dumps({"created_at": 0, "total_bytes": 4, "received_bytes": 4, "sha256": "d" * 64}))
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 8, "sha256": "e" * 64, "replace_existing": False},
        )
        assert init.status == 201
    assert not (staging / f"{stale_id}.data").exists()
    assert not (staging / f"{stale_id}.meta.json").exists()


@pytest.mark.asyncio
async def test_gc_sweeps_orphan_data_file(tmp_path, monkeypatch) -> None:
    """A .data file with no matching .meta.json is a leak fingerprint —
    normally caused by /init crashing between the meta write and the data
    touch. GC should reap it on the next /init sweep."""
    staging = _staging_pointed_at(tmp_path, monkeypatch)
    staging.mkdir(parents=True, exist_ok=True)
    orphan = staging / f"{'a' * 16}.data"
    orphan.write_bytes(b"junk")
    assert orphan.exists()
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 8, "sha256": "f" * 64, "replace_existing": False},
        )
        assert init.status == 201
    assert not orphan.exists()


@pytest.mark.asyncio
async def test_chunked_upload_truncates_torn_file_before_append(colonies_dir: Path, tmp_path, monkeypatch) -> None:
    """Simulates a prior chunk PUT where the data write + fsync landed but
    _write_upload_meta failed after. The on-disk file is longer than
    meta.received_bytes. The next PUT must realign by truncating to
    meta.received_bytes before appending, so the final sha256 matches."""
    staging = _staging_pointed_at(tmp_path, monkeypatch)
    archive = _build_tar({"x_daily/": None, "x_daily/x.txt": b"realign"})
    sha = hashlib.sha256(archive).hexdigest()
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": len(archive), "sha256": sha, "replace_existing": True},
        )
        upload_id = (await init.json())["upload_id"]

        # Send first half normally.
        half = len(archive) // 2
        await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": "0"},
            data=archive[:half],
            headers={"content-type": "application/octet-stream"},
        )

        # Manually corrupt the on-disk file: append garbage past meta.received.
        # This mimics the torn-write hazard (data landed, meta write failed).
        data_path = staging / f"{upload_id}.data"
        with data_path.open("ab") as f:
            f.write(b"\xff" * 4096)
            f.flush()
        assert data_path.stat().st_size == half + 4096

        # Client retries the SECOND half at offset=half — same offset as
        # meta says. Handler must truncate the garbage before appending.
        r = await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": str(half)},
            data=archive[half:],
            headers={"content-type": "application/octet-stream"},
        )
        assert r.status == 200
        assert data_path.stat().st_size == len(archive)

        final = await c.post(f"/api/colonies/import/finalize/{upload_id}")
        assert final.status == 201, await final.text()
    assert (colonies_dir / "x_daily" / "x.txt").read_bytes() == b"realign"


@pytest.mark.asyncio
async def test_chunked_upload_shorter_file_returns_410(tmp_path, monkeypatch) -> None:
    """If somehow the on-disk file is SHORTER than meta.received (unexpected
    external mutation), the handler must refuse rather than silently create
    a zero-padded gap — the client will re-init and start over."""
    staging = _staging_pointed_at(tmp_path, monkeypatch)
    async with await _client(_app()) as c:
        init = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 100, "sha256": "a" * 64, "replace_existing": False},
        )
        upload_id = (await init.json())["upload_id"]

        # Land 50 bytes so meta says received=50.
        await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": "0"},
            data=b"x" * 50,
            headers={"content-type": "application/octet-stream"},
        )
        # Truncate the on-disk file behind the handler's back to 20 bytes.
        data_path = staging / f"{upload_id}.data"
        with data_path.open("r+b") as f:
            f.truncate(20)
        # Next PUT with offset=50 must return 410 — file shorter than meta.
        r = await c.put(
            f"/api/colonies/import/chunk/{upload_id}",
            params={"offset": "50"},
            data=b"y" * 50,
            headers={"content-type": "application/octet-stream"},
        )
        assert r.status == 410


@pytest.mark.asyncio
async def test_concurrent_upload_cap_returns_429(tmp_path, monkeypatch) -> None:
    """Cap on live upload_ids. Once the cap is reached, /init returns 429
    until existing uploads finalize or are cancelled."""
    _staging_pointed_at(tmp_path, monkeypatch)
    monkeypatch.setattr(routes_colonies, "_MAX_CONCURRENT_UPLOADS", 2)
    async with await _client(_app()) as c:
        r1 = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 10, "sha256": "1" * 64, "replace_existing": False},
        )
        assert r1.status == 201
        r2 = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 10, "sha256": "2" * 64, "replace_existing": False},
        )
        assert r2.status == 201
        r3 = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 10, "sha256": "3" * 64, "replace_existing": False},
        )
        assert r3.status == 429
        # After cancelling one, a fresh init succeeds again.
        uid1 = (await r1.json())["upload_id"]
        d = await c.delete(f"/api/colonies/import/{uid1}")
        assert d.status == 204
        r4 = await c.post(
            "/api/colonies/import/init",
            json={"total_bytes": 10, "sha256": "4" * 64, "replace_existing": False},
        )
        assert r4.status == 201


@pytest.mark.asyncio
async def test_staging_dir_is_under_hive_home(tmp_path, monkeypatch) -> None:
    """Regression guard for finding #6: staging must be on the same disk
    as HIVE_HOME, not under tempfile.gettempdir() (which is tmpfs on many
    systemd hosts and would balance 2 GiB uploads on RAM)."""
    # By default in the runtime, _UPLOAD_STAGING_DIR is HIVE_HOME/tmp/colony_uploads.
    # Tests monkeypatch this per-test, but the module default at import time
    # is what matters — read it via a fresh import path.
    import importlib

    from framework.config import HIVE_HOME

    fresh = importlib.reload(routes_colonies)
    # Undo the reload's global-state effect on other tests.
    try:
        expected = HIVE_HOME / "tmp" / "colony_uploads"
        assert fresh._UPLOAD_STAGING_DIR == expected, (
            f"staging dir {fresh._UPLOAD_STAGING_DIR} must be under HIVE_HOME ({HIVE_HOME}), not tempfile.gettempdir()"
        )
    finally:
        importlib.reload(routes_colonies)
