"""HTTP routes for colony import/export — moving a colony spec between hosts.

Today, just the import side: accept a `tar.gz` and unpack it into HIVE_HOME so
a desktop client (or any external mover) can hand a colony to a remote runtime
to run.

  POST /api/colonies/import   -- multipart/form-data
    file              required  -- .tar / .tar.gz / .tar.bz2 / .tar.xz
    name              optional  -- override the colony name (legacy single-root
                                   archives only); defaults to the archive's
                                   single top-level directory
    replace_existing  optional  -- "true" to overwrite, else 409 on conflict

The desktop sends a *multi-root* tar so the queen sees a colony's full state
(not just metadata + data) on resume. Recognised top-level prefixes:

  colonies/<name>/...                                 → HIVE_HOME/colonies/<name>/...
  queens/<queen>/...                                  → HIVE_HOME/queens/<queen>/...
  memories/...                                        → HIVE_HOME/memories/...
  agents/<name>/worker/...                            → HIVE_HOME/agents/<name>/worker/...
  agents/queens/<queen>/sessions/<sid>/...            → HIVE_HOME/agents/queens/<queen>/sessions/<sid>/...

The ``queens/`` and ``memories/`` roots carry user-level state a pushed
colony depends on (queen personas incl. deep fields + avatars, agent
memories). They overwrite in place — never wholesale-replaced — and
``queens/<queen>/sessions/`` members are skipped so a push can't clobber
this host's DM history.

Anything outside those is rejected. For backwards compat with older clients
that tar `<name>/...` directly (single colony dir, no `colonies/` wrapper),
the handler falls back to the legacy single-root flow when no recognised
multi-root prefix is found.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from aiohttp import web

from framework.config import COLONIES_DIR, colony_dir
from framework.host.colony_metadata import (
    update_colony_metadata,
    vacate_soft_deleted_colony,
)

logger = logging.getLogger(__name__)

# Matches the convention used elsewhere in the codebase (see
# routes_colony_workers and queen_lifecycle_tools): lowercase alphanumerics
# and underscores only. No dots, no slashes — names are filesystem segments.
_COLONY_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# Conservative segment validator for the queen's session id (date-stamped UUID
# tail like ``session_20260415_175106_eca07a69``) and queen name slug
# (``queen_technology``). Same charset as colony names — the codebase already
# normalises both to ``[a-z0-9_]+`` everywhere they're created, so accepting
# a wider charset here would just introduce a foothold for path mischief.
_SESSION_SEGMENT_RE = re.compile(r"^[a-z0-9_]+$")

# 2 GiB cap on uploads. We stream the request body straight to disk so the
# ceiling here protects against a runaway upload filling /root/.hive
# (sandbox disk is 6 GiB), not against running out of memory — the prior
# 100 MiB cap was a memory-bound (the handler used to buffer the whole tar
# in `io.BytesIO` before extraction). With the streaming rewrite below,
# 2 GiB is enough headroom for any realistic colony push (worker logs,
# attached session blobs, screenshot caches) while still leaving 4 GiB of
# disk for everything else.
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def _agents_dir() -> Path:
    """``COLONIES_DIR`` resolves to ``HIVE_HOME/colonies``; ``agents/`` is
    the sibling. Resolved per-call so tests that monkeypatch
    ``COLONIES_DIR`` propagate without a second patch."""
    return Path(COLONIES_DIR).parent / "agents"


def _queens_dir() -> Path:
    """Sibling of ``colonies/`` — see ``_agents_dir`` for why per-call."""
    return Path(COLONIES_DIR).parent / "queens"


def _memories_dir() -> Path:
    """Sibling of ``colonies/`` — see ``_agents_dir`` for why per-call."""
    return Path(COLONIES_DIR).parent / "memories"


def _validate_colony_id(name: str) -> str | None:
    """Return an error message if name isn't a valid colony name, else None."""
    if not name:
        return "colony name is required"
    if len(name) > 64:
        return "colony name too long (max 64 chars)"
    if not _COLONY_NAME_RE.match(name):
        return "colony name must match [a-z0-9_]+"
    return None


def _validate_session_segment(seg: str, label: str) -> str | None:
    """Validate a path segment we're going to plumb into a destination dir."""
    if not seg:
        return f"{label} is required"
    if len(seg) > 128:
        return f"{label} too long (max 128 chars)"
    if not _SESSION_SEGMENT_RE.match(seg):
        return f"{label} must match [a-zA-Z0-9_-]+"
    return None


def _archive_top_level(tf: tarfile.TarFile) -> tuple[str | None, str | None]:
    """Find the archive's single top-level directory, if it has one.

    Used only for the legacy single-root path. Returns ``(name, error)``.
    Allows the archive to optionally include a leading ``./`` prefix.
    """
    tops: set[str] = set()
    for member in tf.getmembers():
        if not member.name or member.name.startswith("/"):
            return None, f"invalid member path: {member.name!r}"
        parts = Path(member.name).parts
        if not parts or parts[0] == "..":
            return None, f"invalid member path: {member.name!r}"
        first = parts[0] if parts[0] != "." else (parts[1] if len(parts) > 1 else "")
        if first:
            tops.add(first)
    if len(tops) != 1:
        return None, "archive must contain exactly one top-level directory"
    return next(iter(tops)), None


def _has_multi_root_prefix(tf: tarfile.TarFile) -> bool:
    """True iff any member name starts with a recognised multi-root prefix.

    The legacy shape (`<name>/...`) doesn't match either prefix, so this lets
    us route old and new clients through the same endpoint.
    """
    for member in tf.getmembers():
        name = member.name
        if name.startswith("./"):
            name = name[2:]
        if name.startswith(("colonies/", "agents/", "queens/", "memories/")):
            return True
    return False


def _normalise_member_name(name: str) -> str:
    """Strip a leading ``./`` if present; reject absolute or empty names."""
    if name.startswith("./"):
        name = name[2:]
    return name


def _safe_extract_tar(
    tf: tarfile.TarFile,
    dest: Path,
    *,
    strip_prefix: str,
    exclude: tuple[str, ...] = (),
    atomic: bool = False,
) -> tuple[int, str | None]:
    """Extract every member of ``tf`` whose name starts with ``strip_prefix/``
    into ``dest``, with the prefix stripped off.

    Each member's resolved path must stay under ``dest``; symlinks, hardlinks,
    and device/fifo entries are rejected. Returns ``(files_extracted, error)``;
    on error the caller is responsible for cleanup.

    Members outside ``strip_prefix`` are silently *skipped* (not an error) so
    the caller can call this multiple times on the same tar with different
    prefixes — once per recognised root.

    ``exclude`` lists stripped-relative subtrees to skip (e.g. ``("sessions",)``
    for queen dirs). ``atomic`` writes each file via temp + ``os.replace`` —
    used for in-place roots that may have live readers on this host.
    """
    base = dest.resolve()
    base.mkdir(parents=True, exist_ok=True)
    files_extracted = 0
    prefix_with_sep = f"{strip_prefix}/" if strip_prefix else ""

    for member in tf.getmembers():
        name = _normalise_member_name(member.name)
        if not name:
            continue
        if strip_prefix:
            if name == strip_prefix:
                # The top-level dir entry itself; dest already exists.
                continue
            if not name.startswith(prefix_with_sep):
                # Belongs to a different root in a multi-root tar; skip.
                continue
            rel = name[len(prefix_with_sep) :]
        else:
            rel = name
        if not rel:
            continue
        if any(rel == e or rel.startswith(f"{e}/") for e in exclude):
            continue
        if ".." in Path(rel).parts:
            return files_extracted, f"path traversal in member: {member.name!r}"
        if member.issym() or member.islnk():
            return (
                files_extracted,
                f"symlinks/hardlinks not supported: {member.name!r}",
            )
        if member.isdev() or member.isfifo():
            return (
                files_extracted,
                f"device/fifo not supported: {member.name!r}",
            )

        target = (base / rel).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return files_extracted, f"member escapes destination: {member.name!r}"

        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        src = tf.extractfile(member)
        if src is None:
            return files_extracted, f"unsupported member: {member.name!r}"
        mode = member.mode & 0o755 if member.mode else 0o644
        if atomic:
            fd, tmp = tempfile.mkstemp(prefix=".import.", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(fd, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(tmp, mode)
                os.replace(tmp, target)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        else:
            with target.open("wb") as out:
                shutil.copyfileobj(src, out)
            target.chmod(mode)
        files_extracted += 1

    return files_extracted, None


def _classify_multi_root_member(name: str) -> tuple[str, str] | None:
    """Recognise a multi-root tar member and return ``(root, top_dir)``.

    ``root`` is one of ``"colonies"``, ``"queens"``, ``"memories"``,
    ``"agents_worker"``, ``"agents_queen"``; ``top_dir`` is the prefix to
    feed to ``_safe_extract_tar`` (the part of the path that should be
    stripped before joining with the destination base). Returns None for
    members that don't match any recognised root.

    The caller pre-validates segments before extraction, so this is purely
    structural: which root, what the strip prefix should be.
    """
    parts = Path(name).parts
    if not parts:
        return None
    if parts[0] == "colonies" and len(parts) >= 2:
        return ("colonies", f"colonies/{parts[1]}")
    if parts[0] == "queens" and len(parts) >= 2:
        return ("queens", f"queens/{parts[1]}")
    if parts[0] == "memories":
        return ("memories", "memories")
    if parts[0] == "agents" and len(parts) >= 2:
        # agents/queens/<queen>/sessions/<sid>/...  vs  agents/<name>/worker/...
        if parts[1] == "queens":
            if len(parts) >= 5 and parts[3] == "sessions":
                return ("agents_queen", f"agents/queens/{parts[2]}/sessions/{parts[4]}")
            return None
        # Plain agent — only the worker subtree is exported.
        if len(parts) >= 3 and parts[2] == "worker":
            return ("agents_worker", f"agents/{parts[1]}/worker")
        return None
    return None


def _plan_multi_root(
    tf: tarfile.TarFile,
) -> tuple[dict[str, dict[str, str]], str | None]:
    """Walk the tar once and group entries by root.

    Returns ``(groups, error)`` where ``groups`` is keyed by root kind
    (``"colonies"`` etc.) and each entry maps the strip prefix to its
    destination directory under HIVE_HOME. Validates name segments so we
    bail before unpacking when something looks off.
    """
    groups: dict[str, dict[str, str]] = {
        "colonies": {},
        "queens": {},
        "memories": {},
        "agents_worker": {},
        "agents_queen": {},
    }
    seen_unrecognised: set[str] = set()
    for member in tf.getmembers():
        name = _normalise_member_name(member.name)
        if not name or name.startswith("/") or ".." in Path(name).parts:
            return groups, f"invalid member path: {member.name!r}"
        classified = _classify_multi_root_member(name)
        if classified is None:
            # Track unique top-level dirs to give a useful error if nothing
            # ended up classified.
            seen_unrecognised.add(Path(name).parts[0])
            continue
        kind, prefix = classified
        if prefix in groups[kind]:
            continue
        # Validate path segments per-kind so we never plumb dirty input into
        # a destination we don't fully control.
        prefix_parts = Path(prefix).parts
        if kind == "colonies":
            err = _validate_colony_id(prefix_parts[1])
            if err:
                return groups, err
            dest = str(COLONIES_DIR / prefix_parts[1])
        elif kind == "queens":
            err = _validate_session_segment(prefix_parts[1], "queen id")
            if err:
                return groups, err
            dest = str(_queens_dir() / prefix_parts[1])
        elif kind == "memories":
            dest = str(_memories_dir())
        elif kind == "agents_worker":
            err = _validate_colony_id(prefix_parts[1])
            if err:
                return groups, err
            dest = str(_agents_dir() / prefix_parts[1] / "worker")
        elif kind == "agents_queen":
            queen, sid = prefix_parts[2], prefix_parts[4]
            err = _validate_session_segment(queen, "queen name")
            if err:
                return groups, err
            err = _validate_session_segment(sid, "queen session id")
            if err:
                return groups, err
            dest = str(_agents_dir() / "queens" / queen / "sessions" / sid)
        else:  # pragma: no cover — defensive
            continue
        groups[kind][prefix] = dest

    if not any(groups.values()):
        roots = ", ".join(sorted(seen_unrecognised)) or "(none)"
        return (
            groups,
            "tar has no recognised top-level prefix "
            f"(expected colonies/, queens/, memories/, agents/<name>/worker/, "
            f"agents/queens/<queen>/sessions/<sid>/; got: {roots})",
        )
    return groups, None


async def _read_upload(
    request: web.Request,
) -> tuple[Path | None, str | None, dict[str, str], web.Response | None]:
    """Drain the multipart upload onto a temp file. Returns
    ``(path, filename, form, error)``.

    Streams the ``file`` part to disk in 64 KiB chunks instead of buffering
    the whole tar in memory. Two reasons:

    1.  Lets the cap (`_MAX_UPLOAD_BYTES`) scale far past hive serve's
        process RSS — colonies with worker conversation history, attached
        session blobs, or browser-screenshot caches blow past the legacy
        100 MiB ceiling routinely.
    2.  Makes the failure mode "no disk space" instead of "process OOM" —
        much easier to recover from operationally; aiohttp keeps serving
        every other route.

    Caller is responsible for unlinking the returned path when done; we
    use ``delete=False`` so the file outlives this function but is
    self-cleaned by `handle_import_colony`'s ``finally``.
    """
    if not request.content_type.startswith("multipart/"):
        return None, None, {}, web.json_response({"error": "expected multipart/form-data"}, status=400)
    reader = await request.multipart()
    upload_path: Path | None = None
    upload_filename: str | None = None
    form: dict[str, str] = {}
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            # NamedTemporaryFile(delete=False) so we can pass the path to
            # tarfile.open after closing the writer; the caller's finally
            # removes the file.
            tmp = tempfile.NamedTemporaryFile(prefix="colony-upload-", suffix=".tar", delete=False)
            tmp_path = Path(tmp.name)
            written = 0
            try:
                while True:
                    chunk = await part.read_chunk(size=65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > _MAX_UPLOAD_BYTES:
                        tmp.close()
                        tmp_path.unlink(missing_ok=True)
                        return (
                            None,
                            None,
                            {},
                            web.json_response(
                                {"error": f"upload exceeds {_MAX_UPLOAD_BYTES} bytes"},
                                status=413,
                            ),
                        )
                    tmp.write(chunk)
                tmp.flush()
                os.fsync(tmp.fileno())
            except BaseException:
                # Including asyncio.CancelledError — don't leak the temp
                # file if the client disconnects mid-upload.
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise
            finally:
                tmp.close()
            upload_path = tmp_path
            upload_filename = part.filename or ""
        else:
            form[part.name or ""] = (await part.text()).strip()
    if upload_path is None:
        return None, None, {}, web.json_response({"error": "missing 'file' part"}, status=400)
    return upload_path, upload_filename, form, None


# ---------------------------------------------------------------------------
# Chunked resumable upload — /api/colonies/import/{init,chunk,status,finalize}
# ---------------------------------------------------------------------------
#
# Why chunked: the desktop's push is one big multipart body. On a residential
# upstream (~5-10 Mbps) a 80 MiB tarball takes 60-120s to fully send, and any
# single network hiccup during that window blows the entire transfer away —
# the client has no way to resume, no way to know how far it got. Observed
# repeatedly against team 14034's colony pushes (see cloud.ts:pushColony logs).
#
# Wire protocol:
#
#   POST /api/colonies/import/init
#     body JSON: { filename, total_bytes, sha256, replace_existing?, name? }
#     -> 201 { upload_id, received: 0 }
#     -> 413 if total_bytes > _MAX_UPLOAD_BYTES
#     -> 400 on validation failure
#
#   PUT  /api/colonies/import/chunk/{upload_id}?offset=N
#     body: raw octet-stream (a slice of the tarball starting at byte N)
#     -> 200 { received: <new total on disk> }
#     -> 404 if upload_id is unknown
#     -> 409 if the client's declared offset doesn't match the server's
#            current byte count (idempotent-resume semantics: client GET
#            /status and retry from server's actual offset)
#     -> 413 if the chunk would push received past total_bytes
#     -> 400 for other malformed requests
#
#   GET  /api/colonies/import/status/{upload_id}
#     -> 200 { upload_id, received, total_bytes, filename }
#     -> 404 if the upload_id is unknown / expired
#
#   POST /api/colonies/import/finalize/{upload_id}
#     -> same 200/201 payload as /api/colonies/import (dispatches to the same
#        _extract_uploaded_archive helper)
#     -> 409 if received != total_bytes
#     -> 400 if sha256 doesn't match the client-declared value (integrity)
#     -> 404 if the upload_id is unknown
#     Deletes the staging file on both success AND failure.
#
#   DELETE /api/colonies/import/{upload_id}
#     -> 204 (idempotent — 204 even if the id was already gone)
#     Client-driven cancel path for user-abort during upload.
#
# Storage:
#   /tmp/hive-colony-uploads/<upload_id>.data      # append-only chunks
#   /tmp/hive-colony-uploads/<upload_id>.meta.json # metadata (see below)
#
# GC: on every /init call we sweep the uploads dir for meta files with
# ``created_at`` older than _UPLOAD_TTL_SECONDS and unlink both the .data
# and .meta.json. No background sweeper — the workload is bounded to
# "user tries to push a colony" and any orphan gets cleaned up on the
# next push.
#
# Concurrency: aiohttp handlers run in the same event loop, so per-upload_id
# state doesn't need locking — the client's chunks are ordered (each PUT
# waits for the previous PUT's response before firing the next). The
# offset-mismatch 409 catches pipelining bugs on the client side.


# Where to stage incoming chunks.
#
# The requirements:
#   1. Real disk, not tmpfs — an upload can be up to _MAX_UPLOAD_BYTES
#      (2 GiB) and a few concurrent uploads on a tmpfs /tmp (Ubuntu
#      systemd default sets /tmp to ~50% of RAM) would exhaust the VM's
#      4 GiB budget and OOM hive-serve.
#   2. LOCAL disk, not NFS — earlier this path was HIVE_HOME/tmp, which
#      in the sandbox VM lives on the per-team persistent volume mounted
#      at /root/.hive. That volume is backed by NFS. During a long-running
#      tar extract (12-17 s for a 60 MiB gzipped multi-root tar with
#      ~48 000 members: gtm_agency_leads on team 14034, 2026-07-02), the
#      NFS server invalidates the open file handle mid-read and
#      ``tarfile → gzip → self._fp.read`` raises OSError ESTALE
#      ("[Errno 116] Stale file handle") which the outer error middleware
#      turns into an opaque 500. Verified live from this workstation
#      against the same sandbox — the traceback pointed straight at
#      ``self.file.read(size-self._length+read)`` in gzip.py.
#   3. Bounded lifetime — a stale/failed upload must be reap-able
#      without ripping out user state.
#
# /var/tmp on Ubuntu is on the container rootfs (firecracker's local
# COW file), NOT tmpfs and NOT NFS. It survives across a hive-serve
# restart (same VM), which the finalize retry path relies on. It gets
# wiped when the VM itself is torn down, which is exactly what we want
# for staging.
_UPLOAD_STAGING_DIR = Path("/var/tmp") / "hive-colony-uploads"
_UPLOAD_TTL_SECONDS = 24 * 60 * 60  # 24h — GC's failed-mid-push orphans
_UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{16}$")
# Per-chunk ceiling. Bigger than the client's default (4 MiB) to give room
# for the client to raise CHUNK_BYTES later without a coordinated flag day,
# but small enough that a hostile client can't tie up hundreds of MiB of
# aiohttp buffer with one PUT.
_MAX_CHUNK_BYTES = 128 * 1024 * 1024
# Cap on concurrent in-flight uploads across ALL clients. Prevents a buggy
# or hostile caller from posting /init many times and either pinning the
# meta-file count (many-tiny-uploads DoS) or filling the staging volume with
# 2 GiB * N of committed chunk data. Chosen empirically: even a heavy user
# pushing several colonies in parallel won't exceed 5-10 concurrent
# uploads; 32 leaves comfortable headroom before we start returning 429.
_MAX_CONCURRENT_UPLOADS = 32


def _upload_paths(upload_id: str) -> tuple[Path, Path]:
    """Return ``(data_path, meta_path)`` for a validated upload_id."""
    return (
        _UPLOAD_STAGING_DIR / f"{upload_id}.data",
        _UPLOAD_STAGING_DIR / f"{upload_id}.meta.json",
    )


def _load_upload_meta(upload_id: str) -> dict | None:
    _, meta_path = _upload_paths(upload_id)
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_upload_meta(upload_id: str, meta: dict) -> None:
    """Atomic meta write: write-tmp+rename so a crash mid-flush can't leave
    a truncated meta file that would falsely orphan a live upload."""
    _, meta_path = _upload_paths(upload_id)
    tmp = meta_path.with_suffix(".meta.json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(meta, f)
    os.replace(tmp, meta_path)


def _live_upload_count() -> int:
    """Count of uploads with a live meta file. Used by the /init cap check."""
    if not _UPLOAD_STAGING_DIR.exists():
        return 0
    return sum(1 for _ in _UPLOAD_STAGING_DIR.glob("*.meta.json"))


def _gc_stale_uploads() -> None:
    """Delete stale staging files. Two sweep passes:

      1. ``*.meta.json`` older than _UPLOAD_TTL_SECONDS → unlink meta + data.
      2. ``*.data`` with no paired ``.meta.json`` at all → unlink the orphan.
         This catches the failure mode where /init created the .data file
         (or a hand-created orphan) but never landed a meta. Without pass 2
         an orphan .data would linger indefinitely because pass 1 iterates
         meta files only.

    Called from /init. Best-effort: any unlink failure is logged and the
    sweep continues so one broken permissions bit doesn't block new uploads.
    """
    if not _UPLOAD_STAGING_DIR.exists():
        return
    now = time.time()
    # Pass 1: meta-driven sweep.
    for meta_path in _UPLOAD_STAGING_DIR.glob("*.meta.json"):
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            if now - float(meta.get("created_at", 0)) < _UPLOAD_TTL_SECONDS:
                continue
        except Exception:
            # Corrupt meta — treat as stale so we don't leak the .data file
            # forever. If the .data is legitimately live, the next PUT will
            # 404 and the client will re-init, which is the correct outcome.
            pass
        upload_id = meta_path.stem.removesuffix(".meta")
        data_path, _ = _upload_paths(upload_id)
        for p in (data_path, meta_path):
            try:
                p.unlink(missing_ok=True)
            except OSError as err:
                logger.warning("upload GC: failed to unlink %s: %s", p, err)
    # Pass 2: orphaned .data sweep (no matching meta).
    for data_path in _UPLOAD_STAGING_DIR.glob("*.data"):
        meta_path = data_path.with_suffix(".meta.json")
        if meta_path.exists():
            continue
        try:
            data_path.unlink(missing_ok=True)
        except OSError as err:
            logger.warning("upload GC: failed to unlink orphan %s: %s", data_path, err)


async def handle_init_upload(request: web.Request) -> web.Response:
    """POST /api/colonies/import/init — start a chunked upload."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    try:
        total_bytes = int(body.get("total_bytes"))
    except (TypeError, ValueError):
        return web.json_response({"error": "total_bytes must be an integer"}, status=400)
    if total_bytes <= 0:
        return web.json_response({"error": "total_bytes must be positive"}, status=400)
    if total_bytes > _MAX_UPLOAD_BYTES:
        return web.json_response({"error": f"total_bytes exceeds {_MAX_UPLOAD_BYTES}"}, status=413)

    sha256 = str(body.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        return web.json_response({"error": "sha256 must be a 64-char hex digest"}, status=400)

    filename = str(body.get("filename") or "upload.tar").strip() or "upload.tar"
    replace_existing = bool(body.get("replace_existing", False))
    name_override = str(body.get("name") or "").strip() or None

    _UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    _gc_stale_uploads()
    # Enforce the concurrent-upload cap AFTER GC — so a burst of stale
    # meta files from an earlier crash doesn't wedge new legitimate
    # uploads. 429 with a hint so a client backoff loop can retry.
    if _live_upload_count() >= _MAX_CONCURRENT_UPLOADS:
        return web.json_response(
            {
                "error": "too many concurrent uploads",
                "hint": f"limit is {_MAX_CONCURRENT_UPLOADS}; retry after finishing or cancelling one",
            },
            status=429,
        )

    upload_id = secrets.token_hex(8)
    # Meta FIRST — establish the resume anchor before creating the .data
    # file. If _write_upload_meta raises (ENOSPC, EACCES, cancellation)
    # we haven't left an orphaned .data behind. The first chunk PUT will
    # open the .data file in "r+b" mode via the truncate-then-append
    # dance below; passing that flag opens-or-creates, so we don't need
    # to pre-touch here.
    _write_upload_meta(
        upload_id,
        {
            "filename": filename,
            "total_bytes": total_bytes,
            "sha256": sha256,
            "replace_existing": replace_existing,
            "name_override": name_override,
            "created_at": time.time(),
            "received_bytes": 0,
        },
    )
    # Create the empty .data now so /status returns a coherent view even
    # before any chunk lands. If this touch fails (unlikely — meta write
    # just succeeded on the same filesystem), roll back the meta so we
    # don't leave the client holding an upload_id whose data file the
    # first PUT can't open.
    data_path, meta_path = _upload_paths(upload_id)
    try:
        data_path.touch()
    except OSError as err:
        meta_path.unlink(missing_ok=True)
        return web.json_response({"error": f"could not create staging file: {err}"}, status=500)
    return web.json_response({"upload_id": upload_id, "received": 0}, status=201)


async def handle_chunk_upload(request: web.Request) -> web.Response:
    """PUT /api/colonies/import/chunk/{upload_id}?offset=N — append a chunk.

    We READ the whole chunk into memory (bounded by the client's chunk
    size, capped server-side at _MAX_CHUNK_BYTES) and only touch the file
    once we've validated it in full. The prior stream-to-disk-while-checking
    shape had a torn-write hazard: on a mid-stream 413 the file already
    contained some bytes of the overflowing chunk but meta pointed at the
    pre-chunk received offset, so subsequent PUTs would silently corrupt
    the archive. Reading-then-writing keeps file and meta consistent by
    construction.
    """
    upload_id = request.match_info["upload_id"]
    if not _UPLOAD_ID_RE.fullmatch(upload_id):
        return web.json_response({"error": "invalid upload_id"}, status=400)

    try:
        declared_offset = int(request.query.get("offset", "-1"))
    except ValueError:
        return web.json_response({"error": "offset must be an integer"}, status=400)
    if declared_offset < 0:
        return web.json_response({"error": "offset must be >= 0"}, status=400)

    meta = _load_upload_meta(upload_id)
    if meta is None:
        return web.json_response({"error": "unknown upload_id"}, status=404)

    received = int(meta.get("received_bytes", 0))
    total = int(meta.get("total_bytes", 0))

    # Idempotent-resume: if the client's offset matches what's on disk,
    # append. If it's LESS than what's on disk, the client is trying to
    # overwrite bytes we already have — reject with 409 so the client
    # re-syncs via /status. If it's GREATER, we'd leave a hole in the file
    # — also 409.
    if declared_offset != received:
        return web.json_response(
            {
                "error": "offset mismatch",
                "declared": declared_offset,
                "received": received,
            },
            status=409,
        )

    # Cap the per-chunk size server-side. The client's default is 4 MiB;
    # 128 MiB is the DoS ceiling — anything larger than that and it's
    # probably a bug/attack, and we don't want a single chunk PUT to hold
    # 500 MiB of aiohttp buffer.
    content_length = request.content_length
    if content_length is None:
        return web.json_response({"error": "Content-Length required"}, status=411)
    if content_length < 0:
        return web.json_response({"error": "invalid Content-Length"}, status=400)
    if content_length > _MAX_CHUNK_BYTES:
        return web.json_response({"error": "chunk too large"}, status=413)
    if received + content_length > total:
        return web.json_response(
            {
                "error": "chunk would exceed total_bytes",
                "received": received,
                "chunk_size": content_length,
                "total": total,
            },
            status=413,
        )

    body = await request.read()
    if len(body) != content_length:
        # Content-Length lied. Body is either truncated (client aborted)
        # or padded (which aiohttp should have rejected upstream). Either
        # way we do not commit — meta stays at ``received`` so the client
        # can resync via /status and retry.
        return web.json_response(
            {"error": "body length mismatch", "expected": content_length, "actual": len(body)},
            status=400,
        )

    data_path, _ = _upload_paths(upload_id)
    # Realign the file to meta.received_bytes BEFORE appending. This is
    # the recovery step for the torn-write hazard: if a prior chunk's
    # data write + fsync landed but its _write_upload_meta then raised
    # (ENOSPC on the meta write, aiohttp shutdown mid-tick, SIGKILL), the
    # file is now longer than meta says. On the client's retry we would
    # otherwise APPEND onto those unmatched bytes and the archive would
    # end up 4 MiB longer than expected — sha256 mismatch at finalize
    # after the user has waited through a full retransmit.
    #
    # By truncating to meta.received_bytes first, we make meta the single
    # source of truth for "what's committed" and drop any bytes past that
    # point regardless of how they got there. If the file happens to be
    # SHORTER than received (should be impossible unless GC or a
    # concurrent writer meddled), we refuse — a shorter file plus a
    # forward append would leave a gap of zeros between meta.received and
    # the current chunk, silently corrupting the archive.
    try:
        current_size = data_path.stat().st_size
    except FileNotFoundError:
        return web.json_response({"error": "staging file vanished; re-init required"}, status=410)
    if current_size < received:
        return web.json_response(
            {
                "error": "staging file shorter than meta says; re-init required",
                "file_size": current_size,
                "meta_received": received,
            },
            status=410,
        )
    with data_path.open("r+b") as f:
        if current_size > received:
            f.truncate(received)
        f.seek(received)
        f.write(body)
        f.flush()
        os.fsync(f.fileno())

    new_received = received + len(body)
    meta["received_bytes"] = new_received
    _write_upload_meta(upload_id, meta)
    return web.json_response({"received": new_received}, status=200)


async def handle_upload_status(request: web.Request) -> web.Response:
    """GET /api/colonies/import/status/{upload_id} — how much has landed."""
    upload_id = request.match_info["upload_id"]
    if not _UPLOAD_ID_RE.fullmatch(upload_id):
        return web.json_response({"error": "invalid upload_id"}, status=400)
    meta = _load_upload_meta(upload_id)
    if meta is None:
        return web.json_response({"error": "unknown upload_id"}, status=404)
    return web.json_response(
        {
            "upload_id": upload_id,
            "received": int(meta.get("received_bytes", 0)),
            "total_bytes": int(meta.get("total_bytes", 0)),
            "filename": meta.get("filename"),
        }
    )


async def handle_finalize_upload(request: web.Request) -> web.Response:
    """POST /api/colonies/import/finalize/{upload_id} — commit and extract."""
    upload_id = request.match_info["upload_id"]
    if not _UPLOAD_ID_RE.fullmatch(upload_id):
        return web.json_response({"error": "invalid upload_id"}, status=400)
    meta = _load_upload_meta(upload_id)
    if meta is None:
        return web.json_response({"error": "unknown upload_id"}, status=404)

    data_path, meta_path = _upload_paths(upload_id)
    received = int(meta.get("received_bytes", 0))
    total = int(meta.get("total_bytes", 0))
    if received != total:
        return web.json_response(
            {"error": "upload incomplete", "received": received, "total": total},
            status=409,
        )

    # Verify sha256 BEFORE handing to _extract_uploaded_archive. tarfile
    # would happily open a truncated or corrupted archive to a certain
    # extent, and the failure mode is confusing ("member missing" etc)
    # rather than the honest "the bytes on disk don't match what the
    # client says it uploaded".
    try:
        digest = _sha256_of_file(data_path)
    except OSError as err:
        # Data file gone from under us (concurrent GC on a stuck upload,
        # or filesystem yank). Clean the meta too and surface it.
        meta_path.unlink(missing_ok=True)
        return web.json_response({"error": f"staging file unreadable: {err}"}, status=500)
    if digest != meta.get("sha256"):
        for p in (data_path, meta_path):
            p.unlink(missing_ok=True)
        return web.json_response(
            {
                "error": "sha256 mismatch",
                "expected": meta.get("sha256"),
                "actual": digest,
            },
            status=400,
        )

    try:
        return await _extract_uploaded_archive(
            data_path,
            meta.get("filename"),
            replace_existing=bool(meta.get("replace_existing", False)),
            name_override=meta.get("name_override"),
        )
    finally:
        # Delete both files whether the extract succeeded or 4xx'd. The
        # client isn't going to retry an extract failure by re-finalizing;
        # they'd re-init a fresh upload.
        for p in (data_path, meta_path):
            p.unlink(missing_ok=True)


async def handle_cancel_upload(request: web.Request) -> web.Response:
    """DELETE /api/colonies/import/{upload_id} — drop a staging upload."""
    upload_id = request.match_info["upload_id"]
    if not _UPLOAD_ID_RE.fullmatch(upload_id):
        return web.json_response({"error": "invalid upload_id"}, status=400)
    data_path, meta_path = _upload_paths(upload_id)
    for p in (data_path, meta_path):
        p.unlink(missing_ok=True)
    return web.Response(status=204)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def handle_import_colony(request: web.Request) -> web.Response:
    """POST /api/colonies/import — unpack a colony tarball into HIVE_HOME.

    Legacy single-shot multipart path. Prefer the chunked-upload flow
    (``/api/colonies/import/init`` → ``/chunk`` → ``/finalize``) for anything
    larger than a few MiB — the chunked flow resumes across transient
    network hiccups instead of restarting the whole transfer.

    This handler is kept for two reasons: (1) desktop clients older than
    the chunked-flow rollout still land here, and (2) it's the fallback
    the client falls back to when ``/import/init`` returns 404 (i.e. the
    runtime template is older than the client). The shared
    ``_extract_uploaded_archive`` helper runs the actual tar-open +
    extraction so both entry points behave identically after the bytes
    are on disk.
    """
    upload_path, upload_filename, form, err_resp = await _read_upload(request)
    if err_resp is not None:
        return err_resp
    assert upload_path is not None  # for the type checker

    replace_existing = form.get("replace_existing", "false").lower() == "true"
    name_override = form.get("name", "").strip() or None

    try:
        return await _extract_uploaded_archive(
            upload_path,
            upload_filename,
            replace_existing=replace_existing,
            name_override=name_override,
        )
    finally:
        upload_path.unlink(missing_ok=True)


async def _extract_uploaded_archive(
    upload_path: Path,
    upload_filename: str | None,
    *,
    replace_existing: bool,
    name_override: str | None,
) -> web.Response:
    """Open a fully-received tarball at ``upload_path`` and extract it.

    Shared by:
      - ``handle_import_colony`` (legacy multipart, one-shot)
      - ``handle_finalize_upload`` (chunked upload, after all chunks landed)

    Behaviour and error surface are identical to what the legacy handler
    did before this refactor — both paths converge here so a client
    switching between them sees no observable difference.
    """
    try:
        # Open the tarball directly off disk — tarfile uses bounded
        # read buffering, so peak memory stays bounded by the largest
        # single member's header, not by the archive total. Mode
        # "r:*" auto-detects gz/bz2/xz/zst.
        tf = tarfile.open(str(upload_path), mode="r:*")
    except tarfile.TarError as err:
        return web.json_response({"error": f"invalid tar archive: {err}"}, status=400)

    try:
        upload_size = upload_path.stat().st_size
        if _has_multi_root_prefix(tf):
            return await _import_multi_root(tf, replace_existing, upload_filename, upload_size)
        return await _import_legacy_single_root(tf, name_override, replace_existing, upload_filename, upload_size)
    finally:
        tf.close()


async def _import_legacy_single_root(
    tf: tarfile.TarFile,
    name_override: str | None,
    replace_existing: bool,
    upload_filename: str | None,
    upload_size: int,
) -> web.Response:
    """Legacy path: tar contains `<name>/...` only, route to colonies/<name>/.

    Kept verbatim from the previous handler so existing test fixtures and
    older desktop builds keep working during a partial rollout.
    """
    top, top_err = _archive_top_level(tf)
    if top_err or top is None:
        return web.json_response({"error": top_err}, status=400)

    colony_id = name_override or top
    name_err = _validate_colony_id(colony_id)
    if name_err:
        return web.json_response({"error": name_err}, status=400)

    target = COLONIES_DIR / colony_id
    if target.exists():
        if not replace_existing:
            return web.json_response(
                {
                    "error": "colony already exists",
                    "name": colony_id,
                    "hint": "set replace_existing=true to overwrite",
                },
                status=409,
            )
        shutil.rmtree(target)

    files_extracted, extract_err = _safe_extract_tar(tf, target, strip_prefix=top)
    if extract_err:
        shutil.rmtree(target, ignore_errors=True)
        return web.json_response({"error": extract_err}, status=400)

    logger.info(
        "Imported colony %s (legacy, %d files) from upload %s (%d bytes)",
        colony_id,
        files_extracted,
        upload_filename or "<unnamed>",
        upload_size,
    )
    return web.json_response(
        {
            "name": colony_id,
            "path": str(target),
            "files_imported": files_extracted,
            "replaced": replace_existing,
        },
        status=201,
    )


async def _import_multi_root(
    tf: tarfile.TarFile,
    replace_existing: bool,
    upload_filename: str | None,
    upload_size: int,
) -> web.Response:
    """New path: tar contains `colonies/<name>/...` plus optional agents trees.

    Each recognised root is extracted to its corresponding HIVE_HOME subtree
    using the same traversal-safe walker as the legacy path. ``replace_existing``
    governs the colonies dir conflict; the agents trees overwrite in place
    (worker conversations and queen sessions are append-mostly stores —
    overwriting a stale subset is fine, and adding the conflict gate would
    block legitimate re-pushes from a different desktop session).

    The ``queens/`` and ``memories/`` roots also overwrite in place, atomically
    per file (live sessions may be reading profile.yaml / memory files), with
    ``queens/<qid>/sessions/`` skipped so a push never clobbers this host's DM
    history. They're excluded from abort-cleanup: rmtree'ing the shared queens
    or memories tree on a failed import would destroy unrelated user state.
    """
    plan, plan_err = _plan_multi_root(tf)
    if plan_err:
        return web.json_response({"error": plan_err}, status=400)

    # Conflict guard for the colonies root only — these are user-visible
    # entities the desktop expects to control overwrite of.
    primary_colony_id: str | None = None
    primary_colony_target: Path | None = None
    for prefix, dest in plan["colonies"].items():
        target = Path(dest)
        primary_colony_id = Path(prefix).parts[1]
        primary_colony_target = target
        if target.exists() and not replace_existing:
            return web.json_response(
                {
                    "error": "colony already exists",
                    "name": primary_colony_id,
                    "hint": "set replace_existing=true to overwrite",
                },
                status=409,
            )
        if target.exists() and replace_existing:
            shutil.rmtree(target)

    # The colonies/ root is required. agents/ trees are optional follow-ons.
    if not plan["colonies"]:
        return web.json_response(
            {
                "error": "tar missing required colonies/<name>/ root",
            },
            status=400,
        )

    summary: dict[str, dict[str, int | str]] = {}
    extracted_dests: list[Path] = []

    def _abort(err: str, status: int = 400) -> web.Response:
        for path in extracted_dests:
            shutil.rmtree(path, ignore_errors=True)
        return web.json_response({"error": err}, status=status)

    # An incoming queen avatar may have a different extension than the one
    # on disk (.jpg ↔ .png) — drop stale siblings so a queen never ends up
    # with two avatars (mirrors routes_queens.handle_upload_avatar).
    for prefix, dest in plan["queens"].items():
        if any(_normalise_member_name(m.name).startswith(f"{prefix}/avatar.") for m in tf.getmembers()):
            for existing in Path(dest).glob("avatar.*"):
                existing.unlink(missing_ok=True)

    # Roots that overwrite a shared tree in place: atomic per-file writes,
    # never registered for abort-cleanup (see docstring).
    _IN_PLACE_KINDS = {"queens", "memories"}

    for kind in ("colonies", "queens", "memories", "agents_worker", "agents_queen"):
        for prefix, dest in plan[kind].items():
            target = Path(dest)
            in_place = kind in _IN_PLACE_KINDS
            files_extracted, extract_err = _safe_extract_tar(
                tf,
                target,
                strip_prefix=prefix,
                exclude=("sessions",) if kind == "queens" else (),
                atomic=in_place,
            )
            if extract_err:
                return _abort(extract_err)
            summary.setdefault(kind, {"files": 0})
            summary[kind]["files"] = int(summary[kind].get("files", 0)) + files_extracted
            if not in_place:
                extracted_dests.append(target)

    total_files = sum(int(v.get("files", 0)) for v in summary.values())
    logger.info(
        "Imported colony %s (%d files across %d roots) from upload %s (%d bytes)",
        primary_colony_id or "<unknown>",
        total_files,
        sum(1 for v in summary.values() if int(v.get("files", 0)) > 0),
        upload_filename or "<unnamed>",
        upload_size,
    )

    return web.json_response(
        {
            "name": primary_colony_id,
            "path": str(primary_colony_target) if primary_colony_target else None,
            "files_imported": total_files,
            "by_root": summary,
            "replaced": replace_existing,
        },
        status=201,
    )


def _find_workers_bound_to_profile(request: web.Request, colony_id: str, profile_name: str) -> list[str]:
    """Return live worker IDs bound to ``(colony_id, profile_name)``.

    Walks every live session's ColonyRuntime workers map. Used to refuse
    profile deletes / renames while workers are still using the binding —
    the contextvar that pins a worker's MCP account lookups is set at
    spawn time and a profile mutation underneath a running worker would
    leave its tool calls pointing at a removed alias on the next turn.
    """
    manager = request.app.get("manager")
    if manager is None:
        return []
    bound: list[str] = []
    try:
        sessions = manager.list_sessions()
    except Exception:
        return []
    for s in sessions:
        runtime = getattr(s, "colony", None)
        if runtime is None:
            continue
        runtime_colony = getattr(runtime, "colony_id", None) or getattr(runtime, "_stream_id", None)
        if runtime_colony != colony_id:
            continue
        try:
            for info in runtime.list_workers():
                if info.profile_name == profile_name and info.status in {
                    "WorkerStatus.RUNNING",
                    "WorkerStatus.PENDING",
                    "running",
                    "pending",
                }:
                    bound.append(info.id)
        except Exception:
            continue
    return bound


async def handle_list_worker_profiles(request: web.Request) -> web.Response:
    """GET /api/colonies/{colony_id}/worker_profiles"""
    colony_id = request.match_info["colony_id"]
    err = _validate_colony_id(colony_id)
    if err:
        return web.json_response({"error": err}, status=400)
    if not (COLONIES_DIR / colony_id).exists():
        return web.json_response({"error": f"colony '{colony_id}' not found"}, status=404)

    from framework.host.worker_profiles import list_worker_profiles

    profiles = list_worker_profiles(colony_id)
    return web.json_response({"worker_profiles": [p.to_dict() for p in profiles]})


async def handle_upsert_worker_profile(request: web.Request) -> web.Response:
    """POST /api/colonies/{colony_id}/worker_profiles — create or replace one profile.

    Body: ``{name, integrations?, task?, skill_name?, concurrency_hint?,
             prompt_override?, tool_filter?, browser_profile?}``. Existing
    siblings are preserved; an existing profile with the same ``name`` is
    replaced (so the desktop can use this for both add and edit).
    ``browser_profile`` binds the profile's browser tools to a connected
    Chrome-profile label (the bridge's ``/profiles`` lists them).
    """
    colony_id = request.match_info["colony_id"]
    err = _validate_colony_id(colony_id)
    if err:
        return web.json_response({"error": err}, status=400)
    if not (COLONIES_DIR / colony_id).exists():
        return web.json_response({"error": f"colony '{colony_id}' not found"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be a JSON object"}, status=400)

    from framework.host.worker_profiles import (
        WorkerProfile,
        upsert_worker_profile,
        validate_profile_name,
    )

    profile = WorkerProfile.from_dict(body)
    name_err = validate_profile_name(profile.name)
    if name_err:
        return web.json_response({"error": name_err}, status=400)

    try:
        saved = upsert_worker_profile(colony_id, profile)
    except (FileNotFoundError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)

    return web.json_response({"worker_profiles": [p.to_dict() for p in saved]}, status=201)


async def handle_delete_worker_profile(request: web.Request) -> web.Response:
    """DELETE /api/colonies/{colony_id}/worker_profiles/{profile_name}.

    Refused with 409 + ``bound_workers`` listing if a live worker is
    bound to the profile, so the user can stop those workers before
    pruning the binding.
    """
    colony_id = request.match_info["colony_id"]
    profile_name = request.match_info["profile_name"]
    err = _validate_colony_id(colony_id)
    if err:
        return web.json_response({"error": err}, status=400)
    if not (COLONIES_DIR / colony_id).exists():
        return web.json_response({"error": f"colony '{colony_id}' not found"}, status=404)

    bound = _find_workers_bound_to_profile(request, colony_id, profile_name)
    if bound:
        return web.json_response(
            {
                "error": "profile is bound to live workers; stop them first",
                "bound_workers": bound,
            },
            status=409,
        )

    from framework.host.worker_profiles import delete_worker_profile

    try:
        removed = delete_worker_profile(colony_id, profile_name)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    if not removed:
        return web.json_response({"error": f"profile '{profile_name}' not found"}, status=404)
    return web.json_response({"deleted": True, "profile_name": profile_name})


async def handle_rename_colony(request: web.Request) -> web.Response:
    """POST /api/colonies/{colony_id}/rename — rename a colony on disk.

    Body: ``{"new_name": "<slug>"}``

    The colony's data lives in two directories that need to move together:

      HIVE_HOME/colonies/{old_name}/...   →  HIVE_HOME/colonies/{new_name}/...
      HIVE_HOME/agents/{old_name}/...     →  HIVE_HOME/agents/{new_name}/...

    Plus any live sessions bound to the old name must be stopped first —
    renaming an in-flight session's working dir under it would corrupt the
    session's open file handles and any tasks it has queued.
    """
    old_name = request.match_info["colony_id"]
    err = _validate_colony_id(old_name)
    if err:
        return web.json_response({"error": err}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be a JSON object"}, status=400)

    new_name = str(body.get("new_name", "")).strip()
    err = _validate_colony_id(new_name)
    if err:
        return web.json_response({"error": err}, status=400)

    if new_name == old_name:
        # No-op; treat as success so the frontend doesn't have to special-case
        # an "unchanged" submission.
        return web.json_response({"renamed": False, "old_name": old_name, "new_name": new_name})

    old_colony_dir = COLONIES_DIR / old_name
    new_colony_dir = COLONIES_DIR / new_name
    agents_root = _agents_dir()
    old_agent_dir = agents_root / old_name
    new_agent_dir = agents_root / new_name

    if not old_colony_dir.is_dir():
        return web.json_response({"error": f"colony '{old_name}' not found"}, status=404)
    # A soft-deleted colony's directories linger on disk but are invisible and
    # unrecoverable. If one is squatting on the target name, park it aside so
    # the rename proceeds instead of failing with a confusing "already exists"
    # against a colony the user can't see. No-op for a live colony, which still
    # trips the 409 below.
    try:
        vacate_soft_deleted_colony(new_name)
    except OSError as exc:
        return web.json_response(
            {"error": f"failed to clear soft-deleted colony '{new_name}': {exc}"},
            status=500,
        )
    if new_colony_dir.exists() or new_agent_dir.exists():
        return web.json_response({"error": f"colony '{new_name}' already exists"}, status=409)

    # Stop any live sessions that have this colony's worker dir mounted —
    # renaming the dir out from under a running session would leave the
    # session pointing at a path that no longer exists.
    manager = request.app.get("manager")
    if manager is not None:
        for session in list(manager.list_sessions()):
            worker_path = getattr(session, "worker_path", None)
            if worker_path is None:
                continue
            try:
                worker_resolved = Path(str(worker_path)).resolve()
            except OSError:
                continue
            if worker_resolved.is_relative_to(old_agent_dir.resolve()) or worker_resolved.is_relative_to(old_colony_dir.resolve()):
                try:
                    await manager.stop_session(session.id)
                except Exception:
                    logger.warning(
                        "rename_colony: failed to stop session %s before move",
                        session.id,
                        exc_info=True,
                    )

    # Two-step move. If the agent-dir move fails after the colony move
    # succeeded, roll the colony move back so the on-disk state stays
    # consistent (otherwise the colony would point at a missing agent dir).
    try:
        old_colony_dir.rename(new_colony_dir)
    except OSError as exc:
        return web.json_response({"error": f"failed to rename colony directory: {exc}"}, status=500)

    if old_agent_dir.is_dir():
        try:
            old_agent_dir.rename(new_agent_dir)
        except OSError as exc:
            # Roll back the colony move so we don't leave a half-renamed
            # colony around. If the rollback itself fails, log loudly —
            # the user will need to clean up manually.
            try:
                new_colony_dir.rename(old_colony_dir)
            except OSError:
                logger.exception("rename_colony: rollback of colony dir move failed after agent-dir move failed; on-disk state is inconsistent")
            return web.json_response({"error": f"failed to rename agent directory: {exc}"}, status=500)

    logger.info("Renamed colony '%s' -> '%s'", old_name, new_name)
    return web.json_response({"renamed": True, "old_name": old_name, "new_name": new_name})


async def handle_reveal_colony_folder(request: web.Request) -> web.Response:
    """POST /api/colonies/{colony_id}/reveal — open a colony's folder in the OS file manager.

    Opens the whole ``colonies/<colony>/`` directory (metadata, tracker, skills,
    workers, queen sessions) — the folder users actually look for when they want
    to inspect a colony's on-disk state.
    """
    colony_id = request.match_info["colony_id"]
    err = _validate_colony_id(colony_id)
    if err:
        return web.json_response({"error": err}, status=400)

    folder = colony_dir(colony_id)
    if not folder.is_dir():
        return web.json_response({"error": f"colony '{colony_id}' not found"}, status=404)

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({"path": str(folder)})


async def handle_delete_colony(request: web.Request) -> web.Response:
    """DELETE /api/colonies/{colony_id}[?purge=true] — delete a colony.

    Soft delete (default): set ``metadata.json``'s ``deleted`` flag so the
    colony drops out of ``/discover`` while its tracked data stays on disk.
    Purge (``?purge=true``): permanently remove the colony's directories
    (``colonies/<id>`` and ``agents/<id>``) and everything under them.

    Stops any live session bound to the colony first. Routing falls out of
    the URL shape: because the colony id is in the path, the desktop's
    per-colony router (``pathTargetsRemote``) sends this to the workspace VM
    for pushed colonies and to the local runtime otherwise — so the same call
    deletes whichever copy actually owns the colony.

    Idempotent: deleting a colony whose directories are already gone returns
    200. The desktop relies on this — after a pushed colony's VM copy is
    deleted and unpinned, it fires the same delete against the local runtime
    to clear any local copy, which may not exist on a second machine.
    """
    colony_id = request.match_info["colony_id"]
    err = _validate_colony_id(colony_id)
    if err:
        return web.json_response({"error": err}, status=400)

    purge = request.query.get("purge", "").strip().lower() in ("1", "true", "yes")

    colony_d = COLONIES_DIR / colony_id
    agent_d = _agents_dir() / colony_id

    if not colony_d.is_dir() and not agent_d.is_dir():
        # Nothing on disk to delete — treat as success so the desktop's
        # local-then-VM (or VM-then-local) double delete doesn't 404.
        return web.json_response({"deleted": colony_id, "purged": purge})

    # Stop any live session whose worker dir lives under this colony — deleting
    # the dir out from under a running session would corrupt its open handles.
    manager = request.app.get("manager")
    if manager is not None:
        for session in list(manager.list_sessions()):
            worker_path = getattr(session, "worker_path", None)
            if worker_path is None:
                continue
            try:
                worker_resolved = Path(str(worker_path)).resolve()
            except OSError:
                continue
            if worker_resolved.is_relative_to(agent_d.resolve()) or worker_resolved.is_relative_to(colony_d.resolve()):
                try:
                    await manager.stop_session(session.id)
                except Exception:
                    logger.warning(
                        "delete_colony: failed to stop session %s before delete",
                        session.id,
                        exc_info=True,
                    )

    if purge:
        for d in (colony_d, agent_d):
            if d.is_dir():
                try:
                    shutil.rmtree(d)
                except OSError as exc:
                    return web.json_response(
                        {"error": f"failed to delete colony directory: {exc}"},
                        status=500,
                    )
        logger.info("Purged colony '%s'", colony_id)
        return web.json_response({"deleted": colony_id, "purged": True})

    # Soft delete: flag the colony so it disappears from /discover (which scans
    # COLONIES_DIR and skips colonies whose metadata.json has deleted=true) but
    # its data stays on disk. No colony dir means nothing for discover to show,
    # so the soft delete is already effective — report success.
    if colony_d.is_dir():
        try:
            update_colony_metadata(colony_id, {"deleted": True})
        except OSError as exc:
            return web.json_response(
                {"error": f"failed to mark colony deleted: {exc}"},
                status=500,
            )
    logger.info("Soft-deleted colony '%s'", colony_id)
    return web.json_response({"deleted": colony_id, "purged": False})


async def handle_scaffold_colony(request: web.Request) -> web.Response:
    """POST /api/colonies/{colony_id}/scaffold — create a colony folder WITHOUT
    booting its queen.

    Body: ``{"queen_name": "<queen_id>"}`` (optional).

    Writes only ``metadata.json`` + a minimal ``worker.json`` (the same minimal
    bootstrap a fresh colony uses) so the colony is discoverable in the sidebar
    and survives a restart — but spins up no MCP servers and makes no LLM call.
    Used by the free-user flow: the colony persists, and the queen boots only
    when the user upgrades and sends for real.
    """
    colony_id = request.match_info["colony_id"]
    err = _validate_colony_id(colony_id)
    if err:
        return web.json_response({"error": err}, status=400)

    try:
        body = await request.json() if request.can_read_body else {}
    except Exception:
        body = {}
    queen_name = str((body or {}).get("queen_name", "")).strip() or None

    from framework.server.session_manager import _ensure_minimal_colony

    _ensure_minimal_colony(colony_id, queen_name=queen_name)
    # Mark the colony as a queen-less scaffold so the upgrade's
    # create_session (initial_prompt set) reuses this dir instead of
    # deduplicating to "<name>_2" and stranding it as an empty husk. The
    # flag is consumed when the first real session opens the colony.
    try:
        update_colony_metadata(colony_id, {"scaffolded": True})
    except OSError as exc:
        return web.json_response({"error": f"failed to mark colony scaffolded: {exc}"}, status=500)
    logger.info("Scaffolded colony '%s' (no queen boot)", colony_id)
    return web.json_response({"colony_id": colony_id, "scaffolded": True})


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/colonies/import", handle_import_colony)
    # Chunked resumable upload flow — see the /import/{init,chunk,status,
    # finalize} section above for the wire contract. The legacy /import
    # route stays registered so an older client (or the chunked flow's
    # explicit fallback path) still lands somewhere.
    app.router.add_post("/api/colonies/import/init", handle_init_upload)
    app.router.add_put("/api/colonies/import/chunk/{upload_id}", handle_chunk_upload)
    app.router.add_get("/api/colonies/import/status/{upload_id}", handle_upload_status)
    app.router.add_post("/api/colonies/import/finalize/{upload_id}", handle_finalize_upload)
    app.router.add_delete("/api/colonies/import/{upload_id}", handle_cancel_upload)
    app.router.add_post(
        "/api/colonies/{colony_id}/scaffold",
        handle_scaffold_colony,
    )
    app.router.add_delete(
        "/api/colonies/{colony_id}",
        handle_delete_colony,
    )
    app.router.add_post(
        "/api/colonies/{colony_id}/reveal",
        handle_reveal_colony_folder,
    )
    app.router.add_post(
        "/api/colonies/{colony_id}/rename",
        handle_rename_colony,
    )
    app.router.add_get(
        "/api/colonies/{colony_id}/worker_profiles",
        handle_list_worker_profiles,
    )
    app.router.add_post(
        "/api/colonies/{colony_id}/worker_profiles",
        handle_upsert_worker_profile,
    )
    app.router.add_delete(
        "/api/colonies/{colony_id}/worker_profiles/{profile_name}",
        handle_delete_worker_profile,
    )
