"""
Audit logging for security events and operational monitoring.

Provides comprehensive audit trail for:
- Security violations
- Runtime operations
- Resource access
- Configuration changes
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """Security severity levels."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EventType(Enum):
    """Types of security and operational events."""
    # Security events
    SECURITY_VIOLATION = "security_violation"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    CODE_INJECTION = "code_injection"
    PATH_TRAVERSAL = "path_traversal"
    XSS_ATTEMPT = "xss_attempt"
    
    # Runtime events
    RUNTIME_START = "runtime_start"
    RUNTIME_STOP = "runtime_stop"
    EXECUTION_TRIGGER = "execution_trigger"
    EXECUTION_COMPLETE = "execution_complete"
    EXECUTION_FAILED = "execution_failed"
    
    # Configuration events
    ENTRY_POINT_REGISTERED = "entry_point_registered"
    ENTRY_POINT_UNREGISTERED = "entry_point_unregistered"
    CONFIG_CHANGE = "config_change"
    
    # Resource events
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    CPU_LIMIT_EXCEEDED = "cpu_limit_exceeded"
    DISK_LIMIT_EXCEEDED = "disk_limit_exceeded"
    NETWORK_ACCESS = "network_access"
    
    # Credential events
    CREDENTIAL_ACCESS = "credential_access"
    CREDENTIAL_ROTATION = "credential_rotation"
    API_KEY_USAGE = "api_key_usage"


@dataclass
class SecurityEvent:
    """
    Represents a security or operational event.
    """
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    security_level: str = SecurityLevel.INFO.value
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    execution_id: Optional[str] = None
    entry_point_id: Optional[str] = None
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    source_ip: Optional[str] = None
    user_agent: Optional[str] = None
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityEvent":
        """Create event from dictionary."""
        return cls(**data)


class AuditLogger:
    """
    Comprehensive audit logger for security and operational events.
    
    Features:
    - Structured logging with JSON output
    - Multiple output destinations (file, syslog, external)
    - Event correlation and chaining
    - Automatic log rotation
    - Performance optimized batching
    """

    def __init__(
        self,
        log_file: Optional[Path] = None,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB
        backup_count: int = 5,
        batch_size: int = 100,
        batch_timeout: float = 5.0,
        enable_syslog: bool = False,
        external_webhook: Optional[str] = None,
    ):
        """
        Initialize audit logger.
        
        Args:
            log_file: Path to audit log file
            max_file_size: Maximum size before rotation
            backup_count: Number of backup files to keep
            batch_size: Number of events to batch together
            batch_timeout: Maximum time before flushing batch
            enable_syslog: Enable syslog logging
            external_webhook: URL for external audit service
        """
        self.log_file = log_file
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.enable_syslog = enable_syslog
        self.external_webhook = external_webhook

        # Event batching
        self._event_queue: List[SecurityEvent] = []
        self._last_flush = time.time()

        # Setup logging handlers
        self._setup_handlers()

        # Stats
        self._events_logged = 0
        self._events_dropped = 0
        self._start_time = time.time()

    def _setup_handlers(self) -> None:
        """Setup logging handlers for audit logs."""
        # Create audit logger
        self._logger = logging.getLogger("hive.audit")
        self._logger.setLevel(logging.INFO)
        
        # Avoid duplicate handlers
        if self._logger.handlers:
            return

        # Formatter for structured logging
        formatter = logging.Formatter(
            '%(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # File handler with rotation
        if self.log_file:
            from logging.handlers import RotatingFileHandler
            
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = RotatingFileHandler(
                self.log_file,
                maxBytes=self.max_file_size,
                backupCount=self.backup_count,
            )
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

        # Console handler for critical events
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.CRITICAL)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)

        # Syslog handler
        if self.enable_syslog:
            try:
                import logging.handlers
                syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
                syslog_handler.setFormatter(formatter)
                self._logger.addHandler(syslog_handler)
            except Exception as e:
                logger.warning(f"Failed to setup syslog handler: {e}")

    def log_event(self, event: SecurityEvent) -> None:
        """
        Log a security event.
        
        Args:
            event: Event to log
        """
        try:
            # Add to batch
            self._event_queue.append(event)
            self._events_logged += 1

            # Check if we should flush
            current_time = time.time()
            should_flush = (
                len(self._event_queue) >= self.batch_size or
                current_time - self._last_flush >= self.batch_timeout or
                event.security_level in [SecurityLevel.HIGH.value, SecurityLevel.CRITICAL.value]
            )

            if should_flush:
                self._flush_events()
                self._last_flush = current_time

        except Exception as e:
            logger.error(f"Failed to log audit event: {e}")
            self._events_dropped += 1

    def log_security_violation(
        self,
        violation_type: str,
        description: str,
        field_path: str = "",
        original_value: Any = None,
        severity: str = SecurityLevel.MEDIUM.value,
        **kwargs
    ) -> None:
        """Log a security violation."""
        event = SecurityEvent(
            event_type=EventType.SECURITY_VIOLATION.value,
            security_level=severity,
            description=description,
            details={
                "violation_type": violation_type,
                "field_path": field_path,
                "original_value": str(original_value) if original_value else None,
                **kwargs
            }
        )
        self.log_event(event)

    def log_runtime_start(self, stream_count: int, **kwargs) -> None:
        """Log runtime start event."""
        event = SecurityEvent(
            event_type=EventType.RUNTIME_START.value,
            security_level=SecurityLevel.INFO.value,
            description=f"Agent runtime started with {stream_count} streams",
            details={"stream_count": stream_count, **kwargs}
        )
        self.log_event(event)

    def log_runtime_stop(self, **kwargs) -> None:
        """Log runtime stop event."""
        event = SecurityEvent(
            event_type=EventType.RUNTIME_STOP.value,
            security_level=SecurityLevel.INFO.value,
            description="Agent runtime stopped",
            details=kwargs
        )
        self.log_event(event)

    def log_execution_trigger(
        self,
        entry_point_id: str,
        execution_id: str,
        correlation_id: Optional[str] = None,
        **kwargs
    ) -> None:
        """Log execution trigger event."""
        event = SecurityEvent(
            event_type=EventType.EXECUTION_TRIGGER.value,
            security_level=SecurityLevel.INFO.value,
            description=f"Execution triggered on entry point: {entry_point_id}",
            entry_point_id=entry_point_id,
            execution_id=execution_id,
            correlation_id=correlation_id,
            details=kwargs
        )
        self.log_event(event)

    def log_execution_complete(
        self,
        entry_point_id: str,
        execution_id: str,
        success: bool,
        duration_ms: int,
        **kwargs
    ) -> None:
        """Log execution completion."""
        event = SecurityEvent(
            event_type=EventType.EXECUTION_COMPLETE.value if success else EventType.EXECUTION_FAILED.value,
            security_level=SecurityLevel.INFO.value,
            description=f"Execution {'completed' if success else 'failed'} for {entry_point_id}",
            entry_point_id=entry_point_id,
            execution_id=execution_id,
            details={
                "success": success,
                "duration_ms": duration_ms,
                **kwargs
            }
        )
        self.log_event(event)

    def log_entry_point_registration(self, entry_point_id: str, entry_node: str, **kwargs) -> None:
        """Log entry point registration."""
        event = SecurityEvent(
            event_type=EventType.ENTRY_POINT_REGISTERED.value,
            security_level=SecurityLevel.INFO.value,
            description=f"Entry point registered: {entry_point_id} -> {entry_node}",
            entry_point_id=entry_point_id,
            details={"entry_node": entry_node, **kwargs}
        )
        self.log_event(event)

    def log_entry_point_unregistration(self, entry_point_id: str, **kwargs) -> None:
        """Log entry point unregistration."""
        event = SecurityEvent(
            event_type=EventType.ENTRY_POINT_UNREGISTERED.value,
            security_level=SecurityLevel.INFO.value,
            description=f"Entry point unregistered: {entry_point_id}",
            entry_point_id=entry_point_id,
            details=kwargs
        )
        self.log_event(event)

    def log_resource_exceeded(
        self,
        resource_type: str,
        current_value: float,
        limit: float,
        **kwargs
    ) -> None:
        """Log resource limit exceeded."""
        event = SecurityEvent(
            event_type=f"{resource_type.upper()}_LIMIT_EXCEEDED".upper(),
            security_level=SecurityLevel.HIGH.value,
            description=f"{resource_type} limit exceeded: {current_value} > {limit}",
            details={
                "resource_type": resource_type,
                "current_value": current_value,
                "limit": limit,
                **kwargs
            }
        )
        self.log_event(event)

    def _flush_events(self) -> None:
        """Flush queued events to log destinations."""
        if not self._event_queue:
            return

        try:
            # Log each event
            for event in self._event_queue:
                self._logger.info(event.to_json())

            # Send to external webhook if configured
            if self.external_webhook:
                self._send_to_external_service(self._event_queue)

            # Clear queue
            self._event_queue.clear()

        except Exception as e:
            logger.error(f"Failed to flush audit events: {e}")
            self._events_dropped += len(self._event_queue)
            self._event_queue.clear()

    def _send_to_external_service(self, events: List[SecurityEvent]) -> None:
        """Send events to external audit service."""
        if not self.external_webhook:
            return

        try:
            import httpx
            
            payload = {
                "events": [event.to_dict() for event in events],
                "timestamp": time.time(),
                "source": "hive_agent_runtime"
            }

            response = httpx.post(
                self.external_webhook,
                json=payload,
                timeout=10.0
            )
            response.raise_for_status()

        except Exception as e:
            logger.warning(f"Failed to send audit events to external service: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get audit logger statistics."""
        uptime = time.time() - self._start_time
        
        return {
            "events_logged": self._events_logged,
            "events_dropped": self._events_dropped,
            "uptime_seconds": uptime,
            "events_per_second": self._events_logged / uptime if uptime > 0 else 0,
            "queue_size": len(self._event_queue),
            "log_file": str(self.log_file) if self.log_file else None,
            "syslog_enabled": self.enable_syslog,
            "external_webhook": self.external_webhook,
        }

    def search_events(
        self,
        event_type: Optional[str] = None,
        security_level: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[SecurityEvent]:
        """
        Search events in log file.
        
        Args:
            event_type: Filter by event type
            security_level: Filter by security level
            start_time: Filter events after this timestamp
            end_time: Filter events before this timestamp
            limit: Maximum number of events to return
            
        Returns:
            List of matching events
        """
        if not self.log_file or not self.log_file.exists():
            return []

        events = []
        
        try:
            with open(self.log_file, 'r') as f:
                for line in f:
                    try:
                        event_data = json.loads(line.strip())
                        event = SecurityEvent.from_dict(event_data)
                        
                        # Apply filters
                        if event_type and event.event_type != event_type:
                            continue
                        if security_level and event.security_level != security_level:
                            continue
                        if start_time and event.timestamp < start_time:
                            continue
                        if end_time and event.timestamp > end_time:
                            continue
                            
                        events.append(event)
                        
                        if len(events) >= limit:
                            break
                            
                    except (json.JSONDecodeError, TypeError):
                        continue
                        
        except Exception as e:
            logger.error(f"Error searching audit events: {e}")
            
        return events

    def cleanup(self) -> None:
        """Cleanup resources and flush remaining events."""
        self._flush_events()
        
        # Close handlers
        for handler in self._logger.handlers[:]:
            handler.close()
            self._logger.removeHandler(handler)