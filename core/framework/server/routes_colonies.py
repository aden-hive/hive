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
  agents/<name>/worker/...                            → HIVE_HOME/agents/<name>/worker/...
  agents/queens/<queen>/sessions/<sid>/...            → HIVE_HOME/agents/queens/<queen>/sessions/<sid>/...

Anything outside those is rejected. For backwards compat with older clients
that tar `<name>/...` directly (single colony dir, no `colonies/` wrapper),
the handler falls back to the legacy single-root flow when no recognised
multi-root prefix is found.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import tarfile
from pathlib import Path

from aiohttp import web

from framework.config import COLONIES_DIR

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

# 100 MB cap on upload size. The multi-root tar carries worker conversations
# (often 100s of small JSON parts) plus the queen's forked session, so the
# legacy 50 MB ceiling is too tight. Anything bigger probably shouldn't be
# pushed wholesale anyway.
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024

def _agents_dir() -> Path:
    """``COLONIES_DIR`` resolves to ``HIVE_HOME/colonies``; ``agents/`` is
    the sibling. Resolved per-call so tests that monkeypatch
    ``COLONIES_DIR`` propagate without a second patch."""
    return Path(COLONIES_DIR).parent / "agents"


def _validate_colony_name(name: str) -> str | None:
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
        if name.startswith("colonies/") or name.startswith("agents/"):
            return True
    return False


def _normalise_member_name(name: str) -> str:
    """Strip a leading ``./`` if present; reject absolute or empty names."""
    if name.startswith("./"):
        name = name[2:]
    return name


def _safe_extract_tar(
    tf: tarfile.TarFile, dest: Path, *, strip_prefix: str
) -> tuple[int, str | None]:
    """Extract every member of ``tf`` whose name starts with ``strip_prefix/``
    into ``dest``, with the prefix stripped off.

    Each member's resolved path must stay under ``dest``; symlinks, hardlinks,
    and device/fifo entries are rejected. Returns ``(files_extracted, error)``;
    on error the caller is responsible for cleanup.

    Members outside ``strip_prefix`` are silently *skipped* (not an error) so
    the caller can call this multiple times on the same tar with different
    prefixes — once per recognised root.
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
            rel = name[len(prefix_with_sep):]
        else:
            rel = name
        if not rel:
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
        with target.open("wb") as out:
            shutil.copyfileobj(src, out)
        target.chmod(member.mode & 0o755 if member.mode else 0o644)
        files_extracted += 1

    return files_extracted, None


def _classify_multi_root_member(name: str) -> tuple[str, str] | None:
    """Recognise a multi-root tar member and return ``(root, top_dir)``.

    ``root`` is one of ``"colonies"``, ``"agents_worker"``, ``"agents_queen"``;
    ``top_dir`` is the prefix to feed to ``_safe_extract_tar`` (the part of
    the path that should be stripped before joining with the destination
    base). Returns None for members that don't match any recognised root.

    The caller pre-validates segments before extraction, so this is purely
    structural: which root, what the strip prefix should be.
    """
    parts = Path(name).parts
    if not parts:
        return None
    if parts[0] == "colonies" and len(parts) >= 2:
        return ("colonies", f"colonies/{parts[1]}")
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
            err = _validate_colony_name(prefix_parts[1])
            if err:
                return groups, err
            dest = str(COLONIES_DIR / prefix_parts[1])
        elif kind == "agents_worker":
            err = _validate_colony_name(prefix_parts[1])
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
            f"(expected colonies/, agents/<name>/worker/, "
            f"agents/queens/<queen>/sessions/<sid>/; got: {roots})",
        )
    return groups, None


async def _read_upload(
    request: web.Request,
) -> tuple[bytes | None, str | None, dict[str, str], web.Response | None]:
    """Drain the multipart upload. Returns ``(bytes, filename, form, error)``."""
    if not request.content_type.startswith("multipart/"):
        return None, None, {}, web.json_response(
            {"error": "expected multipart/form-data"}, status=400
        )
    reader = await request.multipart()
    upload: bytes | None = None
    upload_filename: str | None = None
    form: dict[str, str] = {}
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            buf = io.BytesIO()
            while True:
                chunk = await part.read_chunk(size=65536)
                if not chunk:
                    break
                buf.write(chunk)
                if buf.tell() > _MAX_UPLOAD_BYTES:
                    return None, None, {}, web.json_response(
                        {"error": f"upload exceeds {_MAX_UPLOAD_BYTES} bytes"},
                        status=413,
                    )
            upload = buf.getvalue()
            upload_filename = part.filename or ""
        else:
            form[part.name or ""] = (await part.text()).strip()
    if upload is None:
        return None, None, {}, web.json_response(
            {"error": "missing 'file' part"}, status=400
        )
    return upload, upload_filename, form, None


async def handle_import_colony(request: web.Request) -> web.Response:
    """POST /api/colonies/import — unpack a colony tarball into HIVE_HOME."""
    upload, upload_filename, form, err_resp = await _read_upload(request)
    if err_resp is not None:
        return err_resp
    assert upload is not None  # for the type checker

    replace_existing = form.get("replace_existing", "false").lower() == "true"
    name_override = form.get("name", "").strip() or None

    try:
        tf = tarfile.open(fileobj=io.BytesIO(upload), mode="r:*")
    except tarfile.TarError as err:
        return web.json_response(
            {"error": f"invalid tar archive: {err}"}, status=400
        )

    try:
        if _has_multi_root_prefix(tf):
            return await _import_multi_root(
                tf, replace_existing, upload_filename, len(upload)
            )
        return await _import_legacy_single_root(
            tf, name_override, replace_existing, upload_filename, len(upload)
        )
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

    colony_name = name_override or top
    name_err = _validate_colony_name(colony_name)
    if name_err:
        return web.json_response({"error": name_err}, status=400)

    target = COLONIES_DIR / colony_name
    if target.exists():
        if not replace_existing:
            return web.json_response(
                {
                    "error": "colony already exists",
                    "name": colony_name,
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
        colony_name,
        files_extracted,
        upload_filename or "<unnamed>",
        upload_size,
    )
    return web.json_response(
        {
            "name": colony_name,
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
    """
    plan, plan_err = _plan_multi_root(tf)
    if plan_err:
        return web.json_response({"error": plan_err}, status=400)

    # Conflict guard for the colonies root only — these are user-visible
    # entities the desktop expects to control overwrite of.
    primary_colony_name: str | None = None
    primary_colony_target: Path | None = None
    for prefix, dest in plan["colonies"].items():
        target = Path(dest)
        primary_colony_name = Path(prefix).parts[1]
        primary_colony_target = target
        if target.exists() and not replace_existing:
            return web.json_response(
                {
                    "error": "colony already exists",
                    "name": primary_colony_name,
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

    for kind in ("colonies", "agents_worker", "agents_queen"):
        for prefix, dest in plan[kind].items():
            target = Path(dest)
            files_extracted, extract_err = _safe_extract_tar(
                tf, target, strip_prefix=prefix
            )
            if extract_err:
                return _abort(extract_err)
            summary.setdefault(kind, {"files": 0})
            summary[kind]["files"] = (
                int(summary[kind].get("files", 0)) + files_extracted
            )
            extracted_dests.append(target)

    total_files = sum(int(v.get("files", 0)) for v in summary.values())
    logger.info(
        "Imported colony %s (%d files across %d roots) from upload %s (%d bytes)",
        primary_colony_name or "<unknown>",
        total_files,
        sum(1 for v in summary.values() if int(v.get("files", 0)) > 0),
        upload_filename or "<unnamed>",
        upload_size,
    )

    return web.json_response(
        {
            "name": primary_colony_name,
            "path": str(primary_colony_target) if primary_colony_target else None,
            "files_imported": total_files,
            "by_root": summary,
            "replaced": replace_existing,
        },
        status=201,
    )


def register_routes(app: web.Application) -> None:
    app.router.add_post("/api/colonies/import", handle_import_colony)
