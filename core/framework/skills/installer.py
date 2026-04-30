"""Skill install, remove, and fork operations.

Handles filesystem operations for the hive skill CLI:
  - install_from_git:      git clone --depth=1 → copy to target directory
  - install_from_registry: resolve registry entry → delegate to install_from_git
  - remove_skill:          delete a skill from ~/.hive/skills/
  - fork_skill:            copy a skill to a new location with a new name
  - maybe_show_install_notice: one-time security notice on first install (NFR-5)
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from framework.config import HIVE_HOME
from framework.skills.parser import ParsedSkill
from framework.skills.skill_errors import SkillError, SkillErrorCode

# Default install destination for user-scope skills.
# Anchored on HIVE_HOME so the desktop shell can override the install
# root via $HIVE_HOME without patching every call site.
USER_SKILLS_DIR = HIVE_HOME / "skills"

# Sentinel file for the one-time security notice on first install (NFR-5).
INSTALL_NOTICE_SENTINEL = HIVE_HOME / ".install_notice_shown"


_INSTALL_NOTICE = """\
─────────────────────────────────────────────────────────────
  Security Notice: Installing Third-Party Skills
─────────────────────────────────────────────────────────────
  Skills are instructions executed by AI agents. A malicious
  skill can manipulate agent behavior, exfiltrate data, or
  cause unintended actions.

  Only install skills from sources you trust. Review the
  SKILL.md before running it in a production environment.

  This notice is shown once. Use 'hive skill doctor' to audit
  installed skills at any time.
─────────────────────────────────────────────────────────────
"""


def maybe_show_install_notice() -> None:
    """Print a one-time security notice before the first skill install (NFR-5).

    Touches a sentinel file in $HIVE_HOME after showing the notice so it is
    only displayed once across all future installs.
    """
    if INSTALL_NOTICE_SENTINEL.exists():
        return
    print(_INSTALL_NOTICE, flush=True)
    try:
        INSTALL_NOTICE_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        INSTALL_NOTICE_SENTINEL.touch()
    except OSError:
        pass  # If we can't write the sentinel, just show the notice every time


def install_from_git(
    git_url: str,
    skill_name: str,
    subdirectory: str | None = None,
    version: str | None = None,
    target_dir: Path | None = None,
) -> Path:
    """Install a skill from a git repository.

    Clones the repository with --depth=1 into a temporary directory, then
    copies the skill subdirectory (or repo root) to the target location.

    Args:
        git_url:     Git repository URL to clone.
        skill_name:  Name of the skill — used as the install directory name.
        subdirectory: Relative path within the repo to the skill directory.
                     If None, the repo root is treated as the skill directory.
        version:     Git ref to checkout (tag, branch, or commit). Defaults to
                     the remote's default branch.
        target_dir:  Where to install the skill. Defaults to
                     ~/.hive/skills/<skill_name>/.

    Returns:
        Path to the installed skill directory (the parent of SKILL.md).

    Raises:
        SkillError: On any failure (git not found, clone failed, SKILL.md missing).
    """
    if shutil.which("git") is None:
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"Cannot install '{skill_name}' from {git_url}",
            why="git is not installed or not on PATH.",
            fix="Install git (https://git-scm.com/) and retry.",
        )

    dest = (target_dir or USER_SKILLS_DIR) / skill_name
    if dest.exists():
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"Cannot install '{skill_name}'",
            why=f"Directory already exists: {dest}",
            fix=f"Run 'hive skill remove {skill_name}' first, or use a different --name.",
        )

    tmp_dir = tempfile.mkdtemp(prefix="hive-skill-install-")
    try:
        _git_clone_shallow(git_url, Path(tmp_dir), version=version)

        # Locate the skill within the cloned repo
        source_dir = Path(tmp_dir) / subdirectory if subdirectory else Path(tmp_dir)
        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            raise SkillError(
                code=SkillErrorCode.SKILL_NOT_FOUND,
                what=f"No SKILL.md found in '{subdirectory or '/'}' of {git_url}",
                why="The expected SKILL.md file is not present at the given path.",
                fix=(
                    "Check the repository structure and use "
                    "'hive skill install --from <url>' with the correct subdirectory."
                ),
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        _copy_skill_dir(source_dir, dest)
        return dest

    except SkillError:
        raise
    except Exception as exc:
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"Failed to install '{skill_name}' from {git_url}",
            why=str(exc),
            fix="Check the URL, your network connection, and git configuration.",
        ) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def install_from_registry(
    registry_entry: dict,
    target_dir: Path | None = None,
    version: str | None = None,
) -> Path:
    """Install a skill using a registry index entry.

    Resolves the git_url and subdirectory from the registry entry and
    delegates to install_from_git.

    Args:
        registry_entry: A skill entry dict from skill_index.json.
        target_dir:     Override install destination.
        version:        Override version (defaults to entry's 'version' field).

    Returns:
        Path to the installed skill directory.

    Raises:
        SkillError: If the registry entry is missing required fields or install fails.
    """
    name = registry_entry.get("name")
    git_url = registry_entry.get("git_url")

    if not name or not git_url:
        raise SkillError(
            code=SkillErrorCode.SKILL_NOT_FOUND,
            what="Incomplete registry entry — missing 'name' or 'git_url'.",
            why="The registry index entry does not contain all required fields.",
            fix="Report this issue to the registry maintainer.",
        )

    resolved_version = version or registry_entry.get("version")
    subdirectory = registry_entry.get("subdirectory")

    return install_from_git(
        git_url=git_url,
        skill_name=str(name),
        subdirectory=subdirectory,
        version=resolved_version,
        target_dir=target_dir,
    )


def remove_skill(name: str, skills_dir: Path | None = None) -> bool:
    """Remove an installed skill from the user skills directory.

    Args:
        name:       Skill directory name to remove.
        skills_dir: Override the search directory (default: ~/.hive/skills/).

    Returns:
        True if removed, False if not found.

    Raises:
        SkillError: If the directory exists but cannot be removed.
    """
    target = (skills_dir or USER_SKILLS_DIR) / name
    if not target.exists():
        return False
    try:
        shutil.rmtree(target)
        return True
    except OSError as exc:
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"Failed to remove skill '{name}' at {target}",
            why=str(exc),
            fix="Check file permissions and try again.",
        ) from exc


def fork_skill(
    source: ParsedSkill,
    new_name: str,
    target_dir: Path,
) -> Path:
    """Create a local editable copy of a skill with a new name.

    Copies the skill's base directory to target_dir/new_name/ and rewrites
    the 'name' field in the copied SKILL.md frontmatter.

    Args:
        source:     The source skill to fork (from SkillDiscovery).
        new_name:   Name for the forked skill.
        target_dir: Parent directory for the fork (e.g. ~/.hive/skills/).

    Returns:
        Path to the forked skill directory.

    Raises:
        SkillError: If the target already exists or the copy fails.
    """
    dest = target_dir / new_name
    if dest.exists():
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"Cannot fork to '{dest}'",
            why="Target directory already exists.",
            fix=f"Choose a different --name or remove '{dest}' first.",
        )

    source_dir = Path(source.base_dir)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _copy_skill_dir(source_dir, dest)
    except OSError as exc:
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"Failed to fork skill '{source.name}' to '{dest}'",
            why=str(exc),
            fix="Check file permissions and available disk space.",
        ) from exc

    # Rewrite the name in the forked SKILL.md via YAML round-trip (safe)
    forked_skill_md = dest / "SKILL.md"
    if forked_skill_md.exists():
        _rewrite_name_in_skill_md(forked_skill_md, new_name)

    return dest


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _git_clone_shallow(git_url: str, target: Path, version: str | None = None) -> None:
    """Clone a git repo at --depth=1 into target directory.

    Args:
        git_url: Repository URL.
        target:  Destination directory (will be created by git).
        version: Optional git ref (branch/tag) to clone.

    Raises:
        SkillError: If the clone fails.
    """
    cmd = ["git", "clone", "--depth=1"]
    if version:
        cmd += ["--branch", version]
    cmd += [git_url, str(target)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"git clone timed out for {git_url}",
            why="The clone operation took longer than 60 seconds.",
            fix="Check your network connection and retry.",
        ) from None
    except (FileNotFoundError, OSError) as exc:
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"Cannot run git for {git_url}",
            why=str(exc),
            fix="Ensure git is installed and on PATH.",
        ) from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise SkillError(
            code=SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"git clone failed for {git_url}",
            why=stderr or f"git exited with code {result.returncode}",
            fix="Check the URL is correct and the repository is publicly accessible.",
        )


def _copy_skill_dir(src: Path, dst: Path) -> None:
    """Copy a skill directory, ignoring VCS and cache artifacts."""
    ignore = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "venv", "node_modules")
    shutil.copytree(src, dst, ignore=ignore)


def _rewrite_name_in_skill_md(skill_md: Path, new_name: str) -> None:
    """Rewrite the 'name' field in a SKILL.md frontmatter via YAML round-trip.

    Parses the frontmatter with yaml.safe_load, updates 'name', re-serializes
    with yaml.dump, and reconstructs the file as:
        ---
        <yaml>
        ---
        <body>

    Falls back to no-op if the file can't be parsed (the copy is still usable).
    """
    import yaml

    try:
        content = skill_md.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        if len(parts) < 3:
            return
        frontmatter = yaml.safe_load(parts[1].strip())
        if not isinstance(frontmatter, dict):
            return
        frontmatter["name"] = new_name
        new_yaml = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
        new_content = f"---\n{new_yaml}---\n{parts[2]}"
        skill_md.write_text(new_content, encoding="utf-8")
    except Exception:
        pass  # Degraded: forked copy works, name just isn't updated
