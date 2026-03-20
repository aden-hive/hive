"""Structured error codes and diagnostics for the Hive skill system.

Implements DX-1 (structured error codes) and DX-2 (what/why/fix format)
from the skill system PRD §7.5.
"""

from __future__ import annotations

import logging
from enum import Enum


class SkillErrorCode(Enum):
    """Standardized error codes for skill system operations (DX-1)."""

    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"
    SKILL_PARSE_ERROR = "SKILL_PARSE_ERROR"
    SKILL_ACTIVATION_FAILED = "SKILL_ACTIVATION_FAILED"
    SKILL_MISSING_DESCRIPTION = "SKILL_MISSING_DESCRIPTION"
    SKILL_YAML_FIXUP = "SKILL_YAML_FIXUP"
    SKILL_NAME_MISMATCH = "SKILL_NAME_MISMATCH"
    SKILL_COLLISION = "SKILL_COLLISION"


class SkillError(Exception):
    """Structured exception for skill system errors (DX-2).

    Raised in strict validation paths. Also used as the base
    format contract for log_skill_error() log messages.
    """

    def __init__(self, code: SkillErrorCode, what: str, why: str, fix: str):
        self.code = code
        self.what = what
        self.why = why
        self.fix = fix
        self.message = (
            f"[{self.code.value}]\nWhat failed: {self.what}\nWhy: {self.why}\nFix: {self.fix}"
        )
        super().__init__(self.message)


def log_skill_error(
    logger: logging.Logger,
    level: str,
    code: SkillErrorCode,
    what: str,
    why: str,
    fix: str,
) -> None:
    """Emit a structured skill diagnostic log with consistent format (DX-2).

    Args:
        logger: The module logger to emit to.
        level: Log level string — 'error', 'warning', or 'info'.
        code: Structured error code.
        what: What failed (specific skill name and path).
        why: Root cause.
        fix: Concrete next step for the developer.
    """
    msg = f"[{code.value}] What failed: {what} | Why: {why} | Fix: {fix}"
    getattr(logger, level)(
        msg,
        extra={
            "skill_error_code": code.value,
            "what": what,
            "why": why,
            "fix": fix,
        },
    )
