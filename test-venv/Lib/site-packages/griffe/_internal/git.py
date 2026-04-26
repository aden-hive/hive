# This module contains Git utilities, used by our [`load_git`][griffe.load_git] function,
# which in turn is used to load the API for different snapshots of a Git repository
# and find breaking changes between them.

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit, urlunsplit

from griffe._internal.exceptions import BuiltinModuleError, GitError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from griffe._internal.models import Module


_WORKTREE_PREFIX = "griffe-worktree-"


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[^\w]+", "-", value)
    return re.sub(r"[-\s]+", "-", value).strip("-")


def _git(*args: str, check: bool = True) -> str:
    process = subprocess.run(
        ["git", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf8",
    )
    if check and process.returncode != 0:
        raise GitError(process.stdout.strip())
    return process.stdout.strip()


def _assert_git_repo(path: str | Path) -> None:
    """Deprecated. Assert that a directory is a Git repository.

    Parameters:
        path: Path to a directory.

    Raises:
        OSError: When the directory is not a Git repository.
    """
    if not shutil.which("git"):
        raise RuntimeError("Could not find git executable. Please install git.")
    try:
        _git("-C", str(path), "rev-parse", "--is-inside-work-tree")
    except GitError as error:
        raise OSError(f"Not a git repository: {path}") from error


def _get_latest_tag(repo: str | Path) -> str:
    """Deprecated. Get latest tag of a Git repository.

    Parameters:
        repo: The path to Git repository.

    Returns:
        The latest tag.
    """
    if isinstance(repo, str):
        repo = Path(repo)
    if not repo.is_dir():
        repo = repo.parent
    try:
        output = _git("tag", "-l", "--sort=-creatordate")
    except GitError as error:
        raise GitError(f"Cannot list Git tags in {repo}: {error or 'no tags'}") from error
    return output.split("\n", 1)[0]


def _get_repo_root(repo: str | Path) -> Path:
    """Deprecated. Get the root of a Git repository.

    Parameters:
        repo: The path to a Git repository.

    Returns:
        The root of the repository.
    """
    if isinstance(repo, str):
        repo = Path(repo)
    if not repo.is_dir():
        repo = repo.parent
    return Path(_git("-C", str(repo), "rev-parse", "--show-toplevel"))


@contextmanager
def _tmp_worktree(repo: str | Path = ".", ref: str = "HEAD") -> Iterator[Path]:
    """Deprecated. Context manager that checks out the given reference in the given repository to a temporary worktree.

    Parameters:
        repo: Path to the repository (i.e. the directory *containing* the `.git` directory)
        ref: A Git reference such as a commit, tag or branch.

    Yields:
        The path to the temporary worktree.

    Raises:
        OSError: If `repo` is not a valid `.git` repository
        RuntimeError: If the `git` executable is unavailable, or if it cannot create a worktree
    """
    _assert_git_repo(repo)
    repo_name = Path(repo).resolve().name
    normref = _normalize(ref)  # Branch names can contain slashes.
    with TemporaryDirectory(prefix=f"{_WORKTREE_PREFIX}{repo_name}-{normref}-") as tmp_dir:
        location = os.path.join(tmp_dir, normref)  # noqa: PTH118
        tmp_branch = f"griffe-{normref}"  # Temporary branch name must not already exist.
        try:
            _git("-C", str(repo), "worktree", "add", "-b", tmp_branch, location, ref)
        except GitError as error:
            raise RuntimeError(f"Could not create git worktree: {error}") from error

        try:
            yield Path(location)
        finally:
            _git("-C", str(repo), "worktree", "remove", location, check=False)
            _git("-C", str(repo), "worktree", "prune", check=False)
            _git("-C", str(repo), "branch", "-D", tmp_branch, check=False)


def _get_git_remote_url(repo: str | Path = ".") -> str:
    if git_url := os.getenv("GRIFFE_GIT_REMOTE_URL"):
        return git_url

    remote = "remote." + os.getenv("GRIFFE_GIT_REMOTE", "origin") + ".url"
    git_url = _git("-C", str(repo), "config", "--default", "", "--get", remote)
    if git_url.startswith("git@"):
        git_url = git_url.replace(":", "/", 1).replace("git@", "https://", 1)
    git_url = git_url.removesuffix(".git")

    # Remove credentials from the URL.
    if git_url.startswith(("http://", "https://")):
        # (addressing scheme, network location, path, query, fragment identifier)
        urlparts = list(urlsplit(git_url))
        urlparts[1] = urlparts[1].split("@", 1)[-1]
        git_url = urlunsplit(urlparts)

    return git_url


KnownGitService = Literal["github", "gitlab", "sourcehut", "gitea", "gogs", "forgejo", "codeberg", "radicle"]
"""Known Git hosting services."""

_service_re = re.compile(rf"({'|'.join(KnownGitService.__args__)})")


def _get_git_known_service(git_remote_url: str) -> KnownGitService | None:
    if service := os.getenv("GRIFFE_GIT_SERVICE"):
        if service not in KnownGitService.__args__:
            return None
        return service  # ty:ignore[invalid-return-type]
    if match := _service_re.search(urlsplit(git_remote_url).netloc):
        return match.group(1)  # ty:ignore[invalid-return-type]
    return None


# For Radicle we use https://app.radicle.at/nodes/seed.radicle.at which I believe seeds everything?
# Line ranges do not seem to be supported.
# The rad remote is declared as such in .git/config:
#
# ```ini
# [remote "rad"]
# url = rad://z4M5XTPDD4Wh1sm8iPCenF85J3z8Z
# ```
_RADICLE_URL = "https://app.radicle.at/nodes/seed.radicle.at"


def _get_radicle_url(url_or_rid: str, commit_hash: str, filepath: str, lineno: int, endlineno: int) -> str:  # noqa: ARG001
    # This lets users override the full URL with `GRIFFE_GIT_REMOTE_URL=https://.../rad:...`.
    url = f"{_RADICLE_URL}/{url_or_rid.replace('//', '')}" if url_or_rid.startswith("rad://") else url_or_rid
    return f"{url}/tree/{commit_hash}/{filepath}#L{lineno}"


_service_to_url = {
    "github": lambda url, ch, fp, ln, eln: f"{url}/blob/{ch}/{fp}#L{ln}-L{eln}",
    "gitlab": lambda url, ch, fp, ln, eln: f"{url}/-/blob/{ch}/{fp}#L{ln}-L{eln}",
    # SourceHut does not seem to support line ranges.
    "sourcehut": lambda url, ch, fp, ln, eln: f"{url}/tree/{ch}/{fp}#L{ln}",
    # Cannot find a demo Gogs instance so not sure about this URL template.
    "gogs": lambda url, ch, fp, ln, eln: f"{url}/blob/{ch}/{fp}#L{ln}-L{eln}",
    "gitea": lambda url, ch, fp, ln, eln: f"{url}/src/commit/{ch}/{fp}#L{ln}-L{eln}",
    "codeberg": lambda url, ch, fp, ln, eln: f"{url}/src/commit/{ch}/{fp}#L{ln}-L{eln}",
    "forgejo": lambda url, ch, fp, ln, eln: f"{url}/src/commit/{ch}/{fp}#L{ln}-L{eln}",
    "radicle": _get_radicle_url,
}


def _get_source_link(
    service: KnownGitService,
    remote_url: str,
    commit_hash: str,
    filepath: str | Path,
    lineno: int,
    endlineno: int,
) -> str | None:
    if isinstance(filepath, Path):
        filepath = filepath.as_posix()
    return _service_to_url[service](remote_url, commit_hash, filepath, lineno, endlineno)


def _get_git_commit_hash(repo: str | Path = ".") -> str:
    if commit_hash := os.getenv("GRIFFE_GIT_COMMIT_HASH"):
        return commit_hash
    return _git("-C", str(repo), "rev-parse", "HEAD")


def _is_tracked(filepath: str | Path, repo: str | Path = ".") -> bool:
    return not _git("-C", str(repo), "check-ignore", str(filepath), check=False)


@dataclass
class GitInfo:
    """Information about a Git repository."""

    repository: Path
    """The path to the Git repository."""
    service: KnownGitService
    """The Git hosting service (used to build the right URLs)."""
    remote_url: str
    """The remote URL of the Git repository."""
    commit_hash: str
    """A commit hash (usually the current checked-out one)."""

    @classmethod
    def from_package(cls, package: Module) -> GitInfo | None:
        """Create a GitInfo instance from a Griffe package.

        Returns:
            The GitInfo instance, or None if unknown.
        """
        try:
            path = package.filepath[0] if isinstance(package.filepath, list) else package.filepath
        except BuiltinModuleError:
            return None
        try:
            repo = _get_repo_root(path)
            if not _is_tracked(path.relative_to(repo), repo):
                return None
            remote_url = _get_git_remote_url(repo)
            if not (service := _get_git_known_service(remote_url)):
                return None
            commit_hash = _get_git_commit_hash(repo)
        except (GitError, ValueError, OSError):
            # `ValueError` can happen if `path` is not relative to `repo`.
            # `OSError` is caught just to be safe.
            return None
        return cls(repository=repo, service=service, remote_url=remote_url, commit_hash=commit_hash)

    def get_source_link(self, filepath: str | Path, lineno: int, endlineno: int) -> str | None:
        """Get the source link for the file at the given line numbers.

        Returns:
            The source link, or None if unknown.
        """
        return _get_source_link(self.service, self.remote_url, self.commit_hash, filepath, lineno, endlineno)
