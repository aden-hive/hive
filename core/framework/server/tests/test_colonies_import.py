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
            "x_daily/metadata.json": b'{"colony_name":"x_daily"}',
            "x_daily/scripts/run.sh": b"#!/bin/sh\necho hi\n",
        }
    )
    async with await _client(_app()) as c:
        resp = await c.post("/api/colonies/import", data=_form(archive))
        assert resp.status == 201, await resp.text()
        body = await resp.json()
    assert body["name"] == "x_daily"
    assert body["files_imported"] == 2
    assert (colonies_dir / "x_daily" / "metadata.json").read_bytes() == b'{"colony_name":"x_daily"}'
    assert (colonies_dir / "x_daily" / "scripts" / "run.sh").exists()


@pytest.mark.asyncio
async def test_name_override(colonies_dir: Path) -> None:
    archive = _build_tar({"x_daily/": None, "x_daily/file.txt": b"hi"})
    async with await _client(_app()) as c:
        resp = await c.post(
            "/api/colonies/import", data=_form(archive, name="other_name")
        )
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
async def test_rejects_invalid_colony_name(colonies_dir: Path) -> None:
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
            "colonies/x_daily/data/progress.db": b"sqlite",
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
    assert (colonies_dir / "x_daily" / "data" / "progress.db").exists()
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
