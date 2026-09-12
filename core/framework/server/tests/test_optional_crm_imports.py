"""Imports of the optional ``framework.crm`` package must be guarded.

The CRM package ships with the desktop runtime only — this repo does not
contain it, so ``from framework.crm ... import ...`` raises ImportError at
runtime. That is fine when the import sits inside a ``try`` block and the
caller degrades gracefully; it is a silent catastrophe when the import lives
inside a *larger* try whose except swallows unrelated work.

That exact failure shipped once: ``queen_orchestrator`` imported
``framework.crm.principal`` in the same try block that stamps the agent's
execution context. The ImportError skipped ``set_execution_context`` for
every queen session, so ``task_create`` (which resolves its session id from
that contextvar) soft-failed forever with "No session_id resolved for this
agent." — no traceback, no task list, ever.

This test walks every framework module and asserts each ``framework.crm``
import is *directly* wrapped: the innermost enclosing try must contain the
import and nothing load-bearing after it can be skipped, which we
approximate by requiring the import statement to be lexically inside SOME
try block whose body starts within 3 statements of the import. The precise
rule that matters — and the one reviewers should enforce — is worker.py's
pattern: an inner ``try/except ImportError`` around only the CRM lookup,
never around execution-context stamping.
"""

from __future__ import annotations

import ast
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]


def _crm_imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "framework.crm" or mod.startswith("framework.crm."):
                yield node
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "framework.crm" or alias.name.startswith("framework.crm."):
                    yield node


def _try_ranges(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            body_start = node.body[0].lineno
            body_end = max(getattr(stmt, "end_lineno", stmt.lineno) for stmt in node.body)
            yield node, body_start, body_end


def test_framework_crm_imports_are_guarded():
    offenders: list[str] = []
    for path in FRAMEWORK_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        tries = list(_try_ranges(tree))
        for imp in _crm_imports(tree):
            # The import must sit inside the BODY of some try (not its
            # handlers), and near the top of that body — a try that does a
            # page of unrelated work before/after the import is the swallowed
            # -context bug this file exists to prevent.
            directly_guarded = any(body_start <= imp.lineno <= body_end and imp.lineno - body_start <= 2 for _, body_start, body_end in tries)
            if not directly_guarded:
                rel = path.relative_to(FRAMEWORK_ROOT)
                offenders.append(f"{rel}:{imp.lineno}")
    assert not offenders, (
        "framework.crm is optional (desktop-only); these imports are not "
        "directly wrapped in their own try block and will either crash or — "
        "worse — silently abort unrelated work in an outer try:\n  " + "\n  ".join(offenders)
    )
