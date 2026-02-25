"""Git utilities for per-agent version management.

Each agent in exports/{agent_name}/ can have its own local git repository
for tracking changes, versioning with semver tags, and inspecting history.

All operations use subprocess — no external git library dependency.
"""

import logging
import os
import re
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Semver pattern: v{major}.{minor}.{patch} with optional pre-release
_SEMVER_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

_AGENT_GITIGNORE = """\
__pycache__/
*.pyc
*.pyo
.DS_Store
"""


# ---------------------------------------------------------------------------
# Core primitive
# ---------------------------------------------------------------------------


def git_run(
    repo_dir: Path,
    *args: str,
    timeout: int = 30,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Execute a git command inside *repo_dir*.

    Returns the CompletedProcess. Raises RuntimeError if git is not installed.
    """
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "git is not installed or not on PATH. "
            "Agent versioning requires git."
        )
    except subprocess.TimeoutExpired:
        logger.warning("git command timed out: git %s (in %s)", " ".join(args), repo_dir)
        raise


# ---------------------------------------------------------------------------
# Repo lifecycle
# ---------------------------------------------------------------------------


def is_git_repo(agent_dir: Path) -> bool:
    """Return True if *agent_dir* contains a .git directory."""
    try:
        return (agent_dir / ".git").is_dir()
    except Exception:
        return False


def init_repo(agent_dir: Path) -> None:
    """Idempotent git-init for an agent directory.

    Creates .gitignore, and if files already exist, makes an initial commit.
    """
    if is_git_repo(agent_dir):
        return

    git_run(agent_dir, "init", check=True)

    # Write .gitignore
    gitignore = agent_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_AGENT_GITIGNORE)

    # If there are existing files, create an initial commit
    result = git_run(agent_dir, "status", "--porcelain")
    if result.stdout.strip():
        git_run(agent_dir, "add", "-A")
        git_run(agent_dir, "commit", "-m", "Initial commit")


# ---------------------------------------------------------------------------
# Commit operations
# ---------------------------------------------------------------------------


def has_changes(agent_dir: Path) -> bool:
    """Return True if the working tree has uncommitted changes."""
    if not is_git_repo(agent_dir):
        return False
    result = git_run(agent_dir, "status", "--porcelain")
    return bool(result.stdout.strip())


def commit_all(agent_dir: Path, message: str) -> str | None:
    """Stage all changes and commit.

    Returns the commit SHA on success, or None if there was nothing to commit.
    """
    if not is_git_repo(agent_dir):
        logger.warning("commit_all called on non-git dir: %s", agent_dir)
        return None

    # Check for changes first
    result = git_run(agent_dir, "status", "--porcelain")
    if not result.stdout.strip():
        return None

    git_run(agent_dir, "add", "-A")

    result = git_run(agent_dir, "commit", "-m", message)
    if result.returncode != 0:
        # Retry once on lock contention
        if "index.lock" in (result.stderr or ""):
            time.sleep(0.5)
            result = git_run(agent_dir, "commit", "-m", message)
        if result.returncode != 0:
            logger.warning("git commit failed: %s", result.stderr)
            return None

    sha_result = git_run(agent_dir, "rev-parse", "HEAD")
    return sha_result.stdout.strip() or None


# ---------------------------------------------------------------------------
# Tag / version operations
# ---------------------------------------------------------------------------


def parse_semver(tag: str) -> tuple[int, int, int] | None:
    """Parse a semver tag like 'v1.2.3' into (major, minor, patch).

    Returns None if the tag doesn't match semver format.
    """
    m = _SEMVER_RE.match(tag)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def create_tag(
    agent_dir: Path,
    version: str,
    message: str = "",
) -> None:
    """Create an annotated git tag with semver validation.

    Raises ValueError if the version format is invalid or already exists.
    """
    if parse_semver(version) is None:
        raise ValueError(
            f"Invalid semver tag '{version}'. Expected format: v{{major}}.{{minor}}.{{patch}} (e.g. v1.0.0)"
        )
    if tag_exists(agent_dir, version):
        raise ValueError(f"Tag '{version}' already exists")

    msg = message or version
    result = git_run(agent_dir, "tag", "-a", version, "-m", msg)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create tag: {result.stderr}")


def delete_tag(agent_dir: Path, tag: str) -> None:
    """Delete a git tag."""
    result = git_run(agent_dir, "tag", "-d", tag)
    if result.returncode != 0:
        raise ValueError(f"Tag '{tag}' not found or could not be deleted")


def tag_exists(agent_dir: Path, tag: str) -> bool:
    """Check if a tag exists."""
    result = git_run(agent_dir, "tag", "-l", tag)
    return tag in result.stdout.strip().split("\n")


def list_tags(agent_dir: Path) -> list[dict]:
    """List all tags sorted by semver descending.

    Returns list of {tag, sha, date, message}.
    """
    if not is_git_repo(agent_dir):
        return []

    result = git_run(
        agent_dir,
        "tag",
        "-l",
        "--format=%(refname:short)\t%(objectname:short)\t%(creatordate:iso-strict)\t%(contents:subject)",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    tags = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        if len(parts) < 2:
            continue
        tag_name = parts[0]
        # Only include semver tags
        if parse_semver(tag_name) is None:
            continue
        tags.append({
            "tag": tag_name,
            "sha": parts[1] if len(parts) > 1 else "",
            "date": parts[2] if len(parts) > 2 else "",
            "message": parts[3] if len(parts) > 3 else "",
        })

    # Sort by semver descending
    tags.sort(key=lambda t: parse_semver(t["tag"]) or (0, 0, 0), reverse=True)
    return tags


def latest_version(agent_dir: Path) -> str | None:
    """Return the latest semver tag, or None if no tags exist."""
    tags = list_tags(agent_dir)
    return tags[0]["tag"] if tags else None


def next_version(agent_dir: Path, bump: str = "patch") -> str:
    """Compute the next semver version based on the latest tag.

    Args:
        bump: One of 'patch', 'minor', 'major'.

    Returns:
        The next version string (e.g. 'v1.0.1').
    """
    current = latest_version(agent_dir)
    if current is None:
        return "v0.1.0"

    parsed = parse_semver(current)
    if parsed is None:
        return "v0.1.0"

    major, minor, patch = parsed
    if bump == "major":
        return f"v{major + 1}.0.0"
    elif bump == "minor":
        return f"v{major}.{minor + 1}.0"
    else:  # patch
        return f"v{major}.{minor}.{patch + 1}"


# ---------------------------------------------------------------------------
# History operations
# ---------------------------------------------------------------------------


def get_head(agent_dir: Path) -> dict | None:
    """Get current HEAD commit info.

    Returns {sha, short_sha, message, date, author} or None.
    """
    if not is_git_repo(agent_dir):
        return None

    result = git_run(
        agent_dir,
        "log",
        "-1",
        "--format=%H\t%h\t%s\t%aI\t%an",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    parts = result.stdout.strip().split("\t", 4)
    if len(parts) < 5:
        return None

    return {
        "sha": parts[0],
        "short_sha": parts[1],
        "message": parts[2],
        "date": parts[3],
        "author": parts[4],
    }


def log(
    agent_dir: Path,
    limit: int = 50,
    since_tag: str = "",
) -> list[dict]:
    """Get commit log.

    Returns list of {sha, short_sha, message, date, author, tags}.
    """
    if not is_git_repo(agent_dir):
        return []

    args = [
        "log",
        f"--max-count={limit}",
        "--format=%H\t%h\t%s\t%aI\t%an\t%D",
    ]
    if since_tag:
        args.append(f"{since_tag}..HEAD")

    result = git_run(agent_dir, *args)
    if result.returncode != 0 or not result.stdout.strip():
        return []

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 5)
        if len(parts) < 5:
            continue

        # Extract tags from ref decoration
        refs = parts[5] if len(parts) > 5 else ""
        tags = []
        if refs:
            for ref in refs.split(","):
                ref = ref.strip()
                if ref.startswith("tag: "):
                    tags.append(ref[5:])

        commits.append({
            "sha": parts[0],
            "short_sha": parts[1],
            "message": parts[2],
            "date": parts[3],
            "author": parts[4],
            "tags": tags,
        })

    return commits


# ---------------------------------------------------------------------------
# File inspection at specific refs
# ---------------------------------------------------------------------------


def show_file(agent_dir: Path, ref: str, file_path: str) -> str | None:
    """Read file content at a specific ref (tag, commit SHA, etc.).

    Uses `git show ref:path`. Returns None if the file doesn't exist at that ref.
    """
    if not is_git_repo(agent_dir):
        return None

    result = git_run(agent_dir, "show", f"{ref}:{file_path}")
    if result.returncode != 0:
        return None
    return result.stdout


def list_files_at_ref(agent_dir: Path, ref: str = "HEAD") -> list[str]:
    """List all files tracked at a specific ref.

    Returns a list of relative file paths.
    """
    if not is_git_repo(agent_dir):
        return []

    result = git_run(agent_dir, "ls-tree", "-r", "--name-only", ref)
    if result.returncode != 0:
        return []

    return [f for f in result.stdout.strip().split("\n") if f.strip()]


def diff_between(agent_dir: Path, ref_a: str, ref_b: str) -> str:
    """Get unified diff between two refs.

    Returns the diff output as a string.
    """
    if not is_git_repo(agent_dir):
        return ""

    result = git_run(agent_dir, "diff", ref_a, ref_b)
    return result.stdout if result.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Version export / extraction
# ---------------------------------------------------------------------------


def export_at_ref(
    agent_dir: Path,
    ref: str,
    output_dir: Path | None = None,
) -> Path:
    """Extract the agent files at a specific ref to a directory.

    Uses `git archive` for a clean extraction without .git metadata.
    If output_dir is None, uses ~/.hive/versions/{agent_name}/{ref}/.

    Returns the output directory path.
    """
    if not is_git_repo(agent_dir):
        raise ValueError(f"Not a git repo: {agent_dir}")

    agent_name = agent_dir.name

    if output_dir is None:
        output_dir = Path.home() / ".hive" / "versions" / agent_name / ref

    # Check if already extracted (cache hit)
    if output_dir.exists() and any(output_dir.iterdir()):
        # Verify the ref matches by checking a marker file
        marker = output_dir / ".version_ref"
        if marker.exists() and marker.read_text().strip() == ref:
            return output_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract via git archive piped to tar (binary mode, not text)
    archive = subprocess.run(
        ["git", "archive", ref],
        cwd=str(agent_dir),
        capture_output=True,
        timeout=30,
    )
    if archive.returncode != 0:
        raise ValueError(f"Failed to archive ref '{ref}': {archive.stderr.decode()}")

    extract = subprocess.run(
        ["tar", "xf", "-"],
        cwd=str(output_dir),
        input=archive.stdout,
        capture_output=True,
    )
    if extract.returncode != 0:
        raise RuntimeError(f"Failed to extract archive: {extract.stderr.decode()}")

    # Write marker for cache validation
    (output_dir / ".version_ref").write_text(ref)

    return output_dir
