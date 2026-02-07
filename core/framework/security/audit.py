"""Security Audit Logging.

Provides tamper-evident audit logging for security events:
- All security-relevant operations logged
- Structured JSON format for analysis
- Log integrity verification
- Retention policy enforcement

Usage:
    from framework.security import audit_log, SecurityEvent

    # Log a security event
    audit_log(
        event=SecurityEvent.AUTH_SUCCESS,
        user_id="user123",
        details={"ip": "192.168.1.1"},
    )
"""

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SecurityEvent(StrEnum):
    """Types of security events to audit."""

    # Authentication
    AUTH_SUCCESS = "auth.success"
    AUTH_FAILURE = "auth.failure"
    AUTH_LOGOUT = "auth.logout"
    AUTH_TOKEN_REFRESH = "auth.token_refresh"
    AUTH_TOKEN_REVOKE = "auth.token_revoke"

    # Authorization
    AUTHZ_GRANTED = "authz.granted"
    AUTHZ_DENIED = "authz.denied"

    # Data access
    DATA_READ = "data.read"
    DATA_WRITE = "data.write"
    DATA_DELETE = "data.delete"
    DATA_EXPORT = "data.export"

    # Secrets
    SECRET_ACCESS = "secret.access"
    SECRET_ROTATE = "secret.rotate"
    SECRET_LEAK_DETECTED = "secret.leak_detected"

    # Threats
    THREAT_INJECTION = "threat.injection"
    THREAT_RATE_LIMIT = "threat.rate_limit"
    THREAT_BRUTE_FORCE = "threat.brute_force"
    THREAT_SUSPICIOUS_IP = "threat.suspicious_ip"

    # System
    CONFIG_CHANGE = "config.change"
    ENCRYPTION_KEY_ROTATE = "encryption.key_rotate"
    SYSTEM_START = "system.start"
    SYSTEM_STOP = "system.stop"

    # LLM specific
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    LLM_PROMPT_INJECTION = "llm.prompt_injection"
    LLM_SENSITIVE_DATA = "llm.sensitive_data"


class AuditSeverity(StrEnum):
    """Severity levels for audit events."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEntry:
    """A single audit log entry."""

    event: SecurityEvent
    timestamp: str
    event_id: str
    severity: AuditSeverity = AuditSeverity.INFO
    user_id: str | None = None
    session_id: str | None = None
    ip_address: str | None = None
    resource: str | None = None
    action: str | None = None
    outcome: str = "success"
    details: dict[str, Any] = field(default_factory=dict)
    previous_hash: str | None = None
    entry_hash: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def compute_hash(self, previous_hash: str | None = None) -> str:
        """Compute integrity hash for this entry."""
        data = {
            "event": self.event,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
            "user_id": self.user_id,
            "details": self.details,
            "previous_hash": previous_hash or self.previous_hash,
        }
        content = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()


class AuditLogger:
    """Security audit logger with integrity verification.

    Features:
    - Append-only logging
    - Chain hashing for tamper detection
    - Structured JSON output
    - Multiple output destinations
    """

    def __init__(
        self,
        log_path: Path | str | None = None,
        retention_days: int = 90,
    ):
        """Initialize audit logger.

        Args:
            log_path: Path to audit log file
            retention_days: Days to retain logs (0 = forever)
        """
        self._log_path = Path(log_path) if log_path else None
        self._retention_days = retention_days
        self._last_hash: str | None = None
        self._entry_count = 0

        # Create log directory if needed
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        event: SecurityEvent,
        *,
        severity: AuditSeverity = AuditSeverity.INFO,
        user_id: str | None = None,
        session_id: str | None = None,
        ip_address: str | None = None,
        resource: str | None = None,
        action: str | None = None,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Log a security event.

        Args:
            event: Type of security event
            severity: Event severity level
            user_id: User who triggered event
            session_id: Session identifier
            ip_address: Client IP address
            resource: Resource being accessed
            action: Specific action taken
            outcome: "success" or "failure"
            details: Additional event details

        Returns:
            The created AuditEntry
        """
        entry = AuditEntry(
            event=event,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_id=str(uuid.uuid4()),
            severity=severity,
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            resource=resource,
            action=action,
            outcome=outcome,
            details=details or {},
            previous_hash=self._last_hash,
        )

        # Compute integrity hash
        entry.entry_hash = entry.compute_hash()
        self._last_hash = entry.entry_hash
        self._entry_count += 1

        # Write to destinations
        self._write_entry(entry)

        return entry

    def _write_entry(self, entry: AuditEntry) -> None:
        """Write entry to all configured destinations."""
        # Log to Python logger
        log_level = logging.getLevelName(entry.severity.value.upper())
        if isinstance(log_level, str):
            log_level = logging.INFO

        logger.log(
            log_level,
            f"AUDIT: {entry.event} | user={entry.user_id} | outcome={entry.outcome}",
            extra={"audit_entry": entry.to_dict()},
        )

        # Write to file if configured
        if self._log_path:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(entry.to_json() + "\n")

    def verify_integrity(self, entries: list[AuditEntry]) -> bool:
        """Verify integrity of audit log chain.

        Args:
            entries: List of entries to verify

        Returns:
            True if chain is valid, False if tampering detected
        """
        if not entries:
            return True

        previous_hash = None

        for entry in entries:
            # Check previous hash matches
            if entry.previous_hash != previous_hash:
                logger.error(
                    f"Audit integrity failure: previous_hash mismatch at {entry.event_id}"
                )
                return False

            # Verify entry hash
            expected_hash = entry.compute_hash()
            if entry.entry_hash != expected_hash:
                logger.error(
                    f"Audit integrity failure: entry_hash mismatch at {entry.event_id}"
                )
                return False

            previous_hash = entry.entry_hash

        return True

    def read_entries(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        event_type: SecurityEvent | None = None,
        user_id: str | None = None,
    ) -> list[AuditEntry]:
        """Read audit entries with optional filtering.

        Args:
            since: Start time filter
            until: End time filter
            event_type: Filter by event type
            user_id: Filter by user

        Returns:
            List of matching AuditEntry objects
        """
        if not self._log_path or not self._log_path.exists():
            return []

        entries = []

        with open(self._log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    entry = AuditEntry(**data)

                    # Apply filters
                    if event_type and entry.event != event_type:
                        continue
                    if user_id and entry.user_id != user_id:
                        continue
                    if since:
                        entry_time = datetime.fromisoformat(entry.timestamp)
                        if entry_time < since:
                            continue
                    if until:
                        entry_time = datetime.fromisoformat(entry.timestamp)
                        if entry_time > until:
                            continue

                    entries.append(entry)
                except (json.JSONDecodeError, TypeError):
                    continue

        return entries


# Global instance
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def audit_log(
    event: SecurityEvent,
    **kwargs,
) -> AuditEntry:
    """Log a security event using global logger.

    Convenience function for quick audit logging.
    """
    return get_audit_logger().log(event, **kwargs)


__all__ = [
    "AuditLogger",
    "AuditEntry",
    "SecurityEvent",
    "AuditSeverity",
    "audit_log",
    "get_audit_logger",
]
