"""Trust gating for project-level skills (PRD AS-13).

Project-level skills from untrusted repositories require explicit user consent
before their instructions are loaded into the agent's system prompt.
Framework and user-scope skills are always trusted.

Trusted repos are persisted at ~/.hive/trusted_repos.json.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

from framework.skills.parser import ParsedSkill

logger = logging.getLogger(__name__)

# Env var to bypass trust gating in CI/headless pipelines (opt-in).
_ENV_TRUST_ALL = "HIVE_TRUST_PROJECT_SKILLS"

# Env var for comma-separated own-remote glob patterns (e.g. "github.com/myorg/*").
_ENV_OWN_REMOTES = "HIVE_OWN_REMOTES"

_TRUSTED_REPOS_PATH = Path.home() / ".hive" / "trusted_repos.json"
_NOTICE_SENTINEL_PATH = Path.home() / ".hive" / ".skill_trust_notice_shown"


# ---------------------------------------------------------------------------
# Trusted repo store
# ---------------------------------------------------------------------------


@dataclass
class TrustedRepoEntry:
    repo_key: str
    added_at: datetime
    project_path: str = ""


class TrustedRepoStore:
    """Persists permanently-trusted repo keys to ~/.hive/trusted_repos.json."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _TRUSTED_REPOS_PATH
        self._entries: dict[str, TrustedRepoEntry] = {}
        self._loaded = False

    def is_trusted(self, repo_key: str) -> bool:
        self._ensure_loaded()
        return repo_key in self._entries

    def trust(self, repo_key: str, project_path: str = "") -> None:
        self._ensure_loaded()
        self._entries[repo_key] = TrustedRepoEntry(
            repo_key=repo_key,
            added_at=datetime.now(tz=UTC),
            project_path=project_path,
        )
        self._save()
        logger.info("skill_trust_store: trusted repo_key=%s", repo_key)

    def revoke(self, repo_key: str) -> bool:
        self._ensure_loaded()
        if repo_key in self._entries:
            del self._entries[repo_key]
            self._save()
            logger.info("skill_trust_store: revoked repo_key=%s", repo_key)
            return True
        return False

    def list_entries(self) -> list[TrustedRepoEntry]:
        self._ensure_loaded()
        return list(self._entries.values())

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for raw in data.get("entries", []):
                repo_key = raw.get("repo_key", "")
                if not repo_key:
                    continue
                try:
                    added_at = datetime.fromisoformat(raw["added_at"])
                except (KeyError, ValueError):
                    added_at = datetime.now(tz=UTC)
                self._entries[repo_key] = TrustedRepoEntry(
                    repo_key=repo_key,
                    added_at=added_at,
                    project_path=raw.get("project_path", ""),
                )
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning(
                "skill_trust_store: could not read %s (%s); treating as empty",
                self._path,
                e,
            )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "entries": [
                {
                    "repo_key": e.repo_key,
                    "added_at": e.added_at.isoformat(),
                    "project_path": e.project_path,
                }
                for e in self._entries.values()
            ],
        }
        # Atomic write: write to .tmp then rename
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)


# ---------------------------------------------------------------------------
# Trust classification
# ---------------------------------------------------------------------------


class ProjectTrustClassification(StrEnum):
    ALWAYS_TRUSTED = "always_trusted"
    TRUSTED_BY_USER = "trusted_by_user"
    UNTRUSTED = "untrusted"


class ProjectTrustDetector:
    """Classifies a project directory as trusted or untrusted.

    Algorithm (PRD §4.1 trust note):
    1. No project_dir               → ALWAYS_TRUSTED
    2. No .git directory            → ALWAYS_TRUSTED (not a git repo)
    3. No remote 'origin'           → ALWAYS_TRUSTED (local-only repo)
    4. Remote URL → repo_key; in TrustedRepoStore → TRUSTED_BY_USER
    5. Localhost remote             → ALWAYS_TRUSTED
    6. ~/.hive/own_remotes match    → ALWAYS_TRUSTED
    7. HIVE_OWN_REMOTES env match   → ALWAYS_TRUSTED
    8. None of the above            → UNTRUSTED
    """

    def __init__(self, store: TrustedRepoStore | None = None) -> None:
        self._store = store or TrustedRepoStore()

    def classify(self, project_dir: Path | None) -> tuple[ProjectTrustClassification, str]:
        """Return (classification, repo_key).

        repo_key is empty string for ALWAYS_TRUSTED cases without a remote.
        """
        if project_dir is None or not project_dir.exists():
            return ProjectTrustClassification.ALWAYS_TRUSTED, ""

        if not (project_dir / ".git").exists():
            return ProjectTrustClassification.ALWAYS_TRUSTED, ""

        remote_url = self._get_remote_origin(project_dir)
        if not remote_url:
            return ProjectTrustClassification.ALWAYS_TRUSTED, ""

        repo_key = _normalize_remote_url(remote_url)

        # Explicitly trusted by user
        if self._store.is_trusted(repo_key):
            return ProjectTrustClassification.TRUSTED_BY_USER, repo_key

        # Localhost remotes are always trusted
        if _is_localhost_remote(remote_url):
            return ProjectTrustClassification.ALWAYS_TRUSTED, repo_key

        # User-configured own-remote patterns
        if self._matches_own_remotes(repo_key):
            return ProjectTrustClassification.ALWAYS_TRUSTED, repo_key

        return ProjectTrustClassification.UNTRUSTED, repo_key

    def _get_remote_origin(self, project_dir: Path) -> str:
        """Run git remote get-url origin. Returns empty string on any failure."""
        try:
            result = subprocess.run(
                ["git", "-C", str(project_dir), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.warning(
                "skill_trust: git remote lookup timed out for %s; treating as trusted",
                project_dir,
            )
        except (FileNotFoundError, OSError):
            pass  # git not found or other OS error
        return ""

    def _matches_own_remotes(self, repo_key: str) -> bool:
        """Check repo_key against user-configured own-remote glob patterns."""
        import fnmatch

        patterns: list[str] = []

        # From env var
        env_patterns = _ENV_OWN_REMOTES
        import os

        raw = os.environ.get(env_patterns, "")
        if raw:
            patterns.extend(p.strip() for p in raw.split(",") if p.strip())

        # From ~/.hive/own_remotes file
        own_remotes_file = Path.home() / ".hive" / "own_remotes"
        if own_remotes_file.is_file():
            try:
                for line in own_remotes_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
            except OSError:
                pass

        return any(fnmatch.fnmatch(repo_key, p) for p in patterns)


# ---------------------------------------------------------------------------
# URL helpers (public so CLI can reuse)
# ---------------------------------------------------------------------------


def _normalize_remote_url(url: str) -> str:
    """Normalize a git remote URL to a canonical ``host/org/repo`` key.

    Examples:
        git@github.com:org/repo.git  → github.com/org/repo
        https://github.com/org/repo  → github.com/org/repo
        ssh://git@github.com/org/repo.git → github.com/org/repo
    """
    url = url.strip()

    # SCP-style SSH: git@github.com:org/repo.git
    if url.startswith("git@") and ":" in url and "://" not in url:
        url = url[4:]  # strip git@
        url = url.replace(":", "/", 1)
    elif "://" in url:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path.lstrip("/")
        url = f"{host}/{path}"

    # Strip .git suffix
    if url.endswith(".git"):
        url = url[:-4]

    return url.lower().strip("/")


def _is_localhost_remote(remote_url: str) -> bool:
    """Return True if the remote points to a local host."""
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    try:
        if "://" in remote_url:
            parsed = urlparse(remote_url)
            return (parsed.hostname or "").lower() in local_hosts
        # SCP-style: git@localhost:org/repo
        if "@" in remote_url:
            host_part = remote_url.split("@", 1)[1].split(":")[0]
            return host_part.lower() in local_hosts
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Trust gate
# ---------------------------------------------------------------------------


class TrustGate:
    """Filters skill list, running consent flow for untrusted project-scope skills.

    Framework and user-scope skills are always allowed through.
    Project-scope skills from untrusted repos require consent.
    """

    def __init__(
        self,
        store: TrustedRepoStore | None = None,
        detector: ProjectTrustDetector | None = None,
        interactive: bool = True,
        print_fn: Callable[[str], None] | None = None,
        input_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._store = store or TrustedRepoStore()
        self._detector = detector or ProjectTrustDetector(self._store)
        self._interactive = interactive
        self._print = print_fn or print
        self._input = input_fn or input

    def filter_and_gate(
        self,
        skills: list[ParsedSkill],
        project_dir: Path | None,
    ) -> list[ParsedSkill]:
        """Return the subset of skills that are trusted for loading.

        - Framework, user, queen_ui, and colony_ui scopes: always included.
          (UI-created skills are authenticated by the user creating them
          through the authenticated UI — they do not go through the
          trusted_repos.json flow.)
        - Project-scope skills: classified; consent prompt shown if untrusted.
        """
        import os

        # UI-authored scopes bypass the trust gate — they're implicitly
        # trusted because the user authored them through the UI. ``preset``
        # ships with the framework distribution, so it's trusted too.
        _bypass_scopes = {"framework", "preset", "user", "queen_ui", "colony_ui"}
        always_trusted = [s for s in skills if s.source_scope in _bypass_scopes]
        project_skills = [s for s in skills if s.source_scope == "project"]

        if not project_skills:
            return always_trusted

        # Env-var CI override: trust all project skills for this invocation
        if os.environ.get(_ENV_TRUST_ALL, "").strip() == "1":
            logger.info(
                "skill_trust: %s=1 set; trusting %d project skill(s) without consent",
                _ENV_TRUST_ALL,
                len(project_skills),
            )
            return always_trusted + project_skills

        classification, repo_key = self._detector.classify(project_dir)

        if classification in (
            ProjectTrustClassification.ALWAYS_TRUSTED,
            ProjectTrustClassification.TRUSTED_BY_USER,
        ):
            logger.info(
                "skill_trust: project skills trusted classification=%s repo=%s count=%d",
                classification,
                repo_key or "(no remote)",
                len(project_skills),
            )
            return always_trusted + project_skills

        # UNTRUSTED — need consent
        if not self._interactive or not sys.stdin.isatty():
            logger.warning(
                "skill_trust: skipping %d project-scope skill(s) from untrusted repo "
                "'%s' (non-interactive mode). "
                "To trust permanently run: hive skill trust %s",
                len(project_skills),
                repo_key,
                project_dir or ".",
            )
            logger.info(
                "skill_trust_decision repo=%s skills=%d decision=denied mode=headless",
                repo_key,
                len(project_skills),
            )
            return always_trusted

        # Interactive consent flow
        decision = self._run_consent_flow(project_skills, project_dir, repo_key)

        logger.info(
            "skill_trust_decision repo=%s skills=%d decision=%s mode=interactive",
            repo_key,
            len(project_skills),
            decision,
        )

        if decision == "session":
            return always_trusted + project_skills

        if decision == "permanent":
            self._store.trust(repo_key, project_path=str(project_dir or ""))
            return always_trusted + project_skills

        # denied
        return always_trusted

    def _run_consent_flow(
        self,
        project_skills: list[ParsedSkill],
        project_dir: Path | None,
        repo_key: str,
    ) -> str:
        """Show the security notice (once) and consent prompt.
        Return 'session' | 'permanent' | 'denied'."""
        from framework.credentials.setup import Colors

        if not sys.stdout.isatty():
            Colors.disable()

        self._maybe_show_security_notice(Colors)
        self._print_consent_prompt(project_skills, project_dir, repo_key, Colors)
        return self._prompt_consent(Colors)

    def _maybe_show_security_notice(self, Colors) -> None:  # noqa: N803
        """Show the one-time security notice if not already shown (NFR-5)."""
        if _NOTICE_SENTINEL_PATH.exists():
            return
        self._print("")
        self._print(
            f"{Colors.YELLOW}Security notice:{Colors.NC} Skills inject instructions into the agent's system prompt."
        )
        self._print(
            "  Only load skills from sources you trust. "
            "Registry skills at tier 'verified' or 'official' have been audited."
        )
        self._print("")
        try:
            _NOTICE_SENTINEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            _NOTICE_SENTINEL_PATH.touch()
        except OSError:
            pass

    def _print_consent_prompt(
        self,
        project_skills: list[ParsedSkill],
        project_dir: Path | None,
        repo_key: str,
        Colors,  # noqa: N803
    ) -> None:
        p = self._print
        p("")
        p(f"{Colors.YELLOW}{'=' * 60}{Colors.NC}")
        p(f"{Colors.BOLD}  SKILL TRUST REQUIRED{Colors.NC}")
        p(f"{Colors.YELLOW}{'=' * 60}{Colors.NC}")
        p("")
        proj_label = str(project_dir) if project_dir else "this project"
        p(f"  The project at {Colors.CYAN}{proj_label}{Colors.NC} wants to load {len(project_skills)} skill(s)")
        p("  that will inject instructions into the agent's system prompt.")
        if repo_key:
            p(f"  Source: {Colors.BOLD}{repo_key}{Colors.NC}")
        p("")
        p("  Skills requesting access:")
        for skill in project_skills:
            p(f"    {Colors.CYAN}•{Colors.NC} {Colors.BOLD}{skill.name}{Colors.NC}")
            p(f'      "{skill.description}"')
            p(f"      {Colors.DIM}{skill.location}{Colors.NC}")
        p("")
        p("  Options:")
        p(f"    {Colors.CYAN}1){Colors.NC} Trust this session only")
        p(f"    {Colors.CYAN}2){Colors.NC} Trust permanently  — remember for future runs")
        p(f"    {Colors.DIM}3) Deny              — skip all project-scope skills from this repo{Colors.NC}")
        p(f"{Colors.YELLOW}{'─' * 60}{Colors.NC}")

    def _prompt_consent(self, Colors) -> str:  # noqa: N803
        """Prompt until a valid choice is entered. Returns 'session'|'permanent'|'denied'."""
        mapping = {"1": "session", "2": "permanent", "3": "denied"}
        while True:
            try:
                choice = self._input("Select option (1-3): ").strip()
                if choice in mapping:
                    return mapping[choice]
            except (KeyboardInterrupt, EOFError):
                return "denied"
            self._print(f"{Colors.RED}Invalid choice. Enter 1, 2, or 3.{Colors.NC}")
