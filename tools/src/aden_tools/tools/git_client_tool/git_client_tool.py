"""
Git Client Tool
===============

Agent-safe Git operations for repository introspection and controlled mutation.

Capabilities:
- Status inspection
- Diff inspection (with truncation)
- Commit history (structured)
- Safe branch checkout

Design goals:
- Non-interactive
- Timeout-protected
- Agent-readable structured outputs
- Minimal blast radius
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Union

from fastmcp import FastMCP


# -----------------------------
# Configuration
# -----------------------------

GIT_TIMEOUT_SECONDS = 5
MAX_OUTPUT_LINES = 500


# -----------------------------
# Tool Registration
# -----------------------------

def register_tools(mcp: FastMCP) -> None:
    """Register Git client tools with the MCP server."""
    tools = {}

    # -------------------------
    # Core Git Runner
    # -------------------------

    def run_git(
        args: List[str],
        cwd: Union[str, Path] = ".",
    ) -> Dict[str, Any]:
        """
        Execute a git command safely.

        Returns a structured dict suitable for LLM consumption.
        """
        try:
            env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

            result = subprocess.run(
                ["git"] + args,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                env=env,
                timeout=GIT_TIMEOUT_SECONDS,
                check=False,
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode != 0:
                return {
                    "ok": False,
                    "error": "GIT_COMMAND_FAILED",
                    "command": "git " + " ".join(args),
                    "exit_code": result.returncode,
                    "stderr": stderr,
                }

            return {
                "ok": True,
                "stdout": stdout,
                "stderr": stderr,
            }

        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": "GIT_TIMEOUT",
                "message": f"Git command exceeded {GIT_TIMEOUT_SECONDS}s timeout",
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "error": "GIT_NOT_INSTALLED",
                "message": "Git executable not found in PATH",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": "UNEXPECTED_ERROR",
                "message": str(e),
            }

    # -------------------------
    # Repo Validation
    # -------------------------

    def ensure_git_repo(repo_path: str) -> Union[Path, Dict[str, Any]]:
        """
        Verify that repo_path is inside a git work tree.
        """
        path = Path(repo_path).resolve()
        result = run_git(
            ["rev-parse", "--is-inside-work-tree"],
            cwd=path,
        )

        if not result.get("ok"):
            return {
                "ok": False,
                "error": "NOT_A_GIT_REPO",
                "path": str(path),
            }

        return path

    # -------------------------
    # Tools
    # -------------------------

    @mcp.tool()
    def git_status(repo_path: str = ".") -> Dict[str, Any]:
        """
        Get current repository status (short + branch).

        Returns modified, staged, and untracked files.
        """
        repo = ensure_git_repo(repo_path)
        if isinstance(repo, dict):
            return repo

        return run_git(
            ["status", "--short", "--branch"],
            cwd=repo,
        )
    
    tools["git_status"] = git_status

    @mcp.tool()
    def git_diff(
        target: str | None = None,
        staged: bool = False,
        repo_path: str = ".",
    ) -> Dict[str, Any]:
        """
        Show diffs in the working tree or index.

        Output is truncated to avoid context explosion.
        """
        repo = ensure_git_repo(repo_path)
        if isinstance(repo, dict):
            return repo

        args = ["diff"]
        if staged:
            args.append("--cached")
        if target:
            args.append(target)

        result = run_git(args, cwd=repo)
        if not result.get("ok"):
            return result

        lines = result["stdout"].splitlines()
        truncated = len(lines) > MAX_OUTPUT_LINES

        return {
            "ok": True,
            "diff": "\n".join(lines[:MAX_OUTPUT_LINES]),
            "total_lines": len(lines),
            "truncated": truncated,
        }
    tools["git_diff"] = git_diff

    @mcp.tool()
    def git_log(
        limit: int = 10,
        file_path: str | None = None,
        repo_path: str = ".",
    ) -> Dict[str, Any]:
        """
        Retrieve structured commit history.
        """
        repo = ensure_git_repo(repo_path)
        if isinstance(repo, dict):
            return repo

        fmt = "%h|%an|%ar|%s"
        args = ["log", "-n", str(limit), f"--format={fmt}"]

        if file_path:
            args.append(file_path)

        result = run_git(args, cwd=repo)
        if not result.get("ok"):
            return result

        commits = []
        for line in result["stdout"].splitlines():
            try:
                commit_hash, author, date, message = line.split("|", 3)
                commits.append({
                    "hash": commit_hash,
                    "author": author,
                    "date": date,
                    "message": message,
                })
            except ValueError:
                continue

        return {
            "ok": True,
            "commits": commits,
            "count": len(commits),
        }

    @mcp.tool()
    def git_checkout(
        branch: str,
        create_new: bool = False,
        repo_path: str = ".",
    ) -> Dict[str, Any]:
        """
        Safely checkout a branch.

        Refuses to run if working tree is dirty.
        """
        repo = ensure_git_repo(repo_path)
        if isinstance(repo, dict):
            return repo

        status = run_git(["status", "--porcelain"], cwd=repo)
        if status.get("ok") and status.get("stdout"):
            return {
                "ok": False,
                "error": "DIRTY_WORKING_TREE",
                "message": "Uncommitted changes present; checkout aborted",
            }

        args = ["checkout"]
        if create_new:
            args.append("-b")
        args.append(branch)

        return run_git(args, cwd=repo)

    tools["git_log"] = git_log
    tools["git_checkout"] = git_checkout    
    return tools