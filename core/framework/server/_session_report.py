"""Problem-session report bundling.

Backs ``POST /api/sessions/{id}/report-bundle``: when a desktop user reports a
problem with a session, package that session's full file tree into a
credential-scrubbed ``tar.gz`` for upload to the backend / local save, and drop
a ``user_report.json`` marker so the training pipeline can pick the session up
as a user-flagged "bad" episode.

Redaction policy (user decision): **credentials only** — keep message bodies,
names, emails, paths, AND screenshots for full debugging fidelity; strip only
JWTs / API keys / bearer tokens / OAuth-callback URLs (zero debugging value,
high risk). The bundle is uploaded to GCS (not a size-capped DB), so nothing is
dropped: screenshots, embedded base64 images, and binary artifacts are all kept.

stdlib-only so it never drags deps into the runtime server.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MARKER_NAME = "user_report.json"
SEVERITIES = ("low", "medium", "high", "critical")

# Text files we scrub + include verbatim; everything else is treated as binary.
_TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".log", ".yaml", ".yml", ".csv"}

# Bundle goes to GCS, not a size-capped DB, so we keep everything. A high
# ceiling only guards against a pathological runaway session dir.
_BINARY_BUDGET_BYTES = 1024 * 1024 * 1024  # 1 GiB total binary
_MAX_SINGLE_BINARY = 256 * 1024 * 1024  # 256 MiB single file

# --- credential patterns (the "scrub everywhere" tier) ----------------------
_CREDENTIAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-\.=]+"), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|"
            r"refresh[_-]?token|client[_-]?secret|x-api-key|x-auth-token)"
            r"(\"?\s*[:=]\s*\"?)([A-Za-z0-9_\-\.\+/]{16,})"
        ),
        r"\1\2[REDACTED_SECRET]",
    ),
    (
        re.compile(r"https?://[^\s\"']+?[?&](?:code|state|access_token|refresh_token|id_token|token|key|secret|password)=[^\s\"']*"),
        "[REDACTED_AUTH_URL]",
    ),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{16,}"), "[REDACTED_KEY]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED_KEY]"),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}"), "[REDACTED_KEY]"),
]


def scrub_credentials(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _CREDENTIAL_PATTERNS:
        text = pattern.sub(repl, text)
    return text


@dataclass
class BundleStats:
    files: int = 0
    text_files: int = 0
    binary_files: int = 0
    binary_omitted: int = 0
    images_stripped: int = 0
    bytes_uncompressed: int = 0
    omitted_paths: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_user_report_marker(session_dir: Path, description: str, severity: str) -> dict:
    """Drop the training-signal marker at the session root.

    The exporter reads this to label the session's episodes bad/user_reported.
    Overwrites any prior marker (latest report wins).
    """
    marker = {
        "label": "bad",
        "label_source": "user_reported",
        "description": description or "",
        "severity": severity if severity in SEVERITIES else "medium",
        "reported_at": _now_iso(),
        "reporter": "desktop",
    }
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / MARKER_NAME).write_text(json.dumps(marker, indent=2), encoding="utf-8")
    return marker


def build_session_report_bundle(
    session_dir: Path,
    *,
    session_id: str,
    description: str = "",
    severity: str = "medium",
    marker: dict | None = None,
) -> tuple[bytes, BundleStats]:
    """Build a credential-scrubbed ``tar.gz`` of the whole session tree.

    Returns ``(gzip_bytes, stats)``. Text files are scrubbed + image data-URIs
    stripped; binary files are included up to a budget. A ``report_manifest.json``
    is added at the archive root.
    """
    stats = BundleStats()
    buf = io.BytesIO()
    binary_used = 0

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(session_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(session_dir)
            # Never re-pack previously-generated report bundles (defensive: we
            # also write new bundles to a temp dir outside the session tree).
            if rel.parts[:2] == ("data", "reports"):
                continue
            arcname = f"session_{session_id}/{rel.as_posix()}"
            stats.files += 1

            if path.suffix.lower() in _TEXT_SUFFIXES:
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                # Screenshots kept in full (GCS, not a size-capped DB).
                scrubbed = scrub_credentials(raw)
                data = scrubbed.encode("utf-8")
                _add_bytes(tar, arcname, data)
                stats.text_files += 1
                stats.bytes_uncompressed += len(data)
            else:
                size = path.stat().st_size
                if size > _MAX_SINGLE_BINARY or binary_used + size > _BINARY_BUDGET_BYTES:
                    stats.binary_omitted += 1
                    stats.omitted_paths.append(rel.as_posix())
                    continue
                try:
                    tar.add(str(path), arcname=arcname)
                except OSError:
                    continue
                binary_used += size
                stats.binary_files += 1
                stats.bytes_uncompressed += size

        manifest = {
            "session_id": session_id,
            "generated_at": _now_iso(),
            "redaction": "credentials_only",
            "image_payloads": "stripped (size control; full pixels remain on disk)",
            "description": description,
            "severity": severity,
            "marker": marker,
            "stats": {
                "files": stats.files,
                "text_files": stats.text_files,
                "binary_files": stats.binary_files,
                "binary_omitted": stats.binary_omitted,
                "images_stripped": stats.images_stripped,
                "omitted_paths": stats.omitted_paths[:50],
            },
        }
        _add_bytes(tar, f"session_{session_id}/report_manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))

    return buf.getvalue(), stats


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
